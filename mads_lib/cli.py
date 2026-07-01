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

# ── Resource-group Click groups ──────────────────────────────
# These modules each define a `@click.group()` that is registered on the
# root `cli` group below.
from mads_lib.campaigns import campaign as campaign_group
from mads_lib.adsets import adset as adset_group
from mads_lib.ads import ad as ad_group
from mads_lib.creatives import creative as creative_group
from mads_lib.insights import insights as insights_group
from mads_lib.abtest import abtest as abtest_group
from mads_lib.business import business as business_group
from mads_lib.pages import page as page_group
from mads_lib.webhooks import webhooks as webhooks_group

# NOTE(mads-cli): audiences.py, commerce.py, and capi.py are pure Meta Graph
# API client function libraries (list_audiences/create_custom_audience/...,
# create_catalog/create_product_feed/..., create_pixel/send_event/...) — none
# of them define a `@click.group()` or any `@click.command()`. Likewise,
# mads_lib/analyze/*.py exposes only analyze_*()/render_*() functions with no
# Click group. There is nothing importable to wire for `audience`, `commerce`,
# `capi`, or `analyze` yet; a Click command layer needs to be built on top of
# those functions first (mirroring the group() + command() pattern used in
# campaigns.py/adsets.py/etc.) before they can be added here.


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
            "reason, agent, snapshot_ref, script, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, action, campaign_name, campaign_id, details, "", "mads-cli", "", "", _json.dumps(raw)),
        )
        conn.commit()
        conn.close()
    except Exception:
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
            (timestamp, action, campaign, campaign_id, details, reason, agent, snapshot_ref, script, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, action, campaign, campaign_id, details, reason, agent, snapshot_ref, script, _json.dumps(raw)),
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
    """Snapshot the current mads-cli config state.

    No campaign/ad-set/ad resource modules exist yet (see the TODOs at the
    top of this file), so there is nothing live to snapshot from the
    Marketing API. This records the current env-derived config instead.
    Once resource groups are wired in, extend this to also snapshot live
    campaign/ad set/ad configs, mirroring gads-cli's `snapshot` command.
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

    # Best-effort DB record — mads-cli owns no schema, so `snapshots` may not
    # exist yet in a fresh MADS_DB_PATH.
    try:
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?, ?)",
            (filename, ts_date, datetime.now().strftime("%H:%M:%S"), name, ""),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    written_path = None
    if save_file:
        SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = SNAPSHOTS_DIR / filename
        with open(filepath, "w") as f:
            _json.dump({"name": name, "date": ts_date, "config": config_state}, f, indent=2)
        written_path = str(filepath)

    if as_json:
        print_json({
            "saved": True, "name": name, "date": ts_date, "db_record": filename,
            "file": written_path, "config": config_state,
        })
        return
    click.secho(f"✓ Saved snapshot '{name}' (date={ts_date})", fg="green")
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
    try:
        ops = _json.loads(operations_json)
    except _json.JSONDecodeError as e:
        raise SystemExit(print_error(f"Invalid JSON: {e}", code="VALIDATION", as_json=as_json))
    if not isinstance(ops, list):
        ops = [ops]

    if not _confirm_and_log(f"mutate {resource_type} ({len(ops)} op(s))", "generic mutate", dry_run, yes):
        return

    results = [graph_request("POST", resource_type, params=op, as_json=as_json) for op in ops]
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
