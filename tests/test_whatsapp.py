"""Offline/CI-safe test suite for mads_lib/whatsapp.py (WhatsApp Business Platform / Cloud API).

Mirrors tests/test_mads.py's conventions (see its module docstring): no real network calls —
every HTTP-touching test mocks `mads_lib.http.requests.request` (the sole transport call), and
config constants (`WABA_ID`/`APP_ID`/`APP_SECRET`) are monkeypatched per-test rather than relying
on real credentials/env. tests/conftest.py's fake env vars (META_APP_ID/META_APP_SECRET/
MADS_PROJECT_ROOT) already keep mads_lib/config.py from ever resolving to the real talas-ads
scope — see that file for why.

Kept in its own file (not appended to tests/test_mads.py) per this change's task scope, since
another concurrent change was in flight against test_mads.py at the time this was written.

Covers:
  * `mads whatsapp` group + every subgroup/subcommand --help exits 0
  * META_WABA_ID-required commands fail gracefully (VALIDATION, not a crash) when unset
  * `template create` JSON-argument validation
  * `webhook subscribe`'s META_APP_ID/META_APP_SECRET requirement and App Access Token shape
  * success paths (mocked HTTP) for waba info, phone-number info, template list/create,
    webhook subscribe
  * --dry-run never touches the network for mutating commands

Note: this module is management/analytics-only by design (no `send` command — sending/receiving
messages requires the separate `whatsapp_business_messaging` OAuth scope, which Talas doesn't
need; see mads_lib/whatsapp.py's module docstring and kb/whatsapp-business-platform.md).
"""
import json
import sqlite3

import click
import pytest
from click.testing import CliRunner

from mads_lib.cli import cli
from mads_lib.output import EXIT_CODES

runner = CliRunner()


class _FakeResponse:
    """Minimal stand-in for requests.Response, matching tests/test_mads.py's _FakeResponse."""

    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text if text else json.dumps(self._json_data)

    def json(self):
        return self._json_data


@pytest.fixture(autouse=True)
def _fake_credentials(monkeypatch):
    """CLI-invoked success-path tests below go through graph_request()'s default
    (no explicit `token=`) code path, which loads a bearer token off disk via
    mads_lib.auth.get_access_token() — there is no real credentials file in this
    offline test environment (see tests/conftest.py). Stub both auth helpers
    graph_request() actually calls (imported into mads_lib.http's namespace) so
    every test in this file is credential-file-free, matching the rest of the
    offline suite's no-real-network discipline.
    """
    monkeypatch.setattr("mads_lib.http.get_access_token", lambda: "fake-token")
    monkeypatch.setattr("mads_lib.http.get_appsecret_proof", lambda token=None: "fake-proof")


@pytest.fixture(autouse=True)
def _fake_changelog_db(monkeypatch):
    """`whatsapp.py`'s `_auto_log()` is best-effort (mirrors mads_lib.campaigns._auto_log) —
    it must never surface a missing-database error to the caller. In this offline test
    environment MADS_DB_PATH doesn't exist, so the real `get_db()` would print a "Database
    not found" message to stderr on every mutating command; CliRunner's default `output`
    stream interleaves stdout+stderr, which would corrupt `--json` output parsing in
    success-path tests below. Stub `get_db()` with a real in-memory SQLite connection (a
    changelog table matching cli.py's INSERT columns) so `_auto_log()`'s INSERT succeeds
    silently instead, exercising the happy path rather than the swallowed-failure path.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE changelog (timestamp TEXT, action TEXT, campaign TEXT, "
        "campaign_id TEXT, details TEXT, reason TEXT, agent TEXT, snapshot_ref TEXT, "
        "script TEXT, raw_json TEXT)"
    )
    monkeypatch.setattr("mads_lib.whatsapp.get_db", lambda: conn)


# ─────────────────────────────────────────────────────────────────────────
# --help sweep
# ─────────────────────────────────────────────────────────────────────────


class TestWhatsappHelp:
    def test_whatsapp_is_registered_as_a_top_level_group(self):
        ctx = click.Context(cli, info_name="mads")
        cmd = cli.get_command(ctx, "whatsapp")
        assert cmd is not None
        assert isinstance(cmd, click.Group)

    def test_root_help_mentions_whatsapp(self):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "whatsapp" in result.output

    def test_whatsapp_group_help_exits_0(self):
        result = runner.invoke(cli, ["whatsapp", "--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    @pytest.mark.parametrize("subgroup", ["waba", "phone-number", "template", "webhook"])
    def test_whatsapp_subgroup_help_exits_0(self, subgroup):
        result = runner.invoke(cli, ["whatsapp", subgroup, "--help"])
        assert result.exit_code == 0, result.output

    @pytest.mark.parametrize("args", [
        ["waba", "info"], ["waba", "phone-numbers"],
        ["phone-number", "info"],
        ["template", "list"], ["template", "create"],
        ["webhook", "subscribe"],
    ])
    def test_every_leaf_command_help_exits_0(self, args):
        result = runner.invoke(cli, ["whatsapp", *args, "--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    def test_whatsapp_appears_in_catalog_json_as_a_group_with_subcommands(self):
        result = runner.invoke(cli, ["catalog", "--json"])
        assert result.exit_code == 0, result.output
        manifest = json.loads(result.output)
        entry = manifest["commands"]["whatsapp"]
        assert entry["is_group"] is True
        assert set(entry["subcommands"].keys()) == {"waba", "phone-number", "template", "webhook"}


# ─────────────────────────────────────────────────────────────────────────
# META_WABA_ID not configured -> graceful VALIDATION, not a crash
# ─────────────────────────────────────────────────────────────────────────


class TestWabaIdNotConfigured:
    """WABA_ID is optional config (mads_lib/config.py) — commands that need it must fail with
    a clear VALIDATION error, never a raw KeyError/crash, when it isn't set."""

    def test_waba_info_fails_gracefully_without_waba_id(self, monkeypatch):
        monkeypatch.setattr("mads_lib.whatsapp.WABA_ID", "")
        result = runner.invoke(cli, ["whatsapp", "waba", "info", "--json"])
        assert result.exit_code == EXIT_CODES["VALIDATION"]
        payload = json.loads(result.output)
        assert payload["error"]["code"] == "VALIDATION"
        assert "META_WABA_ID" in payload["error"]["message"]

    def test_waba_phone_numbers_fails_gracefully_without_waba_id(self, monkeypatch):
        monkeypatch.setattr("mads_lib.whatsapp.WABA_ID", "")
        result = runner.invoke(cli, ["whatsapp", "waba", "phone-numbers", "--json"])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

    def test_template_list_fails_gracefully_without_waba_id(self, monkeypatch):
        monkeypatch.setattr("mads_lib.whatsapp.WABA_ID", "")
        result = runner.invoke(cli, ["whatsapp", "template", "list", "--json"])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

    def test_template_create_fails_gracefully_without_waba_id(self, monkeypatch):
        monkeypatch.setattr("mads_lib.whatsapp.WABA_ID", "")
        result = runner.invoke(cli, [
            "whatsapp", "template", "create", "order_shipped", "UTILITY", "en_US",
            '[{"type":"BODY","text":"hi"}]', "--yes", "--json",
        ])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

    def test_waba_id_override_flag_bypasses_missing_env(self, monkeypatch):
        """--waba-id should work even when META_WABA_ID is unset."""
        monkeypatch.setattr("mads_lib.whatsapp.WABA_ID", "")
        monkeypatch.setattr(
            "mads_lib.http.requests.request",
            lambda *a, **k: _FakeResponse(200, {"id": "999", "name": "Talas WABA"}),
        )
        result = runner.invoke(cli, ["whatsapp", "waba", "info", "--waba-id", "999", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == {"id": "999", "name": "Talas WABA"}


# ─────────────────────────────────────────────────────────────────────────
# phone-number info — does NOT require a WABA id (operates on a phone number id directly)
# ─────────────────────────────────────────────────────────────────────────


class TestPhoneNumberInfo:
    def test_success_path(self, monkeypatch):
        captured = []

        def fake_request(method, url, **kwargs):
            captured.append((method, url, kwargs))
            return _FakeResponse(200, {"id": "111", "display_phone_number": "+971500000000", "quality_rating": "GREEN"})

        monkeypatch.setattr("mads_lib.http.requests.request", fake_request)
        result = runner.invoke(cli, ["whatsapp", "phone-number", "info", "111", "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["quality_rating"] == "GREEN"
        assert len(captured) == 1
        method, url, kwargs = captured[0]
        assert method == "GET"
        assert url.endswith("111")


# ─────────────────────────────────────────────────────────────────────────
# template create — JSON validation + success + dry-run
# ─────────────────────────────────────────────────────────────────────────


class TestTemplateCreate:
    def test_invalid_components_json_rejected_before_any_network_call(self, monkeypatch):
        calls = []
        monkeypatch.setattr("mads_lib.whatsapp.WABA_ID", "waba_1")
        monkeypatch.setattr("mads_lib.http.requests.request", lambda *a, **k: calls.append(1))
        result = runner.invoke(cli, [
            "whatsapp", "template", "create", "order_shipped", "UTILITY", "en_US",
            "not-json", "--yes", "--json",
        ])
        assert result.exit_code == EXIT_CODES["VALIDATION"]
        assert calls == []

    def test_invalid_category_rejected_by_click_choice(self, monkeypatch):
        monkeypatch.setattr("mads_lib.whatsapp.WABA_ID", "waba_1")
        result = runner.invoke(cli, [
            "whatsapp", "template", "create", "order_shipped", "NOT_A_CATEGORY", "en_US",
            "[]", "--yes",
        ])
        assert result.exit_code == EXIT_CODES["USAGE"]

    def test_dry_run_never_calls_network(self, monkeypatch):
        calls = []
        monkeypatch.setattr("mads_lib.whatsapp.WABA_ID", "waba_1")
        monkeypatch.setattr("mads_lib.http.requests.request", lambda *a, **k: calls.append(1))
        result = runner.invoke(cli, [
            "whatsapp", "template", "create", "order_shipped", "UTILITY", "en_US",
            '[{"type":"BODY","text":"hi"}]', "--dry-run",
        ])
        assert result.exit_code == 0, result.output
        assert "DRY RUN" in result.output
        assert calls == []

    def test_success_path_submits_expected_body(self, monkeypatch):
        captured = []

        def fake_request(method, url, **kwargs):
            captured.append((method, url, kwargs))
            return _FakeResponse(200, {"id": "tpl_123", "status": "PENDING", "category": "UTILITY"})

        monkeypatch.setattr("mads_lib.whatsapp.WABA_ID", "waba_1")
        monkeypatch.setattr("mads_lib.http.requests.request", fake_request)
        result = runner.invoke(cli, [
            "whatsapp", "template", "create", "order_shipped", "UTILITY", "en_US",
            '[{"type":"BODY","text":"Your order {{1}} has shipped."}]', "--yes", "--json",
        ])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["status"] == "PENDING"
        assert len(captured) == 1
        method, url, kwargs = captured[0]
        assert method == "POST"
        assert url.endswith("waba_1/message_templates")
        body = kwargs["json"]
        assert body["name"] == "order_shipped"
        assert body["category"] == "UTILITY"
        assert body["language"] == "en_US"
        assert body["components"] == [{"type": "BODY", "text": "Your order {{1}} has shipped."}]


# ─────────────────────────────────────────────────────────────────────────
# webhook subscribe — App Access Token requirement + success path
# ─────────────────────────────────────────────────────────────────────────


class TestWebhookSubscribe:
    def test_missing_app_secret_fails_gracefully(self, monkeypatch):
        monkeypatch.setattr("mads_lib.whatsapp.APP_SECRET", "")
        result = runner.invoke(cli, [
            "whatsapp", "webhook", "subscribe",
            "--callback-url", "https://example.com/webhook",
            "--verify-token", "secret123", "--json",
        ])
        assert result.exit_code == EXIT_CODES["VALIDATION"]

    def test_success_path_uses_app_access_token(self, monkeypatch):
        captured = []

        def fake_request(method, url, **kwargs):
            captured.append((method, url, kwargs))
            return _FakeResponse(200, {"success": True})

        monkeypatch.setattr("mads_lib.whatsapp.APP_ID", "app_123")
        monkeypatch.setattr("mads_lib.whatsapp.APP_SECRET", "shh")
        monkeypatch.setattr("mads_lib.http.requests.request", fake_request)
        result = runner.invoke(cli, [
            "whatsapp", "webhook", "subscribe",
            "--callback-url", "https://example.com/webhook",
            "--verify-token", "secret123", "--json",
        ])
        assert result.exit_code == 0, result.output
        method, url, kwargs = captured[0]
        assert method == "POST"
        assert url.endswith("app_123/subscriptions")
        assert kwargs["params"]["object"] == "whatsapp_business_account"
        assert kwargs["params"]["callback_url"] == "https://example.com/webhook"
        assert kwargs["params"]["verify_token"] == "secret123"
        # App Access Token convention: app_id|app_secret, not the general user token.
        assert kwargs["params"]["access_token"] == "app_123|shh"
