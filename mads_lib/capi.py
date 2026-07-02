"""Meta Conversions API (CAPI) client — pixel/dataset management + server-side events.

API: Marketing API v25.0 — Conversions API surface. Pixel/Dataset CRUD lives on the
`AdAccount`/`Business` nodes; event ingestion lives on the pixel/dataset node itself
(`AdsPixel`).
KB reference: kb/conversions-api.md (relative to mads-cli root)
Official docs: https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api

Mirrors gads-cli's gads_lib/merchant.py shape: one function per endpoint, `as_json`
threaded through for --json error routing, response shapes documented per KB citation.

KB Gotcha #7: "Pixel" and "Dataset" are now largely the same underlying `AdsPixel`
object — a "dataset" is just the umbrella concept that can carry Pixel (web), App
Events, legacy Offline Conversions, and Messaging Events data together.
`create_dataset()` below is therefore a thin, semantically-named alias for
`create_pixel()`, not a distinct endpoint.
"""
import hashlib
import re
import time

from .config import AD_ACCOUNT_ID
from .http import graph_request
from .output import print_error

# KB: kb/conversions-api.md § "Rate Limits and Batch Constraints — Summary".
MAX_EVENTS_PER_REQUEST = 1000
EVENT_TIME_MAX_AGE_SECONDS = 7 * 24 * 3600
EVENT_TIME_MAX_AGE_PHYSICAL_STORE_SECONDS = 62 * 24 * 3600

# KB: kb/conversions-api.md § "Customer Information Parameters (user_data) — Hashing Rules".
HASH_REQUIRED_USER_DATA_FIELDS = frozenset({"em", "ph", "fn", "ln", "db", "ge", "ct", "st", "zp", "country"})
HASH_RECOMMENDED_USER_DATA_FIELDS = frozenset({"external_id"})
NEVER_HASH_USER_DATA_FIELDS = frozenset({
    "client_ip_address", "client_user_agent", "fbc", "fbp", "subscription_id",
    "fb_login_id", "lead_id", "anon_id", "madid", "page_id", "page_scoped_user_id",
    "ctwa_clid", "ig_account_id", "ig_sid",
})

# KB: kb/conversions-api.md § "Pixel / Dataset Creation — Full Walkthrough" — Notable
# AdsPixel fields (from the SDK `Field` enum), trimmed to the most commonly useful.
#
# `owner_ad_account` is deliberately EXCLUDED from the default set. Root-caused
# 2026-07-02 (session investigating a `capi list-pixels` AUTH failure): this
# sub-object expansion requires ads_management/ads_read on the pixel's *actual*
# owning ad account — which, for pixels created via a third-party channel
# (e.g. Shopify's Facebook & Instagram sales channel) or migrated/legacy
# pixels, can be an ad account entirely outside the caller's Business Manager
# and never assigned to the caller at all. When that happens Meta returns
# `(#200) Ad account owner has NOT grant ads_management or ads_read
# permission` for the WHOLE list-pixels call, even though every other field
# (including `owner_business`) resolves fine and the caller has full
# DRAFT/ANALYZE/ADVERTISE/MANAGE tasks on the ad account being queried. See
# kb/graph-api.md Gotchas for the full verified trace. Callers who need
# `owner_ad_account` for a specific known-good pixel can still request it
# explicitly via `--fields`.
DEFAULT_PIXEL_FIELDS = (
    "id,name,creation_time,is_consolidated_container,last_fired_time,"
    "match_rate_approx,owner_business,data_use_setting"
)


def _normalize_user_data_value(value, field: str) -> str:
    """Normalize a raw user_data value before hashing, per the Customer Information
    Parameters table (kb/conversions-api.md). Only `em`/`ph`/name-style trim+lowercase
    and `ph`'s extra digit-stripping are implemented generically here — the KB's
    per-field nuances beyond that (exact `db`/`ct`/`st`/`zp` punctuation-stripping
    rules) should be applied by the caller if not already clean.
    """
    v = str(value).strip().lower()
    if field == "ph":
        v = re.sub(r"\D", "", v)
    elif field in ("ct", "st", "zp", "country"):
        v = re.sub(r"[^a-z0-9]", "", v)
    return v


def _hash_value(value, field: str) -> str:
    return hashlib.sha256(_normalize_user_data_value(value, field).encode("utf-8")).hexdigest()


# KB: kb/conversions-api.md § "Customer Information Parameters (user_data) — Hashing Rules"
# and § "3. Hashing — Implementation Pattern".
def hash_user_data(user_data: dict, *, already_hashed: bool = False) -> dict:
    """Return a copy of `user_data` with hash-required/-recommended fields SHA-256
    hashed and normalized; never-hash fields (client_ip_address, client_user_agent,
    fbc, fbp, subscription_id, fb_login_id, lead_id, anon_id, madid, page_id,
    page_scoped_user_id, ctwa_clid, ig_account_id, ig_sid) are always passed through
    untouched.

    Not auto-applied inside send_event() by default — call this explicitly (or pass
    `auto_hash_user_data=True` to send_event()) so already-hashed values are never
    silently re-hashed (double-hashing produces a wrong-but-valid-looking digest with
    no error — see kb/conversions-api.md Gotcha #6).

    If `already_hashed=True`, returns a shallow copy of `user_data` unchanged.
    """
    if already_hashed:
        return dict(user_data)
    out = {}
    for field, value in user_data.items():
        key = field.lower()
        if key in HASH_REQUIRED_USER_DATA_FIELDS or key in HASH_RECOMMENDED_USER_DATA_FIELDS:
            if isinstance(value, (list, tuple)):
                out[field] = [_hash_value(v, key) for v in value]
            else:
                out[field] = _hash_value(value, key)
        else:
            out[field] = value
    return out


def _require_act_id(ad_account_id, as_json=False):
    """Build + validate the `act_`-prefixed ad-account id.

    Mirrors campaigns.py's `_act_id`/`_require_act_id` (KB § Base URL / Gotcha
    #2: a bare numeric ad-account id 404s — the `act_` prefix is mandatory).
    Without this, `ad_account_id or AD_ACCOUNT_ID` being empty/unprefixed
    silently built a malformed `/adspixels` path instead of a clear pre-flight
    error.
    """
    aid = (ad_account_id or AD_ACCOUNT_ID or "").strip()
    if not aid:
        raise SystemExit(print_error(
            "META_AD_ACCOUNT_ID is not set (or pass --ad-account-id).",
            code="VALIDATION", as_json=as_json,
        ))
    return aid if aid.startswith("act_") else f"act_{aid}"


# KB: kb/conversions-api.md § "POST /act_{AD_ACCOUNT_ID}/adspixels — Create Pixel/Dataset"
# https://developers.facebook.com/docs/marketing-api/reference/ad-account/adspixels/
def create_pixel(name, *, ad_account_id=None, token=None, as_json=False):
    """Create a Pixel/Dataset under an ad account (the confirmed API-scriptable path).

    POST /act_{ad_account_id}/adspixels

    KB Gotcha #1: `Business.create_ads_pixel` (POST /{business_id}/adspixels) is a
    documented contradiction — the SDK ships it, but Meta's own reference page says
    Create is unsupported on that edge ("You can't perform this operation on this
    endpoint"). Use this AdAccount-scoped path.

    Error codes specific to this call (KB): 6200 = a pixel already exists for this
    account; 6202 = more than one pixel exists for this account. Historically most
    accounts are expected to have one pixel/dataset.

    Response shape (KB-confirmed): {"id": "<numeric string>"}
    """
    account = _require_act_id(ad_account_id, as_json)
    return graph_request("POST", f"{account}/adspixels", params={"name": name}, token=token, as_json=as_json)


def create_dataset(name, *, ad_account_id=None, token=None, as_json=False):
    """Create a "dataset" — semantically identical to create_pixel() (KB Gotcha #7:
    Pixel and Dataset are the same underlying AdsPixel object). Provided as a
    separately-named entry point for callers/CLI commands thinking in Conversions-API
    terms (no browser Pixel involved) rather than classic Pixel terms.
    """
    return create_pixel(name, ad_account_id=ad_account_id, token=token, as_json=as_json)


# KB: kb/conversions-api.md § "Resources & Endpoints" (adspixels list, on AdAccount or Business)
def list_pixels(*, ad_account_id=None, business_id=None, fields=DEFAULT_PIXEL_FIELDS,
                 id_filter=None, name_filter=None, token=None, as_json=False):
    """List pixels/datasets.

    If `business_id` is given: GET /{business_id}/adspixels — pixels the Business
    has access to (supports `id_filter`/`name_filter`).
    Otherwise: GET /{ad_account_id}/adspixels — pixels owned by the ad account.

    Response shape (standard Graph API list-edge shape; the endpoint table in the KB
    confirms both edges exist and their fields via the AdsPixel field list backing
    DEFAULT_PIXEL_FIELDS, but no verbatim `{data: [...]}` example was captured for
    either specific edge this session):
      {"data": [AdsPixel...], "paging": {...}}
    """
    params = {}
    if fields:
        params["fields"] = fields
    if business_id:
        if id_filter:
            params["id_filter"] = id_filter
        if name_filter:
            params["name_filter"] = name_filter
        return graph_request("GET", f"{business_id}/adspixels", params=params, token=token, as_json=as_json)
    account = _require_act_id(ad_account_id, as_json)
    return graph_request("GET", f"{account}/adspixels", params=params, token=token, as_json=as_json)


# KB: kb/conversions-api.md § "POST /{PIXEL_ID}/events — Send Server Event(s)"
# https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api
def send_event(pixel_id, events, *, test_event_code=None, namespace_id=None,
               partner_agent=None, upload_tag=None, auto_hash_user_data=False,
               token=None, as_json=False):
    """Send one or more server-side Conversions API events.

    POST /{pixel_id}/events

    Args:
        events: list of event dicts, each needing at minimum `event_name`,
            `event_time`, `user_data`, `action_source` (KB § Server Event
            Parameters). `user_data` is passed through as-is by default — set
            `auto_hash_user_data=True` to run each event's `user_data` through
            hash_user_data() first, or call hash_user_data() yourself beforehand.
        test_event_code: routes events into Events Manager → Test Events for live
            visibility. Does NOT sandbox delivery — test events still count for
            targeting/measurement; remove before production sends.

    Client-side guards enforced here, mirroring documented all-or-nothing batch
    failure modes (better to fail fast locally than send a doomed request):
      - up to 1,000 events per call (KB: batch cap)
      - event_time no older than 7 days (62 days if action_source="physical_store")
        — exceeding this on ANY event rejects the ENTIRE batch, zero processed.

    Response shape: not shown verbatim in kb/conversions-api.md for this edge —
    treat the returned dict as opaque beyond the standard error envelope already
    handled by graph_request()'s error classification.
    """
    if not events:
        raise ValueError("send_event: `events` must be a non-empty list.")
    if len(events) > MAX_EVENTS_PER_REQUEST:
        raise ValueError(
            f"send_event: {len(events)} events exceeds Meta's hard cap of "
            f"{MAX_EVENTS_PER_REQUEST} per /events call — split into multiple calls."
        )

    now = time.time()
    for i, event in enumerate(events):
        event_time = event.get("event_time")
        if event_time is None:
            raise ValueError(f"send_event: events[{i}] is missing required `event_time`.")
        max_age = (
            EVENT_TIME_MAX_AGE_PHYSICAL_STORE_SECONDS
            if event.get("action_source") == "physical_store"
            else EVENT_TIME_MAX_AGE_SECONDS
        )
        if now - event_time > max_age:
            raise ValueError(
                f"send_event: events[{i}].event_time is older than the allowed "
                f"{max_age // 86400:.0f}-day window — Meta rejects the ENTIRE batch, "
                "not just this event."
            )

    if auto_hash_user_data:
        events = [
            {**event, "user_data": hash_user_data(event["user_data"])} if event.get("user_data") else event
            for event in events
        ]

    body = {"data": events}
    if test_event_code:
        body["test_event_code"] = test_event_code
    if namespace_id:
        body["namespace_id"] = namespace_id
    if partner_agent:
        body["partner_agent"] = partner_agent
    if upload_tag:
        body["upload_tag"] = upload_tag

    return graph_request("POST", f"{pixel_id}/events", json_body=body, token=token, as_json=as_json)


# KB: kb/conversions-api.md § "test_event_code — Test Events Tool"
def test_event(pixel_id, events, test_event_code, *, auto_hash_user_data=False,
               token=None, as_json=False):
    """Send events through the Test Events tool.

    Not a separate endpoint — this is send_event() with `test_event_code` required
    (KB: Events Manager → Data Sources → your Pixel → Test Events, generates a code
    like "TEST123"). Events sent this way are NOT sandboxed: they still count for
    targeting/measurement in Events Manager; they just additionally surface live in
    the Test Events UI. Remove `test_event_code` before sending production traffic.
    """
    if not test_event_code:
        raise ValueError("test_event: `test_event_code` is required (Events Manager → Test Events).")
    return send_event(pixel_id, events, test_event_code=test_event_code,
                       auto_hash_user_data=auto_hash_user_data, token=token, as_json=as_json)
