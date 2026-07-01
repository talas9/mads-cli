"""Creative fatigue detection — frequency + CTR-decay signals from Ads Insights.

Mirrors gads-cli's ``gads_lib/analyze/*.py`` shape: a module-local ``_window()``
helper, an ``analyze_`` + ``render_`` function pair, ``--json`` handled by the
caller via ``render_``.

READ-ONLY: only ``graph_request("GET", ...)`` calls are used.

Two independent fatigue signals, either of which flags an entity as "fatigued":

1. **Frequency threshold** — average `frequency` (impressions per person) over
   the window at or above `frequency_threshold` (default 3.0). This figure is
   a commonly-cited industry rule of thumb for creative fatigue on Meta
   placements, not a value Meta itself publishes as a hard rule in the docs
   consulted for kb/marketing-api.md — treat it as a tunable starting point
   (`frequency_threshold` parameter), not a platform-mandated cutoff.
2. **CTR decay** — the window is split into two halves by day; if the second
   half's average CTR is down `ctr_decay_pct` (default 20%) or more relative
   to the first half, the entity is flagged as decaying (a creative wear-out
   signal independent of frequency).

`level` controls the granularity: "ad" (default) or "adset". Both are valid
Ads Insights `level` values (kb/marketing-api.md's one Insights example uses
`level=campaign`; `ad`/`adset` are the same well-known enum family). Ad-level
is finer-grained and recommended for creative-specific fatigue; adset-level
is a reasonable fallback for accounts running Dynamic Creative, where
individual-ad insights may not isolate a specific creative variant.

Note on field coverage: `frequency`, `ctr`, and the per-level denormalized
name fields (`ad_name`/`adset_name`) are part of Meta's long-stable,
foundational Ads Insights field set. kb/marketing-api.md explicitly scopes a
full Insights API reference out of its coverage (see that file's §13 note on
`GET .../insights`, which only doc-cites `campaign_name`/`spend`/`impressions`/
`clicks`/`actions` from one example URL) — these additional field names are
not individually doc-cited in this session's KB. They are not exotic or new,
but flagged here per the project's verify-first convention.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from ..config import AD_ACCOUNT_ID
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


def _graph_get_all(path: str, params: dict, max_pages: int = 40) -> list[dict]:
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


def _fetch_daily_insights(act_id: str, level: str, d_from: str, d_to: str) -> list[dict]:
    """Daily rows (time_increment=1) with impressions/reach/frequency/clicks/ctr/spend."""
    id_field = f"{level}_id"
    name_field = f"{level}_name"
    return _graph_get_all(f"{act_id}/insights", {
        "level": level,
        "fields": f"{id_field},{name_field},impressions,reach,frequency,clicks,ctr,spend",
        "time_range": json.dumps({"since": d_from, "until": d_to}),
        "time_increment": 1,
        "limit": 500,
    })


def analyze_creative_fatigue(
    ad_account_id: str | None = None,
    days: int = 14,
    level: str = "ad",
    frequency_threshold: float = 3.0,
    ctr_decay_pct: float = 20.0,
) -> dict:
    """Detect frequency- and CTR-decay-based creative fatigue.

    Parameters
    ----------
    ad_account_id       : override for META_AD_ACCOUNT_ID
    days                : lookback window ending YESTERDAY (default 14)
    level               : "ad" (default) or "adset"
    frequency_threshold : flag if avg frequency >= this (see module docstring)
    ctr_decay_pct       : flag if 2nd-half CTR is down this % or more vs. 1st half

    Returns
    -------
    {
      "window": {"from": str, "to": str, "days": int}, "level": str,
      "entities": [
        {
          "id": str, "name": str, "days_with_data": int,
          "avg_frequency": float|None, "latest_frequency": float|None,
          "ctr_first_half": float|None, "ctr_second_half": float|None,
          "ctr_decay_pct": float|None,
          "frequency_flag": bool, "ctr_decay_flag": bool, "fatigued": bool,
        }, ...
      ],
      "summary": {"total": int, "fatigued": int, "frequency_flagged": int, "ctr_decay_flagged": int},
    }
    """
    if level not in ("ad", "adset"):
        raise ValueError("level must be 'ad' or 'adset'")

    d_from, d_to = _window(days)
    act_id = _act(ad_account_id)
    id_field = f"{level}_id"
    name_field = f"{level}_name"

    rows = _fetch_daily_insights(act_id, level, d_from, d_to)

    by_entity: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for r in rows:
        eid = r.get(id_field)
        if not eid:
            continue
        by_entity.setdefault(eid, []).append(r)
        if eid not in names:
            names[eid] = r.get(name_field, "")

    entities = []
    fatigued_count = freq_flag_count = ctr_flag_count = 0

    for eid, day_rows in by_entity.items():
        # `date_start` is always present on time_increment=1 rows even when
        # not explicitly requested in `fields`; sort defensively regardless.
        day_rows.sort(key=lambda r: r.get("date_start", ""))

        freqs: list[float] = []
        ctrs: list[float] = []
        for r in day_rows:
            try:
                freqs.append(float(r["frequency"]))
            except (KeyError, TypeError, ValueError):
                pass
            try:
                ctrs.append(float(r["ctr"]))
            except (KeyError, TypeError, ValueError):
                pass

        avg_frequency = sum(freqs) / len(freqs) if freqs else None
        latest_frequency = freqs[-1] if freqs else None

        ctr_first_half = ctr_second_half = ctr_decay = None
        if len(ctrs) >= 4:
            mid = len(ctrs) // 2
            first_half, second_half = ctrs[:mid], ctrs[mid:]
            ctr_first_half = sum(first_half) / len(first_half)
            ctr_second_half = sum(second_half) / len(second_half)
            if ctr_first_half > 0:
                ctr_decay = round((1 - (ctr_second_half / ctr_first_half)) * 100, 1)

        frequency_flag = avg_frequency is not None and avg_frequency >= frequency_threshold
        ctr_decay_flag = ctr_decay is not None and ctr_decay >= ctr_decay_pct
        fatigued = frequency_flag or ctr_decay_flag

        if frequency_flag:
            freq_flag_count += 1
        if ctr_decay_flag:
            ctr_flag_count += 1
        if fatigued:
            fatigued_count += 1

        entities.append({
            "id": eid,
            "name": names.get(eid, ""),
            "days_with_data": len(day_rows),
            "avg_frequency": round(avg_frequency, 2) if avg_frequency is not None else None,
            "latest_frequency": round(latest_frequency, 2) if latest_frequency is not None else None,
            "ctr_first_half": round(ctr_first_half, 3) if ctr_first_half is not None else None,
            "ctr_second_half": round(ctr_second_half, 3) if ctr_second_half is not None else None,
            "ctr_decay_pct": ctr_decay,
            "frequency_flag": frequency_flag,
            "ctr_decay_flag": ctr_decay_flag,
            "fatigued": fatigued,
        })

    entities.sort(key=lambda e: (not e["fatigued"], -(e["avg_frequency"] or 0)))

    return {
        "window": {"from": d_from, "to": d_to, "days": days},
        "level": level,
        "entities": entities,
        "summary": {
            "total": len(entities),
            "fatigued": fatigued_count,
            "frequency_flagged": freq_flag_count,
            "ctr_decay_flagged": ctr_flag_count,
        },
    }


def render_creative_fatigue(result: dict, as_json: bool = False) -> None:
    """Print creative fatigue report to stdout."""
    import click

    if as_json:
        return print_json(result)

    w = result["window"]
    s = result["summary"]
    click.secho(
        f"\nCreative Fatigue — {result['level']} level, {w['from']} → {w['to']} ({w['days']}d)",
        fg="yellow", bold=True,
    )
    click.echo(
        f"  {s['total']} entities: {s['fatigued']} fatigued "
        f"({s['frequency_flagged']} by frequency, {s['ctr_decay_flagged']} by CTR decay)"
    )

    rows = []
    for e in result["entities"][:30]:
        rows.append({
            "name": e["name"][:35],
            "avg_freq": e["avg_frequency"],
            "ctr_1st_half": e["ctr_first_half"],
            "ctr_2nd_half": e["ctr_second_half"],
            "ctr_decay%": e["ctr_decay_pct"],
            "fatigued": "YES" if e["fatigued"] else "",
        })
    print_table(rows, ["name", "avg_freq", "ctr_1st_half", "ctr_2nd_half", "ctr_decay%", "fatigued"])
    click.echo()
