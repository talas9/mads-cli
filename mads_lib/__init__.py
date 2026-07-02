"""Internal library for the mads CLI."""

__version__ = "0.2.0"

from .config import (
    PROJECT_ROOT,
    CONFIG_HOME,
    GLOBAL_HOME,
    SCOPE_ROOT,
    SCOPE_TYPE,
    DB_PATH,
    CREDS_PATH,
    SNAPSHOTS_DIR,
    API_VERSION,
    APP_ID,
    APP_SECRET,
    AD_ACCOUNT_ID,
    BUSINESS_ID,
    TZ_NAME,
    CURRENCY,
)
from .auth import get_access_token, get_appsecret_proof
from .db import get_db
from .output import flatten, print_json, print_table, print_error, EXIT_CODES
from .timeutil import now_local, today_local

# TODO(mads-cli): once resource-group modules exist (campaign.py, adset.py,
# ad.py, creative.py, etc. — mirroring gads-cli's ads.py/gbp.py/merchant.py
# pattern), import and re-export their public functions here so cli.py can
# do `from mads_lib import campaign_list, ...` the same way gads-cli does.
