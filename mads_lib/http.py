"""Shared Meta Graph API HTTP wrapper.

Base URL: https://graph.facebook.com/{API_VERSION}/

Every call appends `access_token` and `appsecret_proof` (see auth.py) to the
request params. Meta's error envelope shape differs from Google's — errors
come back as a top-level `error` object:

    {"error": {"message": "...", "type": "OAuthException", "code": 190,
               "error_subcode": 460, "fbtrace_id": "..."}}

`classify_meta_error()` maps known `code` values to one of mads-cli's
EXIT_CODES (see output.py), most notably code 190 (expired/invalid token) to
AUTH, and Meta's rate-limiting codes (4, 17, 32, 613) to the mads-cli-specific
RATE_LIMIT exit code that gads-cli does not define.
"""
import json
import sys

import click
import requests

from .auth import get_access_token, get_appsecret_proof
from .config import API_VERSION
from .output import EXIT_CODES, print_error

BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

# Meta hard batch limit: https://developers.facebook.com/docs/graph-api/batch-requests
MAX_BATCH_OPS = 50

# Known Graph API error codes → mads-cli EXIT_CODES key.
# Reference: https://developers.facebook.com/docs/graph-api/guides/error-handling
_ERROR_CODE_MAP = {
    190: "AUTH",       # Invalid OAuth access token / token expired
    102: "AUTH",       # Session key invalid or no longer valid
    2500: "VALIDATION",  # An active access token must be used to query information (malformed)
    100: "VALIDATION",  # Invalid parameter
    200: "AUTH",       # Permissions error
    10: "AUTH",        # Application does not have permission for this action
    4: "RATE_LIMIT",   # Application request limit reached
    17: "RATE_LIMIT",  # User request limit reached
    32: "RATE_LIMIT",  # Page request limit reached
    613: "RATE_LIMIT",  # Calls to this API have exceeded the rate limit
    80004: "RATE_LIMIT",  # Ads Insights: too many calls to ad account
    803: "NOT_FOUND",  # (#803) Some of the aliases you requested do not exist
}


def classify_meta_error(status_code, response_json):
    """Classify a Meta Graph API error envelope.

    Returns a dict {code, message, error_code, error_subcode, error_type,
    fbtrace_id, exit_code}, or None if `response_json` has no `error` object.
    """
    if not isinstance(response_json, dict):
        return None
    error = response_json.get("error")
    if not isinstance(error, dict):
        return None

    fb_code = error.get("code")
    exit_key = _ERROR_CODE_MAP.get(fb_code)
    if exit_key is None:
        # 4xx/5xx without a known code still gets a reasonable default.
        if status_code == 401:
            exit_key = "AUTH"
        elif status_code == 404:
            exit_key = "NOT_FOUND"
        elif status_code == 429:
            exit_key = "RATE_LIMIT"
        else:
            exit_key = "API"

    return {
        "code": exit_key,
        "message": error.get("message", "Unknown Meta Graph API error"),
        "error_code": fb_code,
        "error_subcode": error.get("error_subcode"),
        "error_type": error.get("type"),
        "fbtrace_id": error.get("fbtrace_id"),
        "exit_code": EXIT_CODES.get(exit_key, EXIT_CODES["API"]),
    }


def _auth_params(token=None):
    """Build the {access_token, appsecret_proof} param dict for a request."""
    tok = token or get_access_token()
    return {
        "access_token": tok,
        "appsecret_proof": get_appsecret_proof(tok),
    }


def graph_request(method, path, *, params=None, json_body=None, files=None, token=None,
                   timeout=30, as_json=False):
    """Make a single Graph API request.

    `path` may be a full node/edge path like "act_123/campaigns" or "me" —
    it is joined onto BASE_URL. Absolute URLs (starting with "http") are used
    as-is (useful for paging `next`/`previous` links Meta returns verbatim).

    `files`, if given, switches this call to multipart/form-data — used by the
    two binary-upload endpoints (POST act_{id}/adimages, POST act_{id}/advideos).
    In that mode `params` (including the injected access_token/appsecret_proof)
    travel as multipart form fields via `data=`, not the query string, and
    `json_body` is ignored — Meta does not accept a JSON body alongside a
    multipart upload.
    """
    if path.startswith("http://") or path.startswith("https://"):
        url = path
    else:
        url = f"{BASE_URL}/{path.lstrip('/')}"

    merged_params = dict(params or {})
    merged_params.update(_auth_params(token))

    try:
        if files:
            resp = requests.request(
                method,
                url,
                data=merged_params,
                files=files,
                timeout=timeout,
            )
        else:
            resp = requests.request(
                method,
                url,
                params=merged_params,
                json=json_body,
                timeout=timeout,
            )
    except requests.exceptions.Timeout:
        raise SystemExit(print_error(
            f"Request to Meta Graph API timed out after {timeout}s ({method} {url}). "
            "This is a network/latency issue, not a Meta API error — retry, or pass a "
            "longer timeout if it persists.",
            code="API", as_json=as_json,
        ))
    except requests.exceptions.ConnectionError as e:
        raise SystemExit(print_error(
            f"Could not reach the Meta Graph API ({method} {url}): {e}. "
            "The request never reached graph.facebook.com — check your network "
            "connection, DNS, or firewall/proxy settings.",
            code="API", as_json=as_json,
        ))
    except requests.exceptions.RequestException as e:
        # Catch-all for other network-layer failures (SSL errors, too-many-redirects,
        # etc.) that are distinct from an HTTP-level 4xx/5xx API error below.
        raise SystemExit(print_error(
            f"Network error calling Meta Graph API ({method} {url}): "
            f"{type(e).__name__}: {e}",
            code="API", as_json=as_json,
        ))

    if resp.status_code >= 400:
        try:
            body = resp.json()
        except ValueError:
            body = {}
        classified = classify_meta_error(resp.status_code, body)
        if classified:
            if as_json:
                sys.stdout.write(json.dumps({"error": classified}) + "\n")
                sys.stdout.flush()
                raise SystemExit(classified["exit_code"])
            click.secho(f"✗ Meta API error {classified['error_code']}: {classified['message']}", fg="red", err=True)
            if classified.get("fbtrace_id"):
                click.secho(f"  fbtrace_id: {classified['fbtrace_id']}", fg="yellow", err=True)
            raise SystemExit(classified["exit_code"])
        detail = resp.text[:1200]
        raise SystemExit(print_error(f"API Error {resp.status_code}: {detail}", code="API", as_json=as_json))

    if not resp.text:
        return {}
    return resp.json()


def batch_request(operations, *, token=None, timeout=30, as_json=False):
    """Run a Graph API batch request.

    `operations` is a list of dicts like {"method": "GET", "relative_url": "..."}
    (see https://developers.facebook.com/docs/graph-api/batch-requests). Meta's
    hard limit is 50 operations per batch call — this raises a clear error
    client-side rather than letting the API reject it opaquely.
    """
    if not isinstance(operations, list):
        raise ValueError("batch_request: `operations` must be a list of operation dicts.")
    if len(operations) > MAX_BATCH_OPS:
        raise ValueError(
            f"batch_request: {len(operations)} operations exceeds Meta's hard batch "
            f"limit of {MAX_BATCH_OPS}. Split into multiple batch calls."
        )
    if not operations:
        raise ValueError("batch_request: `operations` must not be empty.")

    return graph_request(
        "POST",
        "",
        params={"batch": json.dumps(operations)},
        token=token,
        timeout=timeout,
        as_json=as_json,
    )
