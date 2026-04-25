"""Tests for automation_file.core.action_executor."""

from __future__ import annotations

from pathlib import Path

import pytest

from automation_file.core.action_executor import ActionExecutor
from automation_file.core.action_registry import ActionRegistry
from automation_file.core.json_store import read_action_json
from automation_file.exceptions import AddCommandException, ExecuteActionException


def _fresh_executor() -> ActionExecutor:
    """Build a minimal executor with only a tiny registry (cheap, no Drive imports)."""
    registry = ActionRegistry()
    registry.register("echo", lambda value: value)
    registry.register("add", lambda a, b: a + b)
    return ActionExecutor(registry=registry)


def test_execute_action_kwargs() -> None:
    executor = _fresh_executor()
    results = executor.execute_action([["echo", {"value": "hi"}]])
    assert list(results.values()) == ["hi"]


def test_execute_action_args() -> None:
    executor = _fresh_executor()
    results = executor.execute_action([["add", [2, 3]]])
    assert list(results.values()) == [5]


def test_execute_action_no_args() -> None:
    executor = _fresh_executor()
    executor.registry.register("ping", lambda: "pong")
    results = executor.execute_action([["ping"]])
    assert list(results.values()) == ["pong"]


def test_execute_action_unknown_records_error() -> None:
    executor = _fresh_executor()
    results = executor.execute_action([["missing"]])
    [value] = results.values()
    assert "unknown action" in value


def _raise_runtime_error() -> None:
    raise RuntimeError("nope")


def test_execute_action_runtime_error_is_caught() -> None:
    executor = _fresh_executor()
    executor.registry.register("boom", _raise_runtime_error)
    results = executor.execute_action([["boom"]])
    [value] = results.values()
    assert "RuntimeError" in value


def test_execute_action_empty_raises() -> None:
    executor = _fresh_executor()
    with pytest.raises(ExecuteActionException):
        executor.execute_action([])


def test_execute_action_auto_control_key() -> None:
    executor = _fresh_executor()
    results = executor.execute_action({"auto_control": [["echo", {"value": 1}]]})
    assert list(results.values()) == [1]


def test_execute_action_missing_auto_control_key() -> None:
    executor = _fresh_executor()
    with pytest.raises(ExecuteActionException):
        executor.execute_action({"wrong": []})


def test_add_command_rejects_non_callable() -> None:
    executor = _fresh_executor()
    with pytest.raises(AddCommandException):
        executor.add_command_to_executor({"x": 123})


def test_execute_files(tmp_path: Path) -> None:
    executor = _fresh_executor()
    action_file = tmp_path / "actions.json"
    action_file.write_text('[["echo", {"value": "hello"}]]', encoding="utf-8")
    all_results = executor.execute_files([str(action_file)])
    assert len(all_results) == 1
    assert list(all_results[0].values()) == ["hello"]


def test_json_store_roundtrip(tmp_path: Path) -> None:
    from automation_file.core.json_store import write_action_json

    path = tmp_path / "payload.json"
    write_action_json(str(path), [["a", 1]])
    assert read_action_json(str(path)) == [["a", 1]]


def test_duplicate_actions_do_not_collide() -> None:
    """Two identical actions in one batch must keep both results."""
    executor = _fresh_executor()
    results = executor.execute_action(
        [
            ["echo", {"value": "first"}],
            ["echo", {"value": "first"}],
        ]
    )
    assert len(results) == 2
    assert list(results.values()) == ["first", "first"]


def test_substitute_does_not_leak_into_result_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """``substitute=True`` must keep the un-expanded literal in result keys."""
    sentinel = "sentinel-must-not-appear-in-key"
    monkeypatch.setenv("FA_EXEC_LEAK_PROBE", sentinel)
    executor = _fresh_executor()
    results = executor.execute_action(
        [["echo", {"value": "${env:FA_EXEC_LEAK_PROBE}"}]],
        substitute=True,
    )
    [(key, value)] = results.items()
    assert sentinel not in key
    assert "${env:FA_EXEC_LEAK_PROBE}" in key
    assert value == sentinel
