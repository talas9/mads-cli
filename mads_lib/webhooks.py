"""Ad-account Webhooks — subscribe / list / unsubscribe for the 5 known trigger fields.

THIS IS NOT A GENERAL CHANGE-DETECTION STREAM. Meta's `ad_account` webhook object exposes
exactly **5** subscribable trigger fields per the official "Webhooks for Ad Accounts"
getting-started guide (kb/graph-api.md, "The 5 Trigger Fields" table):

    1. with_issues_ad_objects   — a campaign/ad set/ad enters the WITH_ISSUES status
    2. in_process_ad_objects    — a campaign/ad set/ad exits the IN_PROCESS status
    3. ad_recommendations       — Meta generates a recommendation for one of the account's ads
    4. creative_fatigue         — an ad enters/exits creative fatigue (Low/Medium/High)
    5. product_set_issue       — a catalog product set encounters an issue

These fire ONLY for the specific named conditions above. They do NOT notify on arbitrary
field changes (budget edits, status toggles you make yourself, targeting changes, etc.) the
way a generic "row changed" webhook would — do not build change-detection logic around this
module expecting broad coverage.

A 6th field, `ads_async_creation_request`, exists on the full Webhooks Reference page but is
NOT part of the getting-started 5 and is explicitly out of scope here — graph-api.md frames
it as "an optional 6th if the CLI ever needs async-creation-job callbacks," a different use
case (async batch-creation job completion, not account health).

Confirmed endpoints (kb/graph-api.md, "Ad-Account Webhooks" section):
  - Subscribe:     POST /act_{ad_account_id}/subscribed_apps   (params: app_id, access_token)
  - Verify/list:   GET  /act_{ad_account_id}/subscribed_apps

NOT CONFIRMED in this KB pass — flagged rather than silently invented:
  - `unsubscribe`: kb/graph-api.md's Resources table only transcribes `subscribe` (POST)
    and `verify` (GET) for the `subscribed_apps` edge; it does not show an explicit
    unsubscribe example. Graph API's long-standing, widely-documented convention across
    the whole subscribed_apps/webhooks edge family is that `DELETE` on the same edge
    removes the subscription. This is included as [inference from stable public Graph API
    convention, NOT KB-verified in this pass] — re-verify live against your own ad account
    (e.g. run `webhooks list` immediately after) before relying on it in production.

Setup reminder (graph-api.md Gotcha #7): a live ad-account-level subscription requires BOTH
the App Dashboard's Webhooks product configured with "Ad Account" as object type (with a
verified callback URL) AND this module's `subscribe` call per ad account — the dashboard
config alone is not sufficient.
"""
import click

from .config import AD_ACCOUNT_ID, APP_ID
from .http import graph_request
from .output import print_json, print_table, print_error, flatten

# The 5 confirmed subscribable trigger fields (graph-api.md, "The 5 Trigger Fields" table).
# Informational only — Meta subscribes the whole `ad_account` object, not individual fields,
# but this is what to expect in delivered `changes[].field` payloads.
TRIGGER_FIELDS = [
    "with_issues_ad_objects",
    "in_process_ad_objects",
    "ad_recommendations",
    "creative_fatigue",
    "product_set_issue",
]


def _normalize_account_id(account_id):
    """Ensure the `act_` prefix Meta requires on ad-account-scoped edges."""
    if not account_id:
        return account_id
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


def _require_account_id(account_id, as_json):
    acct = _normalize_account_id(account_id or AD_ACCOUNT_ID)
    if not acct:
        raise SystemExit(print_error(
            "META_AD_ACCOUNT_ID is not set (or pass --account-id).", code="VALIDATION", as_json=as_json,
        ))
    return acct


@click.group()
def webhooks():
    """Ad-account webhook subscriptions (5 known trigger fields only — see module docstring)."""


@webhooks.command("subscribe")
@click.option("--account-id", default=None, help="Override META_AD_ACCOUNT_ID.")
@click.option("--app-id", default=None, help="Override META_APP_ID.")
@click.option("--json", "as_json", is_flag=True)
def webhooks_subscribe(account_id, app_id, as_json):
    """POST /act_{ad_account_id}/subscribed_apps — subscribe this app to ad-account webhooks.

    Requires the app to already have the Webhooks product configured with "Ad Account" as
    object type + a verified callback URL in the App Dashboard — this call only performs
    the per-ad-account subscription step, it does not configure the App Dashboard side.
    """
    acct = _require_account_id(account_id, as_json)
    aid = app_id or APP_ID
    if not aid:
        raise SystemExit(print_error(
            "META_APP_ID is not set (or pass --app-id).", code="VALIDATION", as_json=as_json,
        ))
    result = graph_request("POST", f"{acct}/subscribed_apps", params={"app_id": aid}, as_json=as_json)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Subscribed app {aid} to {acct} webhooks", fg="green")
    print_json(result)


@webhooks.command("list")
@click.option("--account-id", default=None, help="Override META_AD_ACCOUNT_ID.")
@click.option("--json", "as_json", is_flag=True)
def webhooks_list(account_id, as_json):
    """GET /act_{ad_account_id}/subscribed_apps — verify which apps are subscribed."""
    acct = _require_account_id(account_id, as_json)
    result = graph_request("GET", f"{acct}/subscribed_apps", as_json=as_json)
    rows = result.get("data", []) if isinstance(result, dict) else []
    if as_json:
        print_json(result)
        return
    print_table([flatten(r) for r in rows]) if rows else print_json(result)


@webhooks.command("unsubscribe")
@click.option("--account-id", default=None, help="Override META_AD_ACCOUNT_ID.")
@click.option("--app-id", default=None, help="Override META_APP_ID.")
@click.option("--json", "as_json", is_flag=True)
def webhooks_unsubscribe(account_id, app_id, as_json):
    """DELETE /act_{ad_account_id}/subscribed_apps — remove this app's webhook subscription.

    NOT transcribed verbatim in kb/graph-api.md (only POST subscribe + GET verify are
    shown there) — see module docstring for the standard-Graph-API-convention caveat. Run
    `webhooks list` afterward to confirm the subscription is actually gone.
    """
    acct = _require_account_id(account_id, as_json)
    aid = app_id or APP_ID
    params = {}
    if aid:
        params["app_id"] = aid
    result = graph_request("DELETE", f"{acct}/subscribed_apps", params=params, as_json=as_json)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Unsubscribed app {aid or '(default)'} from {acct} webhooks", fg="green")
    print_json(result)
