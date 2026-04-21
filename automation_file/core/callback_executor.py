"""Callback executor — runs a trigger, then a callback.

Implements the "do X then do Y" flow many automation JSON files want. The
registry is shared with :class:`ActionExecutor`, so adding a command to one
adds it to the other.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import CallbackExecutorException
from automation_file.logging_config import file_automation_logger

_VALID_METHODS = frozenset({"kwargs", "args"})


class CallbackExecutor:
    """Invoke ``trigger(**kwargs)`` then ``callback(*args | **kwargs)``."""

    def __init__(self, registry: ActionRegistry) -> None:
        self.registry: ActionRegistry = registry

    def callback_function(
        self,
        trigger_function_name: str,
        callback_function: Callable[..., Any],
        callback_function_param: Mapping[str, Any] | list[Any] | None = None,
        callback_param_method: str = "kwargs",
        **kwargs: Any,
    ) -> Any:
        trigger = self.registry.resolve(trigger_function_name)
        if trigger is None:
            raise CallbackExecutorException(f"unknown trigger: {trigger_function_name!r}")
        if callback_param_method not in _VALID_METHODS:
            raise CallbackExecutorException(
                f"callback_param_method must be 'kwargs' or 'args', got {callback_param_method!r}"
            )

        file_automation_logger.info("callback: trigger=%s kwargs=%s", trigger_function_name, kwargs)
        return_value = trigger(**kwargs)

        if callback_function_param is None:
            callback_function()
        elif callback_param_method == "kwargs":
            if not isinstance(callback_function_param, Mapping):
                raise CallbackExecutorException(
                    "callback_param_method='kwargs' requires a mapping payload"
                )
            callback_function(**callback_function_param)
        else:
            if not isinstance(callback_function_param, (list, tuple)):
                raise CallbackExecutorException(
                    "callback_param_method='args' requires a list/tuple payload"
                )
            callback_function(*callback_function_param)

        file_automation_logger.info(
            "callback: done trigger=%s callback=%r", trigger_function_name, callback_function
        )
        return return_value
