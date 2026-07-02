"""Offline/CI-safe test suite for mads-cli.

No real network calls: every HTTP-touching test mocks `requests.request`
(the sole transport call in mads_lib/http.py — see its module docstring) so
`graph_request()`/`batch_request()` never leave the process. Nothing here
needs a live Meta access token, a real credentials file, or a live database;
see tests/conftest.py for how the fake env vars keep mads_lib/config.py from
ever resolving to the real talas-ads scope.

Covers, at minimum:
  * `--version` / `--help` exit 0 for the root group and every resource group
  * `catalog --json` manifest shape
  * `doctor --json` shape, including sibling_cli (gads-cli) detection
  * dbread.assert_select_only rejecting non-SELECT SQL
  * http.py's Meta error classifier mapping known error codes to exit codes
"""
import json

import click
import pytest
import requests
from click.testing import CliRunner

import mads_lib.audiences
import mads_lib.auth
import mads_lib.capi
import mads_lib.commerce
import mads_lib.pages
from mads_lib import __version__
from mads_lib.cli import cli
from mads_lib import dbread
from mads_lib.http import (
    MAX_BATCH_OPS,
    batch_request,
    classify_meta_error,
    graph_request,
)
from mads_lib.output import EXIT_CODES

runner = CliRunner()


def _root_ctx():
    return click.Context(cli, info_name="mads")


def _top_level_group_names():
    """All top-level Click *groups* registered on the root `cli` (not plain
    commands like `doctor`/`query`/`log`). Discovered dynamically rather than
    hardcoded so this test can't silently go stale if a group is renamed.
    """
    ctx = _root_ctx()
    names = []
    for name in cli.list_commands(ctx):
        cmd = cli.get_command(ctx, name)
        if isinstance(cmd, click.Group):
            names.append(name)
    return names


# The 9 Meta resource-group modules wired into cli.py (campaigns.py,
# adsets.py, ads.py, creatives.py, insights.py, abtest.py, business.py,
# pages.py, webhooks.py->"webhook"). `auth` is also a top-level group but is
# credential/diagnostics-focused rather than a Meta *resource* group.
RESOURCE_GROUPS = (
    "campaign", "adset", "ad", "creative", "insights",
    "abtest", "business", "page", "webhook",
)


# ─────────────────────────────────────────────────────────────────────────
# --version / --help
# ─────────────────────────────────────────────────────────────────────────


class TestVersionAndHelp:
    def test_resource_groups_are_actually_registered(self):
        """Sanity check: the hardcoded RESOURCE_GROUPS tuple above must be a
        subset of what's really on the CLI, so this test file can't drift
        from cli.py without failing loudly.
        """
        discovered = set(_top_level_group_names())
        missing = set(RESOURCE_GROUPS) - discovered
        assert not missing, f"expected resource groups missing from cli: {missing}"

    def test_root_version_exits_0(self):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output
        assert "mads" in result.output

    def test_root_help_exits_0(self):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output

    def test_root_no_args_shows_help_without_crashing(self):
        # Click groups invoked bare (no subcommand) print usage and exit 2 by
        # default (missing command) — verify this is the *expected* usage
        # error, not an unhandled traceback.
        result = runner.invoke(cli, [])
        assert result.exit_code in (0, 2)
        assert result.exception is None or isinstance(result.exception, SystemExit)

    @pytest.mark.parametrize("group_name", sorted(_top_level_group_names()))
    def test_group_help_exits_0(self, group_name):
        result = runner.invoke(cli, [group_name, "--help"])
        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output

    @pytest.mark.parametrize("group_name", RESOURCE_GROUPS)
    def test_resource_group_help_exits_0(self, group_name):
        """Explicit, named coverage of the 9 Meta resource groups (in
        addition to the dynamic sweep above), so the requirement is visibly
        satisfied even if cli.py's group list changes shape.
        """
        result = runner.invoke(cli, [group_name, "--help"])
        assert result.exit_code == 0, result.output

    @pytest.mark.parametrize("group_name", RESOURCE_GROUPS)
    def test_resource_group_has_no_own_version_flag(self, group_name):
        """Click's --version is an eager flag attached only to the root
        `cli` group via @click.version_option; subgroups do not inherit it.
        Verified behavior (not assumed): passing --version to a subgroup is
        an unrecognized option -> Click usage error, exit code 2.
        """
        result = runner.invoke(cli, [group_name, "--version"])
        assert result.exit_code == EXIT_CODES["USAGE"]
        assert "No such option" in result.output

    def test_every_resource_group_subcommand_help_exits_0(self):
        """Belt-and-suspenders: --help on every subcommand of every resource
        group must also exit 0 (guards against a broken option definition
        anywhere in the Meta command surface).
        """
        ctx = _root_ctx()
        failures = []
        for group_name in RESOURCE_GROUPS:
            group_cmd = cli.get_command(ctx, group_name)
            group_ctx = click.Context(group_cmd, info_name=group_name, parent=ctx)
            for sub_name in group_cmd.list_commands(group_ctx):
                result = runner.invoke(cli, [group_name, sub_name, "--help"])
                if result.exit_code != 0:
                    failures.append((group_name, sub_name, result.exit_code, result.output))
        assert not failures, failures


# ─────────────────────────────────────────────────────────────────────────
# catalog --json
# ─────────────────────────────────────────────────────────────────────────


class TestCatalogJson:
    @pytest.fixture(scope="class")
    def manifest(self):
        result = runner.invoke(cli, ["catalog", "--json"])
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def test_top_level_shape(self, manifest):
        assert set(manifest.keys()) == {"cli", "version", "description", "commands"}
        assert manifest["cli"] == "mads"
        assert manifest["version"] == __version__
        assert isinstance(manifest["description"], str)
        assert isinstance(manifest["commands"], dict)

    def test_contains_expected_top_level_commands(self, manifest):
        commands = manifest["commands"]
        expected = {
            "doctor", "catalog", "db", "changelog", "decisions", "milestones",
            "query", "snapshot", "log", "mutate", "batch-mutate", "auth",
            *RESOURCE_GROUPS,
        }
        missing = expected - set(commands.keys())
        assert not missing, f"catalog is missing expected commands: {missing}"

    def test_group_entry_shape(self, manifest):
        entry = manifest["commands"]["campaign"]
        assert set(entry.keys()) == {"name", "help", "is_group", "params", "subcommands"}
        assert entry["name"] == "campaign"
        assert entry["is_group"] is True
        assert isinstance(entry["params"], list)
        assert isinstance(entry["subcommands"], dict)
        # campaigns.py defines list/create/status/budget/delete subcommands.
        expected_subs = {"list", "create", "status", "budget", "delete"}
        assert expected_subs.issubset(entry["subcommands"].keys())

    def test_leaf_command_entry_shape(self, manifest):
        entry = manifest["commands"]["doctor"]
        assert set(entry.keys()) == {"name", "help", "is_group", "params"}
        assert entry["is_group"] is False
        assert "subcommands" not in entry

    def test_param_entry_shape(self, manifest):
        entry = manifest["commands"]["db"]
        params_by_name = {p["name"]: p for p in entry["params"]}
        assert "sql" in params_by_name
        sql_param = params_by_name["sql"]
        assert sql_param["param_type"] == "argument"
        assert sql_param["required"] is True

        assert "as_json" in params_by_name
        json_param = params_by_name["as_json"]
        assert json_param["param_type"] == "option"
        assert json_param["is_flag"] is True
        assert "--json" in json_param["opts"]

    def test_every_resource_group_present_and_is_group(self, manifest):
        for name in RESOURCE_GROUPS:
            entry = manifest["commands"][name]
            assert entry["is_group"] is True
            assert isinstance(entry["subcommands"], dict)
            assert entry["subcommands"], f"{name} has no subcommands in catalog"


# ─────────────────────────────────────────────────────────────────────────
# doctor --json
# ─────────────────────────────────────────────────────────────────────────


class TestDoctorJson:
    EXPECTED_CHECK_NAMES = {
        "scope", "credentials", "database", "app_id", "app_secret",
        "ad_account_id", "business_id", "api_version", "timezone",
        "currency", "sibling_cli",
    }

    def test_shape(self):
        result = runner.invoke(cli, ["doctor", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert set(payload.keys()) == {"checks", "sibling_cli"}

        assert isinstance(payload["checks"], list)
        for check in payload["checks"]:
            assert set(check.keys()) == {"check", "status", "detail"}
            assert check["status"] in ("ok", "warn", "fail")

        found_names = {c["check"] for c in payload["checks"]}
        assert found_names == self.EXPECTED_CHECK_NAMES

        sibling = payload["sibling_cli"]
        assert set(sibling.keys()) == {"name", "installed", "path"}
        assert sibling["name"] == "gads-cli"
        assert isinstance(sibling["installed"], bool)

    def test_doctor_json_exits_0_even_with_fail_checks(self):
        """Verified quirk (not a bug being introduced by this test): the
        --json branch of `doctor` returns before the SystemExit(1)-on-failure
        logic that the human-readable branch runs, so `doctor --json` always
        exits 0 regardless of check outcomes. In this test env, credentials
        are guaranteed absent (fake MADS_PROJECT_ROOT has no credentials/
        dir), which normally means a "fail" status for the credentials
        check — confirm that still doesn't change the exit code.
        """
        result = runner.invoke(cli, ["doctor", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        credentials_check = next(c for c in payload["checks"] if c["check"] == "credentials")
        assert credentials_check["status"] == "fail"

    def test_sibling_cli_detected_when_gads_on_path(self, monkeypatch):
        monkeypatch.setattr("mads_lib.cli.shutil.which", lambda name: "/usr/local/bin/gads")
        result = runner.invoke(cli, ["doctor", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["sibling_cli"] == {
            "name": "gads-cli", "installed": True, "path": "/usr/local/bin/gads",
        }
        sibling_check = next(c for c in payload["checks"] if c["check"] == "sibling_cli")
        assert sibling_check["status"] == "ok"
        assert sibling_check["detail"] == "/usr/local/bin/gads"

    def test_sibling_cli_not_detected_when_gads_absent(self, monkeypatch):
        monkeypatch.setattr("mads_lib.cli.shutil.which", lambda name: None)
        result = runner.invoke(cli, ["doctor", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["sibling_cli"] == {"name": "gads-cli", "installed": False, "path": None}
        sibling_check = next(c for c in payload["checks"] if c["check"] == "sibling_cli")
        assert sibling_check["status"] == "warn"
        assert sibling_check["detail"] == "gads not found on PATH"

    def test_human_readable_mode_exits_1_on_real_failures(self, monkeypatch):
        """Contrast case for the quirk above: the *non*-JSON branch does
        enforce SystemExit(1) when any check fails. Credentials are absent
        in this test scope, so this should fail for real.
        """
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 1


# ─────────────────────────────────────────────────────────────────────────
# dbread.assert_select_only
# ─────────────────────────────────────────────────────────────────────────


class TestAssertSelectOnly:
    @pytest.mark.parametrize("sql", [
        "SELECT * FROM changelog",
        "  select id from decisions  ",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SELECT insert_time, updated_at, created_by FROM changelog",
        "SELECT 1 /* sneaky block comment */ FROM changelog",
        "-- leading line comment\nSELECT 1",
        "SELECT 1; -- trailing comment hides nothing dangerous here",
        "SELECT campaign, action FROM changelog ORDER BY timestamp DESC LIMIT 10",
    ])
    def test_allows_single_select_or_with(self, sql):
        assert dbread.assert_select_only(sql) is True

    @pytest.mark.parametrize("sql,expected_fragment", [
        (None, "empty query"),
        ("", "empty query"),
        ("   ", "empty query"),
        ("DROP TABLE changelog", "statement starts with DROP"),
        ("drop table changelog", "statement starts with DROP"),
        ("INSERT INTO changelog (action) VALUES ('x')", "statement starts with INSERT"),
        ("UPDATE changelog SET action = 'x'", "statement starts with UPDATE"),
        ("DELETE FROM changelog", "statement starts with DELETE"),
        ("PRAGMA table_info(changelog)", "statement starts with PRAGMA"),
        ("ATTACH DATABASE 'evil.db' AS evil", "statement starts with ATTACH"),
        ("SELECT 1; DROP TABLE changelog", "multiple statements"),
        ("SELECT 1; SELECT 2", "multiple statements"),
        ("SELECT 1 WHERE DROP = 1", "DROP"),
    ])
    def test_rejects_non_select(self, sql, expected_fragment):
        with pytest.raises(dbread.UnsafeSQLError) as exc_info:
            dbread.assert_select_only(sql)
        assert expected_fragment in str(exc_info.value)

    def test_run_select_rejects_before_touching_the_database(self):
        """The guard must fire before any DB connection is attempted — this
        must raise UnsafeSQLError even though MADS_DB_PATH (derived from the
        fake MADS_PROJECT_ROOT) does not exist on disk at all.
        """
        with pytest.raises(dbread.UnsafeSQLError):
            dbread.run_select("DROP TABLE changelog")


# ─────────────────────────────────────────────────────────────────────────
# http.py — Meta error classifier + no-real-network HTTP behavior
# ─────────────────────────────────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text if text else json.dumps(self._json_data)

    def json(self):
        return self._json_data


class TestClassifyMetaError:
    @pytest.mark.parametrize("fb_code,expected_key", [
        (190, "AUTH"),          # Invalid/expired OAuth access token
        (102, "AUTH"),          # Session key invalid
        (200, "AUTH"),          # Permissions error
        (10, "AUTH"),           # App lacks permission
        (2500, "VALIDATION"),   # Malformed access token usage
        (100, "VALIDATION"),    # Invalid parameter
        (4, "RATE_LIMIT"),      # App request limit reached
        (17, "RATE_LIMIT"),     # User request limit reached
        (32, "RATE_LIMIT"),     # Page request limit reached
        (613, "RATE_LIMIT"),    # Calls exceeded rate limit
        (80004, "RATE_LIMIT"),  # Ads Insights rate limit
        (803, "NOT_FOUND"),     # Unknown aliases/object not found
    ])
    def test_known_error_codes_map_to_expected_exit_class(self, fb_code, expected_key):
        response = {"error": {"code": fb_code, "message": "boom", "type": "OAuthException", "fbtrace_id": "tid-1"}}
        classified = classify_meta_error(400, response)
        assert classified is not None
        assert classified["code"] == expected_key
        assert classified["exit_code"] == EXIT_CODES[expected_key]
        assert classified["error_code"] == fb_code
        assert classified["fbtrace_id"] == "tid-1"

    @pytest.mark.parametrize("status_code,expected_key", [
        (401, "AUTH"),
        (404, "NOT_FOUND"),
        (429, "RATE_LIMIT"),
        (500, "API"),
        (503, "API"),
    ])
    def test_unknown_error_code_falls_back_to_status_code(self, status_code, expected_key):
        response = {"error": {"code": 999999, "message": "unrecognized Meta error code"}}
        classified = classify_meta_error(status_code, response)
        assert classified["code"] == expected_key
        assert classified["exit_code"] == EXIT_CODES[expected_key]

    @pytest.mark.parametrize("response_json", [
        None,
        [],
        "not a dict",
        {},
        {"data": []},
        {"error": "not a dict either"},
    ])
    def test_returns_none_when_no_error_envelope(self, response_json):
        assert classify_meta_error(200, response_json) is None


class TestGraphRequestNoRealNetwork:
    """Every test here mocks `requests.request` (the only transport call
    mads_lib/http.py makes — see graph_request()'s body); requests.request is
    replaced with a stub that returns a canned _FakeResponse, so no socket is
    ever opened.
    """

    def test_known_error_code_exits_with_mapped_code_and_json_envelope(self, monkeypatch, fake_token, capsys):
        fake_resp = _FakeResponse(
            status_code=401,
            json_data={"error": {"code": 190, "message": "Invalid OAuth access token", "type": "OAuthException", "fbtrace_id": "tid-abc"}},
        )
        monkeypatch.setattr("mads_lib.http.requests.request", lambda *a, **k: fake_resp)

        with pytest.raises(SystemExit) as exc_info:
            graph_request("GET", "me", token=fake_token, as_json=True)

        assert exc_info.value.code == EXIT_CODES["AUTH"] == 3
        captured = capsys.readouterr()
        body = json.loads(captured.out)
        assert body["error"]["code"] == "AUTH"
        assert body["error"]["error_code"] == 190
        assert body["error"]["exit_code"] == 3

    def test_rate_limit_code_exits_8(self, monkeypatch, fake_token):
        fake_resp = _FakeResponse(
            status_code=400,
            json_data={"error": {"code": 17, "message": "User request limit reached"}},
        )
        monkeypatch.setattr("mads_lib.http.requests.request", lambda *a, **k: fake_resp)

        with pytest.raises(SystemExit) as exc_info:
            graph_request("GET", "act_123/campaigns", token=fake_token, as_json=True)

        assert exc_info.value.code == EXIT_CODES["RATE_LIMIT"] == 8

    def test_error_in_non_json_mode_still_exits_with_mapped_code(self, monkeypatch, fake_token):
        fake_resp = _FakeResponse(
            status_code=404,
            json_data={"error": {"code": 803, "message": "Some aliases do not exist"}},
        )
        monkeypatch.setattr("mads_lib.http.requests.request", lambda *a, **k: fake_resp)

        with pytest.raises(SystemExit) as exc_info:
            graph_request("GET", "act_123/campaigns", token=fake_token, as_json=False)

        assert exc_info.value.code == EXIT_CODES["NOT_FOUND"] == 4

    def test_success_path_returns_parsed_json_and_injects_auth_params(self, monkeypatch, fake_token):
        captured_calls = []

        def fake_request(method, url, **kwargs):
            captured_calls.append((method, url, kwargs))
            return _FakeResponse(status_code=200, json_data={"data": [{"id": "123"}]})

        monkeypatch.setattr("mads_lib.http.requests.request", fake_request)

        result = graph_request("GET", "act_123/campaigns", token=fake_token, as_json=True)

        assert result == {"data": [{"id": "123"}]}
        assert len(captured_calls) == 1
        method, url, kwargs = captured_calls[0]
        assert method == "GET"
        assert url.endswith("act_123/campaigns")
        assert kwargs["params"]["access_token"] == fake_token
        assert "appsecret_proof" in kwargs["params"]

    def test_batch_request_rejects_over_hard_limit_without_any_request(self, monkeypatch):
        calls = []
        monkeypatch.setattr("mads_lib.http.requests.request", lambda *a, **k: calls.append(1))

        too_many_ops = [{"method": "GET", "relative_url": "me"}] * (MAX_BATCH_OPS + 1)
        with pytest.raises(ValueError, match="exceeds Meta's hard batch"):
            batch_request(too_many_ops)

        assert calls == []  # client-side rejection — no network attempted

    def test_batch_request_rejects_empty_list(self):
        with pytest.raises(ValueError, match="must not be empty"):
            batch_request([])

    def test_batch_request_rejects_non_list(self):
        with pytest.raises(ValueError, match="must be a list"):
            batch_request({"method": "GET"})


class TestAutoLogSurvivesMissingDB:
    """Regression test for the known bug pattern: `get_db()` raises
    `SystemExit(1)` (not a plain `Exception`) when MADS_DB_PATH doesn't exist
    yet. `mads_lib.cli._auto_log()` is documented as "never raises" (it's a
    best-effort changelog write called after a mutation has *already*
    succeeded against the live API) — it must swallow that SystemExit too,
    not just plain exceptions, or a successful mutation would incorrectly
    surface as a failed command.
    """

    def test_auto_log_swallows_systemexit_from_missing_db(self, monkeypatch):
        def _raise_system_exit(*a, **k):
            raise SystemExit(1)

        monkeypatch.setattr("mads_lib.cli.get_db", _raise_system_exit)

        # Must not raise — this is the whole point of _auto_log being
        # "best-effort". Before the fix, `except Exception:` let SystemExit
        # (a BaseException subclass, not an Exception subclass) escape here.
        from mads_lib.cli import _auto_log
        _auto_log("test_action", "test details", campaign_name="c", campaign_id="123")

    def test_auto_log_swallows_plain_exception_from_missing_db(self, monkeypatch):
        def _raise(*a, **k):
            raise RuntimeError("some other DB error")

        monkeypatch.setattr("mads_lib.cli.get_db", _raise)

        from mads_lib.cli import _auto_log
        _auto_log("test_action", "test details")


class TestGraphRequestNetworkErrors:
    """Network-layer failures (timeouts, DNS/connection errors) must be
    caught distinctly from HTTP-level 4xx/5xx API errors and produce a
    clean, classified SystemExit — not a raw exception/traceback leaking out
    of graph_request() to the caller.
    """

    def test_timeout_exits_with_clear_message(self, monkeypatch, fake_token, capsys):
        def _raise_timeout(*a, **k):
            raise requests.exceptions.Timeout("Connection timed out")

        monkeypatch.setattr("mads_lib.http.requests.request", _raise_timeout)

        with pytest.raises(SystemExit) as exc_info:
            graph_request("GET", "act_123/campaigns", token=fake_token, as_json=True)

        assert exc_info.value.code == EXIT_CODES["API"]
        captured = capsys.readouterr()
        body = json.loads(captured.err)
        assert "timed out" in body["error"]["message"].lower()

    def test_connection_error_exits_with_clear_message_not_raw(self, monkeypatch, fake_token, capsys):
        def _raise_conn_error(*a, **k):
            raise requests.exceptions.ConnectionError(
                "HTTPSConnectionPool(host='graph.facebook.com', port=443): "
                "Max retries exceeded (Failed to establish a new connection)"
            )

        monkeypatch.setattr("mads_lib.http.requests.request", _raise_conn_error)

        with pytest.raises(SystemExit) as exc_info:
            graph_request("GET", "act_123/campaigns", token=fake_token, as_json=True)

        assert exc_info.value.code == EXIT_CODES["API"]
        captured = capsys.readouterr()
        body = json.loads(captured.err)
        # Message must be classified/actionable — mentioning the network angle —
        # not just the bare urllib3 string with no guidance.
        assert "could not reach" in body["error"]["message"].lower()
        assert "network" in body["error"]["message"].lower() or "dns" in body["error"]["message"].lower()

    def test_generic_request_exception_exits_cleanly(self, monkeypatch, fake_token):
        def _raise_generic(*a, **k):
            raise requests.exceptions.RequestException("some other transport failure")

        monkeypatch.setattr("mads_lib.http.requests.request", _raise_generic)

        with pytest.raises(SystemExit) as exc_info:
            graph_request("GET", "act_123/campaigns", token=fake_token, as_json=False)

        assert exc_info.value.code == EXIT_CODES["API"]


class TestAccountIdValidation:
    """audiences.py and capi.py functions previously did
    `account = ad_account_id or AD_ACCOUNT_ID` with no validation and no
    `act_` prefix normalization — an empty/missing account id silently built
    a malformed path (e.g. `/customaudiences` with no account node) instead
    of a clear pre-flight VALIDATION error, and a bare numeric id (no `act_`
    prefix) would 404 against the live API instead of being normalized.
    """

    def test_list_audiences_raises_validation_error_when_account_missing(self, monkeypatch):
        monkeypatch.setattr("mads_lib.audiences.AD_ACCOUNT_ID", "")
        with pytest.raises(SystemExit) as exc_info:
            mads_lib.audiences.list_audiences(ad_account_id=None, as_json=True)
        assert exc_info.value.code == EXIT_CODES["VALIDATION"]

    def test_list_audiences_normalizes_bare_numeric_account_id(self, monkeypatch, fake_token):
        captured_urls = []

        def fake_request(method, url, **kwargs):
            captured_urls.append(url)
            return _FakeResponse(status_code=200, json_data={"data": []})

        monkeypatch.setattr("mads_lib.http.requests.request", fake_request)
        mads_lib.audiences.list_audiences(ad_account_id="1234567890", token=fake_token, as_json=True)

        assert len(captured_urls) == 1
        assert "/act_1234567890/customaudiences" in captured_urls[0]

    def test_create_pixel_raises_validation_error_when_account_missing(self, monkeypatch):
        monkeypatch.setattr("mads_lib.capi.AD_ACCOUNT_ID", "")
        with pytest.raises(SystemExit) as exc_info:
            mads_lib.capi.create_pixel("test pixel", ad_account_id=None, as_json=True)
        assert exc_info.value.code == EXIT_CODES["VALIDATION"]

    def test_create_catalog_raises_validation_error_when_business_id_missing(self, monkeypatch):
        monkeypatch.setattr("mads_lib.commerce.BUSINESS_ID", "")
        with pytest.raises(SystemExit) as exc_info:
            mads_lib.commerce.create_catalog("test catalog", business_id=None, as_json=True)
        assert exc_info.value.code == EXIT_CODES["VALIDATION"]


class TestMutatePartialProgress:
    """`mads mutate` runs multiple ops as sequential client-side HTTP calls
    (not the Meta batch API). If op N fails partway through, ops 0..N-1 have
    already executed against the live account — the user must be told how
    much already ran so they don't blindly re-run (and duplicate) the whole
    batch.
    """

    def test_partial_failure_reports_how_many_ops_already_ran(self, monkeypatch, tmp_path):
        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append(path)
            if len(calls) == 2:
                raise SystemExit(EXIT_CODES["AUTH"])
            return {"id": f"fake_{len(calls)}"}

        monkeypatch.setattr("mads_lib.cli.graph_request", fake_graph_request)

        ops_json = json.dumps([{"name": "a"}, {"name": "b"}, {"name": "c"}])
        result = runner.invoke(
            cli, ["mutate", "act_123/campaigns", ops_json, "--yes"],
        )

        assert result.exit_code == EXIT_CODES["AUTH"]
        assert len(calls) == 2  # third op never ran
        assert "1 of 3" in result.output


class TestGetPageAccessToken:
    """`mads_lib.auth.get_page_access_token()` — fetch/cache a Page Access Token via
    GET /me/accounts, distinct from the general user/system-user token. See its docstring
    for why this exists (Meta error 190, "This method must be called with a Page Access
    Token", on page-scoped edges like /{page-id}/insights) and why caching to disk is safe
    (a Page Access Token derived from a valid user token was confirmed live, via
    GET /debug_token, to report `expires_at: 0` — non-expiring — independent of the parent
    user token's own expiry).
    """

    def _cache_path(self, tmp_path):
        return tmp_path / "meta-page-tokens.json"

    def test_cache_hit_returns_cached_token_without_any_network_call(self, monkeypatch, tmp_path):
        cache_path = self._cache_path(tmp_path)
        cache_path.write_text(json.dumps({"106391075531104": "cached-page-token"}))
        monkeypatch.setattr(mads_lib.auth, "PAGE_TOKENS_PATH", cache_path)

        def fail_if_called(*a, **k):
            raise AssertionError("graph_request must not be called on a cache hit")

        monkeypatch.setattr("mads_lib.http.graph_request", fail_if_called)

        token = mads_lib.auth.get_page_access_token("106391075531104")
        assert token == "cached-page-token"

    def test_cache_miss_fetches_from_me_accounts_and_writes_cache(self, monkeypatch, tmp_path):
        cache_path = self._cache_path(tmp_path)
        assert not cache_path.exists()
        monkeypatch.setattr(mads_lib.auth, "PAGE_TOKENS_PATH", cache_path)

        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append((method, path, kwargs.get("token")))
            return {
                "data": [
                    {"id": "106391075531104", "name": "Talas Tesla Auto Parts", "access_token": "fresh-page-token"},
                    {"id": "999", "name": "Other Page", "access_token": "other-page-token"},
                ]
            }

        monkeypatch.setattr("mads_lib.http.graph_request", fake_graph_request)

        token = mads_lib.auth.get_page_access_token("106391075531104", user_token="fake-user-token")

        assert token == "fresh-page-token"
        assert calls == [("GET", "me/accounts", "fake-user-token")]
        # Both pages returned by /me/accounts get cached in the same pass, not just the
        # one requested — the call is already paid for.
        cached = json.loads(cache_path.read_text())
        assert cached == {"106391075531104": "fresh-page-token", "999": "other-page-token"}

    def test_page_not_managed_by_token_exits_1_with_clear_message(self, monkeypatch, tmp_path, capsys):
        cache_path = self._cache_path(tmp_path)
        monkeypatch.setattr(mads_lib.auth, "PAGE_TOKENS_PATH", cache_path)

        def fake_graph_request(method, path, **kwargs):
            return {"data": [{"id": "999", "name": "Other Page", "access_token": "other-page-token"}]}

        monkeypatch.setattr("mads_lib.http.graph_request", fake_graph_request)

        with pytest.raises(SystemExit) as exc_info:
            mads_lib.auth.get_page_access_token("106391075531104", user_token="fake-user-token")
        assert exc_info.value.code == 1
        assert "106391075531104" in capsys.readouterr().err

    def test_force_refresh_bypasses_a_stale_cache(self, monkeypatch, tmp_path):
        cache_path = self._cache_path(tmp_path)
        cache_path.write_text(json.dumps({"106391075531104": "stale-token"}))
        monkeypatch.setattr(mads_lib.auth, "PAGE_TOKENS_PATH", cache_path)

        def fake_graph_request(method, path, **kwargs):
            return {"data": [{"id": "106391075531104", "name": "P", "access_token": "renewed-token"}]}

        monkeypatch.setattr("mads_lib.http.graph_request", fake_graph_request)

        token = mads_lib.auth.get_page_access_token(
            "106391075531104", user_token="fake-user-token", force_refresh=True,
        )
        assert token == "renewed-token"
        assert json.loads(cache_path.read_text())["106391075531104"] == "renewed-token"

    def test_corrupt_cache_file_is_ignored_not_fatal(self, monkeypatch, tmp_path):
        cache_path = self._cache_path(tmp_path)
        cache_path.write_text("{not valid json")
        monkeypatch.setattr(mads_lib.auth, "PAGE_TOKENS_PATH", cache_path)

        def fake_graph_request(method, path, **kwargs):
            return {"data": [{"id": "106391075531104", "name": "P", "access_token": "recovered-token"}]}

        monkeypatch.setattr("mads_lib.http.graph_request", fake_graph_request)

        token = mads_lib.auth.get_page_access_token("106391075531104", user_token="fake-user-token")
        assert token == "recovered-token"


class TestPageInsightsDeprecatedMetrics:
    """Pre-flight metric validation in mads_lib/pages.py — both the originally-documented
    2026-06-15 deprecation wave, and additional metrics confirmed dead by live testing
    against the real Meta Graph API on 2026-07-02 (graph-api.md's "current metrics" table
    had incorrectly kept listing `page_impressions`/`page_fans`/etc. as valid).
    """

    def test_rejects_metrics_confirmed_dead_by_live_2026_07_02_testing(self):
        with pytest.raises(SystemExit) as exc_info:
            mads_lib.pages._check_deprecated_metrics(
                "page_impressions,page_fans,page_engaged_users", as_json=True,
            )
        assert exc_info.value.code == EXIT_CODES["VALIDATION"]

    def test_rejects_original_2026_06_15_deprecated_metric(self):
        with pytest.raises(SystemExit) as exc_info:
            mads_lib.pages._check_deprecated_metrics("page_impressions_unique", as_json=True)
        assert exc_info.value.code == EXIT_CODES["VALIDATION"]

    def test_rejects_10s_video_view_family_by_prefix(self):
        with pytest.raises(SystemExit) as exc_info:
            mads_lib.pages._check_deprecated_metrics("page_video_views_10s_autoplayed", as_json=True)
        assert exc_info.value.code == EXIT_CODES["VALIDATION"]

    def test_allows_current_valid_metrics(self):
        # Should not raise.
        mads_lib.pages._check_deprecated_metrics(
            "page_post_engagements,page_media_view,page_total_media_view_unique,page_follows",
            as_json=True,
        )


class TestInsightsRequestWithRetry:
    """`mads_lib.pages._insights_request_with_retry()` — the cache-hit-first, retry-once-on-
    AUTH-failure wrapper around GET /{page-id}/insights.
    """

    def test_success_on_first_attempt_returns_result_without_retry(self, monkeypatch):
        monkeypatch.setattr(mads_lib.pages, "get_page_access_token", lambda page_id, **k: "page-token-1")

        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append(kwargs.get("token"))
            return {"data": [{"name": "page_media_view", "values": []}]}

        monkeypatch.setattr(mads_lib.pages, "graph_request", fake_graph_request)

        result = mads_lib.pages._insights_request_with_retry(
            "106391075531104", {"metric": "page_media_view", "period": "day"}, as_json=True,
        )
        assert result["data"][0]["name"] == "page_media_view"
        assert calls == ["page-token-1"]  # only one attempt, no retry

    def test_auth_failure_on_cached_token_triggers_one_retry_with_fresh_token(self, monkeypatch):
        tokens_requested = []

        def fake_get_page_access_token(page_id, user_token=None, force_refresh=False):
            tokens_requested.append(force_refresh)
            return "stale-token" if not force_refresh else "fresh-token"

        monkeypatch.setattr(mads_lib.pages, "get_page_access_token", fake_get_page_access_token)

        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append(kwargs.get("token"))
            if kwargs.get("token") == "stale-token":
                raise SystemExit(EXIT_CODES["AUTH"])
            return {"data": [{"name": "page_media_view", "values": []}]}

        monkeypatch.setattr(mads_lib.pages, "graph_request", fake_graph_request)

        result = mads_lib.pages._insights_request_with_retry(
            "106391075531104", {"metric": "page_media_view", "period": "day"}, as_json=True,
        )
        assert calls == ["stale-token", "fresh-token"]
        assert tokens_requested == [False, True]
        assert result["data"][0]["name"] == "page_media_view"

    def test_non_auth_failure_reraises_with_original_exit_code_no_retry(self, monkeypatch):
        monkeypatch.setattr(mads_lib.pages, "get_page_access_token", lambda page_id, **k: "page-token-1")

        calls = []

        def fake_graph_request(method, path, **kwargs):
            calls.append(kwargs.get("token"))
            raise SystemExit(EXIT_CODES["VALIDATION"])

        monkeypatch.setattr(mads_lib.pages, "graph_request", fake_graph_request)

        with pytest.raises(SystemExit) as exc_info:
            mads_lib.pages._insights_request_with_retry(
                "106391075531104", {"metric": "page_media_view", "period": "day"}, as_json=True,
            )
        assert exc_info.value.code == EXIT_CODES["VALIDATION"]
        assert calls == ["page-token-1"]  # no retry for a non-AUTH failure

    def test_non_auth_failure_output_is_not_swallowed(self, monkeypatch, capsys):
        """A real (non-AUTH) error's printed output must survive the buffer-and-replay
        used to suppress a *successful* retry's stray optimistic-attempt output."""
        monkeypatch.setattr(mads_lib.pages, "get_page_access_token", lambda page_id, **k: "page-token-1")

        def fake_graph_request(method, path, **kwargs):
            import sys
            sys.stderr.write("distinctive-error-marker\n")
            raise SystemExit(EXIT_CODES["VALIDATION"])

        monkeypatch.setattr(mads_lib.pages, "graph_request", fake_graph_request)

        with pytest.raises(SystemExit):
            mads_lib.pages._insights_request_with_retry(
                "106391075531104", {"metric": "page_media_view", "period": "day"}, as_json=True,
            )
        assert "distinctive-error-marker" in capsys.readouterr().err
