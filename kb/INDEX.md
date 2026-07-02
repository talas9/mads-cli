# mads CLI — External API Knowledge Base

Documentation-sourced reference for every external Meta (Facebook/Instagram) API the `mads` CLI
talks to. Each KB file is built from **official developers.facebook.com docs and the
`facebook-python-business-sdk` GitHub source, fetched 2026-07-01** (not training memory); every
endpoint/version/claim cites a source URL, and anything that couldn't be doc-verified is marked
`(unverified)`.

Machine-readable summary: [`manifest.json`](./manifest.json).

## APIs

| # | API | KB file | Current version | Status / key sunset |
|---|-----|---------|-----------------|----------------------|
| 1 | **Meta Marketing API** (Campaigns, Ad Sets, Ads, Creatives, Audiences, Ad Studies) | [marketing-api.md](./marketing-api.md) | v25.0 (released 2026-02-18) | Active. Per-version expiration is **TBD** (not yet announced); rough unverified estimate ~March 2027 based on historical pattern. No v26.0 shipped as of 2026-07-01 (expected ~Sept 2026 per Meta's own blog). |
| 2 | **Meta Graph API** (Business Manager, System Users, Pages, Webhooks) | [graph-api.md](./graph-api.md) | v25.0 (released 2026-02-18) | Active. No sunset announced for v25.0. Distinct dated deprecations inside the file: Page ratings/recommendations dead since 2025-09-09; Page/Post "unique" reach Insights metrics deprecated 2026-06-15 (already live); v19.0 deprecates 2026-05-21; v20.0 deprecates 2026-09-24; all versions older than v22.0 already uncallable since 2025-09-09. |
| 3 | **Meta Conversions API** (server-side events, Pixel/Dataset management, Dataset Quality) | [conversions-api.md](./conversions-api.md) | v25.0 (released 2026-02-18) | Active. Conversions API carries its own 2-year minimum support guarantee independent of standard Graph API version sunset cycles. No hard shutdown date found for the legacy Offline Conversions API (still functional for existing legacy integrations). |
| 4 | **Meta Commerce Manager — Catalog & Product API** | [commerce-catalog.md](./commerce-catalog.md) | v25.0 (released 2026-02-18) | Active. Note: Marketing API has its **own shorter version-expiration clock** than general Graph API (e.g. Marketing API v23.0 already expired 2026-06-09 while Graph API v23.0 shows TBD) — easy to miss. |

## OAuth scopes at a glance

| API | Scope(s) |
|-----|----------|
| Marketing API | `ads_management` (write), `ads_read` (read-only), `business_management` (Business-level resources) |
| Graph API | `business_management`, `ads_management`, `ads_read`, `pages_show_list`, `pages_read_engagement`, `pages_read_user_content`, `pages_manage_metadata`, `read_insights` |
| Conversions API | No classic OAuth-scope model for core event-send (uses a Pixel access token minted in Events Manager, no App Review needed); Dataset Quality API needs `ads_read` + (`ads_management` or `business_management`) |
| Commerce Catalog | `catalog_management` (requires `business_management` already granted) |

All four APIs share a single host and version segment: `https://graph.facebook.com/{version}/...`
(the Marketing/Conversions/Commerce APIs are Marketing-API edges layered on top of the same Graph
API host, not separate hosts like Google's per-API subdomains).

## Notes on verification

- **Version cross-check:** all four files independently confirm `v25.0` as current via two sources
  — the official `developers.facebook.com/docs/graph-api/changelog/versions/` table and the live
  `facebook-python-business-sdk` (`main` branch) `apiconfig.py`, which is pinned to
  `API_VERSION: 'v25.0'` / `SDK_VERSION: 'v25.0.2'`.
- **Retrieval method:** `developers.facebook.com` is a client-rendered SPA that direct `WebFetch`
  and `curl` repeatedly failed against on several large reference pages (AdCreative field
  reference, Marketing API error-reference table, Conversions API guide pages, Commerce reference
  pages). Worked around per-file via the `r.jina.ai` reader proxy, Wayback Machine snapshots, and
  the official Python SDK GitHub source — each file's own "Sources" section documents exactly
  which method was used for which claim, and flags genuine gaps as `(unverified)` rather than
  fabricating them.
- Each file carries its own **Gotchas / Unverified Claims** section listing SDK-vs-doc
  discrepancies and open questions (e.g. `regional_regulated_categories` enum representation,
  `targeting.DevicePlatforms` value count, `Business.create_ads_pixel` doc-vs-SDK contradiction,
  `dedup_key_feedback` vs `dedupe_key_feedback` spelling) — read the relevant file's own notes
  before relying on any single field/enum in code.
- `mads-cli`'s own implementation (`mads_lib/`) is fully wired (verified live via
  `mads catalog --json`, 2026-07-02): **82 commands across 25 groups**, including dedicated
  `campaign`/`adset`/`ad`/`creative` resource commands (CRUD + status/budget), plus `audience`,
  `commerce`, `capi`, `insights`, `abtest`, `business`, `page`, `webhook`, and `analyze` (5
  read-only checks), on top of the config/auth/http/db/cli scaffolding and core `query`,
  `mutate`/`batch-mutate`, `snapshot`, `log`, `catalog`, `db`, `changelog`, `decisions`,
  `milestones` commands. No "Coverage vs mads-cli" cross-reference section has been added to any KB
  file yet, though — that remains a real gap to fill.

## Sister tool

This `mads-cli/kb/` is the Meta-Ads equivalent of **[`gads-cli/kb/`](../../gads-cli/kb/INDEX.md)**
— the same documentation-sourced, source-cited knowledge-base convention applied to Google Ads /
GA4 / GBP / Merchant Center / Search Console instead of Meta Marketing/Graph/Conversions/Commerce
APIs. Consult `gads-cli/kb/` for the Google-side APIs; this directory is Meta-only.
