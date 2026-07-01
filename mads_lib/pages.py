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
    window per request.

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
import click

from .http import graph_request
from .output import print_json, print_table, print_error, flatten

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
}
# The 10s-tier video-view family has no documented 1:1 replacement (graph-api.md notes this
# explicitly) — matched by prefix rather than exact name since there are several sub-metrics.
DEPRECATED_10S_PREFIXES = ("page_video_views_10s", "post_video_views_10s")

DEFAULT_PAGE_FIELDS = (
    "id,name,about,category,category_list,fan_count,followers_count,link,phone,website,"
    "username,verification_status,is_published,is_permanently_closed,single_line_address,"
    "checkins,talking_about_count,overall_star_rating,rating_count"
)


def _check_deprecated_metrics(metric_csv, as_json):
    """Reject any metric confirmed dead as of 2026-06-15 before calling the API."""
    if not metric_csv:
        return
    requested = [m.strip() for m in metric_csv.split(",") if m.strip()]
    bad = []
    for m in requested:
        if m in DEPRECATED_METRIC_REPLACEMENTS:
            bad.append(f"{m} (dead since 2026-06-15 — use {DEPRECATED_METRIC_REPLACEMENTS[m]})")
        elif m.startswith(DEPRECATED_10S_PREFIXES):
            bad.append(f"{m} (dead since 2026-06-15 — no documented 1:1 replacement; use the 3s or 30s tier)")
    if bad:
        raise SystemExit(print_error(
            "Requested metric(s) are dead on every API version as of 2026-06-15: " + "; ".join(bad),
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


@page.command("insights")
@click.argument("page_id")
@click.option("--metric", required=True, help="Comma-separated metric name(s).")
@click.option("--period", type=click.Choice(["day", "week", "days_28", "month", "lifetime", "total_over_range"]), default="day")
@click.option("--since", default=None, help="Range start (YYYY-MM-DD). Max 90-day window per request.")
@click.option("--until", default=None, help="Range end (YYYY-MM-DD).")
@click.option("--json", "as_json", is_flag=True)
def page_insights(page_id, metric, period, since, until, as_json):
    """GET /{page_id}/insights — organic Page/Post Insights metrics.

    Pre-flight-rejects any metric confirmed dead as of 2026-06-15 (see module docstring)
    instead of letting the call fail opaquely against the live API.
    """
    _check_deprecated_metrics(metric, as_json)
    params = {"metric": metric, "period": period}
    if since:
        params["since"] = since
    if until:
        params["until"] = until
    result = graph_request("GET", f"{page_id}/insights", params=params, as_json=as_json)
    rows = result.get("data", []) if isinstance(result, dict) else []
    if as_json:
        print_json(result)
        return
    print_table([flatten(r) for r in rows]) if rows else print_json(result)
