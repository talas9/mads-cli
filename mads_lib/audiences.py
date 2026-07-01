"""Meta Custom Audience / Lookalike Audience client.

API: Marketing API v25.0 — `CustomAudience` resource (Lookalikes are a `CustomAudience`
with `subtype="LOOKALIKE"` and a populated `lookalike_spec`; there is no separate
Lookalike resource/endpoint).
KB reference: kb/marketing-api.md § Custom Audiences, § Lookalike Audiences, § DG-6, § DG-7
Official docs:
  https://developers.facebook.com/docs/marketing-api/audiences/guides/custom-audiences/
  https://developers.facebook.com/docs/marketing-api/audiences/guides/lookalike-audiences/

Mirrors gads-cli's gads_lib/merchant.py shape: one function per endpoint, `as_json`
threaded through to the shared HTTP layer for --json error routing, response shapes
documented in each docstring with a citation to what was actually confirmed in the KB
vs. inferred from the standard Graph API list/create/delete conventions used
elsewhere in this KB set.
"""
import hashlib
import re
import time

from .config import AD_ACCOUNT_ID
from .http import graph_request

# KB: kb/marketing-api.md § Custom Audiences — "Key fields" table (verbatim field list).
DEFAULT_AUDIENCE_FIELDS = (
    "id,name,subtype,customer_file_source,approximate_count_lower_bound,"
    "approximate_count_upper_bound,description,delivery_status,operation_status,"
    "time_created,time_updated,lookalike_audience_ids,lookalike_spec"
)

# KB: kb/marketing-api.md § DG-6 — "MADID ... and EXTERN_ID ... are the two schema keys
# that are not hashed. All other supported schema keys ... require the SHA-256 hash."
UNHASHED_SCHEMA_KEYS = frozenset({"MADID", "EXTERN_ID"})

# KB: kb/marketing-api.md § Custom Audiences / § DG-6 — up to 10,000 records per
# POST /{custom_audience_id}/users request; larger uploads are chunked across
# multiple requests sharing one session_id with incrementing batch_seq.
MAX_USERS_PER_UPLOAD_REQUEST = 10_000

# KB: kb/marketing-api.md § Lookalike Audiences — "ratio ranges 0.01–0.20 in 0.01
# increments (top 1%–20% of the target country's population...)".
LOOKALIKE_RATIO_MIN = 0.01
LOOKALIKE_RATIO_MAX = 0.20


def _normalize_schema_value(value, schema_key: str) -> str:
    """Normalize a raw value before hashing, per kb/marketing-api.md § DG-6.

    The KB's worked normalization example only spells out the `phone` rule
    explicitly ("strip symbols/letters/leading zeros"); for everything else it
    says generically "email (trimmed + lowercased before hashing), ... names
    (lowercased, Roman-alphabet preferred)". This applies trim+lowercase to all
    hashable fields, plus phone's extra digit-stripping — do not assume this
    covers every documented nuance (e.g. exact DOB/city/state/zip enum key
    spellings) beyond EMAIL/PHONE/FN/LN, which are the only ones the KB shows
    verbatim.
    """
    v = str(value).strip().lower()
    if schema_key.upper() == "PHONE":
        v = re.sub(r"\D", "", v).lstrip("0")
    return v


def _hash_schema_value(value, schema_key: str) -> str:
    """Hash one (schema_key, value) pair per the Custom Audience upload rules."""
    if schema_key.upper() in UNHASHED_SCHEMA_KEYS:
        return str(value).strip()
    normalized = _normalize_schema_value(value, schema_key)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# KB: kb/marketing-api.md § Resources & Endpoints (implicit) | https://developers.facebook.com/docs/marketing-api/reference/custom-audience/
def list_audiences(*, ad_account_id=None, fields=DEFAULT_AUDIENCE_FIELDS, limit=None,
                    after=None, token=None, as_json=False):
    """List Custom/Lookalike Audiences owned by an ad account.

    GET /{ad_account_id}/customaudiences

    Response shape (standard Graph API list-edge shape — the same `{data, paging}`
    envelope confirmed elsewhere in this KB set for owned_product_catalogs /
    product_feeds / products; not shown verbatim for this specific edge in
    kb/marketing-api.md, so treat the exact envelope as high-confidence but
    unconfirmed-for-this-edge):
      data[]   — array of CustomAudience objects (see DEFAULT_AUDIENCE_FIELDS for
                 the field list pulled from the KB's Key Fields table)
      paging   — cursor pagination object
    """
    account = ad_account_id or AD_ACCOUNT_ID
    params = {}
    if fields:
        params["fields"] = fields
    if limit:
        params["limit"] = limit
    if after:
        params["after"] = after
    return graph_request("GET", f"{account}/customaudiences", params=params, token=token, as_json=as_json)


# KB: kb/marketing-api.md § Custom Audiences / § DG-6 | https://developers.facebook.com/docs/marketing-api/audiences/guides/custom-audiences/
def create_custom_audience(name, *, customer_file_source="USER_PROVIDED_ONLY",
                            description=None, subtype="CUSTOM", ad_account_id=None,
                            token=None, as_json=False):
    """Create a Custom Audience.

    POST /{ad_account_id}/customaudiences

    Args:
        subtype: one of the `subtype` enum values (KB: APP, BAG_OF_ACCOUNTS, BIDDING,
            CLAIM, CUSTOM, ENGAGEMENT, EXCLUSION, FOX, LOOKALIKE, MANAGED, MEASUREMENT,
            MESSENGER_SUBSCRIBER_LIST, OFFLINE_CONVERSION, PARTNER, PRIMARY,
            REGULATED_CATEGORIES_AUDIENCE, STUDY_RULE_AUDIENCE, VIDEO, WEBSITE).
            Use create_lookalike_audience() instead for `subtype="LOOKALIKE"` — it
            requires `lookalike_spec`/`origin_audience_id`, which this function does
            not send.
        customer_file_source: `USER_PROVIDED_ONLY` | `PARTNER_PROVIDED_ONLY` |
            `BOTH_USER_AND_PARTNER_PROVIDED`.

    Response shape (KB-confirmed): {"id": "<numeric string>"}
    """
    account = ad_account_id or AD_ACCOUNT_ID
    body = {"name": name, "subtype": subtype, "customer_file_source": customer_file_source}
    if description:
        body["description"] = description
    return graph_request("POST", f"{account}/customaudiences", json_body=body, token=token, as_json=as_json)


# KB: kb/marketing-api.md § Lookalike Audiences / § DG-7 | https://developers.facebook.com/docs/marketing-api/audiences/guides/lookalike-audiences/
def create_lookalike_audience(name, origin_audience_id, *, ratio=0.01, country="AE",
                               lookalike_type="similarity", starting_ratio=None,
                               ad_account_id=None, token=None, as_json=False):
    """Create a Lookalike Audience seeded from an existing Custom Audience.

    POST /{ad_account_id}/customaudiences  (subtype="LOOKALIKE")

    Args:
        origin_audience_id: seed CustomAudience ID. KB: needs >=100 people to
            generate a lookalike at all ("Meta recommends far more for match
            quality").
        ratio: 0.01–0.20 in 0.01 increments (top 1%–20% of the target country's
            population most similar to the seed).
        lookalike_type: "similarity" (tighter/top ~1%) or "reach" (broader, up to
            ~5–10%, more volume).
        starting_ratio: combine with `ratio` to target a *band* instead of the top
            N% (e.g. starting_ratio=0.01, ratio=0.02 → the 1–2% band).

    KB gotcha: newly created lookalikes take 1–6 hours to fully populate; ad sets
    can be created immediately, delivery normalizes once population completes.

    Response shape (KB-confirmed): {"id": "<numeric string>"}
    """
    if not (LOOKALIKE_RATIO_MIN <= ratio <= LOOKALIKE_RATIO_MAX):
        raise ValueError(
            f"create_lookalike_audience: ratio={ratio} out of Meta's allowed range "
            f"[{LOOKALIKE_RATIO_MIN}, {LOOKALIKE_RATIO_MAX}]."
        )
    account = ad_account_id or AD_ACCOUNT_ID
    lookalike_spec = {"type": lookalike_type, "ratio": ratio, "country": country}
    if starting_ratio is not None:
        lookalike_spec["starting_ratio"] = starting_ratio
    body = {
        "name": name,
        "subtype": "LOOKALIKE",
        "origin_audience_id": origin_audience_id,
        "lookalike_spec": lookalike_spec,
    }
    return graph_request("POST", f"{account}/customaudiences", json_body=body, token=token, as_json=as_json)


# KB: kb/marketing-api.md § Custom Audiences ("Creating a Custom Audience and uploading
# hashed PII") / § DG-6 | https://developers.facebook.com/docs/marketing-api/audiences/guides/custom-audiences/
def upload_audience_users(custom_audience_id, schema, rows, *, already_hashed=False,
                           session_id=None, token=None, as_json=False):
    """Add (hashed) user records to a Custom Audience, chunked to Meta's 10k/request cap.

    POST /{custom_audience_id}/users

    Args:
        schema: list of field-type keys aligned to each row, e.g. ["EMAIL", "FN", "LN"].
            `MADID` and `EXTERN_ID` are never hashed; every other documented schema key
            (email, phone, name components, gender, DOB, city/state/zip/country) is
            SHA-256-hashed after normalization.
        rows: list of lists, each inner list a record aligned to `schema` order. Pass
            raw (unhashed) values by default — this function hashes required fields
            for you (mirrors Meta's own Business SDKs, which "hash automatically").
        already_hashed: set True if `rows` are already SHA-256 hashes — this skips
            the auto-hash step so values are never hashed twice (double-hashing
            silently produces a wrong-but-valid-looking hash with no error).
        session_id: shared across chunked requests for the same logical upload.
            Defaults to the current Unix timestamp if not given (matches Meta's own
            example, which uses a similarly-derived integer).

    Returns a single response dict if only one chunk was needed, else a list of
    per-chunk response dicts (one per HTTP request actually sent).

    Response shape: not shown verbatim in kb/marketing-api.md for this specific
    edge — treat the returned dict as opaque beyond the standard success/error
    envelope already handled by graph_request()'s error classification.
    """
    if not rows:
        raise ValueError("upload_audience_users: `rows` must be a non-empty list.")

    if already_hashed:
        hashed_rows = [list(row) for row in rows]
    else:
        hashed_rows = [
            [_hash_schema_value(value, key) for value, key in zip(row, schema)]
            for row in rows
        ]

    sid = session_id if session_id is not None else int(time.time())
    total = len(hashed_rows)
    chunks = [
        hashed_rows[i:i + MAX_USERS_PER_UPLOAD_REQUEST]
        for i in range(0, total, MAX_USERS_PER_UPLOAD_REQUEST)
    ] or [[]]

    responses = []
    for seq, chunk in enumerate(chunks, start=1):
        body = {
            "schema": list(schema),
            "data": chunk,
            "session": {
                "session_id": sid,
                "batch_seq": seq,
                "last_batch_flag": seq == len(chunks),
                "estimated_num_total": total,
            },
        }
        responses.append(
            graph_request("POST", f"{custom_audience_id}/users", json_body=body, token=token, as_json=as_json)
        )

    return responses[0] if len(responses) == 1 else responses


# KB: NOT explicitly documented in kb/marketing-api.md (no "Deleting" section was
# fetched for the CustomAudience reference page this session). This follows the
# standard Graph API DELETE-by-node-ID convention confirmed elsewhere in this KB set
# (e.g. commerce-catalog.md's `DELETE /{product_feed_id}`, and marketing-api.md's own
# note that "a true DELETE HTTP verb is also accepted on many nodes ... codegen'd in
# the SDK as api_delete()"). Treat as (unverified for this specific node type) until
# exercised against a real audience ID.
def delete_audience(audience_id, *, token=None, as_json=False):
    """Delete a Custom/Lookalike Audience.

    DELETE /{custom_audience_id}

    Response shape: not confirmed in the KB for this node; standard Graph API
    delete convention returns {"success": true} on success.
    """
    return graph_request("DELETE", audience_id, token=token, as_json=as_json)
