# Meta Graph API — Business Manager, System Users, Pages, Webhooks

Scope of this document: the four Graph API surfaces `mads-cli` needs outside the Marketing API proper —
**Business Manager** (the `Business` node), **System Users** (Business Asset Management), **Pages**
(profile info + organic Insights, and the deprecated Reviews/Recommendations surface), **ad-account
Webhooks** (the 5 real-time trigger fields), and **`appsecret_proof`** request signing. It does not cover
Campaign/AdSet/Ad CRUD (see `marketing-api.md`) or Instagram Graph API.

All facts below were verified against `developers.facebook.com` (fetched 2026-07-01) and cross-checked
against the `facebook-business` Python SDK source on GitHub
(`facebook/facebook-python-business-sdk`, `main` branch) for field-name accuracy. Anything not
doc-confirmed is explicitly tagged **(unverified)**.

---

## Status & Versions

| Item | Value |
|---|---|
| Current Graph API / Marketing API version | **v25.0** — released **February 18, 2026** |
| Next version (v26.0) | Not yet released as of 2026-07-01. No v26.0 changelog page exists yet. |
| Version lifespan policy | Each version stays callable for a **minimum of 2 years after the *next* version ships** — not a fixed calendar window. When a version expires, calls "default to the next oldest usable version" rather than hard-failing. |
| v19.0 | Deprecated **May 21, 2026** |
| v20.0 | Deprecated **September 24, 2026** |
| v21.0 and older | Already unusable — Meta stopped accepting calls on any version older than v22.0 **September 9, 2025** (an accelerated/security-driven cutover, not the normal 2-year clock) |
| v22.0 | Released January 21, 2025 — introduced the Page ratings/recommendations deprecation (see below) |
| v23.0 | Released May 29, 2025 |
| v24.0 | Released October 8, 2025 |

**This document describes v25.0**, confirmed as current by directly fetching
`https://developers.facebook.com/docs/graph-api/changelog` on 2026-07-01, which states verbatim:
*"The latest Graph API version is: `v25.0`"*.

**Two dated changes that are already LIVE as of today (2026-07-01) and materially affect this doc's scope:**

1. **Page reviews/recommendations reading is dead for every API version, effective September 9, 2025.**
   See the Pages → Reviews section below.
2. **A large batch of Page/Post Insights "unique reach" metrics were deprecated for all API versions
   effective June 15, 2026** (moved up from an originally-announced June 30, 2026 date). See the Pages →
   Organic Insights section below — this happened only two weeks before today's date, so it is very
   likely to be the proximate cause of any `page_impressions_unique`-style query suddenly failing.

Sources:
- https://developers.facebook.com/docs/graph-api/changelog
- https://developers.facebook.com/docs/graph-api/changelog/versions/
- https://developers.facebook.com/docs/graph-api/changelog/version25.0/
- https://developers.facebook.com/docs/graph-api/guides/versioning/

---

## Base URLs

| Purpose | Base URL |
|---|---|
| Graph API (all resources in this doc) | `https://graph.facebook.com/{version}` |
| OAuth token exchange (refresh) | `https://graph.facebook.com/{version}/oauth/access_token` |
| OAuth token revoke | `https://graph.facebook.com/{version}/oauth/revoke` |

Ad account IDs are always referenced with the `act_` prefix in the URL path (e.g. `act_1234567890`)
even though the bare numeric ID is what's stored in the `AdAccount.account_id` field.

---

## Auth / OAuth Scopes

| Scope | Needed for |
|---|---|
| `business_management` | Creating/reading Businesses, System Users, installing apps, generating system-user tokens |
| `ads_management` | Read/write ad account webhook subscriptions (`subscribed_apps`), most write calls in this doc |
| `ads_read` | Read-only ad account access |
| `pages_show_list` | Listing Pages a user manages |
| `pages_read_engagement` | Page Insights (organic), most Page-info fields |
| `pages_read_user_content` | Page ratings/reviews edge (permission still enforced even though the edge is functionally dead — see Gotchas) |
| `pages_manage_metadata` | Managing Page settings/webhooks subscription state |
| `read_insights` | Required alongside `pages_read_engagement` for `/​{page-id}/insights` |

**Token types used in this doc:**
- **User access token** — used to create a Business, or (with `business_management`) to create/manage System Users under a Business the calling user administers.
- **System User access token** — long-lived/non-expiring or 60-day token, used for server-to-server automation once created (see System Users section).
- **Page access token** — required for `/{page-id}` info fields and `/{page-id}/insights`; obtained via `GET /{user-id}/accounts` or via a System User with the Page assigned as an asset.

Source: https://developers.facebook.com/docs/business-management-apis/

---

## Resources & Endpoints

| Area | Resource | Method | Path | Purpose | Source |
|---|---|---|---|---|---|
| Business Manager | businesses | create | POST | `/{user-id}/businesses` | Create a new Business Manager | https://developers.facebook.com/docs/marketing-api/business-manager-api/get-started |
| Business Manager | business | get | GET | `/{business-id}` | Read a Business node | https://developers.facebook.com/docs/graph-api/reference/business/ |
| Business Manager | owned_ad_accounts / client_ad_accounts | list | GET | `/{business-id}/owned_ad_accounts`, `/{business-id}/client_ad_accounts` | List ad accounts owned by vs. shared with this Business | https://developers.facebook.com/docs/marketing-api/business-manager-api/ |
| Business Manager | owned_pages / client_pages | list | GET | `/{business-id}/owned_pages`, `/{business-id}/client_pages` | List Pages owned by vs. shared with this Business | https://developers.facebook.com/docs/marketing-api/business-manager-api/ |
| System Users | system_users | create | POST | `/{business-id}/system_users` | Create a system user under a Business | https://developers.facebook.com/docs/marketing-api/business-asset-management/guides/system-users |
| System Users | system_users | list | GET | `/{business-id}/system_users` | List system users | https://developers.facebook.com/docs/marketing-api/business-asset-management/guides/system-users |
| System Users | applications | install | POST | `/{system-user-id}/applications` | Install (link) an app to a system user | https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/ |
| System Users | access_tokens | generate | POST | `/{system-user-id}/access_tokens` | Generate a system-user access token | https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/ |
| System Users | system_user_access_tokens | generate (alias) | POST | `/{business-id}/system_user_access_tokens` | Business-scoped equivalent of the above (SDK-confirmed) | facebook-business SDK `business.py` |
| System Users | oauth/access_token | refresh | GET | `/oauth/access_token?grant_type=fb_exchange_token` | Renew a 60-day system-user token before it expires | https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/ |
| System Users | oauth/revoke | revoke | GET | `/oauth/revoke` | Revoke a system-user access token | https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/ |
| Pages | page | get | GET | `/{page-id}` | Page profile info | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Pages | insights | list | GET | `/{page-id}/insights` | Organic Page/Post Insights metrics | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Pages | ratings | get | GET | `/{page-id}/ratings` | **DEPRECATED** — reviews/recommendations; returns error 12 | https://developers.facebook.com/docs/graph-api/reference/page/ratings/ |
| Webhooks | subscribed_apps | subscribe | POST | `/act_{ad-account-id}/subscribed_apps` | Subscribe an app to an ad account's webhook events | https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-ad-accounts/ |
| Webhooks | subscribed_apps | verify | GET | `/act_{ad-account-id}/subscribed_apps` | Confirm subscription | https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-ad-accounts/ |

---

## Concrete Endpoint Reference

---

### POST /{user-id}/businesses — Create Business Manager

**Full URL:**
```
POST https://graph.facebook.com/v25.0/{user-id}/businesses
```

**Parameters:**

| Parameter | Type | Req? | Notes |
|---|---|---|---|
| `name` | string | required | Business Manager display name |
| `vertical` | enum (`Business.Vertical`) | required | e.g. `AUTOMOTIVE`, `ECOMMERCE`, `RETAIL`, `ADVERTISING` — see full enum below |
| `primary_page` | string (Page ID) | recommended | A Page ID representing the business |
| `timezone_id` | int (enum) | optional | Business timezone |
| `child_business_external_id` | string | optional | Used for 2-tier / partner-created child businesses |
| `survey_business_type`, `survey_num_assets`, `survey_num_people` | enum/int | optional | Onboarding survey metadata |

**Permissions:** `business_management`. The creating user automatically becomes an **Admin** with full
control of the new Business. Per the official guide: *"Only create a new business manager if you are
setting up a new business manager for yourself or your clients"* — and **deleting a Business Manager is
not allowed** once created (permanent action).

**Example request:**
```
POST https://graph.facebook.com/v25.0/1234567890/businesses
Content-Type: application/x-www-form-urlencoded

name=Talas Auto Parts&vertical=AUTOMOTIVE&primary_page=987654321098765&access_token=EAAG...
```

**Example response:**
```json
{ "id": "111222333444555" }
```

**Cross-check:** the SDK's `User.create_business()` (`facebook_business/adobjects/user.py`) confirms the
endpoint (`POST /{id}/businesses`) and exact param set: `child_business_external_id`, `email`, `name`,
`primary_page`, `sales_rep_email`, `survey_business_type`, `survey_num_assets`, `survey_num_people`,
`timezone_id`, `vertical`.

Sources:
- https://developers.facebook.com/docs/marketing-api/business-manager-api/get-started
- facebook-business SDK: `facebook_business/adobjects/user.py::create_business`

---

### GET /{business-id} — Get Business

**Full URL:**
```
GET https://graph.facebook.com/v25.0/{business-id}?fields=name,vertical,verification_status,primary_page,timezone_id
```

**Business node fields** (SDK-confirmed, `facebook_business/adobjects/business.py::Business.Field`):

| Field | Type | Notes |
|---|---|---|
| `id` | numeric string | Business Manager ID |
| `name` | string | Display name |
| `vertical` | enum | See `Vertical` enum below |
| `vertical_id` | int | Numeric form of vertical |
| `verification_status` | enum | See table below |
| `primary_page` | string (Page ID) | The Page representing this business |
| `timezone_id` | int | Business timezone |
| `two_factor_type` | enum | `none`, `admin_required`, `all_required` |
| `payment_account_id` | string | Linked payment account |
| `created_time` / `updated_time` | datetime | — |
| `created_by` / `updated_by` | object | User who created/updated |
| `is_hidden` | bool | Hidden business flag |
| `link` | string | URL to the Business Manager settings page |
| `profile_picture_uri` | string | — |
| `block_offline_analytics` | bool | — |
| `whatsapp_business_manager_messaging_limit` | enum | Tiered messaging limit (`TIER_250` … `TIER_UNLIMITED`) |
| `user_access_expire_time` | datetime | When the calling user's access to this business expires (2FA/compliance) |

**`verification_status` enum:** `expired`, `failed`, `ineligible`, `not_verified`, `pending`,
`pending_need_more_info`, `pending_submission`, `rejected`, `revoked`, `verified`

**`vertical` enum (partial — 30+ values total):** `ADVERTISING`, `AUTOMOTIVE`, `CONSUMER_PACKAGED_GOODS`,
`ECOMMERCE`, `EDUCATION`, `ENERGY_AND_UTILITIES`, `ENTERTAINMENT_AND_MEDIA`, `FINANCIAL_SERVICES`,
`GAMING`, `GOVERNMENT_AND_POLITICS`, `HEALTH`, `LUXURY`, `MARKETING`, `NON_PROFIT`, `NOT_SET`,
`ORGANIZATIONS_AND_ASSOCIATIONS`, `OTHER` … (full list in SDK `Business.Vertical`)

Source: facebook-business SDK `facebook_business/adobjects/business.py`

---

### Owned vs. Client Assets (Business Manager 2-tier model)

Every asset (ad account, Page, app, catalog, WhatsApp account) attached to a Business is either:

- **Owned** — created directly inside this Business (`get_owned_ad_accounts`, `get_owned_pages`,
  `get_owned_apps` in the SDK → `GET /{business-id}/owned_ad_accounts`, `/owned_pages`, `/owned_apps`)
- **Client** — shared with this Business by a partner/agency Business
  (`get_client_ad_accounts`, `get_client_pages`, `get_client_apps` → `GET /{business-id}/client_ad_accounts`,
  `/client_pages`, `/client_apps`)

This owned/client split is the foundation of Meta's **2-Tier Business Manager** partner model (an agency
Business is "client" to the brand's "owned" Business, or vice versa). The exact mechanics of provisioning
a 2-tier partner relationship beyond this owned/client read split were not independently doc-confirmed in
this pass — **(unverified)** for anything beyond the edge names above.

Source: facebook-business SDK `facebook_business/adobjects/business.py` (methods `get_owned_ad_accounts`,
`get_client_ad_accounts`, `get_owned_pages`, `get_client_pages`, `get_owned_apps`, `get_client_apps`,
`create_client_app`, `create_client_page`)

---

## System Users

System Users are non-human identities scoped to a Business Manager, used for server-side automation
(webhooks consumers, cron scripts, CLIs like `mads-cli`) without tying access to a specific employee's
Facebook login.

### POST /{business-id}/system_users — Create System User

**Full URL:**
```
POST https://graph.facebook.com/v25.0/{business-id}/system_users
```

**Parameters:**

| Parameter | Type | Req? | Notes |
|---|---|---|---|
| `name` | string | required | Display name for the system user |
| `role` | enum (`SystemUser.Role`) | required | See Role enum below |
| `system_user_id` | int | optional | — |

**`SystemUser.Role` enum (SDK-confirmed):** `ADMIN`, `ADS_RIGHTS_REVIEWER`, `DEFAULT`, `DEVELOPER`,
`EMPLOYEE`, `FINANCE_ANALYST`, `FINANCE_EDIT`, `FINANCE_EDITOR`, `FINANCE_VIEW`, `MANAGE`,
`PARTNER_CENTER_ADMIN`, `PARTNER_CENTER_ANALYST`, `PARTNER_CENTER_EDUCATION`,
`PARTNER_CENTER_MARKETING`, `PARTNER_CENTER_OPERATIONS`

**Permissions:** `business_management`, called with a token from a human Admin of the Business.

**Example response:**
```json
{ "id": "100093887654321", "name": "mads-cli automation" }
```

**System User node fields:** `id`, `name`, `role`, `created_by`, `created_time`, `finance_permission`,
`ip_permission`, `system_user_id`.

Source: facebook-business SDK `facebook_business/adobjects/business.py::create_system_user`,
`facebook_business/adobjects/systemuser.py`

---

### POST /{system-user-id}/applications — Install App on System User

Before a system user can generate a token, the target app must be **installed** on it.

**Full URL:**
```
POST https://graph.facebook.com/v25.0/{system-user-id}/applications
```

**Parameters:**

| Parameter | Type | Req? | Notes |
|---|---|---|---|
| `business_app` | string (App ID) | required | The app to install |
| `access_token` | string | required | Token from a Business Manager admin, admin system user, or system user |

**Example:**
```bash
curl -F "business_app=<APP_ID>" \
     -F "access_token=<ADMIN_ACCESS_TOKEN>" \
     "https://graph.facebook.com/v25.0/<SYSTEM_USER_ID>/applications"
```

Source: https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/

---

### POST /{system-user-id}/access_tokens — Generate System User Access Token

**Full URL:**
```
POST https://graph.facebook.com/v25.0/{system-user-id}/access_tokens
```

**Parameters:**

| Parameter | Type | Req? | Notes |
|---|---|---|---|
| `business_app` | string (App ID) | required | App the token will act as |
| `scope` | string (comma-separated list of Permission) | required | e.g. `ads_management,pages_read_engagement` |
| `set_token_expires_in_60_days` | bool | optional | See "60-day vs never-expire" below |
| `appsecret_proof` | string | conditional | Required if the app has "Require App Secret" enabled |
| `access_token` | string | required | Caller's (admin) token |

**Example (60-day expiring token):**
```bash
curl -F "business_app=<APP_ID>" \
     -F "scope=ads_management,pages_read_engagement" \
     -F "set_token_expires_in_60_days=true" \
     -F "appsecret_proof=<APPSECRET_PROOF>" \
     -F "access_token=<ADMIN_ACCESS_TOKEN>" \
     "https://graph.facebook.com/v25.0/<SYSTEM_USER_ID>/access_tokens"
```

**Example response:**
```json
{ "access_token": "EAAG...", "token_type": "bearer" }
```

**Alias endpoint (business-scoped, SDK-confirmed):**
```
POST https://graph.facebook.com/v25.0/{business-id}/system_user_access_tokens
```
with body params `system_user_id` (required — which system user to mint for), `asset` (list of asset IDs
to scope the token to), `scope` (list of Permission), `set_token_expires_in_60_days` (bool), and
`fetch_only` (bool — return the existing valid token instead of minting a new one). This is the form
implemented in `facebook_business/adobjects/business.py::create_system_user_access_token`. Both this and
the `/{system-user-id}/access_tokens` form appear in official Meta material; **use the node-level
`/{system-user-id}/access_tokens` form as primary** since it's the one shown in Meta's own
"Install Apps, Generate, Refresh, and Revoke Tokens" guide.

Sources:
- https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/
- facebook-business SDK: `facebook_business/adobjects/business.py::create_system_user_access_token`

---

### 60-Day vs. Never-Expire System User Tokens

This is the single most consequential decision when minting a system user token:

| Mode | How to get it | Lifespan | Renewal required? |
|---|---|---|---|
| **Never-expire (default)** | Omit `set_token_expires_in_60_days`, or pass `false` | Does not expire | No — "one benefit of using a system user access token is that it does not expire, so it can be used in long-running scripts or services" |
| **60-day expiring** | Pass `set_token_expires_in_60_days=true` | 60 days from mint/refresh date | Yes — must call the refresh endpoint before expiry or the token is forfeited and a brand-new one must be generated |

Meta's own guide labels `set_token_expires_in_60_days=true` as **"recommended"** — i.e. Meta's current
security guidance favors the expiring form even though the never-expire form remains the API default and
remains available. No forced sunset of never-expire system-user tokens was found in any doc fetched on
2026-07-01 — **(unverified: absence of a deprecation notice is not proof one won't be announced later;
re-check `changelog` before relying on this long-term)**.

Source: https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/

---

### GET /oauth/access_token — Renew (Refresh) a 60-Day Token

**Full URL:**
```
GET https://graph.facebook.com/v25.0/oauth/access_token
    ?grant_type=fb_exchange_token
    &client_id={app-id}
    &client_secret={app-secret}
    &fb_exchange_token={current-system-user-token}
    &set_token_expires_in_60_days=true
```

**Behavior:** Returns a **new** system user access token valid for 60 days from the refresh date. The
**old token keeps working until its own original expiry** (creation date + 60 days) — refreshing does not
immediately invalidate the prior token, so overlapping rotation is safe.

**Example response:**
```json
{ "access_token": "EAAG...", "token_type": "bearer", "expires_in": 5183999 }
```

Source: https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/

---

### GET /oauth/revoke — Revoke a System User Access Token

**Full URL:**
```
GET https://graph.facebook.com/v25.0/oauth/revoke
    ?client_id={app-id}
    &client_secret={app-secret}
    &revoke_token={system-user-access-token-to-revoke}
    &access_token={caller-access-token}
```

Source: https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/

---

## Pages

### GET /{page-id} — Page Info

**Full URL:**
```
GET https://graph.facebook.com/v25.0/{page-id}?fields=id,name,about,category,category_list,fan_count,followers_count,link,phone,website,username,verification_status,is_published,is_permanently_closed,single_line_address,checkins,talking_about_count,overall_star_rating,rating_count
```

**Key fields** (SDK-confirmed, `facebook_business/adobjects/page.py::Page.Field`):

| Field | Type | Notes |
|---|---|---|
| `id` | numeric string | Page ID |
| `name` | string | Core field |
| `about` | string | Short description, ~100 chars |
| `description` | string | Longer About text |
| `category` | string | Primary category, e.g. "Product/Service" |
| `category_list` | list | Sub-categories |
| `fan_count` | uint32 | Total Page likes |
| `followers_count` | uint32 | Total followers |
| `link` | string | Page's facebook.com URL |
| `phone` | string | — |
| `website` | string | — |
| `username` | string | Page's vanity handle |
| `verification_status` | string | `blue_verified`, `gray_verified`, `not_verified` |
| `is_verified` | bool | **Deprecated** — use `verification_status` instead |
| `is_published` | bool | Visible to non-admins |
| `is_permanently_closed` | bool | Business closure flag |
| `checkins` | uint32 | — |
| `single_line_address` | string | — |
| `talking_about_count` | uint32 | "People talking about this" |
| `overall_star_rating` | float | Aggregate star rating summary field on the Page node itself |
| `rating_count` | uint32 | Count of ratings feeding the summary |
| `emails` | list<string> | Contact emails |
| `keywords` | — | Returns null (dead field) |
| `breaking_news_usage` | — | Marked deprecated |

**Important edges:** `posts`, `feed`, `insights`, `ratings` (deprecated, see below), `photos`, `videos`,
`likes`, `roles`, `albums`.

> **`overall_star_rating` and `rating_count` are still present in the field schema** (confirmed against
> the SDK's `Page.Field` enum, both typed `float`/`unsigned int` respectively) even though the underlying
> per-review `ratings` edge is deprecated (see below). Whether these two summary fields still return live,
> updating data post-deprecation, or are frozen/stale, was **not independently confirmed** in this pass —
> **(unverified)**. Do not build a "reviews" feature around them without testing live.

Sources:
- https://developers.facebook.com/docs/graph-api/reference/page/
- facebook-business SDK: `facebook_business/adobjects/page.py::Page.Field`

---

### GET /{page-id}/insights — Organic Page Insights

**Full URL:**
```
GET https://graph.facebook.com/v25.0/{page-id}/insights
    ?metric=page_impressions,page_post_engagements,page_fans,page_media_view,page_total_media_view_unique
    &period=day
    &since=2026-06-01
    &until=2026-06-30
```

**Auth:** Page access token from someone with the `ANALYZE` task on the Page. Permissions:
`read_insights` + `pages_read_engagement`.

**Parameters:**

| Parameter | Req? | Notes |
|---|---|---|
| `metric` | required | Comma-separated metric name(s) |
| `period` | conditional | `day`, `week`, `days_28`, `month`, `lifetime`, `total_over_range` — which are valid depends on the metric |
| `since` / `until` | optional | Date range; **max 90-day window per request** |

**Hard limits (doc-confirmed):**
- Requires **100+ Page likes** minimum before most metrics populate.
- Most metrics refresh **once every 24 hours**.
- Only the **last 2 years** of insights data is retained/queryable.
- Video-specific metrics only return accurate values if the caller is the actual video's Page-post creator; resharing another Page's video zeroes out several video metrics.
- Reels interactions are **not** included in these metrics.

**Current (non-deprecated) metrics you should actually use** — representative set, grouped:

| Category | Metric | Description | Period(s) |
|---|---|---|---|
| Engagement | `page_post_engagements` | Reactions + comments + shares on posts | day, week, days_28 |
| Engagement | `page_follows` | Total Page followers | day |
| Media view (**current replacement for reach**) | `page_media_view` | Times content was played/displayed | day, week, days_28 |
| Media view | `page_total_media_view_unique` | Total unique media viewers — **the current replacement for `page_impressions_unique`** | day, week, days_28 |
| Post media view | `post_media_view` / `post_total_media_view_unique` | Post-level equivalents of the above | lifetime |
| Video | `page_video_views`, `page_video_views_organic`, `page_video_views_paid` | Videos played 3+ seconds | day, week, days_28 |
| Video | `page_video_complete_views_30s*` | Videos watched 30+ seconds, several sub-breakdowns | day, week, days_28 |
| Views | `page_views_total` | Page profile views (logged in + out) | day, week, days_28 |
| Reactions | `page_actions_post_reactions_like_total` (and `_love`/`_wow`/`_haha`/`_sorry`/`_anger`) | Reaction counts by type | day, week, days_28 |
| Monetization | `content_monetization_earnings`, `monetization_approximate_earnings` | Estimated payouts | varies |

> **Correction (live-verified 2026-07-02):** this table previously also listed an "Impressions" row
> (`page_impressions`, `page_impressions_paid`, `page_impressions_viral`/`_nonviral`) and a "Demographics"
> row (`page_fans`, `page_fans_locale`, `page_fans_city`, `page_fans_country`, `page_fan_adds`,
> `page_fan_adds_unique`, `page_fan_removes`) as current/valid. All of those were **live-tested against
> the real Meta Graph API on 2026-07-02** (`GET /{page-id}/insights?metric=...` against Page
> `106391075531104`, using a proper Page Access Token — see the Gotcha below — so this is not a
> Page-Access-Token-vs-user-token confusion) and **every one of them returned error `(#100) The value
> must be a valid insights metric`**, distinct from the "empty `data: []`, no error" shape that a
> genuinely-valid-but-quiet metric returns. They are removed from the table above. This document's own
> 2026-07-01 fetch date did not catch this — either the doc page itself lagged the actual API behavior
> by a day, or the doc's "current metrics" listing was already stale when originally captured. Treat the
> table above, not the original developer docs page, as the ground truth until re-verified.

**DEPRECATED as of June 15, 2026 (already in effect — do not use, will error on every API version):**

| Deprecated metric | Replacement |
|---|---|
| `page_impressions_unique` | `page_total_media_view_unique` |
| `page_posts_impressions_unique`, `page_posts_impressions_organic_unique`, `page_posts_impressions_nonviral_unique` | `post_total_media_view_unique` |
| `post_impressions`, `post_impressions_unique`, `post_impressions_fan_unique`, `post_impressions_organic_unique`, `post_impressions_nonviral_unique` | `post_media_view` / `post_total_media_view_unique` |
| `page_video_views_unique`, `post_video_views_unique` | `page_total_media_view_unique` / `post_total_media_view_unique` |
| `page_video_views_10s*` and `post_video_views_10s*` (all sub-breakdowns) | No 1:1 replacement documented — use the 3s (`page_video_views`) or 30s (`page_video_complete_views_30s`) tiers |
| `page_impressions` (confirmed dead **live**, 2026-07-02 — not in Meta's originally-published June 15 list) | `page_media_view` (same impression→media-view semantic shift as `page_impressions_unique` above) |

Per the docs verbatim: *"By June 15, 2026, a number of the Page Insights metrics will be deprecated for
all API versions"* — and this date **already moved up once**, from an originally-announced June 30, 2026
date, to June 15, 2026. Third-party trackers (Supermetrics, Sprout Social, Emplifi) independently confirm
the June 15, 2026 live date. **Because today is 2026-07-01, this is not a future warning — any code still
requesting the deprecated metrics above is broken right now.**

**Additional metrics confirmed dead by LIVE testing on 2026-07-02, with no replacement metric confirmed
(not documented in Meta's June 15, 2026 changelog wave, and no evidence a like-for-like replacement
exists — do not guess one):**

| Dead metric | Notes |
|---|---|
| `page_fans` | Legacy "Page likes" count; no confirmed current equivalent — `page_follows` (Engagement table above) is the closest modern analog but this is **not** a confirmed 1:1 replacement. |
| `page_fan_adds`, `page_fan_adds_unique`, `page_fan_removes` | Like/unlike deltas — dead alongside `page_fans` above. |
| `page_fans_locale`, `page_fans_city`, `page_fans_country` | Likers demographic breakdowns — dead alongside `page_fans` above. |
| `page_impressions_paid`, `page_impressions_viral`, `page_impressions_nonviral` | Dead alongside plain `page_impressions` above; no paid/viral-split equivalent of `page_media_view` found live. |
| `page_engaged_users` | Predates the June 2026 wave entirely — this is a pre-2018-era Insights metric name, already dead independent of the other deprecations here. |

`mads-cli`'s `mads_lib/pages.py` pre-flight-rejects every metric in both tables above (VALIDATION exit
code) before sending the request to the API, rather than letting the call fail opaquely — see
`DEPRECATED_METRIC_REPLACEMENTS` and `CONFIRMED_DEAD_NO_REPLACEMENT` in that file.

The underlying semantic shift: the old "impression" event (content delivered to a feed) is being replaced
everywhere by a "media view" event (content actually visually rendered). Both count unique users, but
`page_total_media_view_unique` will typically read **lower** than the old `page_impressions_unique` did,
because a view is a stricter (more selective) signal than a delivered impression.

**v26.0 outlook:** the v25.0 changelog additionally warns that "page reach, page post reach, video
impressions, and story impressions metrics" are slated for further deprecation "when v26.0 releases" —
i.e. this is a two-wave rollout and more reach-family metrics will break once v26.0 ships.

Sources:
- https://developers.facebook.com/docs/graph-api/reference/page/insights/
- https://developers.facebook.com/docs/graph-api/changelog/version25.0/
- https://docs.supermetrics.com/docs/facebook-insights-field-changes-june-30-2026

---

### GET /{page-id}/ratings — Page Reviews & Recommendations — **DEPRECATED**

> **This entire surface is dead. Do not implement a "reply to review" feature for Meta — it never existed
> to begin with, and reading reviews is now also blocked.**

**What changed and when:** Effective **for v22.0 and all future versions**, per the v22.0 changelog
(released January 21, 2025): *"Page recommendations have been deprecated for v22.0 and future versions.
Attempting to read a recommendation, or get recommendations on a page, will return error code `12`."*
Separately, this restriction was extended to apply **regardless of API version** starting
**September 9, 2025** — the same date Meta cut off all calls to pre-v22.0 versions. From that date forward,
`GET /{page-id}/ratings` and `GET /{recommendation-id}` return error code `12` **no matter which Graph API
version you call them with**, and **Page ratings webhooks stopped being sent entirely.**

**Full URL (now non-functional for its original purpose):**
```
GET https://graph.facebook.com/v25.0/{page-id}/ratings
```

**HTTP methods:**
- `GET` — the only method ever supported; now returns error 12 for reading recommendation data.
- `POST` / `DELETE` — never supported on this edge ("You can't perform this operation on this endpoint").

**Permissions still enforced by the endpoint** (even though it's functionally dead): a Page access token
from someone with `CREATE_CONTENT`, `MANAGE`, or `MODERATE` capability, plus `pages_read_user_content`.
Missing these still surfaces error 283 ("missing required extended permissions") *before* you'd even get
to the error-12 deprecation response.

**Recommendation node fields (still defined in the schema, unreachable in practice):** `created_time`,
`has_rating` (bool), `has_review` (bool), `open_graph_story`, `rating` (int32, 1–5), `recommendation_type`
(`positive`/`negative`), `review_text` (string), `reviewer` (User).

**Was there ever a "reply to review" capability?** **No.** Unlike Google Business Profile's
`accounts.locations.reviews.updateReply` (a dedicated, documented reply endpoint that is still active —
see `gbp.md`), the Graph API **never shipped a first-class endpoint to reply to a Page recommendation or
rating.** The only historical workaround developers found was posting to the generic `/comments` edge
against a review's object ID — and that workaround was itself already broken by Facebook's deprecation of
the "singular statuses API" back in **API version v2.4** (i.e. it stopped working circa 2015/2016, a
decade before the ratings-read deprecation above). A live developer-community thread from 2026 confirms
this exact failure mode: attempting `POST /{review-id}/comments` today returns
`"(#12) singular statuses API is deprecated for versions v2.4 and higher"` — the same error code 12,
for an entirely different, much older reason. Net effect: **there is no path, past or present, to
programmatically reply to a Facebook Page review/recommendation.**

Sources:
- https://developers.facebook.com/docs/graph-api/changelog/version22.0/
- https://developers.facebook.com/docs/graph-api/reference/page/ratings/
- https://developers.facebook.com/docs/graph-api/reference/recommendation/
- https://developers.facebook.com/community/threads/368009610930042/ (community thread confirming the reply workaround has been dead since v2.4)

---

## Ad-Account Webhooks

Meta's Webhooks product lets an app subscribe to real-time server-to-server notifications about an ad
account. The **`ad_account`** webhook object exposes **5 subscribable trigger fields** per Meta's own
"Webhooks for Ad Accounts" getting-started guide (fetched with a live v25.0-versioned example URL,
confirming currency as of today):

### The 5 Trigger Fields

| # | Field | Fires when | `value` payload schema |
|---|---|---|---|
| 1 | `with_issues_ad_objects` | A campaign, ad set, or ad under the account changes to the `WITH_ISSUES` status | `id` (numeric string), `level` (string: `CREATIVE`/`AD`/`AD_SET`/`CAMPAIGN`), `error_code` (numeric string), `error_summary` (string), `error_message` (string) |
| 2 | `in_process_ad_objects` | A campaign, ad set, or ad finishes processing and exits the `IN_PROCESS` status | `id` (numeric string), `level` (string), `status_name` (string) |
| 3 | `ad_recommendations` | Meta generates a recommendation for one of the account's ads | `ad_account_id` (numeric string), `ad_object_ids` (list<numeric string>), `recommendation_type` (enum), `recommendation_signature` (string), `recommendation_message` (string), `recommendation_stage` (string), `recommendation_hash` (string) |
| 4 | `creative_fatigue` | An ad enters or exits creative fatigue (with granularity `Low`/`Medium`/`High`) | `ad_account_id` (numeric string), `adgroup_id` (numeric string), `creative_fatigue_level` (string), `creative_fatigue_message` (string) |
| 5 | `product_set_issue` | A product set (catalog) encounters an issue affecting the account's ads | `ad_account_id` (numeric string), `product_set_id` (numeric string), `type` (enum), `description` (string), `recommended_action` (string) |

**Example payload for `with_issues_ad_objects`** (from the official doc):
```json
{
  "object": "ad_account",
  "entry": [
    {
      "id": "0",
      "time": 1568132516,
      "changes": [
        {
          "field": "with_issues_ad_objects",
          "value": {
            "id": "111111111111",
            "level": "AD",
            "error_code": "567",
            "error_summary": "error summary",
            "error_message": "error message"
          }
        }
      ]
    }
  ]
}
```

> **A 6th field exists on the full Webhooks Reference page but is NOT part of the "5" documented in the
> getting-started guide:** `ads_async_creation_request` (schema: `status` enum, `result` object,
> `result_id` numeric string, `error_code` uint32, `error_message` string) — fires for async batch ad
> creation job status. It is real and doc-confirmed on the reference page, but it is a newer/separate
> addition covering a different use case (async job completion, not account health). **Implement the 5
> above as the primary/expected set; treat `ads_async_creation_request` as an optional 6th if the CLI ever
> needs async-creation-job callbacks.**

### Subscribing an Ad Account to Webhooks

1. In the App Dashboard, add the **Webhooks** product, select **Ad Account** as the object type, and
   configure/verify your callback URL (standard Webhooks Getting Started flow — endpoint must respond to
   Meta's verification `hub.challenge` handshake).
2. Ensure the calling token has **edit permission on the ad account** plus the **`ads_management`**
   permission.
3. Subscribe the specific ad account to your app:

```bash
curl -X POST \
  -d "access_token=<ACCESS_TOKEN>" \
  -d "app_id=<APP_ID>" \
  "https://graph.facebook.com/v25.0/act_<AD_ACCOUNT_ID>/subscribed_apps"
```

**Success response:**
```json
{"success": "true"}
```

4. Verify with a `GET` on the same endpoint — the app should appear in the ad account's subscribed-apps
   list.

Sources:
- https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-ad-accounts/ (the 5-field getting-started guide)
- https://developers.facebook.com/docs/graph-api/webhooks/reference/ad-account/ (full reference page — 6 fields including `ads_async_creation_request`)

---

## `appsecret_proof` Computation

`appsecret_proof` is a per-request HMAC signature that proves a server-side call was made by someone who
actually holds the app secret, not just the access token.

**Formula:**
```
appsecret_proof = HMAC-SHA256(key = app_secret, message = access_token) → hex digest
```

**PHP (from the official doc):**
```php
$appsecret_proof = hash_hmac('sha256', $access_token, $app_secret);
```

**Python equivalent:**
```python
import hmac
import hashlib

def appsecret_proof(access_token: str, app_secret: str) -> str:
    return hmac.new(
        app_secret.encode("utf-8"),
        access_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
```

**Usage:** add `appsecret_proof` as an extra query/form parameter on every Graph API call alongside
`access_token`. The official PHP SDK adds it automatically; the Python SDK does **not** do this for you
transparently in all call paths — compute and pass it explicitly in `mads-cli`.

**When it becomes mandatory:** App Dashboard → **App Settings → Advanced → Security → "Require App
Secret"**. Once toggled on, *"all client-initiated calls must be proxied through your backend where the
`appsecret_proof` parameter can be added to the request before sending it to the Graph API, or the call
will fail."* This means once enabled, **no client-side (mobile/JS SDK) call can succeed directly** —
everything must be proxied server-side where the secret can be safely used to compute the proof.

**Failure mode when required but missing/wrong:** Graph API returns an OAuth-class error with the message
*"Invalid appsecret_proof provided in the API argument"* (widely reported against the archived PHP SDK
issue tracker). The exact numeric error code was **not confirmed** in a single canonical doc during this
pass — **(unverified: treat any exact numeric code you see in the wild as SDK/library-reported, not
independently Meta-doc-confirmed here)**.

Sources:
- https://developers.facebook.com/docs/graph-api/securing-requests

---

## Gotchas

1. **Two documented endpoints exist for minting a system-user token** — `/{system-user-id}/access_tokens`
   (official guide) and `/{business-id}/system_user_access_tokens` (SDK). Prefer the first; the second is
   real but only confirmed via SDK source in this pass, not an independent doc page.

2. **Never-expire is still the API default for system-user tokens.** `set_token_expires_in_60_days` is
   opt-in, not opt-out. If you don't see it in your mint call, you got a never-expiring token — confirm
   this is what you intended before shipping to production, since Meta's own docs now *recommend* the
   60-day form for security even though it's not required.

3. **`error code 12` means two completely different things depending on the endpoint.** On
   `/{page-id}/ratings` and `/{recommendation-id}`, it means "this whole feature is deprecated, doesn't
   matter what version you call." On `/{review-id}/comments`, the same code 12 means "the singular
   statuses API died in v2.4" — a decade-old, unrelated deprecation. Don't assume error 12 always means
   "reviews are dead" — read the accompanying message string.

4. **`rating_count` / `overall_star_rating` remain in the Page node schema** even though the `ratings`
   edge (individual review objects) is dead. Do not build a UI that assumes these two summary numbers are
   still live and accurate without testing — **(unverified)** whether they still update.

5. **Page Insights "unique" metrics broke on June 15, 2026 — 2 weeks before today.** If `mads-cli`'s
   `fetch_daily.py`-equivalent for Meta ever requested `page_impressions_unique`,
   `page_posts_impressions_unique`, `post_impressions_unique`, or any `*_video_views_unique` /
   `*_10s*` metric, it started failing on that date. Migrate to `page_total_media_view_unique` /
   `post_total_media_view_unique`.

6. **v26.0 will break more reach metrics.** The v25.0 changelog already telegraphs that page/post reach,
   video impressions, and story impressions will be deprecated further "when v26.0 releases" — budget for
   a second migration wave once that version ships.

7. **Ad-account webhooks require a live ad-account-level subscription, not just an app-level Webhooks
   product config.** Adding the Webhooks product and picking "Ad Account" as object type in the dashboard
   is necessary but not sufficient — you must also `POST /act_{id}/subscribed_apps` per ad account you
   want notifications for.

8. **`appsecret_proof` is silently optional until "Require App Secret" is flipped on** — meaning code that
   works fine in dev (secret requirement off) can start failing in prod the moment someone enables that
   toggle in App Dashboard settings. Compute and send it unconditionally to avoid this class of surprise.

9. **The Business Manager creation guide explicitly warns Business Managers cannot be deleted once
   created.** Do not script test/throwaway Business creation without a real cleanup plan — there isn't
   one via the API.

10. **`/oauth/revoke` and `/oauth/access_token` are top-level OAuth endpoints, not System-User-node
    edges** — don't accidentally construct them as `/{system-user-id}/oauth/revoke`; they hang directly
    off the API root.

11. **`AdsPixel.owner_ad_account` can point to an ad account entirely outside the caller's Business
    Manager, and expanding it then fails the WHOLE request with `(#200) Ad account owner has NOT grant
    ads_management or ads_read permission`** — even though every other field on the same pixel resolves
    fine and the caller has full `DRAFT/ANALYZE/ADVERTISE/MANAGE` tasks on the ad account being queried.
    Root-caused live 2026-07-02 against App ID `1332295765705902` / Business `1183781372354749` / ad
    account `act_565243822008153`:
    - `mads capi list-pixels --json` (requesting the full `DEFAULT_PIXEL_FIELDS` set, which included
      `owner_ad_account`) failed with error 200 as above.
    - Bisecting field-by-field (`GET act_565243822008153/adspixels?fields=id,name,<one field>` for each
      of `creation_time`, `is_consolidated_container`, `last_fired_time`, `match_rate_approx`,
      `owner_business`, `data_use_setting`) showed **only `owner_ad_account` fails** — every other field,
      including the structurally similar `owner_business`, returns cleanly.
    - The failure reproduces identically querying the pixel by its bare numeric ID
      (`GET /3192549394396428?fields=owner_ad_account`) and via the Business-scoped path
      (`GET /1183781372354749/adspixels?fields=owner_ad_account`) — it is not specific to one node path.
    - It reproduces on **both** pixels in the account: the Shopify-channel-created one
      (`3192549394396428`, "Ads Pixel for Shopify Facebook Ad") and the natively-created one
      (`1081436410576446`, "Talas Auto Spare Parts Trading's pixel") — so it is not a Shopify-specific
      quirk, just a "foreign owning ad account" quirk that happened to affect both pixels here.
    - Confirmed the caller has full `['DRAFT', 'ANALYZE', 'ADVERTISE', 'MANAGE']` tasks on
      `act_565243822008153` via `GET act_565243822008153/assigned_users?business=1183781372354749`, and
      `GET me/adaccounts` lists 7 total ad accounts visible to this user (1 full-access, 4 with only the
      `ANALYZE` task, 2 with zero `assigned_users` entries) — none of which directly own either pixel
      per `GET act_<id>/adspixels` returning `{"data": []}` for all of them. The pixels' true
      `owner_ad_account` is therefore an ad account that never appears anywhere in this
      user's/Business's visible asset graph — Meta enforces the field-level permission check against
      that real (foreign) owner, not against the account/edge you queried through.
    - **This is a client-side default-fields bug, not a grantable Business Manager asset-permission
      gap** — there is no `assigned_users` action that fixes it, because the account that would need to
      grant access isn't one the caller (or the Business) administers at all. `mads-cli` fixed this by
      dropping `owner_ad_account` from `capi.py`'s `DEFAULT_PIXEL_FIELDS`; callers who need it for a
      *known-good, same-Business* pixel can still request it explicitly via `--fields`.

12. **`GET /{page-id}/insights` requires a Page Access Token — the general user/system-user token gets
    you error 190, `"This method must be called with a Page Access Token"`.** This is a *different*
    meaning of error 190 than its far more common "expired/invalid token" meaning (see
    `mads_lib/http.py::_ERROR_CODE_MAP`, which maps 190 → `AUTH` either way — the distinction only shows
    up in the error `message` string). `GET /{page-id}` (Page profile info) does **not** need a Page
    token — only page-scoped edges like `/insights` do.

    A Page Access Token is obtained via `GET /me/accounts` (or `GET /{user-id}/accounts`), authenticated
    with the *user* token, which returns each managed Page's `id`, `name`, and a page-scoped
    `access_token`. Confirmed live 2026-07-02 against Page `106391075531104` ("Talas Tesla Auto Parts")
    using the project's user token (scopes `ads_management, ads_read, business_management,
    pages_read_engagement, pages_show_list`) — the call succeeded and returned a distinct page-scoped
    token with the `ANALYZE` task present (required for Insights reads).

    **Lifetime of the returned Page Access Token:** confirmed live via `GET /debug_token` against the
    freshly-issued Page token — response showed `expires_at: 0` (Meta's convention for "does not
    expire"), **even though** the parent user token it was derived from is itself a 60-day token with a
    real, non-zero expiry. A Page Access Token minted from a valid "Login for Business" user token gets
    its own long-lived/non-expiring lifetime, independent of that parent token's remaining life. This is
    why caching it to disk (rather than re-fetching on every single Page-scoped call) is correct.

    **How `mads-cli` handles this:** `mads_lib/auth.py::get_page_access_token(page_id)` fetches a Page
    Access Token via `GET /me/accounts` on first use and caches it to
    `credentials/meta-page-tokens.json` (gitignored, override path via `MADS_PAGE_TOKENS_PATH`) as a
    flat `{page_id: access_token}` map — every Page returned by that call is cached in the same pass,
    not just the one requested. `mads_lib/pages.py::page_insights` uses this Page token instead of the
    general one; `page_insights` also retries exactly once with a freshly-fetched token
    (`force_refresh=True`) if a cache hit still comes back with a 190/AUTH error (covers the
    out-of-band-invalidation case: password change, app deauthorization, or the granting user's
    `pages_show_list`/`pages_read_engagement` scope being revoked). `page_info` deliberately keeps using
    the general token — it was never broken and doesn't need this.

---

## Sources

All claims in this document were verified via `WebFetch`/`WebSearch` against `developers.facebook.com`
and cross-checked against the `facebook/facebook-python-business-sdk` GitHub source, fetched/queried on
2026-07-01:

- https://developers.facebook.com/docs/graph-api/changelog — confirms v25.0 is current
- https://developers.facebook.com/docs/graph-api/changelog/versions/ — version release/expiration table
- https://developers.facebook.com/docs/graph-api/changelog/version25.0/ — v25.0 release notes, Insights deprecation warnings
- https://developers.facebook.com/docs/graph-api/changelog/version22.0/ — Page ratings/recommendations deprecation (error 12)
- https://developers.facebook.com/docs/graph-api/guides/versioning/ — 2-year version lifespan policy
- https://developers.facebook.com/docs/marketing-api/business-manager-api/get-started — Business creation endpoint/params
- https://developers.facebook.com/docs/graph-api/reference/business/ — Business node overview
- https://developers.facebook.com/docs/marketing-api/business-asset-management/guides/system-users — System Users guide
- https://developers.facebook.com/docs/business-management-apis/system-users/install-apps-and-generate-tokens/ — install/generate/refresh/revoke token workflow
- https://developers.facebook.com/docs/graph-api/reference/page/ — Page node fields
- https://developers.facebook.com/docs/graph-api/reference/page/insights/ — Page Insights metrics + deprecation list
- https://developers.facebook.com/docs/graph-api/reference/page/ratings/ — Reviews/recommendations edge, now-dead
- https://developers.facebook.com/docs/graph-api/reference/recommendation/ — Recommendation node fields + deprecation notice
- https://developers.facebook.com/community/threads/368009610930042/ — confirms no reply-to-review capability ever existed (v2.4-era deprecation of the workaround)
- https://developers.facebook.com/docs/graph-api/webhooks/getting-started/webhooks-for-ad-accounts/ — the 5 ad_account webhook trigger fields + subscription flow
- https://developers.facebook.com/docs/graph-api/webhooks/reference/ad-account/ — full 6-field webhook reference (5 + `ads_async_creation_request`)
- https://developers.facebook.com/docs/graph-api/securing-requests — `appsecret_proof` formula and requirement toggle
- https://docs.supermetrics.com/docs/facebook-insights-field-changes-june-30-2026 — third-party corroboration of the June 15, 2026 Insights deprecation date
- GitHub `facebook/facebook-python-business-sdk` (`main` branch), files: `facebook_business/adobjects/business.py`, `facebook_business/adobjects/systemuser.py`, `facebook_business/adobjects/page.py`, `facebook_business/adobjects/user.py` — field-name and endpoint cross-checks
