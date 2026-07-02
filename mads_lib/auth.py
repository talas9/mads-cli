"""Credential loading for mads-cli.

Unlike gads-cli's Google OAuth `Credentials` object, Meta access tokens
(System User tokens or long-lived user tokens) do not self-refresh
transparently — there is no `refresh_token` dance to perform on every call.
This module is intentionally simple: load the bearer token string from disk,
and provide a helper to compute the `appsecret_proof` HMAC that Meta's Graph
API expects on every authenticated request when App Secret Proof is enabled.

See generate_token.py for how MADS_CREDENTIALS_PATH is produced.
"""
import contextlib
import hashlib
import hmac
import io
import json
import sys

import click

from .config import APP_SECRET, CREDS_PATH, PAGE_TOKENS_PATH
from .output import EXIT_CODES


def get_access_token():
    """Load the bearer token string from MADS_CREDENTIALS_PATH.

    Returns the raw access_token string. Exits with a clear error if the
    credentials file is missing or malformed.
    """
    if not CREDS_PATH.exists():
        click.secho(f"✗ Credentials not found: {CREDS_PATH}", fg="red", err=True)
        click.secho("  Run: python generate_token.py", fg="yellow", err=True)
        raise SystemExit(1)

    with open(CREDS_PATH) as f:
        try:
            creds_data = json.load(f)
        except json.JSONDecodeError as e:
            click.secho(f"✗ Credentials file is not valid JSON: {CREDS_PATH} ({e})", fg="red", err=True)
            raise SystemExit(1)

    token = creds_data.get("access_token")
    if not token:
        click.secho(f"✗ No access_token found in {CREDS_PATH}", fg="red", err=True)
        raise SystemExit(1)

    return token


def get_appsecret_proof(token=None):
    """Compute the `appsecret_proof` HMAC-SHA256 for a Meta access token.

    Meta requires this on every call when "Require App Secret" is enabled for
    the app: `appsecret_proof = HMAC-SHA256(key=app_secret, msg=access_token)`
    (hex digest). See:
    https://developers.facebook.com/docs/graph-api/securing-requests

    If `token` is not given, loads it via `get_access_token()`.
    """
    if token is None:
        token = get_access_token()

    if not APP_SECRET:
        click.secho("✗ META_APP_SECRET is not set — cannot compute appsecret_proof.", fg="red", err=True)
        raise SystemExit(1)

    return hmac.new(
        APP_SECRET.encode("utf-8"),
        msg=token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def _load_page_token_cache():
    """Load the on-disk Page Access Token cache ({page_id: access_token}).

    Returns an empty dict if the file is missing, empty, or malformed — the
    cache is a best-effort optimization, not a source of truth (the source of
    truth is `GET /me/accounts`), so a corrupt cache file should never be
    fatal.
    """
    if not PAGE_TOKENS_PATH.exists():
        return {}
    try:
        with open(PAGE_TOKENS_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def get_page_access_token(page_id, user_token=None, force_refresh=False):
    """Return a Page Access Token for `page_id`, fetching + caching it if needed.

    Why this exists: page-scoped Graph API calls — notably `GET
    /{page-id}/insights` — require a *Page* Access Token, not the general
    user/system-user token loaded by `get_access_token()`. Passing the wrong
    kind of token gets you Meta error code 190, "This method must be called
    with a Page Access Token" (distinct from 190's more common meaning of an
    expired/invalid token). `GET /{page-id}` (Page profile info) does *not*
    need a Page token — only page-scoped edges like `/insights` do — so
    `mads_lib/pages.py::page_info` deliberately keeps using the general
    token; only `page_insights` calls this function.

    A Page Access Token is obtained via `GET /me/accounts` (returns each
    Page the calling user manages, plus a page-scoped `access_token` for
    each), authenticated with the *user* token from `MADS_CREDENTIALS_PATH`.

    Caching rationale — verified live (2026-07-02) by running Meta's
    `GET /debug_token` against a freshly-issued Page Access Token: the
    response showed `expires_at: 0`, which per Meta's convention means the
    token does not expire. This holds even though the *user* token it was
    derived from is a 60-day token (has a real `expires_at`) — Page Access
    Tokens obtained from a Business "Login for Business" user token get
    their own long-lived/non-expiring lifetime, independent of the parent
    user token's expiry. Because of that, caching this token to disk (rather
    than re-fetching it via `/me/accounts` on every single Page-scoped call)
    is correct and safe, mirroring how `get_access_token()` treats the main
    credentials file. It can still be invalidated out-of-band (password
    change, app deauthorization, the granting user's `pages_show_list`/
    `pages_read_engagement` scope being revoked) — callers that get a 190
    back despite a cache hit should retry once with `force_refresh=True`
    (see `mads_lib/pages.py::page_insights` for that retry).

    Cached at `PAGE_TOKENS_PATH` (default
    `credentials/meta-page-tokens.json`, gitignored alongside the rest of
    `credentials/`) as a flat `{page_id: access_token}` map — every Page
    returned by `/me/accounts` is cached in the same pass, not just the one
    requested, since the call is already paid for.
    """
    if not force_refresh:
        cached = _load_page_token_cache().get(page_id)
        if cached:
            return cached

    from .http import graph_request  # local import: http.py imports this module at load time

    tok = user_token or get_access_token()
    result = graph_request(
        "GET", "me/accounts", params={"fields": "id,name,access_token"}, token=tok,
    )
    pages = result.get("data", []) if isinstance(result, dict) else []

    cache = _load_page_token_cache()
    found = None
    for p in pages:
        pid, ptok = p.get("id"), p.get("access_token")
        if pid and ptok:
            cache[pid] = ptok
        if pid == page_id:
            found = ptok

    if found is None:
        managed = ", ".join(f"{p.get('id')} ({p.get('name')})" for p in pages) or "(none)"
        click.secho(
            f"✗ No Page Access Token available for page_id {page_id} — it was not "
            f"returned by GET /me/accounts for the current user token. Either this "
            f"page isn't managed by that user, or the token is missing pages_show_list "
            f"scope. Pages the current token *does* manage: {managed}",
            fg="red", err=True,
        )
        raise SystemExit(1)

    PAGE_TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PAGE_TOKENS_PATH, "w") as f:
        json.dump(cache, f, indent=2)

    return found


def graph_request_with_page_token(page_id, method, path, *, params=None, json_body=None,
                                   files=None, timeout=30, as_json=False, user_token=None):
    """Call the Graph API against `path` using a cached Page Access Token for `page_id`,
    retrying exactly once with a freshly-fetched token if the cached one turns out to have
    been invalidated out-of-band (Meta error 190, AUTH).

    Promoted from `mads_lib/pages.py`'s original `_insights_request_with_retry()` (which
    only handled `GET /{page_id}/insights`) into this general-purpose helper so every
    page-token-scoped edge shares one cache/retry implementation instead of duplicating it:
    Page Insights and Page profile updates (`pages.py`), and the organic-content endpoints
    in `posts.py`/`comments.py` (feed/photos/videos, and Instagram's two-step
    /media -> /media_publish flow — the "Instagram API with Facebook Login" track uses this
    exact same Page Access Token mechanism, not a separate Instagram-specific token).

    See `get_page_access_token()`'s docstring for why disk-caching a Page token is safe
    (confirmed non-expiring, independent of the parent user token's own expiry) and why a
    single retry-on-190 is the right response to out-of-band invalidation rather than a
    full retry loop. `user_token`, if given, is forwarded to `get_page_access_token()` for
    the (rare) case a caller already holds a user token and wants to skip the
    `get_access_token()` file read.
    """
    from .http import graph_request  # local import: http.py imports this module at load time

    page_token = get_page_access_token(page_id, user_token=user_token)
    out_buf, err_buf = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            return graph_request(method, path, params=params, json_body=json_body, files=files,
                                  token=page_token, timeout=timeout, as_json=as_json)
    except SystemExit as exc:
        if exc.code == EXIT_CODES["AUTH"]:
            page_token = get_page_access_token(page_id, user_token=user_token, force_refresh=True)
            return graph_request(method, path, params=params, json_body=json_body, files=files,
                                  token=page_token, timeout=timeout, as_json=as_json)
        sys.stdout.write(out_buf.getvalue())
        sys.stderr.write(err_buf.getvalue())
        raise
