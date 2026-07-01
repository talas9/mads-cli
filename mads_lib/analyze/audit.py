"""Structural-compliance audit for Meta (Facebook/Instagram) campaigns — 5 sections, 0/50/100 scoring.

Mirrors gads-cli's ``gads_lib/analyze/audit.py`` shape exactly: a module-local
``_window()`` helper, weighted 0/50/100 section scorers, an overall score +
letter grade, and a ``render_audit`` for terminal output.

READ-ONLY: only ``graph_request("GET", ...)`` calls are used (directly, and via
``budget_pacing.analyze_budget_pacing``). Nothing here mutates the account.
Date window always ends YESTERDAY (attribution lag — same convention as gads-cli).

Sections
--------
 1. creative_count    — active ad sets have ≥2 active ad creatives (testing best practice)
 2. creative_quality   — active ads have complete creatives (primary text + headline +
                          call-to-action + image/video)
 3. audience_setup     — active ad sets use Custom Audience / Lookalike / detailed
                          targeting rather than broad-only (geo + age/gender)
 4. budget_pacing      — delegates to ``budget_pacing.analyze_budget_pacing`` and
                          translates its over/under-pace summary into a section score
 5. capi_configured    — ≥1 ad-account pixel/dataset exists and has fired recently
                          (proxy for "Conversions API / Pixel is actually configured
                          and sending events" — see that check's own docstring for the
                          proxy's limits)
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..config import AD_ACCOUNT_ID
from ..http import graph_request
from ..output import print_json, print_table
from .budget_pacing import analyze_budget_pacing

# ---------------------------------------------------------------------------
# Section weights (must sum to 100)
# ---------------------------------------------------------------------------
_WEIGHTS: dict[str, int] = {
    "creative_count": 20,
    "creative_quality": 20,
    "audience_setup": 20,
    "budget_pacing": 20,
    "capi_configured": 20,
}

assert sum(_WEIGHTS.values()) == 100, "Section weights must sum to 100"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _window(days: int) -> tuple[str, str]:
    """Return (d_from, d_to) YYYY-MM-DD. d_to = yesterday."""
    d_to = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    d_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return d_from, d_to


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


def _fetch_adsets(act_id: str) -> list[dict]:
    return _graph_get_all(f"{act_id}/adsets", {
        "fields": "id,name,campaign_id,effective_status,targeting",
        "limit": 200,
    })


def _fetch_ads(act_id: str) -> list[dict]:
    return _graph_get_all(f"{act_id}/ads", {
        "fields": "id,name,adset_id,effective_status,"
                  "creative{id,body,title,call_to_action_type,image_hash,video_id,object_story_spec}",
        "limit": 500,
    })


def _fetch_pixels(act_id: str) -> list[dict]:
    return _graph_get_all(f"{act_id}/adspixels", {
        "fields": "id,name,last_fired_time,is_unavailable",
        "limit": 20,
    })


# ---------------------------------------------------------------------------
# Section scorers — each returns (score: int, details: dict)
# ---------------------------------------------------------------------------

def _check_creative_count(ads: list[dict], adsets: list[dict]) -> tuple[int, dict]:
    """Score 100 if all active ad sets have ≥2 active creatives; 50 if ≤25% don't; 0 otherwise.

    ≥2 active ads per ad set is Meta's own commonly-cited creative-testing
    best practice (avoid single-creative ad sets with no rotation/learning
    signal) — an operational recommendation, not an API-enforced minimum.
    """
    active_adset_ids = {a["id"] for a in adsets if a.get("effective_status") == "ACTIVE"}
    if not active_adset_ids:
        return 50, {"note": "No active ad sets found", "thin_adsets": 0, "total": 0}

    counts: dict[str, int] = {aid: 0 for aid in active_adset_ids}
    for ad in ads:
        if ad.get("effective_status") != "ACTIVE":
            continue
        aid = ad.get("adset_id")
        if aid in counts:
            counts[aid] += 1

    zero = [aid for aid, n in counts.items() if n == 0]
    one = [aid for aid, n in counts.items() if n == 1]
    thin = zero + one

    total = len(active_adset_ids)
    pct_thin = len(thin) / total
    if pct_thin == 0:
        s = 100
    elif pct_thin <= 0.25:
        s = 50
    else:
        s = 0

    return s, {
        "total_active_adsets": total,
        "zero_active_ads": len(zero),
        "one_active_ad": len(one),
        "two_plus_active_ads": total - len(thin),
        "pct_thin": round(pct_thin * 100, 1),
        "examples_zero": zero[:5],
    }


def _check_creative_quality(ads: list[dict]) -> tuple[int, dict]:
    """Score 100 if all active ads have complete creatives; 50 if ≤25% incomplete; 0 otherwise.

    "Complete" = primary text (body) + a headline (title, or link_data.message
    as a dark-post fallback) + call_to_action + at least one visual asset
    (image_hash or video_id, or the equivalent nested under object_story_spec).
    """
    active_ads = [ad for ad in ads if ad.get("effective_status") == "ACTIVE"]
    if not active_ads:
        return 50, {"note": "No active ads found", "incomplete": 0, "total": 0}

    incomplete: list[dict] = []
    for ad in active_ads:
        creative = ad.get("creative") or {}
        story = creative.get("object_story_spec") or {}
        link_data = story.get("link_data") or {}

        body = creative.get("body") or link_data.get("message")
        headline = creative.get("title") or link_data.get("message")
        cta = creative.get("call_to_action_type") or (link_data.get("call_to_action") or {}).get("type")
        visual = creative.get("image_hash") or creative.get("video_id") or link_data.get("image_hash")

        missing = []
        if not body:
            missing.append("primary_text")
        if not headline:
            missing.append("headline")
        if not cta:
            missing.append("call_to_action")
        if not visual:
            missing.append("image_or_video")

        if missing:
            incomplete.append({
                "ad_id": ad.get("id", ""),
                "name": ad.get("name", ""),
                "missing": missing,
            })

    total = len(active_ads)
    pct_incomplete = len(incomplete) / total
    if pct_incomplete == 0:
        s = 100
    elif pct_incomplete <= 0.25:
        s = 50
    else:
        s = 0

    return s, {
        "total_active_ads": total,
        "incomplete_count": len(incomplete),
        "pct_incomplete": round(pct_incomplete * 100, 1),
        "examples": incomplete[:5],
    }


def _check_audience_setup(adsets: list[dict]) -> tuple[int, dict]:
    """Score 100 if all active ad sets use audience refinement beyond broad geo/age;
    50 if ≤25% are broad-only; 0 otherwise.

    "Refinement" = targeting.custom_audiences (Custom Audience / Lookalike
    inclusion) or targeting.flexible_spec (interests/behaviors/demographics)
    is non-empty.
    """
    active = [a for a in adsets if a.get("effective_status") == "ACTIVE"]
    if not active:
        return 50, {"note": "No active ad sets found", "broad_only": 0, "total": 0}

    broad_only: list[dict] = []
    custom_audience_count = flexible_spec_count = 0
    for a in active:
        targeting = a.get("targeting") or {}
        custom_audiences = targeting.get("custom_audiences") or []
        flexible_spec = targeting.get("flexible_spec") or []
        if custom_audiences:
            custom_audience_count += 1
        if flexible_spec:
            flexible_spec_count += 1
        if not custom_audiences and not flexible_spec:
            broad_only.append({"ad_set_id": a.get("id", ""), "name": a.get("name", "")})

    total = len(active)
    pct_broad = len(broad_only) / total
    if pct_broad == 0:
        s = 100
    elif pct_broad <= 0.25:
        s = 50
    else:
        s = 0

    return s, {
        "total_active_adsets": total,
        "broad_only_count": len(broad_only),
        "pct_broad_only": round(pct_broad * 100, 1),
        "using_custom_audiences": custom_audience_count,
        "using_flexible_spec": flexible_spec_count,
        "examples_broad_only": broad_only[:5],
    }


def _check_capi_configured(pixels: list[dict], days: int) -> tuple[int, dict]:
    """Score 100 if ≥1 pixel/dataset exists and fired within the window; 50 if a pixel
    exists but hasn't fired recently (or `last_fired_time` is unknown); 0 if none exist.

    Proxy limitation: a firing pixel confirms *some* event flow (browser Pixel
    and/or server-side Conversions API both feed the same `AdsPixel` node's
    `last_fired_time`) — kb/conversions-api.md's confirmed `AdsPixel` field
    list (`event_stats`, `last_fired_time`, etc.) does not include a
    documented per-source (browser vs. server) breakdown in this session's
    research, so this check cannot distinguish "CAPI is configured" from
    "the browser Pixel alone is firing." Treat a 100/50 score here as "pixel
    infrastructure is present and active," not definitive proof server-side
    CAPI events are flowing — confirm in Events Manager's "Overview" tab
    (Browser vs. Server column) for a conclusive answer.
    """
    if not pixels:
        return 0, {
            "note": "No pixel/dataset found on this ad account — Conversions API cannot be "
                    "configured without one (POST act_{id}/adspixels to create).",
            "pixels": [],
        }

    cutoff = datetime.now() - timedelta(days=max(days, 7))
    active_pixels = []
    stale_pixels = []
    for p in pixels:
        if p.get("is_unavailable"):
            continue
        last_fired = p.get("last_fired_time")
        fired_recently = False
        if last_fired:
            try:
                # last_fired_time is a unix epoch seconds value on AdsPixel.
                fired_dt = datetime.fromtimestamp(float(last_fired))
                fired_recently = fired_dt >= cutoff
            except (TypeError, ValueError, OSError):
                fired_recently = False
        entry = {"id": p.get("id", ""), "name": p.get("name", ""), "last_fired_time": last_fired}
        if fired_recently:
            active_pixels.append(entry)
        else:
            stale_pixels.append(entry)

    if active_pixels:
        s = 100
    elif stale_pixels:
        s = 50
    else:
        s = 0

    return s, {
        "total_pixels": len(pixels),
        "active_pixels": active_pixels,
        "stale_or_unknown_pixels": stale_pixels,
        "note": (
            "Proxy check only — confirms pixel infrastructure is present and firing, not "
            "specifically that server-side CAPI (vs. browser-only Pixel) is configured. "
            "See this function's docstring."
        ),
    }


def _check_budget_pacing(ad_account_id: str | None, days: int) -> tuple[int, dict]:
    """Score 100 if no budgeted entity is over/under pace; 50 if ≤25% are; 0 otherwise.

    Delegates the actual pacing computation to `budget_pacing.analyze_budget_pacing`
    to avoid duplicating that logic.
    """
    pacing = analyze_budget_pacing(ad_account_id=ad_account_id, days=days)
    summary = pacing["summary"]
    total = summary["total"]

    if total == 0:
        return 50, {
            "note": "No budgeted active campaigns/ad sets found in scope for pacing analysis",
            **summary,
        }

    off_pace = summary["over_pace"] + summary["under_pace"]
    pct_off = off_pace / total
    if pct_off == 0:
        s = 100
    elif pct_off <= 0.25:
        s = 50
    else:
        s = 0

    worst = [e for e in pacing["entities"] if e["status"] in ("over_pace", "under_pace")]
    worst.sort(key=lambda e: abs((e["pace_ratio"] or 1.0) - 1.0), reverse=True)

    return s, {
        **summary,
        "pct_off_pace": round(pct_off * 100, 1),
        "worst_offenders": [
            {"name": e["name"], "level": e["level"], "status": e["status"], "pace_ratio": e["pace_ratio"]}
            for e in worst[:5]
        ],
    }


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def analyze_audit(ad_account_id: str | None = None, days: int = 30) -> dict:
    """Run the 5-section structural-compliance audit.

    Parameters
    ----------
    ad_account_id : override for META_AD_ACCOUNT_ID (with or without 'act_' prefix)
    days          : look-back window ending YESTERDAY (default 30)

    Returns
    -------
    {
      "window": {"from": str, "to": str, "days": int},
      "overall_score": int,           # 0-100 weighted average
      "grade": str,                   # A/B/C/D/F
      "sections": [
        {
          "id": str, "name": str, "score": int, "weight": int,
          "weighted_contribution": float, "status": "pass"|"partial"|"fail",
          "details": dict,
        }, ...
      ],
      "sections_by_id": {str: {...}},
      "summary": {"pass": int, "partial": int, "fail": int, "critical_fails": [str]},
    }
    """
    d_from, d_to = _window(days)
    act_id = _act(ad_account_id)

    adsets = _fetch_adsets(act_id)
    ads = _fetch_ads(act_id)
    pixels = _fetch_pixels(act_id)

    raw_sections: dict[str, tuple[int, dict]] = {
        "creative_count": _check_creative_count(ads, adsets),
        "creative_quality": _check_creative_quality(ads),
        "audience_setup": _check_audience_setup(adsets),
        "budget_pacing": _check_budget_pacing(ad_account_id, days),
        "capi_configured": _check_capi_configured(pixels, days),
    }

    _NAMES: dict[str, str] = {
        "creative_count": "Creative Count (≥2 active per ad set)",
        "creative_quality": "Creative Quality (complete fields)",
        "audience_setup": "Audience Setup (refined vs. broad)",
        "budget_pacing": "Budget Pacing (on-track vs. flight)",
        "capi_configured": "Conversions API / Pixel Configured",
    }

    sections = []
    total_weighted = 0.0
    pass_count = partial_count = fail_count = 0
    critical_fails: list[str] = []

    for sec_id in _WEIGHTS:
        score, details = raw_sections[sec_id]
        weight = _WEIGHTS[sec_id]
        contribution = score * weight / 100
        total_weighted += contribution

        if score == 100:
            status = "pass"
            pass_count += 1
        elif score == 50:
            status = "partial"
            partial_count += 1
        else:
            status = "fail"
            fail_count += 1
            critical_fails.append(sec_id)

        sections.append({
            "id": sec_id,
            "name": _NAMES[sec_id],
            "score": score,
            "weight": weight,
            "weighted_contribution": round(contribution, 2),
            "status": status,
            "details": details,
        })

    overall = int(round(total_weighted))

    if overall >= 85:
        grade = "A"
    elif overall >= 70:
        grade = "B"
    elif overall >= 55:
        grade = "C"
    elif overall >= 40:
        grade = "D"
    else:
        grade = "F"

    sections_by_id = {s["id"]: s for s in sections}

    return {
        "window": {"from": d_from, "to": d_to, "days": days},
        "overall_score": overall,
        "grade": grade,
        "sections": sections,
        "sections_by_id": sections_by_id,
        "summary": {
            "pass": pass_count,
            "partial": partial_count,
            "fail": fail_count,
            "critical_fails": critical_fails,
        },
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_audit(result: dict, as_json: bool = False) -> None:
    """Print audit report to stdout.

    If as_json=True, dumps the full result dict as JSON. Otherwise prints:
      1. Section scorecard table
      2. Per-section findings for non-passing sections
      3. Overall score + grade
    """
    import click

    if as_json:
        return print_json(result)

    w = result["window"]
    overall = result["overall_score"]
    grade = result["grade"]
    summary = result["summary"]

    click.secho(
        f"\nStructural Compliance Audit — {w['from']} → {w['to']} ({w['days']}d)",
        fg="yellow", bold=True,
    )
    click.echo(
        f"  Sections: {summary['pass']} pass  |  "
        f"{summary['partial']} partial  |  "
        f"{summary['fail']} fail"
    )

    click.secho("\nSection scorecard:", fg="white", bold=True)
    table_rows = []
    for s in result["sections"]:
        table_rows.append({
            "#": s["id"],
            "section": s["name"][:40],
            "score": s["score"],
            "weight": f"{s['weight']}%",
            "contrib": f"{s['weighted_contribution']:.1f}",
            "status": s["status"].upper(),
        })
    print_table(table_rows, ["#", "section", "score", "weight", "contrib", "status"])

    non_pass = [s for s in result["sections"] if s["status"] != "pass"]
    if non_pass:
        click.secho("\nFindings (partial / fail sections):", fg="white", bold=True)
        for s in non_pass:
            status_fg = "red" if s["status"] == "fail" else "yellow"
            click.secho(
                f"\n  [{s['status'].upper()}] {s['name']} — score {s['score']}/100",
                fg=status_fg, bold=True,
            )
            details = s["details"]
            if "note" in details:
                click.echo(f"    Note: {details['note']}")
            if "examples" in details and details["examples"]:
                click.echo(f"    Examples: {details['examples'][:3]}")
            if "examples_zero" in details and details["examples_zero"]:
                click.echo(f"    Ad sets with zero active ads: {', '.join(details['examples_zero'][:5])}")
            if "examples_broad_only" in details and details["examples_broad_only"]:
                names = [e["name"] for e in details["examples_broad_only"][:5]]
                click.echo(f"    Broad-only ad sets: {', '.join(names)}")
            if "worst_offenders" in details and details["worst_offenders"]:
                click.echo(f"    Worst-paced: {details['worst_offenders']}")
            if "stale_or_unknown_pixels" in details and details["stale_or_unknown_pixels"]:
                click.echo(f"    Stale/unknown pixels: {details['stale_or_unknown_pixels']}")

    click.echo()
    if overall >= 85:
        score_fg = "green"
    elif overall >= 55:
        score_fg = "yellow"
    else:
        score_fg = "red"

    click.secho("  Overall score: ", nl=False)
    click.secho(f"{overall}/100  Grade: {grade}", fg=score_fg, bold=True)
    click.echo()
