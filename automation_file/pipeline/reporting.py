"""How a run tells the world what happened: events on the bus, checkpoints in the store.

The pipeline calls no notification sink and writes no audit row. It publishes
``pipeline.*`` and ``task.*`` events with ``source="pipeline"``; whoever needs
them subscribes to the bus. A failing store is logged and the run goes on: the
work matters more than its record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from automation_file.events import Event, EventBus, Severity
from automation_file.logging_config import file_automation_logger
from automation_file.pipeline.errors import PipelineException
from automation_file.pipeline.model import PipelineRun, TaskRun
from automation_file.pipeline.store import RunStore

SOURCE = "pipeline"


@dataclass(frozen=True)
class Outcome:
    """The optional details of an event: how long it took, what went wrong, how bad it is."""

    duration_ms: float | None = None
    error: str | None = None
    severity: Severity | None = None


_PLAIN = Outcome()


class Reporter:
    """Publishes the events of one run and writes its checkpoints."""

    def __init__(self, run: PipelineRun, store: RunStore, bus: EventBus) -> None:
        self._run = run
        self._store = store
        self._bus = bus

    def save_run(self) -> None:
        """Checkpoint the run and all of its tasks."""
        try:
            self._store.save_run(self._run)
        except PipelineException as error:
            self._lost("the run", error)

    def save_task(self, state: TaskRun) -> None:
        """Checkpoint one task transition."""
        try:
            self._store.save_task(self._run.run_id, state)
        except PipelineException as error:
            self._lost(f"task {state.task!r}", error)

    def _lost(self, what: str, error: PipelineException) -> None:
        file_automation_logger.error(
            "pipeline %s run %s: cannot record %s: %r",
            self._run.pipeline,
            self._run.run_id,
            what,
            error,
        )

    def pipeline_event(self, kind: type[Event], status: str, outcome: Outcome = _PLAIN) -> None:
        """Publish a ``pipeline.*`` event for the run."""
        payload: dict[str, Any] = {
            "pipeline": self._run.pipeline,
            "run_id": self._run.run_id,
            "status": status,
        }
        self._publish(kind, f"{self._run.pipeline} {status}", payload, outcome)

    def task_event(
        self, kind: type[Event], state: TaskRun, status: str, outcome: Outcome = _PLAIN
    ) -> None:
        """Publish a ``task.*`` event for the current attempt of ``state``."""
        payload: dict[str, Any] = {
            "pipeline": self._run.pipeline,
            "run_id": self._run.run_id,
            "task": state.task,
            "attempt": state.attempts,
            "status": status,
        }
        subject = f"{self._run.pipeline}/{state.task} {status} (attempt {state.attempts})"
        self._publish(kind, subject, payload, outcome)

    def _publish(
        self, kind: type[Event], subject: str, payload: dict[str, Any], outcome: Outcome
    ) -> None:
        if outcome.duration_ms is not None:
            payload["duration_ms"] = outcome.duration_ms
        if outcome.error is not None:
            payload["error"] = outcome.error
        if outcome.severity is None:
            event = kind(source=SOURCE, subject=subject, payload=payload)
        else:
            event = kind(source=SOURCE, subject=subject, payload=payload, severity=outcome.severity)
        self._bus.publish(event)
