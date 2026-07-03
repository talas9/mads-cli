"""Ad-copy compliance checker — validates Meta ad creative text against Talas business rules.

Mirrors gads-cli's ``gads_lib/analyze/adcopy.py`` shape and violation-reporting
format almost exactly: a module-local business-rules loader, compiled-regex
detectors, an ``analyze_`` + ``render_`` function pair, ``--json`` handled by
the caller via ``render_``.

READ-ONLY: only ``graph_request("GET", ...)`` and ``get_db()`` (read) are
used. Nothing here mutates the account.

Business rules checked (same substance as gads-cli's checker):
  CRITICAL — install/repair/workshop/battery-service words
  CRITICAL — standalone "EV"/"electric vehicle" without "Tesla"
  HIGH     — "OEM only" / "Genuine only" / "genuine parts only" wording
  CRITICAL — UAE phone numbers appearing in copy (flag + branch match)

Business-rules DB note: the shared ``business_rules`` table
(``talas-ads/tools/init_db.py``) has a ``platform`` column, but as of this
writing every row is tagged ``platform='general'`` — commit fed0a89 only
added ``platform='meta_ads'`` tagging to the *changelog/decisions/milestones*
write paths, not to ``business_rules`` (which has no write path from mads-cli
at all — it's dbread.py, read-only). So this loader queries
``platform IN ('general', 'meta_ads')`` rather than ``platform = 'meta_ads'``
— this picks up today's real rows (all ``general``) and will also pick up any
Meta-specific rules added later, without inventing a filter that would return
zero rows against the actual schema.

Text-field coverage: unlike gads-cli's Responsive Search Ads (up to 15
headlines + 4 descriptions per ad), a Meta ``AdCreative`` carries a handful of
distinct named text fields. All of the following are checked, when present,
tagged with which field they came from (see ``_check_text``'s ``field``
param): ``creative.body``/``creative.title`` (top-level AdCreative fields —
same ones ``analyze/audit.py``'s creative-quality check already reads) and
``object_story_spec.link_data.message``/``.description``/``.name`` plus
``object_story_spec.video_data.message`` (dark-post / Page-post-ad fields).
"""

from __future__ import annotations

import re

from ..config import AD_ACCOUNT_ID
from ..http import graph_request
from ..output import print_json, print_table

# ── Branch phone numbers (from ~/talas-ads/CLAUDE.md "Business Rules") ──────
_BRANCH_PHONE_DIGITS: dict[str, str] = {
    "566662075": "QZ3",
    "501996588": "SJA",
    "564045033": "IND4",
}

# ── Compiled regex patterns for rule detection (near-verbatim port of
#    gads-cli's gads_lib/analyze/adcopy.py detectors) ────────────────────────
_RE_INSTALL = re.compile(
    r"\b(install(ation)?|repair|workshop|battery\s+service|"
    r"technician|bring\s+your\s+car|we\s+(fix|repair)|service\s+cent(?:er|re))\b",
    re.IGNORECASE,
)

_RE_EV = re.compile(
    r"\b(EV|electric\s+vehicle|electric\s+car)\b",
    re.IGNORECASE,
)

_RE_TESLA = re.compile(r"\btesla\b", re.IGNORECASE)

_RE_OEM_GENUINE = re.compile(
    r"\b(OEM\s+only|genuine\s+only|genuine\s+parts\s+only|original\s+parts\s+only)\b",
    re.IGNORECASE,
)

# UAE phone pattern: optional country code 971 or 0, then 9 digits
_RE_UAE_PHONE = re.compile(
    r"(?:(?:\+|00)?971|0)\s*(?:\d[\s.-]?){8,9}\d",
)

# Field expansion requested per ad — mirrors analyze/audit.py's
# _fetch_ads() creative expansion, plus the object_story_spec text fields
# that module doesn't need for its completeness check.
_AD_FIELDS = (
    "id,name,adset_id,campaign_id,effective_status,"
    "creative{id,body,title,object_story_spec{"
    "link_data{message,description,name},video_data{message}}}"
)


def _act(ad_account_id: str | None = None) -> str:
    aid = ad_account_id or AD_ACCOUNT_ID
    return aid if aid.startswith("act_") else f"act_{aid}"


def _graph_get_all(path: str, params: dict, max_pages: int = 20) -> list[dict]:
    """Fetch all pages of a Graph API list edge, following `paging.next`.

    Duplicated per-module by design — see budget_pacing.py's copy for the
    rationale (mirrors gads-cli's per-module fetch-helper convention).
    """
    rows: list[dict] = []
    result = graph_request("GET", path, params=params)
    if isinstance(result, dict):
        rows.extend(result.get("data", []))
        next_url = result.get("paging", {}).get("next")
    else:
        next_url = None
    pages = 1
    while next_url and pages < max_pages:
        result = graph_request("GET", next_url)
        if isinstance(result, dict):
            rows.extend(result.get("data", []))
            next_url = result.get("paging", {}).get("next")
        else:
            next_url = None
        pages += 1
    return rows


def _fetch_ads(act_id: str, campaign_id: str | None, adset_id: str | None) -> list[dict]:
    """Fetch ads scoped to one ad set, one campaign, or the whole ad account.

    Mirrors ads.py's `ad list` precedence: --adset-id wins if both are given.
    """
    if adset_id:
        path = f"{adset_id}/ads"
    elif campaign_id:
        path = f"{campaign_id}/ads"
    else:
        path = f"{act_id}/ads"
    return _graph_get_all(path, {"fields": _AD_FIELDS, "limit": 500})


def _extract_texts(ad: dict) -> dict[str, str]:
    """Pull every populated text field off an ad's creative.

    Returns {field_name: text} for only the fields that are actually present
    — field names match the KB/Graph-API dotted path, flattened with `_`.
    """
    creative = ad.get("creative") or {}
    story = creative.get("object_story_spec") or {}
    link_data = story.get("link_data") or {}
    video_data = story.get("video_data") or {}

    texts: dict[str, str] = {}
    if creative.get("body"):
        texts["body"] = creative["body"]
    if creative.get("title"):
        texts["title"] = creative["title"]
    if link_data.get("message"):
        texts["link_data.message"] = link_data["message"]
    if link_data.get("description"):
        texts["link_data.description"] = link_data["description"]
    if link_data.get("name"):
        texts["link_data.name"] = link_data["name"]
    if video_data.get("message"):
        texts["video_data.message"] = video_data["message"]
    return texts


def _load_rules(conn) -> list[dict]:
    """Load ad_copy and business rules from the DB business_rules table.

    See module docstring for why `platform IN ('general', 'meta_ads')`
    rather than `platform = 'meta_ads'` — verified against the live schema
    and its actual rows before writing this query.
    """
    cur = conn.execute(
        "SELECT id, rule, category, severity, examples "
        "FROM business_rules "
        "WHERE category IN ('ad_copy', 'business') "
        "AND platform IN ('general', 'meta_ads') "
        "ORDER BY severity, id"
    )
    return [dict(row) for row in cur.fetchall()]


def _check_text(text: str, field: str, rules: list[dict]) -> list[dict]:
    """Run all detectors on a single creative text field.

    Returns a list of violation dicts:
        {"text", "field", "rule", "rule_id", "severity", "kind", "snippet"}
    (same shape as gads-cli's checker, plus a "field" key — Meta creatives
    have several distinct named text fields per ad, unlike RSA's flat
    headlines/descriptions arrays, so "which field" is worth carrying).
    """
    violations: list[dict] = []

    # ── 1. Install / repair / workshop / battery-service / service-center ───
    m = _RE_INSTALL.search(text)
    if m:
        rule_row = next(
            (r for r in rules if r["id"] in (1, 3)),
            {"id": 1, "rule": "PARTS ONLY — no install/repair/workshop/battery/service-center language", "severity": "CRITICAL"},
        )
        violations.append({
            "text": text,
            "field": field,
            "rule": rule_row["rule"],
            "rule_id": rule_row["id"],
            "severity": "CRITICAL",
            "kind": "install_repair_language",
            "snippet": m.group(0),
        })

    # ── 2. EV / electric vehicle used WITHOUT Tesla ──────────────────────────
    ev_m = _RE_EV.search(text)
    if ev_m and not _RE_TESLA.search(text):
        rule_row = next(
            (r for r in rules if r["id"] == 2),
            {"id": 2, "rule": "Tesla not EV — always Tesla-specific, never generic EV", "severity": "CRITICAL"},
        )
        violations.append({
            "text": text,
            "field": field,
            "rule": rule_row["rule"],
            "rule_id": rule_row["id"],
            "severity": "CRITICAL",
            "kind": "ev_not_tesla",
            "snippet": ev_m.group(0),
        })

    # ── 3. OEM only / Genuine only ────────────────────────────────────────────
    oem_m = _RE_OEM_GENUINE.search(text)
    if oem_m:
        rule_row = next(
            (r for r in rules if r["id"] == 9),
            {"id": 9, "rule": "Parts: new + used + aftermarket — NOT OEM only or Genuine only", "severity": "HIGH"},
        )
        violations.append({
            "text": text,
            "field": field,
            "rule": rule_row["rule"],
            "rule_id": rule_row["id"],
            "severity": "HIGH",
            "kind": "oem_genuine_only",
            "snippet": oem_m.group(0),
        })

    # ── 4. UAE phone in copy — flag + try to identify branch ─────────────────
    phone_m = _RE_UAE_PHONE.search(text)
    if phone_m:
        raw = phone_m.group(0)
        digits_only = re.sub(r"\D", "", raw)
        branch = None
        for suffix, br in _BRANCH_PHONE_DIGITS.items():
            if digits_only.endswith(suffix):
                branch = br
                break
        branch_note = f" (matches {branch})" if branch else " (unknown branch — verify!)"
        rule_row = next(
            (r for r in rules if r["id"] == 7),
            {"id": 7, "rule": "Phone numbers are branch-specific — never mix", "severity": "CRITICAL"},
        )
        violations.append({
            "text": text,
            "field": field,
            "rule": rule_row["rule"] + branch_note,
            "rule_id": rule_row["id"],
            "severity": rule_row.get("severity", "HIGH"),
            "kind": "phone_in_copy",
            "snippet": raw,
        })

    return violations


def analyze_adcopy(
    ad_account_id: str | None = None,
    campaign_id: str | None = None,
    adset_id: str | None = None,
) -> dict:
    """Pull Meta ad creative text and validate against Talas business rules.

    Parameters
    ----------
    ad_account_id : override for META_AD_ACCOUNT_ID (with or without 'act_' prefix)
    campaign_id   : restrict to one campaign's ads (ignored if adset_id is set)
    adset_id      : restrict to one ad set's ads (wins over campaign_id)

    Returns::

        {
          "scope": {"ad_account_id": str, "campaign_id": str|None, "adset_id": str|None},
          "ads": [
            {
              "ad_id": str, "name": str, "campaign_id": str, "adset_id": str,
              "status": str, "creative_id": str,
              "texts": {field_name: text, ...},
              "violations": [
                {"text": str, "field": str, "rule": str, "rule_id": int,
                 "severity": str, "kind": str, "snippet": str}
              ]
            },
            ...
          ],
          "violations_summary": {"CRITICAL": int, "HIGH": int, "MEDIUM": int, "LOW": int},
          "rules_loaded": int,
        }
    """
    from ..db import get_db

    act_id = _act(ad_account_id)

    # ── Load business rules from DB ───────────────────────────────────────────
    conn = get_db()
    try:
        db_rules = _load_rules(conn)
    finally:
        conn.close()

    # ── Fetch ads (scoped) with creative text fields ──────────────────────────
    raw_ads = _fetch_ads(act_id, campaign_id, adset_id)

    ads = []
    violations_summary: dict[str, int] = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}

    for ad in raw_ads:
        texts = _extract_texts(ad)
        all_violations: list[dict] = []
        for field, text in texts.items():
            all_violations.extend(_check_text(text, field, db_rules))

        for v in all_violations:
            sev = v.get("severity", "LOW")
            violations_summary[sev] = violations_summary.get(sev, 0) + 1

        creative = ad.get("creative") or {}
        ads.append({
            "ad_id": ad.get("id", ""),
            "name": ad.get("name", ""),
            "campaign_id": ad.get("campaign_id", ""),
            "adset_id": ad.get("adset_id", ""),
            "status": ad.get("effective_status", ""),
            "creative_id": creative.get("id", ""),
            "texts": texts,
            "violations": all_violations,
        })

    # Violated ads first, most-critical first
    ads.sort(key=lambda a: (
        -len(a["violations"]),
        -sum(1 for v in a["violations"] if v["severity"] == "CRITICAL"),
    ))

    return {
        "scope": {"ad_account_id": act_id, "campaign_id": campaign_id, "adset_id": adset_id},
        "ads": ads,
        "violations_summary": violations_summary,
        "rules_loaded": len(db_rules),
    }


def render_adcopy(result: dict, as_json: bool = False, violations_only: bool = False) -> None:
    """Print ad table + violations table.

    Args:
        result:          Return value of ``analyze_adcopy``.
        as_json:         If True, print raw JSON instead of tables.
        violations_only: If True, only show ads that have violations.
    """
    import click

    if as_json:
        return print_json(result)

    scope = result["scope"]
    vs = result.get("violations_summary", {})
    n_ads = len(result["ads"])
    n_viol_ads = sum(1 for a in result["ads"] if a["violations"])

    scope_bits = [f"account {scope['ad_account_id']}"]
    if scope.get("campaign_id"):
        scope_bits.append(f"campaign {scope['campaign_id']}")
    if scope.get("adset_id"):
        scope_bits.append(f"ad set {scope['adset_id']}")

    click.secho(f"\nAd-copy compliance — {', '.join(scope_bits)}", fg="yellow", bold=True)
    click.echo(
        f"  {n_ads} ads  |  {n_viol_ads} with violations  |  "
        f"rules loaded: {result['rules_loaded']}"
    )
    click.echo(
        f"  Violations — CRITICAL: {vs.get('CRITICAL', 0)}  "
        f"HIGH: {vs.get('HIGH', 0)}  "
        f"MEDIUM: {vs.get('MEDIUM', 0)}  "
        f"LOW: {vs.get('LOW', 0)}"
    )

    ads_to_show = result["ads"]
    if violations_only:
        ads_to_show = [a for a in ads_to_show if a["violations"]]

    click.secho(
        "\nAds" + (" (violations only)" if violations_only else "") + ":",
        fg="white", bold=True,
    )

    if not ads_to_show:
        click.echo("  (no ads to check)" if not result["ads"] else "  (no violations found)")
    else:
        table_rows = []
        for ad in ads_to_show:
            n_v = len(ad["violations"])
            n_crit = sum(1 for v in ad["violations"] if v["severity"] == "CRITICAL")
            viol_flag = (
                f"CRIT:{n_crit}" if n_crit > 0
                else (f"HIGH:{n_v}" if n_v > 0 else "OK")
            )
            table_rows.append({
                "ad_id": ad["ad_id"],
                "name": ad["name"][:35],
                "status": ad["status"],
                "violations": viol_flag,
            })
        print_table(table_rows, ["ad_id", "name", "status", "violations"])

    # ── Violations detail table ───────────────────────────────────────────────
    all_violations = []
    for ad in result["ads"]:
        for v in ad["violations"]:
            all_violations.append({
                "ad_id": ad["ad_id"],
                "severity": v["severity"],
                "kind": v["kind"],
                "field": v["field"],
                "snippet": v.get("snippet", "")[:40],
                "text": v["text"][:50],
                "rule": v["rule"][:60],
            })

    if all_violations:
        click.secho(f"\nViolations detail ({len(all_violations)} total):", fg="red", bold=True)
        all_violations.sort(key=lambda x: (0 if x["severity"] == "CRITICAL" else 1, x["ad_id"]))
        print_table(
            all_violations,
            ["severity", "ad_id", "kind", "field", "snippet", "text", "rule"],
        )
    else:
        click.secho("\nNo business-rule violations found.", fg="green", bold=True)
