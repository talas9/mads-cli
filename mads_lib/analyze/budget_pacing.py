"""Budget pacing — over/under-pace vs. elapsed time-in-flight for Meta campaigns/ad sets.

Mirrors gads-cli's ``gads_lib/analyze/*.py`` shape: a module-local ``_window()``
helper, an ``analyze_`` + ``render_`` function pair, ``--json`` handled by the
caller via ``render_``.

READ-ONLY: only ``graph_request("GET", ...)`` calls are used. Nothing here
mutates the account. Date window always ends YESTERDAY (attribution lag —
same convention as gads-cli; Meta's own lag is generally shorter, but never
using same-day data avoids spend still trickling in for "today").

Two pacing models, chosen per entity based on its budget type (Meta's
``daily_budget``/``lifetime_budget`` are mutually exclusive at both the
Campaign and AdSet level — kb/marketing-api.md, Field Reference tables):

1. **Lifetime-budget entities with a defined flight window** (``lifetime_budget``
   plus both a start and stop/end time set): pacing compares actual
   spend-to-date as a fraction of the lifetime budget against elapsed time as
   a fraction of the total flight duration —
   ``pace_ratio = spend_fraction / elapsed_fraction``.
2. **Daily-budget entities** (open-ended, no fixed stop date — the common
   case): "time in flight" doesn't apply the same way since the budget resets
   every day, so pacing here compares yesterday's actual spend against the
   configured ``daily_budget`` (a delivery-variance check, not a
   flight-completion check).

Thresholds (``pace_ratio`` > 1.2 = over-pace, < 0.8 = under-pace for lifetime
budgets; > 125% / < 50% of ``daily_budget`` for daily budgets) are
**operational heuristics chosen for this CLI**, not Meta-published hard
rules — no exact daily-budget overdelivery percentage was found in
kb/marketing-api.md. Treat them as a tunable starting point.

Currency note: per kb/marketing-api.md's own (unverified) note, Meta's
``daily_budget``/``lifetime_budget`` fields are in the account currency's
*minor unit* (e.g. fils-equivalent for AED, cents for USD) while Ads Insights
``spend`` is returned in *major* currency units. This module divides budget
fields by 100 to match, except for known zero-decimal currencies (JPY, KRW,
etc. — the standard Meta/Stripe zero-decimal currency list), where no
division is applied. This was not independently re-verified against a live
account in this session — sanity-check absolute amounts against Ads Manager;
the relative ``pace_ratio`` classification is more robust to a residual unit
mismatch than the absolute currency figures are.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import AD_ACCOUNT_ID, CURRENCY
from ..http import graph_request
from ..output import print_json, print_table

# Currencies with no minor unit (standard Meta/Stripe zero-decimal currency
# list) — do not divide daily_budget/lifetime_budget by 100 for these.
_ZERO_DECIMAL_CURRENCIES = {
    "BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG",
    "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF",
}

# Pace-ratio thresholds — operational heuristics, see module docstring.
_OVER_PACE_RATIO = 1.2
_UNDER_PACE_RATIO = 0.8
_DAILY_OVER_PCT = 1.25
_DAILY_UNDER_PCT = 0.5


def _window(days: int) -> tuple[str, str]:
    """Return (d_from, d_to) YYYY-MM-DD. d_to = yesterday."""
    d_to = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    d_from = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    return d_from, d_to


def _act(ad_account_id: str | None = None) -> str:
    aid = ad_account_id or AD_ACCOUNT_ID
    return aid if aid.startswith("act_") else f"act_{aid}"


def _minor_to_major(raw: Any, currency: str) -> float | None:
    """Convert a budget field (minor units) to major currency units. See module docstring."""
    if raw is None:
        return None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None
    if currency.upper() in _ZERO_DECIMAL_CURRENCIES:
        return val
    return val / 100.0


def _graph_get_all(path: str, params: dict, max_pages: int = 20) -> list[dict]:
    """Fetch all pages of a Graph API list edge, following `paging.next`.

    Duplicated per-module by design (mirrors gads-cli's convention of each
    analyze/*.py module owning its own fetch helpers rather than sharing a
    heavier abstraction across modules — see e.g. gads_lib/analyze/audit.py's
    module-local `_fetch_rsa_ads`, not reused by adcopy.py).
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


def _parse_meta_dt(ts: str | None):
    """Parse a Meta ISO-8601 datetime string (e.g. '2026-06-01T00:00:00+0400').

    Uses `strptime` rather than `datetime.fromisoformat` because this
    project's minimum supported Python is 3.10 (pyproject.toml), where
    `fromisoformat` does not yet accept the non-colon UTC-offset form
    (`+0400`) Graph API returns; `%z` has always accepted that form via
    `strptime`.
    """
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
    except (ValueError, TypeError):
        return None


def _fetch_campaigns(act_id: str) -> list[dict]:
    return _graph_get_all(f"{act_id}/campaigns", {
        "fields": "id,name,status,effective_status,daily_budget,lifetime_budget,"
                  "budget_remaining,start_time,stop_time",
        "limit": 100,
    })


def _fetch_adsets(act_id: str) -> list[dict]:
    return _graph_get_all(f"{act_id}/adsets", {
        "fields": "id,name,campaign_id,status,effective_status,daily_budget,lifetime_budget,"
                  "budget_remaining,start_time,end_time",
        "limit": 200,
    })


def _fetch_insights_spend(act_id: str, level: str, since: str, until: str) -> dict[str, float]:
    """Aggregate spend per entity id (keyed by campaign_id/adset_id) for [since, until].

    Omitting `time_increment` returns one aggregated row per entity across the
    whole range (the Insights API default) rather than a daily breakdown.
    """
    id_field = f"{level}_id"
    rows = _graph_get_all(f"{act_id}/insights", {
        "level": level,
        "fields": f"{id_field},spend",
        "time_range": json.dumps({"since": since, "until": until}),
        "limit": 500,
    })
    spend: dict[str, float] = {}
    for r in rows:
        eid = r.get(id_field)
        if not eid:
            continue
        try:
            spend[eid] = spend.get(eid, 0.0) + float(r.get("spend", 0) or 0)
        except (TypeError, ValueError):
            continue
    return spend


def _pace_status(ratio: float | None, over: float, under: float) -> str:
    if ratio is None:
        return "unknown"
    if ratio > over:
        return "over_pace"
    if ratio < under:
        return "under_pace"
    return "on_pace"


def analyze_budget_pacing(ad_account_id: str | None = None, days: int = 30) -> dict:
    """Compute pacing status for every active, budgeted campaign/ad set.

    Parameters
    ----------
    ad_account_id : override for META_AD_ACCOUNT_ID (with or without 'act_' prefix)
    days          : lifetime-budget spend-to-date lookback window ending YESTERDAY (default 30)

    Returns
    -------
    {
      "window": {"from": str, "to": str, "days": int},
      "entities": [
        {
          "level": "campaign" | "adset", "id": str, "name": str, "campaign_id": str,
          "budget_type": "lifetime" | "daily",
          "budget_major": float | None, "spend_major": float | None,
          "elapsed_pct": float | None,       # lifetime entities only
          "pace_ratio": float | None,
          "status": "over_pace" | "under_pace" | "on_pace" | "unknown",
        }, ...
      ],
      "summary": {"over_pace": int, "under_pace": int, "on_pace": int, "unknown": int, "total": int},
    }
    """
    d_from, d_to = _window(days)
    act_id = _act(ad_account_id)

    campaigns = _fetch_campaigns(act_id)
    adsets = _fetch_adsets(act_id)

    # Campaign-level CBO: campaign itself carries the budget, so its child ad
    # sets must NOT be double-counted at their own (empty) budget fields.
    cbo_campaign_ids = {
        c["id"] for c in campaigns
        if c.get("effective_status") == "ACTIVE" and (c.get("daily_budget") or c.get("lifetime_budget"))
    }

    now = datetime.now(timezone.utc)
    entities: list[dict] = []

    # --- Lifetime-budget campaigns with a defined flight window ---
    lifetime_campaigns = [
        c for c in campaigns
        if c.get("effective_status") == "ACTIVE" and c.get("lifetime_budget")
        and c.get("start_time") and c.get("stop_time")
    ]
    lifetime_campaign_ids = {c["id"] for c in lifetime_campaigns}
    if lifetime_campaigns:
        spend_map = _fetch_insights_spend(act_id, "campaign", d_from, d_to)
        for c in lifetime_campaigns:
            start = _parse_meta_dt(c.get("start_time"))
            stop = _parse_meta_dt(c.get("stop_time"))
            budget = _minor_to_major(c.get("lifetime_budget"), CURRENCY)
            spend = spend_map.get(c["id"])
            elapsed_pct = None
            ratio = None
            if start and stop and stop > start:
                elapsed_pct = max(0.0, min(1.0, (now - start).total_seconds() / (stop - start).total_seconds()))
                if budget and spend is not None and elapsed_pct > 0:
                    ratio = (spend / budget) / elapsed_pct
            entities.append({
                "level": "campaign", "id": c["id"], "name": c.get("name", ""),
                "campaign_id": c["id"], "budget_type": "lifetime",
                "budget_major": round(budget, 2) if budget is not None else None,
                "spend_major": round(spend, 2) if spend is not None else None,
                "elapsed_pct": round(elapsed_pct * 100, 1) if elapsed_pct is not None else None,
                "pace_ratio": round(ratio, 2) if ratio is not None else None,
                "status": _pace_status(ratio, _OVER_PACE_RATIO, _UNDER_PACE_RATIO),
            })

    # --- Daily-budget campaigns (yesterday's spend vs. daily_budget) ---
    daily_campaigns = [
        c for c in campaigns
        if c.get("effective_status") == "ACTIVE" and c.get("daily_budget")
        and c["id"] not in lifetime_campaign_ids
    ]
    if daily_campaigns:
        yesterday_spend = _fetch_insights_spend(act_id, "campaign", d_to, d_to)
        for c in daily_campaigns:
            budget = _minor_to_major(c.get("daily_budget"), CURRENCY)
            spend = yesterday_spend.get(c["id"])
            ratio = (spend / budget) if (budget and spend is not None) else None
            entities.append({
                "level": "campaign", "id": c["id"], "name": c.get("name", ""),
                "campaign_id": c["id"], "budget_type": "daily",
                "budget_major": round(budget, 2) if budget is not None else None,
                "spend_major": round(spend, 2) if spend is not None else None,
                "elapsed_pct": None,
                "pace_ratio": round(ratio, 2) if ratio is not None else None,
                "status": _pace_status(ratio, _DAILY_OVER_PCT, _DAILY_UNDER_PCT),
            })

    # --- Ad-set-level budgets (only where the parent campaign has no CBO budget) ---
    own_budget_adsets = [
        a for a in adsets
        if a.get("effective_status") == "ACTIVE" and a.get("campaign_id") not in cbo_campaign_ids
        and (a.get("daily_budget") or a.get("lifetime_budget"))
    ]
    lifetime_adsets = [
        a for a in own_budget_adsets
        if a.get("lifetime_budget") and a.get("start_time") and a.get("end_time")
    ]
    daily_adsets = [a for a in own_budget_adsets if a.get("daily_budget")]

    if lifetime_adsets:
        spend_map = _fetch_insights_spend(act_id, "adset", d_from, d_to)
        for a in lifetime_adsets:
            start = _parse_meta_dt(a.get("start_time"))
            stop = _parse_meta_dt(a.get("end_time"))
            budget = _minor_to_major(a.get("lifetime_budget"), CURRENCY)
            spend = spend_map.get(a["id"])
            elapsed_pct = None
            ratio = None
            if start and stop and stop > start:
                elapsed_pct = max(0.0, min(1.0, (now - start).total_seconds() / (stop - start).total_seconds()))
                if budget and spend is not None and elapsed_pct > 0:
                    ratio = (spend / budget) / elapsed_pct
            entities.append({
                "level": "adset", "id": a["id"], "name": a.get("name", ""),
                "campaign_id": a.get("campaign_id", ""), "budget_type": "lifetime",
                "budget_major": round(budget, 2) if budget is not None else None,
                "spend_major": round(spend, 2) if spend is not None else None,
                "elapsed_pct": round(elapsed_pct * 100, 1) if elapsed_pct is not None else None,
                "pace_ratio": round(ratio, 2) if ratio is not None else None,
                "status": _pace_status(ratio, _OVER_PACE_RATIO, _UNDER_PACE_RATIO),
            })

    if daily_adsets:
        yesterday_spend = _fetch_insights_spend(act_id, "adset", d_to, d_to)
        for a in daily_adsets:
            budget = _minor_to_major(a.get("daily_budget"), CURRENCY)
            spend = yesterday_spend.get(a["id"])
            ratio = (spend / budget) if (budget and spend is not None) else None
            entities.append({
                "level": "adset", "id": a["id"], "name": a.get("name", ""),
                "campaign_id": a.get("campaign_id", ""), "budget_type": "daily",
                "budget_major": round(budget, 2) if budget is not None else None,
                "spend_major": round(spend, 2) if spend is not None else None,
                "elapsed_pct": None,
                "pace_ratio": round(ratio, 2) if ratio is not None else None,
                "status": _pace_status(ratio, _DAILY_OVER_PCT, _DAILY_UNDER_PCT),
            })

    summary = {"over_pace": 0, "under_pace": 0, "on_pace": 0, "unknown": 0, "total": len(entities)}
    for e in entities:
        summary[e["status"]] = summary.get(e["status"], 0) + 1

    return {
        "window": {"from": d_from, "to": d_to, "days": days},
        "entities": entities,
        "summary": summary,
    }


def render_budget_pacing(result: dict, as_json: bool = False) -> None:
    """Print budget pacing report to stdout."""
    import click

    if as_json:
        return print_json(result)

    w = result["window"]
    summary = result["summary"]
    click.secho(
        f"\nBudget Pacing — lifetime-budget lookback {w['from']} → {w['to']} ({w['days']}d)",
        fg="yellow", bold=True,
    )
    click.echo(
        f"  {summary['total']} budgeted entities: {summary['over_pace']} over-pace  |  "
        f"{summary['under_pace']} under-pace  |  {summary['on_pace']} on-pace  |  "
        f"{summary['unknown']} unknown"
    )

    rows = []
    for e in result["entities"]:
        rows.append({
            "level": e["level"],
            "name": e["name"][:35],
            "budget_type": e["budget_type"],
            "budget": e["budget_major"],
            "spend": e["spend_major"],
            "elapsed%": e["elapsed_pct"],
            "pace_ratio": e["pace_ratio"],
            "status": e["status"].upper(),
        })
    print_table(rows, ["level", "name", "budget_type", "budget", "spend", "elapsed%", "pace_ratio", "status"])
    click.echo()
