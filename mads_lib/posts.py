"""mads_lib/posts.py — Facebook Page + Instagram organic content (posts/media).

Auth track: "Instagram API with Facebook Login" (NOT the newer standalone "Instagram
Login" track — see AGENTS.md Known Gotchas and generate_token.py's SCOPES list for why).
This track reuses the exact same Page Access Token mechanism `mads_lib/auth.py` already
implements for `page insights` (same graph.facebook.com host, same appsecret_proof
computation) — no separate Instagram-specific auth mechanism was built here. Every
network call below goes through `auth.graph_request_with_page_token()`.

Permissions required (see AGENTS.md's "Pre-implementation blocker" Known Gotcha — none
of these are granted on the live Talas token as of this module's creation, confirmed via
`GET /me/permissions`):
  - pages_manage_posts         — create_page_post, create_page_photo_post,
                                  create_page_video_post, delete_post
  - instagram_basic            — create_ig_container, list_posts(platform="instagram")
  - instagram_content_publish  — create_ig_container, publish_ig_container

Scheduling windows (Meta-documented, distinct per edge — validated client-side before
any network call so a rejected schedule fails fast with a clear message instead of an
opaque API error):
  - POST /{page-id}/feed    — 10 minutes to 30 days from now.
  - POST /{page-id}/videos  — 10 minutes to ~6 months (180 days) from now — much wider
    than the feed window.
  - Instagram (/media, /media_publish) — NO documented scheduled-publish equivalent.
    create_ig_container()/publish_ig_container() take no scheduling parameter at all —
    same "verify before adding" discipline pages.py already uses for the confirmed-dead
    reviews endpoint, rather than accepting a parameter the API would silently ignore.

Image/video inputs accept either a local file path or a remote URL — a URL is sent
under the API's own `url`/`file_url`/`image_url`/`video_url` param name (Meta fetches it
server-side); a local path is uploaded as multipart/form-data via the `source` field
(mirrors creatives.py's upload-image/upload-video convention).
"""
import time
from pathlib import Path

from .auth import get_access_token, graph_request_with_page_token
from .http import graph_request

_FEED_SCHEDULE_MIN_SECONDS = 10 * 60
_FEED_SCHEDULE_MAX_SECONDS = 30 * 24 * 60 * 60
_VIDEO_SCHEDULE_MIN_SECONDS = 10 * 60
_VIDEO_SCHEDULE_MAX_SECONDS = 180 * 24 * 60 * 60  # ~6 months

# KB: no formal Graph API enum reference found for /{ig-user-id}/media's media_type —
# these four are the values documented across Meta's Content Publishing guide.
VALID_IG_MEDIA_TYPES = ("IMAGE", "VIDEO", "REELS", "STORIES")

DEFAULT_LIST_POST_FIELDS = "id,message,created_time,permalink_url,status_type"
DEFAULT_LIST_IG_MEDIA_FIELDS = "id,caption,media_type,media_url,permalink,timestamp"


def _is_url(value):
    return isinstance(value, str) and (value.startswith("http://") or value.startswith("https://"))


def _validate_schedule_window(scheduled_publish_time, min_seconds, max_seconds, label):
    """Raise ValueError before any network call if `scheduled_publish_time` (a unix
    timestamp) falls outside the edge-specific window Meta documents — fails fast with a
    clear message instead of letting the call fail opaquely against the live API."""
    if scheduled_publish_time is None:
        return
    now = int(time.time())
    delta = int(scheduled_publish_time) - now
    if delta < min_seconds:
        raise ValueError(
            f"{label}: scheduled_publish_time is too soon — must be at least "
            f"{min_seconds // 60} minutes from now (got {delta}s from now)."
        )
    if delta > max_seconds:
        raise ValueError(
            f"{label}: scheduled_publish_time is too far out — must be no more than "
            f"{max_seconds // 86400} days from now (got {delta}s from now)."
        )


def create_page_post(page_id, message=None, link=None, scheduled_publish_time=None, as_json=False):
    """POST /{page-id}/feed — create a Page feed post (text and/or link).

    Requires `pages_manage_posts`. At least one of `message`/`link` is required.
    `scheduled_publish_time` (unix timestamp), if given, must be 10 minutes to 30 days
    from now — Meta's documented window for feed posts (distinct and narrower than
    /videos' ~6-month window; see create_page_video_post()).
    """
    if message is None and link is None:
        raise ValueError("create_page_post: at least one of message/link is required.")
    _validate_schedule_window(scheduled_publish_time, _FEED_SCHEDULE_MIN_SECONDS,
                               _FEED_SCHEDULE_MAX_SECONDS, "Feed post")

    body = {}
    if message is not None:
        body["message"] = message
    if link is not None:
        body["link"] = link
    if scheduled_publish_time is not None:
        body["published"] = False
        body["scheduled_publish_time"] = int(scheduled_publish_time)

    return graph_request_with_page_token(page_id, "POST", f"{page_id}/feed", json_body=body, as_json=as_json)


def create_page_photo_post(page_id, image_path_or_url, message=None, as_json=False):
    """POST /{page-id}/photos — publish a photo (with optional caption) to the Page feed.

    `image_path_or_url` may be a local file path or a remote URL: a URL is sent as the
    `url` param (Meta fetches it server-side); a local path is uploaded as
    multipart/form-data via the `source` field. Requires `pages_manage_posts`.
    """
    body = {}
    if message is not None:
        body["message"] = message

    if _is_url(image_path_or_url):
        body["url"] = image_path_or_url
        return graph_request_with_page_token(page_id, "POST", f"{page_id}/photos", json_body=body, as_json=as_json)

    path = Path(image_path_or_url)
    if not path.exists():
        raise ValueError(f"create_page_photo_post: local file not found: {image_path_or_url}")
    with path.open("rb") as f:
        files = {"source": (path.name, f.read())}
    return graph_request_with_page_token(page_id, "POST", f"{page_id}/photos", params=body, files=files, as_json=as_json)


def create_page_video_post(page_id, video_path_or_url, message=None, scheduled_publish_time=None, as_json=False):
    """POST /{page-id}/videos — publish a video (with optional caption) to the Page.

    Scheduling window is up to ~6 months (180 days) from now — much wider than feed
    posts' 30-day window (Meta-documented difference; validated separately here). Uses
    the API's `description` field for caption text (the /videos edge does not use
    `message` the way /feed and /photos do). `video_path_or_url` may be a local file
    path (uploaded as multipart/form-data via `source`) or a remote URL (sent as
    `file_url`, fetched server-side). Requires `pages_manage_posts`.
    """
    _validate_schedule_window(scheduled_publish_time, _VIDEO_SCHEDULE_MIN_SECONDS,
                               _VIDEO_SCHEDULE_MAX_SECONDS, "Video post")

    body = {}
    if message is not None:
        body["description"] = message
    if scheduled_publish_time is not None:
        body["published"] = False
        body["scheduled_publish_time"] = int(scheduled_publish_time)

    if _is_url(video_path_or_url):
        body["file_url"] = video_path_or_url
        return graph_request_with_page_token(page_id, "POST", f"{page_id}/videos", json_body=body, as_json=as_json)

    path = Path(video_path_or_url)
    if not path.exists():
        raise ValueError(f"create_page_video_post: local file not found: {video_path_or_url}")
    with path.open("rb") as f:
        files = {"source": (path.name, f.read())}
    return graph_request_with_page_token(page_id, "POST", f"{page_id}/videos", params=body, files=files, as_json=as_json)


def _resolve_page_id_for_ig_account(ig_account_id, as_json=False):
    """Find the Page whose linked `instagram_business_account.id` matches `ig_account_id`
    by walking GET /me/accounts (fields=id,name,instagram_business_account) — there is no
    documented reverse edge on the IG User node pointing back to its Page, so this is the
    only confirmed resolution path (same call shape auth.get_page_access_token() already
    makes, extended with one more field). Raises ValueError with the list of Pages the
    current token *does* manage if no match is found, so a caller can fall back to
    `--page-id` explicitly.
    """
    tok = get_access_token()
    result = graph_request(
        "GET", "me/accounts",
        params={"fields": "id,name,instagram_business_account"}, token=tok, as_json=as_json,
    )
    pages = result.get("data", []) if isinstance(result, dict) else []
    for p in pages:
        iba = p.get("instagram_business_account") or {}
        if iba.get("id") == ig_account_id:
            return p.get("id")

    managed = ", ".join(f"{p.get('id')} ({p.get('name')})" for p in pages) or "(none)"
    raise ValueError(
        f"Could not resolve a Page for ig_account_id {ig_account_id} via GET /me/accounts "
        f"— no linked Page found among the Pages this token manages: {managed}. Pass "
        f"page_id explicitly if this Instagram account's linked Page isn't listed here."
    )


def create_ig_container(ig_account_id, caption=None, image_url=None, video_url=None,
                         media_type="IMAGE", page_id=None, as_json=False):
    """POST /{ig-user-id}/media — create an Instagram media container (step 1 of 2).

    Two-step flow (Instagram API with Facebook Login track): this creates a container
    and returns its `id` (the `creation_id`); publish_ig_container() must be called next
    with that id to actually publish it — if that second call fails, the container is
    left orphaned (created but never published; Meta expires unpublished containers
    ~24h after creation). Requires `instagram_basic` + `instagram_content_publish`.

    Exactly one of `image_url`/`video_url` is required, matching `media_type`. No
    documented scheduled-publish equivalent for Instagram exists — unlike the FB feed/
    video functions above, this function takes no scheduling parameter.

    `page_id` — the Page Access Token used for this call is resolved via the Facebook
    Page linked to `ig_account_id` (its `instagram_business_account` field). If not
    given, it is auto-resolved via GET /me/accounts (see _resolve_page_id_for_ig_account()).
    """
    if media_type not in VALID_IG_MEDIA_TYPES:
        raise ValueError(f"create_ig_container: media_type must be one of {VALID_IG_MEDIA_TYPES}, got {media_type!r}.")
    if bool(image_url) == bool(video_url):
        raise ValueError("create_ig_container: pass exactly one of image_url/video_url.")
    if media_type == "IMAGE" and not image_url:
        raise ValueError("create_ig_container: media_type=IMAGE requires image_url.")
    if media_type in ("VIDEO", "REELS", "STORIES") and not video_url:
        raise ValueError(f"create_ig_container: media_type={media_type} requires video_url.")

    resolved_page_id = page_id or _resolve_page_id_for_ig_account(ig_account_id, as_json=as_json)

    body = {"media_type": media_type}
    if caption is not None:
        body["caption"] = caption
    if image_url is not None:
        body["image_url"] = image_url
    if video_url is not None:
        body["video_url"] = video_url

    return graph_request_with_page_token(resolved_page_id, "POST", f"{ig_account_id}/media", json_body=body, as_json=as_json)


def publish_ig_container(ig_account_id, creation_id, page_id=None, as_json=False):
    """POST /{ig-user-id}/media_publish — publish a previously-created container (step 2 of 2).

    If this call fails after create_ig_container() already succeeded, `creation_id` is
    orphaned — callers (see `post create-ig` in cli.py) must surface it in any error
    output so it isn't silently lost; Meta containers expire ~24h after creation if
    never published.
    """
    resolved_page_id = page_id or _resolve_page_id_for_ig_account(ig_account_id, as_json=as_json)
    body = {"creation_id": creation_id}
    return graph_request_with_page_token(
        resolved_page_id, "POST", f"{ig_account_id}/media_publish", json_body=body, as_json=as_json,
    )


def list_posts(object_id, platform="facebook", limit=25, fields=None, as_json=False):
    """GET /{object-id}/feed (Facebook) or GET /{object-id}/media (Instagram) — list
    recent posts/media. `platform` selects the edge name since Meta names it differently
    per product; `post list --page-id`/`--ig-account-id` in cli.py picks the right value
    automatically based on which flag was given.
    """
    if platform not in ("facebook", "instagram"):
        raise ValueError(f"list_posts: platform must be 'facebook' or 'instagram', got {platform!r}.")

    edge = "feed" if platform == "facebook" else "media"
    default_fields = DEFAULT_LIST_POST_FIELDS if platform == "facebook" else DEFAULT_LIST_IG_MEDIA_FIELDS
    params = {"fields": fields or default_fields}
    if limit:
        params["limit"] = limit

    if platform == "facebook":
        return graph_request_with_page_token(object_id, "GET", f"{object_id}/{edge}", params=params, as_json=as_json)

    # Instagram media listing is routed through the same Page-token path as every other
    # organic-content call in this module (uniform auth), rather than the general token.
    resolved_page_id = _resolve_page_id_for_ig_account(object_id, as_json=as_json)
    return graph_request_with_page_token(resolved_page_id, "GET", f"{object_id}/{edge}", params=params, as_json=as_json)


def delete_post(post_id, page_id, platform="facebook", as_json=False):
    """DELETE /{post-id} — delete a Facebook Page post. FB only.

    Instagram has no documented media-deletion operation via the Graph API for the
    Instagram API with Facebook Login track — pass platform="instagram" to get a clear,
    structural refusal here instead of attempting an opaque live API call; mirrors
    pages.py's precedent of refusing to build unverified functionality (see its module
    docstring re: Page reviews). Re-verify live against Meta's Instagram Content
    Publishing docs before ever lifting this restriction.
    """
    if platform == "instagram":
        raise ValueError(
            "delete_post: Instagram media deletion is not a documented Graph API "
            "operation for the Instagram API with Facebook Login track — refusing to "
            "attempt it. FB Page posts only (platform='facebook', the default)."
        )
    if platform != "facebook":
        raise ValueError(f"delete_post: platform must be 'facebook' or 'instagram', got {platform!r}.")

    return graph_request_with_page_token(page_id, "DELETE", post_id, as_json=as_json)
