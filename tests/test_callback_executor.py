"""Tests for automation_file.core.callback_executor."""
from __future__ import annotations

import pytest

from automation_file.core.action_registry import ActionRegistry
from automation_file.core.callback_executor import CallbackExecutor
from automation_file.exceptions import CallbackExecutorException


def test_callback_runs_after_trigger() -> None:
    registry = ActionRegistry({"trigger": lambda value: value.upper()})
    executor = CallbackExecutor(registry)
    seen: list[str] = []

    result = executor.callback_function(
        trigger_function_name="trigger",
        callback_function=lambda tag: seen.append(tag),
        callback_function_param={"tag": "done"},
        value="hi",
    )
    assert result == "HI"
    assert seen == ["done"]


def test_callback_with_positional_payload() -> None:
    registry = ActionRegistry({"trigger": lambda: "x"})
    executor = CallbackExecutor(registry)
    seen: list[int] = []

    executor.callback_function(
        trigger_function_name="trigger",
        callback_function=lambda a, b: seen.append(a + b),
        callback_function_param=[2, 3],
        callback_param_method="args",
    )
    assert seen == [5]


def test_callback_no_payload() -> None:
    registry = ActionRegistry({"trigger": lambda: "ok"})
    executor = CallbackExecutor(registry)
    marker: list[str] = []

    executor.callback_function(
        trigger_function_name="trigger",
        callback_function=lambda: marker.append("called"),
    )
    assert marker == ["called"]


def test_callback_unknown_trigger_raises() -> None:
    executor = CallbackExecutor(ActionRegistry())
    with pytest.raises(CallbackExecutorException):
        executor.callback_function("missing", callback_function=lambda: None)


def test_callback_bad_method_raises() -> None:
    registry = ActionRegistry({"t": lambda: None})
    executor = CallbackExecutor(registry)
    with pytest.raises(CallbackExecutorException):
        executor.callback_function(
            "t", callback_function=lambda: None, callback_param_method="neither",
        )


def test_callback_kwargs_requires_mapping() -> None:
    registry = ActionRegistry({"t": lambda: None})
    executor = CallbackExecutor(registry)
    with pytest.raises(CallbackExecutorException):
        executor.callback_function(
            "t",
            callback_function=lambda **_: None,
            callback_function_param=[1, 2],
            callback_param_method="kwargs",
        )
