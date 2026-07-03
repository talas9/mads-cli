"""mads adset command group — Meta Marketing API Ad Set management.

KB reference: kb/marketing-api.md (relative to mads-cli root)
Endpoints: POST/GET act_{ad_account_id}/adsets, GET {campaign_id}/adsets edge,
GET/POST/DELETE /{adset_id}
Uses mads_lib.http.graph_request() for every call — see campaigns.py's module
docstring for the overall shape/logging convention this file follows.
"""
import json

import click

from .config import AD_ACCOUNT_ID
from .db import get_db
from .http import graph_request
from .output import flatten, print_error, print_json, print_table
from .timeutil import now_local

# KB § Enums Reference — `billing_event` (AdSet).
_BILLING_EVENTS = (
    "APP_INSTALLS", "CLICKS", "IMPRESSIONS", "LINK_CLICKS", "LISTING_INTERACTION",
    "NONE", "OFFER_CLAIMS", "PAGE_LIKES", "POST_ENGAGEMENT", "PURCHASE", "THRUPLAY",
)

# KB § Enums Reference — `optimization_goal` (AdSet).
_OPTIMIZATION_GOALS = (
    "NONE", "APP_INSTALLS", "AD_RECALL_LIFT", "ENGAGED_USERS", "EVENT_RESPONSES", "IMPRESSIONS",
    "LEAD_GENERATION", "QUALITY_LEAD", "LINK_CLICKS", "OFFSITE_CONVERSIONS", "PAGE_LIKES",
    "POST_ENGAGEMENT", "QUALITY_CALL", "REACH", "LANDING_PAGE_VIEWS", "VISIT_INSTAGRAM_PROFILE",
    "ENGAGED_PAGE_VIEWS", "VALUE", "THRUPLAY", "DERIVED_EVENTS",
    "APP_INSTALLS_AND_OFFSITE_CONVERSIONS", "CONVERSATIONS", "IN_APP_VALUE",
    "MESSAGING_PURCHASE_CONVERSION", "MESSAGING_DEEP_CONVERSATION_AND_FOLLOW", "SUBSCRIBERS",
    "REMINDERS_SET", "MEANINGFUL_CALL_ATTEMPT", "PROFILE_VISIT", "PROFILE_AND_PAGE_ENGAGEMENT",
    "ADVERTISER_SILOED_VALUE", "AUTOMATIC_OBJECTIVE", "MESSAGING_APPOINTMENT_CONVERSION",
)

# KB § Enums Reference — `bid_strategy` (Campaign and AdSet — same 4 values).
_BID_STRATEGIES = (
    "LOWEST_COST_WITHOUT_CAP", "LOWEST_COST_WITH_BID_CAP", "COST_CAP", "LOWEST_COST_WITH_MIN_ROAS",
)

# KB § Enums Reference — Status enums by resource: AdSet `status`/
# `configured_status` accepts these 4 values (effective_status adds
# CAMPAIGN_PAUSED/IN_PROCESS/WITH_ISSUES, but those are read-only/derived).
_STATUS_CHOICES = ("ACTIVE", "PAUSED", "ARCHIVED", "DELETED")

_DEFAULT_LIST_FIELDS = (
    "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,"
    "billing_event,optimization_goal,bid_strategy,bid_amount,start_time,end_time"
)


@click.group()
def adset():
    """Ad Set management commands."""
    pass


# ── Helpers (duplicated per resource-group module — see campaigns.py) ───────


def _act_id(ad_account_id=None):
    aid = (ad_account_id or AD_ACCOUNT_ID or "").strip()
    if not aid:
        return None
    return aid if aid.startswith("act_") else f"act_{aid}"


def _require_act_id(ad_account_id, as_json):
    act = _act_id(ad_account_id)
    if not act:
        raise SystemExit(print_error(
            "META_AD_ACCOUNT_ID is not set (or pass --ad-account-id).",
            code="VALIDATION", as_json=as_json,
        ))
    return act


def _confirm_and_log(action, details, dry_run=False, yes=False):
    if dry_run:
        click.secho(f"  DRY RUN: {action} — {details}", fg="yellow")
        return False
    if not yes:
        click.confirm(f"  Execute: {action}?", abort=True)
    return True


def _auto_log(action, details, campaign_name="", campaign_id=""):
    """Best-effort changelog write; never raises (mirrors mads_lib.cli._auto_log).

    Note: `get_db()` raises `SystemExit(1)` (not a plain `Exception`) when
    MADS_DB_PATH doesn't exist yet — caught explicitly here alongside
    `Exception` so a missing/not-yet-initialized DB never aborts an otherwise
    successful mutation.
    """
    try:
        conn = get_db()
        ts = now_local()
        raw = {
            "timestamp": ts, "action": action, "details": details,
            "campaign": campaign_name, "campaign_id": campaign_id, "agent": "mads-cli",
        }
        conn.execute(
            "INSERT INTO changelog (timestamp, action, campaign, campaign_id, details, "
            "reason, agent, snapshot_ref, script, raw_json, platform) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, action, campaign_name, campaign_id, details, "", "mads-cli", "", "", json.dumps(raw), "meta_ads"),
        )
        conn.commit()
        conn.close()
    except (Exception, SystemExit):
        pass


def _minor_units(amount):
    """Convert a major-currency-unit float to Meta's minor-unit budget string.

    See campaigns.py's `_minor_units` docstring — same (unverified for AED)
    ×100 assumption, same `--minor-units` escape hatch on the calling command.
    """
    return str(int(round(amount * 100)))


def _build_targeting(countries, age_min, age_max, publisher_platforms=None, instagram_positions=None):
    """Build a minimal `targeting` object from convenience flags.

    KB § Targeting Reference: `geo_locations` (or an audience-based
    alternative) is required. This only covers the common
    countries/age_min/age_max/placements case — pass --targeting with a raw
    JSON object for anything richer (flexible_spec interests/behaviors, etc).
    """
    targeting = {}
    if countries:
        targeting["geo_locations"] = {"countries": [c.strip().upper() for c in countries.split(",")]}
    if age_min is not None:
        targeting["age_min"] = age_min
    if age_max is not None:
        targeting["age_max"] = age_max
    if publisher_platforms:
        targeting["publisher_platforms"] = [p.strip().lower() for p in publisher_platforms.split(",")]
    if instagram_positions:
        targeting["instagram_positions"] = [p.strip().lower() for p in instagram_positions.split(",")]
    return targeting


# ── Commands ─────────────────────────────────────────────────


@adset.command("list")
@click.option("--campaign-id", default=None,
              help="List ad sets under this campaign (uses the campaign's `adsets` edge). "
                   "Omit to list across the whole ad account instead.")
@click.option("--ad-account-id", default=None)
@click.option("--fields", default=_DEFAULT_LIST_FIELDS)
@click.option("--all", "include_deleted", is_flag=True, help="Include DELETED/ARCHIVED ad sets (excluded by default).")
@click.option("--limit", "-l", type=int, default=100)
@click.option("--json", "as_json", is_flag=True)
def adset_list(campaign_id, ad_account_id, fields, include_deleted, limit, as_json):
    """List ad sets (optionally scoped to one campaign).

    KB: kb/marketing-api.md § 2. Create Ad Set / Field Reference — Ad Set,
    `adsets` edge.
    """
    params = {"fields": fields, "limit": limit}
    if not include_deleted:
        params["filtering"] = json.dumps(
            [{"field": "effective_status", "operator": "NOT_IN", "value": ["DELETED"]}]
        )
    if campaign_id:
        path = f"{campaign_id}/adsets"
    else:
        act = _require_act_id(ad_account_id, as_json)
        path = f"{act}/adsets"
    result = graph_request("GET", path, params=params, as_json=as_json)
    rows = result.get("data", []) if isinstance(result, dict) else []
    if as_json:
        print_json(result)
        return
    if not rows:
        click.echo("  (no ad sets)")
        return
    print_table([flatten(r) for r in rows])
    click.echo(f"\n  {len(rows)} ad set(s)")


@adset.command("create")
@click.argument("name")
@click.option("--campaign-id", required=True)
@click.option("--billing-event", type=click.Choice(_BILLING_EVENTS), default="IMPRESSIONS",
              help="What you're charged for — IMPRESSIONS is the KB-documented common default regardless of optimization_goal.")
@click.option("--optimization-goal", type=click.Choice(_OPTIMIZATION_GOALS), required=True)
@click.option("--bid-strategy", type=click.Choice(_BID_STRATEGIES), default="LOWEST_COST_WITHOUT_CAP")
@click.option("--bid-amount", type=int, default=None,
              help="Bid cap/target in Meta minor units — required for *_WITH_BID_CAP / COST_CAP strategies (KB: unverified exact per-strategy requirement).")
@click.option("--daily-budget", type=float, default=None,
              help="Major currency units. Omit if the parent Campaign uses Campaign Budget Optimization (CBO).")
@click.option("--lifetime-budget", type=float, default=None, help="Major currency units.")
@click.option("--minor-units", is_flag=True, help="Treat --daily-budget/--lifetime-budget as already-converted Meta minor-unit integers.")
@click.option("--status", type=click.Choice(["ACTIVE", "PAUSED"], case_sensitive=False), default="PAUSED")
@click.option("--targeting", default=None, help="Raw JSON targeting object — overrides --countries/--age-min/--age-max.")
@click.option("--countries", default=None, help="Comma-separated ISO country codes for targeting.geo_locations.countries.")
@click.option("--age-min", type=int, default=None, help="KB floor: 13 (many objectives default the practical floor to 18).")
@click.option("--age-max", type=int, default=None, help="KB ceiling: 65.")
@click.option("--publisher-platforms", default=None, help="Comma-separated platforms for targeting.publisher_platforms, e.g. facebook,instagram.")
@click.option("--instagram-positions", default=None, help="Comma-separated placements for targeting.instagram_positions, e.g. stream,story,reels.")
@click.option("--pixel-id", default=None, help="Sets promoted_object.pixel_id for conversion-based optimization.")
@click.option("--custom-event-type", default=None,
              help="e.g. PURCHASE, LEAD, COMPLETE_REGISTRATION — paired with --pixel-id (full event enum not in the KB; pass the literal Meta event name).")
@click.option("--ad-account-id", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def adset_create(name, campaign_id, billing_event, optimization_goal, bid_strategy, bid_amount,
                  daily_budget, lifetime_budget, minor_units, status, targeting, countries,
                  age_min, age_max, publisher_platforms, instagram_positions, pixel_id,
                  custom_event_type, ad_account_id, dry_run, yes, as_json):
    """Create an ad set under an existing campaign.

    KB: kb/marketing-api.md § 2. Create Ad Set — POST act_{ad_account_id}/adsets
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    if daily_budget is not None and lifetime_budget is not None:
        raise SystemExit(print_error(
            "--daily-budget and --lifetime-budget are mutually exclusive.",
            code="VALIDATION", as_json=as_json,
        ))

    if targeting:
        try:
            targeting_obj = json.loads(targeting)
        except json.JSONDecodeError as e:
            raise SystemExit(print_error(f"--targeting is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
    else:
        targeting_obj = _build_targeting(countries, age_min, age_max, publisher_platforms, instagram_positions)
        if not targeting_obj.get("geo_locations"):
            raise SystemExit(print_error(
                "targeting.geo_locations is required — pass --countries or a full --targeting JSON object.",
                code="VALIDATION", as_json=as_json,
            ))

    act = _require_act_id(ad_account_id, as_json)
    body = {
        "name": name,
        "campaign_id": campaign_id,
        "billing_event": billing_event,
        "optimization_goal": optimization_goal,
        "bid_strategy": bid_strategy,
        "targeting": targeting_obj,
        "status": status.upper(),
    }
    if bid_amount is not None:
        body["bid_amount"] = bid_amount
    if daily_budget is not None:
        body["daily_budget"] = str(int(daily_budget)) if minor_units else _minor_units(daily_budget)
    if lifetime_budget is not None:
        body["lifetime_budget"] = str(int(lifetime_budget)) if minor_units else _minor_units(lifetime_budget)
    if pixel_id:
        promoted = {"pixel_id": pixel_id}
        if custom_event_type:
            promoted["custom_event_type"] = custom_event_type.upper()
        body["promoted_object"] = promoted

    if not _confirm_and_log(f"create ad set '{name}' in campaign {campaign_id}", json.dumps(body), dry_run, yes):
        return

    result = graph_request("POST", f"{act}/adsets", json_body=body, as_json=as_json)
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("adset_create", f"'{name}' in campaign {campaign_id}", campaign_id=campaign_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created ad set '{name}' → id {new_id or '?'}", fg="green")


@adset.command("status")
@click.argument("adset_id")
@click.argument("status", type=click.Choice(_STATUS_CHOICES, case_sensitive=False))
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def adset_status(adset_id, status, dry_run, yes, as_json):
    """Change an ad set's status (ACTIVE / PAUSED / ARCHIVED / DELETED).

    KB: kb/marketing-api.md § 6. Update (partial) — POST /{node_id}
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    status = status.upper()
    if not _confirm_and_log(f"ad set {adset_id} → {status}", "status change", dry_run, yes):
        return
    result = graph_request("POST", adset_id, json_body={"status": status}, as_json=as_json)
    _auto_log("adset_status", f"{adset_id} → {status}")
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Ad set {adset_id} → {status}", fg="green")


@adset.command("budget")
@click.argument("adset_id")
@click.argument("amount", type=float)
@click.option("--lifetime", is_flag=True, help="Set lifetime_budget instead of daily_budget.")
@click.option("--minor-units", is_flag=True, help="Treat AMOUNT as an already-converted Meta minor-unit integer.")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def adset_budget(adset_id, amount, lifetime, minor_units, dry_run, yes, as_json):
    """Change an ad set's daily or lifetime budget (Ad Set Budget Optimization / ABO mode).

    KB: kb/marketing-api.md § 6. Update (partial); Gotcha #5 — do not also set a
    budget here if the parent Campaign uses Campaign Budget Optimization (CBO).
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    field = "lifetime_budget" if lifetime else "daily_budget"
    value = str(int(amount)) if minor_units else _minor_units(amount)
    if not _confirm_and_log(f"ad set {adset_id} {field} → {amount}", "budget change", dry_run, yes):
        return
    result = graph_request("POST", adset_id, json_body={field: value}, as_json=as_json)
    _auto_log("adset_budget", f"{adset_id} {field} → {amount}")
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Ad set {adset_id} {field} → {amount}", fg="green")


@adset.command("delete")
@click.argument("adset_id")
@click.option("--hard", is_flag=True,
              help="Issue a true HTTP DELETE instead of the safer status=DELETED soft-delete "
                   "(KB § 7: only independently confirmed reliable on AdCreative — use with caution here).")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def adset_delete(adset_id, hard, dry_run, yes, as_json):
    """Delete an ad set (soft-delete via status=DELETED by default).

    KB: kb/marketing-api.md § 7. Remove / Delete a node.
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    action = f"{'HARD ' if hard else ''}delete ad set {adset_id}"
    if not _confirm_and_log(action, "delete", dry_run, yes):
        return
    if hard:
        result = graph_request("DELETE", adset_id, as_json=as_json)
    else:
        result = graph_request("POST", adset_id, json_body={"status": "DELETED"}, as_json=as_json)
    _auto_log("adset_delete", f"{adset_id} ({'hard' if hard else 'soft'})")
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Deleted ad set {adset_id}", fg="green")
