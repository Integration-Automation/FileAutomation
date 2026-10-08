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

import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from je_action_core import (
    ActionExecutor as _CoreActionExecutor,
)
from je_action_core import (
    ActionListRules,
    BoundAction,
    ExecutorSettings,
    ParsedAction,
    StrictActionParser,
    indexed_record_key,
)

from automation_file.core.action_registry import ActionRegistry, build_default_registry
from automation_file.core.json_store import read_action_json
from automation_file.core.metrics import record_action
from automation_file.core.substitution import substitute as substitute_payload
from automation_file.exceptions import ExecuteActionException, ValidationException
from automation_file.logging_config import file_automation_logger

_PARSER = StrictActionParser(error=ExecuteActionException)
# The document key FileAutomation inherited from AutoControl, and its list errors.
_SETTINGS = ExecutorSettings(
    rules=ActionListRules(
        "auto_control",
        error=ExecuteActionException,
        missing_message="dict action list missing {key!r}",
        not_list_message="action_list must be list, got {type}",
        empty_message="action_list is empty",
    ),
    parser=_PARSER,
    read_json=read_action_json,
    record_key=indexed_record_key,
)


class ActionExecutor(_CoreActionExecutor):
    """Execute named actions resolved through an :class:`ActionRegistry`.

    Uses the shared action executor's implementation.
    """

    registry: ActionRegistry

    def __init__(self, registry: ActionRegistry | None = None) -> None:
        super().__init__(_SETTINGS, registry or build_default_registry())
        self.registry.register_many(
            {
                "FA_execute_action": self.execute_action,
                "FA_execute_files": self.execute_files,
                "FA_execute_action_parallel": self.execute_action_parallel,
                "FA_validate": self.validate,
            }
        )

    # Template-method: single action ------------------------------------
    def invoke(self, bound: BoundAction) -> Any:
        """Call the bound command inside a tracing span named after the action."""
        from automation_file.core.tracing import action_span

        with action_span(bound.name):
            return super().invoke(bound)

    @staticmethod
    def _parse_action(action: list) -> ParsedAction:
        return _PARSER.parse(action)

    # Public API --------------------------------------------------------
    def validate(self, action_list: list | Mapping[str, Any]) -> list[str]:
        """Validate shape and resolve every name; return the list of action names.

        Raises :class:`ValidationException` on the first problem. Useful for
        fail-fast checks before executing an entire batch.
        """
        actions = self._coerce(action_list)
        names: list[str] = []
        for action in actions:
            try:
                name, _, _ = self._parse_action(action)
            except ExecuteActionException as error:
                raise ValidationException(str(error)) from error
            if self.registry.resolve(name) is None:
                raise ValidationException(f"unknown action: {name!r}")
            names.append(name)
        return names

    def execute_action(
        self,
        action_list: list | Mapping[str, Any],
        dry_run: bool = False,
        validate_first: bool = False,
        substitute: bool = False,
    ) -> dict[str, Any]:
        """Execute every action; return ``{"execute[<index>]: <action>": result|repr(error)}``.

        ``dry_run=True`` logs and records the resolved name without invoking the
        command. ``validate_first=True`` runs :meth:`validate` before touching
        any action so a typo aborts the whole batch up-front. ``substitute=True``
        expands ``${env:...}`` / ``${date:...}`` / ``${uuid}`` / ``${cwd}``
        placeholders inside every string in the payload — the original
        (un-substituted) action is used for log lines and result keys so
        secrets pulled in via ``${env:...}`` never reach logs.
        """
        actions = self._coerce(action_list)
        executed: list = (
            substitute_payload(actions) if substitute else actions  # type: ignore[assignment]
        )
        if validate_first:
            self.validate(executed)
        results: dict[str, Any] = {}
        for index, (display, action) in enumerate(zip(actions, executed, strict=True)):
            key = f"execute[{index}]: {display}"
            results[key] = self._run_one(action, dry_run=dry_run, display=display)
        return results

    def execute_action_parallel(
        self,
        action_list: list | Mapping[str, Any],
        max_workers: int = 4,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Execute actions concurrently with a ``ThreadPoolExecutor``.

        Callers are responsible for ensuring the chosen actions are independent
        (no shared file target, no ordering dependency).
        """
        actions = self._coerce(action_list)
        results: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                (index, action, pool.submit(self._run_one, action, dry_run))
                for index, action in enumerate(actions)
            ]
            for index, action, future in futures:
                results[f"execute[{index}]: {action}"] = future.result()
        return results

    def add_command_to_executor(self, command_dict: Mapping[str, Any]) -> None:
        """Register every ``name -> callable`` pair (Registry facade)."""
        file_automation_logger.info("add_command_to_executor: %s", list(command_dict.keys()))
        super().add_command_to_executor(command_dict)

    # Internals ---------------------------------------------------------
    def _run_one(self, action: list, dry_run: bool, display: list | None = None) -> Any:
        display_action = action if display is None else display
        name = _safe_action_name(action)
        if dry_run:
            return self._run_dry(action, display=display_action)
        started = time.monotonic()
        ok = False
        try:
            value = self._execute_event(action)
            file_automation_logger.info("execute_action: %s", display_action)
            ok = True
            return value
        except ExecuteActionException as error:
            file_automation_logger.error("execute_action malformed: %r", error)
            return repr(error)
        except Exception as error:  # pylint: disable=broad-except
            file_automation_logger.error("execute_action runtime error: %r", error)
            return repr(error)
        finally:
            record_action(name, time.monotonic() - started, ok)

    def _run_dry(self, action: list, display: list | None = None) -> Any:
        display_action = action if display is None else display
        try:
            name, _, _ = self._parse_action(action)
            if self.registry.resolve(name) is None:
                raise ExecuteActionException(f"unknown action: {name!r}")
        except ExecuteActionException as error:
            file_automation_logger.error("execute_action malformed: %r", error)
            return repr(error)
        _, display_kind, display_payload = self._parse_action(display_action)
        file_automation_logger.info(
            "dry_run: %s kind=%s payload=%r",
            name,
            display_kind,
            display_payload,
        )
        return f"dry_run:{name}"

    def _coerce(self, action_list: list | Mapping[str, Any]) -> list:
        actions = self.settings.rules.extract(action_list)
        if actions is None:  # EmptyListPolicy.RAISE: extract raises instead
            raise ExecuteActionException("action_list is empty")
        return actions


def _safe_action_name(action: Any) -> str:
    if isinstance(action, list) and action and isinstance(action[0], str):
        return action[0]
    return "unknown"


# Default shared executor — built once, mutated in place by plugins.
executor: ActionExecutor = ActionExecutor()


def execute_action(
    action_list: list | Mapping[str, Any],
    dry_run: bool = False,
    validate_first: bool = False,
    substitute: bool = False,
) -> dict[str, Any]:
    """Module-level shim that delegates to the shared executor."""
    return executor.execute_action(
        action_list,
        dry_run=dry_run,
        validate_first=validate_first,
        substitute=substitute,
    )


def execute_action_parallel(
    action_list: list | Mapping[str, Any],
    max_workers: int = 4,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Module-level shim that delegates to the shared executor."""
    return executor.execute_action_parallel(action_list, max_workers, dry_run)


def validate_action(action_list: list | Mapping[str, Any]) -> list[str]:
    """Module-level shim that delegates to :meth:`ActionExecutor.validate`."""
    return executor.validate(action_list)


def execute_files(execute_files_list: list[str]) -> list[dict[str, Any]]:
    """Module-level shim that delegates to the shared executor."""
    return executor.execute_files(execute_files_list)


def add_command_to_executor(command_dict: Mapping[str, Any]) -> None:
    """Module-level shim that delegates to the shared executor."""
    executor.add_command_to_executor(command_dict)
