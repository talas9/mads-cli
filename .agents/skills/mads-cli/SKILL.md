---
name: mads-cli
description: >
  Meta/Facebook/Instagram Ads campaign management via mads-cli — Marketing API
  campaigns/ad sets/ads/creatives/audiences, Business Manager, Pixel and
  Conversions API (CAPI), and Commerce/Catalog. Trigger on mentions of
  Facebook Ads, Instagram Ads, Meta Ads, Business Manager, Pixel, or CAPI.
---

# mads-cli

`mads` is the CLI for managing Meta (Facebook/Instagram) Ads. Its knowledge base lives in
`mads-cli/kb/` (sister to `gads-cli/kb/` for Google Ads).

## Discovery first

Before assuming any command shape, run discovery — do not guess flags or subcommands:

1. `mads catalog --json` — full machine-readable manifest of every implemented command, its
   params, and help text. This is the ground truth for what `mads` can actually do today; the CLI
   is still early (auth, `query`, `mutate`/`batch-mutate`, `snapshot`, `log`, `catalog`, `db`,
   `changelog`, `decisions`, `milestones` — no dedicated campaign/ad-set/ad/creative resource
   commands yet).
2. `mads kb list` — mirrors the `gads-cli` `kb` command-group convention (`kb list` / `kb show` /
   `kb check`) for surfacing the KB files below. Not yet implemented in `mads-cli` as of this
   writing (see the `TODO(mads-cli)` block in `mads_lib/cli.py`) — until it lands, read the KB
   files directly instead of assuming the command exists.

## Deep API reference (read on demand, not preloaded)

- `kb/marketing-api.md` — Campaigns, Ad Sets, Ads, Creatives, Custom/Lookalike Audiences, Ad
  Studies (the core Marketing API resources you mutate/query).
- `kb/graph-api.md` — Business Manager, System Users, Pages, Webhooks (account/asset plumbing
  outside the Marketing API proper).
- `kb/conversions-api.md` — Server-side Conversions API (CAPI), Pixel/Dataset management,
  deduplication, Dataset Quality API.
- `kb/commerce-catalog.md` — Commerce Manager Catalog & Product API (product feeds, items,
  ratings-and-reviews).

`kb/manifest.json` and `kb/INDEX.md` index all four with current version, base URL, OAuth scopes,
and status. Read the specific KB file for the resource you're touching before writing code against
it — do not rely on training-data knowledge of the Meta Marketing API, which changes frequently.
