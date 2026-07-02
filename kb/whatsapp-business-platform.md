# WhatsApp Business Platform (Cloud API)

Covers `mads_lib/whatsapp.py` (the `mads whatsapp` command group) — the WhatsApp Business
Platform's Cloud API. **This is a SEPARATE Meta product from the Marketing API / Graph API**
surface the rest of `mads-cli` covers (campaigns, ad sets, ads, creatives, audiences, commerce,
CAPI, Pages, Business Manager). Nothing else in this CLI implies WhatsApp coverage — it is its
own product line with its own onboarding flow, its own node type (a WhatsApp Business Account,
"WABA"), and its own endpoint family, hosted on the same `graph.facebook.com/{version}` domain as
everything else in this repo (current `API_VERSION` per `mads_lib/config.py` / `META_API_VERSION`
env var — check that constant for the exact live value; this doc does not duplicate it to avoid
drift).

This module does **not** cover WhatsApp *click-to-chat ad destinations* — those already work
today through the normal `ad`/`creative` commands with a `wa.me`/`whatsapp://` destination URL;
no dedicated module is needed for that and none is added here.

## What this module does

`mads whatsapp` wraps the following Cloud API endpoints:

| Command | Endpoint | Purpose |
|---|---|---|
| `waba info` | `GET /{waba-id}` | WABA details (name, timezone, template namespace, review status) |
| `waba phone-numbers` | `GET /{waba-id}/phone_numbers` | List phone numbers registered to a WABA |
| `phone-number info` | `GET /{phone-number-id}` | A single phone number's status/quality rating |
| `template list` | `GET /{waba-id}/message_templates` | List message templates + their review status |
| `template create` | `POST /{waba-id}/message_templates` | Submit a new message template for Meta review |
| `send` | `POST /{phone-number-id}/messages` | Send a template or free-form session message |
| `webhook subscribe` | `POST /{app-id}/subscriptions` | Subscribe the app to inbound-message/status webhooks |

Every command accepts `--json`/fails with the same structured error envelope + stable exit codes
(`VALIDATION`=6, `AUTH`=3, `API`=5, `RATE_LIMIT`=8, etc.) as the rest of `mads-cli` — see
`AGENTS.md`'s "Output Contract" section.

## Prerequisite: WABA + coexistence onboarding — NOT YET DONE for Talas

Every command that needs a WABA (`--waba-id` or the optional `META_WABA_ID` env var) requires a
WhatsApp Business Account already onboarded through the same Meta App already used for the rest
of `mads-cli` (`META_APP_ID` in `talas-ads/.env`). **This onboarding is an account-level,
Meta-eligibility-gated step that cannot be completed by writing code.** It happens through Meta's
Embedded Signup flow or a Tech/Solution Provider — not an API call this CLI (or any CLI) can make
on your behalf.

Talas runs **3 branches (QZ3, IND4, SJA)**, each already using its own consumer WhatsApp number on
the regular WhatsApp Business App. Getting *real per-branch attribution* out of this module
requires **"coexistence" onboarding** for each of those 3 numbers individually — migrating an
existing number onto the Cloud API while keeping the WhatsApp Business App usable in parallel, as
opposed to registering a fresh Cloud-API-only number with no history/contacts. This is real,
per-number, Tech/Solution-Provider-mediated account work.

**None of that onboarding has been done yet.** `META_WABA_ID` is unset. Every `mads whatsapp`
command that needs it fails with a clear `VALIDATION` error (`META_WABA_ID is not set...`), not a
crash — `WABA_ID` is optional config specifically so the rest of `mads-cli` keeps working for
users without WhatsApp configured (see `mads_lib/config.py`). **Building this module does not make
WhatsApp live for Talas** — it builds the code path assuming the account-level onboarding above is
a prerequisite someone completes separately, then configures `META_WABA_ID` (and, per branch once
coexistence is done, likely one `--phone-number-id` per branch) to actually use it.

## The 24-hour customer-service window

Cloud API enforces a hard rule on **who can receive a free-form (non-template) message**: only a
customer who has messaged the business within the last 24 hours. That window opens on the
customer's inbound message and closes 24h after their *most recent* inbound message. Outside that
window, **only pre-approved message templates** (see `template list`/`template create`) may be
sent — Meta rejects a free-form send outside the window server-side.

`mads whatsapp send` defaults to **template-only** sends for this reason:

- `--template-name` (the default/recommended path) sends an approved template — works any time.
- `--text` (a free-form session message) additionally requires `--confirm-24h-window` — an
  explicit human acknowledgement, since this CLI has **no client-side way to know** whether a
  given recipient's 24h window is currently open (Meta enforces it server-side; there is no
  "check window status" endpoint to pre-flight this against).

## Conversation Analytics is deprecated — use `pricing_analytics`

The old **Conversation Analytics API** (per-conversation, per-pricing-category message-volume
counters) was deprecated as part of Meta's **July 2025 WhatsApp pricing model change** — a shift
from per-conversation pricing to **per-message pricing**. Its replacement is
**`pricing_analytics`**, which is billing-shaped (message-level pricing/cost breakdowns by
category), **not a drop-in message counter** — do not assume `pricing_analytics` answers "how many
conversations did we have" the same way the old API did; it answers "what did we get billed for
and why," at message granularity.

**No command in this module wraps `pricing_analytics` yet** — this pass covers WABA/phone-number
read, template list/create, message send, and app webhook subscribe only. Add a dedicated command
for `pricing_analytics` as a follow-up if/when message-cost reporting is actually needed; do not
resurrect a "Conversation Analytics" command — it is dead.

## Configuration

| Variable | Required? | Purpose |
|---|---|---|
| `META_APP_ID` | Already required by the rest of mads-cli | Same Meta App the WABA is (or will be) onboarded under |
| `META_APP_SECRET` | Already required by the rest of mads-cli | Used for `webhook subscribe`'s App Access Token (`app_id\|app_secret`) |
| `META_WABA_ID` | **Optional** — new in this module | The onboarded WABA's numeric ID. Commands needing it fail gracefully (`VALIDATION`, not a crash) when unset. |

`META_WABA_ID` is deliberately **not** added to `mads doctor`'s required-check set or any
existing-command's validation path — it is additive, WhatsApp-only config that must never break
`mads-cli` for users who haven't set up WhatsApp.

## Command reference

```bash
mads whatsapp waba info [--waba-id ID] [--fields F] [--json]
mads whatsapp waba phone-numbers [--waba-id ID] [--fields F] [--limit N] [--json]

mads whatsapp phone-number info PHONE_NUMBER_ID [--fields F] [--json]

mads whatsapp template list [--waba-id ID] [--fields F] [--limit N] [--json]
mads whatsapp template create NAME CATEGORY LANGUAGE COMPONENTS_JSON \
    [--waba-id ID] [--dry-run] [-y/--yes] [--json]
    # CATEGORY: AUTHENTICATION | MARKETING | UTILITY
    # COMPONENTS_JSON: JSON array of template components, e.g.
    #   '[{"type":"BODY","text":"Your order {{1}} has shipped."}]'
    # Submits for Meta review — not immediately sendable; check `status` via `template list`.

mads whatsapp send PHONE_NUMBER_ID TO \
    [--template-name NAME --template-language en_US --template-components JSON] \
    [--text BODY --confirm-24h-window] \
    [--dry-run] [-y/--yes] [--json]
    # Exactly one of --template-name or --text is required.

mads whatsapp webhook subscribe --callback-url URL --verify-token TOKEN \
    [--app-id ID] [--fields messages] [--json]
    # Distinct from `mads webhook subscribe` (ad-account webhooks, mads_lib/webhooks.py) —
    # this subscribes the *app* to WABA object callbacks (object=whatsapp_business_account).
    # Requires the App Dashboard's Webhooks product already configured with "WhatsApp
    # Business Account" as object type + --callback-url verified; this call only performs
    # the app-level subscription step.
```

## Live-testing status

**Not live-tested.** There is no WABA configured for Talas (`META_WABA_ID` unset, no coexistence
onboarding done for QZ3/IND4/SJA) as of this doc's writing (2026-07-02) — every command above has
been exercised only against `--help` output and the pre-flight `VALIDATION` error path (missing
`META_WABA_ID`), never against a real WABA/phone number/template/send call. Endpoint shapes
(field names, request bodies) follow the standard, long-documented WhatsApp Business Platform
Cloud API surface, matching this repo's existing `API_VERSION` convention — but treat them as
[inference from stable public Meta API convention, NOT live-verified in this pass] until run
against a real onboarded WABA, the same caveat style used elsewhere in this KB
(e.g. `mads_lib/business.py`'s `business_users` note).

## Sister tool

No WhatsApp equivalent exists in `gads-cli` (Google side) — this module has no sister-CLI parallel
the way `mads`'s other groups mirror `gads_lib/merchant.py`/`gads_lib/analyze/*.py`.
