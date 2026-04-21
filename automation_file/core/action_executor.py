"""Action executor (Facade + Template Method over :class:`ActionRegistry`).

An *action* is one of three shapes inside a JSON list:

* ``[name]`` — call the registered command with no arguments
* ``[name, {kwargs}]`` — call ``command(**kwargs)``
* ``[name, [args]]`` — call ``command(*args)``

``ActionExecutor.execute_action`` iterates a list of actions and returns a
dict mapping each action's string form to either its return value or the
``repr`` of the exception it raised. This keeps one bad action from aborting
the batch, which is important when running against Google Drive where
transient errors are common.
"""
from __future__ import annotations

from typing import Any, Mapping

from automation_file.core.action_registry import ActionRegistry, build_default_registry
from automation_file.core.json_store import read_action_json
from automation_file.exceptions import ExecuteActionException
from automation_file.logging_config import file_automation_logger


class ActionExecutor:
    """Execute named actions resolved through an :class:`ActionRegistry`."""

    def __init__(self, registry: ActionRegistry | None = None) -> None:
        self.registry: ActionRegistry = registry or build_default_registry()
        self.registry.register_many(
            {
                "FA_execute_action": self.execute_action,
                "FA_execute_files": self.execute_files,
            }
        )

    # Template-method: single action ------------------------------------
    def _execute_event(self, action: list) -> Any:
        if not isinstance(action, list) or not action:
            raise ExecuteActionException(f"malformed action: {action!r}")
        name = action[0]
        command = self.registry.resolve(name)
        if command is None:
            raise ExecuteActionException(f"unknown action: {name!r}")
        if len(action) == 1:
            return command()
        if len(action) == 2:
            payload = action[1]
            if isinstance(payload, dict):
                return command(**payload)
            if isinstance(payload, list):
                return command(*payload)
            raise ExecuteActionException(
                f"action {name!r} payload must be dict or list, got {type(payload).__name__}"
            )
        raise ExecuteActionException(f"action has too many elements: {action!r}")

    # Public API --------------------------------------------------------
    def execute_action(self, action_list: list | Mapping[str, Any]) -> dict[str, Any]:
        """Execute every action; return ``{"execute: <action>": result|repr(error)}``."""
        actions = self._coerce(action_list)
        results: dict[str, Any] = {}
        for action in actions:
            key = f"execute: {action}"
            try:
                results[key] = self._execute_event(action)
                file_automation_logger.info("execute_action: %s", action)
            except ExecuteActionException as error:
                file_automation_logger.error("execute_action malformed: %r", error)
                results[key] = repr(error)
            except Exception as error:  # pylint: disable=broad-except
                file_automation_logger.error("execute_action runtime error: %r", error)
                results[key] = repr(error)
        return results

    def execute_files(self, execute_files_list: list[str]) -> list[dict[str, Any]]:
        """Execute every JSON file's action list and return their results."""
        return [self.execute_action(read_action_json(path)) for path in execute_files_list]

    def add_command_to_executor(self, command_dict: Mapping[str, Any]) -> None:
        """Register every ``name -> callable`` pair (Registry facade)."""
        file_automation_logger.info(
            "add_command_to_executor: %s", list(command_dict.keys())
        )
        self.registry.register_many(command_dict)

    # Internals ---------------------------------------------------------
    @staticmethod
    def _coerce(action_list: list | Mapping[str, Any]) -> list:
        if isinstance(action_list, Mapping):
            nested = action_list.get("auto_control")
            if nested is None:
                raise ExecuteActionException("dict action list missing 'auto_control'")
            action_list = nested
        if not isinstance(action_list, list):
            raise ExecuteActionException(
                f"action_list must be list, got {type(action_list).__name__}"
            )
        if not action_list:
            raise ExecuteActionException("action_list is empty")
        return action_list


# Default shared executor — built once, mutated in place by plugins.
executor: ActionExecutor = ActionExecutor()


def execute_action(action_list: list | Mapping[str, Any]) -> dict[str, Any]:
    """Module-level shim that delegates to the shared executor."""
    return executor.execute_action(action_list)


def execute_files(execute_files_list: list[str]) -> list[dict[str, Any]]:
    """Module-level shim that delegates to the shared executor."""
    return executor.execute_files(execute_files_list)


def add_command_to_executor(command_dict: Mapping[str, Any]) -> None:
    """Module-level shim that delegates to the shared executor."""
    executor.add_command_to_executor(command_dict)
