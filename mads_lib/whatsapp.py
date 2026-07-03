"""WhatsApp Business Platform (Cloud API) — waba/phone-number/template/webhook commands.

**This is a SEPARATE Meta product from the Marketing API / Graph API surface the rest of
mads-cli covers (campaigns/ad sets/ads/creatives/audiences/commerce/CAPI/pages/business).**
Nothing elsewhere in this CLI implies WhatsApp coverage — the WhatsApp Business Platform
(Cloud API) is its own product line with its own onboarding, its own node type (a
WhatsApp Business Account, "WABA"), and its own endpoint family under the same
`graph.facebook.com/{API_VERSION}` host. This module wraps that endpoint family; it does
NOT touch WhatsApp click-to-chat ad destinations (those already work today via the normal
`ad`/`creative` commands and a `wa.me`/`whatsapp://` destination URL — no special module
needed for that).

**This module is management/analytics-only by design, not a messaging integration.** It
wraps WABA/phone-number reads, message-template list/create, and account-level webhook
subscription (template/quality-rating change notifications) — it deliberately does NOT wrap
`POST /{phone-number-id}/messages` (sending template or free-form messages). That endpoint
requires the separate `whatsapp_business_messaging` OAuth scope; every command in this
module needs only `whatsapp_business_management`, which is all Talas has ever needed
(reading template/quality-rating/WABA state, not sending or receiving messages). See
`kb/whatsapp-business-platform.md` for the scope rationale.

## Prerequisite: WABA + coexistence onboarding — NOT YET DONE for Talas

Every command below that needs `--waba-id` (or `META_WABA_ID`) requires a WhatsApp
Business Account already onboarded through the same Meta App already used for the rest of
mads-cli (`META_APP_ID` in talas-ads/.env). **This onboarding is an account-level,
Meta-eligibility-gated step that cannot be completed by writing code** — it happens via
Meta's Embedded Signup flow or a Tech/Solution Provider, not an API call this CLI can make
on your behalf.

Talas has 3 branches (QZ3, IND4, SJA), each already running its own consumer WhatsApp
number on the regular WhatsApp Business App. Getting *real per-branch attribution* out of
this module requires **"coexistence" onboarding** for each of those 3 numbers — migrating
an existing number onto the Cloud API while keeping the WhatsApp Business App usable in
parallel (as opposed to a fresh Cloud-API-only number with no history). This is real,
Tech/Solution-Provider-mediated, per-number account work; **none of it has been done yet**.
Every command in this module is built assuming that prerequisite will eventually be
satisfied — running any command that needs `--waba-id` today will fail with a clear
VALIDATION error (`META_WABA_ID is not set`), not a crash, because `WABA_ID` is optional
config (see `config.py`). **The code existing here does not make WhatsApp live for Talas.**

## Conversation Analytics is deprecated — use `pricing_analytics`

The old "Conversation Analytics" API (per-conversation, per-category message-volume
counters) was deprecated as part of Meta's July 2025 WhatsApp pricing model change (a
shift from per-conversation to per-message pricing). Its replacement,
`pricing_analytics`, is billing-shaped (message-level pricing/cost breakdowns), not a
drop-in message counter — do not assume it answers "how many conversations did we have"
the same way the old API did. No `whatsapp` command in this module wraps
`pricing_analytics` yet (out of scope for this pass — this module covers WABA/phone-number
read, template list/create, and webhook subscribe only); add it as a dedicated command
if/when message-cost reporting is needed.

## Endpoints wrapped here

  - `GET  /{waba-id}` — WABA details                                    → `waba info`
  - `GET  /{waba-id}/phone_numbers` — registered phone numbers          → `waba phone-numbers`
  - `GET  /{phone-number-id}` — phone number details/status             → `phone-number info`
  - `GET  /{waba-id}/message_templates` — list message templates        → `template list`
  - `POST /{waba-id}/message_templates` — create a message template     → `template create`
  - `POST /{app-id}/subscriptions` (object=whatsapp_business_account)   → `webhook subscribe`

API version follows the same `API_VERSION` constant (config.py, `META_API_VERSION` env
var) every other module in this CLI uses — WhatsApp Cloud API endpoints live on the same
`graph.facebook.com/{version}` host as the Marketing/Graph API, not a separate host.
"""
import json as _json

import click

from .config import APP_ID, APP_SECRET, WABA_ID
from .db import get_db
from .http import graph_request
from .output import flatten, print_error, print_json, print_table
from .timeutil import now_local

DEFAULT_WABA_FIELDS = "id,name,timezone_id,message_template_namespace,account_review_status"
DEFAULT_PHONE_NUMBER_LIST_FIELDS = (
    "id,display_phone_number,verified_name,quality_rating,code_verification_status,"
    "platform_type,throughput"
)
DEFAULT_PHONE_NUMBER_FIELDS = (
    "id,display_phone_number,verified_name,quality_rating,code_verification_status,"
    "platform_type,throughput,messaging_limit_tier"
)
DEFAULT_TEMPLATE_FIELDS = "id,name,status,category,language,quality_score"

# Meta's current (post-2023) message template category set — AUTHENTICATION templates
# have additional restrictions (no free-form body text) not enforced client-side here.
TEMPLATE_CATEGORIES = ("AUTHENTICATION", "MARKETING", "UTILITY")


# ── Helpers (small, intentionally duplicated per resource-group module — same
# pattern mads_lib/campaigns.py, business.py, webhooks.py already use) ──────


def _require_waba_id(waba_id, as_json):
    wid = waba_id or WABA_ID
    if not wid:
        raise SystemExit(print_error(
            "META_WABA_ID is not set (or pass --waba-id). WhatsApp Business Platform "
            "commands require a WhatsApp Business Account (WABA) onboarded via coexistence "
            "or Embedded Signup — an account-level Meta prerequisite this CLI cannot "
            "complete for you. See kb/whatsapp-business-platform.md.",
            code="VALIDATION", as_json=as_json,
        ))
    return wid


def _confirm_and_log(action, details, dry_run=False, yes=False):
    if dry_run:
        click.secho(f"  DRY RUN: {action} — {details}", fg="yellow")
        return False
    if not yes:
        click.confirm(f"  Execute: {action}?", abort=True)
    return True


def _auto_log(action, details, campaign_id=""):
    """Best-effort changelog write; never raises (mirrors mads_lib.campaigns._auto_log)."""
    try:
        conn = get_db()
        ts = now_local()
        raw = {
            "timestamp": ts, "action": action, "details": details,
            "campaign": "", "campaign_id": campaign_id, "agent": "mads-cli",
        }
        conn.execute(
            "INSERT INTO changelog (timestamp, action, campaign, campaign_id, details, "
            "reason, agent, snapshot_ref, script, raw_json, platform) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, action, "", campaign_id, details, "", "mads-cli", "", "", _json.dumps(raw), "meta_ads"),
        )
        conn.commit()
        conn.close()
    except (Exception, SystemExit):
        pass


def _emit_list(result, as_json):
    rows = result.get("data", []) if isinstance(result, dict) else []
    if as_json:
        print_json(result)
        return
    print_table([flatten(r) for r in rows]) if rows else print_json(result)


@click.group()
def whatsapp():
    """WhatsApp Business Platform (Cloud API) — a SEPARATE Meta product from Ads.

    Requires a WABA onboarded via coexistence/Embedded Signup (not yet done for Talas —
    see this module's docstring and kb/whatsapp-business-platform.md before using).
    """


# ── WABA ─────────────────────────────────────────────────────


@whatsapp.group("waba")
def waba_group():
    """WhatsApp Business Account (WABA) commands."""


@waba_group.command("info")
@click.option("--waba-id", default=None, help="Override META_WABA_ID.")
@click.option("--fields", default=DEFAULT_WABA_FIELDS)
@click.option("--json", "as_json", is_flag=True)
def waba_info(waba_id, fields, as_json):
    """GET /{waba-id} — WABA details."""
    wid = _require_waba_id(waba_id, as_json)
    result = graph_request("GET", wid, params={"fields": fields}, as_json=as_json)
    if as_json:
        print_json(result)
        return
    print_table([flatten(result)])


@waba_group.command("phone-numbers")
@click.option("--waba-id", default=None, help="Override META_WABA_ID.")
@click.option("--fields", default=DEFAULT_PHONE_NUMBER_LIST_FIELDS)
@click.option("--limit", "-l", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def waba_phone_numbers(waba_id, fields, limit, as_json):
    """GET /{waba-id}/phone_numbers — list phone numbers registered to this WABA."""
    wid = _require_waba_id(waba_id, as_json)
    params = {"fields": fields}
    if limit:
        params["limit"] = limit
    result = graph_request("GET", f"{wid}/phone_numbers", params=params, as_json=as_json)
    _emit_list(result, as_json)


# ── Phone number ─────────────────────────────────────────────


@whatsapp.group("phone-number")
def phone_number_group():
    """Registered WhatsApp phone number commands."""


@phone_number_group.command("info")
@click.argument("phone_number_id")
@click.option("--fields", default=DEFAULT_PHONE_NUMBER_FIELDS)
@click.option("--json", "as_json", is_flag=True)
def phone_number_info(phone_number_id, fields, as_json):
    """GET /{phone-number-id} — phone number details/status (quality rating, verification, throughput)."""
    result = graph_request("GET", phone_number_id, params={"fields": fields}, as_json=as_json)
    if as_json:
        print_json(result)
        return
    print_table([flatten(result)])


# ── Message templates ────────────────────────────────────────


@whatsapp.group("template")
def template_group():
    """Message template commands (list existing templates, submit new ones for review)."""


@template_group.command("list")
@click.option("--waba-id", default=None, help="Override META_WABA_ID.")
@click.option("--fields", default=DEFAULT_TEMPLATE_FIELDS)
@click.option("--limit", "-l", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def template_list(waba_id, fields, limit, as_json):
    """GET /{waba-id}/message_templates — list message templates."""
    wid = _require_waba_id(waba_id, as_json)
    params = {"fields": fields}
    if limit:
        params["limit"] = limit
    result = graph_request("GET", f"{wid}/message_templates", params=params, as_json=as_json)
    _emit_list(result, as_json)


@template_group.command("create")
@click.argument("name")
@click.argument("category", type=click.Choice(TEMPLATE_CATEGORIES))
@click.argument("language")
@click.argument("components_json")
@click.option("--waba-id", default=None, help="Override META_WABA_ID.")
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def template_create(name, category, language, components_json, waba_id, dry_run, yes, as_json):
    """POST /{waba-id}/message_templates — create a message template.

    LANGUAGE is a locale code (e.g. "en_US"). COMPONENTS_JSON is a JSON array of template
    component objects (HEADER/BODY/FOOTER/BUTTONS, per Meta's Message Templates spec), e.g.
    '[{"type":"BODY","text":"Your order {{1}} has shipped."}]'. This call SUBMITS the
    template for Meta review — it does not become approved immediately; check its `status`
    via `template list`.
    """
    try:
        components = _json.loads(components_json)
    except _json.JSONDecodeError as e:
        raise SystemExit(print_error(f"COMPONENTS_JSON is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
    wid = _require_waba_id(waba_id, as_json)
    body = {"name": name, "category": category, "language": language, "components": components}

    if not _confirm_and_log(f"create template '{name}' [{category}/{language}]", _json.dumps(body), dry_run, yes):
        return
    result = graph_request("POST", f"{wid}/message_templates", json_body=body, as_json=as_json)
    new_id = result.get("id", "") if isinstance(result, dict) else ""
    _auto_log("whatsapp_template_create", f"'{name}' [{category}/{language}]", campaign_id=new_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Submitted template '{name}' for review → id {new_id or '?'}", fg="green")
    print_json(result)


# ── Webhook (WABA-object subscription — distinct from mads_lib/webhooks.py's
# ad-account subscription) ───────────────────────────────────


@whatsapp.group("webhook")
def whatsapp_webhook_group():
    """WhatsApp Business Account webhook subscription (inbound messages, status updates)."""


@whatsapp_webhook_group.command("subscribe")
@click.option("--app-id", default=None, help="Override META_APP_ID.")
@click.option("--callback-url", required=True, help="HTTPS endpoint Meta delivers WhatsApp events to — must already be verified in the App Dashboard's Webhooks product (object type 'WhatsApp Business Account').")
@click.option("--verify-token", required=True, help="Shared secret Meta echoes back during the hub.challenge verification handshake for --callback-url.")
@click.option("--fields", default="messages", help="Comma-separated webhook fields to subscribe (default 'messages' — inbound message + delivery-status callbacks).")
@click.option("--json", "as_json", is_flag=True)
def whatsapp_webhook_subscribe(app_id, callback_url, verify_token, fields, as_json):
    """POST /{app-id}/subscriptions — subscribe this app to WhatsApp Business Account webhook events.

    Distinct from mads_lib/webhooks.py's ad-account `webhook subscribe` (which subscribes
    an *ad account* to the 5 ad-health trigger fields via `POST act_{id}/subscribed_apps`)
    — this subscribes the *app itself* to WABA object callbacks
    (object=whatsapp_business_account), a separate Webhooks product configuration used for
    inbound WhatsApp message delivery, matching that module's dashboard-config-plus-API-call
    split (the App Dashboard's Webhooks product must ALSO already have "WhatsApp Business
    Account" configured as object type with --callback-url verified — this call only
    performs the app-level subscription step).

    Uses an App Access Token (`app_id|app_secret` — Meta's standard convention for
    app-level, as opposed to user-level, endpoints; see
    developers.facebook.com/docs/facebook-login/guides/access-tokens#apptokens) built from
    META_APP_ID/META_APP_SECRET, rather than the general user/system-user token this CLI
    uses elsewhere. [Not live-verified in this pass — graph_request() still appends its
    usual appsecret_proof computed over this composite token string, which is unnecessary
    for an app-token call; flagged here rather than silently assumed harmless, re-verify
    once a real callback URL exists.]
    """
    aid = app_id or APP_ID
    if not aid or not APP_SECRET:
        raise SystemExit(print_error(
            "META_APP_ID and META_APP_SECRET must both be set to subscribe app-level "
            "WhatsApp webhooks (App Access Token = app_id|app_secret).",
            code="VALIDATION", as_json=as_json,
        ))
    app_token = f"{aid}|{APP_SECRET}"
    result = graph_request(
        "POST", f"{aid}/subscriptions",
        params={
            "object": "whatsapp_business_account",
            "callback_url": callback_url,
            "verify_token": verify_token,
            "fields": fields,
        },
        token=app_token,
        as_json=as_json,
    )
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Subscribed app {aid} to whatsapp_business_account webhooks (fields={fields})", fg="green")
    print_json(result)
