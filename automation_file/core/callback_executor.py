"""Callback executor — runs a trigger, then a callback.

Implements the "do X then do Y" flow many automation JSON files want. The
registry is shared with :class:`ActionExecutor`, so adding a command to one
adds it to the other (je_action_core's callback executor, strict checks).
"""

from __future__ import annotations

from je_action_core import (
    CallbackErrorPolicy,
    CallbackFunctionExecutor,
    CallbackSettings,
    CallbackStyle,
)

from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import CallbackExecutorException
from automation_file.logging_config import file_automation_logger

_SETTINGS = CallbackSettings(
    error=CallbackExecutorException,
    style=CallbackStyle.STRICT,
    on_error=CallbackErrorPolicy.RAISE,
    log_info=file_automation_logger.info,
)


class CallbackExecutor(CallbackFunctionExecutor):
    """Invoke ``trigger(**kwargs)`` then ``callback(*args | **kwargs)``."""

    registry: ActionRegistry

    def __init__(self, registry: ActionRegistry) -> None:
        super().__init__(registry, _SETTINGS)
