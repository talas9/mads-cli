"""Placement breakdown — Facebook vs. Instagram vs. Audience Network split.

Mirrors gads-cli's ``gads_lib/analyze/*.py`` shape: a module-local ``_window()``
helper, an ``analyze_`` + ``render_`` function pair, ``--json`` handled by the
caller via ``render_``.

READ-ONLY: only ``graph_request("GET", ...)`` calls are used.

Uses the Ads Insights ``breakdowns=publisher_platform`` parameter. The valid
`publisher_platform` values (`facebook`, `instagram`, `threads`, `messenger`,
`audience_network`) are confirmed in kb/marketing-api.md's Targeting Reference
placement table (there, they gate `targeting.publisher_platforms`; the same
enum family is the standard Ads Insights breakdown dimension for splitting
delivery/results by platform). kb/marketing-api.md explicitly scopes a full
Insights API reference out of its coverage (see that file's §13 note), so the
`breakdowns` parameter itself and the exact `publisher_platform` breakdown key
are not individually doc-cited in this session's KB — this is not exotic or
new (it is one of the most commonly used Insights breakdowns in the
ecosystem), but flagged here per the project's verify-first convention. A
finer `platform_position` breakdown (feed/story/reels/etc. *within* each
publisher_platform) also exists on the API but is out of scope for this
module's Facebook/Instagram/Audience-Network-level split.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from ..config import AD_ACCOUNT_ID, CURRENCY
from ..http import graph_request
from ..output import print_json, print_table


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


def analyze_placement_breakdown(
    ad_account_id: str | None = None,
    days: int = 14,
    level: str = "campaign",
    campaign_id: str | None = None,
) -> dict:
    """Spend/CTR/CPC/CPM split by publisher_platform.

    Parameters
    ----------
    ad_account_id : override for META_AD_ACCOUNT_ID
    days          : lookback window ending YESTERDAY (default 14)
    level         : Insights aggregation level — "account" or "campaign" (default)
    campaign_id   : optional — restrict results to one campaign (client-side filter,
                    requires level="campaign"; avoids relying on an unconfirmed
                    Insights `filtering` field-name convention for this project)

    Returns
    -------
    {
      "window": {"from": str, "to": str, "days": int}, "level": str,
      "platforms": [
        {
          "publisher_platform": str, "spend": float, "impressions": int, "clicks": int,
          "ctr": float|None, "cpc": float|None, "cpm": float|None, "pct_of_spend": float|None,
        }, ...
      ],
      "total_spend": float,
    }
    """
    if campaign_id and level != "campaign":
        raise ValueError("campaign_id filter requires level='campaign'")

    d_from, d_to = _window(days)
    act_id = _act(ad_account_id)

    fields = "spend,impressions,clicks,ctr,cpc,cpm"
    if level == "campaign":
        fields = "campaign_id," + fields

    rows = _graph_get_all(f"{act_id}/insights", {
        "level": level,
        "fields": fields,
        "breakdowns": "publisher_platform",
        "time_range": json.dumps({"since": d_from, "until": d_to}),
        "limit": 200,
    })

    if campaign_id:
        rows = [r for r in rows if r.get("campaign_id") == campaign_id]

    agg: dict[str, dict] = {}
    for r in rows:
        platform = r.get("publisher_platform", "unknown")
        bucket = agg.setdefault(platform, {"spend": 0.0, "impressions": 0, "clicks": 0})
        try:
            bucket["spend"] += float(r.get("spend", 0) or 0)
        except (TypeError, ValueError):
            pass
        try:
            bucket["impressions"] += int(float(r.get("impressions", 0) or 0))
        except (TypeError, ValueError):
            pass
        try:
            bucket["clicks"] += int(float(r.get("clicks", 0) or 0))
        except (TypeError, ValueError):
            pass

    total_spend = sum(b["spend"] for b in agg.values())

    platforms = []
    for platform, b in sorted(agg.items(), key=lambda kv: kv[1]["spend"], reverse=True):
        ctr = (b["clicks"] / b["impressions"] * 100) if b["impressions"] else None
        cpc = (b["spend"] / b["clicks"]) if b["clicks"] else None
        cpm = (b["spend"] / b["impressions"] * 1000) if b["impressions"] else None
        pct_of_spend = (b["spend"] / total_spend * 100) if total_spend else None
        platforms.append({
            "publisher_platform": platform,
            "spend": round(b["spend"], 2),
            "impressions": b["impressions"],
            "clicks": b["clicks"],
            "ctr": round(ctr, 2) if ctr is not None else None,
            "cpc": round(cpc, 2) if cpc is not None else None,
            "cpm": round(cpm, 2) if cpm is not None else None,
            "pct_of_spend": round(pct_of_spend, 1) if pct_of_spend is not None else None,
        })

    return {
        "window": {"from": d_from, "to": d_to, "days": days},
        "level": level,
        "platforms": platforms,
        "total_spend": round(total_spend, 2),
    }


def render_placement_breakdown(result: dict, as_json: bool = False) -> None:
    """Print placement breakdown report to stdout."""
    import click

    if as_json:
        return print_json(result)

    w = result["window"]
    click.secho(
        f"\nPlacement Breakdown — {result['level']} level, {w['from']} → {w['to']} ({w['days']}d)",
        fg="yellow", bold=True,
    )
    click.echo(f"  Total spend: {result['total_spend']:,.2f} {CURRENCY}")

    rows = []
    for p in result["platforms"]:
        rows.append({
            "platform": p["publisher_platform"],
            "spend": p["spend"],
            "%_of_spend": p["pct_of_spend"],
            "impressions": p["impressions"],
            "clicks": p["clicks"],
            "ctr%": p["ctr"],
            "cpc": p["cpc"],
            "cpm": p["cpm"],
        })
    print_table(rows, ["platform", "spend", "%_of_spend", "impressions", "clicks", "ctr%", "cpc", "cpm"])
    click.echo()
