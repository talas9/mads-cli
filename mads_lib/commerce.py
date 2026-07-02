"""Meta Commerce Manager — Catalog & Product API client.

API: Marketing API v25.0 — `ProductCatalog` / `ProductFeed` / `ProductItem` resources
and the Catalog Batch API (`items_batch`).
KB reference: kb/commerce-catalog.md (relative to mads-cli root)
Official docs: https://developers.facebook.com/docs/marketing-api/reference/product-catalog/

Named `commerce.py`, not `catalog.py` — `catalog.py` in this package is reserved for
CLI self-introspection (mads_lib/catalog.py walks the Click command tree, ported from
gads-cli's gads_lib/catalog.py — unrelated to Meta's Commerce/Product Catalog).

Mirrors gads-cli's gads_lib/merchant.py shape: one function per endpoint, `as_json`
threaded through for --json error routing, response shapes documented per KB citation.

`graph_request()` (mads_lib/http.py) only supports JSON bodies and query params — it
has no `files=` support for multipart file attachments — so the local-file variant of
`upload_feed()` sends its own `requests.post(..., files=...)` call below, reusing the
same access-token/appsecret_proof and error-classification logic as graph_request()
for parity (see `_upload_local_file()`).
"""
import json
import sys
from pathlib import Path

import click
import requests

from .auth import get_access_token, get_appsecret_proof
from .config import BUSINESS_ID
from .http import BASE_URL, classify_meta_error, graph_request
from .output import print_error

# KB: kb/commerce-catalog.md § "Catalog Batch API — items_batch" — Limitations.
MAX_BATCH_ITEMS = 5000
RECOMMENDED_BATCH_ITEMS = 3000
MAX_BATCH_PAYLOAD_BYTES = 28 * 1024 * 1024  # 28 MB


def _upload_local_file(path, *, file_path, field_name="file", extra_fields=None,
                        token=None, timeout=120, as_json=False):
    """POST a local file as multipart/form-data (graph_request() can't do this)."""
    tok = token or get_access_token()
    params = {"access_token": tok, "appsecret_proof": get_appsecret_proof(tok)}
    url = f"{BASE_URL}/{path.lstrip('/')}"

    fp = Path(file_path)
    try:
        with fp.open("rb") as fh:
            files = {field_name: (fp.name, fh)}
            resp = requests.post(url, params=params, data=dict(extra_fields or {}), files=files, timeout=timeout)
    except requests.exceptions.Timeout:
        raise SystemExit(print_error(
            f"Upload to Meta Graph API timed out after {timeout}s ({path}). "
            "This is a network/latency issue, not a Meta API error — retry, or pass a "
            "longer timeout for large files.",
            code="API", as_json=as_json,
        ))
    except requests.exceptions.ConnectionError as e:
        raise SystemExit(print_error(
            f"Could not reach the Meta Graph API ({path}): {e}. "
            "The upload never reached graph.facebook.com — check your network "
            "connection, DNS, or firewall/proxy settings.",
            code="API", as_json=as_json,
        ))
    except requests.exceptions.RequestException as e:
        raise SystemExit(print_error(
            f"Network error uploading to Meta Graph API ({path}): "
            f"{type(e).__name__}: {e}",
            code="API", as_json=as_json,
        ))

    if resp.status_code >= 400:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        classified = classify_meta_error(resp.status_code, body)
        if classified:
            if as_json:
                sys.stdout.write(json.dumps({"error": classified}) + "\n")
                sys.stdout.flush()
                raise SystemExit(classified["exit_code"])
            click.secho(f"✗ Meta API error {classified['error_code']}: {classified['message']}", fg="red", err=True)
            if classified.get("fbtrace_id"):
                click.secho(f"  fbtrace_id: {classified['fbtrace_id']}", fg="yellow", err=True)
            raise SystemExit(classified["exit_code"])
        detail = resp.text[:1200]
        raise SystemExit(print_error(f"API Error {resp.status_code}: {detail}", code="API", as_json=as_json))

    if not resp.text:
        return {}
    return resp.json()


def _require_business_id(business_id, as_json=False):
    """Validate the Business Manager id. Mirrors abtest.py's/business.py's
    `_require_business_id` — without this, `business_id or BUSINESS_ID` being
    empty silently built a malformed `/owned_product_catalogs` path (missing
    the business node entirely) instead of a clear pre-flight error.
    """
    biz = business_id or BUSINESS_ID
    if not biz:
        raise SystemExit(print_error(
            "META_BUSINESS_ID is not set (or pass --business-id).", code="VALIDATION", as_json=as_json,
        ))
    return biz


# KB: kb/commerce-catalog.md § "POST /{business_id}/owned_product_catalogs — Create a catalog"
# https://developers.facebook.com/docs/marketing-api/reference/business/owned_product_catalogs/
def create_catalog(name, *, vertical="commerce", business_id=None, business_metadata=None,
                    parent_catalog_id=None, catalog_segment_filter=None, token=None,
                    as_json=False, **extra_fields):
    """Create a ProductCatalog owned by a Business Manager.

    POST /{business_id}/owned_product_catalogs

    Args:
        vertical: one of adoptable_pets, apps_and_software, articles_and_publications,
            commerce, destinations, flights, generic, home_listings, hotels,
            local_service_businesses, media_titles, offer_items, services,
            offline_commerce, transactable_items, vehicles. Default "commerce" —
            correct for a physical-goods catalog (Talas auto parts).
        business_metadata: dict, e.g. {"page_id": "...", "external_business_id": "..."}.
        **extra_fields: passthrough for less-common create params documented in the
            KB (da_display_settings, destination_catalog_settings,
            flight_catalog_settings, partner_integration, store_catalog_settings).

    KB gotcha: `owned_product_catalogs` is the current, fully-parameterized create
    path; `product_catalogs` seen in some older Meta doc snippets is a legacy alias.

    Response shape (KB-confirmed): {"id": "<numeric string>"}
    """
    biz = _require_business_id(business_id, as_json)
    body = {"name": name, "vertical": vertical}
    if business_metadata:
        body["business_metadata"] = business_metadata
    if parent_catalog_id:
        body["parent_catalog_id"] = parent_catalog_id
    if catalog_segment_filter:
        body["catalog_segment_filter"] = catalog_segment_filter
    body.update(extra_fields)
    return graph_request("POST", f"{biz}/owned_product_catalogs", json_body=body, token=token, as_json=as_json)


# KB: kb/commerce-catalog.md § "POST /{product_catalog_id}/product_feeds — Create a product feed"
# https://developers.facebook.com/docs/marketing-api/reference/product-catalog/product_feeds/
def create_product_feed(catalog_id, name, *, feed_type="PRODUCTS", country=None,
                         default_currency=None, deletion_enabled=None, delimiter=None,
                         encoding=None, schedule=None, update_schedule=None, token=None,
                         as_json=False, **extra_fields):
    """Create a ProductFeed — a named, independently-schedulable ingestion pipeline.

    POST /{product_catalog_id}/product_feeds

    Args:
        feed_type: PRODUCTS for a normal commerce feed; PRODUCT_RATINGS_AND_REVIEWS
            for the Ratings & Reviews feed (see the Ratings and Reviews section of
            the KB — same product_feeds + uploads machinery, just this flag).
        country: two-letter code. Meta defaults to "US" if omitted — **must be set
            explicitly to "AE" for Talas.**
        default_currency: ISO 4217. Meta defaults to "USD" if omitted — **must be
            set explicitly to "AED" for Talas.**
        deletion_enabled: KB gotcha — "cannot be disabled once enabled" per Meta's
            own docs; treat enabling it as a one-way door.
        schedule / update_schedule: dict (auto JSON-encoded) or pre-encoded JSON
            string, shaped like ProductFeedSchedule (interval, interval_count, hour,
            minute, day_of_week, day_of_month, timezone, url, username).
            `schedule` is a **full-replace** fetch (deletes items missing from the
            latest file, if deletion_enabled); `update_schedule` **never deletes**.

    Response shape (KB-confirmed):
      {"id": "<numeric string>", "errors": [{"error_subcode", "invalid_attribute", "error_message"}]}
    """
    body = {"name": name, "feed_type": feed_type}
    if country:
        body["country"] = country
    if default_currency:
        body["default_currency"] = default_currency
    if deletion_enabled is not None:
        body["deletion_enabled"] = deletion_enabled
    if delimiter:
        body["delimiter"] = delimiter
    if encoding:
        body["encoding"] = encoding
    if schedule is not None:
        body["schedule"] = json.dumps(schedule) if isinstance(schedule, dict) else schedule
    if update_schedule is not None:
        body["update_schedule"] = json.dumps(update_schedule) if isinstance(update_schedule, dict) else update_schedule
    body.update(extra_fields)
    return graph_request("POST", f"{catalog_id}/product_feeds", json_body=body, token=token, as_json=as_json)


# KB: kb/commerce-catalog.md § "Feed Uploads — File, URL, and Scheduling"
# https://developers.facebook.com/docs/marketing-api/reference/product-feed/uploads/
def upload_feed(feed_id, *, url=None, file_path=None, token=None, as_json=False):
    """Trigger a one-off feed upload, either fetched from a URL or a local file.

    POST /{product_feed_id}/uploads

    Pass exactly one of `url=` (Meta fetches the file server-side at request time)
    or `file_path=` (uploaded directly as multipart/form-data, no publicly-reachable
    URL needed).

    KB note: the dedicated reference page's own "Creating" section is internally
    inconsistent (a working curl example immediately followed by "You can't perform
    this operation on this endpoint") — treated as real/working per corroborating
    use in the Ratings & Reviews guide and the exact `uploads` edge name.

    Response shape (KB-confirmed): {"id": "{UPLOAD_SESSION_ID}"}
    """
    if bool(url) == bool(file_path):
        raise ValueError("upload_feed: pass exactly one of url= or file_path=.")
    if url:
        return graph_request("POST", f"{feed_id}/uploads", params={"url": url}, token=token, as_json=as_json)
    return _upload_local_file(f"{feed_id}/uploads", file_path=file_path, field_name="file",
                               token=token, as_json=as_json)


# KB: kb/commerce-catalog.md § "POST /{product_catalog_id}/products — Direct product creation"
# https://developers.facebook.com/docs/marketing-api/reference/product-catalog/products/
def create_product(catalog_id, retailer_id, name, currency, price, image_url, *,
                    url=None, availability="in stock", condition="new", brand=None,
                    description=None, gtin=None, manufacturer_part_number=None,
                    category=None, product_type=None, allow_upsert=True,
                    visibility="published", commerce_tax_category=None,
                    additional_image_urls=None, custom_labels=None, token=None,
                    as_json=False, **extra_fields):
    """Create (or, with allow_upsert, update) a single ProductItem directly.

    POST /{product_catalog_id}/products

    Not recommended at scale — prefer a feed (create_product_feed + upload_feed) or
    batch_update_items() for bulk onboarding; this is for real-time one-off items.

    Args:
        price: int64 in **minor units** (e.g. "599" = 5.99) — KB gotcha: this
            differs from batch_update_items(), which takes price as a string with
            the currency code embedded (e.g. "14 GBP").
        condition: new, refurbished, used, used_like_new, used_good, used_fair, cpo,
            open_box_new. Talas: "used" for OEM-pulled parts, "new" for new
            aftermarket (never "OEM only"/"Genuine only" per the account's own
            business rules).
        availability: "in stock", "out of stock", "preorder", "available for order",
            "discontinued", "pending", "mark_as_sold", "mark_as_expired".
        allow_upsert: default True — re-posting the same retailer_id updates it in
            place; False raises an error on a duplicate retailer_id instead.
        custom_labels: up to 5 strings, mapped to custom_label_0..custom_label_4.

    Response shape (KB-confirmed): {"id": "<numeric string>"}
    """
    body = {
        "retailer_id": retailer_id,
        "name": name,
        "currency": currency,
        "price": price,
        "image_url": image_url,
        "availability": availability,
        "condition": condition,
        "allow_upsert": allow_upsert,
        "visibility": visibility,
    }
    if url:
        body["url"] = url
    if brand:
        body["brand"] = brand
    if description:
        body["description"] = description
    if gtin:
        body["gtin"] = gtin
    if manufacturer_part_number:
        body["manufacturer_part_number"] = manufacturer_part_number
    if category:
        body["category"] = category
    if product_type:
        body["product_type"] = product_type
    if commerce_tax_category:
        body["commerce_tax_category"] = commerce_tax_category
    if additional_image_urls:
        body["additional_image_urls"] = additional_image_urls
    if custom_labels:
        for i, label in enumerate(custom_labels[:5]):
            body[f"custom_label_{i}"] = label
    body.update(extra_fields)
    return graph_request("POST", f"{catalog_id}/products", json_body=body, token=token, as_json=as_json)


# KB: kb/commerce-catalog.md § "POST /{product_catalog_id}/products — Direct product creation" (Reading)
def list_products(catalog_id, *, fields=None, limit=None, after=None, filter_json=None,
                   error_priority=None, error_type=None,
                   return_only_approved_products=None, token=None, as_json=False):
    """List products in a catalog.

    GET /{product_catalog_id}/products

    Args:
        filter_json: JSON-encoded WCA-style filter rule (dict auto-encoded, or a
            pre-encoded JSON string).
        error_priority: HIGH, MEDIUM, LOW.
        error_type: catalog quality-issue enum, e.g. EMPTY_PRICE,
            IMAGE_RESOLUTION_LOW, MISSING_TAX_CATEGORY.

    Response shape (KB-confirmed):
      {"data": [ProductItem...], "paging": {...}, "summary": {"total_count": int}}
    """
    params = {}
    if fields:
        params["fields"] = fields
    if limit:
        params["limit"] = limit
    if after:
        params["after"] = after
    if filter_json is not None:
        params["filter"] = filter_json if isinstance(filter_json, str) else json.dumps(filter_json)
    if error_priority:
        params["error_priority"] = error_priority
    if error_type:
        params["error_type"] = error_type
    if return_only_approved_products is not None:
        params["return_only_approved_products"] = return_only_approved_products
    return graph_request("GET", f"{catalog_id}/products", params=params, token=token, as_json=as_json)


# KB: kb/commerce-catalog.md § "Catalog Batch API — items_batch"
# https://developers.facebook.com/docs/marketing-api/reference/product-catalog/items_batch/
def batch_update_items(catalog_id, operations, *, item_type="PRODUCT_ITEM",
                        allow_upsert=True, token=None, as_json=False):
    """Bulk create/update/delete catalog items in one call.

    POST /{catalog_id}/items_batch

    Args:
        operations: list of up to 5000 (keep under 3000 for reliability) dicts,
            each `{"method": "CREATE"|"UPDATE"|"DELETE", "data": {...}}`. CREATE
            needs all required fields for `item_type`; UPDATE can be partial;
            DELETE needs only the identifying field(s) — for PRODUCT_ITEM that's
            just `id`.
        item_type: PRODUCT_ITEM, APP_AND_SOFTWARE, DESTINATION, FLIGHT,
            HOME_LISTING, HOTEL, HOTEL_ROOM, MEDIA_TITLE, STORE_PRODUCT_ITEM,
            VEHICLE, VEHICLE_OFFER. Talas uses PRODUCT_ITEM.
        allow_upsert: default True — method="UPDATE" for a non-existent item
            creates it; False rejects such updates instead.

    KB gotchas enforced client-side here:
      - hard cap 5000 items/call (raises ValueError above that)
      - 28 MB request payload cap (raises ValueError if the JSON-encoded
        `operations` would exceed it)
    Both are documented as failure modes if exceeded, not always a clean 400 —
    chunk at ~2500-3000 items/call for reliability margin.

    KB gotcha (price format): each item's "price" field here is a **string with
    currency code embedded** (e.g. "14 GBP") — this differs from create_product()'s
    direct-products-edge, which takes price as a bare int64 in minor units.

    Response shape (KB-confirmed — NOT read-after-write; poll check_batch_status()):
      {"handles": ["<opaque handle>"], "validation_status": [{"retailer_id", "warnings": [], "errors": []}]}
      `handles` is empty if nothing was ingested.
    """
    if len(operations) > MAX_BATCH_ITEMS:
        raise ValueError(
            f"batch_update_items: {len(operations)} operations exceeds Meta's hard cap of "
            f"{MAX_BATCH_ITEMS} per items_batch call (keep under {RECOMMENDED_BATCH_ITEMS} "
            "for reliability)."
        )
    encoded = json.dumps(operations)
    if len(encoded.encode("utf-8")) > MAX_BATCH_PAYLOAD_BYTES:
        raise ValueError(
            f"batch_update_items: encoded `operations` payload exceeds Meta's "
            f"{MAX_BATCH_PAYLOAD_BYTES} byte (28 MB) cap — split into multiple calls."
        )
    # NOTE: sent via json_body (request body), not params (which graph_request()
    # always places in the URL query string) — a 5000-item/28MB payload would blow
    # past any practical URL-length limit if sent as a query string. `requests` is
    # still a JSON-*encoded string* value (per the KB's declared param type, matching
    # the curl example's `-F 'requests=[...]'` multipart-string usage), just carried
    # inside a JSON request body instead of a form/query-string one.
    body = {"item_type": item_type, "requests": encoded, "allow_upsert": allow_upsert}
    return graph_request("POST", f"{catalog_id}/items_batch", json_body=body, token=token, as_json=as_json)


# KB: kb/commerce-catalog.md § "Catalog Batch API — items_batch" (Checking status)
# https://developers.facebook.com/docs/marketing-api/reference/product-catalog/check_batch_request_status/
#
# Not in the literal "catalog create / feed create / feed upload / product create+list
# / batch" ask, but included alongside batch_update_items() because a `handle` with no
# way to poll its outcome makes the batch feature unusable end-to-end — same resource,
# same doc section, one extra thin GET wrapper.
def check_batch_status(catalog_id, handle, *, load_ids_of_invalid_requests=True,
                        token=None, as_json=False):
    """Poll the outcome of a previous batch_update_items() call.

    GET /{catalog_id}/check_batch_request_status?handle=...

    KB gotcha: `load_ids_of_invalid_requests` defaults False in the API — without
    explicitly passing True (this function's default), `ids_of_invalid_requests` is
    always `[]` even when rows failed.

    Response shape (KB-confirmed):
      {"data": [{"handle", "status", "warnings": [{"line","id","message"}],
                 "errors_total_count": int, "ids_of_invalid_requests": [...]}]}
    """
    params = {"handle": handle, "load_ids_of_invalid_requests": load_ids_of_invalid_requests}
    return graph_request("GET", f"{catalog_id}/check_batch_request_status", params=params,
                          token=token, as_json=as_json)
