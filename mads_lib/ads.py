"""mads ad command group — Meta Marketing API Ad management.

KB reference: kb/marketing-api.md (relative to mads-cli root)
Endpoints: POST/GET act_{ad_account_id}/ads, GET {adset_id}/ads or
{campaign_id}/ads edges, GET/POST/DELETE /{ad_id}
Uses mads_lib.http.graph_request() for every call — see campaigns.py's module
docstring for the overall shape/logging convention this file follows.

Note: unlike gads-cli (where google-ads.py is the pure REST client and cli.py
holds the Click commands), this module *is* both — the click group + commands
live here directly, matching the mads-cli-specific resource-group-module
convention already stubbed out in mads_lib/cli.py's TODO block.
"""
import json

import click

from .config import AD_ACCOUNT_ID
from .db import get_db
from .http import graph_request
from .output import flatten, print_error, print_json, print_table
from .timeutil import now_local

# KB § Enums Reference — Status enums by resource: Ad `status`/
# `configured_status` accepts these 4 values (effective_status has many more
# read-only/derived values — ADSET_PAUSED, DISAPPROVED, PENDING_REVIEW, etc).
_STATUS_CHOICES = ("ACTIVE", "PAUSED", "ARCHIVED", "DELETED")

_DEFAULT_LIST_FIELDS = (
    "id,name,adset_id,campaign_id,status,effective_status,creative,bid_amount,"
    "created_time,updated_time"
)


@click.group("ad")
def ad():
    """Ad management commands."""
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


# ── Commands ─────────────────────────────────────────────────


@ad.command("list")
@click.option("--adset-id", default=None, help="List ads under this ad set (uses the ad set's `ads` edge).")
@click.option("--campaign-id", default=None,
              help="List ads under this campaign (uses the campaign's `ads` edge). Ignored if --adset-id is given.")
@click.option("--ad-account-id", default=None)
@click.option("--fields", default=_DEFAULT_LIST_FIELDS)
@click.option("--all", "include_deleted", is_flag=True, help="Include DELETED/ARCHIVED ads (excluded by default).")
@click.option("--limit", "-l", type=int, default=100)
@click.option("--json", "as_json", is_flag=True)
def ad_list(adset_id, campaign_id, ad_account_id, fields, include_deleted, limit, as_json):
    """List ads (optionally scoped to one ad set or campaign).

    KB: kb/marketing-api.md § 4. Create Ad / Field Reference — Ad, `ads` edge.
    """
    params = {"fields": fields, "limit": limit}
    if not include_deleted:
        params["filtering"] = json.dumps(
            [{"field": "effective_status", "operator": "NOT_IN", "value": ["DELETED"]}]
        )
    if adset_id:
        path = f"{adset_id}/ads"
    elif campaign_id:
        path = f"{campaign_id}/ads"
    else:
        act = _require_act_id(ad_account_id, as_json)
        path = f"{act}/ads"
    result = graph_request("GET", path, params=params, as_json=as_json)
    rows = result.get("data", []) if isinstance(result, dict) else []
    if as_json:
        print_json(result)
        return
    if not rows:
        click.echo("  (no ads)")
        return
    print_table([flatten(r) for r in rows])
    click.echo(f"\n  {len(rows)} ad(s)")


@ad.command("create")
@click.argument("name")
@click.option("--adset-id", required=True)
@click.option("--creative-id", default=None, help="Reference an existing AdCreative id (see `mads creative create`).")
@click.option("--creative-spec", default=None, help="Raw JSON inline creative object — advanced, overrides --creative-id.")
@click.option("--status", type=click.Choice(["ACTIVE", "PAUSED"], case_sensitive=False), default="PAUSED")
@click.option("--ad-account-id", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def ad_create(name, adset_id, creative_id, creative_spec, status, ad_account_id, dry_run, yes, as_json):
    """Create an ad, linking it to an existing ad set + creative.

    KB: kb/marketing-api.md § 4. Create Ad — POST act_{ad_account_id}/ads
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    if not creative_id and not creative_spec:
        raise SystemExit(print_error(
            "Provide --creative-id (existing AdCreative) or --creative-spec (inline JSON).",
            code="VALIDATION", as_json=as_json,
        ))
    if creative_spec:
        try:
            creative_obj = json.loads(creative_spec)
        except json.JSONDecodeError as e:
            raise SystemExit(print_error(f"--creative-spec is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
    else:
        creative_obj = {"creative_id": creative_id}

    act = _require_act_id(ad_account_id, as_json)
    body = {"name": name, "adset_id": adset_id, "creative": creative_obj, "status": status.upper()}

    if not _confirm_and_log(f"create ad '{name}' in ad set {adset_id}", json.dumps(body), dry_run, yes):
        return

    result = graph_request("POST", f"{act}/ads", json_body=body, as_json=as_json)
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("ad_create", f"'{name}' in adset {adset_id}", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created ad '{name}' → id {new_id or '?'}", fg="green")


@ad.command("status")
@click.argument("ad_id")
@click.argument("status", type=click.Choice(_STATUS_CHOICES, case_sensitive=False))
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def ad_status(ad_id, status, dry_run, yes, as_json):
    """Change an ad's status (ACTIVE / PAUSED / ARCHIVED / DELETED).

    KB: kb/marketing-api.md § 6. Update (partial) — POST /{node_id}
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    status = status.upper()
    if not _confirm_and_log(f"ad {ad_id} → {status}", "status change", dry_run, yes):
        return
    result = graph_request("POST", ad_id, json_body={"status": status}, as_json=as_json)
    _auto_log("ad_status", f"{ad_id} → {status}")
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Ad {ad_id} → {status}", fg="green")


@ad.command("budget")
@click.argument("ad_id")
@click.argument("amount", type=int)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def ad_budget(ad_id, amount, dry_run, yes, as_json):
    """Set an ad's legacy bid_amount (Meta minor units).

    KB: kb/marketing-api.md Field Reference — Ad — `bid_amount` is "largely
    superseded by ad-set-level bidding". Included only to keep the
    campaign/adset/ad/creative CLI shape uniform (list/create/status/budget/
    delete) — prefer `mads adset budget` / `mads adset create --bid-strategy`
    for real bidding control.
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    if not _confirm_and_log(f"ad {ad_id} bid_amount → {amount}", "legacy ad-level bid", dry_run, yes):
        return
    result = graph_request("POST", ad_id, json_body={"bid_amount": amount}, as_json=as_json)
    _auto_log("ad_budget", f"{ad_id} bid_amount → {amount}")
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Ad {ad_id} bid_amount → {amount}", fg="green")


@ad.command("delete")
@click.argument("ad_id")
@click.option("--hard", is_flag=True,
              help="Issue a true HTTP DELETE instead of the safer status=DELETED soft-delete "
                   "(KB § 7: only independently confirmed reliable on AdCreative — use with caution here).")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def ad_delete(ad_id, hard, dry_run, yes, as_json):
    """Delete an ad (soft-delete via status=DELETED by default).

    KB: kb/marketing-api.md § 7. Remove / Delete a node.
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    action = f"{'HARD ' if hard else ''}delete ad {ad_id}"
    if not _confirm_and_log(action, "delete", dry_run, yes):
        return
    if hard:
        result = graph_request("DELETE", ad_id, as_json=as_json)
    else:
        result = graph_request("POST", ad_id, json_body={"status": "DELETED"}, as_json=as_json)
    _auto_log("ad_delete", f"{ad_id} ({'hard' if hard else 'soft'})")
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Deleted ad {ad_id}", fg="green")
