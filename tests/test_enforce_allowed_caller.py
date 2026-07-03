"""Offline tests for `enforce_allowed_caller()` — mads-cli's optional
caller-enforcement gate for agent delegation models.

Mirrors gads-cli's `enforce_allowed_caller()` (gads_lib/cli.py:145) exactly,
under mads-prefixed env vars (MADS_ENFORCE_CALLER / MADS_EXPECTED_CALLER /
MADS_CALLER_AGENT instead of GADS_*). gads-cli itself carries no dedicated
test coverage for its own `enforce_allowed_caller()` (confirmed: no
`enforce_allowed_caller`/`ENFORCE_CALLER` references anywhere under
gads-cli/tests/) — this file follows gads-cli/mads-cli's general test-suite
conventions instead (CliRunner + monkeypatch env vars + mocked
`requests.request`, see tests/test_mads.py's module docstring), since there
is no existing enforce_allowed_caller test pattern to mirror directly.

No real network calls: every CLI-level test below mocks
`mads_lib.http.requests.request` with a stub that raises if it is ever
called, so a passing "blocked" test also proves the gate runs BEFORE any
Graph API call is attempted — not just that the command eventually fails.
"""
import os

import pytest
from click.testing import CliRunner

from mads_lib.cli import cli, enforce_allowed_caller

runner = CliRunner()

_ENV_KEYS = ("MADS_ENFORCE_CALLER", "MADS_EXPECTED_CALLER", "MADS_CALLER_AGENT")


@pytest.fixture(autouse=True)
def _clean_enforce_caller_env(monkeypatch):
    """Ensure no leftover MADS_ENFORCE_CALLER/... env vars leak between tests
    (or in from the real shell environment) — each test sets exactly what it
    needs via monkeypatch, which auto-reverts on teardown.
    """
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _unreachable_request(method, url, **kwargs):
    raise AssertionError(
        f"requests.request({method!r}, {url!r}) was called — enforce_allowed_caller() "
        "should have blocked execution before any HTTP call was made."
    )


# ─────────────────────────────────────────────────────────────────────────
# Direct unit tests — enforce_allowed_caller() in isolation
# ─────────────────────────────────────────────────────────────────────────


class TestEnforceAllowedCallerUnit:
    def test_noop_when_flag_unset(self):
        """No MADS_ENFORCE_CALLER at all → always a no-op, regardless of caller."""
        enforce_allowed_caller()  # must not raise

    @pytest.mark.parametrize("flag_value", ["0", "true", "TRUE", "yes", "on", ""])
    def test_noop_when_flag_not_exactly_1(self, monkeypatch, flag_value):
        """Only the exact string "1" arms the gate — mirrors gads-cli's strict `!= "1"` check."""
        monkeypatch.setenv("MADS_ENFORCE_CALLER", flag_value)
        monkeypatch.setenv("MADS_CALLER_AGENT", "some-random-agent")
        enforce_allowed_caller()  # must not raise even though caller doesn't match anything

    def test_passes_when_caller_matches_default_expected(self, monkeypatch):
        monkeypatch.setenv("MADS_ENFORCE_CALLER", "1")
        monkeypatch.setenv("MADS_CALLER_AGENT", "meta-platform-operator")
        enforce_allowed_caller()  # must not raise

    def test_passes_when_caller_matches_custom_expected_override(self, monkeypatch):
        monkeypatch.setenv("MADS_ENFORCE_CALLER", "1")
        monkeypatch.setenv("MADS_EXPECTED_CALLER", "adops-manager")
        monkeypatch.setenv("MADS_CALLER_AGENT", "adops-manager")
        enforce_allowed_caller()  # must not raise

    def test_blocks_and_exits_1_when_caller_mismatched(self, monkeypatch):
        monkeypatch.setenv("MADS_ENFORCE_CALLER", "1")
        monkeypatch.setenv("MADS_CALLER_AGENT", "some-other-agent")
        with pytest.raises(SystemExit) as exc_info:
            enforce_allowed_caller()
        assert exc_info.value.code == 1

    def test_blocks_when_caller_agent_env_var_entirely_unset(self, monkeypatch):
        """MADS_ENFORCE_CALLER=1 with no MADS_CALLER_AGENT at all → caller defaults to
        "" which never matches a real expected-caller value → blocked."""
        monkeypatch.setenv("MADS_ENFORCE_CALLER", "1")
        with pytest.raises(SystemExit) as exc_info:
            enforce_allowed_caller()
        assert exc_info.value.code == 1

    def test_blocks_when_expected_caller_overridden_but_actual_caller_still_default(self, monkeypatch):
        monkeypatch.setenv("MADS_ENFORCE_CALLER", "1")
        monkeypatch.setenv("MADS_EXPECTED_CALLER", "adops-manager")
        monkeypatch.setenv("MADS_CALLER_AGENT", "meta-platform-operator")
        with pytest.raises(SystemExit) as exc_info:
            enforce_allowed_caller()
        assert exc_info.value.code == 1

    def test_error_message_names_the_expected_caller(self, monkeypatch, capsys):
        monkeypatch.setenv("MADS_ENFORCE_CALLER", "1")
        monkeypatch.setenv("MADS_EXPECTED_CALLER", "adops-manager")
        monkeypatch.setenv("MADS_CALLER_AGENT", "someone-else")
        with pytest.raises(SystemExit):
            enforce_allowed_caller()
        captured = capsys.readouterr()
        assert "adops-manager" in captured.err
        assert "MADS_ENFORCE_CALLER=1" in captured.err


# ─────────────────────────────────────────────────────────────────────────
# CLI-level tests — the gate fires before any mutating command's HTTP call,
# for one representative command per resource-group module.
# ─────────────────────────────────────────────────────────────────────────


class TestEnforceAllowedCallerBlocksMutatingCommands:
    """Every case sets MADS_ENFORCE_CALLER=1 with a mismatched MADS_CALLER_AGENT,
    then asserts the CLI exits 1 *and* never reaches `requests.request` (proving
    the gate runs first, not just that the command eventually errors out).
    """

    @pytest.fixture(autouse=True)
    def _arm_gate_with_mismatched_caller(self, monkeypatch):
        monkeypatch.setenv("MADS_ENFORCE_CALLER", "1")
        monkeypatch.setenv("MADS_CALLER_AGENT", "unauthorized-caller")
        monkeypatch.setattr("mads_lib.http.requests.request", _unreachable_request)

    @pytest.mark.parametrize("args", [
        # cli.py-native mutating commands
        ["mutate", "act_123/campaigns", '{"name": "x"}', "--yes"],
        ["batch-mutate", '[{"method":"POST","relative_url":"act_123/campaigns","body":"name=x"}]', "--yes"],
        ["audience", "create", "TestAud", "--yes"],
        ["audience", "upload-users", "aud_1", "EMAIL", "[[\"a@b.com\"]]", "--yes"],
        ["audience", "delete", "aud_1", "--yes"],
        ["commerce", "create-catalog", "TestCat", "--yes"],
        ["commerce", "create-feed", "cat_1", "TestFeed", "--yes"],
        ["commerce", "upload-feed", "feed_1", "--url", "https://example.com/feed.csv", "--yes"],
        ["commerce", "create-product", "cat_1", "retailer_1", "Name", "AED", "100", "https://example.com/i.jpg", "--yes"],
        ["commerce", "batch-update", "cat_1", '[{"method":"CREATE","data":{}}]', "--yes"],
        ["capi", "send-event", "pixel_1", '[{"event_name":"Purchase"}]', "--yes"],
        ["post", "create", "--page-id", "page_1", "--message", "hi", "--yes"],
        ["post", "create-ig", "--ig-account-id", "ig_1", "--image-url", "https://example.com/i.jpg", "--yes"],
        ["post", "delete", "post_1", "--page-id", "page_1", "--yes"],
        ["comment", "reply", "--post-id", "post_1", "--message", "hi", "--yes"],
        ["comment", "hide", "comment_1", "--yes"],
        ["comment", "delete", "comment_1", "--yes"],
        # campaigns.py
        ["campaign", "create", "TestCamp", "--objective", "OUTCOME_TRAFFIC", "--yes"],
        ["campaign", "status", "camp_1", "ACTIVE", "--yes"],
        ["campaign", "budget", "camp_1", "100", "--yes"],
        ["campaign", "delete", "camp_1", "--yes"],
        # adsets.py
        ["adset", "create", "TestSet", "--campaign-id", "camp_1",
         "--optimization-goal", "LINK_CLICKS", "--countries", "AE", "--yes"],
        ["adset", "status", "adset_1", "ACTIVE", "--yes"],
        ["adset", "budget", "adset_1", "100", "--yes"],
        ["adset", "delete", "adset_1", "--yes"],
        # ads.py
        ["ad", "create", "TestAd", "--adset-id", "adset_1", "--creative-id", "creative_1", "--yes"],
        ["ad", "status", "ad_1", "ACTIVE", "--yes"],
        ["ad", "budget", "ad_1", "100", "--yes"],
        ["ad", "delete", "ad_1", "--yes"],
        # creatives.py
        ["creative", "create", "TestCreative", "--page-id", "page_1",
         "--link", "https://example.com/?branch=qz3", "--yes"],
        # webhooks.py
        ["webhook", "subscribe", "--account-id", "act_123", "--app-id", "app_1"],
        ["webhook", "unsubscribe", "--account-id", "act_123", "--app-id", "app_1"],
        # pages.py
        ["page", "update", "page_1", "--about", "New about text", "--yes"],
        # abtest.py
        ["abtest", "create", "--name", "Test Study", "--start-time", "1700000000",
         "--end-time", "1700100000", "--cells",
         '[{"name":"A","treatment_percentage":50,"adsets":["a"]},'
         '{"name":"B","treatment_percentage":50,"adsets":["b"]}]'],
    ], ids=lambda args: " ".join(args[:2]))
    def test_command_blocked_before_any_network_call(self, args):
        result = runner.invoke(cli, args)
        assert result.exit_code == 1, (
            f"expected exit_code 1 for {args!r}, got {result.exit_code}: {result.output}"
        )
        assert "unauthorized-caller" not in result.output  # sanity: our fixture name never leaks
        assert "restricted to the" in result.output


class TestEnforceAllowedCallerDoesNotBreakDefaultBehavior:
    """Regression guard: with MADS_ENFORCE_CALLER unset (the default, existing
    behavior for every current user of mads-cli), a mutating command still
    reaches its normal HTTP call — enforce_allowed_caller() must be a true
    no-op when the gate isn't armed.
    """

    def test_campaign_status_still_reaches_http_layer_when_gate_unarmed(self, monkeypatch, fake_token):
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url))
            return _FakeOKResponse()

        monkeypatch.setattr("mads_lib.http.requests.request", fake_request)
        monkeypatch.setattr("mads_lib.http.get_access_token", lambda: fake_token)

        result = runner.invoke(cli, ["campaign", "status", "camp_1", "ACTIVE", "--yes"])
        assert result.exit_code == 0, result.output
        assert len(calls) == 1


class _FakeOKResponse:
    status_code = 200
    text = "{}"

    def json(self):
        return {"id": "camp_1", "success": True}
