# Meta Marketing API — Campaigns, Ad Sets, Ads, Creatives, Audiences

> Implementation-grade reference for building `mads-cli` subcommands that create/read/update
> Campaign, AdSet, Ad, AdCreative, Custom Audience, Lookalike Audience, and Ad Study (split-test)
> resources. Every field name and enum value below is either (a) transcribed from an official
> `developers.facebook.com` doc page fetched 2026-07-01, or (b) cross-checked against the live
> `facebook/facebook-python-business-sdk` GitHub source (`main` branch, fetched 2026-07-01, pinned
> to `API_VERSION: 'v25.0'`, `SDK_VERSION: 'v25.0.2'`). Anything not confirmed by one of those two
> sources is explicitly tagged **(unverified)**.
>
> Companion files in this `kb/`: `graph-api.md` (Business Manager, System Users, Pages, Webhooks),
> `conversions-api.md` (server-side Conversions API), `commerce-catalog.md` (Commerce/Catalog API).
> This file is self-contained for Marketing API ad-object work — it does not assume the reader has
> read the others.

---

## Status & Versions

| Version | Release Date | Marketing API Expiration | Source |
|---------|--------------|---------------------------|--------|
| v25.0 | 2026-02-18 | **TBD** (not yet announced) | changelog/versions |
| v24.0 | 2025-10-08 | 2026-10-06 | changelog/versions |
| v23.0 | 2025-05-29 | 2026-06-09 | changelog/versions |
| v22.0 | 2025-01-21 | 2026-02-19 | changelog/versions |
| v21.0 | 2024-10-02 | 2025-09-09 | changelog/versions |

**Current version as of 2026-07-01: `v25.0`.** No newer version (v26.0 or later) has shipped yet.
Meta's own Feb 18, 2026 announcement blog post states v26.0 is expected **September 2026**
(that post is a forward-looking statement, not a release — confirmed not yet released as of this
KB's fetch date). `v25.0`'s own expiration/sunset date is listed as **`TBD`** on the official
versions table — Meta has not yet published a fixed sunset date for it, so `sunset_date` for the
purposes of this KB is **null/unknown**, not a specific date. Based on the pattern above (each
version's Marketing-API-specific sunset is roughly 13 months after its own release, distinctly
shorter than the Graph-API-core "2 years after next version" policy), a rough **unverified**
estimate would put v25.0's sunset around **March 2027**, but treat that as a guess, not a fact.

**Cross-check:** `facebook-python-business-sdk` (`facebook_business/apiconfig.py`, `main` branch,
fetched 2026-07-01):
```python
ads_api_config = {
  'API_VERSION': 'v25.0',
  'SDK_VERSION': 'v25.0.2',
  'STRICT_MODE': False
}
```
This independently corroborates v25.0 as current — the official Python SDK's `main` branch (which
tracks Meta's own codegen and is updated on every version bump) is pinned to it.

**Version-support policy (Graph API core, from the official versioning guide):** each version
"remains operational for at least 2 years from release"; "a version will no longer be usable two
years after the date that the subsequent version is released." **Marketing API has its own,
shorter, version-specific expiration schedule** (see table above) that does not follow the 2-year
Graph-API-core rule — always check the versions table for the Marketing-API-specific expiration
date, not the generic Graph API policy.

**v25.0 key changes (from the official Feb 18, 2026 announcement blog):**
- `metadata=1` query parameter deprecated in v25.0, to be fully removed by May 2026.
- **Breaking:** Creation, duplication, and updates to Advantage+ Shopping Campaigns (ASC) and
  Advantage+ App Campaigns (AAC) are **no longer allowed starting v25.0**; this restriction applies
  to all versions by May 19, 2026. Remaining ASC/AAC campaigns will be force-paused by v26.0
  (Sept 2026).
- `smart_promotion_type` is no longer available for creating new ad campaigns from v25.0 onward
  (still readable on existing campaigns).
- Ads Insights Asynchronous API responses now include richer default error fields on failed report
  jobs: `error_code` (changed from `uint` to `int`), `error_message`, `error_subcode`,
  `error_user_title`, `error_user_msg`.
- Webhooks mTLS: Meta signs webhook certs with its own CA starting March 31, 2026
  (`meta-outbound-api-ca-2025-12.pem`) — DigiCert Client-Auth EKU deprecation. Not directly relevant
  to ad-object CRUD but affects any webhook-subscribed integration in the same app.
- Page/Post reach, video-impression, and story-impression metrics deprecated June 2026 in favor of
  "Media Views"/"Media Viewers" — affects organic Page insights, not ad-object fields covered here.

**Sources:**
- https://developers.facebook.com/docs/graph-api/changelog/versions/ (versions table, fetched 2026-07-01 via r.jina.ai reader)
- https://developers.facebook.com/docs/graph-api/guides/versioning/ (2-year policy language, fetched 2026-07-01)
- https://developers.facebook.com/blog/post/2026/02/18/introducing-graph-api-v25-and-marketing-api-v25/ (v25.0 announcement, fetched 2026-07-01)
- `facebook_business/apiconfig.py` — https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/main/facebook_business/apiconfig.py (fetched 2026-07-01)

---

## Base URL

```
https://graph.facebook.com/{API_VERSION}/act_{AD_ACCOUNT_ID}/{edge}
https://graph.facebook.com/{API_VERSION}/{NODE_ID}
```

- Ad-account-scoped operations (create campaign/adset/ad/creative/audience) go under
  `act_{AD_ACCOUNT_ID}` — **the `act_` prefix is required**, e.g. `act_123456789`, not the bare
  numeric ID.
- Node-scoped operations (read/update/delete a specific object) address the object's own numeric
  `id` directly: `graph.facebook.com/v25.0/120210000000000`.
- Unversioned calls (`graph.facebook.com/{edge}`, no version segment) use whatever default version
  is configured on the calling app in the App Dashboard — **always send an explicit version** in
  production integrations to avoid silent behavior changes when Meta rotates the app's default.

Source: https://developers.facebook.com/docs/graph-api/guides/versioning/ (fetched 2026-07-01);
https://developers.facebook.com/docs/marketing-api/get-started (fetched 2026-07-01, via r.jina.ai
reader); ad-account-id `act_` prefix confirmed via WebSearch synthesis of Meta docs + Postman API
Network mirror (fetched 2026-07-01).

---

## Auth / OAuth Scopes & Access Tiers

### Required permissions (scopes)

| Scope | Purpose |
|-------|---------|
| `ads_management` | Create/update/delete campaigns, ad sets, ads, creatives, audiences |
| `ads_read` | Read-only access to campaign/ad-set/ad/insights data |
| `business_management` | Manage Business Manager-level resources (accounts, assets, system users) |

`ads_management` and `business_management` require **Meta App Review** before use with any ad
account outside the developer's own Business Manager (i.e. before going live for a client account).
(unverified detail: exact review-item names change over time — verify current review requirements
in the App Dashboard before launch.)

### Access token types

| Token type | Use case |
|------------|----------|
| User access token | Interactive/manual use, short-lived unless extended |
| System User access token | Server-to-server automation; can be issued with **no expiration** — the standard choice for a CLI/cron integration like `mads-cli` |

### Required request auth

Every call must include a valid token, either as:
- `Authorization: Bearer {access_token}` header, or
- `access_token={access_token}` query/body parameter

Source: https://developers.facebook.com/docs/marketing-api/get-started (fetched 2026-07-01);
WebSearch synthesis of official docs + Postman API Network + Stitchflow integration guide
(fetched 2026-07-01, cross-referenced for `act_` prefix and scope names).

### Access tiers — Standard vs. Development

Marketing API rate limits depend on which **access tier** the calling app is in. The tier is
determined by the app's **Ads Management Standard Access** feature status (renamed **"Marketing
API Access Tier"** as of May 2026):

| Tier | How obtained |
|------|-------------|
| Development tier | Default — app has only Standard Access to the Ads Management Standard Access / Marketing API Access Tier feature |
| Standard tier | App has **Advanced Access** to that same feature, granted via App Review |

As of the May 2026 update, the minimum historical usage bar to qualify for Advanced Access was
lowered from 1,500 to **500 Marketing API calls in the past 15 days**.

Source: https://developers.facebook.com/docs/marketing-api/overview/rate-limiting/ (fetched
2026-07-01, content retrieved via WebSearch synthesis — direct page fetch returned only navigation,
see Error Reference section note below); https://developers.meta.com/blog/updates-to-ads-management-standard-access-feature/ (fetched 2026-07-01).

---

## Endpoint Reference

Quick index:

| # | Endpoint | Purpose |
|---|----------|---------|
| 1 | `POST /act_{ad_account_id}/campaigns` | Create Campaign |
| 2 | `POST /act_{ad_account_id}/adsets` | Create Ad Set |
| 3 | `POST /act_{ad_account_id}/adcreatives` | Create Ad Creative |
| 4 | `POST /act_{ad_account_id}/ads` | Create Ad |
| 5 | `GET /{node_id}?fields=...` | Read any node's fields |
| 6 | `POST /{node_id}` | Update any node (partial — send only changed fields) |
| 7 | `POST /{node_id}` with no fields (or `DELETE`) | Remove/delete a node |
| 8 | `POST /act_{ad_account_id}/customaudiences` | Create Custom Audience |
| 9 | `POST /{custom_audience_id}/users` | Add hashed PII to a Custom Audience |
| 10 | `POST /act_{ad_account_id}/customaudiences` (subtype=`LOOKALIKE`) | Create Lookalike Audience |
| 11 | `POST /{business_id}/ad_studies` | Create Ad Study (A/B / split test) |
| 12 | `POST /?batch=[...]` | Batch Requests (max 50 per call) |
| 13 | `GET /act_{ad_account_id}/insights` | Ads Insights (sync); async variant via `/insights` job pattern |

---

### 1. `POST /act_{ad_account_id}/campaigns` — Create Campaign

**Required parameters:**

| Field | Type | Notes |
|-------|------|-------|
| `name` | UTF-8 string | Campaign name, emoji supported |
| `objective` | enum | See Objective enum below |
| `special_ad_categories` | array\<enum\> | **Required for every campaign, even if not applicable** — send `["NONE"]` or `[]` if not a regulated category. See Special Ad Categories below |

```http
POST https://graph.facebook.com/v25.0/act_123456789/campaigns
Content-Type: application/json
Authorization: Bearer {access_token}

{
  "name": "Talas Tesla Parts - Prospecting - QZ3",
  "objective": "OUTCOME_SALES",
  "status": "PAUSED",
  "special_ad_categories": [],
  "buying_type": "AUCTION"
}
```

**Response:**
```json
{ "id": "120210000000001" }
```

Notes:
- `status` at creation may only be `ACTIVE` or `PAUSED`.
- `spend_cap` minimum is $100 (account-currency equivalent); set to `922337203685478` to remove a
  previously-set cap.
- `daily_budget` and `lifetime_budget` are mutually exclusive at the Campaign level (Campaign
  Budget Optimization / CBO). If neither is set, budgets are managed per-AdSet instead (see DG-2).

Source: https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/ (fetched
2026-07-01 via r.jina.ai reader); cross-checked against `facebook_business/adobjects/campaign.py`
(fetched 2026-07-01).

---

### 2. `POST /act_{ad_account_id}/adsets` — Create Ad Set

**Required parameters:**

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Ad set name |
| `campaign_id` | numeric string | Parent campaign |
| `billing_event` | enum | What you're charged for |
| `optimization_goal` | enum | What delivery optimizes toward |
| `bid_amount` or `bid_strategy` | int / enum | Required unless campaign uses CBO with an auto strategy |
| `targeting` | Targeting object | See Targeting Reference below |
| `status` | enum | `ACTIVE` or `PAUSED` |
| `daily_budget` or `lifetime_budget` | numeric string | Required if Campaign has no CBO budget set |

```http
POST https://graph.facebook.com/v25.0/act_123456789/adsets
Content-Type: application/json
Authorization: Bearer {access_token}

{
  "name": "IND4 - Tesla+Korean - Prospecting",
  "campaign_id": "120210000000001",
  "daily_budget": "10000",
  "billing_event": "IMPRESSIONS",
  "optimization_goal": "OFFSITE_CONVERSIONS",
  "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
  "targeting": {
    "geo_locations": { "countries": ["AE"] },
    "age_min": 18,
    "age_max": 65,
    "publisher_platforms": ["facebook", "instagram"]
  },
  "status": "PAUSED",
  "promoted_object": { "pixel_id": "987654321", "custom_event_type": "PURCHASE" }
}
```

**Response:**
```json
{ "id": "120210000000002" }
```

Notes:
- `daily_budget`/`lifetime_budget` are in the **smallest currency unit** for most currencies but
  whole units for zero-decimal currencies (e.g. AED has 2 decimals → value is in fils-equivalent
  smallest unit per Meta's currency table) — **(unverified: exact AED minor-unit convention was not
  re-confirmed from a docs page in this session; verify empirically with a small test budget before
  relying on this for money-moving code)**.
- Regular ad accounts: max **5,000** non-deleted ad sets; bulk ad accounts: max **10,000**. Max
  **50** non-archived ads per ad set.

Source: https://developers.facebook.com/docs/marketing-api/reference/ad-campaign/ (fetched
2026-07-01 via r.jina.ai reader — this legacy-named URL is the **Ad Set** reference page, not
Campaign; Meta's REST naming is `ad-campaign-group` = Campaign, `ad-campaign` = AdSet,
`adgroup` = Ad); cross-checked against `facebook_business/adobjects/adset.py` (fetched 2026-07-01).

---

### 3. `POST /act_{ad_account_id}/adcreatives` — Create Ad Creative

**Common pattern — link ad via `object_story_spec`:**

```http
POST https://graph.facebook.com/v25.0/act_123456789/adcreatives
Content-Type: application/json
Authorization: Bearer {access_token}

{
  "name": "IND4 Tesla Parts - Creative A",
  "object_story_spec": {
    "page_id": "111222333444",
    "link_data": {
      "link": "https://shop.talas.ae/?branch=ind4",
      "message": "Genuine, used & aftermarket Tesla parts in the UAE.",
      "image_hash": "abc123def456...",
      "call_to_action": { "type": "SHOP_NOW", "value": { "link": "https://shop.talas.ae/?branch=ind4" } }
    }
  }
}
```

**Response:**
```json
{ "id": "120210000000003" }
```

See the full AdCreative field table and `object_story_spec`/`link_data`/`asset_feed_spec`
sub-structures in **Developer Guide DG-4** below.

Source: `facebook_business/adobjects/adcreative.py`,
`adcreativeobjectstoryspec.py`, `adcreativelinkdata.py` (all fetched 2026-07-01 from
`facebook/facebook-python-business-sdk` `main` branch — the live `developers.facebook.com/docs/marketing-api/reference/ad-creative/` page
consistently returned only sidebar/navigation content through the fetch tooling available in this
session, likely because its Fields table is virtualized/lazy-rendered; the SDK source is the
authoritative cross-check per this task's instructions and is *more current* than any cached doc
snapshot since it tracks Meta's own codegen on `main`).

---

### 4. `POST /act_{ad_account_id}/ads` — Create Ad

**Required parameters:**

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Ad name |
| `adset_id` | numeric string (int64) | Parent ad set (or `adset_spec` inline) |
| `creative` | object | `{"creative_id": "..."}` reference to an existing AdCreative |
| `status` | enum | `ACTIVE` or `PAUSED` |

```http
POST https://graph.facebook.com/v25.0/act_123456789/ads
Content-Type: application/json
Authorization: Bearer {access_token}

{
  "name": "IND4 - Prospecting - Ad 1",
  "adset_id": "120210000000002",
  "creative": { "creative_id": "120210000000003" },
  "status": "PAUSED"
}
```

**Response:**
```json
{ "id": "120210000000004" }
```

Source: https://developers.facebook.com/docs/marketing-api/reference/adgroup/ (fetched 2026-07-01
via r.jina.ai reader — legacy REST name `adgroup` = Ad); cross-checked against
`facebook_business/adobjects/ad.py` (fetched 2026-07-01).

---

### 5. `GET /{node_id}?fields=...` — Read Fields

```http
GET https://graph.facebook.com/v25.0/120210000000001?fields=name,objective,status,effective_status,daily_budget
Authorization: Bearer {access_token}
```

```json
{
  "name": "Talas Tesla Parts - Prospecting - QZ3",
  "objective": "OUTCOME_SALES",
  "status": "PAUSED",
  "effective_status": "PAUSED",
  "daily_budget": "10000",
  "id": "120210000000001"
}
```

`fields` is comma-separated; nested objects/edges can be requested with `{}` sub-selection syntax,
e.g. `adsets{name,status}`.

---

### 6. `POST /{node_id}` — Update (partial)

Only send the fields being changed — there is **no separate `updateMask` parameter** the way
Google Ads REST requires; Meta's Graph API treats any field present in the POST body as the new
value for that field, and omitted fields are left untouched.

```http
POST https://graph.facebook.com/v25.0/120210000000001
Content-Type: application/json
Authorization: Bearer {access_token}

{ "status": "ACTIVE" }
```

```json
{ "success": true }
```

---

### 7. Remove / Delete a node

Most ad objects are **soft-deleted** via status update rather than a hard `DELETE`:

```http
POST https://graph.facebook.com/v25.0/120210000000001
Content-Type: application/json
Authorization: Bearer {access_token}

{ "status": "DELETED" }
```

A true `DELETE` HTTP verb is also accepted on many nodes (e.g. AdCreative) and is codegen'd in the
SDK as `api_delete()` — confirmed present on `AdCreative` in `adcreative.py` (fetched 2026-07-01).

---

### 8. `POST /act_{ad_account_id}/customaudiences` — Create Custom Audience

```http
POST https://graph.facebook.com/v25.0/act_123456789/customaudiences
Content-Type: application/json
Authorization: Bearer {access_token}

{
  "name": "Talas Website Visitors - 180d",
  "subtype": "CUSTOM",
  "customer_file_source": "USER_PROVIDED_ONLY",
  "description": "Website visitors, 180-day window"
}
```

```json
{ "id": "23850000000000001" }
```

Full field/subtype/hashing reference: see **Custom Audiences** section and **DG-6** below.

---

### 9. `POST /{custom_audience_id}/users` — Add Hashed PII

```http
POST https://graph.facebook.com/v25.0/23850000000000001/users
Content-Type: application/json
Authorization: Bearer {access_token}

{
  "schema": ["EMAIL", "FN", "LN"],
  "data": [
    ["<sha256-hash-of-email>", "<sha256-hash-of-first-name>", "<sha256-hash-of-last-name>"]
  ],
  "session": { "session_id": 1, "batch_seq": 1, "last_batch_flag": true, "estimated_num_total": 1 }
}
```

Up to **10,000 records per request**; larger uploads use a shared `session_id` with incrementing
`batch_seq`, `last_batch_flag: true` on the final batch. Full hashing rules in DG-6.

Source: https://developers.facebook.com/docs/marketing-api/audiences/guides/custom-audiences/
(fetched 2026-07-01 via r.jina.ai reader).

---

### 10. `POST /act_{ad_account_id}/customaudiences` — Create Lookalike Audience

```http
POST https://graph.facebook.com/v25.0/act_123456789/customaudiences
Content-Type: application/json
Authorization: Bearer {access_token}

{
  "name": "Talas LAL 1% - UAE - Website Visitors",
  "subtype": "LOOKALIKE",
  "origin_audience_id": "23850000000000001",
  "lookalike_spec": { "type": "similarity", "ratio": 0.01, "country": "AE" }
}
```

```json
{ "id": "23850000000000002" }
```

Full reference in **Lookalike Audiences** section and **DG-7** below.

Source: https://developers.facebook.com/docs/marketing-api/audiences/guides/lookalike-audiences/
(fetched 2026-07-01 via r.jina.ai reader).

---

### 11. `POST /{business_id}/ad_studies` — Create Ad Study (Split Test)

```http
POST https://graph.facebook.com/v25.0/{business_id}/ad_studies
Content-Type: application/json
Authorization: Bearer {access_token}

{
  "name": "QZ3 Search vs PMax - Q3 2026",
  "description": "Compare Search-only vs PMax-only delivery for Tesla parts prospecting",
  "type": "SPLIT_TEST",
  "start_time": 1751328000,
  "end_time": 1752537600,
  "cells": [
    { "name": "Search", "treatment_percentage": 50, "adsets": ["120210000000002"] },
    { "name": "PMax-equivalent", "treatment_percentage": 50, "adsets": ["120210000000005"] }
  ]
}
```

```json
{ "id": "1234567890" }
```

Full reference in **Ad Studies** section and **DG-8** below.

Source: https://developers.facebook.com/docs/marketing-api/guides/split-testing/v2.8 (fetched
2026-07-01 via r.jina.ai reader — content is a legacy v2.8-tagged doc snapshot; the underlying
`ad_studies` resource and cell/percentage mechanics are the same long-stable mechanism used by
current Ads Manager split testing, cross-checked structurally against `facebook_business/adobjects/adstudy.py`
and `adstudycell.py`, fetched 2026-07-01, both current on `main`).

---

### 12. `POST /?batch=[...]` — Batch Requests

See **Batch API** section below — full reference, **50-request hard limit**.

---

### 13. `GET /act_{ad_account_id}/insights` — Ads Insights

```http
GET https://graph.facebook.com/v25.0/act_123456789/insights?fields=campaign_name,spend,impressions,clicks,actions&date_preset=last_7d&level=campaign
Authorization: Bearer {access_token}
```

Large/complex insights pulls should use the **async** variant (`POST .../insights` to start a
report job, then poll `GET /{report_run_id}` until `async_status: "Job Completed"`, then
`GET /{report_run_id}/insights` for the data) rather than the synchronous `GET`, which can time out
on large date ranges. As of v25.0, failed async report jobs return richer error fields
(`error_code`, `error_message`, `error_subcode`, `error_user_title`, `error_user_msg`) — see Status
& Versions above.

Source: v25.0 announcement blog (fetched 2026-07-01); general async-insights pattern is
**(unverified in this session)** beyond the v25.0 error-field change — the dedicated Insights KB
detail is out of scope for this Campaign/AdSet/Ad/AdCreative-focused file; treat this subsection as
a pointer, not a full Insights reference.

---

## Field Reference — Campaign

Resource name in REST docs: `ad-campaign-group`. Resource name in the Python SDK: `Campaign`
(`facebook_business/adobjects/campaign.py` — the SDK's `adcampaigngroup.py` is a deprecated 2KB
alias shim, confirmed by direct comparison of file sizes/contents, fetched 2026-07-01).

| Field | Type | Description |
|-------|------|-------------|
| `id` | numeric string | Campaign's ID |
| `account_id` | numeric string | ID of the ad account that owns this campaign |
| `adlabels` | list\<AdLabel\> | Ad Labels associated with this campaign |
| `advantage_state_info` | object | Advantage+ automation state info |
| `bid_strategy` | enum | Strategy for campaign budget optimization — see Enums |
| `boosted_object_id` | numeric string | The Boosted Object this campaign is associated with, if any |
| `brand_lift_studies` | list\<AdStudy\> | Automated Brand Lift v2 studies for this campaign |
| `budget_rebalance_flag` | bool | Whether to automatically rebalance budgets daily (CBO) |
| `budget_remaining` | numeric string | Remaining budget |
| `budget_schedule_specs` | list\<JSON\> | Scheduled high-demand budget periods (`time_start`, `time_end`, `budget_value`, `budget_value_type`) |
| `buying_type` | string | `AUCTION` or `RESERVED` (default `AUCTION`) |
| `campaign_group_active_time` | numeric string | Active running duration |
| `can_create_brand_lift_study` | bool | Whether a new automated brand lift study can be created |
| `can_use_spend_cap` | bool | Whether the campaign can set a spend cap |
| `configured_status` | enum | User-set status: `ACTIVE`, `PAUSED`, `DELETED`, `ARCHIVED` |
| `created_time` | datetime | Creation time |
| `daily_budget` | numeric string | Daily budget (mutually exclusive with `lifetime_budget`) |
| `effective_status` | enum | `ACTIVE`, `PAUSED`, `DELETED`, `ARCHIVED`, `IN_PROCESS`, `WITH_ISSUES` |
| `frequency_control_specs` | list | Frequency-control specs |
| `has_secondary_skadnetwork_reporting` | bool | Secondary SKAdNetwork reporting availability |
| `is_adset_budget_sharing_enabled` | bool | Whether child ad sets share budget (up to 20%) |
| `is_budget_schedule_enabled` | bool | Whether budget scheduling is enabled |
| `is_direct_send_campaign` | bool | Direct-send campaign flag |
| `is_message_campaign` | bool | Messaging campaign flag |
| `is_meta_moment_maker_enabled` | bool | Meta Moment Maker enablement |
| `is_reels_trending_ads_enabled` | bool | Reels trending ads enablement |
| `is_skadnetwork_attribution` | bool | iOS 14+ SKAdNetwork attribution flag |
| `issues_info` | list\<AdCampaignIssuesInfo\> | Issues preventing delivery |
| `last_budget_toggling_time` | datetime | Last budget toggling time |
| `lifetime_budget` | numeric string | Lifetime budget (mutually exclusive with `daily_budget`) |
| `name` | string | Campaign's name |
| `objective` | enum (string) | Campaign's objective — see Enums |
| `pacing_type` | list\<string\> | Pacing type (e.g. `standard`) |
| `primary_attribution` | enum | Primary attribution window spec |
| `promoted_object` | AdPromotedObject | The object this campaign promotes across its ads |
| `recommendations` | list\<AdRecommendation\> | System recommendations |
| `smart_promotion_type` | enum | `GUIDED_CREATION`, `SMART_APP_PROMOTION` — **cannot be set on create as of v25.0** |
| `source_campaign` / `source_campaign_id` | Campaign / numeric string | Source campaign if copied |
| `source_recommendation_type` | string | Source recommendation type |
| `special_ad_categories` | list\<enum\> | Regulated category classification — **required on create** |
| `special_ad_category` | enum | **Deprecated** (since v7.0) — use `special_ad_categories` |
| `special_ad_category_country` | list\<enum\> | Country scoping for Special Ad Category |
| `spend_cap` | numeric string | Max spend; min $100-equivalent; `922337203685478` removes it |
| `start_time` / `stop_time` | datetime | Merged start/stop of child ad sets (read-only) |
| `status` | enum | `ACTIVE`, `PAUSED`, `DELETED`, `ARCHIVED` |
| `topline_id` | numeric string | Topline ID |
| `updated_time` | datetime | Last update time |

**Create-only extra parameters:** `execution_options` (`validate_only`, `include_recommendations`),
`campaign_optimization_type` (`NONE`, `ICO_ONLY`), `is_skadnetwork_attribution`,
`is_using_l3_schedule`, `iterative_split_test_configs`, `source_campaign_id`.

**Update-only extra parameters:** `adset_bid_amounts`, `adset_budgets`, `budget_rebalance_flag`,
`is_adset_budget_sharing_enabled`, `is_reels_trending_ads_enabled`.

**Edges:** `ad_studies`, `adrules_governed`, `ads`, `adsets`, `copies`.

**Limits:** max **200 ad sets per campaign**.

Sources: https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/ (fetched
2026-07-01); `facebook_business/adobjects/campaign.py` (fetched 2026-07-01) — field list on this
table matches the SDK's `Field` class exactly, with SDK also confirming (and adding, vs. the doc
snapshot) `advantage_state_info`, `is_direct_send_campaign`, `is_message_campaign`,
`is_meta_moment_maker_enabled`, `source_recommendation_type`, `recommendations`.

---

## Field Reference — Ad Set

Resource name in REST docs: `ad-campaign` (legacy/confusing name — this is **not** the Campaign
object). Resource name in SDK: `AdSet` (`facebook_business/adobjects/adset.py`; `adcampaign.py` is
the deprecated 2KB alias shim).

| Field | Type | Description |
|-------|------|-------------|
| `id` | numeric string | Ad Set ID |
| `account_id` | numeric string | Owning ad account |
| `adlabels` | list\<AdLabel\> | Ad Labels |
| `adset_schedule` | list\<DayPart\> | Day-parting delivery schedule |
| `asset_feed_id` | numeric string | Asset feed ID (Dynamic Creative / Advantage+ creative) |
| `attribution_spec` | list\<AttributionSpec\> | Conversion attribution spec used for optimization |
| `automatic_manual_state` | enum | `AUTOMATIC`, `MANUAL`, `UNSET` |
| `bid_adjustments` | AdBidAdjustments | Map of bid adjustment types to values |
| `bid_amount` | unsigned int32 | Bid cap / target cost |
| `bid_constraints` | AdCampaignBidConstraint | Bid constraint choices |
| `bid_info` | map\<string, uint32\> | Map of bid objective to bid value |
| `bid_strategy` | enum | See Enums |
| `billing_event` | enum | See Enums |
| `brand_safety_config` | BrandSafetyCampaignConfig | Brand safety configuration |
| `budget_remaining` | numeric string | Remaining budget |
| `campaign` / `campaign_id` | Campaign / numeric string | Parent campaign |
| `campaign_active_time` | numeric string | Campaign running length |
| `campaign_attribution` | enum | e.g. SKAN or AEM |
| `configured_status` | enum | User-set status |
| `cost_bidding_mode` | enum | `BALANCED`, `COST_FOCUSED`, `VOLUME_FOCUSED` |
| `created_time` | datetime | Creation time |
| `creative_sequence` | list\<numeric string\> | Order of ad rotation shown to users |
| `daily_budget` / `lifetime_budget` | numeric string | Mutually exclusive |
| `daily_min_spend_target` / `daily_spend_cap` | numeric string | Daily spend floor/ceiling |
| `destination_type` | string (enum) | See Enums |
| `dsa_beneficiary` / `dsa_payor` | string | EU Digital Services Act disclosure fields |
| `effective_status` | enum | See Enums |
| `end_time` / `start_time` | datetime | UTC UNIX timestamp |
| `frequency_control_specs` | list | Frequency-control specs |
| `instagram_user_id` | numeric string | Instagram account used for ads |
| `is_dynamic_creative` | bool | Dynamic Creative ad set flag |
| `is_incremental_attribution_enabled` | bool | Incremental attribution optimization |
| `issues_info` | list\<AdCampaignIssuesInfo\> | Delivery-blocking issues |
| `learning_stage_info` | AdCampaignLearningStageInfo | Ranking/delivery learning status |
| `lifetime_imps` | int32 | Lifetime impressions (FIXED_CPM only) |
| `min_budget_spend_percentage` / `max_budget_spend_percentage` | numeric string | Budget-share bounds under CBO |
| `multi_optimization_goal_weight` | enum | See Enums |
| `name` | string | Ad set name |
| `optimization_goal` | enum | See Enums |
| `optimization_sub_event` | enum | See Enums |
| `pacing_type` | list\<string\> | `standard` or ad-scheduling pacing |
| `promoted_object` | AdPromotedObject | The object this ad set promotes |
| `recommendations` | list\<AdRecommendation\> | System recommendations |
| `recurring_budget_semantics` | bool | Whether daily spend may exceed daily budget within weekly bounds |
| `regional_regulated_categories` | list\<enum\> | See Enums |
| `regional_regulation_identities` | RegionalRegulationIdentities | Regional regulation identity info |
| `review_feedback` | string | Dynamic creative ad review notes |
| `rf_prediction_id` | id | Reach & frequency prediction ID |
| `source_adset` / `source_adset_id` | AdSet / numeric string | Copy source |
| `start_time` / `status` | datetime / enum | See Enums |
| `targeting` | Targeting | See Targeting Reference |
| `targeting_optimization_types` | list\<KeyValue\<string,int32\>\> | Relaxed targeting used as optimization signals |
| `time_based_ad_rotation_id_blocks` / `_intervals` | list | Custom date-range ad rotation |
| `updated_time` | datetime | Last update |
| `use_new_app_click` | bool | Lets Mobile App Engagement ads optimize for `LINK_CLICKS` |
| `value_rule_set_id` | numeric string | Value Rule Set ID |

**Create/update-only extra parameters (SDK-confirmed, not all in the doc snapshot):**
`budget_schedule_specs`, `budget_source`, `budget_split_set_id`, `campaign_spec`, `date_format`,
`execution_options`, `is_sac_cfca_terms_certified`, `line_number`, `rb_prediction_id`,
`time_start`/`time_stop`, `topline_id`, `tune_for_category`.

**Edges:** `activities`, `ad_studies`, `adcreatives`, `adrules_governed`, `ads`, `asyncadrequests`,
`copies`, `delivery_estimate`, `message_delivery_estimate`, `targetingsentencelines`.

**Limits:** regular ad account max **5,000** non-deleted ad sets; bulk ad account max **10,000**;
max **50** non-archived ads per ad set.

Sources: https://developers.facebook.com/docs/marketing-api/reference/ad-campaign/ (fetched
2026-07-01); `facebook_business/adobjects/adset.py` (fetched 2026-07-01) — SDK field list is
noticeably larger/more current than the doc snapshot (adds e.g. `meta_moment_maker_spec`,
`trending_topics_spec`, `creative_diversity_label`, `creative_diversity_score`,
`is_organic_ad_joint_optimized`, `multi_event_conversion_attribution_window_seconds`,
`full_funnel_exploration_mode`, `existing_customer_budget_percentage`, `low_creative_reach`,
`is_ba_skip_delayed_eligible`, `is_dc_follow_optimized`, `live_video_ad_campaign_config`,
`placement_soft_opt_out`, `relative_value`, `value_rules_applied` — all confirmed field names via
SDK source but **not independently doc-confirmed with descriptions in this session; treat their
one-line descriptions above as best-effort (unverified) glosses of the field name, not verbatim doc
text**).

---

## Field Reference — Ad

Resource name in REST docs: `adgroup`. Resource name in SDK: `Ad` (`facebook_business/adobjects/ad.py`;
`adgroup.py` is the deprecated 2KB alias shim).

| Field | Type | Description |
|-------|------|-------------|
| `id` | numeric string | Ad ID |
| `account_id` | numeric string | Owning ad account |
| `ad_active_time` | numeric string | Time ad became active |
| `ad_review_feedback` | AdgroupReviewFeedback | Review feedback details |
| `ad_schedule_start_time` / `_end_time` | datetime | Ad scheduling window |
| `adlabels` | list\<AdLabel\> | Ad Labels |
| `adset` / `adset_id` | AdSet / numeric string | Parent ad set |
| `bid_amount` | int32 | Bid amount (largely superseded by ad-set-level bidding) |
| `bid_info` | map\<string, uint32\> | Bidding information |
| `bid_type` | enum | See Enums |
| `campaign` / `campaign_id` | Campaign / numeric string | Parent campaign |
| `configured_status` | enum | User-set status |
| `conversion_domain` | string | Domain used for conversion tracking |
| `conversion_specs` | list\<ConversionActionQuery\> | Conversion specifications |
| `created_time` | datetime | Creation time |
| `creative` | AdCreative | Associated creative |
| `creative_asset_groups_spec` | AdCreativeAssetGroupsSpec | Asset-group spec |
| `creative_automation_spec` | object | Creative automation configuration |
| `demolink_hash` | string | Demo link hash |
| `display_sequence` | int32 | Display order within the ad set |
| `effective_status` | enum | See Enums |
| `engagement_audience` | bool | Engagement-based audience flag |
| `failed_delivery_checks` | list\<DeliveryCheck\> | Failed validation checks |
| `issues_info` | list\<AdgroupIssuesInfo\> | Issues affecting the ad |
| `last_updated_by_app_id` | id | Last updating app |
| `name` | string | Ad name |
| `placement` | object | Placement info **(unverified: not present in the older doc snapshot; SDK-confirmed field name only)** |
| `preview_shareable_link` | string | Shareable preview URL |
| `priority` | unsigned int32 | Ad priority level |
| `recommendations` | list\<AdRecommendation\> | System recommendations |
| `source_ad` / `source_ad_id` | Ad / numeric string | Copy source |
| `special_ad_categories` | list\<enum\> | Regulated category classification |
| `status` | enum | `ACTIVE`, `PAUSED`, `DELETED`, `ARCHIVED` |
| `targeting` | Targeting | Ad-level targeting override (rare — usually set at AdSet level) |
| `tracking_and_conversion_with_defaults` | TrackingAndConversionWithDefaults | Tracking configuration |
| `tracking_specs` | list\<ConversionActionQuery\> | Tracking specs |
| `updated_time` | datetime | Last update |

**Create-only extra parameters:** `adset_spec` (inline ad-set definition instead of `adset_id`),
`audience_id`, `date_format`, `draft_adgroup_id`, `execution_options` (`validate_only`,
`include_recommendations`, `synchronous_ad_review`), `filename`, `include_demolink_hashes`.

**Required to create:** `name`, `adset_id` (or `adset_spec`), `creative` (object with
`creative_id`, or an inline creative spec).

**Edges:** `adcreatives`, `adrules_governed`, `copies`, `insights`, `leads`, `previews`,
`targetingsentencelines`.

Sources: https://developers.facebook.com/docs/marketing-api/reference/adgroup/ (fetched
2026-07-01); `facebook_business/adobjects/ad.py` (fetched 2026-07-01).

---

## Field Reference — Ad Creative

Resource name: `AdCreative` (`facebook_business/adobjects/adcreative.py`). **This section's field
list is sourced from the SDK, not the docs page** — `developers.facebook.com/docs/marketing-api/reference/ad-creative/`
consistently returned only sidebar navigation (an unrelated Ad Account edges list) through every
fetch attempt in this session, both via direct `WebFetch` and via the `r.jina.ai` reader proxy,
across the base URL, trailing-slash, and `/v25.0` variants — most likely because its Fields table
is virtualized/lazy-loaded client-side and the page is unusually large. The SDK source is treated
here as the authoritative cross-check per this task's explicit instructions, and is arguably *more*
current than any cached doc snapshot since Meta's own codegen regenerates it on every API bump
(confirmed fresh: contains 2026-era `CallToActionType` values like `shop_with_ai`, `try_on_with_ai`,
`sotto_subscribe`).

| Field | Type |
|-------|------|
| `id` | string |
| `account_id` | string |
| `actor_id` | string |
| `ad_disclaimer_spec` | AdCreativeAdDisclaimer |
| `adlabels` | list\<AdLabel\> |
| `applink_treatment` | string (enum — see `ApplinkTreatment` below) |
| `asset_feed_spec` | AdAssetFeedSpec |
| `authorization_category` | string (enum — see `AuthorizationCategory` below) |
| `auto_update` | bool |
| `body` | string — primary ad text/body copy |
| `branded_content` | AdCreativeBrandedContentAds |
| `branded_content_sponsor_page_id` | string |
| `bundle_folder_id` | string |
| `call_to_action` | AdCreativeLinkDataCallToAction |
| `call_to_action_type` | CallToActionType enum — see below |
| `categorization_criteria` | string |
| `category_media_source` | string |
| `collaborative_ads_lsb_image_bank_id` | string |
| `contextual_multi_ads` | AdCreativeContextualMultiAds |
| `creative_sourcing_spec` | AdCreativeSourcingSpec |
| `degrees_of_freedom_spec` | AdCreativeDegreesOfFreedomSpec |
| `destination_set_id` | string |
| `destination_spec` | AdCreativeDestinationSpec |
| `dynamic_ad_voice` | string (`DYNAMIC`, `STORY_OWNER`) |
| `effective_authorization_category` | string |
| `effective_instagram_media_id` | string |
| `effective_object_story_id` | string |
| `enable_direct_install` | bool |
| `enable_launch_instant_app` | bool |
| `existing_post_title` | string |
| `facebook_branded_content` | AdCreativeFacebookBrandedContent |
| `format_transformation_spec` | list\<AdCreativeFormatTransformationSpec\> |
| `generative_asset_spec` | AdCreativeGenerativeAssetSpec |
| `image_crops` | AdsImageCrops |
| `image_hash` | string — hash of an uploaded image (from `/act_{id}/adimages`) |
| `image_url` | string — direct image URL (alternative to `image_hash`) |
| `instagram_branded_content` | AdCreativeInstagramBrandedContent |
| `instagram_permalink_url` | string |
| `instagram_user_id` | string |
| `interactive_components_spec` | AdCreativeInteractiveComponentsSpec |
| `link_deep_link_url` | string |
| `link_destination_display_url` | string |
| `link_og_id` | string |
| `link_url` | string |
| `marketing_message_structured_spec` | AdCreativeMarketingMessageStructuredSpec |
| `media_sourcing_spec` | AdCreativeMediaSourcingSpec |
| `messenger_sponsored_message` | string |
| `name` | string — creative name (internal label, not shown to users) |
| `object_id` | string |
| `object_store_url` | string |
| `object_story_id` | string — existing organic post ID to use as the ad ("dark post" alternative is `object_story_spec`) |
| `object_story_spec` | AdCreativeObjectStorySpec — see DG-4 |
| `object_type` | ObjectType enum — see below |
| `object_url` | string |
| `omnichannel_link_spec` | AdCreativeOmnichannelLinkSpec |
| `page_welcome_message` | string |
| `photo_album_source_object_story_id` | string |
| `place_page_set_id` | string |
| `platform_customizations` | AdCreativePlatformCustomization |
| `playable_asset_id` | string |
| `portrait_customizations` | AdCreativePortraitCustomizations |
| `product_data` | list\<AdCreativeProductData\> |
| `product_set_id` | string |
| `product_suggestion_settings` | AdCreativeProductSuggestionSettings |
| `recommender_settings` | AdCreativeRecommenderSettings |
| `regional_regulation_disclaimer_spec` | AdCreativeRegionalRegulationDisclaimer |
| `source_facebook_post_id` | string |
| `source_instagram_media_id` | string |
| `status` | Status enum — `ACTIVE`, `DELETED`, `IN_PROCESS`, `WITH_ISSUES` |
| `template_url` | string |
| `template_url_spec` | AdCreativeTemplateURLSpec |
| `thumbnail_id` | string |
| `thumbnail_url` | string |
| `title` | string — headline text |
| `url_tags` | string — query string appended to click-through URLs (UTM-style tracking) |
| `use_page_actor_override` | bool |
| `video_id` | string — uploaded video ID (from `/act_{id}/advideos`) |
| `wamo_whatsapp_identity_spec` | AdCreativeWAMOWhatsAppIdentitySpec |
| `execution_options` | list\<ExecutionOptions\> (`validate_only`) |
| `image_file` | string (create-only: raw upload path/handle) |
| `is_dco_internal` | bool |

### CallToActionType enum (full — 100+ values, confirmed via SDK `main` branch, fetched 2026-07-01)

`ADD_TO_CART`, `APPLY_NOW`, `ASK_ABOUT_SERVICES`, `ASK_A_QUESTION`, `ASK_FOR_MORE_INFO`, `ASK_US`,
`AUDIO_CALL`, `BOOK_A_CONSULTATION`, `BOOK_NOW`, `BOOK_TRAVEL`, `BROWSE_SHOP`, `BUY`, `BUY_NOW`,
`BUY_TICKETS`, `BUY_VIA_MESSAGE`, `CALL`, `CALL_ME`, `CALL_NOW`, `CHAT_NOW`, `CHAT_WITH_US`,
`CONFIRM`, `CONTACT`, `CONTACT_US`, `DONATE`, `DONATE_NOW`, `DOWNLOAD`, `EVENT_RSVP`,
`FIND_A_GROUP`, `FIND_OUT_MORE`, `FIND_YOUR_GROUPS`, `FOLLOW_NEWS_STORYLINE`, `FOLLOW_PAGE`,
`FOLLOW_USER`, `GET_A_QUOTE`, `GET_DETAILS`, `GET_DIRECTIONS`, `GET_IN_TOUCH`, `GET_OFFER`,
`GET_OFFER_VIEW`, `GET_PROMOTIONS`, `GET_QUOTE`, `GET_SHOWTIMES`, `GET_STARTED`, `INQUIRE_NOW`,
`INSTALL_APP`, `INSTALL_MOBILE_APP`, `JOIN_CHANNEL`, `JOIN_LIVE_VIDEO`, `LEARN_MORE`, `LIKE_PAGE`,
`LISTEN_MUSIC`, `LISTEN_NOW`, `MAKE_AN_APPOINTMENT`, `MESSAGE_PAGE`, `MOBILE_DOWNLOAD`,
`NO_BUTTON`, `OPEN_INSTANT_APP`, `OPEN_LINK`, `ORDER_NOW`, `PAY_TO_ACCESS`, `PLAY_GAME`,
`PLAY_GAME_ON_FACEBOOK`, `PURCHASE_GIFT_CARDS`, `RAISE_MONEY`, `RECORD_NOW`, `REFER_FRIENDS`,
`REQUEST_TIME`, `SAY_THANKS`, `SEE_MORE`, `SEE_SHOP`, `SELL_NOW`, `SEND_A_GIFT`,
`SEND_GIFT_MONEY`, `SEND_UPDATES`, `SHARE`, `SHOP_NOW`, `SHOP_WITH_AI`, `SIGN_UP`,
`SOTTO_SUBSCRIBE`, `START_A_CHAT`, `START_ORDER`, `SUBSCRIBE`, `SWIPE_UP_PRODUCT`,
`SWIPE_UP_SHOP`, `TRY_DEMO`, `TRY_ON_WITH_AI`, `UPDATE_APP`, `USE_APP`, `USE_MOBILE_APP`,
`VIDEO_ANNOTATION`, `VIDEO_CALL`, `VIEW_CART`, `VIEW_CHANNEL`, `VIEW_IN_CART`, `VIEW_PRODUCT`,
`VISIT_PAGES_FEED`, `VISIT_WEBSITE`, `WATCH_LIVE_VIDEO`, `WATCH_MORE`, `WATCH_VIDEO`,
`WHATSAPP_MESSAGE`, `WOODHENGE_SUPPORT`

### ObjectType enum
`APPLICATION`, `DOMAIN`, `EVENT`, `INVALID`, `OFFER`, `PAGE`, `PHOTO`, `POST_DELETED`,
`PRIVACY_CHECK_FAIL`, `SHARE`, `STATUS`, `STORE_ITEM`, `VIDEO`

### Status enum
`ACTIVE`, `DELETED`, `IN_PROCESS`, `WITH_ISSUES`

### ApplinkTreatment enum
`automatic`, `deeplink_with_appstore_fallback`, `deeplink_with_web_fallback`, `web_only`

### AuthorizationCategory enum
`NONE`, `POLITICAL`, `POLITICAL_WITH_DIGITALLY_CREATED_MEDIA`

**Edges:** `adcreatives` (self, for AdCreative→AdCreative relations), `creative_insights`,
`previews`.

Source: `facebook_business/adobjects/adcreative.py` (fetched 2026-07-01, full byte-for-byte field
and enum transcription).

---

## Enums Reference

### `objective` (Campaign)

Legacy objectives (pre-2022, still valid on read; **new campaigns should use the `OUTCOME_*`
set** — Meta has been steering all campaign creation toward `OUTCOME_*` since 2022, and some
legacy-objective creation paths are progressively restricted, e.g. Advantage+ Shopping/App
campaigns as of v25.0):

`APP_INSTALLS`, `BRAND_AWARENESS`, `CONVERSIONS`, `EVENT_RESPONSES`, `LEAD_GENERATION`,
`LINK_CLICKS`, `LOCAL_AWARENESS`, `MESSAGES`, `OFFER_CLAIMS`, `PAGE_LIKES`, `POST_ENGAGEMENT`,
`PRODUCT_CATALOG_SALES`, `REACH`, `STORE_VISITS`, `VIDEO_VIEWS`

Current (`OUTCOME_*`) objectives:

`OUTCOME_APP_PROMOTION`, `OUTCOME_AWARENESS`, `OUTCOME_ENGAGEMENT`, `OUTCOME_LEADS`,
`OUTCOME_SALES`, `OUTCOME_TRAFFIC`

Source: `facebook_business/adobjects/campaign.py` `class Objective` (fetched 2026-07-01) —
identical set confirmed on the doc page fetch.

### `optimization_goal` (AdSet)

`NONE`, `APP_INSTALLS`, `AD_RECALL_LIFT`, `ENGAGED_USERS`, `EVENT_RESPONSES`, `IMPRESSIONS`,
`LEAD_GENERATION`, `QUALITY_LEAD`, `LINK_CLICKS`, `OFFSITE_CONVERSIONS`, `PAGE_LIKES`,
`POST_ENGAGEMENT`, `QUALITY_CALL`, `REACH`, `LANDING_PAGE_VIEWS`, `VISIT_INSTAGRAM_PROFILE`,
`ENGAGED_PAGE_VIEWS`, `VALUE`, `THRUPLAY`, `DERIVED_EVENTS`,
`APP_INSTALLS_AND_OFFSITE_CONVERSIONS`, `CONVERSATIONS`, `IN_APP_VALUE`,
`MESSAGING_PURCHASE_CONVERSION`, `MESSAGING_DEEP_CONVERSATION_AND_FOLLOW`, `SUBSCRIBERS`,
`REMINDERS_SET`, `MEANINGFUL_CALL_ATTEMPT`, `PROFILE_VISIT`, `PROFILE_AND_PAGE_ENGAGEMENT`,
`ADVERTISER_SILOED_VALUE`, `AUTOMATIC_OBJECTIVE`, `MESSAGING_APPOINTMENT_CONVERSION`

Source: `facebook_business/adobjects/adset.py` `class OptimizationGoal` (fetched 2026-07-01); doc
page fetch produced the same set (minus the newest few, confirming SDK currency).

### `bid_strategy` (Campaign and AdSet — same 4 values at both levels)

| Value | Meaning (best-effort — see note) |
|-------|-----------------------------------|
| `LOWEST_COST_WITHOUT_CAP` | Spend the full budget to get the lowest average cost per result, no bid ceiling |
| `LOWEST_COST_WITH_BID_CAP` | Lowest cost per result, but never bid above `bid_amount` |
| `COST_CAP` | Try to hold average cost per result near a target `bid_amount` |
| `LOWEST_COST_WITH_MIN_ROAS` | Lowest cost while maintaining a minimum ROAS target |

**(unverified nuance):** the exact per-strategy requirement for `bid_amount` (which strategies
require it vs. treat it as optional/ignored) was not confirmed from a rendered docs page in this
session — the dedicated Bid Strategy doc page (`.../bidding/overview/bid-strategy`) returned only
navigation through every fetch attempt tried. The one-line meanings above are a standard,
widely-corroborated gloss (WebSearch synthesis across multiple sources), not a verbatim doc quote —
verify empirically (or via a rendered doc snapshot) before encoding hard validation rules on this
in `mads-cli`.

Source: `facebook_business/adobjects/campaign.py` + `adset.py` `class BidStrategy` (fetched
2026-07-01, enum values only); https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/
(fetched 2026-07-01, gave the one-line "Strategy for campaign budget optimization" gloss only).

### `billing_event` (AdSet)

`APP_INSTALLS`, `CLICKS`, `IMPRESSIONS`, `LINK_CLICKS`, `LISTING_INTERACTION`, `NONE`,
`OFFER_CLAIMS`, `PAGE_LIKES`, `POST_ENGAGEMENT`, `PURCHASE`, `THRUPLAY`

Source: `facebook_business/adobjects/adset.py` `class BillingEvent` (fetched 2026-07-01).

### Status enums by resource

| Resource | `status`/`configured_status` | `effective_status` |
|----------|------------------------------|----------------------|
| Campaign | `ACTIVE`, `PAUSED`, `DELETED`, `ARCHIVED` | `ACTIVE`, `PAUSED`, `DELETED`, `ARCHIVED`, `IN_PROCESS`, `WITH_ISSUES` |
| AdSet | `ACTIVE`, `PAUSED`, `DELETED`, `ARCHIVED` | `ACTIVE`, `PAUSED`, `CAMPAIGN_PAUSED`, `DELETED`, `ARCHIVED`, `IN_PROCESS`, `WITH_ISSUES` |
| Ad | `ACTIVE`, `PAUSED`, `DELETED`, `ARCHIVED` | `ACTIVE`, `ADSET_PAUSED`, `ARCHIVED`, `CAMPAIGN_PAUSED`, `DELETED`, `DISAPPROVED`, `IN_PROCESS`, `PAUSED`, `PENDING_BILLING_INFO`, `PENDING_REVIEW`, `PREAPPROVED`, `WITH_ISSUES` |
| AdCreative | `ACTIVE`, `DELETED`, `IN_PROCESS`, `WITH_ISSUES` | — (AdCreative has no `effective_status`) |

Source: `campaign.py`, `adset.py`, `ad.py`, `adcreative.py` `class Status`/`ConfiguredStatus`/`EffectiveStatus`
(all fetched 2026-07-01, exact per-file enums).

### `bid_type` (Ad — legacy, largely superseded by ad-set-level `bid_strategy`)

`CPC`, `CPM`, `MULTI_PREMIUM`, `ABSOLUTE_OCPM`, `CPA`

Source: `facebook_business/adobjects/ad.py` `class BidType` (fetched 2026-07-01).

### `destination_type` (AdSet)

`WEBSITE`, `APP`, `MESSENGER`, `APPLINKS_AUTOMATIC`, `WHATSAPP`, `INSTAGRAM_DIRECT`, `FACEBOOK`,
`MESSAGING_MESSENGER_WHATSAPP`, `MESSAGING_INSTAGRAM_DIRECT_MESSENGER`,
`MESSAGING_INSTAGRAM_DIRECT_MESSENGER_WHATSAPP`, `MESSAGING_INSTAGRAM_DIRECT_WHATSAPP`,
`SHOP_AUTOMATIC`, `ON_AD`, `ON_POST`, `ON_EVENT`, `ON_VIDEO`, `ON_PAGE`, `INSTAGRAM_PROFILE`,
`FACEBOOK_PAGE`, `INSTAGRAM_PROFILE_AND_FACEBOOK_PAGE`, `INSTAGRAM_LIVE`, `FACEBOOK_LIVE`,
`IMAGINE`

Source: cross-fetch of doc page + `adset.py` `class DestinationType` (both fetched 2026-07-01,
values matched).

### `special_ad_categories` (Campaign, Ad)

`NONE`, `EMPLOYMENT`, `HOUSING`, `CREDIT`, `ISSUES_ELECTIONS_POLITICS`,
`ONLINE_GAMBLING_AND_GAMING`, `FINANCIAL_PRODUCTS_SERVICES`

Every campaign and ad **must** declare this field (send `[]` or `["NONE"]` if not applicable) —
Meta requires all advertisers to self-classify regardless of business type.

Source: `facebook_business/adobjects/campaign.py` `class SpecialAdCategories` (fetched 2026-07-01);
confirmed required-on-create by doc page fetch of `ad-campaign-group` (fetched 2026-07-01).

### `regional_regulated_categories` (AdSet)

`TAIWAN_FINSERV`, `AUSTRALIA_FINSERV`, `INDIA_FINSERV`, `TAIWAN_UNIVERSAL`, `SINGAPORE_UNIVERSAL`,
`THAILAND_UNIVERSAL`, `BRAZIL_REGULATION`

Source: doc-page fetch of `ad-campaign` (AdSet reference), fetched 2026-07-01. **(unverified against
SDK: SDK's `adset.py` `class RegionalRegulatedCategories` instead lists numeric string values `'0'`
through `'19'` — the two sources disagree in representation, likely because the SDK enum is an
internal numeric-ID mapping while the doc page shows the human-readable category names. Do not
assume the numeric SDK values map 1:1 in order to the named list above without testing — flagged as
a genuine (unverified) discrepancy between the two sources.)**

---

## Targeting Reference

`Targeting` is an embedded object on `AdSet.targeting` (and, rarely, `Ad.targeting`). Full field
list confirmed via `facebook_business/adobjects/targeting.py` (fetched 2026-07-01) — over 90
fields; the most commonly used are below (full list is the SDK `Field` class, all field names
already 1:1 with what `mads-cli` should send).

### Core demographic / geo fields

| Field | Notes |
|-------|-------|
| `geo_locations` | Object — see sub-fields below. **Required** (or `custom_audiences` / `product_audience_specs` / `dynamic_audience_ids` in its place) |
| `excluded_geo_locations` | Same shape as `geo_locations`, for exclusions |
| `age_min` / `age_max` | Min 13 (defaults to 18 for most objectives); max 65 |
| `genders` | `1` = male, `2` = female; omit for all |
| `locales` | Language targeting |
| `custom_audiences` / `excluded_custom_audiences` | Array of Custom Audience IDs/objects; up to 500 excluded |

`geo_locations` sub-fields: `countries`, `regions` (max 200, `key`-based), `cities` (max 250, `key`
+ `radius` 10–50 mi / 17–80 km + `distance_unit`), `zips` (max 50,000), `places` (max 200, optional
radius), `custom_locations` (lat/lng or address + radius 0.63–50 mi / 1–80 km, max 200),
`geo_markets` (Comscore Markets, max 2,500), `electoral_district`, `country_groups`,
`location_types` (`home`, `recent` — defaults to both if omitted).

Source: https://developers.facebook.com/docs/marketing-api/audiences/reference/basic-targeting/
(fetched 2026-07-01 via r.jina.ai reader).

### Placement fields and their valid values

| Field | Valid values |
|-------|-------------|
| `publisher_platforms` | `facebook`, `instagram`, `threads`, `messenger`, `audience_network` |
| `facebook_positions` | `feed`, `right_hand_column`, `marketplace`, `video_feeds`, `story`, `search`, `instream_video`, `facebook_reels`, `facebook_reels_overlay`, `profile_feed`, `notification` |
| `instagram_positions` | `stream`, `story`, `explore`, `explore_home`, `reels`, `profile_feed`, `ig_search`, `profile_reels` |
| `messenger_positions` | `sponsored_messages`, `story` |
| `audience_network_positions` | `classic`, `rewarded_video` |
| `threads_positions` | `threads_stream` |
| `whatsapp_positions` | `status` |
| `device_platforms` | `mobile`, `desktop` |

`brand_safety_content_filter_levels` values are scoped by placement type: in-stream/Reels
(`FACEBOOK_RELAXED`/`FACEBOOK_STANDARD`/`FACEBOOK_STRICT`), Audience Network
(`AN_RELAXED`/`AN_STANDARD`/`AN_STRICT`), Feed (`FEED_RELAXED`/`FEED_STANDARD`/`FEED_STRICT`).
`excluded_publisher_categories` values: `dating`, `gambling`. Account-level filter settings cap how
restrictive campaign-level settings can be relaxed (a `MODERATE` account default cannot be loosened
to `EXPANDED` at the campaign level).

Source: https://developers.facebook.com/docs/marketing-api/audiences/reference/placement-targeting/
(fetched 2026-07-01 via r.jina.ai reader — full table transcribed verbatim).

### Flexible/detailed targeting (`flexible_spec`)

Detailed targeting (interests, behaviors, demographics, life events) is expressed as an array under
`targeting.flexible_spec`; each element of the array is **OR'd** internally and the array elements
themselves are **AND'd** together (i.e. group targeting options you want unioned into the same
`flexible_spec` element; put options that must all independently match into separate elements).
`exclusions` works the same way for negative targeting.

```json
{
  "geo_locations": { "countries": ["AE"] },
  "age_min": 20,
  "age_max": 45,
  "genders": [1],
  "flexible_spec": [
    { "interests": [{ "id": "6003107902433", "name": "Tesla, Inc." }] },
    { "behaviors": [{ "id": "6002714895372", "name": "All travelers" }] }
  ],
  "device_platforms": ["mobile"],
  "publisher_platforms": ["facebook", "audience_network"],
  "facebook_positions": ["feed"]
}
```

Source: https://developers.facebook.com/docs/marketing-api/targeting-specs (fetched 2026-07-01 via
r.jina.ai reader — legacy stable URL, structurally unchanged concept); `targeting.py` confirms field
names `flexible_spec`, `exclusions`, `interests`, `behaviors`, `life_events`, `demographics`-family
fields all exist (fetched 2026-07-01).

### DevicePlatforms enum (SDK-confirmed)

`connected_tv`, `desktop`, `mobile` — note this SDK enum (`class DevicePlatforms` in
`targeting.py`) includes `connected_tv`, one more value than the `basic-targeting` doc snapshot
listed (`mobile`, `desktop` only) — **(unverified discrepancy, same pattern as
`regional_regulated_categories` above: prefer the SDK's more current 3-value list)**.

---

## Custom Audiences

Resource: `CustomAudience` (`facebook_business/adobjects/customaudience.py`, fetched 2026-07-01).

### Key fields

| Field | Type |
|-------|------|
| `id` | numeric string |
| `account_id` | numeric string |
| `approximate_count_lower_bound` / `_upper_bound` | numeric string — size estimate range |
| `customer_file_source` | enum — see below |
| `data_source` | object |
| `delivery_status` | object |
| `description` | string |
| `excluded_custom_audiences` / `included_custom_audiences` | list — audience combination logic |
| `lookalike_audience_ids` | list — Lookalikes derived from this audience |
| `lookalike_spec` | LookalikeSpec — present when this audience *is* a lookalike |
| `name` | string |
| `opt_out_link` | string |
| `operation_status` | object |
| `pixel_id` | numeric string — for pixel-based (`WEBSITE`) audiences |
| `retention_days` | int — rolling window length for pixel/engagement audiences |
| `rule` / `rule_v2` | object — audience membership rule (pixel/engagement audiences) |
| `sharing_status` | object |
| `subtype` | enum — see below |
| `time_created` / `time_updated` / `time_content_updated` | datetime |

### `subtype` enum

`APP`, `BAG_OF_ACCOUNTS`, `BIDDING`, `CLAIM`, `CUSTOM`, `ENGAGEMENT`, `EXCLUSION`, `FOX`,
`LOOKALIKE`, `MANAGED`, `MEASUREMENT`, `MESSENGER_SUBSCRIBER_LIST`, `OFFLINE_CONVERSION`,
`PARTNER`, `PRIMARY`, `REGULATED_CATEGORIES_AUDIENCE`, `STUDY_RULE_AUDIENCE`, `VIDEO`, `WEBSITE`

### `customer_file_source` enum

`USER_PROVIDED_ONLY`, `PARTNER_PROVIDED_ONLY`, `BOTH_USER_AND_PARTNER_PROVIDED`

### `audience_labels` enum (segment classification hints)

`APP_INSTALLERS`, `APP_USERS`, `AT_RISK`, `CART_ABANDONERS`, `CUSTOMER_LEADS`, `DISENGAGED`,
`DISQUALIFIED_LEADS`, `ENGAGED_USERS`, `HIGH_VALUE_CUSTOMERS`, `LOW_VALUE_CUSTOMERS`, `OTHER_1`,
`OTHER_2`, `OTHER_3`, `PERSONAS`, `QUALIFIED_LEADS`, `RECENT_PURCHASERS`, `RESTRICTED_USERS`,
`TRIAL_USERS`, `UNWANTED_CUSTOMERS`

### `usage_restriction` enum

`EXCLUSION_ONLY`, `NONE`

### Creating a Custom Audience and uploading hashed PII

1. `POST /act_{ad_account_id}/customaudiences` with `name`, `subtype: "CUSTOM"`,
   `customer_file_source`.
2. `POST /{custom_audience_id}/users` with:
   - `schema`: array of field-type keys, e.g. `["EMAIL", "FN", "LN"]`
   - `data`: array of arrays, each inner array a hashed record aligned to `schema` order
   - `session`: `{session_id, batch_seq, last_batch_flag, estimated_num_total}` for chunked uploads

**Hashing rule:** SHA-256, most PII fields required — email (trimmed + lowercased before hashing),
phone (strip all symbols/letters first), names (lowercased, Roman-alphabet preferred),
gender/DOB/location fields. `MADID` (mobile advertiser ID) and `EXTERN_ID` do **not** require
hashing. Up to **10,000 records per request**; larger files split across multiple requests sharing
one `session_id` with incrementing `batch_seq`, final request sets `last_batch_flag: true`.

Source: https://developers.facebook.com/docs/marketing-api/audiences/guides/custom-audiences/
(fetched 2026-07-01 via r.jina.ai reader); `customaudience.py` (fetched 2026-07-01, field/enum
names).

---

## Lookalike Audiences

A Lookalike is a `CustomAudience` with `subtype: "LOOKALIKE"` and a populated `lookalike_spec`.

### `LookalikeSpec` fields (`facebook_business/adobjects/lookalikespec.py`, fetched 2026-07-01)

| Field | Type |
|-------|------|
| `country` | string |
| `is_created_by_recommended_dfca` | bool |
| `is_financial_service` | bool |
| `is_parent_lal` | bool |
| `origin` | list\<object\> |
| `origin_event_name` / `origin_event_source_name` / `origin_event_source_type` | string |
| `product_set_name` | string |
| `ratio` | float |
| `starting_ratio` | float |
| `target_countries` | list\<string\> |
| `target_country_names` | list |
| `type` | string |

### Creating a Lookalike Audience

```http
POST /act_{ad_account_id}/customaudiences
{
  "name": "Talas LAL 1% - UAE",
  "subtype": "LOOKALIKE",
  "origin_audience_id": "{seed custom audience id}",
  "lookalike_spec": { "type": "similarity", "ratio": 0.01, "country": "AE" }
}
```

- `type`: `"similarity"` (top ~1%, tighter match) or `"reach"` (broader, up to ~5–10%, more
  volume). `ratio` ranges **0.01–0.20** in 0.01 increments (top 1%–20% of the target country's
  population most similar to the seed). `starting_ratio` can be combined with `ratio` to target a
  *band* (e.g. `starting_ratio: 0.01, ratio: 0.02` → the 1–2% band, excluding the top 1%).
- Seed (`origin_audience_id`) audience needs **at least 100 people** to generate a lookalike at all
  (Meta recommends far more for match quality).
- Conversion-based lookalikes (seeded from campaign/ad-set conversions rather than a
  `CustomAudience`) use `origin_ids` (campaign/ad-set IDs) + `conversion_type: "campaign_conversions"`
  instead of `origin_audience_id`; minimum 100 unique conversions required, 200+ recommended.
- Newly created lookalikes take **1–6 hours** to fully populate; ad sets can be created immediately
  and delivery normalizes once population completes.

Source: https://developers.facebook.com/docs/marketing-api/audiences/guides/lookalike-audiences/
(fetched 2026-07-01 via r.jina.ai reader); `lookalikespec.py` (fetched 2026-07-01, field names).

---

## Ad Studies (A/B Testing / Split Testing)

Resource: `AdStudy` (`facebook_business/adobjects/adstudy.py`, fetched 2026-07-01), created under a
**Business** node (`POST /{business_id}/ad_studies`), and readable as an edge off Campaign/AdSet
(`.../ad_studies`).

### `AdStudy` fields

| Field | Type |
|-------|------|
| `id` | numeric string |
| `business` / `client_business` | Business |
| `canceled_time` / `cooldown_start_time` / `created_time` / `end_time` / `observation_end_time` / `start_time` / `updated_time` | datetime |
| `created_by` / `updated_by` | User |
| `description` | string |
| `measurement_contact` / `sales_contact` | string |
| `name` | string |
| `results_first_available_date` | datetime |
| `type` | enum — see below |
| `cells` | list\<AdStudyCell\> |
| `confidence_level` | float |
| `creative_test_config` | object — budget config for `SPLIT_TEST_V2` creative tests |
| `objectives` | list\<AdStudyObjective\> |
| `viewers` | list |

### `type` enum

`BACKEND_AB_TESTING`, `CONTINUOUS_LIFT_CONFIG`, `CREATIVE_SPEND_ENFORCEMENT`, `GEO_LIFT`, `LIFT`,
`PORTFOLIO_OPTIMIZER`, `SPLIT_TEST`, `VERSION_CONTROL`

(`SPLIT_TEST_V2` appears in the split-testing guide for creative A/B tests specifically — treat it
as a variant of the `SPLIT_TEST` family used for the creative-testing workflow; **(unverified)**
whether `SPLIT_TEST_V2` is a distinct value of this same `type` enum or a separate internal
classifier, since it did not appear in the SDK's `class Type` enumeration fetched 2026-07-01 — the
SDK list above is the confirmed set for the general `type` field.)

### `AdStudyCell` fields

| Field | Type |
|-------|------|
| `id` | numeric string |
| `name` | string |
| `ad_entities_count` | int |
| `ad_ids` | list |
| `control_percentage` / `treatment_percentage` | float |

### Split-test creation workflow

```http
POST https://graph.facebook.com/v25.0/{business_id}/ad_studies
Content-Type: application/json
Authorization: Bearer {access_token}

{
  "name": "QZ3 Search vs PMax-equivalent - Q3 2026",
  "description": "KPI: cost per WhatsApp click",
  "type": "SPLIT_TEST",
  "start_time": 1751328000,
  "end_time": 1752537600,
  "cells": [
    { "name": "Cell A", "treatment_percentage": 50, "adsets": ["120210000000002"] },
    { "name": "Cell B", "treatment_percentage": 50, "adsets": ["120210000000005"] }
  ]
}
```

- Ad-set-level test: `cells[].adsets` (array of ad set IDs); campaign-level test:
  `cells[].campaigns` instead.
- Creative test (`SPLIT_TEST_V2`): 2–5 cells, each cell references **exactly one** `ads` ID;
  requires `creative_test_config` (`daily_budget` or `lifetime_budget_percentage`); requires
  `cooldown_start_time` == `start_time` and `observation_end_time` == `end_time`.
- **Limits:** max **100 concurrent studies**, max **150 cells per study**, max **100 ad entities
  per cell**.
- Best practices (from the official guide): agree on KPI/confidence-level expectations before
  starting; vary **only one variable** per test; keep cell sizes/budgets comparable when comparing
  volume metrics — uneven budgets distort comparability and require manual scaling to interpret;
  pick the winner on the agreed efficiency metric (e.g. lowest CPA); use Lift studies instead of
  Split Tests when true incremental/causal impact (not just relative comparison) is the goal.

Source: https://developers.facebook.com/docs/marketing-api/guides/split-testing/v2.8 (fetched
2026-07-01 via r.jina.ai reader — content is from a v2.8-tagged legacy snapshot; the `ad_studies`/
cells/`treatment_percentage` mechanism itself is a long-stable core concept, structurally confirmed
current via `adstudy.py`/`adstudycell.py` fetched 2026-07-01 from the `main`-branch SDK); the
canonical current-version reference page `docs/marketing-api/reference/ad-study/` exists (confirmed
via WebSearch title match "Graph API Reference v25.0: Ad Study") but returned HTTP 503 / navigation-only
content on every fetch attempt in this session.

---

## Batch API

**Hard limit: 50 requests per batch call.** Confirmed verbatim from the official Graph API guide:
"Batch requests are limited to 50 requests per batch."

### Request

```http
POST https://graph.facebook.com/v25.0/?access_token={access_token}
Content-Type: application/json

{
  "batch": [
    { "method": "GET", "relative_url": "act_123456789/campaigns?fields=name,status" },
    { "method": "POST", "relative_url": "act_123456789/campaigns",
      "body": "name=New+Campaign&objective=OUTCOME_SALES&status=PAUSED&special_ad_categories=%5B%5D" },
    { "method": "POST", "relative_url": "act_123456789/adsets", "name": "create-adset",
      "body": "name=New+AdSet&campaign_id={result=create-campaign:$.id}&..." }
  ]
}
```

- Each `body` is a URL-encoded query string (not raw JSON) for POST/PUT operations.
- `name` on a batch element lets **later** elements reference its result via
  `{result=NAME:$.JSONPath}` — dependent operations execute **sequentially** in array order;
  independent ones may execute in parallel.
- `attached_files` (comma-separated names) references binary parts of a `multipart/form-data`
  request for file uploads (e.g. image/video upload within a batch).

### Response

An array, one element per batch request, in the same order:

```json
[
  { "code": 200, "headers": [ { "name": "Content-Type", "value": "application/json" } ],
    "body": "{\"data\":[...]}" },
  { "code": 200, "headers": [...], "body": "{\"id\":\"120210000000099\"}" }
]
```

Individual elements can fail independently (e.g. `code: 403`) while others in the same batch
succeed — **check each element's `code`/`body`, a batch HTTP 200 does not mean every sub-request
succeeded.** A batch timeout can leave trailing elements `null`.

### Rate-limit interaction

**Batching provides no rate-limit advantage** — "each call within the batch is counted separately
for the purposes of calculating API call limits." A 50-call batch consumes the same quota as 50
separate HTTP requests.

Source: https://developers.facebook.com/docs/graph-api/batch-requests (fetched 2026-07-01 via
r.jina.ai reader, verbatim quotes as marked).

---

## Pagination & Rate Limits

### Pagination

Cursor-based (preferred):
```json
{
  "data": [ /* ... */ ],
  "paging": {
    "cursors": { "before": "NDMyNzQyODI3OTQw", "after": "MTAxNTExOTQ1MjAwNzI5NDE=" },
    "previous": "https://graph.facebook.com/{id}/{edge}?limit=25&before=NDMyNzQyODI3OTQw",
    "next": "https://graph.facebook.com/{id}/{edge}?limit=25&after=MTAxNTExOTQ1MjAwNzI5NDE="
  }
}
```
- `limit` caps page size (server may return fewer after filtering).
- Absence of `next` means final page. **Cursors are not stable long-term** — don't persist them
  across sessions; deleted items can invalidate a saved cursor.
- Time-based paging (`since`/`until`, Unix timestamps) is used on some insight/edge endpoints;
  best practice is to always specify both bounds, max ~6-month span per request.
- Offset-based paging exists as a fallback only — page contents can shift if the underlying list
  changes between requests (items added/removed mid-pagination).

Source: https://developers.facebook.com/docs/graph-api/results (fetched 2026-07-01 via r.jina.ai
reader).

### Rate limits — access-tier-dependent formulas

Per ad account, per rolling one-hour window:

| Business use case | Formula |
|---|---|
| `ads_management` | (100,000 if Standard tier, else 300 if Development tier) + 40 × (# active ads) |
| `ads_insights` | (190,000 if Standard tier, else 600 if Development tier) + 400 × (# active ads) − 0.001 × (# user errors) |
| `custom_audience` | max 700,000; floor of (190,000 if Standard tier, else 5,000 if Development tier) + 40 × (# active custom audiences) |

Additionally, ad-object **create/edit** operations (campaigns, ad sets, ads) are separately capped
around **100 QPS per (app, ad account) pair** — exceeding it returns error code `80004`
("There have been too many calls from this ad-account. Wait a bit and try again.").

Response headers to inspect for current usage: `X-Business-Use-Case-Usage` (per business-use-case
`call_count`, `total_cputime`, `total_time`, and — when throttled —
`estimated_time_to_regain_access`), `X-Ad-Account-Usage`, and `X-FB-Ads-Insights-Throttle`. The
`ads_api_access_tier` value is also exposed in these headers so a caller can programmatically
confirm whether it's in the Standard or Development tier.

Source: https://developers.facebook.com/docs/marketing-api/overview/rate-limiting/ (content
retrieved via WebSearch synthesis of the official page, fetched 2026-07-01 — direct page/reader
fetch returned navigation only in this session, consistent with the same virtualized-content issue
seen on the AdCreative and Error Reference pages); WebSearch cross-reference for the `80004` error
code and 100 QPS create/edit ceiling (fetched 2026-07-01, multiple corroborating sources including
an official-docs-derived summary and a GitHub issue thread quoting the exact error message).

---

## Error Reference

### HTTP status codes

Graph API errors are not confined to one HTTP status — expect standard codes:

| Status | Meaning | Common cause |
|--------|---------|--------------|
| 400 | Bad Request | Invalid field/enum/parameter, missing required field |
| 401 | Unauthorized | Missing/invalid access token |
| 403 | Forbidden | Permission denied, missing scope, App Review requirement not met |
| 404 | Not Found | Wrong node ID / object doesn't exist or isn't visible to this token |
| 429 / rate-limit-flavored 4xx | Throttled | See Rate Limits above |
| 500 / 503 | Server error | Transient — retry with backoff |

**(unverified precision):** Meta's Graph API famously often returns errors with HTTP 200 or other
non-obvious codes depending on the endpoint generation; the `error.code`/`error.type` fields inside
the body (below) are the reliable signal, not the raw HTTP status alone.

### Error envelope (verbatim from the official error-handling guide)

```json
{
  "error": {
    "message": "Message describing the error",
    "type": "OAuthException",
    "code": 190,
    "error_subcode": 460,
    "error_user_title": "A title",
    "error_user_msg": "A message",
    "fbtrace_id": "EJplcsCHuLu"
  }
}
```

| Field | Description |
|-------|-------------|
| `message` | Human-readable description of the error |
| `type` | Exception class name, e.g. `OAuthException` |
| `code` | Numeric error classification |
| `error_subcode` | Additional, more specific error context |
| `error_user_title` / `error_user_msg` | Localized, end-user-safe title/message — safe to surface in a UI |
| `fbtrace_id` | Internal Meta support identifier — include in any support ticket |

### Common error codes (Graph-API-wide — applies to all Marketing API calls)

| Code | Type/Name | Meaning |
|------|-----------|---------|
| 1 | API Unknown | Possibly a temporary issue due to downtime — wait and retry |
| 2 | API Service | Temporary issue due to downtime — wait and retry |
| 3 | API Method | Capability/permissions issue — app lacks the necessary capability |
| 4 | API Too Many Calls | Throttling — wait and retry |
| 10 | API Permission Denied | Permission not granted or has been removed |
| 17 | API User Too Many Calls | Throttling — wait and retry |
| 100 | Invalid Parameter | Bad/missing parameter — check `error_user_msg` for specifics |
| 102 | API Session | Session/token issue — same handling as OAuthException |
| 190 | OAuthException — Access Token Expired | Get a new access token; check `error_subcode` for the specific reason |
| 200–299 | API Permission (range) | Permission not granted or removed |
| 341 | Application limit reached | Downtime or throttling — wait and retry |
| 368 | Temporarily blocked for policy violations | Wait and retry |
| 506 | Duplicate Post | Duplicate posts cannot be published consecutively |
| 1609005 | Error Posting Link | Problem scraping the provided URL — check it resolves publicly |
| 2635 | OAuthException — Deprecated API version | "You are calling a deprecated version of the Ads API. Please update to the latest version." — confirmed via multiple real-world integration bug reports (GitHub issues on `singer-io/tap-facebook`, Meltano `tap-facebook`), **not from a rendered official table in this session** |
| 80004 | Marketing-API-specific rate limit | "There have been too many calls from this ad-account. Wait a bit and try again." — see Rate Limits above |

**OAuthException subcodes (190):** `458` (app not installed), `459` (user checkpointed), `460`
(password changed), `463` (token expired), `464` (unconfirmed user), `467` (invalid access token),
`492` (invalid session).

**(unverified — extended Marketing-API-specific table):** Meta publishes a dedicated, much longer
"Error Codes" reference specifically for the Marketing API at
`developers.facebook.com/docs/marketing-api/error-reference/` (confirmed to exist and be current
for v25.0 via a WebSearch title match), covering Ads-specific codes (e.g. iOS 14/SKAdNetwork error
codes as a separate sub-table) beyond the general Graph API table above. **That page's actual table
content could not be extracted in this session** — every fetch attempt (direct `WebFetch`, `r.jina.ai`
reader, alternate `/documentation/ads-commerce/...` mirror URL, multiple prompt phrasings) returned
only sidebar navigation, most likely because the table is rendered client-side from a large
virtualized dataset that a headless single-snapshot fetch doesn't capture. Do not treat the table
above as exhaustive for Marketing-API-specific codes; treat it as the confirmed Graph-API-core
subset plus the handful of Marketing-API-specific codes independently corroborated via WebSearch.

### Extracting error details

```python
resp = requests.post(url, headers=headers, json=payload)
if resp.status_code != 200 or "error" in resp.json():
    err = resp.json().get("error", {})
    print(err.get("message"))
    print(err.get("type"), err.get("code"), err.get("error_subcode"))
    print("fbtrace_id:", err.get("fbtrace_id"))
    # error_user_msg / error_user_title are safe to show end users directly
```

Source: https://developers.facebook.com/docs/graph-api/guides/error-handling (fetched 2026-07-01
via r.jina.ai reader, envelope and code table transcribed as marked); WebSearch cross-reference for
codes `2635` and `80004` (fetched 2026-07-01).

---

## Gotchas

1. **`special_ad_categories` is mandatory on every Campaign and Ad create call** — send `[]` or
   `["NONE"]` explicitly if not a regulated category; omitting it is a create-time error.
2. **`act_` prefix required** on the ad-account ID for every ad-account-scoped endpoint
   (`act_123456789`, not `123456789`) — a bare numeric ID 404s.
3. **REST legacy naming is confusing** — the doc URL `reference/ad-campaign-group/` is Campaign, and
   `reference/ad-campaign/` (no `-group`) is AdSet, and `reference/adgroup/` is Ad. The SDK class
   names (`Campaign`, `AdSet`, `Ad`) are the sane ones — use those mentally when reading REST docs.
4. **No `updateMask`** — unlike Google Ads REST, a Graph API `POST` update only touches the fields
   present in the body; there is no separate field-mask parameter. Never send an object's full
   current state on update — send only the delta.
5. **Budget is mutually exclusive between `daily_budget` and `lifetime_budget`**, and (for CBO)
   between Campaign-level and AdSet-level — a Campaign using Campaign Budget Optimization holds the
   budget; its child AdSets should not also set their own `daily_budget`/`lifetime_budget` in that
   case (Ad Set Budget Optimization/ABO mode is the alternative where each AdSet holds its own
   budget and the Campaign holds none). **(unverified precise validation error text for the
   conflicting case — confirmed only that the two fields are mutually exclusive per-object; the
   cross-object CBO/ABO exclusivity behavior is standard, widely corroborated knowledge, not
   independently doc-quoted in this session.)**
6. **`special_ad_category` (singular) is deprecated since v7.0** — use `special_ad_categories`
   (plural array) instead; the singular field still exists for backward-compat reads only.
7. **Advantage+ Shopping/App campaign creation blocked as of v25.0** — creating, duplicating, or
   updating ASC/AAC campaign types via the API is disallowed starting this version; existing ones
   will be force-paused by v26.0 (Sept 2026).
8. **`smart_promotion_type` cannot be set on new campaigns as of v25.0** — still readable on
   existing campaigns created before the restriction.
9. **AdCreative fields are almost entirely spec objects** (`object_story_spec`, `asset_feed_spec`,
   `template_url_spec`, etc.) rather than flat scalars — a "simple" text/image ad still requires
   nesting through `object_story_spec.link_data`.
10. **Custom Audience hashing must happen client-side before upload** — Meta receives only SHA-256
    hashes for PII fields (email, phone, name, DOB, location); sending raw PII in the `data` array
    is a policy violation, not just ineffective.
11. **Batch is 50 requests max and gives zero rate-limit relief** — batching is purely a
    round-trip/latency optimization, not a quota optimization; size any bulk-mutation loop around
    50-item chunks and still track cumulative call count against the tier formulas.
12. **Lookalike seed minimum is ~100**, but practically needs to be much larger for good match
    quality; a freshly created lookalike can take up to 6 hours to populate before delivery
    normalizes.
13. **`error.code` is the reliable signal, not raw HTTP status** — Graph API error responses don't
    consistently map 1:1 to conventional REST status codes across all endpoint generations; always
    inspect the JSON `error` object.
14. **This session's fetch tooling could not render two specific doc pages** —
    `reference/ad-creative/` and `error-reference/` — both are unusually large tables that appear to
    be client-side virtualized; this KB substitutes the live `facebook-python-business-sdk` GitHub
    source for AdCreative (arguably more current) and flags the Marketing-API-specific error table
    as incomplete. Re-attempt those two pages directly in a real browser if a doc-verbatim
    transcription is ever required.

---

## Sources

All URLs fetched 2026-07-01 (via `r.jina.ai` reader proxy unless noted; direct `WebFetch` attempts
on `developers.facebook.com` frequently returned only sidebar navigation for very large pages —
noted per-section above where that happened):

1. https://developers.facebook.com/docs/graph-api/changelog/versions/ — version/expiration table
2. https://developers.facebook.com/docs/graph-api/guides/versioning/ — versioning policy language
3. https://developers.facebook.com/blog/post/2026/02/18/introducing-graph-api-v25-and-marketing-api-v25/ — v25.0 announcement
4. https://developers.facebook.com/docs/marketing-api/get-started — base URL, auth basics
5. https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/ — Campaign fields/enums
6. https://developers.facebook.com/docs/marketing-api/reference/ad-campaign/ — AdSet fields/enums
7. https://developers.facebook.com/docs/marketing-api/reference/adgroup/ — Ad fields/enums
8. https://developers.facebook.com/docs/marketing-api/audiences/reference/basic-targeting/ — geo/demographic targeting
9. https://developers.facebook.com/docs/marketing-api/audiences/reference/placement-targeting/ — placement enums (verbatim table)
10. https://developers.facebook.com/docs/marketing-api/targeting-specs — flexible_spec/exclusions concept
11. https://developers.facebook.com/docs/marketing-api/audiences/guides/custom-audiences/ — Custom Audience creation, hashing
12. https://developers.facebook.com/docs/marketing-api/audiences/guides/lookalike-audiences/ — Lookalike creation, ratio rules
13. https://developers.facebook.com/docs/marketing-api/guides/split-testing/v2.8 — Ad Studies/split-test workflow
14. https://developers.facebook.com/docs/graph-api/batch-requests — Batch API, 50-request limit (verbatim)
15. https://developers.facebook.com/docs/graph-api/results — pagination
16. https://developers.facebook.com/docs/graph-api/guides/error-handling — error envelope + core code table (verbatim)
17. https://developers.facebook.com/docs/marketing-api/overview/rate-limiting/ — rate-limit formulas, access tiers (via WebSearch synthesis)
18. https://developers.meta.com/blog/updates-to-ads-management-standard-access-feature/ — access-tier renaming, May 2026
19. `facebook_business/apiconfig.py` — https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/main/facebook_business/apiconfig.py — current API_VERSION/SDK_VERSION pin
20. `facebook_business/adobjects/campaign.py`, `adset.py`, `ad.py`, `adcreative.py`, `targeting.py`, `customaudience.py`, `lookalikespec.py`, `adstudy.py`, `adstudycell.py`, `adcreativeobjectstoryspec.py`, `adcreativelinkdata.py`, `adcreativelinkdatacalltoaction.py`, `adassetfeedspec.py` — all under `https://raw.githubusercontent.com/facebook/facebook-python-business-sdk/main/facebook_business/adobjects/` — field/enum ground truth cross-check
21. WebSearch synthesis (multiple queries, fetched 2026-07-01) for: v25/v26 changelog corroboration, `act_` prefix convention, error codes `2635` and `80004`, rate-limiting formulas, `X-Business-Use-Case-Usage` header fields — see inline citations per section

---

## Developer Guide

> Comprehensive implementation reference for LLM agents building Meta Marketing API integrations.
> Covers the Campaign→AdSet→Ad→AdCreative creation workflow, bidding/budget mechanics, creative
> deep-dive, targeting deep-dive, audiences, ad studies, batching, error handling, pagination, and
> versioning — sufficient to implement `mads-cli` commands without re-fetching docs for the common
> cases. Sources as cited per-section above; DG sections synthesize material already cited, no new
> unsourced claims are introduced here.

---

### DG-1. Campaign → Ad Set → Ad → Ad Creative Creation Workflow

Creating a runnable ad requires, in order: **Campaign**, **AdSet**, **AdCreative**, **Ad** (the Ad
references the Creative, so the Creative must exist — or be inlined — before or alongside the Ad).

| Step | Resource | Endpoint | Depends on |
|------|----------|----------|------------|
| 1 | Campaign | `POST act_{id}/campaigns` | — |
| 2 | AdSet | `POST act_{id}/adsets` | `campaign_id` |
| 3 | AdCreative | `POST act_{id}/adcreatives` | Page ID (+ uploaded image/video hash) |
| 4 | Ad | `POST act_{id}/ads` | `adset_id` + `creative.creative_id` |

**Atomic batch creation** (using the generic Batch API, dependent-request references):

```json
{
  "batch": [
    { "method": "POST", "relative_url": "act_123456789/campaigns", "name": "campaign",
      "body": "name=Talas+QZ3+Prospecting&objective=OUTCOME_SALES&status=PAUSED&special_ad_categories=%5B%5D" },
    { "method": "POST", "relative_url": "act_123456789/adsets", "name": "adset",
      "body": "name=QZ3+AdSet&campaign_id={result=campaign:$.id}&daily_budget=10000&billing_event=IMPRESSIONS&optimization_goal=OFFSITE_CONVERSIONS&bid_strategy=LOWEST_COST_WITHOUT_CAP&status=PAUSED&targeting=%7B%22geo_locations%22%3A%7B%22countries%22%3A%5B%22AE%22%5D%7D%7D" },
    { "method": "POST", "relative_url": "act_123456789/adcreatives", "name": "creative",
      "body": "name=QZ3+Creative&object_story_spec=%7B%22page_id%22%3A%22111222333444%22%2C%22link_data%22%3A%7B%22link%22%3A%22https%3A%2F%2Fshop.talas.ae%2F%3Fbranch%3Dqz3%22%2C%22message%22%3A%22Genuine%2C+used+%26+aftermarket+Tesla+parts%22%2C%22image_hash%22%3A%22abc123%22%7D%7D" },
    { "method": "POST", "relative_url": "act_123456789/ads",
      "body": "name=QZ3+Ad&adset_id={result=adset:$.id}&creative=%7B%22creative_id%22%3A%22{result=creative:$.id}%22%7D&status=PAUSED" }
  ]
}
```

Note this uses the **generic Graph API `batch` parameter** (50-item limit, dependent-request
`{result=NAME:$.id}` references), not a Marketing-API-specific "atomic mutate" mechanism — Meta's
Marketing API has no single-call cross-resource atomic-create endpoint analogous to Google Ads'
`googleAds:mutate`; batching is the closest equivalent, and it is **not atomic across elements**
(a later element can fail after an earlier one has already committed — there is no
`partialFailure: false` all-or-nothing guarantee).

Everything created above should be left `status: "PAUSED"` until reviewed — this mirrors the
existing gads-cli convention of snapshot-before-mutate; there is no dry-run-and-rollback primitive
in the Marketing API itself.

---

### DG-2. Bidding Strategies and Budget Optimization

**Bid strategies** (same 4 enum values at Campaign level for CBO, or AdSet level for ABO — see
Enums Reference above for the full value list and the (unverified) caveat on exact `bid_amount`
requirements per strategy).

**Campaign Budget Optimization (CBO) vs. Ad Set Budget Optimization (ABO):**
- CBO: `daily_budget`/`lifetime_budget` set on the **Campaign**; Meta's delivery system
  automatically distributes spend across the campaign's ad sets. Child ad sets should not also
  carry their own budget in this mode.
- ABO: budget set on **each AdSet** individually; the Campaign carries no budget field.
- These are mutually exclusive at the object level — `daily_budget` and `lifetime_budget` cannot
  both be set on the same object (confirmed field-level constraint from the Campaign/AdSet doc
  fetches); the CBO-vs-ABO cross-object exclusivity described above is standard practitioner
  knowledge, **(unverified via a directly rendered bidding/budget doc page in this session — the
  dedicated `bidding/overview/budgets` page returned navigation only on every fetch attempt)**.

**Spend cap:** minimum $100-equivalent; the magic value `922337203685478` (`int64` max minus a
constant, i.e. Meta's "unset/no cap" sentinel) removes a previously-set `spend_cap`.

---

### DG-3. Objective → Optimization Goal → Billing Event

Meta's delivery stack has three layers that must be compatible:

1. **`objective`** (Campaign level) — the overall business goal (`OUTCOME_SALES`,
   `OUTCOME_LEADS`, `OUTCOME_TRAFFIC`, `OUTCOME_ENGAGEMENT`, `OUTCOME_AWARENESS`,
   `OUTCOME_APP_PROMOTION`, or a legacy objective).
2. **`optimization_goal`** (AdSet level) — what specifically the delivery algorithm optimizes for
   within that objective (e.g. `OFFSITE_CONVERSIONS`, `LINK_CLICKS`, `LANDING_PAGE_VIEWS`,
   `THRUPLAY`, `REACH`).
3. **`billing_event`** (AdSet level) — what you're actually charged per (`IMPRESSIONS` is by far
   the most common choice regardless of `optimization_goal`, since Meta's auction is
   impression-based even when optimizing for a downstream event like a conversion).

**(unverified):** the exact valid-combinations matrix (which `optimization_goal` values are legal
under which `objective` values) is enforced server-side at AdSet creation time but was not
independently re-confirmed from a rendered compatibility-matrix doc page in this session — expect
an `INVALID_PARAMETER`-class error (code 100) if an incompatible pair is submitted, and treat any
hardcoded compatibility table in `mads-cli` as needing empirical validation against a real ad
account before shipping.

---

### DG-4. Ad Creative Deep Dive

`AdCreative.object_story_spec` (`facebook_business/adobjects/adcreativeobjectstoryspec.py`, fetched
2026-07-01) fields: `instagram_user_id`, `link_data`, `page_id`, `photo_data`, `product_data`,
`template_data`, `text_data`, `video_data`.

`link_data` (`adcreativelinkdata.py`, fetched 2026-07-01) — the most common sub-object for a
standard link/website ad — full field list: `ad_context`, `additional_image_index`,
`app_link_spec`, `attachment_style`, `automated_product_tags`, `boosted_product_set_id`,
`branded_content_shared_to_sponsor_status`, `branded_content_sponsor_page_id`, `call_to_action`,
`caption`, `child_attachments` (carousel cards), `collection_thumbnails`,
`customization_rules_spec`, `description`, `event_id`, `force_single_link`, `format_option`,
`image_crops`, `image_hash`, `image_layer_specs`, `image_overlay_spec`, `is_local_expansion`,
`link`, `message`, `multi_share_end_card`, `multi_share_optimized`, `name`, `offer_id`,
`page_welcome_message`, `picture`, `post_click_configuration`, `preferred_image_tags`,
`preferred_video_tags`, `retailer_item_ids`, `show_multiple_images`, `smart_pse_enabled`,
`static_fallback_spec`, `use_flexible_image_aspect_ratio`.

`link_data.call_to_action` (`adcreativelinkdatacalltoaction.py`, fetched 2026-07-01): just `type`
(a `CallToActionType` value — see Enums Reference) and `value` (object, typically
`{"link": "https://..."}`, or app/phone/event specifics depending on `type`).

`asset_feed_spec` (`adassetfeedspec.py`, fetched 2026-07-01) — used for Dynamic Creative /
Advantage+ creative (multiple asset variants Meta auto-combines): `ad_formats`, `additional_data`,
`app_product_page_id`, `asset_customization_rules`, `audios`, `autotranslate`, `bodies`,
`call_ads_configuration`, `call_to_action_types`, `call_to_actions`, `captions`, `carousels`,
`ctwa_consent_data`, `descriptions`, `events`, `groups`, `images`, `link_urls`,
`message_extensions`, `onsite_destinations`, `optimization_type`, `promotional_metadata`,
`reasons_to_shop`, `shops_bundle`, `titles`, `translations`, `upcoming_events`, `videos`,
`web_destination_spec`. **(unverified: `ad_formats` valid string values, e.g. whether
`"CAROUSEL_FORMAT"`/`"SINGLE_IMAGE"` are the exact literal strings — the SDK does not define an enum
class for this field, and no doc page rendering was obtained in this session to confirm the literal
values; verify empirically before hardcoding.)**

**Image/video upload prerequisite:** an ad creative referencing an image or video needs the
asset uploaded first — `POST act_{id}/adimages` (returns `image_hash`, used in `link_data.image_hash`
or top-level `AdCreative.image_hash`) or `POST act_{id}/advideos` (returns `video_id`, used in
`AdCreative.video_id` / `object_story_spec.video_data`). Field names for these two upload resources
were confirmed present via `adimage.py` / `advideo.py` SDK source (fetched 2026-07-01) but their
own full field tables are out of scope for this Campaign/AdSet/Ad/AdCreative-focused KB file.

---

### DG-5. Targeting Deep Dive

See the Targeting Reference section above for the full placement-position tables (verbatim from
the official placement-targeting doc) and the `flexible_spec` AND/OR semantics.

**Advantage+ targeting / targeting expansion:** enabling Facebook to expand beyond the literal
targeting spec (broader reach at potentially lower cost) does **not** create a lookalike audience
and does **not** alter location/demographic/exclusion targeting — it only loosens interest/behavior
matching when doing so improves results at a similar or lower cost per result. **(unverified: the
exact API field controlling this — likely `targeting_optimization` or `targeting_automation`, both
confirmed to exist as field names in `targeting.py` — was not independently confirmed against a
rendered doc page describing its accepted values in this session.)**

**Age/gender:** `age_min` floor is 13 (many objectives default the practical floor to 18);
`age_max` ceiling is 65; `genders`: `1` = male, `2` = female, omit the field entirely to target all
genders. `user_age_unknown` (boolean) defaults to `true` starting May 2026 for WhatsApp Status
placements specifically — a narrow, dated exception worth flagging if `mads-cli` ever targets
WhatsApp Status.

---

### DG-6. Custom Audiences — Full Reference

**Hashing implementation (Python, SHA-256):**

```python
import hashlib

def normalize_and_hash(value: str, field: str) -> str:
    v = value.strip().lower()
    if field == "phone":
        v = "".join(ch for ch in v if ch.isdigit())  # strip symbols/letters, keep digits
    return hashlib.sha256(v.encode("utf-8")).hexdigest()

schema = ["EMAIL", "FN", "LN"]
row = ["user@example.com", "Mohammed", "Al Talas"]
hashed_row = [normalize_and_hash(v, "email" if i == 0 else "name") for i, v in enumerate(row)]
```

**Upload request:**
```http
POST /{custom_audience_id}/users
{
  "schema": ["EMAIL", "FN", "LN"],
  "data": [ ["<hash>", "<hash>", "<hash>"] ],
  "session": { "session_id": 1701234567, "batch_seq": 1, "last_batch_flag": true, "estimated_num_total": 1 }
}
```

`MADID` (mobile advertiser ID / IDFA/GAID) and `EXTERN_ID` (your own internal customer ID) are the
two schema keys that are **not** hashed. All other supported schema keys (email, phone, name
components, gender, DOB, city/state/zip/country) require the SHA-256 hash of the normalized value.

Full `subtype` and `customer_file_source` enums are in the Custom Audiences section above.

---

### DG-7. Lookalike Audiences — Full Reference

See the Lookalike Audiences section above for the full `LookalikeSpec` field table, `ratio`/`type`
mechanics, seed-size minimum, and conversion-based-lookalike variant. No additional detail beyond
what's already cited there.

---

### DG-8. Ad Studies / Split Testing — Full Reference

See the Ad Studies section above for the full `AdStudy`/`AdStudyCell` field tables, the `type`
enum, the split-test creation JSON, and the documented limits (100 concurrent studies / 150 cells
per study / 100 ad entities per cell) and best practices. No additional detail beyond what's already
cited there.

---

### DG-9. Batch API — Complete Reference

See the Batch API section above for the full request/response shape, the confirmed **50-request
limit**, dependent-request `{result=NAME:$.path}` syntax, `attached_files` for binary uploads, and
the "no rate-limit advantage" behavior. No additional detail beyond what's already cited there.

---

### DG-10. Error Handling — Complete Reference

See the Error Reference section above for the full envelope shape, the core Graph-API-wide error
code table (verbatim from the official guide), the two Marketing-API-specific codes independently
corroborated (`2635` deprecated-version, `80004` ad-account rate limit), and the explicit note that
the dedicated Marketing-API error-reference table could not be extracted in this session (flagged,
not fabricated).

**Retry strategy (standard practice, not independently doc-quoted beyond the general "wait and
retry" language already cited per-code above):** exponential backoff on codes `1`, `2`, `4`, `17`,
`341`, `368`, and any `5xx`; do not retry `10`/`190`/`200-299` without first fixing the underlying
permission/token problem; log `fbtrace_id` on every error for support escalation.

---

### DG-11. Pagination — Complete Reference

See Pagination & Rate Limits above for the cursor-based `paging.cursors.{before,after}` shape,
`limit` parameter, time-based `since`/`until` alternative, and the offset-based fallback's
instability caveat. No additional detail beyond what's already cited there.

---

### DG-12. Rate Limits and Quotas

See Pagination & Rate Limits above for the per-ad-account, per-hour formulas for `ads_management`,
`ads_insights`, and `custom_audience` business use cases, the Standard-vs-Development access-tier
distinction (and how an app qualifies for Standard via Advanced Access to the "Marketing API Access
Tier" feature, min. 500 calls in 15 days as of May 2026), and the response headers
(`X-Business-Use-Case-Usage`, `X-Ad-Account-Usage`, `ads_api_access_tier`) that expose current usage
and tier programmatically.

---

### DG-13. API Versioning Policy

- **Marketing API versions have their own expiration schedule**, distinct from and generally
  shorter than the Graph-API-core "2 years after the next version ships" rule — always check the
  Marketing-API-specific column in the versions table (Status & Versions section above), not the
  generic Graph API policy language.
- **Always send an explicit version** in the URL path (`/v25.0/...`) — unversioned calls silently
  use whatever default is configured in the App Dashboard, which can change without the calling
  code changing.
- **Current version at time of writing: `v25.0`** (released 2026-02-18). Its own Marketing-API
  expiration is listed as `TBD` — there is no confirmed sunset date to plan a migration deadline
  around yet; re-check `https://developers.facebook.com/docs/graph-api/changelog/versions/`
  periodically, and treat `v26.0` (expected ~September 2026 per Meta's own forward-looking blog
  statement, not yet released as of this KB's fetch date) as the next likely version bump to watch
  for.
- **Breaking-change discovery pattern used in this KB:** version-specific announcement blog posts
  (`developers.facebook.com/blog/post/{year}/{month}/{day}/introducing-graph-api-v{N}-and-marketing-api-v{N}/`)
  are a reliable, consistently-rendering source for what changed in each version — prefer them over
  the reference/changelog pages when those return only navigation.
