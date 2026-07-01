"""Shared fixtures for the mads-cli offline test suite.

Adapted from gads-cli's tests/conftest.py. The fake env vars below MUST be set
BEFORE any mads_lib import resolves config, since mads_lib/config.py reads
os.environ at *module import time* (SCOPE_ROOT/SCOPE_TYPE are computed and
.env files are loaded as soon as `mads_lib.config` is first imported). Setting
them here — at the top of conftest.py, which pytest imports before collecting
any test module — guarantees they win the race.

Critically, MADS_PROJECT_ROOT must point somewhere fake: without it,
config._detect_scope() walks up to the talas-ads project root (which *does*
have real data/ and credentials/ directories — see mads_lib/config.py's scope
detection), and would happily load the real .env / real Meta credentials
sitting there. Pointing MADS_PROJECT_ROOT at a scratch directory keeps every
test fully offline and credential-free.
"""
import os

import pytest

# ── Environment stubs — must be set BEFORE mads_lib imports resolve config ──
# These are set at module load time so config.py picks them up on first import.
os.environ.setdefault("META_APP_ID", "fake-app-id")
os.environ.setdefault("META_APP_SECRET", "fake-app-secret")
os.environ.setdefault("META_AD_ACCOUNT_ID", "act_1234567890")
os.environ.setdefault("META_SYSTEM_USER_TOKEN", "fake-system-user-token")
os.environ.setdefault("MADS_PROJECT_ROOT", "/tmp/mads-test-scope")


@pytest.fixture
def fake_token():
    """A fake Meta bearer token string.

    Unlike gads-cli, which loads a Google OAuth `Credentials` object (an
    object with a self-refreshing `.token` attribute — see gads-cli's
    `fake_creds` fixture and its MagicMock), Meta access tokens are just bare
    strings read straight off disk (mads_lib/auth.py::get_access_token()
    returns `creds_data["access_token"]`, nothing more). There is no
    credentials *object* to mock here — a plain string is the whole
    contract. Tests pass this directly as `token=` to graph_request()/
    batch_request() to skip CREDS_PATH file I/O entirely.
    """
    return os.environ["META_SYSTEM_USER_TOKEN"]
