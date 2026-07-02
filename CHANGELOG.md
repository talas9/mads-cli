# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-07-02

### Added

- **New `mads whatsapp` command group (`mads_lib/whatsapp.py`) — WhatsApp Business Platform
  (Cloud API) support, a SEPARATE Meta product from the Marketing/Graph API surface the rest of
  this CLI covers:**
  - `whatsapp waba info` / `waba phone-numbers` — WABA details and registered phone numbers
  - `whatsapp phone-number info` — phone number details/status (quality rating, verification,
    throughput)
  - `whatsapp template list` / `template create` — message template listing + submission
    (AUTHENTICATION/MARKETING/UTILITY categories)
  - `whatsapp send` — template send (default) or free-form session-message send (requires
    `--confirm-24h-window`, since Cloud API only allows free-form messages inside the 24h
    customer-service window and this CLI cannot verify window state client-side)
  - `whatsapp webhook subscribe` — app-level WABA webhook subscription (App Access Token,
    distinct from `mads_lib/webhooks.py`'s ad-account subscription)
  - Requires `META_WABA_ID` (or `--waba-id`) — **no WhatsApp Business Account is onboarded for
    Talas yet**; every WABA-dependent command fails gracefully with a VALIDATION error rather
    than crashing. See `kb/whatsapp-business-platform.md` for the full onboarding prerequisite
    and the 24h-window / pricing-model context.
  - **34 new offline pytest tests** (`tests/test_whatsapp.py`): Click-tree registration + `--help`
    exit-code checks, missing-WABA graceful failures, template/send validation (invalid JSON,
    invalid category, mutually-exclusive `--template-name`/`--text`), `--dry-run` never touching
    the network, and webhook subscribe success/failure paths.

- **Instagram creative attribution** — `creative create --instagram-user-id` sets
  `object_story_spec.instagram_user_id` so a creative can be attributed to a specific Instagram
  Business Account (`mads_lib/creatives.py`).

- **Instagram/placement adset targeting flags** — `adset create --publisher-platforms` (e.g.
  `facebook,instagram`) and `--instagram-positions` (e.g. `stream,story,reels`) populate
  `targeting.publisher_platforms` / `targeting.instagram_positions` (`mads_lib/adsets.py`). Raw
  `--targeting` JSON still overrides these flags when both are supplied.

- **`audience`, `commerce`, `capi`, and `analyze` resource groups wired into the CLI**
  (`mads_lib/cli.py`) — previously library-only functions in `audiences.py`/`commerce.py`/
  `capi.py`/`analyze/*.py` are now full Click command groups: `audience list/create/
  create-lookalike/upload-users/delete`, `commerce create-catalog/create-feed/upload-feed/
  create-product/list-products/batch-update/batch-status`, `capi create-pixel/create-dataset/
  list-pixels/send-event/test-event/hash-user-data`, `analyze audit/budget-pacing/
  creative-fatigue/audience-overlap/placement-breakdown`. Hardened error handling across these
  groups (structured VALIDATION errors on bad input instead of raw tracebacks).

### Fixed

- **`page insights` now uses a Page Access Token instead of the general user/system-user
  token.** Meta returns error 190 ("This method must be called with a Page Access Token") for
  Page-level Insights edges — the general token never worked for this call. `mads_lib/pages.py`
  now fetches and caches a Page Access Token via `GET /me/accounts` (`auth.py::
  get_page_access_token()`, cached at `MADS_PAGE_TOKENS_PATH`, default
  `credentials/meta-page-tokens.json`), with a one-shot retry-with-fresh-token on auth failure
  and pre-flight rejection of metrics confirmed dead as of 2026-06-15 (`page_impressions_unique`,
  `post_impressions`, the `*_video_views_10s*` family) with a VALIDATION error naming the
  replacement metric.
- **CAPI: dropped `owner_ad_account` from `DEFAULT_PIXEL_FIELDS`.** Requesting this field
  expansion on `capi list-pixels` failed the entire call with `(#200) Ad account owner has NOT
  grant ads_management or ads_read permission` for pixels created via a third-party channel
  (e.g. Shopify's Facebook & Instagram sales channel) whose owning ad account sits outside the
  caller's Business Manager — even though every other field (including `owner_business`)
  resolved fine. Callers who need `owner_ad_account` for a specific known-good pixel can still
  request it explicitly via `--fields`.
- **`catalog_management` app-approval gap documented, not silently swallowed.** `commerce`
  catalog commands fail with `(#100) This application has not been approved to use this api`
  because the app was never granted the `catalog_management` permission (confirmed via
  `GET /me/permissions`). The scope is now prepared (commented out, ready to uncomment once App
  Review grants it) in `generate_token.py`, and the full root cause + remediation steps are
  documented in `kb/commerce-catalog.md` Gotchas #13 and `AGENTS.md` Known Gotchas.
- **`.gitignore` was silently ignoring `kb/manifest.json`** — the blanket `*.json` rule caught
  it despite the `!pyproject.toml` exception, so KB drift-tracking metadata was never actually
  committed. Added `!kb/manifest.json` alongside the existing `pyproject.toml` exception.

### Changed

- Test suite expanded from 129 (`tests/test_mads.py` only) to **163 tests**
  (`tests/test_mads.py` + new `tests/test_whatsapp.py`), all offline/mocked, no live API calls.
- `kb/manifest.json` — added the `whatsapp-business-platform` entry (5th tracked API), status
  flagged `"active — NOT YET ONBOARDED for Talas"`.
- New KB file: `kb/whatsapp-business-platform.md`.
- `generate_token.py` `SCOPES` — added commented-out `whatsapp_business_management` /
  `whatsapp_business_messaging` entries (not requested yet; no WABA onboarded).

## [0.1.0] - 2026-07-01

### Added

- **Initial `mads-cli` release** — a Meta (Facebook/Instagram) Ads CLI, architected as the sibling
  to `gads-cli` (Google Ads): same scope-aware config, output contract, structured error envelope,
  and `snapshot → mutate → log` mutation discipline.

- **Core commands** (`mads_lib/cli.py`): `query` (generic Graph API GET builder — Meta has no
  GAQL equivalent), `doctor` (readiness check incl. `sibling_cli` detection of `gads` on PATH),
  `log`, `snapshot`, `mutate`, `batch-mutate` (escape hatches, 50-op hard limit enforced
  client-side), `catalog --json` (live Click-tree manifest), `db` (SELECT-only history-DB
  passthrough), `changelog`, `decisions`, `milestones`.

- **9 resource command groups (59 commands total, verified via live Click-tree walk):**
  - `campaign` — list/create/status/budget/delete (`mads_lib/campaigns.py`)
  - `adset` — list/create/status/budget/delete, targeting (countries/age), pixel/custom-event
    promoted object (`mads_lib/adsets.py`)
  - `ad` — list/create/status/budget/delete, creative attach by id or inline spec
    (`mads_lib/ads.py`)
  - `creative` — create/upload-image/upload-video (`mads_lib/creatives.py`)
  - `insights` — campaign/adset/ad (sync) + async-submit/async-status/async-fetch (long-running
    report jobs) (`mads_lib/insights.py`)
  - `abtest` — create/list/status (Ad Studies / split tests) (`mads_lib/abtest.py`)
  - `business` — info/adaccounts/pages/users + `system-user create/list` + `token generate/renew`
    (Business Manager) (`mads_lib/business.py`)
  - `page` — info/insights only — **no reviews command**, by design (`mads_lib/pages.py`)
  - `webhook` — subscribe/list/unsubscribe — **5 fixed trigger fields only**, by design
    (`mads_lib/webhooks.py`)
  - `auth` — status/login/revoke/test + `system-user create/list` + `token generate/renew`
    (mirrors `business system-user`/`business token` as a second entry point to the same
    Business Manager endpoints)

- **Shared infrastructure** (mirroring gads-cli module-for-module): `config.py` (scope detection:
  `MADS_PROJECT_ROOT` → CWD heuristics → `~/.config/mads/`), `auth.py` (bearer-token loading +
  `appsecret_proof` HMAC-SHA256 computation), `http.py` (`graph_request()`/`batch_request()` +
  `classify_meta_error()` mapping Meta's numeric error codes to exit codes), `db.py`/`dbread.py`
  (SQLite connection + SELECT-only guard), `output.py` (table/JSON formatters, `EXIT_CODES` — 0-7
  shared with gads-cli plus mads-specific `RATE_LIMIT=8`), `timeutil.py`, `catalog.py`.

- **`RATE_LIMIT=8` exit code** — mads-specific, does not exist in gads-cli. Maps Meta's explicit
  rate-limit error codes (4, 17, 32, 613, 80004) to a distinct exit code so callers back off and
  retry instead of treating rate limits as generic API failures.

- **Library-only modules** (functions exist, not yet wired to Click commands): `audiences.py`
  (Custom/Lookalike Audience list/create/upload/delete), `commerce.py` (Catalog/Product Feed
  create/upload/list/batch-update), `capi.py` (Conversions API pixel/dataset creation + event
  send/test with SHA-256 PII hashing), `analyze/` (5 modules: `audit`, `budget_pacing`,
  `creative_fatigue`, `audience_overlap`, `placement_breakdown` — analysis functions with
  `render_*()` output helpers, no CLI group yet).

- **`generate_token.py`** — standalone OAuth "Login for Business" flow: opens the Facebook OAuth
  dialog, catches the redirect on a local callback server, exchanges the code for a short-lived
  token, then exchanges that for a long-lived (~60 day) token via `fb_exchange_token`. Requests
  scopes `ads_management`, `business_management`, `pages_read_engagement`,
  `pages_manage_metadata`.

- **Knowledge base** (`kb/`): `marketing-api.md`, `graph-api.md`, `conversions-api.md`,
  `commerce-catalog.md` plus `INDEX.md` and `manifest.json` — documentation-sourced reference for
  every Meta API the CLI talks to, each citing source URLs and flagging unverified claims. All
  four APIs confirmed on Meta API `v25.0` (released 2026-02-18) via both the official changelog
  and the live `facebook-python-business-sdk` `apiconfig.py`.

- **Test suite** (`tests/test_mads.py`) — 96 tests, all offline/mocked (no live API calls):
  Click-tree registration and `--help` exit-code checks for every group/subcommand, `catalog
  --json` shape assertions, `doctor --json` shape + `sibling_cli` detection (with/without `gads`
  on PATH), SELECT-only SQL guard, and `classify_meta_error()` / `graph_request()` error-envelope
  and rate-limit-classification coverage (mocked HTTP, no network).

- **Documentation tier** (mirroring gads-cli's proven structure): `AGENTS.md` (command taxonomy,
  output contract, exit codes, mutation discipline, Known Gotchas, sister-tool pointer),
  `CLAUDE.md` (`@AGENTS.md`), `README.md` (install, quickstart, full command reference,
  configuration table, architecture diagram, sister-tool section), `llms.txt` (ultra-terse
  LLM quick-reference), `scripts/install.sh` (interactive installer: clone/pull, pip deps,
  Claude Code/gsd/**Codex** platform detection, agent + skill file writing, `mads auth setup`,
  plus sibling-awareness of `gads-cli`).

### Known Gotchas (see AGENTS.md for full detail)

- Page reviews/reply-review: permanently dead on every Graph API version (error code 12); no
  reply-to-review endpoint has ever existed. Not implemented, and should not be.
- Webhooks: 5 fixed trigger fields only (`with_issues_ad_objects`, `in_process_ad_objects`,
  `ad_recommendations`, `creative_fatigue`, `product_set_issue`) — not general change-detection.
- Batch mutate: Meta's hard 50-operation limit enforced client-side.
- Every authenticated Graph API call requires `appsecret_proof`; `META_APP_SECRET` must be set.
