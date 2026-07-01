# mads-cli

**Meta (Facebook/Instagram) Ads CLI** — a unified command-line tool for managing Meta Marketing
API campaigns, ad sets, ads, and creatives, with built-in support for Business Manager, Ad
Studies (A/B tests), Page insights, and ad-account webhooks.

Built for AI coding agents (Claude Code, Codex, etc.) and human operators. Every command supports
`--json` for machine-readable output and `--help` for full documentation.

> The name `mads` stands for **M**eta **Ads**. Architecture mirrors its sibling CLI, **gads-cli**
> (Google Ads) — same scope-aware config, output contract, structured error envelope, and
> `snapshot → mutate → log` mutation discipline — so if you already know `gads`, `mads` will feel
> immediately familiar.

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](pyproject.toml)

---

## Features

**59 commands** across 11 groups (verified by walking the live Click tree), covering the Meta
Marketing API operational surface:

| Group | Commands | Description |
|-------|----------|-------------|
| **Core** | `query`, `doctor`, `log`, `snapshot`, `mutate`, `batch-mutate`, `catalog`, `db`, `changelog`, `decisions`, `milestones` | Generic Graph API GET builder, readiness check, structured logs, history-DB passthrough, machine-readable command catalog |
| **Auth** | `auth status`, `login`, `revoke`, `test`, `system-user create/list`, `token generate/renew` | OAuth "Login for Business" flow, credential diagnostics, Business Manager System User + access-token management |
| **Campaign** | `campaign list`, `create`, `status`, `budget`, `delete` | Campaign CRUD — objective, special ad categories, buying type, bid strategy, budget |
| **Ad Set** | `adset list`, `create`, `status`, `budget`, `delete` | Ad Set CRUD — billing event, optimization goal, bid strategy, targeting (countries/age), pixel/custom-event promoted object |
| **Ad** | `ad list`, `create`, `status`, `budget`, `delete` | Ad CRUD — creative attach by id or inline spec |
| **Creative** | `creative create`, `upload-image`, `upload-video` | AdCreative construction (link/image or video), binary asset upload |
| **Insights** | `insights campaign`, `adset`, `ad`, `async-submit`, `async-status`, `async-fetch` | Synchronous Insights at all 3 levels + async long-running report jobs |
| **A/B Test** | `abtest create`, `list`, `status` | Ad Studies (split test) management |
| **Business** | `business info`, `adaccounts`, `pages`, `users`, `system-user create/list`, `token generate/renew` | Business Manager account/page/user listing + System User + token management |
| **Page** | `page info`, `insights` | Page profile + organic Page/Post Insights — **no reviews** (see Known Gotchas in [AGENTS.md](AGENTS.md)) |
| **Webhook** | `webhook subscribe`, `list`, `unsubscribe` | Ad-account webhook subscriptions — **5 fixed triggers only**, not general change-detection |

**Cross-cutting:**
- `--json` on every command for machine-readable output
- `--plain` (no color/emoji) and `-q`/`--quiet` global flags
- `--dry-run` and `--yes` on all mutation commands
- Auto-logging to changelog after successful mutations
- Scope-aware config — auto-detects project (`./`) vs global (`~/.config/mads/`)
- Structured error envelope + 8 stable exit codes (0-7 shared with gads-cli, plus mads-specific
  `RATE_LIMIT=8` for Meta's rate-limit error codes)
- Configurable timezone (IANA) and currency (ISO 4217)
- `doctor` reports a `sibling_cli` field — detects `gads` (gads-cli) on PATH

**Library-only, not yet wired to the CLI** (functions exist, no Click commands yet — see
[AGENTS.md](AGENTS.md) for the full list): Custom/Lookalike Audiences (`mads_lib/audiences.py`),
Commerce Catalog (`mads_lib/commerce.py`), Conversions API (`mads_lib/capi.py`), and 5 analysis
modules (`mads_lib/analyze/`: audit, budget pacing, creative fatigue, audience overlap, placement
breakdown).

---

## Install

### One-liner (recommended)

```bash
pip install git+https://github.com/talas9/mads-cli.git
```

### Interactive installer

Downloads the CLI, detects your AI platforms (Claude Code, gsd, Codex), wires up agents + skills,
and runs auth setup:

```bash
curl -fsSL https://raw.githubusercontent.com/talas9/mads-cli/main/scripts/install.sh | bash
```

### From source

```bash
git clone https://github.com/talas9/mads-cli.git
cd mads-cli
pip install .
```

### Upgrade

```bash
pip install --upgrade git+https://github.com/talas9/mads-cli.git
```

---

## Quick Start

```bash
# 1. Configure environment (dev app credentials + account IDs)
export META_APP_ID=...
export META_APP_SECRET=...
export META_AD_ACCOUNT_ID=act_1234567890

# 2. Generate an access token (opens browser for the Facebook OAuth dialog)
python generate_token.py
# or: mads auth login

# 3. Verify
mads doctor

# 4. Try it
mads campaign list
mads query --node act_1234567890/campaigns --fields id,name,status
mads insights campaign --date-preset last_7d
```

---

## Command Reference

### Core

```bash
mads doctor                              # Check credentials, config, sibling_cli (gads)
mads auth status --json                  # Credential status (never prints secrets)
mads query --node act_123/campaigns --fields id,name,status  # Generic Graph API GET
mads log "action" "details"              # Append to changelog
mads snapshot pre-change --save-file     # Snapshot current config state
mads catalog --json                      # Full command/parameter manifest
mads db "SELECT * FROM changelog LIMIT 10" --json  # Read-only SELECT passthrough
mads changelog --json -n 20
mads decisions --json -n 20
mads milestones --json -n 20
```

### Campaigns

```bash
mads campaign list                                            # All campaigns
mads campaign create "My Campaign" --objective OUTCOME_SALES   # Create (PAUSED by default)
mads campaign status 120210000000000000 PAUSED                 # Pause a campaign
mads campaign budget 120210000000000000 50.00                  # Change daily budget (major units)
mads campaign delete 120210000000000000                        # Soft-delete (status=DELETED); --hard for true delete
```

### Ad Sets

```bash
mads adset list --campaign-id 120210000000000000
mads adset create "My Ad Set" --campaign-id 120210000000000000 \
    --optimization-goal OFFSITE_CONVERSIONS --daily-budget 25.00 \
    --countries AE --age-min 18 --age-max 65 --pixel-id 123456789
mads adset status 120210000000000001 PAUSED
mads adset budget 120210000000000001 30.00
mads adset delete 120210000000000001
```

### Ads & Creatives

```bash
mads ad list --adset-id 120210000000000001
mads creative upload-image ./banner.jpg
mads creative create "My Creative" --link "https://talas.ae/?branch=qz3" \
    --image-hash abc123... --headline "Tesla Parts" --message "..." --cta-type SHOP_NOW
mads ad create "My Ad" --adset-id 120210000000000001 --creative-id 987654321
mads ad status 120210000000000002 PAUSED
mads ad delete 120210000000000002
```

### Insights

```bash
mads insights campaign --date-preset last_7d
mads insights adset --since 2026-06-01 --until 2026-06-30 --breakdowns age,gender
mads insights ad --fields impressions,clicks,spend,actions
mads insights async-submit --level campaign --date-preset last_30d   # Long-running report job
mads insights async-status <report_run_id>
mads insights async-fetch <report_run_id>
```

### A/B Tests (Ad Studies)

```bash
mads abtest create --name "Creative test" --start-time 1751328000 --end-time 1753920000 \
    --cells '[{"name":"A","treatment_percentage":50,"adaccount_spec":{...}}]'
mads abtest list
mads abtest status <ad_study_id>
```

### Business Manager

```bash
mads business info
mads business adaccounts --type owned
mads business pages
mads business users
mads business system-user create "Automation Bot" --role ADMIN
mads business token generate <system_user_id> --scope ads_management,business_management
```

### Pages

```bash
mads page info <page_id>
mads page insights <page_id> --metric page_fans --period day --since 2026-06-01 --until 2026-06-30
```

> No `reviews`/`reply-review` command — Meta's Page ratings/reviews API returns error code 12 on
> every version and no reply-to-review endpoint has ever existed. See [AGENTS.md](AGENTS.md) Known
> Gotchas.

### Webhooks

```bash
mads webhook subscribe --account-id act_1234567890
mads webhook list --account-id act_1234567890
mads webhook unsubscribe --account-id act_1234567890
```

> Only 5 fixed trigger fields (`with_issues_ad_objects`, `in_process_ad_objects`,
> `ad_recommendations`, `creative_fatigue`, `product_set_issue`) — not general change-detection.

### Generic Mutations (escape hatch)

```bash
mads mutate act_1234567890/campaigns '{"name": "New Campaign", "objective": "OUTCOME_SALES", "status": "PAUSED"}'
mads batch-mutate '[{"method": "POST", "relative_url": "act_123/campaigns", "body": "name=X&objective=OUTCOME_SALES"}]'
```

Meta's hard 50-operation batch limit is enforced client-side before any HTTP call is made.

---

## Configuration

All configuration via environment variables or a `.env` file at the scope root.

| Variable | Required for | Description |
|----------|--------------|--------------|
| `META_APP_ID` | **All commands** | Meta App ID (developers.facebook.com/apps) |
| `META_APP_SECRET` | **All commands** | Meta App Secret — used to compute `appsecret_proof` on every call |
| `META_AD_ACCOUNT_ID` | Campaign/Ad Set/Ad/Creative/Insights/Webhook commands | Ad account ID (`act_` prefix auto-added if missing) |
| `META_BUSINESS_ID` | Business Manager + Ad Studies commands | Business Manager (Business Manager ID) |
| `META_API_VERSION` | Optional (default: `v25.0`) | Graph/Marketing API version |
| `MADS_TIMEZONE` | Optional (default: `UTC`) | IANA timezone (e.g. `Asia/Dubai`) |
| `MADS_CURRENCY` | Optional (default: `USD`) | ISO 4217 code (e.g. `AED`, `EUR`) |
| `MADS_PROJECT_ROOT` | Optional | Force project-scope config to a specific directory |
| `MADS_DB_PATH` | Optional | Override the local SQLite history DB path |
| `MADS_CREDENTIALS_PATH` | Optional | Override the OAuth token file path (default: `credentials/meta-oauth.json`) |
| `MADS_SNAPSHOTS_DIR` | Optional | Override the snapshot output directory |

### Scope detection

1. `MADS_PROJECT_ROOT` env var set → project scope (that directory)
2. CWD has `data/`, `credentials/`, or `.env` → project scope (CWD)
3. Otherwise → global scope (`~/.config/mads/`)

### OAuth scopes requested by `generate_token.py` / `mads auth login`

`ads_management`, `business_management`, `pages_read_engagement`, `pages_manage_metadata`

---

## Architecture

```
mads-cli/
├── mads                   # CLI entry point (thin shim)
├── mads.sh                # Shell wrapper with .env loading
├── mads_lib/
│   ├── __init__.py        # Version + public API exports
│   ├── cli.py             # Root Click group + core commands (59 commands total)
│   ├── config.py          # Scope-aware env config
│   ├── auth.py            # Access-token loading + appsecret_proof HMAC
│   ├── http.py            # Graph API request/batch wrapper + Meta error classifier
│   ├── db.py              # SQLite connection manager
│   ├── dbread.py          # SELECT-only history-DB passthrough
│   ├── output.py          # Table/JSON formatters + EXIT_CODES (incl. RATE_LIMIT=8)
│   ├── timeutil.py        # Timezone-aware helpers
│   ├── catalog.py         # Live Click-tree catalog emitter
│   ├── campaigns.py       # campaign group: list/create/status/budget/delete
│   ├── adsets.py          # adset group: list/create/status/budget/delete
│   ├── ads.py             # ad group: list/create/status/budget/delete
│   ├── creatives.py       # creative group: create/upload-image/upload-video
│   ├── insights.py        # insights group: campaign/adset/ad + async report jobs
│   ├── abtest.py          # abtest group: create/list/status (Ad Studies)
│   ├── business.py        # business group: info/adaccounts/pages/users/system-user/token
│   ├── pages.py           # page group: info/insights (NO reviews — see AGENTS.md Gotchas)
│   ├── webhooks.py        # webhook group: subscribe/list/unsubscribe (5-trigger only)
│   ├── audiences.py       # library only — Custom/Lookalike Audience functions (no CLI yet)
│   ├── commerce.py        # library only — Catalog/Product functions (no CLI yet)
│   ├── capi.py            # library only — Conversions API functions (no CLI yet)
│   └── analyze/           # library only — audit/budget_pacing/creative_fatigue/
│                          #   audience_overlap/placement_breakdown (no CLI yet)
├── kb/                    # API knowledge base (4 md files + INDEX.md + manifest.json)
├── tests/                 # offline/CI-safe pytest suite (96 tests)
├── generate_token.py      # OAuth "Login for Business" token generator
├── scripts/install.sh     # Interactive installer
├── pyproject.toml         # Package metadata
├── AGENTS.md              # Agent-driveable capability index
├── llms.txt               # LLM-optimised quick reference
├── CLAUDE.md              # @AGENTS.md
├── CHANGELOG.md           # Version history
└── README.md
```

Uses Meta's Graph API directly (`requests` + stdlib `hmac`/`hashlib`) — no Facebook Business SDK
dependency, no protobuf.

---

## Sister tool

For **Google Ads, Google Business Profile (GBP), Google Merchant Center, GA4, and Google Search
Console**, see the sister CLI **gads-cli**: https://github.com/talas9/gads-cli

`gads-cli` and `mads-cli` share the same architecture conventions — scope-aware config, `--json`/
`--plain`/`--quiet`, structured error envelope + stable exit codes, `snapshot → mutate → log`
discipline, `catalog --json` self-description, and read-only `db`/`changelog`/`decisions`/
`milestones` history access. If you manage both Google Ads and Meta Ads for the same business,
both CLIs can share a single history DB (their `changelog` tables use identical column names) and
each CLI's `doctor` command reports whether the other is installed via a `sibling_cli` field.

---

## Using with Claude Code

The included `CLAUDE.md` points to `AGENTS.md`, which gives Claude full context about commands,
auth, exit codes, and known gotchas.

```bash
claude "Run mads campaign list and summarize active campaigns"
claude "Check insights for the last 7 days and flag any ad sets with zero conversions"
```

## Contributing

1. Fork → feature branch → make changes
2. `mads doctor` to verify
3. `pytest tests/` — all tests are offline/mocked, no live API calls
4. Push → open PR

## License

MIT — declared in [`pyproject.toml`](pyproject.toml).
