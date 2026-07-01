#!/usr/bin/env bash
# mads-cli installer
#
# Install:
#   curl -fsSL https://raw.githubusercontent.com/talas9/mads-cli/main/scripts/install.sh | bash
#
# Interactive — detects Claude Code, gsd-pi, and Codex. Asks where to install,
# wires agents + skills + hooks, runs auth login.
#
set -euo pipefail

REPO_URL="https://github.com/talas9/mads-cli.git"
DEFAULT_DIR="$HOME/.mads-cli"
VERSION="0.1.0"

# ── Flags ────────────────────────────────────────────────────
PROJECT_SCOPE=false
SKIP_AUTH=false
INSTALL_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)    PROJECT_SCOPE=true; shift ;;
    --skip-auth)  SKIP_AUTH=true; shift ;;
    --dir)        INSTALL_DIR="$2"; shift 2 ;;
    --help|-h)
      cat <<EOF
mads-cli installer v${VERSION}

Usage:
  curl -fsSL https://raw.githubusercontent.com/talas9/mads-cli/main/scripts/install.sh | bash

Options:
  --project     Install agents into current project instead of global
  --dir PATH    Custom CLI install location
  --skip-auth   Skip OAuth login (for CI/testing)

Detects Claude Code, gsd-pi, and Codex automatically.
EOF
      exit 0 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

# ── Helpers ──────────────────────────────────────────────────
R="\033[0m"; B="\033[1m"; D="\033[2m"
CC="\033[36m"; CG="\033[32m"; CY="\033[33m"; CR="\033[31m"

ok()   { echo -e "  ${CG}✓${R} $1"; }
warn() { echo -e "  ${CY}⚠${R} $1"; }
err()  { echo -e "  ${CR}✗${R} $1"; }
step() { echo -e "\n  ${B}[$1/$2]${R} $3\n"; }

prompt() {
  local q="$1" default="$2" answer
  if [[ -t 0 ]]; then
    echo -ne "  $q [$default]: " >&2; read -r answer || answer=""
    echo "${answer:-$default}"
  else
    echo "$default"
  fi
}

# ── Banner ───────────────────────────────────────────────────
echo ""
echo -e "  ${CC}╔══════════════════════════════════════════════════════╗${R}"
echo -e "  ${CC}║${R}  ${B}mads-cli${R} v${VERSION}                         ${CC}║${R}"
echo -e "  ${CC}║${R}  Meta (Facebook/Instagram) Ads CLI                    ${CC}║${R}"
echo -e "  ${CC}╚══════════════════════════════════════════════════════╝${R}"

# ── Step 1: Prerequisites ───────────────────────────────────
step 1 6 "Prerequisites"

PY=""
command -v python3 &>/dev/null && PY="python3"
[[ -z "$PY" ]] && command -v python &>/dev/null && PY="python"
if [[ -z "$PY" ]]; then
  err "Python 3.10+ required. Install: https://python.org/downloads/"; exit 1
fi
ok "Python $($PY --version 2>&1 | cut -d' ' -f2)"

command -v git &>/dev/null || { err "git required"; exit 1; }
ok "git $(git --version | cut -d' ' -f3)"

# ── Step 2: Download ────────────────────────────────────────
step 2 6 "Download CLI"

CLI_DIR="${INSTALL_DIR:-$DEFAULT_DIR}"

if [[ -f "$CLI_DIR/mads" ]]; then
  ok "Found at $CLI_DIR"
  if [[ "$(prompt "Pull latest?" "Y/n")" =~ ^[Yy] ]]; then
    git -C "$CLI_DIR" pull --quiet 2>/dev/null && ok "Updated" || warn "Pull failed — using existing"
  fi
else
  echo "  Cloning to $CLI_DIR..."
  git clone --quiet --depth 1 "$REPO_URL" "$CLI_DIR"
  ok "Downloaded"
fi

chmod +x "$CLI_DIR/mads" "$CLI_DIR/mads.sh" 2>/dev/null || true

# ── Step 3: Dependencies ────────────────────────────────────
step 3 6 "Python dependencies"

# No google-auth equivalent needed — Meta's OAuth code/token exchange and
# appsecret_proof computation only need stdlib (hmac, hashlib, http.server,
# urllib.parse) plus click/requests/python-dotenv.
$PY -m pip install --quiet --user click requests python-dotenv 2>/dev/null \
  && ok "Installed" \
  || warn "pip had issues — run: pip install click requests python-dotenv"

# ── Step 4: Detect platforms ────────────────────────────────
step 4 6 "Detect AI platforms"

HAS_CLAUDE=false; HAS_GSD=false; HAS_CODEX=false
command -v claude &>/dev/null && HAS_CLAUDE=true && ok "Claude Code"
command -v gsd    &>/dev/null && HAS_GSD=true    && ok "gsd-pi"
command -v codex  &>/dev/null && HAS_CODEX=true  && ok "Codex"
$HAS_CLAUDE || $HAS_GSD || $HAS_CODEX || warn "No AI platforms found — standalone install"

# ── Step 5: Wire agents + skills + hooks ─────────────────────
step 5 6 "Install agents & skills"

# Scope
SCOPE="global"
if $PROJECT_SCOPE; then
  SCOPE="project"
elif [[ -t 0 ]] && ($HAS_CLAUDE || $HAS_GSD); then
  echo "  Scope:"
  echo "    1) Global  — all projects (~/.claude, ~/.gsd)"
  echo "    2) Project — this directory only"
  echo ""
  [[ "$(prompt "Choice" "1")" == "2" ]] && SCOPE="project"
fi
ok "Scope: $SCOPE"
echo ""

# ── Agent template ───────────────────────────────────────────
write_agent() {
  local dir="$1"
  mkdir -p "$dir"
  cat > "$dir/meta-ads-operator.md" << 'ENDAGENT'
---
name: meta-ads-operator
description: >
  Use for ALL Meta (Facebook/Instagram) Ads operations. Runs the mads CLI for
  campaign/ad set/ad/creative management, Insights reporting, Business
  Manager, Ad Studies (A/B tests), and Page/webhook operations.
model: inherit
tools: Bash, Read
---

You are the Meta Ads operator. You have exclusive access to the `mads`
CLI for all Meta Marketing API, Business Manager, and Page operations.

## CLI Location

ENDAGENT
  # Append dynamic path (not in heredoc to avoid escaping issues)
  echo "\`$CLI_DIR/mads\`" >> "$dir/meta-ads-operator.md"
  cat >> "$dir/meta-ads-operator.md" << 'ENDAGENT2'

## Quick Reference

```bash
mads --help              # All commands
mads doctor              # Verify setup (incl. sibling_cli: gads-cli)
mads auth test           # Test API access

# Campaigns / Ad Sets / Ads
mads campaign list
mads adset list --campaign-id 120210000000000000
mads ad list --adset-id 120210000000000001
mads insights campaign --date-preset last_7d --json

# Business Manager
mads business info
mads business adaccounts --json

# Generic Graph API query (no GAQL equivalent on Meta)
mads query --node act_1234567890/campaigns --fields id,name,status --json
```

## Rules
- Use `--json` when output is processed programmatically
- Snapshot before changes: `mads snapshot pre-change`
- Log all mutations: `mads log "action" "details"`
- Never print credentials — use `mads auth status`
- If a command fails, run `mads doctor` first
- No `page reviews`/`reply-review` command exists (or ever will) — Meta's
  Page ratings API is permanently dead (error code 12 on every version)
- Webhooks only fire on 5 fixed triggers — not general change-detection
- Batch mutate has a hard 50-operation limit (client-enforced)
ENDAGENT2

  # Replace generic 'mads' with full path in the file
  sed -i "s|^mads |$CLI_DIR/mads |g" "$dir/meta-ads-operator.md"

  ok "Agent → $dir/meta-ads-operator.md"
}

# ── Skill template ───────────────────────────────────────────
write_skill() {
  local dir="$1/mads-cli"
  mkdir -p "$dir"
  cat > "$dir/SKILL.md" << ENDSKILL
---
name: mads-cli
description: >
  Use when the user asks about Meta Ads, Facebook Ads, Instagram Ads campaigns,
  performance, ad sets, Business Manager, Ad Studies (A/B tests), Page
  insights, or ad-account webhooks. Triggers on: "meta ads", "facebook ads",
  "instagram ads", "campaign performance", "business manager", "ad set",
  "ad study", "page insights".
---

# Meta Ads CLI

Unified CLI at \`$CLI_DIR/mads\` for Meta (Facebook/Instagram) Ads.

\`\`\`bash
$CLI_DIR/mads --help          # All commands
$CLI_DIR/mads doctor          # Check setup
$CLI_DIR/mads auth login      # OAuth "Login for Business" flow
\`\`\`

| Group | Commands |
|-------|---------|
| Core | query, doctor, log, snapshot, mutate, batch-mutate, catalog, db |
| Campaign / Ad Set / Ad | list/create/status/budget/delete |
| Creative | create, upload-image, upload-video |
| Insights | campaign/adset/ad, async-submit/status/fetch |
| A/B Test | create, list, status (Ad Studies) |
| Business | info, adaccounts, pages, users, system-user, token |
| Page | info, insights (no reviews — Meta's ratings API is dead) |
| Webhook | subscribe, list, unsubscribe (5 fixed triggers only) |

Every command supports \`--json\`. If setup fails, run \`$CLI_DIR/mads auth login\`.

Full command taxonomy, exit codes, and Known Gotchas: \`$CLI_DIR/AGENTS.md\`.
ENDSKILL
  ok "Skill → $dir/SKILL.md"
}

# ── Install per platform ─────────────────────────────────────
install_for() {
  local platform="$1" agent_dir="$2" skill_dir="$3"

  if [[ -t 0 ]]; then
    [[ "$(prompt "Install for $platform?" "Y/n")" =~ ^[Nn] ]] && return
  fi

  echo ""
  echo -e "  ${B}${platform}${R}"
  write_agent "$agent_dir"
  [[ -n "$skill_dir" ]] && write_skill "$skill_dir" || true
}

if $HAS_CLAUDE; then
  if [[ "$SCOPE" == "global" ]]; then
    install_for "Claude Code" "$HOME/.claude/agents" "$HOME/.claude/skills"
  else
    install_for "Claude Code" ".claude/agents" ".claude/skills"
  fi
fi

if $HAS_GSD; then
  if [[ "$SCOPE" == "global" ]]; then
    install_for "gsd-pi" "$HOME/.gsd/agent/agents" "$HOME/.gsd/agent/skills"
  else
    install_for "gsd-pi" ".gsd/agents" ".gsd/skills"
  fi
fi

if $HAS_CODEX; then
  # Codex reads AGENTS.md natively (the open agents.md convention) — there is
  # no separate agent/skill directory format to wire the way Claude Code and
  # gsd-pi have. Nothing to write; AGENTS.md at the CLI root already covers it.
  ok "Codex detected — reads $CLI_DIR/AGENTS.md natively, no extra wiring needed"
fi

# ── Step 6: Auth ─────────────────────────────────────────────
step 6 6 "Credentials"

ENV_FILE="$CLI_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  ok ".env exists"
else
  echo "  No .env found — create one with META_APP_ID, META_APP_SECRET, META_AD_ACCOUNT_ID"
  echo "  (mads-cli has no .env.example yet; set these as environment variables or write $ENV_FILE manually)"
fi

if ! $SKIP_AUTH && [[ -t 0 ]]; then
  if [[ "$(prompt "Run OAuth login now?" "Y/n")" =~ ^[Yy] ]]; then
    echo ""
    PYTHONPATH="$CLI_DIR" $PY "$CLI_DIR/mads" auth login
  else
    echo "  Run later: $CLI_DIR/mads auth login"
  fi
else
  echo "  Run: $CLI_DIR/mads auth login"
fi

# ── Sibling-awareness (gads-cli) ─────────────────────────────
echo ""
GADS_PATH="$(command -v gads 2>/dev/null || true)"
if [[ -n "$GADS_PATH" ]]; then
  ok "gads-cli found on PATH ($GADS_PATH) — Google Ads/GBP/Merchant Center/GA4/Search Console"
  echo -e "  ${D}mads-cli's doctor command will detect it automatically (sibling_cli field).${R}"
else
  echo -e "  ${CY}ℹ${R} Managing Google Ads too? Install the sister CLI, gads-cli:"
  echo "    curl -fsSL https://raw.githubusercontent.com/talas9/gads-cli/main/scripts/install.sh | bash"
  echo "    https://github.com/talas9/gads-cli"
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "  ${CG}╔══════════════════════════════════════════════════════╗${R}"
echo -e "  ${CG}║${R}  ${B}Installation complete!${R}                              ${CG}║${R}"
echo -e "  ${CG}╚══════════════════════════════════════════════════════╝${R}"
echo ""
echo "  CLI:       $CLI_DIR/mads"
echo "  Verify:    $CLI_DIR/mads doctor"
echo "  API test:  $CLI_DIR/mads auth test"
echo "  Help:      $CLI_DIR/mads --help"
echo ""
echo -e "  ${D}Update:     git -C $CLI_DIR pull${R}"
echo -e "  ${D}Reinstall:  re-run this script${R}"
echo -e "  ${D}Uninstall:  rm -rf $CLI_DIR${R}"
echo ""
