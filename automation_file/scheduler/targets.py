"""What a job runs: an action list or a pipeline.

An action list goes through the shared executor one action at a time, so the
scheduler learns which action raised and can stop before the next one when the
run is cancelled or out of time. A pipeline runs in the calling thread with a
cancellation token the scheduler keeps.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from automation_file.core.progress import CancellationToken
from automation_file.events import Event, EventBus, PipelineStarted
from automation_file.exceptions import ExecuteActionException, FileAutomationException
from automation_file.logging_config import file_automation_logger
from automation_file.scheduler.errors import SchedulerException
from automation_file.scheduler.runs import JobRun, RunState

if TYPE_CHECKING:
    from automation_file.pipeline import Pipeline

_DATE = re.compile(r"\$\{date(?::([^}]*))?\}", re.IGNORECASE)
_DEFAULT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
_UNKNOWN_ACTION = "unknown"


@dataclass(frozen=True)
class Outcome:
    """How a target ended.

    ``reported`` is set when the failure has already been published (by
    ``notify_on_failure``), so the scheduler does not publish it a second time.
    """

    state: RunState
    error: str | None = None
    reported: bool = False


def describe(error: BaseException) -> str:
    """Return ``"<ExceptionType>: <message>"`` with every URL cut down to its host."""
    from automation_file.notify.manager import describe_error

    return describe_error(error)


def _action_name(action: Any) -> str:
    if isinstance(action, list) and action and isinstance(action[0], str):
        return action[0]
    return _UNKNOWN_ACTION


def _run_action(action: Any) -> str | None:
    """Run one action through the executor; return ``"<name>: <error>"`` if it raised."""
    from automation_file.core.action_executor import executor
    from automation_file.core.metrics import record_action

    name = _action_name(action)
    started = time.monotonic()
    try:
        # pylint: disable-next=protected-access  # the executor's single-action Template Method
        executor._execute_event(action)
    except Exception as error:  # pylint: disable=broad-except
        # Boundary: one failing action must not stop the list; it is recorded and reported.
        record_action(name, time.monotonic() - started, False)
        problem = describe(error)
        file_automation_logger.error("scheduler: action %s failed: %s", name, problem)
        return f"{name}: {problem}"
    record_action(name, time.monotonic() - started, True)
    file_automation_logger.info("scheduler: action %s done", name)
    return None


def run_actions(action_list: Any, cancel: CancellationToken) -> list[str]:
    """Run the actions of ``action_list`` in order; return one line per action that raised.

    A failing action does not stop the list, as in ``execute_action``. A
    cancelled ``cancel`` stops it before the next action: the action in progress
    cannot be interrupted. A list the executor does not accept (empty, not a
    list) raises :class:`~automation_file.exceptions.ExecuteActionException`
    before anything runs.
    """
    from automation_file.core.action_executor import executor

    actions = executor.settings.rules.extract(action_list)
    if actions is None:
        raise ExecuteActionException("action_list is empty")
    failures: list[str] = []
    for index, action in enumerate(actions):
        if cancel.is_cancelled:
            file_automation_logger.info(
                "scheduler: action list stopped before action %d of %d", index + 1, len(actions)
            )
            break
        problem = _run_action(action)
        if problem is not None:
            failures.append(f"execute[{index}] {problem}")
    return failures


def load_pipeline(source: Any) -> Pipeline:
    """Return the pipeline ``source`` stands for, checked.

    ``source`` is a :class:`~automation_file.pipeline.Pipeline`, a definition
    mapping, or the path of a ``.yaml`` / ``.yml`` / ``.json`` definition file.
    A definition that is wrong raises ``PipelineDefinitionException`` here, when
    the job is registered, not at its first firing.
    """
    from automation_file.pipeline import Pipeline

    if isinstance(source, Pipeline):
        pipeline = source
    elif isinstance(source, Mapping):
        pipeline = Pipeline.from_dict(source)
    elif isinstance(source, (str, os.PathLike)):
        pipeline = Pipeline.from_file(source)
    else:
        raise SchedulerException(
            "pipeline: expected a Pipeline, a definition mapping or a file path, "
            f"got {type(source).__name__}"
        )
    pipeline.validate()
    return pipeline


def run_pipeline(
    pipeline: Pipeline,
    params: Mapping[str, Any],
    record: JobRun,
    cancel: CancellationToken,
    bus: EventBus,
) -> Outcome:
    """Run ``pipeline`` in the calling thread and say how it ended.

    The pipeline's events carry its own run ID as their correlation ID, so
    ``record.correlation_id`` is moved to that ID as soon as the run starts.
    """
    from automation_file.pipeline import RunStatus

    worker = threading.get_ident()

    def adopt(event: Event) -> None:
        if threading.get_ident() == worker:
            record.correlation_id = str(event.payload.get("run_id") or record.correlation_id)

    subscription = bus.subscribe(adopt, types=PipelineStarted)
    try:
        run = pipeline.run(params=params, cancel=cancel, bus=bus)
    except FileAutomationException as error:
        return Outcome(RunState.FAILED, describe(error))
    finally:
        bus.unsubscribe(subscription)
    record.correlation_id = run.run_id
    if run.status is RunStatus.SUCCEEDED:
        return Outcome(RunState.COMPLETED)
    if run.status is RunStatus.CANCELLED:
        return Outcome(RunState.CANCELLED, run.error)
    return Outcome(RunState.FAILED, run.error or f"pipeline {pipeline.name} did not succeed")


def _fill(value: Any, moment: datetime) -> Any:
    if isinstance(value, str):
        return _DATE.sub(
            lambda match: moment.strftime(match.group(1) or _DEFAULT_DATE_FORMAT), value
        )
    if isinstance(value, Mapping):
        return {key: _fill(item, moment) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_fill(item, moment) for item in value]
    return value


def fill_params(params: Mapping[str, Any], moment: datetime) -> dict[str, Any]:
    """Return ``params`` with ``${date}`` and ``${date:FORMAT}`` replaced by ``moment``.

    ``FORMAT`` is a ``strftime`` format; a bare ``${date}`` gives
    ``2026-10-08T02:00:00``. Strings are looked at at every depth; anything else
    is passed on unchanged.
    """
    return {name: _fill(value, moment) for name, value in params.items()}
