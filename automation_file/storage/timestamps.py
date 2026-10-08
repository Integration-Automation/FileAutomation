"""RFC 3339 timestamps as cloud APIs send them (``2026-10-08T02:30:00.123Z``)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_RFC3339 = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:\d{2})"
)
_MICROSECOND_DIGITS = 6


def _utc_offset(zone: str) -> timedelta:
    if zone in ("Z", "z"):
        return timedelta(0)
    offset = timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
    return -offset if zone.startswith("-") else offset


def parse_rfc3339(value: object) -> datetime | None:
    """Return ``value`` as an aware UTC ``datetime``, or ``None`` when it is not a timestamp.

    A fraction of any length is accepted and cut to microseconds. Before Python
    3.11 ``datetime.fromisoformat`` reads neither that nor the ``Z`` suffix.
    """
    if not isinstance(value, str):
        return None
    match = _RFC3339.fullmatch(value.strip())
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(part) for part in match.groups()[:6])
    fraction = (match.group(7) or "")[:_MICROSECOND_DIGITS].ljust(_MICROSECOND_DIGITS, "0")
    try:
        zone = timezone(_utc_offset(match.group(8)))
        moment = datetime(year, month, day, hour, minute, second, int(fraction), tzinfo=zone)
        return moment.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        # Not a real date (month 13, second 60), or one that leaves the calendar in UTC.
        return None
