from datetime import datetime
from zoneinfo import ZoneInfo

from .config import TZ_NAME


def _tz():
    return ZoneInfo(TZ_NAME)


def now_local():
    """Current time in the configured timezone as ISO 8601."""
    return datetime.now(_tz()).isoformat(timespec="seconds")


def today_local():
    """Today's date in the configured timezone."""
    return datetime.now(_tz()).strftime("%Y-%m-%d")
