"""Page profile info + organic Page Insights ONLY.

This module deliberately implements NO reviews/ratings and NO reply-review command of any
kind. See the deprecation notice below before ever adding one.

Confirmed against kb/graph-api.md ("Pages" section):

  - GET /{page-id} — Page profile info. Field table (SDK-confirmed,
    `facebook_business/adobjects/page.py::Page.Field`): id, name, about, description,
    category, category_list, fan_count, followers_count, link, phone, website, username,
    verification_status, is_published, is_permanently_closed, checkins,
    single_line_address, talking_about_count, overall_star_rating, rating_count, emails.
    (`is_verified` is deprecated in favor of `verification_status`; `keywords` returns
    null; `breaking_news_usage` is marked deprecated — none of those three are requested
    by default here.)
  - GET /{page-id}/insights — organic Page/Post Insights. Hard limits (doc-confirmed):
    requires 100+ Page likes before most metrics populate; most metrics refresh once every
    24h; only the last 2 years of data is retained/queryable; max 90-day `since`/`until`
    window per request. **Requires a Page Access Token, not the general user/system-user
    token** — see get_page_access_token() below for why, and kb/graph-api.md's Gotcha #12
    for the full live verification.

  - DEPRECATED as of 2026-06-15, already live for every API version as of this KB's
    2026-07-01 fetch date (graph-api.md, "DEPRECATED as of June 15, 2026" table):
    page_impressions_unique, page_posts_impressions_unique,
    page_posts_impressions_organic_unique, page_posts_impressions_nonviral_unique,
    post_impressions, post_impressions_unique, post_impressions_fan_unique,
    post_impressions_organic_unique, post_impressions_nonviral_unique,
    page_video_views_unique, post_video_views_unique, and every
    page_video_views_10s*/post_video_views_10s* sub-breakdown (no documented 1:1
    replacement for the 10s family). This module pre-flight-rejects any of these with a
    clear VALIDATION error (naming the confirmed replacement metric where one exists)
    instead of letting the call fail opaquely against a dead metric.

  - ALSO CONFIRMED DEAD by live testing on 2026-07-02 (error #100 "not a valid insights
    metric", using a real Page Access Token — not a token-type confusion): page_impressions,
    page_fans, page_fan_adds, page_fan_adds_unique, page_fan_removes, page_fans_locale,
    page_fans_city, page_fans_country, page_impressions_paid, page_impressions_viral,
    page_impressions_nonviral, page_engaged_users. None of these were in graph-api.md's
    originally-documented June 15, 2026 deprecation table — that table (and the KB's
    "current metrics" table) was stale/wrong for these. See CONFIRMED_DEAD_NO_REPLACEMENT
    below and kb/graph-api.md's corrected metrics tables.

  - Reviews/Recommendations — CONFIRMED DEAD, do not resurrect this:
    `GET /{page-id}/ratings` and `GET /{recommendation-id}` return error code 12 on
    **every** API version as of 2025-09-09 (graph-api.md, "GET /{page-id}/ratings —
    DEPRECATED" section, itself dating the underlying deprecation to the v22.0 changelog,
    2025-01-21, later made version-independent on 2025-09-09). `POST`/`DELETE` on this edge
    were "never supported ... 'You can't perform this operation on this endpoint'."
    Separately, and even further back: there has **never** been a first-class "reply to
    review" endpoint on the Graph API (unlike Google Business Profile's
    `accounts.locations.reviews.updateReply` — see gbp.md). The one historical workaround
    developers used, `POST /{review-id}/comments`, was itself killed in API v2.4 (circa
    2015/2016), a full decade before the 2025-09-09 ratings-read deprecation, and today
    returns `"(#12) singular statuses API is deprecated for versions v2.4 and higher"` — the
    same error code 12, for a completely different and much older reason. Net effect, per
    graph-api.md verbatim: **"there is no path, past or present, to programmatically reply
    to a Facebook Page review/recommendation."** THEREFORE this module contains no
    `reviews`, `ratings`, or `reply-review` command — do not add one without first
    re-fetching developers.facebook.com/docs/graph-api/reference/page/ratings/ live and
    confirming the situation has actually changed.
"""
import json

import click

from .auth import graph_request_with_page_token
from .db import get_db
from .http import graph_request
from .output import print_json, print_table, print_error, flatten
from .timeutil import now_local

# Metrics confirmed dead for every API version as of 2026-06-15 (graph-api.md, "DEPRECATED
# as of June 15, 2026" table) — pre-flight-blocked below instead of sent to the API.
DEPRECATED_METRIC_REPLACEMENTS = {
    "page_impressions_unique": "page_total_media_view_unique",
    "page_posts_impressions_unique": "post_total_media_view_unique",
    "page_posts_impressions_organic_unique": "post_total_media_view_unique",
    "page_posts_impressions_nonviral_unique": "post_total_media_view_unique",
    "post_impressions": "post_media_view",
    "post_impressions_unique": "post_total_media_view_unique",
    "post_impressions_fan_unique": "post_total_media_view_unique",
    "post_impressions_organic_unique": "post_total_media_view_unique",
    "post_impressions_nonviral_unique": "post_total_media_view_unique",
    "page_video_views_unique": "page_total_media_view_unique",
    "post_video_views_unique": "post_total_media_view_unique",
    # Confirmed dead by LIVE testing against the real Meta Graph API on 2026-07-02 (GET
    # /{page-id}/insights, error (#100) "The value must be a valid insights metric" — a
    # distinct failure mode from "no data because <100 Page likes", which returns an empty
    # `data: []` with no error). graph-api.md's "current (non-deprecated) metrics" table
    # was stale/wrong in listing this one as current. Replacement follows the same
    # impression→media-view semantic shift documented for `page_impressions_unique`.
    "page_impressions": "page_media_view",
}
# The 10s-tier video-view family has no documented 1:1 replacement (graph-api.md notes this
# explicitly) — matched by prefix rather than exact name since there are several sub-metrics.
DEPRECATED_10S_PREFIXES = ("page_video_views_10s", "post_video_views_10s")

# Also confirmed dead by the same 2026-07-02 live test (error #100, same as above), but with
# no confirmed replacement metric found live or documented anywhere in graph-api.md — kept
# separate from DEPRECATED_METRIC_REPLACEMENTS so the error message never invents a
# replacement that hasn't actually been verified to work. `page_engaged_users` in particular
# predates the June 2026 wave entirely (it's a pre-2018-era Insights metric name) and was
# already dead independent of that deprecation.
CONFIRMED_DEAD_NO_REPLACEMENT = (
    "page_impressions_paid",
    "page_impressions_viral",
    "page_impressions_nonviral",
    "page_fans",
    "page_fan_adds",
    "page_fan_adds_unique",
    "page_fan_removes",
    "page_fans_locale",
    "page_fans_city",
    "page_fans_country",
    "page_engaged_users",
)

DEFAULT_PAGE_FIELDS = (
    "id,name,about,category,category_list,fan_count,followers_count,link,phone,website,"
    "username,verification_status,is_published,is_permanently_closed,single_line_address,"
    "checkins,talking_about_count,overall_star_rating,rating_count"
)


def _check_deprecated_metrics(metric_csv, as_json):
    """Reject any metric confirmed dead — either by graph-api.md's documented 2026-06-15
    deprecation wave, or by live 2026-07-02 testing that found additional dead metrics the
    KB had (incorrectly) still listed as current — before calling the API."""
    if not metric_csv:
        return
    requested = [m.strip() for m in metric_csv.split(",") if m.strip()]
    bad = []
    for m in requested:
        if m in DEPRECATED_METRIC_REPLACEMENTS:
            bad.append(f"{m} (dead — use {DEPRECATED_METRIC_REPLACEMENTS[m]})")
        elif m.startswith(DEPRECATED_10S_PREFIXES):
            bad.append(f"{m} (dead since 2026-06-15 — no documented 1:1 replacement; use the 3s or 30s tier)")
        elif m in CONFIRMED_DEAD_NO_REPLACEMENT:
            bad.append(f"{m} (confirmed dead by live testing on 2026-07-02 — no replacement metric confirmed; see kb/graph-api.md's current-metrics table for valid alternatives)")
    if bad:
        raise SystemExit(print_error(
            "Requested metric(s) are dead / rejected by the Graph API: " + "; ".join(bad),
            code="VALIDATION", as_json=as_json,
        ))


@click.group()
def page():
    """Page profile info + organic Insights (NO reviews — see module docstring)."""


@page.command("info")
@click.argument("page_id")
@click.option("--fields", default=DEFAULT_PAGE_FIELDS)
@click.option("--json", "as_json", is_flag=True)
def page_info(page_id, fields, as_json):
    """GET /{page_id} — Page profile info.

    `overall_star_rating`/`rating_count` remain in the field schema even though the
    per-review `ratings` edge is dead — graph-api.md flags these two summary numbers as
    (unverified) whether they still update live; do not build a reviews UI around them.
    """
    result = graph_request("GET", page_id, params={"fields": fields}, as_json=as_json)
    if as_json:
        print_json(result)
        return
    print_table([flatten(result)])


def _confirm_and_log(action, details, dry_run=False, yes=False):
    if dry_run:
        click.secho(f"  DRY RUN: {action} — {details}", fg="yellow")
        return False
    if not yes:
        click.confirm(f"  Execute: {action}?", abort=True)
    return True


def _auto_log(action, details, campaign_name="", campaign_id=""):
    """Best-effort changelog write; never raises (mirrors mads_lib.cli._auto_log /
    mads_lib.creatives._auto_log — duplicated per resource-group module, see
    creatives.py's module docstring)."""
    try:
        conn = get_db()
        ts = now_local()
        raw = {
            "timestamp": ts, "action": action, "details": details,
            "campaign": campaign_name, "campaign_id": campaign_id, "agent": "mads-cli",
        }
        conn.execute(
            "INSERT INTO changelog (timestamp, action, campaign, campaign_id, details, "
            "reason, agent, snapshot_ref, script, raw_json, platform) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, action, campaign_name, campaign_id, details, "", "mads-cli", "", "", json.dumps(raw), "meta_ads"),
        )
        conn.commit()
        conn.close()
    except (Exception, SystemExit):
        pass


def _insights_request_with_retry(page_id, params, as_json):
    """Call GET /{page_id}/insights via the shared Page Access Token cache/retry helper
    (`auth.graph_request_with_page_token()`, promoted from this function's original
    implementation — see its docstring for the full cache/retry-on-190 rationale).
    """
    return graph_request_with_page_token(page_id, "GET", f"{page_id}/insights", params=params, as_json=as_json)


@page.command("insights")
@click.argument("page_id")
@click.option("--metric", required=True, help="Comma-separated metric name(s).")
@click.option("--period", type=click.Choice(["day", "week", "days_28", "month", "lifetime", "total_over_range"]), default="day")
@click.option("--since", default=None, help="Range start (YYYY-MM-DD). Max 90-day window per request.")
@click.option("--until", default=None, help="Range end (YYYY-MM-DD).")
@click.option("--json", "as_json", is_flag=True)
def page_insights(page_id, metric, period, since, until, as_json):
    """GET /{page_id}/insights — organic Page/Post Insights metrics.

    Pre-flight-rejects any metric confirmed dead as of 2026-06-15, or confirmed dead by
    live 2026-07-02 testing (see module docstring), instead of letting the call fail
    opaquely against the live API.

    Unlike `page info`, this edge requires a **Page Access Token** — Meta returns error
    190 ("This method must be called with a Page Access Token") for the general
    user/system-user token here. `get_page_access_token()` fetches (and disk-caches) one
    via `GET /me/accounts`; see its docstring in auth.py for why caching is safe (the
    Page token is long-lived/non-expiring independent of the parent user token's own
    expiry). If the cached token has been invalidated out-of-band since it was cached,
    the call is retried exactly once with a freshly-fetched token before giving up.
    """
    _check_deprecated_metrics(metric, as_json)
    params = {"metric": metric, "period": period}
    if since:
        params["since"] = since
    if until:
        params["until"] = until

    result = _insights_request_with_retry(page_id, params, as_json)
    rows = result.get("data", []) if isinstance(result, dict) else []
    if as_json:
        print_json(result)
        return
    print_table([flatten(r) for r in rows]) if rows else print_json(result)


def update_page_info(page_id, about=None, phone=None, website=None, hours=None,
                      description=None, as_json=False):
    """POST /{page-id} — update Page profile fields.

    Permission: `pages_manage_metadata` — not previously requested by this CLI (added to
    `generate_token.py`'s SCOPES alongside the `post`/`comment` command groups; see
    AGENTS.md Known Gotchas for the current permission-grant status). Only the fields
    explicitly given are sent — Meta's POST /{page-id} is a partial-update, not a
    full-replace, so omitted fields are left untouched server-side.

    Routed through the same Page Access Token mechanism as `page insights`
    (`auth.graph_request_with_page_token()`) — editing Page metadata, like reading Page
    Insights, requires a Page Access Token rather than the general user/system-user token.

    `hours` — Page opening hours — must already be shaped to Meta's documented format (a
    flat dict keyed `"{day_index}_{open|close}_time"` for day_index 0=Monday..6=Sunday,
    e.g. `{"1_open_time": "09:00", "1_close_time": "17:00"}` for Tuesday); this function
    passes it through as given rather than reshaping/validating it.
    """
    body = {}
    if about is not None:
        body["about"] = about
    if phone is not None:
        body["phone"] = phone
    if website is not None:
        body["website"] = website
    if hours is not None:
        body["hours"] = hours
    if description is not None:
        body["description"] = description
    if not body:
        raise ValueError(
            "update_page_info: at least one of about/phone/website/hours/description is required."
        )
    return graph_request_with_page_token(page_id, "POST", page_id, json_body=body, as_json=as_json)


@page.command("update")
@click.argument("page_id")
@click.option("--about", default=None)
@click.option("--phone", default=None)
@click.option("--website", default=None)
@click.option("--hours-json", default=None, help='JSON object, e.g. {"1_open_time": "09:00", "1_close_time": "17:00"}.')
@click.option("--description", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--yes", "-y", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def page_update(page_id, about, phone, website, hours_json, description, dry_run, yes, as_json):
    """POST /{page_id} — update Page profile fields (about/phone/website/hours/description).

    Requires `pages_manage_metadata` — see AGENTS.md Known Gotchas for the current
    permission-grant status on this account before expecting this to succeed live.
    """
    from .cli import enforce_allowed_caller
    enforce_allowed_caller()
    hours = None
    if hours_json:
        try:
            hours = json.loads(hours_json)
        except json.JSONDecodeError as e:
            raise SystemExit(print_error(f"--hours-json is not valid JSON: {e}", code="VALIDATION", as_json=as_json))
    if about is None and phone is None and website is None and hours is None and description is None:
        raise SystemExit(print_error(
            "At least one of --about/--phone/--website/--hours-json/--description is required.",
            code="VALIDATION", as_json=as_json,
        ))

    if not _confirm_and_log(f"update page {page_id}", "page update", dry_run, yes):
        return
    result = update_page_info(
        page_id, about=about, phone=phone, website=website, hours=hours,
        description=description, as_json=as_json,
    )
    _auto_log("page_update", f"page {page_id}", campaign_id=page_id)
    if as_json:
        print_json(result)
        return
    click.secho(f"✓ Updated page {page_id}", fg="green")
