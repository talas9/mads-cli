"""Configuration for mads-cli.

Scope detection (determines where credentials, data, and .env live):
  1. MADS_PROJECT_ROOT env var set       → project scope (that directory)
  2. CWD has data/, credentials/, or .env → project scope (CWD)
  3. Otherwise                            → global scope (~/.config/mads/)

Within any scope, .env is loaded and all paths resolve relative to the scope root.
Environment variables always override detected paths.
"""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

# ── Scope detection ──────────────────────────────────────────
GLOBAL_HOME = Path.home() / ".config" / "mads"


def _detect_scope():
    """Determine scope root and whether we're global or project-local."""
    explicit = os.environ.get("MADS_PROJECT_ROOT")
    if explicit:
        return Path(explicit), "project"

    cwd = Path.cwd()
    if (cwd / "data").is_dir() or (cwd / "credentials").is_dir() or (cwd / ".env").exists():
        return cwd, "project"

    # Check if we're inside a submodule layout (mads-cli/ inside a project)
    pkg_dir = Path(__file__).resolve().parent.parent  # mads-cli/
    parent = pkg_dir.parent
    if (parent / "data").is_dir() or (parent / "credentials").is_dir():
        return parent, "project"

    return GLOBAL_HOME, "global"


SCOPE_ROOT, SCOPE_TYPE = _detect_scope()

# ── Load .env ────────────────────────────────────────────────
if load_dotenv is not None:
    # Load scope-specific .env first (highest priority)
    load_dotenv(SCOPE_ROOT / ".env")
    # If project scope, also check global as fallback for shared secrets
    if SCOPE_TYPE == "project":
        load_dotenv(GLOBAL_HOME / ".env", override=False)

# ── Paths (all overridable, default to scope root) ───────────
PROJECT_ROOT = SCOPE_ROOT  # alias for backward compat
CONFIG_HOME = GLOBAL_HOME

DB_PATH = Path(os.environ.get("MADS_DB_PATH", SCOPE_ROOT / "data" / "mads.db"))
CREDS_PATH = Path(os.environ.get("MADS_CREDENTIALS_PATH", SCOPE_ROOT / "credentials" / "meta-oauth.json"))
SNAPSHOTS_DIR = Path(os.environ.get("MADS_SNAPSHOTS_DIR", SCOPE_ROOT / "snapshots"))

# ── Meta (Facebook/Instagram) Ads ────────────────────────────
# API_VERSION: confirmed current Meta Marketing/Graph API version as of
# 2026-07-01 via developers.facebook.com/docs/graph-api/changelog/versions/
# (v25.0, released 2026-02-18). Override with META_API_VERSION if Meta ships
# a newer version before this file is updated.
API_VERSION = os.environ.get("META_API_VERSION", "v25.0")

APP_ID = os.environ.get("META_APP_ID", "")
APP_SECRET = os.environ.get("META_APP_SECRET", "")
AD_ACCOUNT_ID = os.environ.get("META_AD_ACCOUNT_ID", "")  # e.g. act_1234567890
BUSINESS_ID = os.environ.get("META_BUSINESS_ID", "")  # Business Manager ID

# ── Timezone (IANA format, e.g. "Asia/Dubai", "America/New_York") ──
TZ_NAME = os.environ.get("MADS_TIMEZONE", "UTC")

# ── Currency (ISO 4217 code, e.g. "USD", "AED", "EUR") ──────
CURRENCY = os.environ.get("MADS_CURRENCY", "USD")
