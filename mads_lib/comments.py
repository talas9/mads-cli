"""mads_lib/comments.py — Facebook Page + Instagram comment moderation.

Auth: `page_id`, if given, routes a call through the shared Page Access Token helper
(`auth.graph_request_with_page_token()` — same mechanism `posts.py` and `page insights`
use). If omitted, calls fall back to the general user/system-user token via
`http.graph_request()` — sufficient for reading public comment data in most cases, but
moderation actions (hide/delete/reply) on comments under a Page you don't personally
hold an admin token for may require the Page Access Token; pass `page_id` in that case.
`cli.py`'s `comment` command group does not currently expose a `--page-id` option (see
its command docstrings) — pass it directly when calling these functions as a library
(e.g. from adops-manager).

Permissions: `pages_manage_engagement` (FB comment moderation) + `instagram_manage_comments`
(IG comment moderation) — neither is granted on the live Talas token as of this module's
creation; see AGENTS.md Known Gotchas.

Platform asymmetry (real, not an oversight): Instagram has no documented way to create a
brand-new *top-level* comment on your own media via the Graph API — only replies to
existing comments (POST /{comment-id}/comments) are supported. Facebook supports both: a
new top-level comment on a post (POST /{post-id}/comments) and a threaded reply
(POST /{comment-id}/comments, which also works identically for Instagram).
"""
from .auth import graph_request_with_page_token
from .http import graph_request

DEFAULT_COMMENT_FIELDS = "id,message,from,created_time,like_count,comment_count,is_hidden"


def list_comments(object_id, page_id=None, limit=25, fields=DEFAULT_COMMENT_FIELDS, as_json=False):
    """GET /{object-id}/comments — list comments on a Facebook post or Instagram media.

    `object_id` is a post_id (FB) or media_id (IG).
    """
    params = {"fields": fields}
    if limit:
        params["limit"] = limit
    if page_id:
        return graph_request_with_page_token(page_id, "GET", f"{object_id}/comments", params=params, as_json=as_json)
    return graph_request("GET", f"{object_id}/comments", params=params, as_json=as_json)


def reply_comment(post_id=None, comment_id=None, message=None, page_id=None, as_json=False):
    """POST /{post-id}/comments (new top-level FB comment) or POST /{comment-id}/comments
    (threaded reply — works identically for FB and IG). Exactly one of post_id/comment_id
    is required.

    Instagram has no documented way to create a brand-new top-level comment on your own
    media — only `comment_id` (threaded reply) is supported for IG. Passing `post_id`
    against an IG media id is not pre-flight-blocked here (the platform can't be inferred
    from the id alone without an extra lookup call this function doesn't make) — it will
    fail against the live API with Meta's own error instead.
    """
    if message is None or not str(message).strip():
        raise ValueError("reply_comment: message is required.")
    if bool(post_id) == bool(comment_id):
        raise ValueError("reply_comment: pass exactly one of post_id/comment_id.")

    target = post_id or comment_id
    body = {"message": message}
    if page_id:
        return graph_request_with_page_token(page_id, "POST", f"{target}/comments", json_body=body, as_json=as_json)
    return graph_request("POST", f"{target}/comments", json_body=body, as_json=as_json)


def hide_comment(comment_id, hide=True, page_id=None, as_json=False):
    """POST /{comment-id} with is_hidden — hide or unhide a comment."""
    body = {"is_hidden": bool(hide)}
    if page_id:
        return graph_request_with_page_token(page_id, "POST", comment_id, json_body=body, as_json=as_json)
    return graph_request("POST", comment_id, json_body=body, as_json=as_json)


def delete_comment(comment_id, page_id=None, as_json=False):
    """DELETE /{comment-id} — permanently delete a comment."""
    if page_id:
        return graph_request_with_page_token(page_id, "DELETE", comment_id, as_json=as_json)
    return graph_request("DELETE", comment_id, as_json=as_json)
