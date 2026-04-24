"""Tests for validation, dry-run, and parallel execution."""

from __future__ import annotations

import threading
import time

import pytest

from automation_file.core.action_executor import ActionExecutor
from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import ValidationException


def _fresh_executor() -> ActionExecutor:
    registry = ActionRegistry()
    registry.register("echo", lambda value: value)
    registry.register("add", lambda a, b: a + b)
    return ActionExecutor(registry=registry)


def test_validate_accepts_known_actions() -> None:
    executor = _fresh_executor()
    names = executor.validate([["echo", {"value": 1}], ["add", [1, 2]]])
    assert names == ["echo", "add"]


def test_validate_rejects_unknown_action() -> None:
    executor = _fresh_executor()
    with pytest.raises(ValidationException):
        executor.validate([["echo", {"value": 1}], ["missing"]])


def test_validate_rejects_malformed_action() -> None:
    executor = _fresh_executor()
    with pytest.raises(ValidationException):
        executor.validate([[123]])


def test_validate_first_aborts_before_execution() -> None:
    executor = _fresh_executor()
    calls: list[int] = []
    executor.registry.register("count", lambda: calls.append(1) or len(calls))
    with pytest.raises(ValidationException):
        executor.execute_action(
            [["count"], ["count"], ["does_not_exist"]],
            validate_first=True,
        )
    assert not calls  # nothing ran because validation failed first


def test_dry_run_does_not_invoke_commands() -> None:
    executor = _fresh_executor()
    calls: list[int] = []
    executor.registry.register("count", lambda: calls.append(1) or 1)
    results = executor.execute_action([["count"], ["count"]], dry_run=True)
    assert not calls
    assert all(value.startswith("dry_run:") for value in results.values())


def test_dry_run_records_unknown_as_error() -> None:
    executor = _fresh_executor()
    results = executor.execute_action([["missing"]], dry_run=True)
    [value] = results.values()
    assert "unknown action" in value


def test_parallel_execution_runs_concurrently() -> None:
    executor = _fresh_executor()
    barrier = threading.Barrier(parties=3, timeout=2.0)

    def wait() -> str:
        barrier.wait()
        return "ok"

    executor.registry.register("wait", wait)
    start = time.monotonic()
    results = executor.execute_action_parallel(
        [["wait"], ["wait"], ["wait"]],
        max_workers=3,
    )
    elapsed = time.monotonic() - start
    assert list(results.values()) == ["ok", "ok", "ok"]
    # If they were serial, barrier.wait would time out. That we got here
    # means all three crossed the barrier together.
    assert elapsed < 2.0
