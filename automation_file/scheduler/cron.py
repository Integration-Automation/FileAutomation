"""Minimal 5-field cron expression parser (stdlib-only).

Supports ``*``, exact values, ``a-b`` ranges, ``a,b,c`` lists, and ``*/n`` or
``a-b/n`` step syntax. Fields are, in order: minute (0-59), hour (0-23),
day-of-month (1-31), month (1-12), day-of-week (0-6, Sunday = 0 or 7). Names
(``jan``..``dec`` / ``sun``..``sat``) are accepted case-insensitively.

Explicitly *not* supported: ``@yearly`` / ``@reboot`` aliases, ``L``/``W``
modifiers, seconds. Callers needing that should use a dedicated cron library.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from automation_file.exceptions import FileAutomationException


class CronException(FileAutomationException):
    """Raised when a cron expression cannot be parsed."""


_FIELD_BOUNDS = (
    (0, 59),
    (0, 23),
    (1, 31),
    (1, 12),
    (0, 6),
)

_MONTH_ALIASES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip

_DOW_ALIASES = {
    "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
}  # fmt: skip


def _resolve_alias(token: str, field_index: int) -> str:
    lowered = token.lower()
    if field_index == 3 and lowered in _MONTH_ALIASES:
        return str(_MONTH_ALIASES[lowered])
    if field_index == 4 and lowered in _DOW_ALIASES:
        return str(_DOW_ALIASES[lowered])
    return token


def _parse_value(token: str, field_index: int) -> int:
    resolved = _resolve_alias(token, field_index)
    try:
        return int(resolved)
    except ValueError as error:
        raise CronException(f"cron: non-numeric value {token!r}") from error


def _expand_range(start: int, end: int, step: int, low: int, high: int) -> set[int]:
    if start < low or end > high or start > end:
        raise CronException(f"cron: range {start}-{end} outside [{low},{high}]")
    if step <= 0:
        raise CronException(f"cron: step must be positive, got {step}")
    return set(range(start, end + 1, step))


def _parse_field(raw: str, field_index: int) -> frozenset[int]:
    low, high = _FIELD_BOUNDS[field_index]
    # DoW accepts 7 as an alias for Sunday (0) before range validation.
    effective_high = 7 if field_index == 4 else high
    result: set[int] = set()
    for part in raw.split(","):
        chunk = part.strip()
        if not chunk:
            raise CronException(f"cron: empty chunk in field {field_index}")
        step = 1
        if "/" in chunk:
            base, step_text = chunk.split("/", 1)
            try:
                step = int(step_text)
            except ValueError as error:
                raise CronException(f"cron: bad step {step_text!r}") from error
            chunk = base
        if chunk == "*":
            result |= _expand_range(low, high, step, low, high)
            continue
        if "-" in chunk:
            start_text, end_text = chunk.split("-", 1)
            start = _parse_value(start_text, field_index)
            end = _parse_value(end_text, field_index)
            result |= _expand_range(start, end, step, low, effective_high)
            continue
        value = _parse_value(chunk, field_index)
        if value < low or value > effective_high:
            raise CronException(f"cron: value {value} outside [{low},{high}]")
        if step == 1:
            result.add(value)
        else:
            result |= _expand_range(value, effective_high, step, low, effective_high)
    if field_index == 4 and 7 in result:
        result.discard(7)
        result.add(0)
    return frozenset(result)


@dataclass(frozen=True)
class CronExpression:
    """Parsed 5-field cron expression."""

    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    source: str

    @classmethod
    def parse(cls, expression: str) -> CronExpression:
        if not expression or not expression.strip():
            raise CronException("cron: expression is empty")
        fields = expression.split()
        if len(fields) != 5:
            raise CronException(f"cron: expected 5 fields, got {len(fields)}: {expression!r}")
        minutes = _parse_field(fields[0], 0)
        hours = _parse_field(fields[1], 1)
        days = _parse_field(fields[2], 2)
        months = _parse_field(fields[3], 3)
        weekdays = _parse_field(fields[4], 4)
        return cls(minutes, hours, days, months, weekdays, expression.strip())

    def matches(self, moment: dt.datetime) -> bool:
        """Return ``True`` when ``moment`` satisfies every field."""
        weekday = moment.isoweekday() % 7  # Monday=1..Sunday=7 -> Monday=1..Sunday=0
        return (
            moment.minute in self.minutes
            and moment.hour in self.hours
            and moment.day in self.days
            and moment.month in self.months
            and weekday in self.weekdays
        )
