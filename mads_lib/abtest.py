"""Ad Studies (A/B / split testing) — create, list, status.

Confirmed against kb/marketing-api.md, "Ad Studies (A/B Testing / Split Testing)" section
(line ~1240-1327), resource `AdStudy` (`facebook_business/adobjects/adstudy.py`):

  - Created under a **Business** node: POST /{business_id}/ad_studies. Also readable as an
    edge off Campaign/AdSet (`.../ad_studies`) — not implemented here, since this module
    only covers the Business-level create/list/status this task asked for.
  - `type` enum (SDK-confirmed): BACKEND_AB_TESTING, CONTINUOUS_LIFT_CONFIG,
    CREATIVE_SPEND_ENFORCEMENT, GEO_LIFT, LIFT, PORTFOLIO_OPTIMIZER, SPLIT_TEST,
    VERSION_CONTROL. `SPLIT_TEST_V2` appears in the split-testing guide for creative A/B
    tests specifically, but the KB flags it "(unverified) whether SPLIT_TEST_V2 is a
    distinct value of this same type field or a separate internal classifier, since it did
    not appear in the SDK's class Type enumeration" — offered below as an extra Choice
    with that same caveat, not presented as SDK-confirmed.
  - Cells: `cells[].name`, `treatment_percentage` (`control_percentage` is the complement),
    plus exactly one of `adsets` / `campaigns` / `ads` (array of IDs) per cell depending on
    the test level.
  - Limits (marketing-api.md, "Split-test creation workflow"): max 100 concurrent studies,
    max 150 cells per study, max 100 ad entities per cell. Creative tests (SPLIT_TEST_V2)
    additionally need 2-5 cells (each referencing exactly one ad) plus
    `creative_test_config`, and `cooldown_start_time == start_time` /
    `observation_end_time == end_time` — this module does not auto-populate those
    creative-test-only fields; pass them via `--cells` JSON or a follow-up `mads mutate`
    call if you're building a SPLIT_TEST_V2.
"""
import json as _json

import click

from .config import BUSINESS_ID
from .http import graph_request
from .output import print_json, print_table, print_error, flatten

# SDK-confirmed `type` enum plus SPLIT_TEST_V2 (unverified variant — see module docstring).
STUDY_TYPES = [
    "BACKEND_AB_TESTING", "CONTINUOUS_LIFT_CONFIG", "CREATIVE_SPEND_ENFORCEMENT",
    "GEO_LIFT", "LIFT", "PORTFOLIO_OPTIMIZER", "SPLIT_TEST", "VERSION_CONTROL",
    "SPLIT_TEST_V2",
]


def _require_business_id(business_id, as_json):
    biz = business_id or BUSINESS_ID
    if not biz:
        raise SystemExit(print_error(
            "META_BUSINESS_ID is not set (or pass --business-id).", code="VALIDATION", as_json=as_json,
        ))
    return biz


def _emit_list(result, as_json):
    rows = result.get("data", []) if isinstance(result, dict) else []
    if as_json:
        print_json(result)
        return
    print_table([flatten(r) for r in rows]) if rows else print_json(result)


@click.group()
def abtest():
    """Ad Studies — A/B / split testing (create, list, status)."""


@abtest.command("create")
@click.option("--name", required=True)
@click.option("--description", default=None)
@click.option("--type", "study_type", type=click.Choice(STUDY_TYPES), default="SPLIT_TEST")
@click.option("--start-time", type=int, required=True, help="Unix timestamp.")
@click.option("--end-time", type=int, required=True, help="Unix timestamp.")
@click.option("--cells", required=True, help=(
    'JSON array of cell objects, e.g. [{"name":"Cell A","treatment_percentage":50,'
    '"adsets":["120210000000002"]},{"name":"Cell B","treatment_percentage":50,'
    '"adsets":["120210000000005"]}] (use "campaigns" or "ads" instead of "adsets" for '
    "those test levels)."
))
@click.option("--business-id", default=None, help="Override META_BUSINESS_ID.")
@click.option("--dry-run", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def abtest_create(name, description, study_type, start_time, end_time, cells, business_id, dry_run, as_json):
    """POST /{business_id}/ad_studies — create a split test / ad study.

    Limits (marketing-api.md): max 100 concurrent studies, max 150 cells/study, max 100 ad
    entities/cell.
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    try:
        cells_obj = _json.loads(cells)
    except _json.JSONDecodeError as e:
        raise SystemExit(print_error(f"--cells is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
    if not isinstance(cells_obj, list) or not cells_obj:
        raise SystemExit(print_error("--cells must be a non-empty JSON array.", code="VALIDATION", as_json=as_json))
    if len(cells_obj) > 150:
        raise SystemExit(print_error(
            f"--cells has {len(cells_obj)} entries; Meta's hard limit is 150 cells per study.",
            code="VALIDATION", as_json=as_json,
        ))

    biz = _require_business_id(business_id, as_json)
    body = {
        "name": name,
        "type": study_type,
        "start_time": start_time,
        "end_time": end_time,
        "cells": _json.dumps(cells_obj),
    }
    if description:
        body["description"] = description

    if dry_run:
        if as_json:
            print_json({"dry_run": True, "business_id": biz, "body": body})
        else:
            click.secho(f"  DRY RUN: would POST /{biz}/ad_studies", fg="yellow")
            print_json(body)
        return

    result = graph_request("POST", f"{biz}/ad_studies", params=body, as_json=as_json)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Created ad study '{name}' ({study_type})", fg="green")
    print_json(result)


@abtest.command("list")
@click.option("--business-id", default=None, help="Override META_BUSINESS_ID.")
@click.option("--fields", default="id,name,type,start_time,end_time,created_time")
@click.option("--limit", "-l", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def abtest_list(business_id, fields, limit, as_json):
    """GET /{business_id}/ad_studies — list ad studies for this Business."""
    biz = _require_business_id(business_id, as_json)
    params = {"fields": fields}
    if limit:
        params["limit"] = limit
    result = graph_request("GET", f"{biz}/ad_studies", params=params, as_json=as_json)
    _emit_list(result, as_json)


@abtest.command("status")
@click.argument("ad_study_id")
@click.option("--fields", default=(
    "id,name,type,start_time,end_time,canceled_time,cooldown_start_time,"
    "observation_end_time,results_first_available_date,confidence_level,"
    "cells{id,name,treatment_percentage,control_percentage,ad_entities_count}"
))
@click.option("--json", "as_json", is_flag=True)
def abtest_status(ad_study_id, fields, as_json):
    """GET /{ad_study_id} — read a single ad study's status/config, including cells."""
    result = graph_request("GET", ad_study_id, params={"fields": fields}, as_json=as_json)
    if as_json:
        print_json(result)
        return
    print_table([flatten(result)])
