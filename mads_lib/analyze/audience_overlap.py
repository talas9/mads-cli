"""Custom Audience overlap and cannibalization flags — structural proxy.

Mirrors gads-cli's ``gads_lib/analyze/*.py`` shape: an ``analyze_`` + ``render_``
function pair, ``--json`` handled by the caller via ``render_``.

READ-ONLY: only ``graph_request("GET", ...)`` calls are used.

**Important scope note:** Meta's Ads Manager UI ships a dedicated "Audience
Overlap" tool that computes a live overlap *percentage* between two Custom
Audiences. No public, documented Marketing API endpoint for that computation
was found in this project's kb/*.md files or in this session's research — it
appears to be an Ads-Manager-UI-only feature. This module does **not**
fabricate an overlap percentage. Instead it computes **structural overlap
risk** purely from confirmed, doc-backed fields (the `customaudiences` edge —
kb/marketing-api.md's Custom Audiences section — and
`AdSet.targeting.custom_audiences`/`excluded_custom_audiences`), flagging
configuration patterns that are near-certain or highly-likely sources of
audience cannibalization:

  - ``duplicate_targeting``      — 2+ *active* ad sets target the exact same
    set of Custom Audience IDs (near-certain: they compete against each other
    in the same auction for the same people).
  - ``shared_inclusion``         — a single Custom Audience is included (not
    just excluded) by 2+ active ad sets (likely budget-splitting/cannibalization).
  - ``lookalike_origin_overlap`` — a Lookalike Audience's seed
    (`lookalike_spec.origin`) is *also* directly targeted by another active ad
    set at the same time (the Lookalike's seed pool and the ad set targeting
    the seed directly compete for a similar/overlapping population).

Treat these as **candidates for a manual overlap check in Ads Manager**, not a
substitute for Meta's own overlap-percentage tool.
"""

from __future__ import annotations

from ..config import AD_ACCOUNT_ID
from ..http import graph_request
from ..output import print_json


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


def _fetch_custom_audiences(act_id: str) -> list[dict]:
    return _graph_get_all(f"{act_id}/customaudiences", {
        "fields": "id,name,subtype,approximate_count_lower_bound,approximate_count_upper_bound,"
                  "lookalike_spec",
        "limit": 200,
    })


def _fetch_adsets(act_id: str) -> list[dict]:
    """All ad sets (any status) — filtered client-side to avoid relying on an
    unconfirmed Insights/list-edge `filtering` field-name convention."""
    return _graph_get_all(f"{act_id}/adsets", {
        # `campaign{name}` uses the standard Graph API `{}` sub-selection
        # syntax (kb/marketing-api.md, "GET /{node_id}?fields=..." section) to
        # pull the parent campaign's name without a separate lookup call.
        "fields": "id,name,campaign_id,campaign{name},effective_status,targeting",
        "limit": 200,
    })


def analyze_audience_overlap(ad_account_id: str | None = None) -> dict:
    """Flag structural Custom Audience overlap/cannibalization risk.

    Parameters
    ----------
    ad_account_id : override for META_AD_ACCOUNT_ID

    Returns
    -------
    {
      "custom_audiences": [
        {"id", "name", "subtype", "size_lower", "size_upper", "is_lookalike",
         "lookalike_origin_id"}, ...
      ],
      "ad_sets": [
        {"id", "name", "campaign_id", "campaign_name",
         "included_audience_ids": [...], "excluded_audience_ids": [...]}, ...
      ],
      "flags": [
        {"type": str, "severity": "high"|"medium", "audience_ids": [...],
         "ad_set_ids": [...], "detail": str}, ...
      ],
      "summary": {"custom_audiences": int, "ad_sets_with_audience_targeting": int, "flags": int},
    }
    """
    act_id = _act(ad_account_id)

    ca_rows = _fetch_custom_audiences(act_id)
    custom_audiences = []
    for ca in ca_rows:
        lookalike_spec = ca.get("lookalike_spec") or {}
        origin = lookalike_spec.get("origin")
        origin_id = None
        if isinstance(origin, list) and origin and isinstance(origin[0], dict):
            origin_id = origin[0].get("id")
        custom_audiences.append({
            "id": ca["id"],
            "name": ca.get("name", ""),
            "subtype": ca.get("subtype", ""),
            "size_lower": ca.get("approximate_count_lower_bound"),
            "size_upper": ca.get("approximate_count_upper_bound"),
            "is_lookalike": ca.get("subtype") == "LOOKALIKE",
            "lookalike_origin_id": origin_id,
        })
    ca_by_id = {c["id"]: c for c in custom_audiences}

    adset_rows = _fetch_adsets(act_id)
    ad_sets = []
    for a in adset_rows:
        if a.get("effective_status") != "ACTIVE":
            continue
        targeting = a.get("targeting") or {}
        included = [
            c.get("id") for c in (targeting.get("custom_audiences") or [])
            if isinstance(c, dict) and c.get("id")
        ]
        excluded = [
            c.get("id") for c in (targeting.get("excluded_custom_audiences") or [])
            if isinstance(c, dict) and c.get("id")
        ]
        ad_sets.append({
            "id": a["id"],
            "name": a.get("name", ""),
            "campaign_id": a.get("campaign_id", ""),
            "campaign_name": (a.get("campaign") or {}).get("name", ""),
            "included_audience_ids": included,
            "excluded_audience_ids": excluded,
        })

    flags: list[dict] = []

    # --- duplicate_targeting: identical inclusion sets across 2+ active ad sets ---
    seen_sets: dict[tuple, list[str]] = {}
    for a in ad_sets:
        if not a["included_audience_ids"]:
            continue
        key = tuple(sorted(a["included_audience_ids"]))
        seen_sets.setdefault(key, []).append(a["id"])
    for key, adset_ids in seen_sets.items():
        if len(adset_ids) >= 2:
            flags.append({
                "type": "duplicate_targeting", "severity": "high",
                "audience_ids": list(key), "ad_set_ids": adset_ids,
                "detail": f"{len(adset_ids)} active ad sets target the identical Custom "
                          f"Audience set {list(key)} — they compete against each other in "
                          f"the same auction.",
            })

    # --- shared_inclusion: same single audience included by 2+ active ad sets ---
    inclusion_map: dict[str, list[str]] = {}
    for a in ad_sets:
        for cid in a["included_audience_ids"]:
            inclusion_map.setdefault(cid, []).append(a["id"])

    duplicate_pairs = {(tuple(f["audience_ids"]), tuple(sorted(f["ad_set_ids"]))) for f in flags
                        if f["type"] == "duplicate_targeting"}
    for cid, adset_ids in inclusion_map.items():
        unique_adsets = sorted(set(adset_ids))
        if len(unique_adsets) < 2:
            continue
        # Skip if this exact audience+ad-set-set was already reported as a
        # duplicate_targeting flag (avoid double-flagging the same root cause).
        if any(cid in pair_audiences and tuple(unique_adsets) == pair_adsets
               for pair_audiences, pair_adsets in duplicate_pairs):
            continue
        flags.append({
            "type": "shared_inclusion", "severity": "medium",
            "audience_ids": [cid], "ad_set_ids": unique_adsets,
            "detail": f"Custom Audience {cid} ({ca_by_id.get(cid, {}).get('name', '?')}) is "
                      f"included by {len(unique_adsets)} active ad sets — check for budget "
                      f"splitting/cannibalization.",
        })

    # --- lookalike_origin_overlap: LAL's origin audience directly targeted elsewhere ---
    for ca in custom_audiences:
        if not ca["is_lookalike"] or not ca["lookalike_origin_id"]:
            continue
        origin_id = ca["lookalike_origin_id"]
        lal_adsets = set(inclusion_map.get(ca["id"], []))
        origin_adsets = set(inclusion_map.get(origin_id, []))
        if lal_adsets and origin_adsets:
            flags.append({
                "type": "lookalike_origin_overlap", "severity": "medium",
                "audience_ids": [ca["id"], origin_id],
                "ad_set_ids": sorted(lal_adsets | origin_adsets),
                "detail": f"Lookalike '{ca['name']}' ({ca['id']}) is active in "
                          f"{len(lal_adsets)} ad set(s) while its seed audience {origin_id} "
                          f"is directly targeted in {len(origin_adsets)} other active ad "
                          f"set(s) — likely population overlap.",
            })

    ad_sets_with_targeting = sum(
        1 for a in ad_sets if a["included_audience_ids"] or a["excluded_audience_ids"]
    )

    return {
        "custom_audiences": custom_audiences,
        "ad_sets": ad_sets,
        "flags": flags,
        "summary": {
            "custom_audiences": len(custom_audiences),
            "ad_sets_with_audience_targeting": ad_sets_with_targeting,
            "flags": len(flags),
        },
    }


def render_audience_overlap(result: dict, as_json: bool = False) -> None:
    """Print audience overlap flags to stdout."""
    import click

    if as_json:
        return print_json(result)

    s = result["summary"]
    click.secho("\nCustom Audience Overlap / Cannibalization Flags", fg="yellow", bold=True)
    click.echo(
        f"  {s['custom_audiences']} custom audiences  |  "
        f"{s['ad_sets_with_audience_targeting']} ad sets with audience targeting  |  "
        f"{s['flags']} flag(s)"
    )
    click.secho(
        "  Note: structural proxy only — Meta's live Audience Overlap % tool is Ads-Manager-UI-only.",
        fg="white",
    )

    if not result["flags"]:
        click.echo("\n  No structural overlap flags found.")
        return

    click.secho("\nFlags:", fg="white", bold=True)
    for f in result["flags"]:
        fg = "red" if f["severity"] == "high" else "yellow"
        click.secho(f"\n  [{f['severity'].upper()}] {f['type']}", fg=fg, bold=True)
        click.echo(f"    {f['detail']}")
    click.echo()
