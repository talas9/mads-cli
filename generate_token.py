"""Generate a long-lived Meta (Facebook/Instagram) access token.

Runs the standard Meta Graph API "Login for Business" / OAuth dialog flow:

  1. Open the Facebook OAuth dialog in a browser, requesting the scopes this
     CLI needs (ads_management, business_management, pages_read_engagement,
     pages_manage_metadata).
  2. Catch the redirect on a local callback server and extract the `code`.
  3. Exchange `code` for a short-lived user access token
     (GET /{api_version}/oauth/access_token).
  4. Exchange the short-lived token for a long-lived token (~60 days)
     via GET /oauth/access_token with grant_type=fb_exchange_token.
  5. Save the result to credentials/meta-oauth.json.

Requires a Meta App (developers.facebook.com/apps) with:
  - META_APP_ID / META_APP_SECRET set in the environment (or .env)
  - `http://localhost:<port>/` added to "Valid OAuth Redirect URIs" in
    Facebook Login product settings for the app.

Usage:
    python generate_token.py                  # browser + local server on 9090
    python generate_token.py --no-browser      # skip opening a browser (WSL/headless)
    python generate_token.py --port 9091       # alternate callback port
    python generate_token.py --print-url-only  # print URL + exit

Mirrors the structure of gads-cli's generate_token.py, adapted for Meta's
OAuth dialog + code/token exchange (no client_secret.json file — Meta apps
use a plain App ID + App Secret pair instead of a downloadable client JSON).
"""
import argparse
import html
import http.server
import os
import secrets
import sys
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

PROJECT_ROOT = Path(os.environ.get("MADS_PROJECT_ROOT", Path(__file__).resolve().parent.parent))

if load_dotenv is not None:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

CREDENTIALS_DIR = Path(os.environ.get("MADS_CREDENTIALS_DIR", PROJECT_ROOT / "credentials"))

APP_ID = os.environ.get("META_APP_ID", "")
APP_SECRET = os.environ.get("META_APP_SECRET", "")
API_VERSION = os.environ.get("META_API_VERSION", "v25.0")

SCOPES = [
    "ads_management",
    "ads_read",
    "business_management",
    "pages_read_engagement",
    "pages_show_list",
    # Organic content (Instagram/Facebook posts, comments, page management) — added
    # 2026-07-02 for mads-cli's `post`/`comment`/`page update` command groups
    # (mads_lib/posts.py, mads_lib/comments.py, mads_lib/pages.py::update_page_info).
    # GRANTED on the live Talas token as of 2026-07-03 — the account owner re-authed
    # via the App Dashboard's Use-cases UI ("Manage messaging & content on
    # Instagram" + "Manage everything on your Page"), Dev-Mode admin access, no
    # App Review required. Confirmed via `mads query --node me/permissions --json`
    # showing "status": "granted" for each scope below. See AGENTS.md Known
    # Gotchas #8 (marked RESOLVED) for the full history.
    "pages_manage_posts",
    "pages_manage_engagement",
    "pages_manage_metadata",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_comments",
    "instagram_manage_insights",
    "pages_manage_ads",
    # "catalog_management",  # UNCOMMENT once the app has "Catalog Management"
    # added under App Dashboard -> App Review -> Permissions and Features (App
    # ID 1332295765705902). Root-caused 2026-07-02: `mads commerce`
    # catalog endpoints fail with "(#100) This application has not been
    # approved to use this api" because this scope was never requested/
    # granted (confirmed via GET /me/permissions — not present in the
    # granted-permissions list). See kb/commerce-catalog.md Gotchas #13 for
    # the full manual remediation steps; this is an App Dashboard action only
    # the account owner can perform, not fixable via the API alone.
    # "whatsapp_business_management",  # UNCOMMENT once a WhatsApp Business
    # Account (WABA) is onboarded for this app via Meta's Embedded Signup or
    # Tech/Solution-Provider-mediated "coexistence" migration of an existing
    # number onto the Cloud API — an account-level, Meta-eligibility-gated
    # prerequisite this repo cannot complete for you. This is the ONLY
    # WhatsApp scope mads-cli needs: mads_lib/whatsapp.py is management/
    # analytics-only (WABA/phone-number reads, template list/create, webhook
    # subscribe) — it does not send or receive messages, so
    # whatsapp_business_messaging (the separate scope required for
    # POST /{phone-number-id}/messages) is intentionally not requested. No
    # WABA is onboarded for Talas yet (added 2026-07-02 alongside
    # mads_lib/whatsapp.py). See kb/whatsapp-business-platform.md.
]

TOKEN_OUTPUT = CREDENTIALS_DIR / "meta-oauth.json"
AUTH_URL_FILE = CREDENTIALS_DIR / ".oauth-auth-url.txt"

GRAPH_HOST = "https://graph.facebook.com"
DIALOG_HOST = "https://www.facebook.com"

SEPARATOR = "=" * 60


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """Minimal local HTTP handler that captures the OAuth redirect."""

    code = None
    error = None
    expected_state = None
    auth_url = None

    def do_GET(self):  # noqa: N802 (http.server API name)
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "error" in params:
            desc = params.get("error_description", params.get("error"))[0]
            _CallbackHandler.error = desc
            self._respond(f"Authorization failed: {desc}")
            return

        if "code" in params:
            returned_state = params.get("state", [None])[0]
            if _CallbackHandler.expected_state and returned_state != _CallbackHandler.expected_state:
                _CallbackHandler.error = "state mismatch (possible CSRF) — aborting"
                self._respond("Authorization failed: state mismatch. Please retry.")
                return
            _CallbackHandler.code = params["code"][0]
            self._respond("Authorization received. You can close this window.")
            return

        self._respond_html(self._landing_page_html())

    def _landing_page_html(self):
        safe_auth_url = html.escape(_CallbackHandler.auth_url or "", quote=True)
        return f"""<html>
<head><title>Talas Meta Ads — Authorize</title></head>
<body style="margin:0;padding:0;background:#f2f3f5;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;">
  <div style="max-width:480px;margin:80px auto;background:#ffffff;border-radius:12px;
              box-shadow:0 2px 10px rgba(0,0,0,0.08);padding:32px;text-align:center;">
    <h3 style="margin-top:0;color:#1c1e21;">Authorize Talas Meta (Facebook/Instagram) access</h3>
    <p style="color:#606770;font-size:14px;">Click the button below to grant this app access
      to the Talas Meta Ads account.</p>
    <a href="{safe_auth_url}"
       style="display:inline-block;margin-top:16px;padding:12px 28px;background:#1877f2;
              color:#ffffff;text-decoration:none;font-weight:bold;border-radius:6px;
              font-size:16px;">Authorize with Facebook</a>
    <p style="color:#8a8d91;font-size:12px;margin-top:24px;">You'll be redirected to Facebook,
      then back here automatically.</p>
  </div>
</body>
</html>"""

    def _respond(self, message):
        self._respond_html(f"<html><body><h3>{message}</h3></body></html>")

    def _respond_html(self, html_body):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html_body.encode("utf-8"))

    def log_message(self, format, *args):  # noqa: A002 - silence default request logging
        pass


def _print_auth_url_block(auth_url: str, port: int) -> None:
    """Print the auth URL with visual separators so terminals don't mangle it."""
    print()
    print(SEPARATOR)
    print(f"Open http://localhost:{port}/ in your browser and click the")
    print("\"Authorize with Facebook\" button.")
    print()
    print("(Fallback — if the local page doesn't load, open this raw auth URL")
    print(" directly instead; it goes straight to the Facebook dialog):")
    print()
    print(auth_url)
    print()
    print(SEPARATOR)
    print(f"(Callback listener will run on http://localhost:{port}/)")
    print()


def _save_auth_url(auth_url: str) -> None:
    try:
        CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
        AUTH_URL_FILE.write_text(auth_url + "\n", encoding="utf-8")
        print(f"Auth URL also saved to: {AUTH_URL_FILE}")
    except OSError as exc:
        print(f"WARNING: could not save auth URL to {AUTH_URL_FILE}: {exc}")


def _build_auth_url(redirect_uri: str, state: str) -> str:
    query = urllib.parse.urlencode({
        "client_id": APP_ID,
        "redirect_uri": redirect_uri,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "state": state,
    })
    return f"{DIALOG_HOST}/{API_VERSION}/dialog/oauth?{query}"


def _run_local_server(auth_url: str, port: int, open_browser: bool, state: str) -> str:
    """Start a local HTTP server, wait for the OAuth redirect, return the code."""
    _CallbackHandler.code = None
    _CallbackHandler.error = None
    _CallbackHandler.expected_state = state
    _CallbackHandler.auth_url = auth_url

    server = http.server.HTTPServer(("localhost", port), _CallbackHandler)

    if open_browser:
        webbrowser.open(auth_url)

    print(f"Listening for the OAuth redirect on http://localhost:{port}/ ...")
    while _CallbackHandler.code is None and _CallbackHandler.error is None:
        server.handle_request()
    server.server_close()

    if _CallbackHandler.error:
        raise RuntimeError(_CallbackHandler.error)
    return _CallbackHandler.code


def _exchange_code_for_short_lived_token(code: str, redirect_uri: str) -> dict:
    """GET /{api_version}/oauth/access_token — code → short-lived user token."""
    resp = requests.get(
        f"{GRAPH_HOST}/{API_VERSION}/oauth/access_token",
        params={
            "client_id": APP_ID,
            "redirect_uri": redirect_uri,
            "client_secret": APP_SECRET,
            "code": code,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _exchange_for_long_lived_token(short_lived_token: str) -> dict:
    """GET /oauth/access_token with grant_type=fb_exchange_token — short-lived → long-lived (~60 days)."""
    resp = requests.get(
        f"{GRAPH_HOST}/{API_VERSION}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "fb_exchange_token": short_lived_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a long-lived Meta (Facebook/Instagram) access token")
    parser.add_argument("--port", type=int, default=9090, help="Local server port for OAuth callback (default: 9090)")
    parser.add_argument("--no-browser", action="store_true", help="Do not attempt to open a browser (WSL/headless/remote)")
    parser.add_argument("--print-url-only", action="store_true", help="Print the auth URL and save it to credentials/.oauth-auth-url.txt, then exit without starting the callback server")
    args = parser.parse_args()

    if not APP_ID or not APP_SECRET:
        print("ERROR: META_APP_ID and/or META_APP_SECRET are not set.")
        print("Set them in .env or the environment. Get them from:")
        print("  https://developers.facebook.com/apps/  →  your app  →  Settings → Basic")
        return 1

    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

    redirect_uri = f"http://localhost:{args.port}/"
    state = secrets.token_urlsafe(24)
    auth_url = _build_auth_url(redirect_uri, state)

    _print_auth_url_block(auth_url, args.port)
    _save_auth_url(auth_url)
    print("NOTE: this exact redirect URI must be listed under 'Valid OAuth Redirect")
    print(f"      URIs' for the app ({redirect_uri}), in Facebook Login → Settings.")
    print()

    if args.print_url_only:
        print("--print-url-only: exiting without starting the local callback server.")
        return 0

    try:
        code = _run_local_server(auth_url, args.port, open_browser=not args.no_browser, state=state)
    except Exception as exc:  # noqa: BLE001 - report whatever blew up
        print()
        print(f"ERROR: OAuth flow failed: {exc}")
        print("Remediation:")
        print("  - Confirm the URL above resolves in your browser.")
        print(f"  - Check nothing else is listening on port {args.port} (try --port N).")
        print("  - Confirm the redirect URI is registered in the app's Facebook Login settings.")
        print("  - On WSL / headless, use --no-browser and open the URL manually.")
        print("  - Re-run with --print-url-only to inspect the URL before attempting.")
        return 2

    try:
        short_lived = _exchange_code_for_short_lived_token(code, redirect_uri)
    except requests.HTTPError as exc:
        print(f"ERROR: failed to exchange code for a short-lived token: {exc}")
        print(f"  Response: {exc.response.text[:500] if exc.response is not None else ''}")
        return 3

    short_lived_token = short_lived.get("access_token")
    if not short_lived_token:
        print(f"ERROR: no access_token in short-lived token response: {short_lived}")
        return 3

    try:
        long_lived = _exchange_for_long_lived_token(short_lived_token)
    except requests.HTTPError as exc:
        print(f"ERROR: failed to exchange for a long-lived token: {exc}")
        print(f"  Response: {exc.response.text[:500] if exc.response is not None else ''}")
        return 4

    access_token = long_lived.get("access_token")
    if not access_token:
        print(f"ERROR: no access_token in long-lived token response: {long_lived}")
        return 4

    obtained_at = datetime.now(timezone.utc)
    expires_in = long_lived.get("expires_in")  # seconds; Meta typically returns ~5184000 (60 days)
    expires_at = (obtained_at + timedelta(seconds=expires_in)).isoformat() if expires_in else None

    payload = {
        "access_token": access_token,
        "token_type": long_lived.get("token_type", "bearer"),
        "expires_in": expires_in,
        "obtained_at": obtained_at.isoformat(),
        "expires_at": expires_at,
        "scopes_requested": SCOPES,
        "api_version": API_VERSION,
    }

    try:
        with open(TOKEN_OUTPUT, "w") as f:
            import json
            json.dump(payload, f, indent=2)
    except OSError as exc:
        print(f"ERROR: could not write token to {TOKEN_OUTPUT}: {exc}")
        return 5

    print()
    print(f"✓ Long-lived token saved to {TOKEN_OUTPUT}")
    print(f"  Scopes requested: {', '.join(SCOPES)}")
    if expires_at:
        print(f"  Expires: {expires_at} (in {expires_in} seconds)")
    else:
        print("  Expires: unknown (System User tokens from Business Manager may not expire)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
