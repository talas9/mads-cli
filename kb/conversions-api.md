# Meta Conversions API — Server-Side Events, Pixel/Dataset Management, Deduplication, Dataset Quality

Scope of this document: the **Conversions API (CAPI)** surface of Meta's Marketing API — pixel/dataset
creation, the server-side Event schema (required/optional fields), customer-information hashing rules,
`test_event_code` testing workflow, deduplication against the browser Meta Pixel, the Dataset Quality
API, and the deprecation status of the legacy standalone Offline Conversions API. It does not cover
Campaign/AdSet/Ad CRUD or Insights (see `marketing-api.md`) or Business Manager / System User creation
(see `graph-api.md`).

**Verification method:** `developers.facebook.com`'s Conversions API guide pages are a JavaScript-rendered
SPA — direct `WebFetch` on the live URLs returned only an empty loading shell ("Get Started" header,
"[Content truncated due to length...]"), not the article body. Full page content was instead retrieved via
the **Wayback Machine** (`web.archive.org`) using snapshots dated **2026-02 through 2026-04-16**, all
within the current v25.0 doc era (the pages themselves show `v25.0` in their code examples). Every field
name below was additionally **cross-checked against the `facebook-business` Python SDK source on GitHub**
(`facebook/facebook-python-business-sdk`, `main` branch, package version `25.0.2` — i.e. version-matched to
Graph API v25.0). Anything not doc-confirmed is tagged **(unverified)**.

---

## Status & Versions

| Item | Value |
|---|---|
| Current Graph API / Marketing API version | **v25.0** — released **February 18, 2026** |
| Next version (v26.0) | **Not released as of 2026-07-01.** `https://developers.facebook.com/docs/graph-api/changelog/version26.0/` returns HTTP 404. |
| facebook-business SDK version (cross-check) | **25.0.2** (GitHub tag, matches Graph API v25.0) |
| Conversions API version-support exception | *"The Conversions API is based on Facebook's Marketing API, which was built on top of our Graph API. Marketing and Graph APIs have different version deprecation schedules. Our release cycle is aligned with the Graph API, so every version is supported for at least two years. **This exception is only valid for the Conversions API.**"* — i.e. CAPI integrations get a longer guaranteed support window than other Graph API surfaces. |
| Access token version-portability | Access tokens generated under the Conversions API tab in Events Manager are **not** locked to the Graph API version active at generation time. Since **v12.0**, these tokens work with all available Graph API versions. |
| v16.0 | Deprecated **May 14, 2025** |
| v17.0 | Deprecated **September 12, 2025** |
| v18.0 | Deprecated **January 26, 2026** |
| v19.0 | Deprecated **May 21, 2026** |
| v20.0 | Deprecated **September 24, 2026** |
| v24.0, v25.0 | Deprecation date **TBD** (not yet announced) |
| Dataset Quality API — "What's New" (as of May 28, 2025) | Added: Additional Conversions Reported (overall, per-parameter, per-event, for event coverage), Event Coverage, Event Deduplication, Data Freshness, Event Match Quality Diagnostics. Also: **Dataset Quality API for Offline Events is in beta.** |

Sources:
- https://developers.facebook.com/docs/graph-api/changelog/versions/
- https://developers.facebook.com/docs/graph-api/changelog/version26.0/ (404 — confirms v26.0 not yet shipped)
- https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api
- https://developers.facebook.com/docs/marketing-api/conversions-api/get-started/
- https://developers.facebook.com/docs/marketing-api/conversions-api/dataset-quality-api
- GitHub: `facebook/facebook-python-business-sdk` `setup.py` (`PACKAGE_VERSION = '25.0.2'`) and repo tags

---

## Base URLs

| Purpose | URL |
|---|---|
| All Graph API / Marketing API / Conversions API calls | `https://graph.facebook.com/{version}` |
| Send server-side events | `POST https://graph.facebook.com/{version}/{PIXEL_OR_DATASET_ID}/events` |
| Create a pixel/dataset under an ad account | `POST https://graph.facebook.com/{version}/act_{AD_ACCOUNT_ID}/adspixels` |
| List pixels/datasets under a Business | `GET https://graph.facebook.com/{version}/{BUSINESS_ID}/adspixels` |
| Dataset Quality API | `GET https://graph.facebook.com/{version}/dataset_quality?dataset_id={DATASET_ID}` |
| Legacy offline event uploads listing | `GET https://graph.facebook.com/{version}/{PIXEL_ID}/offline_event_uploads` |

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api

---

## Auth / Access Tokens

Unlike the Google APIs in this project's sibling `gads-cli` (`gads-cli/kb/*.md`), the Conversions API does
**not** use a classic incremental OAuth-scope model for its core event-sending flow. Instead:

| Requirement | Detail |
|---|---|
| **Pixel ID** | Required. Reuse the same Pixel ID for both browser (Meta Pixel) and server (CAPI) events for correct matching/dedup. |
| **Business Manager** | Required. |
| **Access token — Events Manager path (recommended)** | In Events Manager: choose the Pixel → Settings tab → Conversions API section → "Generate access token" (under "Set up manually"). This link is only visible to users with **developer privileges** for the business. Clicking "Manage" next to Conversions API auto-creates a CAPI app + CAPI system user — **no App Review, no permission requests needed.** |
| **Access token — own-app path** | Business Settings → assign the Pixel to your own system user (or create one) → select the system user → "Generate Token." Also **no App Review required.** |
| **Dataset Quality API — user permission** | The user/system user needs (at minimum): **Partial access → "Use events dataset."** |
| **Dataset Quality API — app permission (Basic)** | `ads_read` **and** (`ads_management` **or** `business_management`) — sufficient for managing a small number of datasets / testing. |
| **Dataset Quality API — app permission (Advanced)** | `ads_management` at **Standard Access** level, plus the **Ads Management Standard Access** app feature — required for high dataset volume or higher rate limits. **Requires App Review.** |
| **Dataset Quality API pre-July-2025 tokens** | Tokens generated in Events Manager *before* July 2025 need the advertiser to explicitly opt in (via the same Events-Manager token flow) before that token — or any other existing token for that user — can call the Dataset Quality API. |

Sources: https://developers.facebook.com/docs/marketing-api/conversions-api/get-started/, https://developers.facebook.com/docs/marketing-api/conversions-api/dataset-quality-api

---

## Resources & Endpoints

| Area | Resource | Method | HTTP | Path | Purpose | Source |
|---|---|---|---|---|---|---|
| Pixel/Dataset | `adspixels` (on `AdAccount`) | create | POST | `/act_{ad_account_id}/adspixels` | **Create a new pixel/dataset — confirmed API-scriptable.** | https://developers.facebook.com/docs/marketing-api/reference/ad-account/adspixels/ |
| Pixel/Dataset | `adspixels` (on `AdAccount`) | list | GET | `/act_{ad_account_id}/adspixels` | List pixels owned by an ad account | https://developers.facebook.com/docs/marketing-api/reference/ad-account/adspixels/ |
| Pixel/Dataset | `adspixels` (on `Business`) | list | GET | `/{business_id}/adspixels` | List pixels a Business has access to (`id_filter`, `name_filter`) | https://developers.facebook.com/docs/marketing-api/reference/business/adspixels/ |
| Pixel/Dataset | `adspixels` (on `Business`) | **create** | POST | `/{business_id}/adspixels` | **Officially documented as unsupported** ("You can't perform this operation on this endpoint") despite existing in the SDK — see Gotchas §1 | https://developers.facebook.com/docs/marketing-api/reference/business/adspixels/ |
| Events | `events` (on `AdsPixel`/dataset) | create | POST | `/{pixel_or_dataset_id}/events` | Send web, app, offline, or business-messaging server events (the unified CAPI endpoint) | https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api |
| Events | `offline_event_uploads` (on `AdsPixel`) | list | GET | `/{pixel_id}/offline_event_uploads` | List legacy offline-upload batch statuses | facebook-business SDK `adspixel.py` |
| Quality | `dataset_quality` | get | GET | `/dataset_quality?dataset_id=...` | Programmatic Event Match Quality / ACR / coverage / dedup / freshness metrics at scale | https://developers.facebook.com/docs/marketing-api/conversions-api/dataset-quality-api |
| Pixel info | `{pixel_id}` | get | GET | `/{pixel_id}?fields=is_consolidated_container` | Detect whether a pixel's dataset is "consolidated" (eligible to also carry offline events) | https://developers.facebook.com/docs/marketing-api/conversions-api/offline-events |

---

## Concrete Examples — Priority Endpoints

---

### POST /act_{AD_ACCOUNT_ID}/adspixels — Create Pixel/Dataset (API-scriptable, confirmed)

**Full HTTP request:**

```
POST https://graph.facebook.com/v25.0/act_<AD_ACCOUNT_ID>/adspixels
Content-Type: application/x-www-form-urlencoded

name=My+WCA+Pixel&access_token=<ACCESS_TOKEN>
```

```bash
curl -X POST \
  -F 'name="My WCA Pixel"' \
  -F 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/act_<AD_ACCOUNT_ID>/adspixels
```

**Parameters:**

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | Name of the pixel/dataset |

**Response (read-after-write):**
```json
{ "id": "1234567890123456" }
```

**Error codes specific to this create call:**

| Code | Meaning |
|---|---|
| `6200` | A pixel already exists for this account |
| `6202` | More than one pixel exists for this account |
| `100` | Invalid parameter |
| `190` | Invalid OAuth 2.0 access token |
| `200` | Permissions error |

**Updating / Deleting:** Both explicitly unsupported on this edge ("You can't perform this operation on
this endpoint").

**SDK cross-check** (`facebook_business/adobjects/adaccount.py`, confirms this is genuinely
API-scriptable, not UI-only):
```python
def create_ads_pixel(self, fields=None, params=None, ...):
    param_types = {'name': 'string'}
    request = FacebookRequest(
        node_id=self['id'], method='POST', endpoint='/adspixels',
        api=self._api, param_checker=TypeChecker(param_types, {}),
        target_class=AdsPixel, api_type='EDGE', ...)
```
Usage: `AdAccount(act_id).create_ads_pixel(params={'name': 'My WCA Pixel'})` → returns an `AdsPixel` object.

Source: https://developers.facebook.com/docs/marketing-api/reference/ad-account/adspixels/ (Wayback snapshot 2025-04-07, `v22.0` tab — create semantics corroborated as current by the `v25.0`-tagged SDK)

---

### `Business.create_ads_pixel` — documented as unsupported despite existing in the SDK

This is the one genuine **discrepancy** found while verifying this KB — flagged explicitly per the
verify-first mandate rather than resolved by assumption:

- The **official Graph API reference page** for `Business` → `adspixels` states, verbatim, under
  "Creating": *"You can't perform this operation on this endpoint."* Only `Reading` (`GET
  /{business-id}/adspixels`, with `id_filter` / `name_filter` params) is documented as supported.
- The **`facebook-business` Python SDK** (`facebook_business/adobjects/business.py`, `main` branch,
  version `25.0.2`) nonetheless ships a generated method:
  ```python
  def create_ads_pixel(self, fields=None, params=None, ...):
      param_types = {'is_crm': 'bool', 'name': 'string'}
      request = FacebookRequest(
          node_id=self['id'], method='POST', endpoint='/adspixels',
          api=self._api, param_checker=TypeChecker(param_types, {}),
          target_class=AdsPixel, api_type='EDGE', ...)
  ```
  targeting the exact same edge (`POST /{business_id}/adspixels`) the reference page says is disabled.

**Conclusion for `mads-cli`:** treat `AdAccount.create_ads_pixel` (`POST /act_{ad_account_id}/adspixels`)
as the **confirmed, working, API-scriptable pixel-creation path**. Do not rely on
`Business.create_ads_pixel` — it is present in the auto-generated SDK but the current official reference
explicitly documents the underlying edge as not supporting Create. **(unverified whether calling it
actually 400s in practice — this was not live-tested against a real ad account; the finding here is a
documented contradiction between two Meta-maintained sources, not a live API-call test.)**

Sources: https://developers.facebook.com/docs/marketing-api/reference/business/adspixels/ (Wayback snapshot 2025-04-08), GitHub `facebook/facebook-python-business-sdk` `facebook_business/adobjects/business.py` and `adaccount.py` (`main` branch)

---

### POST /{PIXEL_ID}/events — Send Server Event(s)

**Full HTTP request:**

```bash
curl -X POST \
  -F 'data=[
       {
         "event_name": "Purchase",
         "event_time": 1762902353,
         "user_data": {
           "em": ["309a0a5c3e211326ae75ca18196d301a9bdbd1a882a4d2569511033da23f0abd"],
           "ph": [
             "254aa248acb47dd654ca3ea53f48c2c26d641d23d7e2e93a1ec56258df7674c4",
             "6f4fcb9deaeadc8f9746ae76d97ce1239e98b404efe5da3ee0b7149740f89ad6"
           ],
           "client_ip_address": "123.123.123.123",
           "client_user_agent": "$CLIENT_USER_AGENT",
           "fbc": "fb.1.1554763741205.AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
           "fbp": "fb.1.1558571054389.1098115397"
         },
         "custom_data": {
           "currency": "usd",
           "value": 123.45,
           "contents": [{"id": "product123", "quantity": 1, "delivery_category": "home_delivery"}]
         },
         "event_source_url": "http://jaspers-market.com/product/123",
         "action_source": "website"
       }
     ]' \
  -F 'access_token=<ACCESS_TOKEN>' \
https://graph.facebook.com/v25.0/<PIXEL_ID>/events
```

**Top-level POST parameters** (`AdsPixel.create_event` in the SDK, confirming the field list): `data`
(list of Event JSON strings — **required**), `namespace_id`, `partner_agent`, `platforms`, `progress`,
`test_event_code`, `trace`, `upload_id`, `upload_source`, `upload_tag` — all optional except `data`.

**Batch and timing limits:**
- Up to **1,000 events** per `data` array. If any event in the batch is invalid, **the entire batch is
  rejected.**
- `event_time` may be up to **7 days** in the past for standard events; if any event's `event_time`
  exceeds 7 days, the **entire request** errors with zero events processed.
- For offline/physical-store events (`action_source: "physical_store"`), the window extends to **62
  days**.
- Recommended cadence: send events as they occur, ideally **within an hour**.

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api, facebook-business SDK `facebook_business/adobjects/adspixel.py`

---

### GET /dataset_quality — Dataset Quality API

**Full HTTP request:**

```bash
curl -X GET -G \
  -d 'fields=web{event_match_quality{composite_score,match_key_feedback},event_name}' \
  -d 'dataset_id=<DATASET_ID>' \
  -d 'agent_name=<AGENT_NAME>' \
  -d 'access_token=<ACCESS_TOKEN>' \
https://graph.facebook.com/v25.0/dataset_quality
```

**Query parameters:**

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `dataset_id` | integer | yes | The ID of the dataset (Pixel) to query |
| `access_token` | string | yes | Long-lived system-user token recommended |
| `agent_name` | string | no | Normalized (lowercase) `partner_agent` value; filters to events tagged with that partner agent in the `/{pixel_id}/events` POST. If omitted, all events (agent-tagged or not) are included in the EMQ calculation. |

**Example response** (`event_match_quality` field):
```json
{
  "web": [
    {
      "event_match_quality": {
        "composite_score": 6.2,
        "match_key_feedback": [
          {"identifier": "user_agent", "coverage": {"percentage": 100}},
          {"identifier": "external_id", "coverage": {"percentage": 100}}
        ]
      },
      "event_name": "pLTVPurchase"
    }
  ]
}
```

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/dataset-quality-api

---

## Key Request/Response Fields — Reference

### Server Event Parameters (top level of each object in `data[]`)

| Field | Type | Required? | Notes |
|---|---|---|---|
| `event_name` | string | **Required** | Standard or custom event name. Used with `event_id` for dedup against browser/app events. If a browser/app and server event match within 48h, only the first is kept; if both arrive within 5 minutes of each other, the browser/app event is preferred. |
| `event_time` | integer (Unix seconds) | **Required** | May be earlier than the send time (batch processing). Max 7 days in the past for standard events (62 days for `physical_store`), else the whole request errors. Must be GMT. |
| `user_data` | object | **Required** | Customer info — see Customer Information Parameters below. |
| `custom_data` | object | optional | Business data about the event — see Custom Data Parameters below. |
| `event_source_url` | string | optional (**required for website events**) | Browser URL where the event happened; should match a verified domain. |
| `opt_out` | boolean | optional | If `true`, event is used for attribution only, not ads-delivery optimization. |
| `event_id` | string | optional (**recommended for dedup**) | Any unique advertiser-chosen string (e.g. order ID). Paired with `event_name` for dedup against the Pixel's `eventID`. |
| `action_source` | string | **Required** | Where the conversion occurred — see enum below. By using CAPI you attest this value is accurate. |
| `data_processing_options` | array | optional | `["LDU"]` to enable Limited Data Use; `[]` to explicitly disable it. |
| `data_processing_options_country` | integer | required if `LDU` is set | `1` = USA, `0` = geolocate. |
| `data_processing_options_state` | integer | required in some cases | `1000` = California, `0` = geolocate. If country is set, state must also be set (or geolocation logic applies to the whole event). Required if `LDU` is set and no IP address is provided. |
| `app_data` | object | required for app events | See App Data Parameters below; contains `extinfo`. |
| `referrer_url` | string | optional | HTTP referrer header as observed by the triggering page. |
| `original_event_data` | object | optional | Associates a delayed event with a past acquisition event — see "Original Event Data Parameters." |
| `customer_segmentation` | enum | optional | One of: `new_customer_to_business`, `new_customer_to_business_line`, `new_customer_to_product_area`, `new_customer_to_medium`, `existing_customer_to_business`, `existing_customer_to_business_line`, `existing_customer_to_product_area`, `existing_customer_to_medium`, `customer_in_loyalty_program`. |

**`action_source` enum (all values):** `email`, `website`, `app`, `phone_call`, `chat`, `physical_store`,
`system_generated`, `business_messaging`, `other`.

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/server-event

---

### Customer Information Parameters (`user_data`) — Hashing Rules

**Critical rule:** *"Our systems are designed to not accept customer information that is unhashed Contact
Information... unless noted below."* Hash with **SHA-256** after normalizing per the rules below. If using
one of Meta's Business SDKs, hashing is done automatically.

| Parameter | Description | Hashing | Normalization rule |
|---|---|---|---|
| `em` | Email | **Required** | Trim leading/trailing spaces; lowercase all characters. |
| `ph` | Phone Number | **Required** | Strip symbols/letters/leading zeros; **must include country code** (e.g. US numbers prefixed with `1`) even if all your data is one country. |
| `fn` | First Name | **Required** | Roman a-z recommended, lowercase, no punctuation. UTF-8 for special characters. |
| `ln` | Last Name | **Required** | Same rule as `fn`. |
| `db` | Date of Birth | **Required** | `YYYYMMDD` format (year 1900–current, month `01`-`12`, day `01`-`31`), with or without punctuation before normalization. |
| `ge` | Gender | **Required** | Single lowercase initial: `f` or `m`. |
| `ct` | City | **Required** | Lowercase, no punctuation/special characters/spaces (UTF-8 if special chars needed). |
| `st` | State | **Required** | 2-character lowercase ANSI code (US); lowercase no-punctuation for non-US. |
| `zp` | Zip Code | **Required** | Lowercase, no spaces/dashes; first 5 digits only for US zips. |
| `country` | Country | **Required** | Lowercase ISO 3166-1 alpha-2 (e.g. `us`). Always send even if all customers share one country — improves global matching. |
| `external_id` | External ID (loyalty ID, user ID, cookie ID) | **Recommended** | Send in the same format used on other channels if sent elsewhere too. |
| `client_ip_address` | Client IP | **Do NOT hash** | Valid IPv4 or IPv6 (IPv6 preferred). Auto-added for browser events; must be manually set for server events. |
| `client_user_agent` | Client User Agent | **Do NOT hash** | **Required for website events shared via CAPI.** Auto-added for browser events; manual for server events. |
| `fbc` | Click ID (`_fbc` cookie) | **Do NOT hash** | Format: `fb.${subdomain_index}.${creation_time}.${fbclid}`. |
| `fbp` | Browser ID (`_fbp` cookie) | **Do NOT hash** | Format: `fb.${subdomain_index}.${creation_time}.${random_number}`. |
| `subscription_id` | Subscription ID | **Do NOT hash** | Analogous to an order ID for a subscription transaction. |
| `fb_login_id` | Facebook Login ID (App-Scoped ID) | **Do NOT hash** | integer. |
| `lead_id` | Lead ID (from Meta Lead Ads) | **Do NOT hash** | integer. |
| `anon_id` | Install ID | **Do NOT hash** | App events only. |
| `madid` | Mobile Advertiser ID (GAID/IDFA) | (no hashing rule stated) | |
| `page_id` | Page ID | **Do NOT hash** | For Messenger-bot business-messaging events. |
| `page_scoped_user_id` | Page-scoped user ID | **Do NOT hash** | From the messaging webhook. |
| `ctwa_clid` | Click-to-WhatsApp ID | **Do NOT hash** | |
| `ig_account_id` | Instagram Account ID | **Do NOT hash** | |
| `ig_sid` | Click-to-Instagram ID (IGSID) | **Do NOT hash** | |

**Worked SHA-256 examples (verbatim from the official doc, useful as unit-test fixtures):**

| Field | Input | Normalized | Expected SHA-256 |
|---|---|---|---|
| `em` | `John_Smith@gmail.com` | `john_smith@gmail.com` | `62a14e44f765419d10fea99367361a727c12365e2520f32218d505ed9aa0f62f` |
| `ph` | US `(650)555-1212` | `16505551212` | `e323ec626319ca94ee8bff2e4c87cf613be6ea19919ed1364124e16807ab3176` |
| `fn` | `Mary` | `mary` | `6915771be1c5aa0c886870b6951b03d7eafc121fea0e80a5ea83beb7c449f4ec` |
| `db` | `2/16/1997` | `19970216` | `01acdbf6ec7b4f478a225f1a246e5d6767eeab1a7ffa17f025265b5b94f40f0c` |
| `country` | `United States` | `us` | `79adb2a2fce5c6ba215fe5f27f532d4e7edbac4b6a5e09e1ef3a08084a904621` |

> **Independently verified**: all five digests above were recomputed locally with
> `hashlib.sha256(normalized.encode()).hexdigest()` and matched the doc's published values
> **byte-for-byte** (64 hex characters each, standard SHA-256 digest length). The doc's worked examples
> are accurate and safe to use as unit-test fixtures as-is.

**All `em`/`ph`/etc. parameters accept either a single string or a `list<string>`** — e.g. multiple phone
numbers per user: `"ph": ["<hash1>", "<hash2>"]`.

Every field above with "Hashing required/recommended" enables **Advanced Matching** parity with the
browser Meta Pixel — you can send the same identifiers via `fbq('init', 'PIXEL_ID', {external_id: 12345})`
client-side, but automatically-supplied ones (like `client_user_agent`) still need manual population
server-side.

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters

---

### Custom Data Parameters (`custom_data`) — Standard Parameters (selected)

Full table has 60+ fields split across Website / App / Offline standard-parameter name variants (e.g.
website `currency` = app `fb_currency` = offline `currency`). The most commonly needed:

| Field | Type | Notes |
|---|---|---|
| `currency` | string | **Required for Purchase events.** ISO 4217 3-letter code. |
| `value` | double | **Required for Purchase events** (and any event using value optimization). Monetary amount. |
| `content_ids` | array | Product SKUs associated with the event (e.g. `AddToCart`). |
| `content_type` | string | `product` or `product_group`. |
| `contents` | array of objects | `{id, quantity, item_price, delivery_category}` per item. |
| `delivery_category` | enum | `in_store`, `curbside`, `home_delivery` — optional, for Purchase events. |
| `order_id` | string | Transaction/order identifier — also used as the default offline-event dedup key. |
| `num_items` | integer | Use only with `InitiateCheckout`. |
| `search_string` | string | Use only with `Search` events. |
| `predicted_ltv` | double | Predicted lifetime value of the conversion. |
| `net_revenue` | double | Margin value of a conversion. |
| `item_number` | string | Distinguishes events within the same order/transaction (used in offline dedup). |
| `lead_event_source` | string | For CRM-integrated lead events. |

Vertical-specific fields also exist for automotive (`body_style`, `make`, `model`, `vin`, `mileage.value`,
...), travel/hotel (`checkin_date`, `destination_airport`, `travel_class`, ...), and real estate
(`property_type`, `listing_type`, `preferred_beds_range`, ...) catalogs — see the full source page for the
complete list; not reproduced here as `mads-cli` targets Tesla/Korean auto **parts** (see the account's own
business rules), not vehicle-listing catalogs.

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/custom-data

---

### App Data Parameters (`app_data`) — required for app events

`app_data.extinfo` is a **positional array** (order matters; use `""` placeholder for missing values):

| Index | Field | Type | Example |
|---|---|---|---|
| 0 | extinfo version (**required**: `a2` Android / `i2` iOS) | string | `i2` |
| 1 | app package name | string | `com.facebook.sdk.samples.hellofacebook` |
| 2 | short version | string | `1.0` |
| 3 | long version | string | `1.0 long` |
| 4 | OS version (**required**) | string | `13.4.1` |
| 5 | device model name | string | `iPhone5,1` |
| 6 | locale | string | `En_US` |
| 7 | timezone abbreviation | string | `PDT` |
| 8 | carrier | string | `AT&T` |
| 9 | screen width | int64 | `320` |
| 10 | screen height | int64 | `568` |
| 11 | screen density | string | `2` |
| 12 | CPU cores | int64 | `2` |
| 13 | external storage size (GB) | int64 | `13` |
| 14 | free external storage (GB) | int64 | `8` |
| 15 | device timezone | string | `USA/New York` |

Other `app_data` fields (all optional unless noted): `advertiser_tracking_enabled` (**required for app
events**, boolean), `application_tracking_enabled` (**required for app events**, boolean), `campaign_ids`,
`install_referrer` (Android only), `installer_package`, `url_schemes`, `windows_attribution_id`,
`vendor_id`.

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/app-data

---

## test_event_code — Test Events Tool

- Location: **Events Manager → Data Sources → your Pixel → Test Events.** The tool generates a test code
  (e.g. `TEST123`).
- Send it as the **top-level** `test_event_code` field alongside `data` (not nested inside each event
  object):
  ```json
  {
    "data": [ { "event_name": "ViewContent", "event_time": 1764975551, "...": "..." } ],
    "test_event_code": "TEST123"
  }
  ```
- **Events sent with `test_event_code` are NOT dropped** — they still flow into Events Manager and count
  for targeting/measurement. It is purely a routing hint that surfaces the event live in the Test Events
  UI within Events Manager (verification typically visible within ~20 minutes for normal, non-test sends).
- **Must be removed before sending production payloads** — it's for validation only, not a "safe sandbox"
  flag that suppresses real delivery.
- The **Payload Helper** tool can generate a complete test payload (including `test_event_code`) from a
  point-and-click form.

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api

---

## Deduplication — Conversions API vs. Browser Meta Pixel

Meta recommends a **"redundant setup"** (both Pixel and CAPI sending the same events) for maximum
coverage, which requires deduplication so the same real-world action isn't double-counted.

### Method 1 — `event_id` + `event_name` (recommended)

- Add a **unique `event_id`** to both the CAPI server event and the corresponding Pixel `eventID`
  (4th argument of `fbq('track', ...)`).
- Dedup match requires **both**: `eventID` (Pixel) == `event_id` (CAPI), **and** `event` (Pixel) ==
  `event_name` (CAPI).
- If server and browser events don't differ meaningfully, Meta generally **keeps whichever arrives
  first.**
- **Discard window: within 48 hours** of the first-received event with a given `event_id`/`event_name`
  combination.
- A natural `event_id` choice: order/transaction ID for purchases; a random string (shared between
  browser and server calls) for events without an intrinsic ID.

```js
// Standard track call for all Pixels on the page
fbq('track', 'Purchase', {value: 12, currency: 'USD'}, {eventID: 'EVENT_ID'});

// trackSingle for one specific Pixel ID
fbq('trackSingle', 'SPECIFIC_PIXEL_ID', 'Purchase', {value: 12, currency: 'USD'}, {eventID: 'EVENT_ID'});

// Image-Pixel fallback
// <img src="https://www.facebook.com/tr?id=PIXEL_ID&ev=Purchase&eid=EVENT_ID"/>
```

### Method 2 — `fbp` and/or `external_id` (fallback)

- Consistently send `event_name` + `fbp` and/or `external_id` from **both** browser and server.
- **Limitation 1:** generally only dedups **browser-first** events — a server event is *not* discarded
  just because a matching browser event later arrives; if the server event was received first, the
  subsequent browser duplicate is not guaranteed to be suppressed either way in all cases.
- **Limitation 2:** does **not** dedup within a single source — two consecutive browser-only or two
  consecutive server-only identical events are never discarded by this method.

### General dedup rules

- If a server event and a browser/app event arrive **within ~5 minutes** of each other, Meta **favors the
  browser/app event**.
- Otherwise, Meta generally keeps whichever event (server or browser) it **received first**.
- **Maximum dedup window: 48 hours** from the first-received event.
- **Offline events dedup only against other offline events** (never against Pixel/browser events) — see
  the Offline Conversions section below for the specific key logic.

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events/

---

## Dataset Quality API

*(Formerly called the "Integration Quality API".)* Solves the problem of monitoring Event Match Quality
(EMQ) at scale — the in-Events-Manager EMQ score view is per-pixel and doesn't scale to a partner/agency
managing hundreds or thousands of pixels.

**Endpoint:** `GET https://graph.facebook.com/v25.0/dataset_quality`

**Query params:** `dataset_id` (required, integer — the Pixel ID), `access_token` (required), `agent_name`
(optional — normalized-lowercase `partner_agent` filter).

**Top-level response field:** `web` — an array, one entry per event name, each entry a struct with:

| Field | Type (per docs) | Purpose |
|---|---|---|
| `event_name` | string | Standard or custom event name |
| `event_match_quality` | `AdsPixelCAPIEMQ` object | `composite_score` (0-10) + `match_key_feedback[]` (`identifier`, `coverage.percentage`, optionally `diagnostics[]` and `potential_aly_acr_increase`) |
| `event_potential_aly_acr_increase` | `AdsPixelCAPIEventALYACR` | Estimated conversions unlocked by improving this event's CAPI setup |
| `acr` | `AdsDatasetCAPIACR` | Additional Conversions Reported — overall lift from using CAPI alongside the Pixel (`percentage`, `description`) |
| `event_coverage` | `AdsDatasetEventCoverage` | 7-day average % of Pixel events also covered (with shared dedup keys) by CAPI (`percentage`, `goal_percentage`, `description`, nested `potential_aly_acr_increase`) |
| `dedup_key_feedback` (docs) / `dedupe_key_feedback` (SDK) | `AdsDatasetDedupKeyFeedback` | Per dedup-key (`event_id`, `external_id`, `fbp`, ...) coverage percentages on both browser and server sides |
| `data_freshness` | `AdsDatasetDataFreshness` | `upload_frequency` (`real_time`, `hourly`, ...) + `description` — delay between event occurrence and receipt |

> Field-name note **(unverified nuance)**: the prose docs use `dedup_key_feedback`; the GraphQL-style
> examples and the SDK's generated `AdsPixelCAPIIntegrationQuality` class both use `dedupe_key_feedback`
> (with the extra `e`). Use `dedupe_key_feedback` — it matches both the SDK field name and the working curl
> examples in the doc. The SDK class also lists two fields (`event_ad_sets`, `event_spend`) that are **not**
> documented in the prose Dataset Quality API page at all — these are auto-generated/codegen fields not yet
> covered by human-written docs; treat them as **(unverified)** until confirmed by a live response.

**EMQ (Event Match Quality) specifics:**
- Score out of **10**, calculated in real time from which customer-info parameters are received, their
  quality, and the % of instances matched to a Meta account.
- **Web events only** — not available for offline, physical-store, app, conversion-leads, or
  alpha/beta-stage event types (contact your Meta rep for those).

**Example — EMQ diagnostics query:**
```
GET /v25.0/dataset_quality?dataset_id=<DATASET_ID>&agent_name=<AGENT_NAME>&access_token=<ACCESS_TOKEN>&fields=web{event_match_quality{diagnostics},event_name}
```
```json
{
  "web": [{
    "event_match_quality": { "diagnostics": [{
      "name": "Update your IPv4 IP addresses to IPv6 IP addresses",
      "description": "Your server is sending IPV4 IP addresses through the Conversions API...",
      "solution": "You can update your web server and DNS provider configuration to support IPv6...",
      "percentage": 59.5, "affected_event_count": 18930, "total_event_count": 31830
    }]},
    "event_name": "Purchase"
  }]
}
```

**Example — Event Coverage query:**
```
GET /v25.0/dataset_quality?dataset_id=<DATASET_ID>&access_token=<ACCESS_TOKEN>&fields=web{event_coverage{percentage,goal_percentage,description},event_name}
```
```json
{"web": [{"event_coverage": {"percentage": 34.1, "goal_percentage": 75, "description": "..."}, "event_name": "B2B Purchase"}]}
```

**FAQ callouts from the official page:**
- *"The access token is used when partners send signal events or access the Setup Quality API on behalf
  of advertisers. The client system user access token onboarding method is not compatible with the EMQ API
  at the moment."*
- Access tokens generated in Events Manager **before July 2025** require an explicit advertiser opt-in
  (via the same Events-Manager flow) before that token (or any of that user's existing tokens) can call
  the Dataset Quality API.

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/dataset-quality-api

---

## Offline Conversions API — Deprecation Status

**Status: legacy / not recommended for new integrations; no confirmed hard shutdown date found in current
official docs as of 2026-07-01.**

**What the current official docs literally say:**

1. From "Using the API" (`.../conversions-api/using-the-api`): *"Note: The App Events and Offline
   Conversions APIs are no longer recommended for new integrations. Instead, it is recommended that you
   use the Conversions API as it now supports web, app, and offline events."*
2. From "Conversions API for Offline Events" (`.../conversions-api/offline-events`): datasets can show
   event data from — among other sources — **"Offline Conversions API (Meta's legacy API for offline
   events)."** The word "legacy" is the docs' own characterization.
3. The **same page** also says the `upload_tag` parameter *"is still supported for offline event uploads
   for advertisers using legacy API for offline events"* — i.e., as of this doc snapshot the legacy path
   is still functionally live for existing integrations, just not the recommended path for new ones.

**URL-redirect evidence (confirms the legacy standalone doc/product surface has been folded into the
unified CAPI, but is not itself proof of a hard API shutdown):**

- The old standalone reference URL `https://developers.facebook.com/docs/marketing-api/offline-conversions`
  has **301-redirected** to `.../conversions-api/offline-events` continuously across every Wayback Machine
  snapshot checked from **2026-02-04 through 2026-06-26**.
- As of a **2026-05-05** snapshot onward, `.../conversions-api/offline-events` itself started 301-redirecting
  again, this time to `https://developers.facebook.com/documentation/ads-commerce/conversions-api/offline-events`
  — this is part of a **site-wide URL/IA restructure** (the `get-started` and other CAPI pages show the same
  `/documentation/ads-commerce/...` migration target), **not** evidence specific to Offline Conversions
  being killed — the content moved, the redirect chain is just two hops deep.

**Current recommended architecture (per the docs):** all offline/physical-store events should go through
the **same unified endpoint** as web/app events: `POST /{DATASET_ID}/events` with `action_source:
"physical_store"` (or `"system_generated"` for automatic events like subscription renewals), rather than a
separate offline-conversions-specific upload flow. A "dataset" is the unifying concept — one dataset can
carry Pixel (web), App Events API, legacy Offline Conversions API, and Messaging Events data
simultaneously. Detect eligibility via `GET /{pixel_id}?fields=is_consolidated_container`.

**Offline-event specifics still relevant if migrating a legacy integration:**
- Offline events dedup **only against other offline events** (never against Pixel events), using the
  combination of `dataset_id` + `event_time` + `event_name` + `item_number` + a key field.
- Default key is **`order_id`**; if absent, falls back to **user-based dedup** (matching Customer
  Information Parameters).
- **Maximum dedup window: 7 days.**
- Upload window: **within 62 days** of the conversion for `physical_store` action-source events.
- The **Dataset Quality API for Offline Events is in beta** (per the Dataset Quality API page's "What's
  New" section) — i.e. offline-event quality metrics are not yet at full GA parity with the web-event
  Dataset Quality API described above.

**Third-party claims explicitly NOT adopted here:** general web search results surfaced third-party blog
claims of a hard "Offline Conversions API dies May 2025" / "v16.0 was the last supported version" shutdown.
This directly **contradicts** the official doc snapshot dated **2026-04-16** (well after May 2025), which
still describes `upload_tag` as *"still supported... for advertisers using legacy API for offline events."*
Per the verify-first mandate, these third-party shutdown-date claims are **rejected as unverified /
contradicted by the primary source** rather than reported as fact. **Treat the Offline Conversions API as
"deprecated for new use, no confirmed forced shutdown date," not as already fully decommissioned.**

Sources: https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api, https://developers.facebook.com/docs/marketing-api/conversions-api/offline-events, https://developers.facebook.com/docs/marketing-api/offline-conversions (redirect-only, confirmed via Wayback Machine CDX index 2026-02 through 2026-06)

---

## Error Responses — Common Patterns

| Code | Meaning | Where seen |
|---|---|---|
| `100` | Invalid parameter | `adspixels` create, general |
| `190` | Invalid OAuth 2.0 access token | `adspixels` create/list, general |
| `200` | Permissions error | `adspixels` create/list, general |
| `270` | Ads API request not allowed at Development access level; token must belong to a user who is both app admin and ad-account admin | `Business` → `adspixels` list |
| `104` | Incorrect signature | `Business` → `adspixels` list |
| `368` | Action deemed abusive/disallowed | `Business` → `adspixels` list |
| `2500` | Error parsing graph query | `adspixels` list |
| `6200` | A pixel already exists for this account | `adspixels` create |
| `6202` | More than one pixel exists for this account | `adspixels` create |
| `80004` | Too many calls to this ad account; back off and retry | `adspixels` list/create (Ads Management rate limiting) |
| *(implicit)* | `event_time` more than 7 days (62 for `physical_store`) in the past on **any** event in the batch → **the entire request is rejected**, zero events processed | `POST /{pixel_id}/events` |
| *(implicit)* | Any single invalid event in a batch of up to 1,000 → **the entire batch is rejected** | `POST /{pixel_id}/events` |

Source: https://developers.facebook.com/docs/marketing-api/reference/ad-account/adspixels/, https://developers.facebook.com/docs/marketing-api/reference/business/adspixels/, https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api

---

## Gotchas

1. **`Business.create_ads_pixel` is a documented contradiction** — the SDK ships it, but the official
   Graph API reference for `Business` → `adspixels` explicitly disables Create on that edge. Use
   `AdAccount.create_ads_pixel` (`POST /act_{ad_account_id}/adspixels`) as the confirmed working path for
   `mads-cli`.

2. **`event_time` windows differ by `action_source`**: 7 days for normal events, **62 days** for
   `physical_store`/offline events. Exceeding either rejects the **whole batch**, not just the offending
   event.

3. **Batch size cap is 1,000 events**, and **one bad event fails the entire call** — validate client-side
   before sending, don't rely on the API to skip-and-continue.

4. **`test_event_code` does not sandbox delivery** — test events still count for targeting/measurement in
   Events Manager. It's a visibility aid, not a safe no-op flag. Remove before production.

5. **Dedup precedence:** if server and browser/app events for the same `event_id`+`event_name` arrive
   within ~5 minutes of each other, **the browser/app event wins**; otherwise whichever arrives first
   within the 48-hour window wins. Offline events dedup **only** against other offline events (separate 7-
   day window, different key logic based on `order_id`/`item_number`).

6. **Hashing table has three distinct buckets**, easy to get wrong: (a) `em`/`ph`/`fn`/`ln`/`ge`/`db`/`ct`/
   `st`/`zp`/`country` — **hashing required**; (b) `external_id` — **hashing recommended** (not strictly
   required); (c) `client_ip_address`/`client_user_agent`/`fbc`/`fbp`/`subscription_id`/`fb_login_id`/
   `lead_id`/`anon_id`/`page_id`/`page_scoped_user_id`/`ctwa_clid`/`ig_account_id`/`ig_sid` — **must never
   be hashed**. Hashing an already-plaintext-required field (or vice versa) silently degrades match
   quality rather than erroring.

7. **"Pixel" and "Dataset" are now largely the same underlying object** — a "dataset" is the umbrella
   concept that can carry Pixel (web), App Events, legacy Offline Conversions, and Messaging Events data
   together. `dataset_id` in Dataset Quality API calls == the Pixel ID for a consolidated container. Check
   `GET /{pixel_id}?fields=is_consolidated_container` before assuming a given pixel can also accept offline
   events.

8. **Legacy doc URLs are 301-redirect chains, not dead ends** — `/docs/marketing-api/offline-conversions`
   → `/docs/marketing-api/conversions-api/offline-events` → (as of ~May 2026)
   `/documentation/ads-commerce/conversions-api/offline-events`. Bookmark the canonical
   `/docs/marketing-api/conversions-api/...` paths used throughout this KB; expect them to eventually
   redirect to the `/documentation/ads-commerce/...` IA as Meta's docs site migration proceeds.

9. **Marketing API (including CAPI) is excluded from standard Graph API rate limiting** — it has its own
   logic, and Conversions API calls are simply counted as Marketing API calls. The practical ceiling for
   CAPI specifically is the **1,000-events-per-request** batch cap, not a requests-per-hour throttle.

10. **Dataset Quality API access-token onboarding is stricter than plain event-sending** — a token that
    works fine for `POST /{pixel_id}/events` may still be rejected by `GET /dataset_quality` if it predates
    July 2025 and the advertiser hasn't done the explicit Events-Manager opt-in for Dataset Quality API
    access.

---

## Coverage vs. Current `mads-cli`

`mads-cli` is a **fresh scaffold** as of this KB's writing — `mads_lib/` contains only
`cli.py`, `auth.py`, `db.py`, `dbread.py`, `output.py`, `catalog.py`, `timeutil.py`, `config.py`, `http.py`,
and `__init__.py`; there is **no Conversions API or Marketing API client module implemented yet**. This
document is written to seed that first implementation (mirroring the REST-first, no-vendor-SDK design
already used by the sibling `gads-cli` project — see `gads-cli/CLAUDE.md`: *"The CLI uses Google's REST
APIs directly... NOT the Python client library"*). Priority endpoints to implement first, in order of
likely value to Talas's Meta Ads workflow:

1. `POST /act_{ad_account_id}/adspixels` — create/verify the pixel/dataset exists
2. `POST /{pixel_id}/events` — send server-side conversion events (with `test_event_code` support for a
   `--test` CLI flag)
3. `GET /dataset_quality` — surface EMQ/ACR/coverage/freshness in a `mads capi quality` style command
4. `GET /{pixel_id}?fields=is_consolidated_container` — detect offline-event eligibility

---

## Sources

| URL | What It Documents |
|---|---|
| https://developers.facebook.com/docs/marketing-api/conversions-api/get-started/ | Prerequisites, access-token generation (Events Manager vs. own-app paths) |
| https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api | Send-events endpoint, batch/time limits, `test_event_code`, rate-limit notes, App-Events/Offline-Conversions deprecation notice, Business SDK Gateway features |
| https://developers.facebook.com/docs/marketing-api/conversions-api/parameters | Parameter taxonomy overview (main body / server event / customer info / app data) |
| https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/server-event | Full server Event schema field reference |
| https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters | `user_data` fields + SHA-256 hashing/normalization rules + worked examples |
| https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/custom-data | `custom_data` standard parameters (Website/App/Offline name variants) |
| https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/app-data | `app_data`/`extinfo` schema for app events |
| https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events/ | Event-ID/event-name and fbp/external-id dedup methods, 48h window, limitations |
| https://developers.facebook.com/docs/marketing-api/conversions-api/dataset-quality-api | Dataset Quality API endpoint, fields (EMQ, ACR, event coverage, dedup key feedback, data freshness), permissions, FAQs |
| https://developers.facebook.com/docs/marketing-api/conversions-api/offline-events | Current "Conversions API for Offline Events" guide — dataset concept, legacy-API framing, dedup rules, `is_consolidated_container` |
| https://developers.facebook.com/docs/marketing-api/offline-conversions | Legacy standalone doc — confirmed 301-redirect-only via Wayback CDX (2026-02 through 2026-06) |
| https://developers.facebook.com/docs/marketing-api/reference/ad-account/adspixels/ | `AdAccount` → `adspixels` Create/Read reference — confirms API-scriptable pixel creation |
| https://developers.facebook.com/docs/marketing-api/reference/business/adspixels/ | `Business` → `adspixels` reference — confirms Create is documented as unsupported (contradicts SDK) |
| https://developers.facebook.com/docs/graph-api/changelog/versions/ | Graph API version list + deprecation dates |
| https://developers.facebook.com/docs/graph-api/changelog/version26.0/ | 404 — confirms v26.0 not yet released as of 2026-07-01 |
| GitHub `facebook/facebook-python-business-sdk` (`main`, tag `25.0.2`) — `adaccount.py`, `business.py`, `adspixel.py`, `adspixelcapiintegrationquality.py`, `dataset.py` | Field-name/method cross-check for pixel creation, event sending, Dataset Quality API response shape |

**Retrieval note:** live `WebFetch` against `developers.facebook.com` guide pages returned only empty
JS-shell content ("[Content truncated due to length...]"); all guide-page content above was retrieved via
Wayback Machine snapshots dated between **2026-02-04 and 2026-04-16** (all showing `v25.0` in their code
samples, i.e. current-era content, not stale). Reference-style pages (`/reference/...`) were similarly
JS-truncated live and were retrieved via Wayback Machine snapshots dated **2025-04-07/08** (the most recent
available in the index at the time of writing); their structural claims (parameters, Create/Read/Update/
Delete support matrix, error codes) were cross-checked against the `v25.0`-tagged SDK and found consistent,
so treated as still current. The 301-redirect evidence for Offline Conversions API used the Wayback
Machine **CDX API** (`web.archive.org/cdx/search/cdx`) directly, which is a lower-level index query, not a
guide-page fetch.

---

## Developer Guide

A deeper reference supplementing the concrete examples above with full schemas, worked examples, and
operational guidance — sufficient for an LLM agent to implement against the Conversions API without
re-fetching docs.

---

### 1. Pixel / Dataset Creation — Full Walkthrough

**API-scriptable path (confirmed):**
```bash
curl -X POST \
  -F 'name="Talas Website Pixel"' \
  -F 'access_token=<SYSTEM_USER_TOKEN>' \
  https://graph.facebook.com/v25.0/act_<AD_ACCOUNT_ID>/adspixels
# => {"id": "1234567890123456"}
```
This is a genuine, documented, API-scriptable create operation — **not** UI-only. It requires only a
valid ad-account-scoped access token with standard ads permissions; no special app review.

**UI-only path (also valid, and what Meta's own "Get Started" guide walks through by default):** Events
Manager → "Connect Data Sources" → "Web" → follow the pixel-setup wizard. This is what most human
advertisers do, and it's why the Get Started guide reads as UI-oriented — but the underlying resource
(`AdsPixel`) is fully API-manageable via the `AdAccount` edge above.

**Constraints surfaced by the error-code table:** Meta's data model historically expected **one pixel per
ad account** in the common case — `6200` fires if you try to create a second one, `6202` if the account
already somehow has more than one. In practice, most accounts today use one pixel/dataset per ad account
or per property; don't assume you can freely spin up many pixels under a single `act_` ID without hitting
this guard.

**Reading:**
```bash
curl -G \
  -d 'fields=code' \
  -d 'access_token=<ACCESS_TOKEN>' \
  https://graph.facebook.com/v25.0/<PIXEL_ID>/
```
Notable `AdsPixel` fields (from SDK `Field` enum — full list, useful for a `mads pixel show` command):
`automatic_matching_fields`, `can_proxy`, `code` (the JS snippet), `config`, `creation_time`, `creator`,
`data_use_setting`, `description`, `duplicate_entries`, `enable_auto_assign_to_accounts`,
`enable_automatic_matching`, `event_stats`, `event_time_max`, `event_time_min`,
`first_party_cookie_status`, `has_1p_pixel_event`, `id`, `is_consolidated_container`,
`is_created_by_business`, `is_crm`, `is_mta_use`, `is_restricted_use`, `is_unavailable`,
`last_fired_time`, `last_upload_app`, `last_upload_app_changed_time`, `match_rate_approx`,
`matched_entries`, `name`, `owner_ad_account`, `owner_business`, `usage`, `user_access_expire_time`,
`valid_entries`.

**Updating / Deleting a pixel via this edge:** both explicitly unsupported per the official reference
("You can't perform this operation on this endpoint") — pixel renaming/config changes go through other
`AdsPixel`-scoped edges (e.g. `create_event`, `assigned_users`), not a PATCH/DELETE on `adspixels` itself.

Sources: https://developers.facebook.com/docs/marketing-api/reference/ad-account/adspixels/, GitHub SDK `adspixel.py`, `adaccount.py`

---

### 2. Server-Side Event Schema — Practical Payload Construction

A minimally-valid server event needs just `event_name`, `event_time`, `user_data` (at least one identifier),
and `action_source`. A well-formed Purchase event for a Talas-style e-commerce/parts flow:

```json
{
  "data": [
    {
      "event_name": "Purchase",
      "event_time": 1751000000,
      "event_id": "order-58213",
      "event_source_url": "https://shop.talas.ae/checkout/complete?branch=qz3",
      "action_source": "website",
      "user_data": {
        "em": ["<sha256-lowercased-trimmed-email>"],
        "ph": ["<sha256-country-code-digits-only>"],
        "client_ip_address": "203.0.113.4",
        "client_user_agent": "Mozilla/5.0 ...",
        "fbc": "fb.1.1554763741205.AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
        "fbp": "fb.1.1558571054389.1098115397",
        "external_id": ["<sha256-of-internal-customer-id>"]
      },
      "custom_data": {
        "currency": "aed",
        "value": 245.00,
        "content_ids": ["TESLA-BRK-PAD-001"],
        "content_type": "product",
        "order_id": "58213"
      }
    }
  ]
}
```

Note **all costs must be sent in the currency they were charged in** (`currency` field), independent of
whatever reporting currency the account's Ads Manager view uses — this is a common source of mismatched
ROAS calculations if not handled consistently.

---

### 3. Hashing — Implementation Pattern

```python
import hashlib

def normalize_email(raw: str) -> str:
    return raw.strip().lower()

def normalize_phone(raw: str, country_calling_code: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    digits = digits.lstrip("0")
    if not digits.startswith(country_calling_code):
        digits = country_calling_code + digits
    return digits

def hash_field(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

em_hash = hash_field(normalize_email("John_Smith@gmail.com"))
# => "62a14e44f765419d10fea99367361a727c12365e2520f32218d505ed9aa0f62f"
# (64 hex chars — matches the doc's published digest exactly, independently verified above)
```

**Never hash:** `client_ip_address`, `client_user_agent`, `fbc`, `fbp`, `subscription_id`, `fb_login_id`,
`lead_id`, `anon_id`, `page_id`, `page_scoped_user_id`, `ctwa_clid`, `ig_account_id`, `ig_sid`.
**Hash (required):** `em`, `ph`, `fn`, `ln`, `ge`, `db`, `ct`, `st`, `zp`, `country`.
**Hash (recommended, not required):** `external_id`.

---

### 4. Verifying a New Integration

1. Send a few events with a `test_event_code` and confirm they appear in **Events Manager → Test Events**
   within the tool's live window.
2. Remove `test_event_code`, send a production event, and confirm within Events Manager: **Data Sources →
   your Pixel → Overview** — check raw/matched/attributed event counts and the "Connection Method" column
   to confirm events are arriving via the expected channel (Conversions API vs. Pixel).
3. If running a redundant Pixel+CAPI setup, verify deduplication is working by confirming the **Connection
   Method** shows a blended "Browser and Server" indicator rather than double-counted separate rows.
4. Query `GET /dataset_quality` for the `event_coverage` and `dedup_key_feedback` fields to catch
   dedup-key mismatches (e.g., `fbp` never populated server-side) before they silently inflate reported
   conversions.

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api

---

### 5. Business SDK Features for Conversions API (if adopting a vendor SDK instead of raw REST)

Meta's Business SDKs (PHP ≥7.2, Node.js ≥7.6.0, Java ≥8, Python ≥2.7, Ruby ≥2 — PHP 5 support has been
deprecated since January 2019) offer three CAPI-specific conveniences on top of raw REST:

- **Asynchronous Requests** — `EventRequestAsync` / `.executeAsync()` instead of blocking `.execute()`.
- **Concurrent Batching** — send multiple `Event` objects in one `EventRequest`.
- **HTTP Service Interface / Conversions API Gateway support** — `CAPIGatewayIngressRequest` lets you
  route events through a **Conversions API Gateway** instance (a first-party proxy pattern for
  server-side tagging setups, analogous in spirit to Google's server-side GTM) with a `setFilter()` hook
  to conditionally drop events client-side before they're forwarded.

`mads-cli` currently has **no dependency on any vendor SDK** (per `pyproject.toml` comments: "no
google-auth equivalent is needed here"), consistent with the REST-first design already used by `gads-cli`
— so these SDK-specific features are informational only unless a future decision is made to adopt the
Python Business SDK instead of raw `requests` calls.

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api

---

### 6. Rate Limits and Batch Constraints — Summary

| Constraint | Value |
|---|---|
| Max events per `POST /events` call | 1,000 |
| Recommended send cadence | As events occur; within 1 hour at the latest |
| `event_time` max age (standard events) | 7 days |
| `event_time` max age (`physical_store` / offline events) | 62 days |
| Offline-event dedup window | 7 days |
| Pixel/browser dedup window | 48 hours |
| Rate limiting model | CAPI calls are counted as **Marketing API** calls, which are **excluded from standard Graph API throttling**; no separate CAPI-specific requests/hour limit is documented beyond the 1,000-event batch cap |

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api

---

### 7. Best Practices Summary

- Always send **both** `client_ip_address` and `client_user_agent` for website events — improves matching
  and ad-delivery optimization, and `client_user_agent` is technically required for website `action_source`.
- Always include `country` in `user_data` even for single-market accounts (like Talas/UAE) — improves
  global match-rate scoring per Meta's own guidance.
- Prefer **IPv6** `client_ip_address` values when available (Dataset Quality API's own EMQ diagnostics
  flag IPv4-only servers as an improvement opportunity).
- Use the **`event_id` + `event_name`** dedup method over the `fbp`/`external_id` fallback — it's simpler
  to reason about and doesn't have the browser-first-only limitation.
- Run `GET /dataset_quality` periodically (not just at initial setup) — EMQ, event coverage, and dedup-key
  feedback are all **live-computed 7-day rolling metrics** that drift as site/checkout code changes.
- For any offline/physical-store event ingestion, prefer the **unified `/events` endpoint with
  `action_source: "physical_store"`** over building a new integration against the legacy standalone Offline
  Conversions API surface — the docs already call the latter "legacy."

Source: https://developers.facebook.com/docs/marketing-api/conversions-api/dataset-quality-api, https://developers.facebook.com/docs/marketing-api/conversions-api/offline-events
