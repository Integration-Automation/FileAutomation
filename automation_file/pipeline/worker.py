"""A task on a thread of its own: the attempts, the retries, their events and the outcome.

The coordinator (:mod:`automation_file.pipeline.runner`) starts one thread per
task and hands it a :class:`Flight`. The thread makes the attempts, publishes
``task.started`` / ``task.completed`` / ``task.failed`` for each of them, records
the outcome and tells the coordinator it has landed.

A flight that passed its deadline is *abandoned*: the coordinator has already
recorded ``timeout``, and whatever the thread still does is ignored. The flight's
lock makes "the task finished" and "the task timed out" exclude each other.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from automation_file.core.progress import CancellationToken, CancelledException
from automation_file.events import (
    Severity,
    TaskCompleted,
    TaskFailed,
    TaskStarted,
    actor_scope,
    correlation_scope,
)
from automation_file.logging_config import file_automation_logger
from automation_file.pipeline.errors import PipelineException
from automation_file.pipeline.model import (
    PipelineRun,
    Task,
    TaskContext,
    TaskRun,
    TaskStatus,
    describe_error,
    utc_now,
)
from automation_file.pipeline.reporting import Outcome, Reporter
from automation_file.pipeline.substitution import render

RETRYING = "retrying"
_NO_OUTCOME = "PipelineException: the task ended without an outcome"


class TaskToken(CancellationToken):
    """A cancellation token a back-off can sleep on."""

    def __init__(self) -> None:
        super().__init__()
        self._woken = threading.Event()

    def cancel(self) -> None:
        super().cancel()
        self._woken.set()

    def wait(self, seconds: float) -> bool:
        """Wait up to ``seconds``; return whether the token was cancelled by then."""
        return self._woken.wait(seconds)


def pause(token: TaskToken, seconds: float) -> bool:
    """Wait out a back-off; return ``True`` when the task was cancelled meanwhile."""
    if seconds <= 0:
        return token.is_cancelled
    return token.wait(seconds)


def elapsed_ms(started: float) -> float:
    """Return the milliseconds since the ``time.monotonic()`` reading ``started``."""
    return round((time.monotonic() - started) * 1000, 3)


@dataclass
class Flight:
    """One task in the air: its definition, its state, its token and its deadline.

    ``deadline`` is a ``time.monotonic()`` reading, set when the first attempt
    starts, so the timeout measures the task and not the wait for its thread.
    """

    task: Task
    state: TaskRun
    token: TaskToken
    results: Mapping[str, Any]
    deadline: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)
    settled: bool = False
    abandoned: bool = False


def make_context(run: PipelineRun, flight: Flight, attempt: int) -> TaskContext:
    """Build what a task callable or a ``when`` callable receives."""
    return TaskContext(
        pipeline=run.pipeline,
        run_id=run.run_id,
        task=flight.task.task_id,
        attempt=attempt,
        params=MappingProxyType(run.params),
        results=flight.results,
        cancel=flight.token,
        dry_run=False,
    )


def call_action(action: list[Any], registry: Any) -> Any:
    """Call the registered command of ``action`` directly, so a failure raises."""
    name = action[0]
    command = registry.resolve(name)
    if command is None:
        raise PipelineException(f"unknown action {name!r}")
    if len(action) == 1:
        return command()
    arguments = action[1]
    if isinstance(arguments, Mapping):
        return command(**arguments)
    return command(*arguments)


class Worker:
    """Runs flights; one instance serves every task thread of a run."""

    def __init__(
        self,
        run: PipelineRun,
        reporter: Reporter,
        registry: Any,
        actor: str,
        landed: Callable[[str], None],
    ) -> None:
        self._run = run
        self._reporter = reporter
        self._registry = registry
        self._actor = actor
        self._landed = landed

    def __call__(self, flight: Flight) -> None:
        """Thread entry point. A new thread has no context: re-enter the run's scopes."""
        with correlation_scope(self._run.run_id), actor_scope(self._actor):
            try:
                self._fly(flight)
            finally:
                self._landed(flight.task.task_id)

    def _fly(self, flight: Flight) -> None:
        try:
            self._attempts(flight)
        except Exception as error:  # pylint: disable=broad-except
            # Boundary of the task thread: the runtime itself failed, for instance a store that
            # raised something other than PipelineException. The task is failed just below.
            file_automation_logger.error(
                "pipeline %s run %s task %s: %r",
                self._run.pipeline,
                self._run.run_id,
                flight.task.task_id,
                error,
            )
        finally:
            # Does nothing when the attempts recorded an outcome, which is the normal case.
            self._settle(flight, TaskStatus.FAILED, error=_NO_OUTCOME)

    def _attempts(self, flight: Flight) -> None:
        for attempt in range(1, flight.task.retry.max_attempts + 1):
            if not self._begin(flight, attempt):
                return
            started = time.monotonic()
            try:
                result = self._invoke(flight, attempt)
            except CancelledException as error:
                self._settle(
                    flight, TaskStatus.CANCELLED, error=describe_error(error), started=started
                )
                return
            except Exception as error:  # pylint: disable=broad-except
                # Boundary: a task's failure is recorded on the run, never raised into the runtime.
                if not self._try_again(flight, attempt, error, started):
                    return
            except SystemExit as error:
                # sys.exit() in a task ends only this thread; what it leaves behind is a failure.
                self._settle(
                    flight, TaskStatus.FAILED, error=describe_error(error), started=started
                )
                return
            else:
                self._settle(flight, TaskStatus.SUCCEEDED, result=result, started=started)
                return

    def _begin(self, flight: Flight, attempt: int) -> bool:
        """Announce an attempt; ``False`` when the task was cancelled or timed out first."""
        if flight.token.is_cancelled:
            self._settle(flight, TaskStatus.CANCELLED, error=flight.state.error, quiet=True)
            return False
        with flight.lock:
            if flight.abandoned:
                return False
            if flight.deadline is None and flight.task.timeout is not None:
                flight.deadline = time.monotonic() + flight.task.timeout
            flight.state.attempts = attempt
            self._reporter.save_task(flight.state)
            self._reporter.task_event(TaskStarted, flight.state, TaskStatus.RUNNING.value)
        return True

    def _invoke(self, flight: Flight, attempt: int) -> Any:
        work = flight.task.work
        if callable(work):
            return work(make_context(self._run, flight, attempt))
        return call_action(render(work, self._run.params, flight.results), self._registry)

    def _try_again(self, flight: Flight, attempt: int, error: Exception, started: float) -> bool:
        """Record a failed attempt; return whether another one follows."""
        policy = flight.task.retry
        text = describe_error(error)
        if attempt >= policy.max_attempts or not policy.retries(error):
            self._settle(flight, TaskStatus.FAILED, error=text, started=started)
            return False
        if flight.token.is_cancelled:
            # It would have been tried again; the cancellation is why it was not.
            self._settle(flight, TaskStatus.CANCELLED, error=text, started=started)
            return False
        with flight.lock:
            if flight.abandoned:
                return False
            flight.state.error = text
            self._reporter.save_task(flight.state)
            self._reporter.task_event(
                TaskFailed,
                flight.state,
                RETRYING,
                Outcome(elapsed_ms(started), text, Severity.WARNING),
            )
        pause(flight.token, policy.delay(attempt))
        return True

    def _settle(
        self,
        flight: Flight,
        status: TaskStatus,
        *,
        result: Any = None,
        error: str | None = None,
        started: float | None = None,
        quiet: bool = False,
    ) -> None:
        """Record the task's outcome once; a flight already settled or abandoned is left alone."""
        with flight.lock:
            if flight.settled or flight.abandoned:
                return
            flight.settled = True
            state = flight.state
            state.status = status
            state.result = result
            state.error = error
            state.finished_at = utc_now()
            self._reporter.save_task(state)
            if quiet:
                return
            duration = None if started is None else elapsed_ms(started)
            if status is TaskStatus.SUCCEEDED:
                self._reporter.task_event(TaskCompleted, state, status.value, Outcome(duration))
                return
            severity = Severity.WARNING if status is TaskStatus.CANCELLED else None
            self._reporter.task_event(
                TaskFailed, state, status.value, Outcome(duration, error, severity)
            )
