"""KB (Knowledge Base) helpers — version drift detection and KB surfacing.

Mirrors gads-cli's `gads_lib/kb.py` (`google-ads-management` sibling CLI), adapted to
mads-cli's simpler version model: every Meta API slug in kb/manifest.json
(marketing-api, graph-api, conversions-api, commerce-catalog,
whatsapp-business-platform) is served from the same `graph.facebook.com/{API_VERSION}`
host (see mads_lib/config.py::API_VERSION and mads_lib/http.py::BASE_URL, plus
mads_lib/whatsapp.py's note that WhatsApp follows the same constant) — unlike
gads-cli, which tracks several independently-versioned services (Google Ads, GA4
Data/Admin, GSC, GBP) and needs a per-slug code_key mapping. mads-cli therefore only
ever compares against a single code version.
"""

import json
import re
from pathlib import Path

# Path to kb/ directory — relative to this file's location
_KB_DIR = Path(__file__).resolve().parent.parent / "kb"
_MANIFEST_PATH = _KB_DIR / "manifest.json"


def load_manifest():
    """Load and return the KB manifest as a list of dicts."""
    with open(_MANIFEST_PATH) as f:
        return json.load(f)


def get_code_versions():
    """Extract the actual API version string used in the code.

    Returns a dict keyed by a stable slug string -> actual version string in code.
    mads-cli has a single Meta API version (config.API_VERSION) shared by every
    kb slug, so this dict always has exactly one entry.
    """
    from .config import API_VERSION

    return {"meta": API_VERSION}


def _extract_version_token(raw):
    """Pull the leading `vNN` or `vNN.N` version token off a manifest string.

    manifest.json's `current_version` fields carry free-text annotations after the
    version (release dates, sunset notes, etc.), e.g.:
      'v25.0 (released 2026-02-18; no v26.0 released as of 2026-07-01)'
    This extracts just the leading token ('v25.0') for comparison.
    """
    m = re.match(r'^(v\d+(?:\.\d+)?)', raw.strip())
    return m.group(1) if m else raw


def _normalize_version(v):
    """Normalize a version token for comparison.

    Strips dot-separated minor versions but preserves pre-release suffixes:
      'v25.0' -> 'v25'
      'v1beta'-> 'v1beta'
      'v3'    -> 'v3'

    This means 'v25' and 'v25.0' compare equal (patch bump, not a code change).
    Free-text annotations are stripped first via _extract_version_token().
    """
    token = _extract_version_token(v)
    return re.sub(r'^(v\d+)\.\d+$', r'\1', token)


def _manifest_entry_to_code_key(entry):
    """Map a manifest entry to the code_versions dict key.

    Every mads-cli kb slug is served from the same graph.facebook.com/{API_VERSION}
    host, so this always returns "meta". Kept as a function (rather than a
    constant) to mirror gads-cli's shape and leave room for a future slug that
    tracks a genuinely separate version (e.g. a hypothetical non-Graph-API
    product) without reshaping check_drift().
    """
    return "meta"


def check_drift():
    """Compare code versions against manifest.json.

    Returns a list of result dicts, one per manifest entry:
      {api, slug, manifest_version, code_version, drift, status}
    where drift=True means the normalized versions do not match.
    """
    manifest = load_manifest()
    code_versions = get_code_versions()

    results = []
    for entry in manifest:
        manifest_version = entry["current_version"]
        code_key = _manifest_entry_to_code_key(entry)
        code_version = code_versions.get(code_key, "n/a") if code_key else "n/a"

        has_drift = False
        if code_version != "n/a":
            has_drift = _normalize_version(manifest_version) != _normalize_version(code_version)

        results.append({
            "api": entry["api"],
            "slug": entry["slug"],
            "manifest_version": manifest_version,
            "code_version": code_version,
            "drift": has_drift,
            "status": "DRIFT" if has_drift else "OK",
        })

    return results


def list_kb_files():
    """Return list of KB files with their metadata."""
    manifest = load_manifest()
    seen = set()
    files = []
    for entry in manifest:
        kb_file = entry.get("kb_file", "")
        if kb_file and kb_file not in seen:
            seen.add(kb_file)
            path = _KB_DIR / kb_file
            files.append({
                "file": kb_file,
                "api": entry["api"],
                "slug": entry["slug"],
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
            })
    return files


def show_kb_file(slug_or_file):
    """Return the contents of a KB file by slug or filename."""
    # Try as filename directly
    path = _KB_DIR / slug_or_file
    if not path.exists():
        # Try adding .md extension
        path = _KB_DIR / f"{slug_or_file}.md"
    if not path.exists():
        # Try finding by slug in manifest
        manifest = load_manifest()
        for entry in manifest:
            if entry.get("slug") == slug_or_file:
                path = _KB_DIR / entry["kb_file"]
                break
    if not path.exists():
        raise FileNotFoundError(f"KB file not found for: {slug_or_file}")
    return path.read_text()
