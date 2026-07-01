"""Business Manager: info, ad accounts, pages, users, System Users, and tokens.

Confirmed against kb/graph-api.md ("Business Manager", "Owned vs. Client Assets (Business
Manager 2-tier model)", "System Users" sections) — real HTTP calls, not placeholders:

  - GET /{business_id} — Business node info. Field list (SDK-confirmed,
    `facebook_business/adobjects/business.py::Business.Field`): name, vertical,
    vertical_id, verification_status, primary_page, timezone_id, two_factor_type,
    payment_account_id, created_time/updated_time, created_by/updated_by, is_hidden, link,
    profile_picture_uri, block_offline_analytics,
    whatsapp_business_manager_messaging_limit, user_access_expire_time.
  - GET /{business_id}/owned_ad_accounts and /client_ad_accounts — ad accounts owned by vs.
    shared with this Business (the owned/client split underlying Meta's 2-Tier Business
    Manager partner model).
  - GET /{business_id}/owned_pages and /client_pages — same owned/client split for Pages.
  - POST /{business_id}/system_users — create a System User. `role` enum (SDK-confirmed,
    `SystemUser.Role`): ADMIN, ADS_RIGHTS_REVIEWER, DEFAULT, DEVELOPER, EMPLOYEE,
    FINANCE_ANALYST, FINANCE_EDIT, FINANCE_EDITOR, FINANCE_VIEW, MANAGE,
    PARTNER_CENTER_ADMIN, PARTNER_CENTER_ANALYST, PARTNER_CENTER_EDUCATION,
    PARTNER_CENTER_MARKETING, PARTNER_CENTER_OPERATIONS.
  - GET /{business_id}/system_users — list System Users.
  - POST /{system_user_id}/access_tokens — generate/renew a System User token. Meta has no
    separate "renew" endpoint — calling this again issues a fresh token (graph-api.md,
    "GET /oauth/access_token" section is the *refresh-a-60-day-token* flow; regenerating
    outright is the same access_tokens POST used for `generate`). `set_token_expires_in_60_days`
    defaults on here to match Meta's own security guidance — its docs call the 60-day
    expiring form "recommended" even though never-expire remains the API default (see
    graph-api.md, "60-Day vs. Never-Expire System User Tokens").

NOTE ON DUPLICATION: cli.py currently also has inline `auth system-user` / `auth token`
commands hitting these same two System-User endpoints — a stopgap wired directly into
cli.py before resource-group modules existed (see cli.py's own "Resource-group
placeholders" TODO block). This module is the intended proper home for that logic per that
TODO; cli.py itself is not modified by this change, so both copies currently exist side by
side. A follow-up should wire `business` (this module) into cli.py and drop the inline
`auth system-user`/`auth token` commands to remove the duplication.

NOT CONFIRMED in this KB pass — flagged rather than silently invented:
  - `GET /{business_id}/business_users` (human users assigned to a Business Manager,
    distinct from System Users) is a real, long-standing Meta Graph API edge under
    Business Asset Management, but it does NOT appear in kb/graph-api.md's Resources table
    (which documents only owned/client ad accounts & pages, and system_users). Included
    here as [inference from stable public Meta API convention, NOT KB-verified in this
    pass] — verify live against your own Business before relying on it in production; if
    it 404s or the field names differ, check
    developers.facebook.com/docs/marketing-api/business-asset-management for the current
    edge/field names.
"""
import click

from .config import BUSINESS_ID
from .http import graph_request
from .output import print_json, print_table, print_error, flatten

# SDK-confirmed `SystemUser.Role` enum (graph-api.md, "System Users" section).
SYSTEM_USER_ROLES = [
    "ADMIN", "ADS_RIGHTS_REVIEWER", "DEFAULT", "DEVELOPER", "EMPLOYEE",
    "FINANCE_ANALYST", "FINANCE_EDIT", "FINANCE_EDITOR", "FINANCE_VIEW", "MANAGE",
    "PARTNER_CENTER_ADMIN", "PARTNER_CENTER_ANALYST", "PARTNER_CENTER_EDUCATION",
    "PARTNER_CENTER_MARKETING", "PARTNER_CENTER_OPERATIONS",
]


def _require_business_id(business_id, as_json):
    biz = business_id or BUSINESS_ID
    if not biz:
        raise SystemExit(print_error(
            "META_BUSINESS_ID is not set (or pass --business-id).", code="VALIDATION", as_json=as_json,
        ))
    return biz


def _emit_list(result, as_json):
    rows = result.get("data", []) if isinstance(result, dict) else []
    if as_json:
        print_json(result)
        return
    print_table([flatten(r) for r in rows]) if rows else print_json(result)


@click.group()
def business():
    """Business Manager: info, ad accounts, pages, users, system users, tokens."""


@business.command("info")
@click.option("--business-id", default=None, help="Override META_BUSINESS_ID.")
@click.option("--fields", default=(
    "id,name,vertical,vertical_id,verification_status,primary_page,timezone_id,"
    "two_factor_type,link,created_time,updated_time"
))
@click.option("--json", "as_json", is_flag=True)
def business_info(business_id, fields, as_json):
    """GET /{business_id} — Business node info."""
    biz = _require_business_id(business_id, as_json)
    result = graph_request("GET", biz, params={"fields": fields}, as_json=as_json)
    if as_json:
        print_json(result)
        return
    print_table([flatten(result)])


@business.command("adaccounts")
@click.option("--business-id", default=None, help="Override META_BUSINESS_ID.")
@click.option("--type", "acct_type", type=click.Choice(["owned", "client"]), default="owned",
              help="owned_ad_accounts (created in this Business) vs client_ad_accounts (shared by a partner Business).")
@click.option("--fields", default="id,name,account_id,account_status,currency,timezone_name")
@click.option("--limit", "-l", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def business_adaccounts(business_id, acct_type, fields, limit, as_json):
    """GET /{business_id}/owned_ad_accounts or /client_ad_accounts."""
    biz = _require_business_id(business_id, as_json)
    edge = "owned_ad_accounts" if acct_type == "owned" else "client_ad_accounts"
    params = {"fields": fields}
    if limit:
        params["limit"] = limit
    result = graph_request("GET", f"{biz}/{edge}", params=params, as_json=as_json)
    _emit_list(result, as_json)


@business.command("pages")
@click.option("--business-id", default=None, help="Override META_BUSINESS_ID.")
@click.option("--type", "page_type", type=click.Choice(["owned", "client"]), default="owned",
              help="owned_pages vs client_pages.")
@click.option("--fields", default="id,name,category,link")
@click.option("--limit", "-l", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def business_pages(business_id, page_type, fields, limit, as_json):
    """GET /{business_id}/owned_pages or /client_pages."""
    biz = _require_business_id(business_id, as_json)
    edge = "owned_pages" if page_type == "owned" else "client_pages"
    params = {"fields": fields}
    if limit:
        params["limit"] = limit
    result = graph_request("GET", f"{biz}/{edge}", params=params, as_json=as_json)
    _emit_list(result, as_json)


@business.command("users")
@click.option("--business-id", default=None, help="Override META_BUSINESS_ID.")
@click.option("--fields", default="id,name,email,role")
@click.option("--json", "as_json", is_flag=True)
def business_users(business_id, fields, as_json):
    """GET /{business_id}/business_users — human users assigned to this Business.

    See module docstring: this edge is [inference from stable public Meta API convention,
    NOT confirmed in kb/graph-api.md's Resources table in this pass].
    """
    biz = _require_business_id(business_id, as_json)
    result = graph_request("GET", f"{biz}/business_users", params={"fields": fields}, as_json=as_json)
    _emit_list(result, as_json)


# ── System Users ─────────────────────────────────────────────


@business.group("system-user")
def business_system_user():
    """Business Manager System User management."""


@business_system_user.command("create")
@click.argument("name")
@click.option("--role", type=click.Choice(SYSTEM_USER_ROLES), default="EMPLOYEE")
@click.option("--business-id", default=None, help="Override META_BUSINESS_ID.")
@click.option("--json", "as_json", is_flag=True)
def system_user_create(name, role, business_id, as_json):
    """POST /{business_id}/system_users — create a System User."""
    biz = _require_business_id(business_id, as_json)
    result = graph_request("POST", f"{biz}/system_users", params={"name": name, "role": role}, as_json=as_json)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created system user '{name}' ({role})", fg="green")
    print_json(result)


@business_system_user.command("list")
@click.option("--business-id", default=None, help="Override META_BUSINESS_ID.")
@click.option("--json", "as_json", is_flag=True)
def system_user_list(business_id, as_json):
    """GET /{business_id}/system_users — list System Users."""
    biz = _require_business_id(business_id, as_json)
    result = graph_request("GET", f"{biz}/system_users", as_json=as_json)
    _emit_list(result, as_json)


# ── Tokens ───────────────────────────────────────────────────


@business.group("token")
def business_token():
    """System User access token generate/renew."""


@business_token.command("generate")
@click.argument("system_user_id")
@click.option("--scope", default="ads_management,business_management", help="Comma-separated permission scopes.")
@click.option("--expires-60-days/--no-expires-60-days", "expires_60d", default=True,
              help="Mint a 60-day expiring token (Meta's recommended default) vs a never-expiring one.")
@click.option("--json", "as_json", is_flag=True)
def token_generate(system_user_id, scope, expires_60d, as_json):
    """POST /{system_user_id}/access_tokens — generate a System User access token."""
    params = {"scope": scope}
    if expires_60d:
        params["set_token_expires_in_60_days"] = "true"
    result = graph_request("POST", f"{system_user_id}/access_tokens", params=params, as_json=as_json)
    if as_json:
        print_json(result)
        return
    click.secho("✓ Generated system user access token", fg="green")
    print_json(result)


@business_token.command("renew")
@click.argument("system_user_id")
@click.option("--json", "as_json", is_flag=True)
def token_renew(system_user_id, as_json):
    """POST /{system_user_id}/access_tokens — renew (regenerate) a System User token.

    Same endpoint as `generate` — Meta has no separate renew call; calling
    POST /{system_user_id}/access_tokens again issues a fresh token.
    """
    result = graph_request(
        "POST", f"{system_user_id}/access_tokens",
        params={"set_token_expires_in_60_days": "true"}, as_json=as_json,
    )
    if as_json:
        print_json(result)
        return
    click.secho("✓ Renewed system user access token", fg="green")
    print_json(result)
