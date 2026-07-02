# Meta Commerce Manager — Catalog & Product API

## Status & Versions

| API surface | Current version | Released | Expiration | Notes |
|---|---|---|---|---|
| **Marketing API** (`/docs/marketing-api/reference/...` — where Catalog, Product Feed, Batch, Ratings & Reviews live) | **v25.0** | Feb 18, 2026 | TBD | Use this. Latest shipped version as of 2026-07-01; no v26 has been announced or released. |
| Marketing API v24.0 | — | Oct 8, 2025 | **Oct 6, 2026** | Still valid today but sunsets in ~3 months; migrate new work to v25.0. |
| Marketing API v23.0 | — | May 29, 2025 | **June 9, 2026** | **Already expired** as of 2026-07-01. Any code still targeting v23.0 is broken. |
| Marketing API v22.0 | — | Jan 21, 2025 | Feb 19, 2026 | Expired. |
| Graph API (general, longer-lived) | v25.0 | Feb 18, 2026 | TBD | Graph API versions get ~2-year windows; Marketing API versions get a shorter (~13-month) independent lifecycle even though they share a version number. |

**Confirmed: v25.0 is the current/latest version as of 2026-07-01.** No v26.0 has shipped. The Marketing API changelog table shows v25.0 with expiration "TBD" and no version beyond it.
(Source: https://developers.facebook.com/docs/graph-api/changelog/versions/ — fetched 2026-07-01, both the "Graph API" and "Marketing API" tables checked)

Important nuance not obvious from the Graph API docs alone: **the Marketing API has its own, shorter version-expiration clock**, distinct from the general Graph API. A version number (e.g. "v23.0") is released on the same calendar date for both, but Marketing API v23.0 expired June 9, 2026 while Graph API v23.0 shows "TBD". Since every endpoint in this document lives under `/docs/marketing-api/reference/`, **use the Marketing API expiration column**, not the Graph API one, when deciding if a pinned version string in code is stale.

Sources:
- https://developers.facebook.com/docs/graph-api/changelog/versions/
- https://developers.facebook.com/docs/marketing-api/reference/product-catalog/ (page footer shows live "v25.0" in the GET/POST examples, confirming the reference content itself targets current version)


## Base URL

All endpoints in this document are plain Graph API calls under a single host — Commerce/Catalog does **not** have the per-sub-API versioned hosts that Google's Merchant API uses:

```
https://graph.facebook.com/<API_VERSION>/<resource-path>
```

Example: `https://graph.facebook.com/v25.0/{business-id}/owned_product_catalogs`

In mads-cli, `API_VERSION` defaults to `v25.0` (`mads_lib/config.py`, overridable via `META_API_VERSION`).


## Auth / Permissions

| Requirement | Detail |
|---|---|
| Permission | **`catalog_management`** — "allows your app to create, read, update and delete business-owned product catalogs that the user is an admin of." |
| Permission dependency | `catalog_management` requires `business_management` to already be granted. |
| Business Verification | Required for any app requesting **Advanced Access** to these permissions (most production integrations). |
| Token type | A **System User access token** (long-lived, non-expiring) scoped to the Business Manager that owns the catalog is the standard integration pattern — this is what `mads_lib/auth.py` loads via `MADS_CREDENTIALS_PATH`. |
| App Secret Proof | If "Require App Secret" is enabled on the app, every call must include `appsecret_proof = HMAC-SHA256(key=app_secret, msg=access_token)` — mads-cli computes this in `get_appsecret_proof()`. |

(Source: https://developers.facebook.com/docs/permissions/reference/catalog_management/ — fetched 2026-07-01)


## Resources & Endpoints — Overview

| Resource / Node | Key edges | Purpose |
|---|---|---|
| `Business` | `owned_product_catalogs` (GET, POST) | Create/list catalogs owned by a Business Manager |
| `ProductCatalog` | `product_feeds`, `products`, `items_batch`, `localized_items_batch`, `batch` (legacy), `check_batch_request_status`, `categories`, `automotive_models`, `vehicles`, `hotels`, `flights`, `home_listings`, `assigned_users` | The catalog container. Also directly updatable/deletable, and directly creatable via `POST /{catalog_id}` update or `/{business_id}/owned_product_catalogs` |
| `ProductFeed` | `uploads`, `upload_schedules`, `rules`, `products` | A named, schedulable ingestion pipeline of items into a catalog |
| `ProductFeedUpload` | `errors`, `error_report` | One concrete upload/fetch attempt for a feed |
| `ProductFeedSchedule` | (embedded object, no own edges) | The recurring-fetch config attached to a feed's `schedule` / `update_schedule` field |
| `ProductItem` | (leaf node, created via `products` edge or Batch API) | A single catalog item (product, in the `PRODUCT_ITEM` vertical) |

(Source: https://developers.facebook.com/docs/marketing-api/reference/product-catalog/ — Edges table, fetched 2026-07-01)


---

## Concrete Request/Response Examples

### POST /{business_id}/owned_product_catalogs — Create a catalog

**Purpose:** Creates a new `ProductCatalog` owned by a Business Manager. This is the current, documented creation path (the same edge is also reachable/duplicated on the `ProductCatalog` reference page's "Creating" section — an older top-of-page example on that same page shows `POST /{business_id}/product_catalogs`, which is a legacy alias; **`owned_product_catalogs` is the one with full parameter documentation and is what should be used**).

**Parameters:**

| Parameter | Type | Notes |
|---|---|---|
| `name` | UTF-8 string | **Required.** Name of the catalog. |
| `vertical` | enum | `adoptable_pets, apps_and_software, articles_and_publications, commerce, destinations, flights, generic, home_listings, hotels, local_service_businesses, media_titles, offer_items, services, offline_commerce, transactable_items, vehicles`. Default `commerce`. Use `commerce` for a physical-goods catalog (Talas auto parts). |
| `additional_vertical_option` | enum | `LOCAL_DA_CATALOG`, `LOCAL_PRODUCTS` — sub-configuration that doesn't add a new vertical. |
| `business_metadata` | JSON object | `{page_id (numeric string, required), external_business_id (string)}` |
| `catalog_segment_filter` | JSON-encoded rule | Creates the new catalog as a **filtered segment** of a parent catalog instead of an independent catalog. |
| `da_display_settings` | object | Dynamic Ads image display settings for `carousel_ad` / `single_ad`, each requiring `transformation_type` (`background_cropping_and_padding`, `background_padding`, `none`). |
| `destination_catalog_settings` | JSON object | `{generate_items_from_pages: bool, default false}` |
| `flight_catalog_settings` | JSON object | `{generate_items_from_events: bool, default false}` |
| `parent_catalog_id` | numeric string/int | Set when creating a catalog segment under a parent. |
| `partner_integration` | JSON object | `{external_access_token, external_merchant_id}` |
| `store_catalog_settings` | JSON object | `{page_id (numeric string, required)}` |

**Example request:**

```http
POST https://graph.facebook.com/v25.0/{business-id}/owned_product_catalogs
Content-Type: multipart/form-data

name=Talas Auto Parts Catalog
vertical=commerce
access_token=<ACCESS_TOKEN>
```

**Return type** (read-after-write, reads the created node's `id`):

```json
{ "id": "numeric string" }
```

**Error Codes:**

| Code | Meaning |
|---|---|
| 100 | Invalid parameter |
| 190 | Invalid OAuth 2.0 Access Token |
| 200 | Permissions error |
| 804 | Specified object already exists |
| 102 | Session key invalid or no longer valid |
| 2310019 | The business of this catalog is not onboarded to Collaborative Ads |

**Reading** (`GET /{business-id}/owned_product_catalogs`): no parameters; returns `{"data": [ProductCatalog...], "paging": {}, "summary": {}}`.

**Updating a catalog** is done via `POST /{product_catalog_id}` directly (not the `owned_product_catalogs` edge) — same field set as create minus `name`'s immutability concerns (name is still updatable), returns `{"success": bool}`.

**Deleting:** the `ProductCatalog` reference page does not document a DELETE on the catalog node itself in the sections captured; catalogs are normally deleted from Commerce Manager UI or via Business Manager. Treat programmatic catalog deletion as **(unverified)** — do not assume a bare `DELETE /{catalog_id}` exists without testing against a real sandbox catalog first.

(Source: https://developers.facebook.com/docs/marketing-api/reference/business/owned_product_catalogs/ and https://developers.facebook.com/docs/marketing-api/reference/product-catalog/ — both fetched 2026-07-01, "Creating"/"Updating" sections)

---

### POST /{product_catalog_id}/product_feeds — Create a product feed

**Purpose:** Creates a `ProductFeed` — a named, independently-schedulable ingestion pipeline into the catalog.

**Parameters:**

| Parameter | Type | Notes |
|---|---|---|
| `name` | UTF-8 string | User-specified feed name. |
| `feed_type` | enum | `ACTIVITY, APP_AND_SOFTWARE, ARTICLE_AND_PUBLICATION, AUTOMOTIVE_MODEL, COLLECTION, DESTINATION, FLIGHT, HOME_LISTING, HOTEL, HOTEL_ROOM, LOCAL_INVENTORY, MEDIA_TITLE, OFFER, PRODUCT_RATINGS_AND_REVIEWS, PRODUCTS, SERVICE, TRANSACTABLE_ITEMS, VEHICLE_OFFER, VEHICLES`. Use `PRODUCTS` for a normal commerce feed, `PRODUCT_RATINGS_AND_REVIEWS` for the Ratings & Reviews feed (see dedicated section below). |
| `country` | string | Two-letter country code. Default `"US"` — **must be set explicitly for Talas (`AE`)**. |
| `default_currency` | ISO 4217 | Default `USD` — **set to `AED` for Talas**; used when the feed file omits currency. |
| `deletion_enabled` | boolean | Default `true` (was `false` pre-API v2.5). When `true`, items missing from a re-uploaded feed are removed from the catalog. **Cannot be disabled once enabled.** |
| `delimiter` | enum | `AUTODETECT, BAR, COMMA, TAB, TILDE, SEMICOLON`. Default `AUTODETECT`. |
| `encoding` | enum | `AUTODETECT, LATIN1, UTF8, UTF16LE, UTF16BE, UTF32LE, UTF32BE`. Default `AUTODETECT`. |
| `file_name` | string | `.tsv`, `.xml`, or compressed (`.zip`, `.gzip`, `.bz2`). |
| `ingestion_source_type` | enum | `PRIMARY_FEED` (default; add/remove products) or `SUPPLEMENTARY_FEED` (overwrite data in an existing primary feed; requires `primary_feed_ids`). |
| `item_sub_type` | enum | Sub-vertical, e.g. `CLOTHING`, `ELECTRONICS_ACCESSORIES`, etc. — not typically needed for auto parts (leave default). |
| `migrated_from_feed_id` | numeric string | Used to split a large feed into smaller feeds without deleting the original — see Developer Guide §3 below. |
| `override_type` / `override_value` | enum / string | For secondary (supplementary) feeds: `LANGUAGE, COUNTRY, VERSION, CATALOG_SEGMENT_CUSTOMIZE_DEFAULT, LANGUAGE_AND_COUNTRY, BATCH_API_LANGUAGE_OR_COUNTRY, SMART_PIXEL_LANGUAGE_OR_COUNTRY, LOCAL`. |
| `primary_feed_ids` | array\<numeric string\> | Required when `ingestion_source_type=SUPPLEMENTARY_FEED`. |
| `quoted_fields_mode` | enum | `autodetect, on, off` — TSV only. |
| `rules` | list\<JSON-encoded string\> | Transformation rules applied on ingestion. |
| `schedule` | JSON-encoded string | Recurring **full-replace** fetch config — see Developer Guide §4. |
| `update_schedule` | JSON-encoded string | Recurring **partial-update** fetch config (no deletions) — see Developer Guide §4. |
| `selected_override_fields` | array\<string\> | Which fields a supplementary feed is allowed to override. |
| `use_case` | enum | `CREATOR_ASSET`. |

**Example request** (exact example from Meta's own docs — daily URL-fetch schedule at creation time):

```http
POST /v25.0/{product-catalog-id}/product_feeds HTTP/1.1
Host: graph.facebook.com

name=Test+Feed&schedule={"interval":"DAILY","url":"http://www.example.com/sample_feed.tsv","hour":"22"}
```

**Return type:**

```json
{
  "id": "numeric string",
  "errors": [ { "error_subcode": "string", "invalid_attribute": "string", "error_message": "string" } ]
}
```

**Error Codes:** 100 (invalid parameter), 190 (invalid token), 200 (permissions).

**Reading** (`GET /{product-catalog-id}/product_feeds`): no parameters; `{"data": [ProductFeed...], "paging": {}}`.

**Updating** (`POST /{product_feed_id}`): subset of create params (`default_currency`, `deletion_enabled`, `delimiter`, `encoding`, `migrated_from_feed_id`, `name`, `quoted_fields_mode`, `schedule`, `update_schedule`) — returns `{"success": bool}`.

**Deleting** (`DELETE /{product_feed_id}`): "Deleting a product feed effectively disables all ads using products that come from this feed. You can create a new feed with the same product IDs to re-enable those ads." No parameters; returns `{"success": bool}`.

(Source: https://developers.facebook.com/docs/marketing-api/reference/product-catalog/product_feeds/ and https://developers.facebook.com/docs/marketing-api/reference/product-feed/ — both fetched 2026-07-01)

---

### Feed Uploads — File, URL, and Scheduling

Three distinct mechanisms exist to get data into a `ProductFeed`; they compose (a feed can be uploaded manually once *and* have a recurring schedule).

#### 1. One-off upload via URL

```http
POST https://graph.facebook.com/v25.0/{PRODUCT_FEED_ID}/uploads
Content-Type: multipart/form-data

url=http://www.example.com/sample_feed.tsv
access_token=<ACCESS_TOKEN>
```

Meta fetches the file from the given URL at request time.

#### 2. One-off upload via direct file

```bash
curl -X POST \
  -F 'file=@reviews_of_catalog_123.csv;type=text/csv' \
  -F 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/{PRODUCT_FEED_ID}/uploads
```

Multipart file upload — the `file` field carries the binary content directly (no publicly-reachable URL needed). (Example above is from the Ratings & Reviews guide but the same `uploads` edge and `file=` mechanic apply to ordinary product feeds.)

**Response for both create-style uploads:**

```json
{ "id": "{UPLOAD_SESSION_ID}" }
```

> **(unverified)** The dedicated `product-feed/uploads` reference page's own "Creating" section is thin ("You can't perform this operation on this endpoint" appears directly under a working `curl` example with `url=`), which is contradictory/stale on Meta's side — the example curl calls in that page and in the Ratings & Reviews guide are the operative, working documentation. Treat the `uploads` POST as real and working (confirmed by two independent Meta doc pages using it), but the formal parameter table for this specific edge was not present in the fetched content.

#### 3. Checking upload status

```http
GET https://graph.facebook.com/v25.0/{product-feed-id}/uploads
```

Returns `{"data": [ProductFeedUpload, ...]}` — list of all past upload attempts (manual + scheduled), most useful for polling after a scheduled/triggered fetch. Each `ProductFeedUpload` has:

| Field | Type | Notes |
|---|---|---|
| `id` | numeric string | Upload session ID |
| `start_time` / `end_time` | datetime | |
| `filename` | string | Source filename |
| `input_method` | enum | `Manual Upload, Server Fetch, Google Sheets Fetch, Reupload Last File, User initiated server fetch` |
| `url` | string | The URL fetched from, if applicable |
| `num_detected_items` / `num_persisted_items` / `num_invalid_items` / `num_deleted_items` | int32 | Processing counts |
| `error_count` / `warning_count` | int32 | |
| `error_report` | `ProductFeedUploadErrorReport` | Downloadable error file; `POST /{upload_id}/error_report` requests generation |

Edge: `errors` — `GET /{product_feed_upload_id}/errors` → `ProductFeedUploadError` list.

#### 4. Recurring scheduling

Two independent recurring-fetch mechanisms exist on `ProductFeed`, both configured with a `ProductFeedSchedule`-shaped JSON object:

- **`schedule`** (full replace) — items missing from the fetched file on a subsequent run are **deleted** (subject to `deletion_enabled`).
- **`update_schedule`** (partial update) — only updates/creates items present in the file; **never deletes**. Useful for price/availability-only recurring updates.

`ProductFeedSchedule` fields:

| Field | Type | Notes |
|---|---|---|
| `interval` | enum | `HOURLY, DAILY, WEEKLY, MONTHLY` |
| `interval_count` | uint32 | Default 1. E.g. `interval=DAILY, interval_count=2` → every 2 days. |
| `hour` | uint32 | 0–23, **Pacific Time** (PDT/PST depending on season) unless `timezone` overrides. |
| `minute` | uint32 | 0–59 |
| `day_of_week` | enum | `SUNDAY..SATURDAY` — required for `WEEKLY` |
| `day_of_month` | uint32 | 1–31 — required for `MONTHLY` |
| `timezone` | string | Overrides the default `America/Los_Angeles`. |
| `url` | string | Feed file location to fetch on schedule. |
| `username` | string | Basic-auth username if the URL requires it. |

**Example — set schedule at feed-creation time:**

```
schedule={"interval":"DAILY","url":"http://www.example.com/sample_feed.tsv","hour":"22"}
```

**Alternative: `upload_schedules` edge** — `POST /{product_feed_id}/upload_schedules` with `upload_schedule` (JSON-encoded, same shape as `update_schedule`) sets/replaces the update-only recurring schedule without touching the rest of the feed object. `GET /{product-feed-id}/upload_schedules` returns `{"data": [ProductFeedSchedule...]}`. No Graph object is created on POST (`{"success": bool}` returned). This page was last updated Dec 4, 2019 — functionally still live (returns a valid schema in v25.0 per the live GET example on the page) but Meta has not revised its docs since; treat as a legacy-but-functioning alternate path to `update_schedule`.

**Trigger an immediate out-of-schedule fetch:** not explicitly documented as a separate endpoint in the pages fetched for this KB — **(unverified)**. Unlike Google Merchant API's `dataSources/{id}:fetch`, no equivalent `:fetch`-style action verb was found on `ProductFeed` in the fetched reference pages. If needed, re-POST to `/uploads` with the same `url=` to force an immediate fetch.

(Sources: https://developers.facebook.com/docs/marketing-api/reference/product-feed/uploads/, https://developers.facebook.com/docs/marketing-api/reference/product-feed-schedule/, https://developers.facebook.com/docs/marketing-api/reference/product-feed-upload/, https://developers.facebook.com/docs/marketing-api/reference/product-feed/upload_schedules/ — all fetched 2026-07-01)

---

### POST /{product_catalog_id}/products — Direct product creation

**Purpose:** Creates a single `ProductItem` directly via the Graph API (no feed file involved). Good for real-time onboarding of one-off items; not recommended at scale (see Developer Guide §5 decision matrix).

**Required fields:**

| Field | Type | Notes |
|---|---|---|
| `retailer_id` | string | **Required.** Unique identifier for this item (can represent a variant). This is your SKU. |
| `name` | string | **Required.** Product title. Supports emoji. |
| `currency` | ISO 4217 | **Required.** |
| `price` | int64 | **Required.** In minor units — e.g. `"599"` = 5.99, `"100"` = 1.00. |
| `image_url` | URI | **Required.** Main product image. |
| `url` | URI | Product landing-page URL (Talas: must include `?branch=`). |

**Important optional fields:**

| Field | Type | Notes |
|---|---|---|
| `allow_upsert` | boolean | Default `true`. If `retailer_id` already exists, `true` updates it in place; `false` throws an error instead. |
| `availability` | enum | `in stock, out of stock, preorder, available for order, discontinued, pending, mark_as_sold, mark_as_expired`. Default `in stock`. |
| `condition` | enum | `new, refurbished, used, used_like_new, used_good, used_fair, cpo, open_box_new`. Default `new`. **Talas: use `used` for OEM-pulled parts, `new` for new aftermarket.** |
| `brand` | string | |
| `description` | string | Max 5000 chars, supports emoji. |
| `gtin` | string | |
| `manufacturer_part_number` | string | MPN — important for auto parts matching. |
| `category` | string | Google product category for the item. |
| `product_type` | string | Retailer-defined category (use instead of `category` for a custom taxonomy). Max 750 chars. |
| `inventory` | int64 | Legacy stock count field. |
| `additional_image_urls` | list\<URL\> | |
| `custom_label_0`..`custom_label_4` | string | Max 100 chars each. |
| `visibility` | enum | `staging` or `published`. Default `published`. |
| `sale_price` / `sale_price_start_date` / `sale_price_end_date` | int64 / datetime | |
| `checkout_url` | URL | |
| `commerce_tax_category` | enum | Large controlled taxonomy, e.g. `FB_VEHI_PART` for auto parts. |
| `mobile_link` | URI | |
| `importer_name` / `importer_address` | string / JSON object | Required by some jurisdictions (not India-origin products). |

**Example request:**

```http
POST https://graph.facebook.com/v25.0/{product-catalog-id}/products
Content-Type: multipart/form-data

retailer_id=TeslaModel3RearBumper-Used-001
name=Tesla Model 3 Rear Bumper Cover — Used OEM
currency=AED
price=45000
condition=used
availability=in stock
image_url=https://cdn.talas.ae/images/tesla-m3-rear-bumper-001.jpg
url=https://shop.talas.ae/products/tesla-model3-rear-bumper?branch=QZ3
brand=Tesla
manufacturer_part_number=1084665-00-E
access_token=<ACCESS_TOKEN>
```

**Return type:** `{ "id": "numeric string" }` (read-after-write).

**Error Codes:**

| Code | Meaning |
|---|---|
| 100 | Invalid parameter |
| 200 | Permissions error |
| 10800 | Duplicate `retailer_id` when attempting to create a store collection |
| 10801 | Either "file" or "url" must be specified (returned in some upload-adjacent contexts) |

**Reading products** (`GET /{product_catalog_id}/products`): supports `filter` (JSON-encoded WCA rule), `error_priority` (`HIGH, MEDIUM, LOW`), `error_type` (huge controlled enum of catalog quality-issue codes, e.g. `EMPTY_PRICE`, `IMAGE_RESOLUTION_LOW`, `MISSING_TAX_CATEGORY`), `return_only_approved_products` (boolean), `bulk_pagination` (boolean, for iterating large catalogs in chunks). Returns `{"data": [ProductItem...], "paging": {}, "summary": {"total_count": int}}`.

**Updating / Deleting directly on this edge:** "You can't perform this operation on this endpoint" — updates go through `allow_upsert=true` re-POSTs to `products` (same `retailer_id`), or through the Catalog Batch API (`method=UPDATE`/`DELETE`), not a per-item `PATCH`/`DELETE` URL on this edge.

(Source: https://developers.facebook.com/docs/marketing-api/reference/product-catalog/products/ — fetched 2026-07-01)

---

### Catalog Batch API — `items_batch`

**Purpose:** Bulk create/update/delete of catalog items in one call — the closest analogue to Google Merchant API's per-item `productInputs:insert`, but batched, and mixing CREATE/UPDATE/DELETE in a single request.

```
POST /{catalog_id}/items_batch
```

**Limitations** (explicit, from the current reference page):

- `requests` can contain **up to 5000 items**; keep it **under 3000 for optimal performance**.
- Request payload size must not exceed **28 MB**.
- Per-catalog call-rate is governed by the Catalog Batch rate-limit formula (see Rate Limits below), not a flat number.

**Parameters:**

| Parameter | Type | Notes |
|---|---|---|
| `item_type` | string | **Required.** One of: `PRODUCT_ITEM, APP_AND_SOFTWARE, DESTINATION, FLIGHT, HOME_LISTING, HOTEL, HOTEL_ROOM, MEDIA_TITLE, STORE_PRODUCT_ITEM, VEHICLE, VEHICLE_OFFER`. Talas uses `PRODUCT_ITEM`. Note: this is NOT the same concept as the product `category` field. |
| `requests` | JSON array (string) | **Required.** Up to 5000 (recommended <3000) objects, each `{"method": "CREATE"\|"UPDATE"\|"DELETE", "data": {...}}`. CREATE must include all required fields for the `item_type`; UPDATE can be partial; DELETE needs only identifying fields (see table below). |
| `allow_upsert` | boolean | Default `true`. When `true`, `method=UPDATE` for a non-existent item creates it. When `false`, such updates are rejected. |
| `item_sub_type` | enum | Same controlled vocabulary as `ProductFeed.item_sub_type`. Default `EMPTY`. |

**Deleting — identifying fields by `item_type`:**

| `item_type` | Fields required for DELETE |
|---|---|
| `PRODUCT_ITEM` | `id` |
| `DESTINATION` | `destination_id` |
| `FLIGHT` | `destination_airport`, `origin_airport` |
| `HOME_LISTING` | `home_listing_id` |
| `HOTEL` | `hotel_id` |
| `HOTEL_ROOM` | `hotel_retailer_id`, `hotel_room_id` |
| `STORE_PRODUCT_ITEM` | `retailer_item_id`, `store_code` |
| `VEHICLE` | `vehicle_id` |
| `VEHICLE_OFFER` | `vehicle_offer_id` |

**Selected `PRODUCT_ITEM` batch fields** (superset overlaps heavily with the direct-`products`-edge fields above; batch-specific/notable additions):

| Field | Notes |
|---|---|
| `id` | Required. Max 100 chars. Must match the content ID used in the Meta Pixel for the same item, if running dynamic ads. |
| `availability` | Required. `in stock, out of stock, available for order, discontinued` |
| `brand` | Required |
| `condition` | Required. `new, refurbished, used` |
| `description` | Required. Max 5000 |
| `image` | Required. Array of up to 21 `{url, tag[]}` objects — **preferred over** the legacy `image_link`/`additional_image_link` (which are ignored if `image` is present). |
| `link` | Required. Product URL. |
| `price` | Required. String, e.g. `"14 GBP"` (value + space + ISO currency — **note this differs from the direct `products` edge, which uses a bare int64 minor-units integer**). |
| `quantity_to_sell_on_facebook` | Replaces the deprecated `inventory` field. |
| `internal_label` | Replaces the deprecated `product_tags` field; up to 5000 labels/product, 110 chars/label. |
| `disabled_capabilities` | Array — opt an item out of specific surfaces: `marketplace, b2c_marketplace, buy_on_facebook, shops, whatsapp, ldp, ...` |
| `fb_product_category` | Meta's own taxonomy (name or numeric ID), distinct from `google_product_category`. |
| `custom_number_0..4` | Whole numbers 0–4294967295, for range-filterable product-set rules. |

**Example request:**

```bash
curl -i -X POST \
  https://graph.facebook.com/v25.0/<catalog-id>/items_batch \
  -F access_token=<ACCESS_TOKEN> \
  -F 'requests=[
        {"method":"UPDATE","data":{
            "id":"TeslaModel3RearBumper-Used-001",
            "price":"450 AED",
            "availability":"in stock"
        }},
        {"method":"DELETE","data":{"id":"discontinued-sku-002"}}
      ]' \
  -F item_type=PRODUCT_ITEM
```

**Response (`{success/warnings}` shape — read-after-write NOT returned; async handle instead):**

```json
{
  "handles": ["Acy_OJLm4aVJdxiRegHfiyhleq26r_CNVRc1wFGnSj1YpFC8azbIc..."],
  "validation_status": [
    { "retailer_id": "TeslaModel3RearBumper-Used-001", "warnings": [], "errors": [] }
  ]
}
```

- `handles` — 0 or 1 element. Empty array = nothing was ingested. Use the handle to poll status.
- `validation_status[].retailer_id` — row identifier echoed back from the request.
- `validation_status[].errors` / `.warnings` — arrays of `{message: string}`.

**Error Codes:** 100 (invalid parameter), 190 (invalid token), 200 (permissions), **80014** (Catalog Batch rate limit exceeded — see below).

**Checking status:** `GET /{catalog_id}/check_batch_request_status?handle=<HANDLE>&load_ids_of_invalid_requests=true`

```json
{
  "data": [{
    "handle": "<HANDLE>",
    "status": "finished",
    "warnings": [ { "line": 1, "id": "item_id", "message": "..." } ],
    "errors_total_count": 6,
    "ids_of_invalid_requests": ["item_id", ...]
  }]
}
```
`load_ids_of_invalid_requests` defaults `false` — without it, `ids_of_invalid_requests` is always `[]` even if some rows failed.

**Legacy `/batch` endpoint:** `POST /{catalog_id}/batch` still exists but Meta's guide is explicit: **"There should be no new integrations with this endpoint. The `/items_batch` endpoint should be used instead."** `/batch` only works for `vertical=COMMERCE` catalogs; `/items_batch` supports all verticals/item types.

**Related sibling endpoint:** `POST /{catalog_id}/localized_items_batch` — same batch mechanics, but for localization overrides on items that already exist (not covered in depth here; not requested in scope).

(Sources: https://developers.facebook.com/docs/marketing-api/reference/product-catalog/items_batch/, https://developers.facebook.com/docs/marketing-api/reference/product-catalog/check_batch_request_status/, https://developers.facebook.com/docs/marketing-api/catalog/guides/manage-catalog-items/catalog-batch-api/ — all fetched 2026-07-01)

---

### Ratings and Reviews API for Products (distinct from deprecated Page reviews)

**This is a completely separate system from the old Page-level "ratings"/reviews.** Facebook retired 5-star Page ratings in **August 2018**, converting them into the yes/no "Recommendations" system (`GET /{page-id}/ratings` today actually returns `Recommendation` objects — the reference page itself is titled **"Page Recommendations"**, not "Page Reviews", confirming the old star-rating model is gone). Do not confuse that legacy/renamed Page endpoint with the API below, which is a **current, active, catalog-level product reviews ingestion pipeline** for Shops/commerce surfaces.
(Source: https://developers.facebook.com/docs/graph-api/reference/page/ratings/ — page title reads "Page Recommendations"; deprecation history corroborated via web search of Meta's August 2018 star-ratings-to-recommendations changeover.)

**How the current Product Ratings and Reviews API works** — it reuses the exact same `product_feeds` + `uploads` machinery documented above, with one feed-type flag:

**Step 1 — create a ratings/reviews feed:**

```bash
curl -X POST \
  -F 'name="Talas Product Reviews"' \
  -F 'feed_type="product_ratings_and_reviews"' \
  -F 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/{PRODUCT_CATALOG_ID}/product_feeds
```

Response: `{"id": "{PRODUCT_FEED_ID}"}` — **save this ID**, it's used in step 2.

**Step 2 — upload the reviews CSV** (via URL or direct file, same `uploads` edge as any other feed):

```bash
# Hosted file
curl -X POST \
  -F 'url="http://www.example.com/reviews_of_catalog_123.csv"' \
  -F 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/{PRODUCT_FEED_ID}/uploads

# Local file
curl -X POST \
  -F 'file=@reviews_of_catalog_123.csv;type=text/csv' \
  -F 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/{PRODUCT_FEED_ID}/uploads
```

Response: `{"id": "{UPLOAD_SESSION_ID}"}` — save for troubleshooting with Meta support if needed.

**Data file constraints:**
- Must be **CSV**.
- Must follow the **Product Review Feed Schema** (below).
- Max **100 MB** file size.

**Product Review Feed Schema — key columns:**

| Column | Type | Required? | Notes |
|---|---|---|---|
| `store.name` | string | **Required** | |
| `store.storeUrls` | array\<string\> | **Required** | |
| `reviewID` | string | **Required** | Unique per review |
| `rating` | integer | **Required** | 1–5 |
| `content` | string | **Required** | Review text, non-empty, UTF-8 |
| `created_at` | string | **Required** | ISO 8601 |
| `incentivized` | boolean | **Required** | Was the review obtained via incentivized promotion |
| `product.name` | string | **Required** | |
| `product.url` | string | **Required** | Product detail page link |
| `title` | string | Optional | Review title |
| `has_verified_purchase` | boolean | Optional | |
| `reviewer.name` | string | Conditional | Required if `reviewer.reviewerID` or `reviewer.isAnonymous` given |
| `product.productIdentifiers.gtins` / `.mpn` / `.brand` / `.skus` | — | Optional | Product matching aids |
| `product.groupID` | string | Optional | Share reviews across a variant group |
| `secondary_ratings` | Map\<string,int\> | Optional | e.g. `{"quality":5,"shipping speed":3}` |
| `merchant_response.*` | — | Conditional | Reply-to-review fields; if any one of `name`/`id`/`content`/`createdAt` is given, all become required together |

(Full column list is longer — ~30 columns total covering reviewer, product variant, and merchant-response sub-objects.)

(Sources: https://developers.facebook.com/docs/marketing-api/catalog/guides/ratings-and-reviews-api/, https://developers.facebook.com/documentation/ads-commerce/commerce-platform/platforms/feed-schema-csv — both fetched 2026-07-01)

---

## Key Request/Response Fields — Object Schemas

### ProductCatalog

```
id                   numeric string  (default field)
business             Business
da_display_settings  ProductCatalogImageSettings
default_image_url    string
fallback_image_url   list<string>
feed_count           int32
is_catalog_segment   bool
is_local_catalog     bool
name                 string          (default field)
product_count        int32
vertical             enum
```

### ProductFeed

```
id                    numeric string  (default)
country               string (ISO 3166-1 alpha-2)
created_time          datetime
default_currency      string
deletion_enabled      bool
delimiter             enum
encoding              enum
file_name             string         (default)
ingestion_source_type enum {primary_feed, supplementary_feed}
item_sub_type         enum
latest_upload         ProductFeedUpload
migrated_from_feed_id numeric string
name                  string         (default)
override_type         enum
primary_feeds         list<string>
product_count         int32
quoted_fields_mode    enum
schedule              ProductFeedSchedule
update_schedule       ProductFeedSchedule
```

### ProductFeedUpload

```
id                  numeric string (default)
end_time            datetime (default)
error_count         int32
error_report        ProductFeedUploadErrorReport
filename            string
input_method        enum {Manual Upload, Server Fetch, Google Sheets Fetch,
                          Reupload Last File, User initiated server fetch}
num_deleted_items    int32
num_detected_items   int32
num_invalid_items    int32
num_persisted_items  int32
start_time           datetime (default)
url                  string
warning_count        int32
```

### ProductFeedSchedule

```
id             numeric string (default)
day_of_month   uint32
day_of_week    enum {SUNDAY..SATURDAY}
hour           uint32 (0-23, Pacific Time by default)
interval       enum {HOURLY, DAILY, WEEKLY, MONTHLY}
interval_count uint32 (default 1)
minute         uint32 (0-59)
timezone       string
url            string
username       string
```

(Sources: https://developers.facebook.com/docs/marketing-api/reference/product-catalog/, https://developers.facebook.com/docs/marketing-api/reference/product-feed/, https://developers.facebook.com/docs/marketing-api/reference/product-feed-upload/, https://developers.facebook.com/docs/marketing-api/reference/product-feed-schedule/)

### Cross-check against `facebook-python-business-sdk` (GitHub)

Field names and enum values above were cross-checked against the official Python Business SDK source on GitHub (`facebook/facebook-python-business-sdk`, `main` branch, fetched 2026-07-01):

| SDK file | Confirms |
|---|---|
| `facebook_business/adobjects/productfeed.py` | `class Field` lists exactly: `country, created_time, default_currency, deletion_enabled, delimiter, encoding, file_name, id, ingestion_source_type, item_sub_type, latest_upload, migrated_from_feed_id, name, override_type, primary_feeds, product_count, quoted_fields_mode, schedule, supplementary_feeds, update_schedule, feed_type, override_value, primary_feed_ids, rules, selected_override_fields, use_case` — matches the doc-page field list. `class FeedType` confirms `product_ratings_and_reviews = 'PRODUCT_RATINGS_AND_REVIEWS'` as a real enum member. |
| `facebook_business/adobjects/productcatalog.py` | SDK method `create_items_batch(...)` posts to `endpoint='/items_batch'`; `create_batch(...)` (legacy) exists separately; `create_product_feed()` → `product_feeds` edge; `create_product()` → `products` edge; `create_localized_items_batch()` → `/localized_items_batch`; `create_geolocated_items_batch()` → `/geolocated_items_batch` (not covered in this doc, out of scope). All match the endpoint paths documented above. |
| `facebook_business/adobjects/productitem.py` | Confirms `ProductItem` as a distinct SDK-modeled object matching the `products` edge / batch item schema. |

Sources: https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/productcatalog.py, https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/productfeed.py, https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/productitem.py


## Pagination & Rate Limits

### Pagination

Standard Graph API cursor pagination on all list edges (`owned_product_catalogs`, `product_feeds`, `products`, `uploads`):

```
GET .../products?limit=100&after={cursor}
Response: { "data": [...], "paging": { "cursors": {...}, "next": "..." } }
```

`summary=true` (or `summary=total_count`) on the `products` edge returns `{"summary": {"total_count": N}}`.

### Rate Limits — Catalog-specific formulas

Two distinct rate-limit buckets apply, both keyed per-catalog-ID (not per-app globally), based on how much ad/PDP intent the catalog has generated in the trailing 28 days:

| Bucket | Formula | Window | Applies to |
|---|---|---|---|
| **Catalog Batch** | `Calls = 8 + 8 × log2(DA impressions + PDP visits)` | Rolling **1 minute** | `POST /{catalog_id}/items_batch`, `/localized_items_batch`, `/batch` |
| **Catalog Management** | `Calls = 20,000 + 20,000 × log2(DA impressions + PDP visits)` | Rolling **1 hour** | General catalog/product/feed CRUD endpoints |

`DA impressions + PDP visits` = dynamic-ads impressions + product-detail-page visits for the catalog (Catalog Batch formula) or across the whole business's catalogs (Catalog Management formula) in the last 28 days. More traffic → more quota.

Check current usage via the `X-Business-Use-Case` response header, which also carries `estimated_time_to_regain_access` when throttled.

**Rate-limit error codes:** `80014` = Catalog Batch limit hit; `80009` = Catalog Management limit hit.

(Source: https://developers.facebook.com/docs/graph-api/overview/rate-limiting — "Catalog" section, fetched 2026-07-01)


## Error Reference

Standard Graph API error envelope:

```json
{ "error": { "message": "...", "type": "OAuthException", "code": 100, "error_subcode": 33, "fbtrace_id": "..." } }
```

| Code | Meaning | Seen on |
|---|---|---|
| 100 | Invalid parameter | All endpoints |
| 190 | Invalid/expired OAuth 2.0 access token | All endpoints |
| 200 | Permissions error (missing `catalog_management` or not an admin on the catalog) | All endpoints |
| 102 | Session key invalid or no longer valid | Catalog create |
| 804 | Specified object already exists | Catalog create |
| 2310019 | Business not onboarded to Collaborative Ads | Catalog create (when using partner/collab fields) |
| 10800 | Duplicate `retailer_id` when creating a store collection | Direct product create |
| 10801 | Either `file` or `url` must be specified | Upload-adjacent calls |
| 80009 | Catalog Management rate limit exceeded | Most catalog/feed/product endpoints |
| 80014 | Catalog Batch rate limit exceeded | `items_batch`/`localized_items_batch`/`batch` |
| 368 | Action deemed abusive or otherwise disallowed | Reading products/catalog |
| 2500 | Error parsing graph query | Reading products with malformed `filter` |

Batch-specific validation errors don't use this envelope for per-row problems — instead they appear inside the **200 OK** response body under `validation_status[].errors[].message` (human-readable strings, e.g. `"A required field is missing: Products need to have availability listed..."`).


## Gotchas

1. **`owned_product_catalogs` is the current path; `product_catalogs` seen in some older example snippets is legacy.** Both appear in Meta's own docs (the top of the `product-catalog` reference page still shows a `product_catalogs` example), but the fully-parameterized, currently-documented creation edge is `owned_product_catalogs` on the `Business` node.

2. **Price format differs between endpoints.** The direct `products` edge takes `price` as a bare **int64 in minor units** (`"599"` = 5.99). The Catalog Batch API (`items_batch`) takes `price` as a **string with currency code embedded** (`"14 GBP"`). Sending the wrong shape to the wrong endpoint silently fails validation or gets coerced incorrectly — always match the format to the endpoint you're calling.

3. **`image` vs `image_link`.** In the Batch API, if you provide the newer `image` array field, the older `image_link` / `additional_image_link` fields are **ignored**, even if also present in the same payload. Pick one.

4. **`inventory` and `product_tags` are deprecated field names still accepted for backward compatibility.** Use `quantity_to_sell_on_facebook` and `internal_label` instead in new integrations.

5. **`schedule` is destructive; `update_schedule` is not.** A recurring `schedule` fetch is a **full replace** — any item missing from the latest file gets deleted (if `deletion_enabled=true`, which is now the default). `update_schedule` never deletes. Use `update_schedule` for a "keep the full catalog stable, just refresh price/availability" recurring job.

6. **`deletion_enabled` cannot be turned back off once enabled.** Per the docs: "Once enabled, we do not allow this field to be disabled." Treat enabling it as a one-way door.

7. **Legacy `/batch` endpoint only supports `vertical=COMMERCE`.** If a catalog is any other vertical (e.g. `vehicles`, `hotels`), `/batch` silently doesn't apply — use `/items_batch`.

8. **Catalog Batch limits: 5000 items/call max, <3000 recommended, 28 MB payload cap.** Exceeding these isn't always a clean 400 — plan for chunking uploads at ~2500-3000 items per call for reliability margin.

9. **`check_batch_request_status` needs `load_ids_of_invalid_requests=true` explicitly**, or `ids_of_invalid_requests` is always returned as an empty array even when rows failed — a common silent-failure trap when polling batch status.

10. **The Ratings & Reviews API is not a bespoke endpoint** — it's the exact same `product_feeds` + `uploads` machinery as normal product feeds, gated only by `feed_type=PRODUCT_RATINGS_AND_REVIEWS` and a different (CSV) file schema. Don't look for a separate "reviews" resource — there isn't one at the Graph API level for products.

11. **Do not confuse this with Page-level "ratings."** `GET /{page-id}/ratings` is a *different, older, unrelated* API (now internally serving `Recommendation` objects, since Meta killed 5-star Page ratings in August 2018). It has nothing to do with product reviews in a catalog.

12. **Marketing API version expiration is independent of and shorter than Graph API version expiration**, even though they share the same version number string (see Status & Versions table). A "v23.0" reference elsewhere in the docs might be fine on the general Graph API but already dead on the Marketing API — always check the Marketing API changelog table specifically for anything under `/docs/marketing-api/reference/`.

13. **`(#100) This application has not been approved to use this api` on any catalog endpoint means the app itself was never granted the `catalog_management` permission — this is an App Dashboard gate, not a per-user/asset permission and NOT fixable via any API call.** Root-caused live 2026-07-02 against App ID `1332295765705902` / Business `1183781372354749` / ad account `act_565243822008153`:
    - `GET /1183781372354749/owned_product_catalogs` (via `mads query`) returned exactly this error, `error_code: 100`.
    - `GET /me/permissions` on the authenticated user's token (which the same session confirmed CAN read campaigns/adsets/ads/insights and list Pixels fine) returned only `pages_show_list, ads_management, ads_read, business_management, pages_read_engagement, public_profile` — **`catalog_management` is absent**, matching `generate_token.py`'s `SCOPES` list, which never requested it.
    - This is a distinct failure mode from a plain `(#200)` permissions error (see the Error Reference table above, and Gotchas #11 in `kb/graph-api.md` for a worked #200 case): error code **100** with the phrase *"has not been approved to use this api"* is Meta's app-approval-gate wording, not a "you're not an admin of this asset" wording — `business_management` already being granted (and the user already being a full admin on the ad account, confirmed via `assigned_users`) does not substitute for it. `catalog_management` has its own dependency (requires `business_management`, already satisfied) and its own Business Verification requirement for Advanced Access — see the Auth/Permissions section above, sourced from `https://developers.facebook.com/docs/permissions/reference/catalog_management/`.
    - **Not fixable via any API call available to this session** — there is no endpoint that lets an authenticated admin self-grant a new OAuth permission scope to their own existing token, and no endpoint that adds a permission to an app's approved-permissions list. Both require the Meta App Dashboard UI, which only the account/app owner can access.
    - **Manual remediation steps for the account owner** (numbered, precise — perform in this order):
      1. Go to `https://developers.facebook.com/apps/1332295765705902/permissions/` (App Dashboard → your app → App Review → Permissions and Features).
      2. Search for **"Catalog Management"** (`catalog_management`) in the permissions list and click **"Get advanced access"** (Advanced Access is required for permissions requested to operate on assets not administered by the requesting user, but Standard Access is typically sufficient for an app whose only calls are made by an admin of the Business that owns the catalog — since this app already has `ads_management`/`business_management` working at Standard Access for admin-owned assets, request Standard Access first and only pursue the App Review submission for Advanced Access if Standard Access proves insufficient in testing).
      3. If Meta requires **Business Verification** before granting even Standard Access (the Auth/Permissions section above flags this as required for Advanced Access — verify at grant time whether it also gates Standard Access for this specific permission), complete it under Business Settings → Business Info → Start Verification for Business `1183781372354749` ("Talas Auto Spare Parts Trading").
      4. Once the permission shows as available/granted in the App Dashboard, uncomment the `"catalog_management"` line already prepared in `mads-cli/generate_token.py`'s `SCOPES` list (added 2026-07-02, currently commented out with this root-cause note attached).
      5. Re-run the interactive OAuth flow: `python generate_token.py` (or `--no-browser --print-url-only` on a headless host, then open the printed URL manually) to mint a new long-lived token carrying the new scope — this step requires the account owner's browser/login session and cannot be completed by an agent.
      6. Verify with `mads query --node me/permissions --json` that `catalog_management` now shows `"status": "granted"`, then re-test `mads query --node 1183781372354749/owned_product_catalogs --json`.

## Sources

All claims in this document are sourced from the following URLs, fetched 2026-07-01 (via a readability proxy where the live developers.facebook.com React app didn't render server-side for direct fetch; content was cross-checked against Wayback Machine snapshots and the official `facebook-python-business-sdk` GitHub source where noted):

| Source | URL |
|---|---|
| Business Owned Product Catalogs (creating/reading catalogs) | https://developers.facebook.com/docs/marketing-api/reference/business/owned_product_catalogs/ |
| Product Catalog (node fields, edges, updating) | https://developers.facebook.com/docs/marketing-api/reference/product-catalog/ |
| Product Catalog Product Feeds (creating feeds) | https://developers.facebook.com/docs/marketing-api/reference/product-catalog/product_feeds/ |
| Product Feed (node fields, updating, deleting) | https://developers.facebook.com/docs/marketing-api/reference/product-feed/ |
| Product Feed Uploads (file/URL upload) | https://developers.facebook.com/docs/marketing-api/reference/product-feed/uploads/ |
| Product Feed Upload (ProductFeedUpload node schema) | https://developers.facebook.com/docs/marketing-api/reference/product-feed-upload/ |
| Product Feed Schedule (ProductFeedSchedule node schema) | https://developers.facebook.com/docs/marketing-api/reference/product-feed-schedule/ |
| Product Feed Upload Schedules (alt scheduling edge) | https://developers.facebook.com/docs/marketing-api/reference/product-feed/upload_schedules/ |
| Product Catalog Products (direct product creation) | https://developers.facebook.com/docs/marketing-api/reference/product-catalog/products/ |
| Product Catalog Items Batch (Catalog Batch API) | https://developers.facebook.com/docs/marketing-api/reference/product-catalog/items_batch/ |
| Product Catalog Check Batch Request Status | https://developers.facebook.com/docs/marketing-api/reference/product-catalog/check_batch_request_status/ |
| Catalog Batch API guide (endpoint overview, legacy `/batch` deprecation notice) | https://developers.facebook.com/docs/marketing-api/catalog/guides/manage-catalog-items/catalog-batch-api/ |
| Product Ratings and Reviews API guide | https://developers.facebook.com/docs/marketing-api/catalog/guides/ratings-and-reviews-api/ |
| Product Review Feed Schema (CSV columns) | https://developers.facebook.com/documentation/ads-commerce/commerce-platform/platforms/feed-schema-csv |
| Page Ratings / Recommendations (confirms legacy Page reviews ≠ product Ratings & Reviews) | https://developers.facebook.com/docs/graph-api/reference/page/ratings/ |
| `catalog_management` permission reference | https://developers.facebook.com/docs/permissions/reference/catalog_management/ |
| Graph API / Marketing API version table (current version confirmation) | https://developers.facebook.com/docs/graph-api/changelog/versions/ |
| Graph API rate limiting (Catalog Batch / Catalog Management formulas) | https://developers.facebook.com/docs/graph-api/overview/rate-limiting |
| `facebook-python-business-sdk` — ProductCatalog source (field/method cross-check) | https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/productcatalog.py |
| `facebook-python-business-sdk` — ProductFeed source (field/enum cross-check) | https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/productfeed.py |
| `facebook-python-business-sdk` — ProductItem source | https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/productitem.py |

### Unverified Claims (flagged explicitly)

- **Programmatic catalog deletion** (`DELETE` on a `ProductCatalog` node) — not found documented in the fetched "Updating"/reference content for `product-catalog/`. Do not assume it exists without testing.
- **Immediate/manual trigger of a scheduled feed fetch outside its cadence** — no `:fetch`-style action verb was found on `ProductFeed` in the pages fetched (unlike Google Merchant API's `dataSources/{id}:fetch`). The workaround (re-POST to `/uploads` with the same `url=`) is an inference, not a documented feature.
- **`ProductFeed/uploads` formal POST parameter table** — the reference page's own "Creating" section is internally inconsistent (shows a working `curl` example immediately followed by "You can't perform this operation on this endpoint"); treated as functioning based on corroborating use in the Ratings & Reviews guide, but no clean parameter table exists for it in current docs.
- **`upload_schedules` edge currency** — its reference page was last updated Dec 4, 2019; still returns valid v25.0 example paths, but Meta has not revisited the docs text itself since, so treat it as legacy-but-functioning rather than actively maintained.
- **Exact numeric coefficients in the two rate-limit formulas could shift** without a version bump (Meta reserves the right to tune these); the formulas themselves (log2-based, per-catalog, engagement-weighted) are doc-confirmed as of 2026-07-01 but the constants (`8`, `20,000`) should be re-verified periodically rather than hardcoded as permanent.
- **`localized_items_batch` and `geolocated_items_batch`** were identified (via the SDK and the Catalog Batch guide) but not deep-dived — out of the requested scope (item/feed/batch/ratings only). Their existence is confirmed; their full field/parameter shape is not documented here.
