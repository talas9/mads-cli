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
from click.testing import CliRunner

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
