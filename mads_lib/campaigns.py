"""mads campaign command group — Meta Marketing API Campaign management.

KB reference: kb/marketing-api.md (relative to mads-cli root)
Endpoints: POST/GET act_{ad_account_id}/campaigns, GET/POST/DELETE /{campaign_id}
Uses mads_lib.http.graph_request() for every call (no separate REST client
module — this file *is* the Campaign resource layer, unlike gads-cli's split
between ads.py/gbp.py clients and cli.py commands).

Convention mirrors gads-cli's campaign/adgroup/ad/asset command groups
(gads_lib/cli.py): list/create/status/budget/delete, --dry-run/--yes confirm
gate, --json machine output, and a best-effort changelog write after every
mutation (snapshot-before-mutate discipline — take a `mads snapshot` before
running any of the mutating commands below).
"""
import json

import click

from .config import AD_ACCOUNT_ID
from .db import get_db
from .http import graph_request
from .output import flatten, print_error, print_json, print_table
from .timeutil import now_local

# KB § Enums Reference — Campaign `objective`. Restricted to the current
# OUTCOME_* set only: the KB notes legacy objectives are progressively
# create-restricted (e.g. Advantage+ Shopping/App campaign creation is
# blocked entirely as of v25.0) and that Meta steers all new campaigns
# toward OUTCOME_*.
_OBJECTIVES = (
    "OUTCOME_APP_PROMOTION", "OUTCOME_AWARENESS", "OUTCOME_ENGAGEMENT",
    "OUTCOME_LEADS", "OUTCOME_SALES", "OUTCOME_TRAFFIC",
)

# KB § Enums Reference — `special_ad_categories` (Campaign, Ad).
_SPECIAL_AD_CATEGORIES = (
    "NONE", "EMPLOYMENT", "HOUSING", "CREDIT", "ISSUES_ELECTIONS_POLITICS",
    "ONLINE_GAMBLING_AND_GAMING", "FINANCIAL_PRODUCTS_SERVICES",
)

# KB § Enums Reference — `bid_strategy` (Campaign and AdSet — same 4 values).
_BID_STRATEGIES = (
    "LOWEST_COST_WITHOUT_CAP", "LOWEST_COST_WITH_BID_CAP", "COST_CAP", "LOWEST_COST_WITH_MIN_ROAS",
)

_BUYING_TYPES = ("AUCTION", "RESERVED")

# KB § Enums Reference — Status enums by resource: Campaign `status`/
# `configured_status` accepts these 4 values (effective_status has more,
# but those are read-only/derived, not settable).
_STATUS_CHOICES = ("ACTIVE", "PAUSED", "ARCHIVED", "DELETED")

_DEFAULT_LIST_FIELDS = (
    "id,name,status,effective_status,objective,daily_budget,lifetime_budget,"
    "special_ad_categories,buying_type,bid_strategy,created_time,updated_time"
)


@click.group()
def campaign():
    """Campaign management commands."""
    pass


# ── Helpers (small, intentionally duplicated per resource-group module —
# same pattern mads_lib/cli.py already uses when mirroring gads_lib/cli.py) ──


def _act_id(ad_account_id=None):
    """Build the `act_`-prefixed ad-account id required on account-scoped endpoints.

    KB § Base URL / Gotcha #2: a bare numeric ad-account id 404s — the `act_`
    prefix is mandatory.
    """
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
    """Convert a major-currency-unit float (e.g. AED) to Meta's minor-unit budget string.

    KB § 2 (Create Ad Set) flags this as an (unverified) nuance: budgets are in
    the smallest currency unit for most currencies, but the exact AED
    minor-unit convention was not re-confirmed from a rendered docs page in
    the KB's research session. This assumes the standard 2-decimal-currency
    convention (×100) — verify empirically with a small test budget before
    relying on this for real money-moving calls. Use `--minor-units` on the
    calling command to bypass this conversion and pass the raw Meta-side
    integer yourself.
    """
    return str(int(round(amount * 100)))


# ── Commands ─────────────────────────────────────────────────


@campaign.command("list")
@click.option("--ad-account-id", default=None, help="Override META_AD_ACCOUNT_ID (bare numeric id or act_-prefixed).")
@click.option("--fields", default=_DEFAULT_LIST_FIELDS, help="Comma-separated Graph API fields to request.")
@click.option("--all", "include_deleted", is_flag=True, help="Include DELETED/ARCHIVED campaigns (excluded by default).")
@click.option("--limit", "-l", type=int, default=100, help="Max campaigns per page (Graph API `limit` param — not auto-paginated).")
@click.option("--json", "as_json", is_flag=True)
def campaign_list(ad_account_id, fields, include_deleted, limit, as_json):
    """List campaigns on the ad account.

    KB: kb/marketing-api.md § 5. Read Fields — GET act_{ad_account_id}/campaigns
    """
    act = _require_act_id(ad_account_id, as_json)
    params = {"fields": fields, "limit": limit}
    if not include_deleted:
        params["filtering"] = json.dumps(
            [{"field": "effective_status", "operator": "NOT_IN", "value": ["DELETED"]}]
        )
    result = graph_request("GET", f"{act}/campaigns", params=params, as_json=as_json)
    rows = result.get("data", []) if isinstance(result, dict) else []
    if as_json:
        print_json(result)
        return
    if not rows:
        click.echo("  (no campaigns)")
        return
    print_table([flatten(r) for r in rows])
    click.echo(f"\n  {len(rows)} campaign(s)")


@campaign.command("create")
@click.argument("name")
@click.option("--objective", type=click.Choice(_OBJECTIVES), required=True,
              help="Campaign objective (OUTCOME_* set only — legacy objectives are create-restricted as of v25.0).")
@click.option("--status", type=click.Choice(["ACTIVE", "PAUSED"], case_sensitive=False), default="PAUSED",
              help="Only ACTIVE/PAUSED are valid at creation time. Defaults PAUSED (review before going live).")
@click.option("--special-ad-categories", default="NONE",
              help=f"Comma-separated categories from {_SPECIAL_AD_CATEGORIES}, or NONE (default). Required by Meta on every campaign.")
@click.option("--buying-type", type=click.Choice(_BUYING_TYPES), default="AUCTION")
@click.option("--bid-strategy", type=click.Choice(_BID_STRATEGIES), default=None,
              help="Campaign-level bid strategy — only meaningful under Campaign Budget Optimization (CBO).")
@click.option("--daily-budget", type=float, default=None,
              help="Daily budget in major currency units (e.g. AED). Mutually exclusive with --lifetime-budget.")
@click.option("--lifetime-budget", type=float, default=None,
              help="Lifetime budget in major currency units. Mutually exclusive with --daily-budget.")
@click.option("--minor-units", is_flag=True,
              help="Treat --daily-budget/--lifetime-budget/--spend-cap as already-converted Meta minor-unit integers (skip ×100 conversion).")
@click.option("--spend-cap", type=float, default=None, help="Spend cap in major currency units; Meta minimum is $100-equivalent.")
@click.option("--ad-account-id", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def campaign_create(name, objective, status, special_ad_categories, buying_type, bid_strategy,
                     daily_budget, lifetime_budget, minor_units, spend_cap, ad_account_id,
                     dry_run, yes, as_json):
    """Create a campaign (left PAUSED by default until reviewed).

    KB: kb/marketing-api.md § 1. Create Campaign — POST act_{ad_account_id}/campaigns
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    act = _require_act_id(ad_account_id, as_json)
    if daily_budget is not None and lifetime_budget is not None:
        raise SystemExit(print_error(
            "--daily-budget and --lifetime-budget are mutually exclusive.",
            code="VALIDATION", as_json=as_json,
        ))

    cats_upper = special_ad_categories.strip().upper()
    categories = [] if cats_upper in ("", "NONE") else [c.strip().upper() for c in special_ad_categories.split(",")]

    body = {
        "name": name,
        "objective": objective,
        "status": status.upper(),
        # KB Gotcha #1: mandatory on every Campaign create call, even if empty.
        "special_ad_categories": categories,
        "buying_type": buying_type,
    }
    if bid_strategy:
        body["bid_strategy"] = bid_strategy
    if daily_budget is not None:
        body["daily_budget"] = str(int(daily_budget)) if minor_units else _minor_units(daily_budget)
    if lifetime_budget is not None:
        body["lifetime_budget"] = str(int(lifetime_budget)) if minor_units else _minor_units(lifetime_budget)
    if spend_cap is not None:
        body["spend_cap"] = str(int(spend_cap)) if minor_units else _minor_units(spend_cap)

    if not _confirm_and_log(f"create campaign '{name}' [{objective}]", json.dumps(body), dry_run, yes):
        return

    result = graph_request("POST", f"{act}/campaigns", json_body=body, as_json=as_json)
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("campaign_create", f"'{name}' [{objective}] status={status.upper()}", campaign_name=name, campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created campaign '{name}' → id {new_id or '?'}", fg="green")


@campaign.command("status")
@click.argument("campaign_id")
@click.argument("status", type=click.Choice(_STATUS_CHOICES, case_sensitive=False))
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def campaign_status(campaign_id, status, dry_run, yes, as_json):
    """Change a campaign's status (ACTIVE / PAUSED / ARCHIVED / DELETED).

    KB: kb/marketing-api.md § 6. Update (partial) — POST /{node_id}
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    status = status.upper()
    if not _confirm_and_log(f"campaign {campaign_id} → {status}", "status change", dry_run, yes):
        return
    result = graph_request("POST", campaign_id, json_body={"status": status}, as_json=as_json)
    _auto_log("campaign_status", f"{campaign_id} → {status}", campaign_id=campaign_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Campaign {campaign_id} → {status}", fg="green")


@campaign.command("budget")
@click.argument("campaign_id")
@click.argument("amount", type=float)
@click.option("--lifetime", is_flag=True, help="Set lifetime_budget instead of daily_budget.")
@click.option("--minor-units", is_flag=True, help="Treat AMOUNT as an already-converted Meta minor-unit integer.")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def campaign_budget(campaign_id, amount, lifetime, minor_units, dry_run, yes, as_json):
    """Change a campaign's daily or lifetime budget.

    KB: kb/marketing-api.md § 6. Update (partial); Campaign field `daily_budget`/
    `lifetime_budget` (Gotcha #5: mutually exclusive on the same object — a
    CBO campaign holds the budget and its child ad sets should not also set one).
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    field = "lifetime_budget" if lifetime else "daily_budget"
    value = str(int(amount)) if minor_units else _minor_units(amount)
    if not _confirm_and_log(f"campaign {campaign_id} {field} → {amount}", "budget change", dry_run, yes):
        return
    result = graph_request("POST", campaign_id, json_body={field: value}, as_json=as_json)
    _auto_log("campaign_budget", f"{campaign_id} {field} → {amount}", campaign_id=campaign_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Campaign {campaign_id} {field} → {amount}", fg="green")


@campaign.command("delete")
@click.argument("campaign_id")
@click.option("--hard", is_flag=True,
              help="Issue a true HTTP DELETE instead of the safer status=DELETED soft-delete "
                   "(KB § 7: a hard DELETE is confirmed reliable on AdCreative; on Campaign it is "
                   "documented as generically accepted but not independently re-confirmed — prefer "
                   "the soft-delete default).")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def campaign_delete(campaign_id, hard, dry_run, yes, as_json):
    """Delete a campaign (soft-delete via status=DELETED by default).

    KB: kb/marketing-api.md § 7. Remove / Delete a node.
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    action = f"{'HARD ' if hard else ''}delete campaign {campaign_id}"
    if not _confirm_and_log(action, "delete", dry_run, yes):
        return
    if hard:
        result = graph_request("DELETE", campaign_id, as_json=as_json)
    else:
        result = graph_request("POST", campaign_id, json_body={"status": "DELETED"}, as_json=as_json)
    _auto_log("campaign_delete", f"{campaign_id} ({'hard' if hard else 'soft'})", campaign_id=campaign_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Deleted campaign {campaign_id}", fg="green")
