"""mads — Meta (Facebook/Instagram) Ads CLI.

Manage Meta Marketing API campaigns, ad sets, ads, Conversions API, and
Commerce Manager from a single CLI. Designed for use with Claude Code and AI
coding agents.

All configuration is via environment variables / .env file. See config.py
for the full list of MADS_* / META_* variables.

Architecture mirrors gads-cli (the Google Ads sibling CLI) wherever sensible:
config/auth/http/output/db/dbread/timeutil/catalog modules, the same
top-level command names (doctor, snapshot, log, changelog, decisions,
milestones, db, catalog, query, mutate, batch-mutate), and the same
structured-error-envelope `main()` entry point.
"""

import json as _json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import click

from mads_lib import (
    AD_ACCOUNT_ID,
    APP_ID,
    APP_SECRET,
    BUSINESS_ID,
    CREDS_PATH,
    CURRENCY,
    DB_PATH,
    SCOPE_ROOT,
    SCOPE_TYPE,
    SNAPSHOTS_DIR,
    TZ_NAME,
    __version__,
    flatten,
    get_db,
    now_local,
    print_json,
    print_table,
    today_local,
)
from mads_lib.catalog import build_catalog
from mads_lib.config import API_VERSION
from mads_lib.http import batch_request, graph_request
from mads_lib.output import EXIT_CODES, print_error
from mads_lib import dbread
from mads_lib.kb import check_drift, list_kb_files, show_kb_file, load_manifest

# ── Resource-group Click groups ──────────────────────────────
# These modules each define a `@click.group()` that is registered on the
# root `cli` group below.
from mads_lib.campaigns import campaign as campaign_group
from mads_lib.campaigns import _DEFAULT_LIST_FIELDS as _CAMPAIGN_SNAPSHOT_FIELDS
from mads_lib.adsets import adset as adset_group
from mads_lib.adsets import _DEFAULT_LIST_FIELDS as _ADSET_SNAPSHOT_FIELDS
from mads_lib.ads import ad as ad_group
from mads_lib.ads import _DEFAULT_LIST_FIELDS as _AD_SNAPSHOT_FIELDS
from mads_lib.creatives import creative as creative_group
from mads_lib.insights import insights as insights_group
from mads_lib.abtest import abtest as abtest_group
from mads_lib.business import business as business_group
from mads_lib.pages import page as page_group
from mads_lib.webhooks import webhooks as webhooks_group
from mads_lib.whatsapp import whatsapp as whatsapp_group

# NOTE(mads-cli): audiences.py, commerce.py, and capi.py are pure Meta Graph
# API client function libraries (list_audiences/create_custom_audience/...,
# create_catalog/create_product_feed/..., create_pixel/send_event/...) — none
# of them define a `@click.group()` or any `@click.command()`. This mirrors
# gads-cli's gads_lib/merchant.py shape, whose functions are wrapped by a
# `merchant` Click group defined directly in gads_lib/cli.py rather than in
# merchant.py itself — the `audience`/`commerce`/`capi` groups below follow
# that same convention. Likewise, mads_lib/analyze/*.py exposes only
# analyze_*()/render_*() functions with no Click group, mirroring gads-cli's
# gads_lib/analyze/*.py — the `analyze` group below wraps them the same way
# gads_lib/cli.py's `analyze` group does (thin per-analysis subcommand,
# lazy-imported inline).
from mads_lib import audiences as _audiences
from mads_lib import commerce as _commerce
from mads_lib import capi as _capi
from mads_lib import posts as _posts
from mads_lib import comments as _comments


@click.group(
    context_settings={"auto_envvar_prefix": "MADS"},
    epilog=(
        "For Google Ads, Google Business Profile, Merchant Center, GA4, and "
        "Search Console, see the sister CLI gads-cli: "
        "https://github.com/talas9/gads-cli"
    ),
)
@click.version_option(__version__, prog_name="mads")
@click.option("--plain", is_flag=True, help="Deterministic output: no color, no emoji (for parsing).")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential progress/info output.")
@click.pass_context
def cli(ctx, plain, quiet):
    """mads — Meta (Facebook/Instagram) Ads CLI."""
    ctx.ensure_object(dict)
    ctx.obj["plain"] = plain
    ctx.obj["quiet"] = quiet
    if plain:
        # Strip ANSI color globally for deterministic, parseable output.
        import os as _os
        _os.environ["NO_COLOR"] = "1"
        ctx.color = False


# ── Resource-group registration ──────────────────────────────
cli.add_command(campaign_group)
cli.add_command(adset_group)
cli.add_command(ad_group)
cli.add_command(creative_group)
cli.add_command(insights_group)
cli.add_command(abtest_group)
cli.add_command(business_group)
cli.add_command(page_group)
# webhooks.py's group function is named `webhooks` (plural); exposed here as
# the singular `webhook` to match the naming convention of the other
# resource groups (campaign/adset/ad/creative/business/page are all singular).
cli.add_command(webhooks_group, name="webhook")
# WhatsApp Business Platform (Cloud API) — a SEPARATE Meta product from the
# Marketing/Graph API resource groups above; see mads_lib/whatsapp.py's module
# docstring for the WABA/coexistence onboarding prerequisite (not yet done for
# Talas) and kb/whatsapp-business-platform.md for full command reference.
cli.add_command(whatsapp_group)
# audience/commerce/capi/analyze groups are defined further down in this file
# (they wrap plain function libraries, mirroring gads-cli's `merchant`/
# `analyze` groups, which are likewise defined in gads_lib/cli.py rather than
# in the wrapped modules) and registered at the bottom of the module.


def enforce_allowed_caller():
    """Optional caller enforcement for agent delegation models.

    Mirrors gads-cli's `enforce_allowed_caller()` (gads_lib/cli.py) exactly,
    with a mads-prefixed env-var namespace so the two CLIs never collide:
    MADS_ENFORCE_CALLER / MADS_EXPECTED_CALLER / MADS_CALLER_AGENT instead of
    GADS_*. os.environ-only gate, no Click dependency — safe to call from any
    resource-group module (campaigns.py, adsets.py, ads.py, creatives.py,
    webhooks.py, pages.py, abtest.py) via a local `from mads_lib.cli import
    enforce_allowed_caller` inside the command function, avoiding a circular
    top-level import (this module imports those modules' Click groups).
    """
    if os.environ.get("MADS_ENFORCE_CALLER") != "1":
        return
    expected = os.environ.get("MADS_EXPECTED_CALLER", "meta-platform-operator")
    caller = os.environ.get("MADS_CALLER_AGENT", "")
    if caller != expected:
        click.secho(
            f"✗ mads is restricted to the '{expected}' agent when MADS_ENFORCE_CALLER=1",
            fg="red", err=True,
        )
        raise SystemExit(1)


# ── Helpers ──────────────────────────────────────────────────


def _confirm_and_log(action, details, dry_run=False, yes=False):
    if dry_run:
        click.secho(f"  DRY RUN: {action} — {details}", fg="yellow")
        return False
    if not yes:
        click.confirm(f"  Execute: {action}?", abort=True)
    return True


def _auto_log(action, details, campaign_name="", campaign_id=""):
    """Best-effort changelog write. mads-cli owns no schema, so the
    `changelog` table may not exist yet in a fresh MADS_DB_PATH — this never
    raises, matching gads-cli's `_auto_log` behavior.

    Note: `get_db()` raises `SystemExit(1)` (not a plain `Exception`) when
    MADS_DB_PATH doesn't exist yet — caught explicitly here alongside
    `Exception` (mirrors mads_lib.campaigns._auto_log and friends) so a
    missing/not-yet-initialized DB never aborts an otherwise-successful
    mutation that already went out over the wire.
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
            (ts, action, campaign_name, campaign_id, details, "", "mads-cli", "", "", _json.dumps(raw), "meta_ads"),
        )
        conn.commit()
        conn.close()
    except (Exception, SystemExit):
        pass


# ── Auth command group ───────────────────────────────────────


@cli.group()
def auth():
    """Authentication and credential diagnostics."""
    pass


@auth.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
@click.option("--verbose", is_flag=True, help="Include the credentials file path.")
def auth_status(as_json, verbose):
    """Show current credential and env status (never prints secrets)."""
    creds_present = CREDS_PATH.exists()
    token_meta = {}
    if creds_present:
        try:
            with open(CREDS_PATH) as f:
                data = _json.load(f)
            token_meta = {
                "token_type": data.get("token_type"),
                "obtained_at": data.get("obtained_at"),
                "expires_at": data.get("expires_at"),
                "scopes_requested": data.get("scopes_requested", []),
            }
        except (OSError, _json.JSONDecodeError):
            token_meta = {}

    payload = {
        "scope": SCOPE_TYPE,
        "scope_root": str(SCOPE_ROOT),
        "credentials_present": creds_present,
        "app_id_set": bool(APP_ID),
        "app_secret_set": bool(APP_SECRET),
        "ad_account_id_set": bool(AD_ACCOUNT_ID),
        "business_id_set": bool(BUSINESS_ID),
        "api_version": API_VERSION,
        "timezone": TZ_NAME,
        "currency": CURRENCY,
        "db_path": str(DB_PATH),
        "db_present": DB_PATH.exists(),
        **token_meta,
    }
    if verbose:
        payload["credentials_path"] = str(CREDS_PATH)

    if as_json:
        print_json(payload)
        return

    click.secho("\n  Auth Status\n", fg="white", bold=True)
    rows = [{"field": k, "value": str(v)} for k, v in payload.items()]
    print_table(rows, ["field", "value"])


@auth.command("login")
@click.option("--port", type=int, default=9090, help="Local OAuth callback port.")
@click.option("--force", is_flag=True, help="Re-authenticate even if a token already exists.")
def auth_login(port, force):
    """Authenticate with Meta (OAuth browser flow).

    Delegates to generate_token.py (kept as a standalone script so it can be
    run headlessly / on a different machine than the one with API access).
    """
    if CREDS_PATH.exists() and not force:
        click.secho("  Token already exists. Use --force to re-authenticate.", fg="yellow")
        click.echo(f"  Token: {CREDS_PATH}")
        return

    import subprocess

    script = Path(__file__).resolve().parent.parent / "generate_token.py"
    if not script.exists():
        click.secho(f"✗ generate_token.py not found at {script}", fg="red", err=True)
        raise SystemExit(1)

    result = subprocess.run([sys.executable, str(script), "--port", str(port)])
    raise SystemExit(result.returncode)


@auth.command("revoke")
@click.confirmation_option(prompt="This will delete your stored Meta access token. Continue?")
def auth_revoke():
    """Revoke and delete the stored Meta access token."""
    if not CREDS_PATH.exists():
        click.echo("  No token to revoke.")
        return

    # Best-effort server-side revoke: DELETE /me/permissions revokes every
    # permission the user granted to this app.
    # https://developers.facebook.com/docs/graph-api/reference/user/permissions/
    try:
        graph_request("DELETE", "me/permissions")
        click.secho("  ✓ Permissions revoked with Meta", fg="green")
    except SystemExit:
        click.secho("  ⚠ Could not revoke with Meta (token may already be expired)", fg="yellow")

    CREDS_PATH.unlink()
    click.secho(f"  ✓ Deleted {CREDS_PATH}", fg="green")


@auth.command("test")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def auth_test(as_json):
    """Attempt a live /me call to verify credentials.

    Reports "no credentials configured" gracefully if none exist yet, rather
    than erroring.
    """
    if not CREDS_PATH.exists():
        detail = "no credentials configured"
        if as_json:
            print_json({"service": "Meta Graph API", "status": "skip", "detail": detail})
            return
        click.echo(f"  {detail} — run 'mads auth login' or 'python generate_token.py'")
        return

    result = graph_request("GET", "me", params={"fields": "id,name"}, as_json=as_json)
    payload = {"service": "Meta Graph API", "status": "ok", "detail": result}

    if as_json:
        print_json(payload)
        return
    click.secho("\n  Auth Test\n", fg="white", bold=True)
    print_table([{"field": k, "value": str(v)} for k, v in payload.items()], ["field", "value"])


# ── Auth: system-user + token subgroups (Business Manager) ──


@auth.group("system-user")
def auth_system_user():
    """Business Manager System User management."""
    pass


@auth_system_user.command("create")
@click.argument("name")
@click.option("--role", type=click.Choice(["ADMIN", "EMPLOYEE"]), default="EMPLOYEE", help="System user role.")
@click.option("--business-id", "business_id", default=None, help="Override META_BUSINESS_ID.")
@click.option("--json", "as_json", is_flag=True)
def system_user_create(name, role, business_id, as_json):
    """Create a Business Manager System User.

    POST /{business_id}/system_users
    https://developers.facebook.com/docs/marketing-api/system-users/create
    """
    biz_id = business_id or BUSINESS_ID
    if not biz_id:
        raise SystemExit(print_error(
            "META_BUSINESS_ID is not set (or pass --business-id).", code="VALIDATION", as_json=as_json,
        ))
    result = graph_request("POST", f"{biz_id}/system_users", params={"name": name, "role": role}, as_json=as_json)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created system user '{name}' ({role})", fg="green")
    print_json(result)


@auth_system_user.command("list")
@click.option("--business-id", "business_id", default=None, help="Override META_BUSINESS_ID.")
@click.option("--json", "as_json", is_flag=True)
def system_user_list(business_id, as_json):
    """List Business Manager System Users.

    GET /{business_id}/system_users
    """
    biz_id = business_id or BUSINESS_ID
    if not biz_id:
        raise SystemExit(print_error(
            "META_BUSINESS_ID is not set (or pass --business-id).", code="VALIDATION", as_json=as_json,
        ))
    result = graph_request("GET", f"{biz_id}/system_users", as_json=as_json)
    rows = result.get("data", []) if isinstance(result, dict) else []
    if as_json:
        print_json(rows)
        return
    print_table(rows)


@auth.group("token")
def auth_token():
    """System User access token generation (Business Manager)."""
    pass


@auth_token.command("generate")
@click.argument("system_user_id")
@click.option("--scope", default="ads_management,business_management", help="Comma-separated permission scopes.")
@click.option("--json", "as_json", is_flag=True)
def token_generate(system_user_id, scope, as_json):
    """Generate a System User access token (60-day expiry by default).

    POST /{system_user_id}/access_tokens
    https://developers.facebook.com/docs/marketing-api/system-users/create-access-token
    """
    result = graph_request(
        "POST", f"{system_user_id}/access_tokens",
        params={"scope": scope, "set_token_expires_in_60_days": "true"},
        as_json=as_json,
    )
    if as_json:
        print_json(result)
        return
    click.secho("✓ Generated system user access token", fg="green")
    print_json(result)


@auth_token.command("renew")
@click.argument("system_user_id")
@click.option("--json", "as_json", is_flag=True)
def token_renew(system_user_id, as_json):
    """Renew (regenerate) a System User access token.

    Same endpoint as `generate` — Meta has no separate "renew" call; calling
    POST /{system_user_id}/access_tokens again issues a fresh token.
    """
    result = graph_request(
        "POST", f"{system_user_id}/access_tokens",
        params={"set_token_expires_in_60_days": "true"},
        as_json=as_json,
    )
    if as_json:
        print_json(result)
        return
    click.secho("✓ Renewed system user access token", fg="green")
    print_json(result)


# ── Doctor ────────────────────────────────────────────────────


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON.")
def doctor(as_json):
    """Run local CLI readiness checks."""
    sibling_path = shutil.which("gads")
    sibling_cli = {
        "name": "gads-cli",
        "installed": sibling_path is not None,
        "path": sibling_path,
    }

    checks = [
        {"check": "scope", "status": "ok", "detail": f"{SCOPE_TYPE} → {SCOPE_ROOT}"},
        {"check": "credentials", "status": "ok" if CREDS_PATH.exists() else "fail", "detail": str(CREDS_PATH)},
        {"check": "database", "status": "ok" if DB_PATH.exists() else "warn", "detail": str(DB_PATH)},
        {"check": "app_id", "status": "ok" if APP_ID else "fail", "detail": "set" if APP_ID else "missing — set META_APP_ID"},
        {"check": "app_secret", "status": "ok" if APP_SECRET else "fail", "detail": "set" if APP_SECRET else "missing — set META_APP_SECRET"},
        {"check": "ad_account_id", "status": "ok" if AD_ACCOUNT_ID else "warn", "detail": "set" if AD_ACCOUNT_ID else "missing — set META_AD_ACCOUNT_ID (optional until ad-account commands land)"},
        {"check": "business_id", "status": "ok" if BUSINESS_ID else "warn", "detail": "set" if BUSINESS_ID else "missing — set META_BUSINESS_ID (optional, needed for system-user commands)"},
        {"check": "api_version", "status": "ok", "detail": API_VERSION},
        {"check": "timezone", "status": "ok", "detail": TZ_NAME},
        {"check": "currency", "status": "ok", "detail": CURRENCY},
        {"check": "sibling_cli", "status": "ok" if sibling_cli["installed"] else "warn", "detail": sibling_path or "gads not found on PATH"},
    ]

    if as_json:
        print_json({"checks": checks, "sibling_cli": sibling_cli})
        return

    click.secho("\n  mads doctor\n", fg="white", bold=True)
    print_table(checks, ["check", "status", "detail"])
    click.echo()
    click.echo(f"  sibling_cli (gads-cli): installed={sibling_cli['installed']} path={sibling_cli['path']}")
    failures = [c for c in checks if c["status"] == "fail"]
    if failures:
        raise SystemExit(1)


# ── Generic Graph API query (no GAQL equivalent on Meta) ─────


@cli.command()
@click.option("--node", required=True, help="Graph API node/edge path, e.g. 'act_1234567890/campaigns' or 'me'.")
@click.option("--edge", default=None, help="Optional edge appended to --node, e.g. 'insights'.")
@click.option("--fields", default=None, help="Comma-separated fields to request.")
@click.option("--filtering", default=None, help="JSON-encoded `filtering` array (Marketing API filtering param).")
@click.option("--limit", "-l", type=int, default=None, help="Max rows (sent as the Graph API `limit` param).")
@click.option("--json", "as_json", is_flag=True)
def query(node, edge, fields, filtering, limit, as_json):
    """Run a generic Graph API GET request.

    Meta has no GAQL equivalent — this is a thin builder around the
    node/edge/fields/filtering shape every Marketing API read call shares.
    """
    path = node
    if edge:
        path = f"{node.rstrip('/')}/{edge.lstrip('/')}"

    params = {}
    if fields:
        params["fields"] = fields
    if filtering:
        try:
            _json.loads(filtering)  # validate shape before sending
        except _json.JSONDecodeError as e:
            raise SystemExit(print_error(f"--filtering is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
        params["filtering"] = filtering
    if limit:
        params["limit"] = limit

    result = graph_request("GET", path, params=params, as_json=as_json)

    if as_json:
        print_json(result)
        return

    rows = result.get("data") if isinstance(result, dict) and "data" in result else None
    if rows is None:
        print_json(result)
        return
    if not rows:
        click.echo("  (no results)")
        return
    flat_rows = [flatten(r) for r in rows]
    print_table(flat_rows)
    click.echo(f"\n  {len(flat_rows)} row(s)")


# ── Changelog / snapshot ──────────────────────────────────────


@cli.command()
@click.argument("action")
@click.argument("details")
@click.option("--reason", "-r", default="")
@click.option("--campaign", "-c", default="")
@click.option("--campaign-id", default="")
@click.option("--agent", default="claude-code")
@click.option("--snapshot-ref", default="")
@click.option("--script", default="")
@click.option("--json", "as_json", is_flag=True)
def log(action, details, reason, campaign, campaign_id, agent, snapshot_ref, script, as_json):
    """Log an action to the changelog (append-only).

    Uses the exact same `changelog` column names as gads-cli
    (timestamp/action/campaign/campaign_id/details/reason/agent/snapshot_ref/script)
    so both CLIs can share one changelog table.
    """
    ts = now_local()
    conn = get_db()
    raw = {
        "timestamp": ts, "action": action, "campaign": campaign,
        "campaign_id": campaign_id, "details": details, "reason": reason,
        "agent": agent, "snapshot_ref": snapshot_ref, "script": script,
    }
    try:
        conn.execute(
            """INSERT INTO changelog
            (timestamp, action, campaign, campaign_id, details, reason, agent, snapshot_ref, script, raw_json, platform)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, action, campaign, campaign_id, details, reason, agent, snapshot_ref, script, _json.dumps(raw), "meta_ads"),
        )
        conn.commit()
        if as_json:
            print_json({"logged": True, "timestamp": ts, "action": action, "details": details})
        else:
            click.secho(f"✓ Logged: {action} at {ts}", fg="green")
    finally:
        conn.close()


@cli.command()
@click.argument("name")
@click.option("--save-file", is_flag=True, help="Also save JSON to MADS_SNAPSHOTS_DIR.")
@click.option("--json", "as_json", is_flag=True)
def snapshot(name, save_file, as_json):
    """Snapshot the current mads-cli config state, plus live campaign/ad-set/ad state.

    Always records the env-derived config (api version, which env vars are
    set, timezone, currency). Additionally, when credentials are configured
    (MADS_CREDENTIALS_PATH exists, META_AD_ACCOUNT_ID and META_APP_SECRET are
    set), fetches live campaign/ad-set/ad state from the Marketing API —
    mirroring gads-cli's `snapshot` command, which runs a live GAQL query and
    writes the results to SNAPSHOTS_DIR + a best-effort DB record. If
    credentials aren't configured yet, or the live fetch fails, this degrades
    gracefully: `live.available` is False and `live.reason` explains why,
    rather than crashing.
    """
    ts_date = today_local()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_{name}.json"

    config_state = {
        "api_version": API_VERSION,
        "app_id_set": bool(APP_ID),
        "ad_account_id_set": bool(AD_ACCOUNT_ID),
        "business_id_set": bool(BUSINESS_ID),
        "timezone": TZ_NAME,
        "currency": CURRENCY,
    }

    # ── Live campaign/ad-set/ad state (best-effort) ──────────
    live_data = {
        "attempted": False,
        "available": False,
        "reason": None,
        "campaigns": [],
        "adsets": [],
        "ads": [],
        "campaign_count": 0,
        "adset_count": 0,
        "ad_count": 0,
    }
    missing = []
    if not CREDS_PATH.exists():
        missing.append(f"credentials not found: {CREDS_PATH}")
    if not AD_ACCOUNT_ID:
        missing.append("META_AD_ACCOUNT_ID is not set")
    if not APP_SECRET:
        missing.append("META_APP_SECRET is not set")

    if missing:
        live_data["reason"] = "; ".join(missing)
    else:
        live_data["attempted"] = True
        act = AD_ACCOUNT_ID if AD_ACCOUNT_ID.startswith("act_") else f"act_{AD_ACCOUNT_ID}"
        not_deleted = _json.dumps(
            [{"field": "effective_status", "operator": "NOT_IN", "value": ["DELETED"]}]
        )
        try:
            camp_result = graph_request(
                "GET", f"{act}/campaigns",
                params={"fields": _CAMPAIGN_SNAPSHOT_FIELDS, "limit": 200, "filtering": not_deleted},
            )
            adset_result = graph_request(
                "GET", f"{act}/adsets",
                params={"fields": _ADSET_SNAPSHOT_FIELDS, "limit": 200, "filtering": not_deleted},
            )
            ad_result = graph_request(
                "GET", f"{act}/ads",
                params={"fields": _AD_SNAPSHOT_FIELDS, "limit": 200, "filtering": not_deleted},
            )
            live_data["campaigns"] = camp_result.get("data", []) if isinstance(camp_result, dict) else []
            live_data["adsets"] = adset_result.get("data", []) if isinstance(adset_result, dict) else []
            live_data["ads"] = ad_result.get("data", []) if isinstance(ad_result, dict) else []
            live_data["campaign_count"] = len(live_data["campaigns"])
            live_data["adset_count"] = len(live_data["adsets"])
            live_data["ad_count"] = len(live_data["ads"])
            live_data["available"] = True
        except SystemExit as e:
            live_data["reason"] = f"Meta Graph API request failed (exit_code={e.code})"
        except Exception as e:
            live_data["reason"] = f"live fetch failed: {e}"

    # Best-effort DB record — mads-cli owns no schema, so `snapshots` may not
    # exist yet in a fresh MADS_DB_PATH. `get_db()` raises `SystemExit(1)`
    # (not a plain `Exception`) when MADS_DB_PATH doesn't exist yet — caught
    # explicitly here too (mirrors mads_lib.campaigns._auto_log) so a missing/
    # not-yet-initialized DB never aborts an otherwise successful snapshot.
    try:
        conn = get_db()
        note = "" if live_data["available"] else (live_data["reason"] or "")
        conn.execute(
            "INSERT OR REPLACE INTO snapshots "
            "(filename, date, time, description, related_action, platform) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (filename, ts_date, datetime.now().strftime("%H:%M:%S"), name, note, "meta_ads"),
        )
        conn.commit()
        conn.close()
    except (Exception, SystemExit) as e:
        click.secho(f"  Warning: snapshot DB record not written: {e}", fg="yellow", err=True)

    written_path = None
    if save_file:
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = SNAPSHOTS_DIR / filename
        with open(filepath, "w") as f:
            _json.dump(
                {"name": name, "date": ts_date, "config": config_state, "live": live_data},
                f, indent=2,
            )
        written_path = str(filepath)

    if as_json:
        print_json({
            "saved": True, "name": name, "date": ts_date, "db_record": filename,
            "file": written_path, "config": config_state, "live": live_data,
        })
        return
    click.secho(f"✓ Saved snapshot '{name}' (date={ts_date})", fg="green")
    if live_data["available"]:
        click.secho(
            f"✓ Live: {live_data['campaign_count']} campaign(s), "
            f"{live_data['adset_count']} ad set(s), {live_data['ad_count']} ad(s)",
            fg="green",
        )
    else:
        click.secho(f"  Live data not captured: {live_data['reason']}", fg="yellow")
    if written_path:
        click.secho(f"✓ Written: {written_path}", fg="green")


# ── Generic mutate commands (escape hatch) ───────────────────


@cli.command("mutate")
@click.argument("resource_type")
@click.argument("operations_json")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def mutate_single(resource_type, operations_json, dry_run, yes, as_json):
    """Generic single-resource mutate (escape hatch).

    `resource_type` is the Graph API node/edge to POST to (e.g.
    'act_1234567890/campaigns'). `operations_json` is a JSON object of POST
    body params, or a JSON array of such objects for sequential calls.
    """
    enforce_allowed_caller()
    try:
        ops = _json.loads(operations_json)
    except _json.JSONDecodeError as e:
        raise SystemExit(print_error(f"Invalid JSON: {e}", code="VALIDATION", as_json=as_json))
    if not isinstance(ops, list):
        ops = [ops]

    if not _confirm_and_log(f"mutate {resource_type} ({len(ops)} op(s))", "generic mutate", dry_run, yes):
        return

    # Sequential client-side loop (this is NOT the Meta batch API — that's
    # `batch-mutate`/http.batch_request(), a single HTTP call). If op N fails
    # partway through, ops 0..N-1 have *already executed* against the live
    # account. graph_request() already raises a clean, classified SystemExit
    # for the failing op itself — but without this, the caller has no way to
    # tell how much of the batch already went out, risking a confusing
    # re-run/duplicate-mutation if an agent retries the whole `operations_json`.
    results = []
    for i, op in enumerate(ops):
        try:
            results.append(graph_request("POST", resource_type, params=op, as_json=as_json))
        except SystemExit:
            if i > 0:
                click.secho(
                    f"  {i} of {len(ops)} operation(s) already executed against the live "
                    "account before this failure — do not blindly re-run the full batch.",
                    fg="yellow", err=True,
                )
            raise
    _auto_log("mutate", f"{resource_type}: {len(ops)} operation(s)")
    if as_json:
        print_json(results)
        return
    click.secho(f"✓ Mutated {resource_type}", fg="green")
    print_json(results)


@cli.command("batch-mutate")
@click.argument("operations_json")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def batch_mutate_cmd(operations_json, dry_run, yes, as_json):
    """Generic cross-resource batch mutate (escape hatch).

    `operations_json` is a JSON array of Graph API batch operations, e.g.
    [{"method": "POST", "relative_url": "act_1234567890/campaigns", "body": "..."}].
    Meta's hard 50-operation batch limit is enforced client-side by
    http.batch_request().
    """
    enforce_allowed_caller()
    try:
        ops = _json.loads(operations_json)
    except _json.JSONDecodeError as e:
        raise SystemExit(print_error(f"Invalid JSON: {e}", code="VALIDATION", as_json=as_json))
    if not isinstance(ops, list):
        ops = [ops]

    if not _confirm_and_log(f"batch mutate ({len(ops)} op(s))", "batch mutate", dry_run, yes):
        return

    result = batch_request(ops, as_json=as_json)
    _auto_log("batch_mutate", f"{len(ops)} operation(s)")
    if as_json:
        print_json(result)
        return
    click.secho("✓ Batch mutate complete", fg="green")
    print_json(result)


# ── Catalog (machine-readable command manifest) ─────────────


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Emit the full command manifest as JSON.")
def catalog(as_json):
    """Emit a machine-readable manifest of every command, param, and help string.

    Lets an agent discover the CLI's full capabilities without parsing --help.
    """
    manifest = build_catalog(cli, __version__)
    if as_json:
        print_json(manifest)
        return
    click.secho("\n  mads command catalog\n", fg="white", bold=True)

    def _emit(commands, indent=2):
        for name in sorted(commands):
            entry = commands[name]
            help_txt = (entry.get("help") or "").strip().splitlines()
            help_one = help_txt[0] if help_txt else ""
            click.echo(f"{' ' * indent}{name:<18} {help_one}")
            if entry.get("subcommands"):
                _emit(entry["subcommands"], indent + 4)

    _emit(manifest["commands"])
    click.echo("\n  Use 'mads catalog --json' for the full machine-readable manifest.\n")


# ── Read-only history DB access ─────────────────────────────


@cli.command(name="db")
@click.argument("sql")
@click.option("--limit", type=int, default=None, help="Cap the number of returned rows.")
@click.option("--json", "as_json", is_flag=True)
def db_query(sql, limit, as_json):
    """Run a read-only SELECT against the local history database.

    Only single SELECT/WITH queries are allowed; any mutating statement is rejected.
    """
    try:
        rows = dbread.run_select(sql, limit=limit)
    except dbread.UnsafeSQLError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    if as_json:
        print_json(rows)
        return
    print_table([flatten(r) for r in rows] if rows else rows)
    click.echo(f"\n  {len(rows)} row(s)")


@cli.command()
@click.option("--limit", "-n", type=int, default=50)
@click.option("--json", "as_json", is_flag=True)
def changelog(limit, as_json):
    """Read the local changelog (append-only action history)."""
    rows = dbread.read_changelog(limit=limit)
    if as_json:
        print_json(rows)
        return
    print_table([flatten(r) for r in rows] if rows else rows)
    click.echo(f"\n  {len(rows)} entry(ies)")


@cli.command()
@click.option("--limit", "-n", type=int, default=50)
@click.option("--json", "as_json", is_flag=True)
def decisions(limit, as_json):
    """Read the local decisions log."""
    rows = dbread.read_decisions(limit=limit)
    if as_json:
        print_json(rows)
        return
    print_table([flatten(r) for r in rows] if rows else rows)
    click.echo(f"\n  {len(rows)} decision(s)")


@cli.command()
@click.option("--limit", "-n", type=int, default=50)
@click.option("--json", "as_json", is_flag=True)
def milestones(limit, as_json):
    """Read the local milestones log."""
    rows = dbread.read_milestones(limit=limit)
    if as_json:
        print_json(rows)
        return
    print_table([flatten(r) for r in rows] if rows else rows)
    click.echo(f"\n  {len(rows)} milestone(s)")


# ── Audience (Custom / Lookalike Audiences) ──────────────────
# Wraps mads_lib/audiences.py (pure Graph API client functions, no Click of
# its own — see the NOTE near the top imports).


@cli.group()
def audience():
    """Custom / Lookalike Audience management."""
    pass


@audience.command("list")
@click.option("--ad-account-id", default=None, help="Override META_AD_ACCOUNT_ID.")
@click.option("--fields", default=_audiences.DEFAULT_AUDIENCE_FIELDS, help="Comma-separated fields to request.")
@click.option("--limit", "-l", type=int, default=None)
@click.option("--after", default=None, help="Pagination cursor.")
@click.option("--json", "as_json", is_flag=True)
def audience_list(ad_account_id, fields, limit, after, as_json):
    """List Custom/Lookalike Audiences owned by the ad account."""
    result = _audiences.list_audiences(ad_account_id=ad_account_id, fields=fields, limit=limit, after=after, as_json=as_json)
    if as_json:
        print_json(result)
        return
    rows = result.get("data", []) if isinstance(result, dict) else []
    if not rows:
        click.echo("  (no audiences)")
        return
    print_table([flatten(r) for r in rows])
    click.echo(f"\n  {len(rows)} audience(s)")


@audience.command("create")
@click.argument("name")
@click.option("--customer-file-source", default="USER_PROVIDED_ONLY",
              type=click.Choice(["USER_PROVIDED_ONLY", "PARTNER_PROVIDED_ONLY", "BOTH_USER_AND_PARTNER_PROVIDED"]))
@click.option("--description", default=None)
@click.option("--subtype", default="CUSTOM", help="CustomAudience subtype (default CUSTOM; use create-lookalike for LOOKALIKE).")
@click.option("--ad-account-id", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def audience_create(name, customer_file_source, description, subtype, ad_account_id, dry_run, yes, as_json):
    """Create a Custom Audience."""
    enforce_allowed_caller()
    if not _confirm_and_log(f"create audience '{name}' [{subtype}]", "audience create", dry_run, yes):
        return
    result = _audiences.create_custom_audience(
        name, customer_file_source=customer_file_source, description=description,
        subtype=subtype, ad_account_id=ad_account_id, as_json=as_json,
    )
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("audience_create", f"'{name}' [{subtype}]", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created audience '{name}' → id {new_id or '?'}", fg="green")


@audience.command("create-lookalike")
@click.argument("name")
@click.argument("origin_audience_id")
@click.option("--ratio", type=float, default=0.01, help="0.01–0.20 (top 1%–20% of the target country).")
@click.option("--country", default="AE")
@click.option("--lookalike-type", type=click.Choice(["similarity", "reach"]), default="similarity")
@click.option("--starting-ratio", type=float, default=None, help="Combine with --ratio to target a band instead of the top N%.")
@click.option("--ad-account-id", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def audience_create_lookalike(name, origin_audience_id, ratio, country, lookalike_type,
                               starting_ratio, ad_account_id, dry_run, yes, as_json):
    """Create a Lookalike Audience seeded from an existing Custom Audience."""
    if not _confirm_and_log(f"create lookalike '{name}' from {origin_audience_id}", "audience create-lookalike", dry_run, yes):
        return
    try:
        result = _audiences.create_lookalike_audience(
            name, origin_audience_id, ratio=ratio, country=country, lookalike_type=lookalike_type,
            starting_ratio=starting_ratio, ad_account_id=ad_account_id, as_json=as_json,
        )
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("audience_create_lookalike", f"'{name}' from {origin_audience_id}", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created lookalike audience '{name}' → id {new_id or '?'}", fg="green")


@audience.command("upload-users")
@click.argument("custom_audience_id")
@click.argument("schema")
@click.argument("rows_json")
@click.option("--already-hashed", is_flag=True, help="Rows are already SHA-256 hashes; skip auto-hashing.")
@click.option("--session-id", type=int, default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def audience_upload_users(custom_audience_id, schema, rows_json, already_hashed, session_id, dry_run, yes, as_json):
    """Add (hashed) user records to a Custom Audience.

    SCHEMA is comma-separated (e.g. "EMAIL,FN,LN"). ROWS_JSON is a JSON array
    of arrays, each inner array a record aligned to SCHEMA order.
    """
    enforce_allowed_caller()
    try:
        rows = _json.loads(rows_json)
    except _json.JSONDecodeError as e:
        raise SystemExit(print_error(f"ROWS_JSON is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
    schema_list = [s.strip() for s in schema.split(",") if s.strip()]

    if not _confirm_and_log(f"upload {len(rows)} user row(s) to {custom_audience_id}", "audience upload-users", dry_run, yes):
        return
    try:
        result = _audiences.upload_audience_users(
            custom_audience_id, schema_list, rows, already_hashed=already_hashed,
            session_id=session_id, as_json=as_json,
        )
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    _auto_log("audience_upload_users", f"{custom_audience_id}: {len(rows)} row(s)", campaign_id=custom_audience_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Uploaded {len(rows)} row(s) to audience {custom_audience_id}", fg="green")
    print_json(result)


@audience.command("delete")
@click.argument("audience_id")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def audience_delete(audience_id, dry_run, yes, as_json):
    """Delete a Custom/Lookalike Audience."""
    enforce_allowed_caller()
    if not _confirm_and_log(f"delete audience {audience_id}", "audience delete", dry_run, yes):
        return
    result = _audiences.delete_audience(audience_id, as_json=as_json)
    _auto_log("audience_delete", audience_id, campaign_id=audience_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Deleted audience {audience_id}", fg="green")


# ── Commerce (Catalog / Product Feed / Products) ─────────────
# Wraps mads_lib/commerce.py (pure Graph API client functions, no Click of
# its own — see the NOTE near the top imports).


@cli.group()
def commerce():
    """Commerce Manager: catalogs, product feeds, products, batch updates."""
    pass


@commerce.command("create-catalog")
@click.argument("name")
@click.option("--vertical", default="commerce")
@click.option("--business-id", default=None, help="Override META_BUSINESS_ID.")
@click.option("--business-metadata", default=None, help="JSON object, e.g. {\"page_id\": \"...\"}.")
@click.option("--parent-catalog-id", default=None)
@click.option("--catalog-segment-filter", default=None, help="JSON-encoded filter.")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def commerce_create_catalog(name, vertical, business_id, business_metadata, parent_catalog_id,
                             catalog_segment_filter, dry_run, yes, as_json):
    """Create a ProductCatalog owned by a Business Manager."""
    enforce_allowed_caller()
    meta = None
    if business_metadata:
        try:
            meta = _json.loads(business_metadata)
        except _json.JSONDecodeError as e:
            raise SystemExit(print_error(f"--business-metadata is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
    if not _confirm_and_log(f"create catalog '{name}' [{vertical}]", "commerce create-catalog", dry_run, yes):
        return
    result = _commerce.create_catalog(
        name, vertical=vertical, business_id=business_id, business_metadata=meta,
        parent_catalog_id=parent_catalog_id, catalog_segment_filter=catalog_segment_filter, as_json=as_json,
    )
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("commerce_create_catalog", f"'{name}' [{vertical}]", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created catalog '{name}' → id {new_id or '?'}", fg="green")


@commerce.command("create-feed")
@click.argument("catalog_id")
@click.argument("name")
@click.option("--feed-type", default="PRODUCTS", type=click.Choice(["PRODUCTS", "PRODUCT_RATINGS_AND_REVIEWS"]))
@click.option("--country", default="AE", help="Must be set explicitly — Meta defaults to US if omitted.")
@click.option("--default-currency", default="AED", help="Must be set explicitly — Meta defaults to USD if omitted.")
@click.option("--deletion-enabled", type=bool, default=None, help="Gotcha: cannot be disabled once enabled.")
@click.option("--delimiter", default=None)
@click.option("--encoding", default=None)
@click.option("--schedule", default=None, help="JSON-encoded ProductFeedSchedule (full-replace fetch).")
@click.option("--update-schedule", default=None, help="JSON-encoded ProductFeedSchedule (never deletes).")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def commerce_create_feed(catalog_id, name, feed_type, country, default_currency, deletion_enabled,
                          delimiter, encoding, schedule, update_schedule, dry_run, yes, as_json):
    """Create a ProductFeed under a catalog."""
    enforce_allowed_caller()
    if not _confirm_and_log(f"create feed '{name}' on catalog {catalog_id}", "commerce create-feed", dry_run, yes):
        return
    result = _commerce.create_product_feed(
        catalog_id, name, feed_type=feed_type, country=country, default_currency=default_currency,
        deletion_enabled=deletion_enabled, delimiter=delimiter, encoding=encoding,
        schedule=schedule, update_schedule=update_schedule, as_json=as_json,
    )
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("commerce_create_feed", f"'{name}' on {catalog_id}", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created feed '{name}' → id {new_id or '?'}", fg="green")


@commerce.command("upload-feed")
@click.argument("feed_id")
@click.option("--url", default=None, help="Meta fetches the file server-side.")
@click.option("--file", "file_path", default=None, type=click.Path(exists=True), help="Local file, uploaded directly.")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def commerce_upload_feed(feed_id, url, file_path, dry_run, yes, as_json):
    """Trigger a one-off feed upload (pass exactly one of --url or --file)."""
    enforce_allowed_caller()
    if bool(url) == bool(file_path):
        raise SystemExit(print_error("Pass exactly one of --url or --file.", code="VALIDATION", as_json=as_json))
    if not _confirm_and_log(f"upload feed {feed_id}", "commerce upload-feed", dry_run, yes):
        return
    result = _commerce.upload_feed(feed_id, url=url, file_path=file_path, as_json=as_json)
    _auto_log("commerce_upload_feed", feed_id, campaign_id=feed_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Uploaded feed {feed_id}", fg="green")
    print_json(result)


@commerce.command("create-product")
@click.argument("catalog_id")
@click.argument("retailer_id")
@click.argument("name")
@click.argument("currency")
@click.argument("price", type=int)
@click.argument("image_url")
@click.option("--url", default=None)
@click.option("--availability", default="in stock",
              type=click.Choice(["in stock", "out of stock", "preorder", "available for order",
                                  "discontinued", "pending", "mark_as_sold", "mark_as_expired"]))
@click.option("--condition", default="new",
              type=click.Choice(["new", "refurbished", "used", "used_like_new", "used_good", "used_fair", "cpo", "open_box_new"]))
@click.option("--brand", default=None)
@click.option("--description", default=None)
@click.option("--gtin", default=None)
@click.option("--manufacturer-part-number", default=None)
@click.option("--category", default=None)
@click.option("--product-type", default=None)
@click.option("--allow-upsert/--no-allow-upsert", default=True)
@click.option("--visibility", default="published")
@click.option("--commerce-tax-category", default=None)
@click.option("--additional-image-urls", default=None, help="Comma-separated URLs.")
@click.option("--custom-labels", default=None, help="Comma-separated, up to 5.")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def commerce_create_product(catalog_id, retailer_id, name, currency, price, image_url, url,
                             availability, condition, brand, description, gtin,
                             manufacturer_part_number, category, product_type, allow_upsert,
                             visibility, commerce_tax_category, additional_image_urls,
                             custom_labels, dry_run, yes, as_json):
    """Create (or upsert) a single ProductItem directly. PRICE is in minor units (e.g. 599 = 5.99)."""
    enforce_allowed_caller()
    if not _confirm_and_log(f"create product '{retailer_id}' on catalog {catalog_id}", "commerce create-product", dry_run, yes):
        return
    result = _commerce.create_product(
        catalog_id, retailer_id, name, currency, price, image_url, url=url,
        availability=availability, condition=condition, brand=brand, description=description,
        gtin=gtin, manufacturer_part_number=manufacturer_part_number, category=category,
        product_type=product_type, allow_upsert=allow_upsert, visibility=visibility,
        commerce_tax_category=commerce_tax_category,
        additional_image_urls=[u.strip() for u in additional_image_urls.split(",")] if additional_image_urls else None,
        custom_labels=[c.strip() for c in custom_labels.split(",")] if custom_labels else None,
        as_json=as_json,
    )
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("commerce_create_product", f"'{retailer_id}' on {catalog_id}", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created product '{retailer_id}' → id {new_id or '?'}", fg="green")


@commerce.command("list-products")
@click.argument("catalog_id")
@click.option("--fields", default=None)
@click.option("--limit", "-l", type=int, default=None)
@click.option("--after", default=None)
@click.option("--filter", "filter_json", default=None, help="JSON-encoded WCA-style filter rule.")
@click.option("--error-priority", type=click.Choice(["HIGH", "MEDIUM", "LOW"]), default=None)
@click.option("--error-type", default=None, help="e.g. EMPTY_PRICE, IMAGE_RESOLUTION_LOW, MISSING_TAX_CATEGORY.")
@click.option("--return-only-approved/--no-return-only-approved", "return_only_approved_products", default=None)
@click.option("--json", "as_json", is_flag=True)
def commerce_list_products(catalog_id, fields, limit, after, filter_json, error_priority,
                            error_type, return_only_approved_products, as_json):
    """List products in a catalog."""
    result = _commerce.list_products(
        catalog_id, fields=fields, limit=limit, after=after, filter_json=filter_json,
        error_priority=error_priority, error_type=error_type,
        return_only_approved_products=return_only_approved_products, as_json=as_json,
    )
    if as_json:
        print_json(result)
        return
    rows = result.get("data", []) if isinstance(result, dict) else []
    if not rows:
        click.echo("  (no products)")
        return
    print_table([flatten(r) for r in rows])
    click.echo(f"\n  {len(rows)} product(s)")


@commerce.command("batch-update")
@click.argument("catalog_id")
@click.argument("operations_json")
@click.option("--item-type", default="PRODUCT_ITEM")
@click.option("--allow-upsert/--no-allow-upsert", default=True)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def commerce_batch_update(catalog_id, operations_json, item_type, allow_upsert, dry_run, yes, as_json):
    """Bulk create/update/delete catalog items. OPERATIONS_JSON is a JSON array of
    {"method": "CREATE"|"UPDATE"|"DELETE", "data": {...}} objects (max 5000)."""
    enforce_allowed_caller()
    try:
        operations = _json.loads(operations_json)
    except _json.JSONDecodeError as e:
        raise SystemExit(print_error(f"OPERATIONS_JSON is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
    if not _confirm_and_log(f"batch update {len(operations)} item(s) on catalog {catalog_id}", "commerce batch-update", dry_run, yes):
        return
    try:
        result = _commerce.batch_update_items(catalog_id, operations, item_type=item_type,
                                               allow_upsert=allow_upsert, as_json=as_json)
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    _auto_log("commerce_batch_update", f"{catalog_id}: {len(operations)} op(s)", campaign_id=catalog_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Batch update submitted for catalog {catalog_id}", fg="green")
    print_json(result)


@commerce.command("batch-status")
@click.argument("catalog_id")
@click.argument("handle")
@click.option("--load-invalid-ids/--no-load-invalid-ids", "load_ids_of_invalid_requests", default=True)
@click.option("--json", "as_json", is_flag=True)
def commerce_batch_status(catalog_id, handle, load_ids_of_invalid_requests, as_json):
    """Poll the outcome of a previous `commerce batch-update` call."""
    result = _commerce.check_batch_status(catalog_id, handle,
                                           load_ids_of_invalid_requests=load_ids_of_invalid_requests, as_json=as_json)
    if as_json:
        print_json(result)
        return
    print_json(result)


# ── CAPI (Conversions API — pixels/datasets + server events) ─
# Wraps mads_lib/capi.py (pure Graph API client functions, no Click of its
# own — see the NOTE near the top imports).


@cli.group()
def capi():
    """Conversions API: pixel/dataset management, server-side events."""
    pass


@capi.command("create-pixel")
@click.argument("name")
@click.option("--ad-account-id", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def capi_create_pixel(name, ad_account_id, dry_run, yes, as_json):
    """Create a Pixel/Dataset under an ad account."""
    if not _confirm_and_log(f"create pixel '{name}'", "capi create-pixel", dry_run, yes):
        return
    result = _capi.create_pixel(name, ad_account_id=ad_account_id, as_json=as_json)
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("capi_create_pixel", f"'{name}'", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created pixel '{name}' → id {new_id or '?'}", fg="green")


@capi.command("create-dataset")
@click.argument("name")
@click.option("--ad-account-id", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def capi_create_dataset(name, ad_account_id, dry_run, yes, as_json):
    """Create a "dataset" — semantically identical to `capi create-pixel`."""
    if not _confirm_and_log(f"create dataset '{name}'", "capi create-dataset", dry_run, yes):
        return
    result = _capi.create_dataset(name, ad_account_id=ad_account_id, as_json=as_json)
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("capi_create_dataset", f"'{name}'", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created dataset '{name}' → id {new_id or '?'}", fg="green")


@capi.command("list-pixels")
@click.option("--ad-account-id", default=None)
@click.option("--business-id", default=None, help="If set, list pixels/datasets the Business has access to.")
@click.option("--fields", default=_capi.DEFAULT_PIXEL_FIELDS)
@click.option("--id-filter", default=None)
@click.option("--name-filter", default=None)
@click.option("--json", "as_json", is_flag=True)
def capi_list_pixels(ad_account_id, business_id, fields, id_filter, name_filter, as_json):
    """List pixels/datasets."""
    result = _capi.list_pixels(ad_account_id=ad_account_id, business_id=business_id, fields=fields,
                                id_filter=id_filter, name_filter=name_filter, as_json=as_json)
    if as_json:
        print_json(result)
        return
    rows = result.get("data", []) if isinstance(result, dict) else []
    if not rows:
        click.echo("  (no pixels)")
        return
    print_table([flatten(r) for r in rows])
    click.echo(f"\n  {len(rows)} pixel(s)")


@capi.command("send-event")
@click.argument("pixel_id")
@click.argument("events_json")
@click.option("--test-event-code", default=None, help="Routes events into Events Manager → Test Events (still counts live).")
@click.option("--namespace-id", default=None)
@click.option("--partner-agent", default=None)
@click.option("--upload-tag", default=None)
@click.option("--auto-hash-user-data", is_flag=True, help="Run each event's user_data through hash_user_data() first.")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def capi_send_event(pixel_id, events_json, test_event_code, namespace_id, partner_agent,
                     upload_tag, auto_hash_user_data, dry_run, yes, as_json):
    """Send one or more server-side Conversions API events.

    EVENTS_JSON is a JSON array of event objects, each needing at minimum
    event_name, event_time, user_data, action_source.
    """
    enforce_allowed_caller()
    try:
        events = _json.loads(events_json)
    except _json.JSONDecodeError as e:
        raise SystemExit(print_error(f"EVENTS_JSON is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
    if not _confirm_and_log(f"send {len(events)} event(s) to pixel {pixel_id}", "capi send-event", dry_run, yes):
        return
    try:
        result = _capi.send_event(
            pixel_id, events, test_event_code=test_event_code, namespace_id=namespace_id,
            partner_agent=partner_agent, upload_tag=upload_tag,
            auto_hash_user_data=auto_hash_user_data, as_json=as_json,
        )
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    _auto_log("capi_send_event", f"{pixel_id}: {len(events)} event(s)", campaign_id=pixel_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Sent {len(events)} event(s) to pixel {pixel_id}", fg="green")
    print_json(result)


@capi.command("test-event")
@click.argument("pixel_id")
@click.argument("events_json")
@click.argument("test_event_code")
@click.option("--auto-hash-user-data", is_flag=True)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def capi_test_event(pixel_id, events_json, test_event_code, auto_hash_user_data, dry_run, yes, as_json):
    """Send events through the Test Events tool (send-event with TEST_EVENT_CODE required)."""
    try:
        events = _json.loads(events_json)
    except _json.JSONDecodeError as e:
        raise SystemExit(print_error(f"EVENTS_JSON is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
    if not _confirm_and_log(f"send {len(events)} test event(s) to pixel {pixel_id}", "capi test-event", dry_run, yes):
        return
    try:
        result = _capi.test_event(pixel_id, events, test_event_code,
                                   auto_hash_user_data=auto_hash_user_data, as_json=as_json)
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    _auto_log("capi_test_event", f"{pixel_id}: {len(events)} event(s)", campaign_id=pixel_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Sent {len(events)} test event(s) to pixel {pixel_id}", fg="green")
    print_json(result)


@capi.command("hash-user-data")
@click.argument("user_data_json")
@click.option("--already-hashed", is_flag=True, help="Pass through unchanged instead of hashing.")
@click.option("--json", "as_json", is_flag=True)
def capi_hash_user_data(user_data_json, already_hashed, as_json):
    """Normalize + SHA-256 hash a user_data JSON object per CAPI hashing rules (local only, no API call)."""
    try:
        user_data = _json.loads(user_data_json)
    except _json.JSONDecodeError as e:
        raise SystemExit(print_error(f"USER_DATA_JSON is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
    result = _capi.hash_user_data(user_data, already_hashed=already_hashed)
    print_json(result)


# ── Analyze (read-only analysis commands) ────────────────────
# mads_lib/analyze/*.py exposes only analyze_*()/render_*() functions with no
# Click group (see the NOTE near the top imports) — mirrors gads-cli's
# gads_lib/cli.py `analyze` group exactly: thin per-analysis subcommand,
# lazy-imported inline.


@cli.group()
def analyze():
    """Read-only analysis: audit, budget pacing, creative fatigue, audience overlap, placements, ad copy."""
    pass


@analyze.command("audit")
@click.option("--ad-account-id", default=None, help="Override META_AD_ACCOUNT_ID.")
@click.option("--days", "-d", type=int, default=30, help="Lookback window ending yesterday.")
@click.option("--json", "as_json", is_flag=True)
def analyze_audit_cmd(ad_account_id, days, as_json):
    """5-section structural-compliance audit: scoring 0-100 weighted overall.

    Checks: creative count, creative quality, audience setup, CAPI configured,
    budget pacing.
    """
    from mads_lib.analyze.audit import analyze_audit, render_audit
    result = analyze_audit(ad_account_id=ad_account_id, days=days)
    render_audit(result, as_json=as_json)


@analyze.command("budget-pacing")
@click.option("--ad-account-id", default=None)
@click.option("--days", "-d", type=int, default=30, help="Lifetime-budget spend-to-date lookback window.")
@click.option("--json", "as_json", is_flag=True)
def analyze_budget_pacing_cmd(ad_account_id, days, as_json):
    """Pacing status for every active, budgeted campaign/ad set."""
    from mads_lib.analyze.budget_pacing import analyze_budget_pacing, render_budget_pacing
    result = analyze_budget_pacing(ad_account_id=ad_account_id, days=days)
    render_budget_pacing(result, as_json=as_json)


@analyze.command("creative-fatigue")
@click.option("--ad-account-id", default=None)
@click.option("--days", "-d", type=int, default=14, help="Lookback window ending yesterday.")
@click.option("--level", type=click.Choice(["ad", "adset"]), default="ad")
@click.option("--frequency-threshold", type=float, default=3.0, help="Flag if avg frequency >= this.")
@click.option("--ctr-decay-pct", type=float, default=20.0, help="Flag if 2nd-half CTR is down this %% or more vs. 1st half.")
@click.option("--json", "as_json", is_flag=True)
def analyze_creative_fatigue_cmd(ad_account_id, days, level, frequency_threshold, ctr_decay_pct, as_json):
    """Detect frequency- and CTR-decay-based creative fatigue."""
    from mads_lib.analyze.creative_fatigue import analyze_creative_fatigue, render_creative_fatigue
    result = analyze_creative_fatigue(ad_account_id=ad_account_id, days=days, level=level,
                                       frequency_threshold=frequency_threshold, ctr_decay_pct=ctr_decay_pct)
    render_creative_fatigue(result, as_json=as_json)


@analyze.command("audience-overlap")
@click.option("--ad-account-id", default=None)
@click.option("--json", "as_json", is_flag=True)
def analyze_audience_overlap_cmd(ad_account_id, as_json):
    """Flag structural Custom Audience overlap/cannibalization risk."""
    from mads_lib.analyze.audience_overlap import analyze_audience_overlap, render_audience_overlap
    result = analyze_audience_overlap(ad_account_id=ad_account_id)
    render_audience_overlap(result, as_json=as_json)


@analyze.command("ad-copy")
@click.option("--ad-account-id", default=None)
@click.option("--campaign-id", default=None, help="Restrict to one campaign's ads.")
@click.option("--adset-id", default=None, help="Restrict to one ad set's ads (wins over --campaign-id).")
@click.option("--violations-only", is_flag=True, help="Only show ads with rule violations.")
@click.option("--json", "as_json", is_flag=True)
def analyze_adcopy_cmd(ad_account_id, campaign_id, adset_id, violations_only, as_json):
    """Validate Meta ad creative text against Talas business rules (PARTS ONLY, Tesla-not-EV, branch phones)."""
    from mads_lib.analyze.adcopy import analyze_adcopy, render_adcopy
    result = analyze_adcopy(ad_account_id=ad_account_id, campaign_id=campaign_id, adset_id=adset_id)
    render_adcopy(result, as_json=as_json, violations_only=violations_only)


@analyze.command("placement-breakdown")
@click.option("--ad-account-id", default=None)
@click.option("--days", "-d", type=int, default=14, help="Lookback window ending yesterday.")
@click.option("--level", type=click.Choice(["account", "campaign"]), default="campaign")
@click.option("--campaign-id", default=None, help="Restrict to one campaign (requires --level=campaign).")
@click.option("--json", "as_json", is_flag=True)
def analyze_placement_breakdown_cmd(ad_account_id, days, level, campaign_id, as_json):
    """Spend/CTR/CPC/CPM split by publisher_platform."""
    from mads_lib.analyze.placement_breakdown import analyze_placement_breakdown, render_placement_breakdown
    try:
        result = analyze_placement_breakdown(ad_account_id=ad_account_id, days=days, level=level, campaign_id=campaign_id)
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    render_placement_breakdown(result, as_json=as_json)


# ── Post (Facebook Page + Instagram organic content) ─────────
# Wraps mads_lib/posts.py (pure Graph API client functions, no Click of its own —
# see the NOTE near the top imports).


def _read_caption_file(path, as_json):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise SystemExit(print_error(f"Could not read {path}: {e}", code="VALIDATION", as_json=as_json))


@cli.group()
def post():
    """Facebook Page + Instagram organic content: create/list/delete posts."""
    pass


@post.command("create")
@click.option("--page-id", required=True)
@click.option("--message", default=None)
@click.option("--caption-file", default=None, type=click.Path(exists=True, dir_okay=False), help="Read --message from a file instead.")
@click.option("--link", default=None)
@click.option("--schedule-time", type=int, default=None, help="Unix timestamp; feed posts allow 10min-30day out.")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def post_create(page_id, message, caption_file, link, schedule_time, dry_run, yes, as_json):
    """POST /{page-id}/feed — create a Facebook Page post. Requires `pages_manage_posts`."""
    enforce_allowed_caller()
    if message and caption_file:
        raise SystemExit(print_error("Pass at most one of --message/--caption-file.", code="VALIDATION", as_json=as_json))
    if caption_file:
        message = _read_caption_file(caption_file, as_json)
    if not message and not link:
        raise SystemExit(print_error(
            "At least one of --message/--caption-file or --link is required.", code="VALIDATION", as_json=as_json,
        ))

    if not _confirm_and_log(f"create page post on {page_id}", "post create", dry_run, yes):
        return
    try:
        result = _posts.create_page_post(
            page_id, message=message, link=link, scheduled_publish_time=schedule_time, as_json=as_json,
        )
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("post_create", f"page {page_id}", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created post on page {page_id} → id {new_id or '?'}", fg="green")


@post.command("create-ig")
@click.option("--ig-account-id", required=True)
@click.option("--page-id", default=None, help="Facebook Page linked to this IG account; auto-resolved via GET /me/accounts if omitted.")
@click.option("--caption", default=None)
@click.option("--caption-file", default=None, type=click.Path(exists=True, dir_okay=False), help="Read --caption from a file instead.")
@click.option("--image-url", default=None)
@click.option("--video-url", default=None)
@click.option("--media-type", type=click.Choice(_posts.VALID_IG_MEDIA_TYPES), default="IMAGE")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def post_create_ig(ig_account_id, page_id, caption, caption_file, image_url, video_url, media_type, dry_run, yes, as_json):
    """2-step Instagram publish: POST /{ig-user-id}/media then POST /{ig-user-id}/media_publish.

    Requires `instagram_basic` + `instagram_content_publish`. If step 2 (publish) fails
    after step 1 (container) already succeeded, the error output includes the orphaned
    `creation_id` so it isn't silently lost — Meta expires unpublished containers ~24h
    after creation.
    """
    enforce_allowed_caller()
    if caption and caption_file:
        raise SystemExit(print_error("Pass at most one of --caption/--caption-file.", code="VALIDATION", as_json=as_json))
    if caption_file:
        caption = _read_caption_file(caption_file, as_json)
    if bool(image_url) == bool(video_url):
        raise SystemExit(print_error("Pass exactly one of --image-url/--video-url.", code="VALIDATION", as_json=as_json))

    if not _confirm_and_log(f"create + publish Instagram media on {ig_account_id}", "post create-ig", dry_run, yes):
        return

    try:
        container = _posts.create_ig_container(
            ig_account_id, caption=caption, image_url=image_url, video_url=video_url,
            media_type=media_type, page_id=page_id, as_json=as_json,
        )
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))

    creation_id = container.get("id", "") if isinstance(container, dict) else ""
    if not creation_id:
        raise SystemExit(print_error(
            f"create_ig_container succeeded but returned no id — full response: {container}",
            code="API", as_json=as_json,
        ))

    try:
        published = _posts.publish_ig_container(ig_account_id, creation_id, page_id=page_id, as_json=as_json)
    except SystemExit as exc:
        raise SystemExit(print_error(
            f"Instagram container {creation_id} was created but publish failed (see error "
            f"above) — it is orphaned, not yet published, and expires ~24h from creation. "
            f"creation_id={creation_id}",
            code="API", exit_code=exc.code, as_json=as_json,
        ))

    _auto_log("post_create_ig", f"ig {ig_account_id}", campaign_id=creation_id)
    if as_json:
        print_json({"creation_id": creation_id, "publish_result": published})
        return
    click.secho(f"✓ Published Instagram media on {ig_account_id} (creation_id={creation_id})", fg="green")


@post.command("list")
@click.option("--page-id", default=None)
@click.option("--ig-account-id", default=None)
@click.option("--limit", "-l", type=int, default=25)
@click.option("--json", "as_json", is_flag=True)
def post_list(page_id, ig_account_id, limit, as_json):
    """List recent posts (Facebook feed) or media (Instagram)."""
    if bool(page_id) == bool(ig_account_id):
        raise SystemExit(print_error("Pass exactly one of --page-id/--ig-account-id.", code="VALIDATION", as_json=as_json))
    object_id = page_id or ig_account_id
    platform = "facebook" if page_id else "instagram"
    result = _posts.list_posts(object_id, platform=platform, limit=limit, as_json=as_json)
    if as_json:
        print_json(result)
        return
    rows = result.get("data", []) if isinstance(result, dict) else []
    if not rows:
        click.echo("  (no posts)")
        return
    print_table([flatten(r) for r in rows])
    click.echo(f"\n  {len(rows)} post(s)")


@post.command("delete")
@click.argument("post_id")
@click.option("--page-id", required=True)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def post_delete(post_id, page_id, dry_run, yes, as_json):
    """DELETE /{post-id} — delete a Facebook Page post (FB only, see posts.delete_post())."""
    enforce_allowed_caller()
    if not _confirm_and_log(f"delete post {post_id}", "post delete", dry_run, yes):
        return
    result = _posts.delete_post(post_id, page_id, as_json=as_json)
    _auto_log("post_delete", post_id, campaign_id=post_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Deleted post {post_id}", fg="green")


# ── Comment (Facebook Page + Instagram comment moderation) ───
# Wraps mads_lib/comments.py (pure Graph API client functions, no Click of its own —
# see the NOTE near the top imports).


@cli.group()
def comment():
    """Facebook Page + Instagram comment moderation: list/reply/hide/delete."""
    pass


@comment.command("list")
@click.option("--post-id", default=None)
@click.option("--media-id", default=None)
@click.option("--limit", "-l", type=int, default=25)
@click.option("--json", "as_json", is_flag=True)
def comment_list(post_id, media_id, limit, as_json):
    """GET /{object-id}/comments — list comments on a Facebook post or Instagram media."""
    if bool(post_id) == bool(media_id):
        raise SystemExit(print_error("Pass exactly one of --post-id/--media-id.", code="VALIDATION", as_json=as_json))
    object_id = post_id or media_id
    result = _comments.list_comments(object_id, limit=limit, as_json=as_json)
    if as_json:
        print_json(result)
        return
    rows = result.get("data", []) if isinstance(result, dict) else []
    if not rows:
        click.echo("  (no comments)")
        return
    print_table([flatten(r) for r in rows])
    click.echo(f"\n  {len(rows)} comment(s)")


@comment.command("reply")
@click.option("--post-id", default=None, help="New top-level FB comment (FB only).")
@click.option("--comment-id", default=None, help="Threaded reply (FB + IG).")
@click.option("--message", required=True)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def comment_reply(post_id, comment_id, message, dry_run, yes, as_json):
    """Post a new top-level FB comment (--post-id) or a threaded reply (--comment-id)."""
    enforce_allowed_caller()
    if bool(post_id) == bool(comment_id):
        raise SystemExit(print_error("Pass exactly one of --post-id/--comment-id.", code="VALIDATION", as_json=as_json))

    if not _confirm_and_log(f"reply to {post_id or comment_id}", "comment reply", dry_run, yes):
        return
    try:
        result = _comments.reply_comment(post_id=post_id, comment_id=comment_id, message=message, as_json=as_json)
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("comment_reply", f"{post_id or comment_id}", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Posted comment → id {new_id or '?'}", fg="green")


@comment.command("hide")
@click.argument("comment_id")
@click.option("--unhide", is_flag=True, help="Unhide instead of hide.")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def comment_hide(comment_id, unhide, dry_run, yes, as_json):
    """POST /{comment-id} with is_hidden — hide or unhide a comment."""
    enforce_allowed_caller()
    action = "unhide" if unhide else "hide"
    if not _confirm_and_log(f"{action} comment {comment_id}", f"comment {action}", dry_run, yes):
        return
    result = _comments.hide_comment(comment_id, hide=not unhide, as_json=as_json)
    _auto_log(f"comment_{action}", comment_id, campaign_id=comment_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ {'Unhid' if unhide else 'Hid'} comment {comment_id}", fg="green")


@comment.command("delete")
@click.argument("comment_id")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def comment_delete(comment_id, dry_run, yes, as_json):
    """DELETE /{comment-id} — permanently delete a comment."""
    enforce_allowed_caller()
    if not _confirm_and_log(f"delete comment {comment_id}", "comment delete", dry_run, yes):
        return
    result = _comments.delete_comment(comment_id, as_json=as_json)
    _auto_log("comment_delete", comment_id, campaign_id=comment_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Deleted comment {comment_id}", fg="green")


# ── KB (Knowledge Base — API version drift detection and KB surfacing) ──
# Wraps mads_lib/kb.py (pure functions, no Click of its own — see the NOTE
# near the top imports). Mirrors gads-cli's `gads kb check/list/show`.


@cli.group()
def kb():
    """Knowledge Base — API version drift detection and KB surfacing."""
    pass


@kb.command("check")
@click.option("--json", "as_json", is_flag=True)
def kb_check_cmd(as_json):
    """Compare code API version against kb/manifest.json. Exits non-zero on drift."""
    results = check_drift()
    if as_json:
        return print_json(results)
    click.secho("\n  KB Drift Check\n", fg="white", bold=True)
    slug_width = max((len(r["slug"]) for r in results), default=15)
    for r in results:
        status = r["status"]
        color = "red" if r["drift"] else "green"
        click.secho(
            f"  [{status}] {r['slug']:{slug_width}s} manifest={r['manifest_version']:8s} code={r['code_version']:8s}  {r['api']}",
            fg=color,
        )
    drifts = [r for r in results if r["drift"]]
    click.echo()
    if drifts:
        click.secho(f"  {len(drifts)} DRIFT(S) detected. Update kb/<api>.md + manifest.json when bumping API versions.", fg="red")
        raise SystemExit(1)
    else:
        click.secho("  All API versions aligned with KB manifest.", fg="green")


@kb.command("list")
@click.option("--json", "as_json", is_flag=True)
def kb_list_cmd(as_json):
    """List all KB files with their API coverage."""
    files = list_kb_files()
    if as_json:
        return print_json(files)
    rows = [{"file": f["file"], "api": f["api"][:40], "exists": f["exists"], "size_bytes": f["size_bytes"]} for f in files]
    print_table(rows, ["file", "api", "exists", "size_bytes"])


@kb.command("show")
@click.argument("api")
def kb_show_cmd(api):
    """Show KB documentation for an API (by slug or filename)."""
    try:
        content = show_kb_file(api)
        click.echo(content)
    except FileNotFoundError as e:
        click.secho(f"✗ {e}", fg="red", err=True)
        manifest = load_manifest()
        slugs = sorted(set(entry["slug"] for entry in manifest))
        click.echo(f"  Available slugs: {', '.join(slugs)}", err=True)
        raise SystemExit(1)


# ── Group registration (audience/commerce/capi/analyze/post/comment/kb) ─
cli.add_command(audience)
cli.add_command(commerce)
cli.add_command(capi)
cli.add_command(analyze)
cli.add_command(post)
cli.add_command(comment)
cli.add_command(kb)


def main():
    """Entry point with a structured error envelope and stable exit codes.

    On failure, emits {"error": {...}} JSON to stderr when --json was requested,
    otherwise a colored message. Honors meaningful exit codes from EXIT_CODES
    (including the mads-cli-specific RATE_LIMIT=8).
    """
    want_json = "--json" in sys.argv
    try:
        cli(standalone_mode=False)
    except SystemExit:
        # Honor explicit exit codes raised by commands (already printed).
        raise
    except click.exceptions.Abort:
        raise SystemExit(EXIT_CODES["GENERAL"])
    except click.exceptions.UsageError as e:
        # Preserve Click's own formatting on stderr, then exit with USAGE code.
        e.show()
        raise SystemExit(EXIT_CODES["USAGE"])
    except click.ClickException as e:
        raise SystemExit(print_error(e.format_message(), code="GENERAL", as_json=want_json))
    except Exception as e:  # noqa: BLE001 — top-level safety net
        code = "GENERAL"
        msg = str(e).lower()
        if "auth" in msg or "credential" in msg or "token" in msg or "401" in msg:
            code = "AUTH"
        elif "not found" in msg or "404" in msg:
            code = "NOT_FOUND"
        elif "rate" in msg or "429" in msg:
            code = "RATE_LIMIT"
        elif "403" in msg or "api" in msg or "quota" in msg:
            code = "API"
        raise SystemExit(print_error(f"{type(e).__name__}: {e}", code=code, as_json=want_json))
