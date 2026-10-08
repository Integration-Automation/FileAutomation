"""parse_rfc3339: the timestamps of the cloud APIs as aware UTC datetimes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from automation_file.storage.timestamps import parse_rfc3339


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2026-10-08T02:30:00Z", datetime(2026, 10, 8, 2, 30, tzinfo=timezone.utc)),
        ("2026-10-08T02:30:00.123Z", datetime(2026, 10, 8, 2, 30, 0, 123000, tzinfo=timezone.utc)),
        # Seven digits, as Microsoft Graph sends: cut to microseconds, not rounded.
        (
            "2026-10-08T02:30:00.1234567Z",
            datetime(2026, 10, 8, 2, 30, 0, 123456, tzinfo=timezone.utc),
        ),
        ("2026-10-08T02:30:00.5z", datetime(2026, 10, 8, 2, 30, 0, 500000, tzinfo=timezone.utc)),
        ("2026-10-08T10:30:00+08:00", datetime(2026, 10, 8, 2, 30, tzinfo=timezone.utc)),
        (
            "2026-10-07T21:00:00.25-05:30",
            datetime(2026, 10, 8, 2, 30, 0, 250000, tzinfo=timezone.utc),
        ),
        ("2026-10-08t02:30:00+00:00", datetime(2026, 10, 8, 2, 30, tzinfo=timezone.utc)),
        (" 2026-10-08 02:30:00Z ", datetime(2026, 10, 8, 2, 30, tzinfo=timezone.utc)),
        ("0001-01-01T00:00:00Z", datetime(1, 1, 1, tzinfo=timezone.utc)),
    ],
)
def test_a_timestamp_becomes_an_aware_utc_datetime(text: str, expected: datetime) -> None:
    parsed = parse_rfc3339(text)
    assert parsed == expected
    assert parsed is not None
    assert parsed.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "value",
    [
        None,
        1759890600,
        "",
        "yesterday",
        "2026-10-08",
        "2026-10-08T02:30:00",
        "2026-10-08T02:30Z",
        "2026-13-08T02:30:00Z",
        "2026-10-08T02:30:60Z",
        "2026-10-08T02:30:00+99:00",
        "0001-01-01T00:00:00+05:00",
        "2026-10-08T02:30:00Z trailing",
    ],
)
def test_anything_else_is_none(value: object) -> None:
    assert parse_rfc3339(value) is None
