"""Credential loading for mads-cli.

Unlike gads-cli's Google OAuth `Credentials` object, Meta access tokens
(System User tokens or long-lived user tokens) do not self-refresh
transparently — there is no `refresh_token` dance to perform on every call.
This module is intentionally simple: load the bearer token string from disk,
and provide a helper to compute the `appsecret_proof` HMAC that Meta's Graph
API expects on every authenticated request when App Secret Proof is enabled.

See generate_token.py for how MADS_CREDENTIALS_PATH is produced.
"""
import hashlib
import hmac
import json

import click

from .config import APP_SECRET, CREDS_PATH


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
