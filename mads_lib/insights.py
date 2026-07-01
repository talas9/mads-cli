"""Meta Ads Insights — sync campaign/adset/ad pulls, plus the async
submit/status/fetch job pattern for larger date ranges, with breakdowns support.

Confirmed against kb/marketing-api.md, "13. GET /act_{ad_account_id}/insights — Ads
Insights" (line ~529-547):
  - Sync call shape (literal example transcribed there):
      GET /act_{ad_account_id}/insights
          ?fields=campaign_name,spend,impressions,clicks,actions
          &date_preset=last_7d&level=campaign
  - "Large/complex insights pulls should use the async variant (POST .../insights to start
    a report job, then poll GET /{report_run_id} until async_status: 'Job Completed', then
    GET /{report_run_id}/insights for the data) rather than the synchronous GET, which can
    time out on large date ranges."
  - v25.0 change (Status & Versions section): failed async report jobs now return richer
    default error fields: error_code (uint -> int), error_message, error_subcode,
    error_user_title, error_user_msg.

That same KB section is explicit about its own scope gap (quoted verbatim): "general
async-insights pattern is (unverified in this session) beyond the v25.0 error-field
change ... treat this subsection as a pointer, not a full Insights reference." This module
honors that gap rather than papering over it:

  - The exact `AdReportRun` polling field names used below (`async_status`,
    `async_percent_completion`) are the long-standing, widely-documented
    facebook-business SDK `AdReportRun` field names (`adreportrun.py`). They are
    [inference from stable public SDK convention, NOT independently re-confirmed against a
    live doc fetch in this KB pass] — verify against a live call (or `adreportrun.py`)
    before hardening this into a strict schema-checked poller. If Meta ever renames these,
    a bad --fields value simply surfaces as a normal classify_meta_error() response, not a
    silent wrong answer.
  - `breakdowns` is a real, long-standing Ads Insights request parameter, but
    kb/marketing-api.md does not transcribe a breakdowns enum table (see the gap note
    above). `publisher_platform` and `platform_position` are the two values this task
    named directly; they are the singular, Insights-side counterparts of the *targeting*-side
    plural `publisher_platforms` / `facebook_positions` fields that marketing-api.md's
    "Placement fields and their valid values" table does confirm — a related but distinct
    parameter family. Treat these two breakdown values as [named in this task, not
    KB-table-verified] and re-check live if a breakdown request errors.
"""
import json as _json

import click

from .config import AD_ACCOUNT_ID
from .http import graph_request
from .output import print_json, print_table, print_error, flatten

# Breakdown values this task asked for support of (see module docstring re: KB gap).
BREAKDOWN_CHOICES = ["publisher_platform", "platform_position"]

LEVEL_CHOICES = ["account", "campaign", "adset", "ad"]


def _normalize_account_id(account_id):
    """Ensure the `act_` prefix Meta requires on ad-account-scoped edges.

    graph-api.md: "Ad account IDs are always referenced with the `act_` prefix in the URL
    path ... even though the bare numeric ID is what's stored in `AdAccount.account_id`."
    """
    if not account_id:
        return account_id
    return account_id if account_id.startswith("act_") else f"act_{account_id}"


def _require_account_id(account_id, as_json):
    acct = _normalize_account_id(account_id or AD_ACCOUNT_ID)
    if not acct:
        raise SystemExit(print_error(
            "META_AD_ACCOUNT_ID is not set (or pass --account-id).", code="VALIDATION", as_json=as_json,
        ))
    return acct


def _common_insights_params(fields, date_preset, since, until, breakdowns, filtering, limit, level=None):
    """Build the shared query-param dict for both sync and async insights calls."""
    if (since and not until) or (until and not since):
        raise ValueError("--since and --until must be given together.")

    params = {}
    if fields:
        params["fields"] = fields
    if level:
        params["level"] = level
    if since and until:
        # time_range is a JSON-encoded {"since": ..., "until": ...} object — standard Ads
        # Insights parameter, not the literal date_preset example transcribed in the KB.
        params["time_range"] = _json.dumps({"since": since, "until": until})
    elif date_preset:
        params["date_preset"] = date_preset
    if breakdowns:
        params["breakdowns"] = ",".join(breakdowns)
    if filtering:
        try:
            _json.loads(filtering)  # validate shape before sending
        except _json.JSONDecodeError as e:
            raise ValueError(f"--filtering is not valid JSON: {e}")
        params["filtering"] = filtering
    if limit:
        params["limit"] = limit
    return params


def _insights_options(f):
    """Shared Click options for every insights-producing command."""
    f = click.option("--account-id", default=None, help="Override META_AD_ACCOUNT_ID.")(f)
    f = click.option("--fields", default="campaign_name,spend,impressions,clicks,actions",
                      help="Comma-separated Ads Insights fields.")(f)
    f = click.option("--date-preset", default="last_7d",
                      help="Meta date_preset (e.g. last_7d, last_30d, yesterday). Ignored if --since/--until given.")(f)
    f = click.option("--since", default=None, help="Range start (YYYY-MM-DD). Requires --until.")(f)
    f = click.option("--until", default=None, help="Range end (YYYY-MM-DD). Requires --since.")(f)
    f = click.option("--breakdown", "breakdowns", multiple=True, type=click.Choice(BREAKDOWN_CHOICES),
                      help="Repeatable. publisher_platform and/or platform_position.")(f)
    f = click.option("--filtering", default=None, help="JSON-encoded Marketing API `filtering` array.")(f)
    f = click.option("--limit", "-l", type=int, default=None)(f)
    f = click.option("--json", "as_json", is_flag=True)(f)
    return f


def _emit_insights(result, as_json):
    rows = result.get("data", []) if isinstance(result, dict) else []
    if as_json:
        print_json(result)
        return
    if not rows:
        print_json(result)
        return
    print_table([flatten(r) for r in rows])
    click.echo(f"\n  {len(rows)} row(s)")


@click.group()
def insights():
    """Ads Insights: sync campaign/adset/ad pulls + async submit/status/fetch."""


@insights.command("campaign")
@_insights_options
def insights_campaign(account_id, fields, date_preset, since, until, breakdowns, filtering, limit, as_json):
    """GET /act_{ad_account_id}/insights?level=campaign — sync campaign-level insights."""
    acct = _require_account_id(account_id, as_json)
    try:
        params = _common_insights_params(fields, date_preset, since, until, breakdowns, filtering, limit, level="campaign")
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    result = graph_request("GET", f"{acct}/insights", params=params, as_json=as_json)
    _emit_insights(result, as_json)


@insights.command("adset")
@_insights_options
def insights_adset(account_id, fields, date_preset, since, until, breakdowns, filtering, limit, as_json):
    """GET /act_{ad_account_id}/insights?level=adset — sync ad-set-level insights."""
    acct = _require_account_id(account_id, as_json)
    try:
        params = _common_insights_params(fields, date_preset, since, until, breakdowns, filtering, limit, level="adset")
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    result = graph_request("GET", f"{acct}/insights", params=params, as_json=as_json)
    _emit_insights(result, as_json)


@insights.command("ad")
@_insights_options
def insights_ad(account_id, fields, date_preset, since, until, breakdowns, filtering, limit, as_json):
    """GET /act_{ad_account_id}/insights?level=ad — sync ad-level insights."""
    acct = _require_account_id(account_id, as_json)
    try:
        params = _common_insights_params(fields, date_preset, since, until, breakdowns, filtering, limit, level="ad")
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    result = graph_request("GET", f"{acct}/insights", params=params, as_json=as_json)
    _emit_insights(result, as_json)


# ── Async job pattern ────────────────────────────────────────
# See module docstring for exactly what is / isn't KB-confirmed about this mechanic.


@insights.command("async-submit")
@click.option("--level", type=click.Choice(LEVEL_CHOICES), default="campaign")
@_insights_options
def insights_async_submit(level, account_id, fields, date_preset, since, until, breakdowns, filtering, limit, as_json):
    """POST /act_{ad_account_id}/insights — start an async Insights report job.

    Returns a report-run identifier (commonly `report_run_id` in the response envelope) —
    pass it to `async-status` / `async-fetch`.
    """
    acct = _require_account_id(account_id, as_json)
    try:
        params = _common_insights_params(fields, date_preset, since, until, breakdowns, filtering, limit, level=level)
    except ValueError as e:
        raise SystemExit(print_error(str(e), code="VALIDATION", as_json=as_json))
    result = graph_request("POST", f"{acct}/insights", params=params, as_json=as_json)
    if as_json:
        print_json(result)
        return
    run_id = (result.get("report_run_id") or result.get("id")) if isinstance(result, dict) else None
    click.secho(f"✓ Submitted async insights job: {run_id or result}", fg="green")
    print_json(result)


@insights.command("async-status")
@click.argument("report_run_id")
@click.option("--json", "as_json", is_flag=True)
def insights_async_status(report_run_id, as_json):
    """GET /{report_run_id} — poll an async Insights job's status.

    `async_status` / `async_percent_completion` are the standard facebook-business SDK
    `AdReportRun` field names for this — see module docstring: [inference from stable
    public SDK convention, not independently confirmed in this KB pass]. As of v25.0, a
    failed job's error surfaces richer fields: error_code, error_message, error_subcode,
    error_user_title, error_user_msg.
    """
    result = graph_request(
        "GET", report_run_id,
        params={"fields": "id,async_status,async_percent_completion,date_start,date_stop"},
        as_json=as_json,
    )
    if as_json:
        print_json(result)
        return
    print_table([flatten(result)])


@insights.command("async-fetch")
@click.argument("report_run_id")
@click.option("--limit", "-l", type=int, default=None)
@click.option("--json", "as_json", is_flag=True)
def insights_async_fetch(report_run_id, limit, as_json):
    """GET /{report_run_id}/insights — fetch rows from a completed async job.

    Run `async-status` first and only fetch once `async_status` reads "Job Completed" —
    fetching an incomplete job typically returns an empty/partial `data` array rather than
    a hard error.
    """
    params = {}
    if limit:
        params["limit"] = limit
    result = graph_request("GET", f"{report_run_id}/insights", params=params, as_json=as_json)
    _emit_insights(result, as_json)
