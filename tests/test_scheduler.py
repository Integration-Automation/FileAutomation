"""Tests for the cron parser and scheduler registry wiring.

The scheduler's live tick thread is intentionally *not* exercised here — we
verify parser correctness, job CRUD, duplicate rejection, and registry
wiring. End-to-end minute-boundary firing is covered manually / in the GUI.
"""

from __future__ import annotations

import datetime as dt

import pytest

from automation_file.exceptions import FileAutomationException
from automation_file.scheduler.cron import CronException, CronExpression
from automation_file.scheduler.manager import (
    Scheduler,
    SchedulerException,
    _safe_execute,
    register_scheduler_ops,
)


def test_cron_parses_star() -> None:
    expression = CronExpression.parse("* * * * *")
    assert 0 in expression.minutes and 59 in expression.minutes
    assert expression.matches(dt.datetime(2026, 4, 21, 12, 30))


def test_cron_parses_exact_minute() -> None:
    expression = CronExpression.parse("30 9 * * *")
    assert expression.minutes == frozenset({30})
    assert expression.hours == frozenset({9})
    assert expression.matches(dt.datetime(2026, 4, 21, 9, 30))
    assert not expression.matches(dt.datetime(2026, 4, 21, 9, 31))


def test_cron_parses_step() -> None:
    expression = CronExpression.parse("*/15 * * * *")
    assert expression.minutes == frozenset({0, 15, 30, 45})


def test_cron_parses_range_with_step() -> None:
    expression = CronExpression.parse("0 9-17/2 * * *")
    assert expression.hours == frozenset({9, 11, 13, 15, 17})


def test_cron_parses_list() -> None:
    expression = CronExpression.parse("0,15,30 * * * *")
    assert expression.minutes == frozenset({0, 15, 30})


def test_cron_parses_month_and_dow_aliases() -> None:
    expression = CronExpression.parse("0 0 * JAN mon")
    assert expression.months == frozenset({1})
    assert expression.weekdays == frozenset({1})


def test_cron_dow_seven_aliases_to_sunday() -> None:
    expression = CronExpression.parse("0 0 * * 7")
    assert expression.weekdays == frozenset({0})


def test_cron_rejects_wrong_field_count() -> None:
    with pytest.raises(CronException):
        CronExpression.parse("* * * *")


def test_cron_rejects_out_of_range() -> None:
    with pytest.raises(CronException):
        CronExpression.parse("60 * * * *")


def test_cron_rejects_empty_expression() -> None:
    with pytest.raises(CronException):
        CronExpression.parse("")


def test_cron_exception_inherits_from_file_automation() -> None:
    assert issubclass(CronException, FileAutomationException)


def test_scheduler_add_remove_lifecycle() -> None:
    engine = Scheduler()
    try:
        snapshot = engine.add("job-a", "*/5 * * * *", [["FA_schedule_list"]])
        assert snapshot["name"] == "job-a"
        assert snapshot["cron"] == "*/5 * * * *"
        assert snapshot["runs"] == 0
        assert "job-a" in engine
        assert len(engine.list()) == 1
        removed = engine.remove("job-a")
        assert removed["name"] == "job-a"
        assert engine.list() == []
    finally:
        engine.shutdown()


def test_scheduler_rejects_duplicate_names() -> None:
    engine = Scheduler()
    try:
        engine.add("dup", "* * * * *", [["FA_schedule_list"]])
        with pytest.raises(SchedulerException):
            engine.add("dup", "* * * * *", [["FA_schedule_list"]])
    finally:
        engine.shutdown()


def test_scheduler_remove_unknown_raises() -> None:
    engine = Scheduler()
    try:
        with pytest.raises(SchedulerException):
            engine.remove("nope")
    finally:
        engine.shutdown()


def test_scheduler_remove_all_clears_everything() -> None:
    engine = Scheduler()
    try:
        engine.add("a", "* * * * *", [["FA_schedule_list"]])
        engine.add("b", "* * * * *", [["FA_schedule_list"]])
        snapshots = engine.remove_all()
        assert len(snapshots) == 2
        assert engine.list() == []
    finally:
        engine.shutdown()


def test_scheduler_rejects_bad_cron() -> None:
    engine = Scheduler()
    try:
        with pytest.raises(CronException):
            engine.add("bad", "not a cron", [["FA_schedule_list"]])
    finally:
        engine.shutdown()


def test_scheduler_exception_inherits_from_file_automation() -> None:
    assert issubclass(SchedulerException, FileAutomationException)


def test_register_scheduler_ops_populates_registry() -> None:
    from automation_file.core.action_registry import ActionRegistry

    registry = ActionRegistry()
    register_scheduler_ops(registry)
    for name in (
        "FA_schedule_add",
        "FA_schedule_remove",
        "FA_schedule_remove_all",
        "FA_schedule_list",
    ):
        assert name in registry


def test_default_registry_contains_scheduler_ops() -> None:
    from automation_file.core.action_registry import build_default_registry

    registry = build_default_registry()
    assert "FA_schedule_add" in registry
    assert "FA_schedule_list" in registry


def test_safe_execute_swallows_exceptions_cleanly() -> None:
    _safe_execute("unit-test", [["FA_does_not_exist"]])
