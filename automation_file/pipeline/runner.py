"""The run loop: order the tasks, fan them out on threads, watch deadlines and cancellation.

One thread coordinates a run (the caller's for ``Pipeline.run``, a background
one for ``Pipeline.start``). When a task's dependencies have all ended it decides
whether the task runs: its ``when`` condition, then its idempotency key. A task
that runs gets a thread of its own, with at most ``max_workers`` tasks in the air.

Python cannot stop a thread. When a timeout passes, the coordinator records
``timeout``, sets the task's cancellation token and moves on; the thread is left
to finish by itself and what it does afterwards is ignored. Task threads are
daemon threads, so one that never returns does not keep the interpreter alive.
A cancelled run is different: its running tasks are told through their tokens
and the run waits for them, because their outcome still counts.
"""

from __future__ import annotations

import queue
import threading
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from automation_file.events import (
    EventBus,
    PipelineCompleted,
    PipelineFailed,
    PipelineStarted,
    Severity,
    TaskFailed,
    actor_scope,
    correlation_scope,
)
from automation_file.logging_config import file_automation_logger
from automation_file.pipeline.errors import PipelineException
from automation_file.pipeline.model import (
    ALWAYS,
    ON_FAILURE,
    REASON_CONDITION,
    REASON_IDEMPOTENT,
    REASON_UPSTREAM_FAILED,
    REASON_UPSTREAM_SKIPPED,
    Condition,
    PipelineRun,
    RunStatus,
    Task,
    TaskRun,
    TaskStatus,
    describe_error,
    utc_now,
)
from automation_file.pipeline.reporting import Outcome, Reporter
from automation_file.pipeline.store import RunStore
from automation_file.pipeline.substitution import render_key
from automation_file.pipeline.worker import Flight, TaskToken, Worker, elapsed_ms, make_context

_POLL_SECONDS = 0.05
_NO_RESULTS: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True)
class Plan:
    """What one run executes: the tasks in dependency order and how they relate."""

    pipeline: str
    tasks: tuple[Task, ...]
    levels: Mapping[str, int]
    upstream: Mapping[str, tuple[str, ...]]
    max_workers: int


@dataclass(frozen=True)
class Services:
    """What a run works with: where it is recorded, where it reports, what it may call."""

    store: RunStore
    bus: EventBus
    registry: Any
    actor: str


@dataclass(frozen=True)
class _Verdict:
    """Why a task ends without running."""

    status: TaskStatus
    reason: str | None = None
    error: str | None = None


class Engine:
    """Coordinates one run of a :class:`Plan` and leaves the outcome on its ``run``."""

    def __init__(self, plan: Plan, run: PipelineRun, services: Services) -> None:
        self.run = run
        self._plan = plan
        self._services = services
        self._reporter = Reporter(run, services.store, services.bus)
        self._inbox: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._worker = Worker(
            run, self._reporter, services.registry, services.actor, self._inbox.put
        )
        self._tasks = {task.task_id: task for task in plan.tasks}
        self._dependents: dict[str, list[str]] = {task.task_id: [] for task in plan.tasks}
        self._blocked: dict[str, int] = {}
        self._ready: deque[str] = deque()
        self._waiting: deque[str] = deque()
        self._flights: dict[str, Flight] = {}
        self._cancel_seen = False
        self._started = time.monotonic()
        self._prepare()

    def _prepare(self) -> None:
        """Work out which tasks are still to run (a resumed run keeps what succeeded)."""
        states = self.run.tasks
        for task in self._plan.tasks:
            for dependency in task.depends_on:
                self._dependents[dependency].append(task.task_id)
            open_dependencies = [
                dependency
                for dependency in task.depends_on
                if not states[dependency].status.is_final
            ]
            self._blocked[task.task_id] = len(open_dependencies)
            if not open_dependencies and not states[task.task_id].status.is_final:
                self._ready.append(task.task_id)

    # ------------------------------------------------------------------ the run

    def execute(self) -> None:
        """Run to the end in the calling thread, inside the run's correlation scope."""
        with correlation_scope(self.run.run_id), actor_scope(self._services.actor):
            try:
                self._reporter.save_run()
                self._reporter.pipeline_event(PipelineStarted, RunStatus.RUNNING.value)
                self._loop()
                self._conclude()
            except BaseException as error:
                # Ctrl-C included: the run must not stay "running", and nothing may wait for ever.
                self._abort(error)
                raise
            finally:
                self.run.mark_done()

    def _loop(self) -> None:
        while self._ready or self._waiting or self._flights:
            self._observe_cancel()
            self._admit()
            self._launch()
            if self._flights:
                self._await()

    def _observe_cancel(self) -> None:
        if self._cancel_seen or not self.run.cancel_token.is_cancelled:
            return
        self._cancel_seen = True
        self._ready.clear()
        self._waiting.clear()
        for flight in self._flights.values():
            flight.token.cancel()
        for task in self._plan.tasks:
            state = self.run.tasks[task.task_id]
            if state.status is TaskStatus.PENDING:
                self._end_unstarted(state, _Verdict(TaskStatus.CANCELLED))

    def _conclude(self) -> None:
        states = list(self.run.tasks.values())
        broken = [state.task for state in states if state.status.is_failure]
        stopped = any(state.status is TaskStatus.CANCELLED for state in states)
        if self._cancel_seen and stopped:
            self._close(RunStatus.CANCELLED, "the run was cancelled")
        elif broken:
            self._close(RunStatus.FAILED, f"did not succeed: {', '.join(broken)}")
        else:
            self._close(RunStatus.SUCCEEDED, None)

    def _close(self, status: RunStatus, error: str | None) -> None:
        self.run.status = status
        self.run.error = error
        self.run.finished_at = utc_now()
        self._reporter.save_run()
        duration = elapsed_ms(self._started)
        if status is RunStatus.SUCCEEDED:
            self._reporter.pipeline_event(PipelineCompleted, status.value, Outcome(duration))
        else:
            severity = Severity.WARNING if status is RunStatus.CANCELLED else None
            self._reporter.pipeline_event(
                PipelineFailed, status.value, Outcome(duration, error, severity)
            )
        file_automation_logger.info(
            "pipeline %s run %s: %s", self.run.pipeline, self.run.run_id, status.value
        )

    def _abort(self, error: BaseException) -> None:
        """Leave a consistent record when the coordinator itself is interrupted."""
        file_automation_logger.error(
            "pipeline %s run %s aborted: %r", self.run.pipeline, self.run.run_id, error
        )
        for flight in self._flights.values():
            with flight.lock:
                flight.abandoned = not flight.settled
            flight.token.cancel()
        for state in self.run.tasks.values():
            if not state.status.is_final:
                state.status = TaskStatus.CANCELLED
                state.finished_at = utc_now()
        self._close(RunStatus.FAILED, describe_error(error))

    # ------------------------------------------------------------------ admission

    def _admit(self) -> None:
        """Decide for every ready task whether it runs; ending one may make others ready."""
        while self._ready:
            task = self._tasks[self._ready.popleft()]
            state = self.run.tasks[task.task_id]
            verdict = self._gate(task, state)
            if verdict is None:
                self._waiting.append(task.task_id)
            else:
                self._end_unstarted(state, verdict)
                self._release(task.task_id)

    def _gate(self, task: Task, state: TaskRun) -> _Verdict | None:
        verdict = self._condition(task)
        if verdict is not None or task.idempotency_key is None:
            return verdict
        return self._seen_before(task, state)

    def _condition(self, task: Task) -> _Verdict | None:
        when = task.when
        if callable(when):
            return self._ask(task, when)
        if when == ALWAYS:
            return None
        dependencies = [self.run.tasks[dependency] for dependency in task.depends_on]
        failed = any(dependency.status.is_failure for dependency in dependencies)
        if when == ON_FAILURE:
            return None if failed else _Verdict(TaskStatus.SKIPPED, REASON_CONDITION)
        if all(dependency.satisfied for dependency in dependencies):
            return None
        reason = REASON_UPSTREAM_FAILED if failed else REASON_UPSTREAM_SKIPPED
        return _Verdict(TaskStatus.SKIPPED, reason)

    def _ask(self, task: Task, when: Condition) -> _Verdict | None:
        probe = Flight(task, self.run.tasks[task.task_id], TaskToken(), self._results_for(task))
        try:
            wanted = when(make_context(self.run, probe, 0))
        except Exception as error:  # pylint: disable=broad-except
            # Boundary: a broken condition fails its task, not the run loop.
            return _Verdict(TaskStatus.FAILED, error=f"when: {describe_error(error)}")
        return None if wanted else _Verdict(TaskStatus.SKIPPED, REASON_CONDITION)

    def _seen_before(self, task: Task, state: TaskRun) -> _Verdict | None:
        """Skip a task whose idempotency key already has a succeeded execution."""
        try:
            key = render_key(str(task.idempotency_key), self.run.params)
            earlier = self._services.store.find_idempotent(self._plan.pipeline, task.task_id, key)
        except PipelineException as error:
            # Running it anyway could repeat the very thing the key protects.
            return _Verdict(TaskStatus.FAILED, error=describe_error(error))
        state.idempotency_key = key
        if earlier is None:
            return None
        state.result = earlier.result
        state.result_is_repr = earlier.result_is_repr
        return _Verdict(TaskStatus.SKIPPED, REASON_IDEMPOTENT)

    def _end_unstarted(self, state: TaskRun, verdict: _Verdict) -> None:
        state.status = verdict.status
        state.reason = verdict.reason
        state.error = verdict.error
        state.finished_at = utc_now()
        self._reporter.save_task(state)
        if verdict.status is TaskStatus.FAILED:
            self._reporter.task_event(
                TaskFailed, state, verdict.status.value, Outcome(error=verdict.error)
            )

    def _release(self, task_id: str) -> None:
        """A task has ended: its dependents wait for one dependency less."""
        for dependent in self._dependents[task_id]:
            self._blocked[dependent] -= 1
            if (
                self._blocked[dependent] == 0
                and self.run.tasks[dependent].status is TaskStatus.PENDING
            ):
                self._ready.append(dependent)

    # ------------------------------------------------------------------ flights

    def _results_for(self, task: Task) -> Mapping[str, Any]:
        states = self.run.tasks
        upstream = self._plan.upstream[task.task_id]
        if not upstream:
            return _NO_RESULTS
        return MappingProxyType(
            {other: states[other].result for other in upstream if states[other].satisfied}
        )

    def _launch(self) -> None:
        while self._waiting and len(self._flights) < self._plan.max_workers:
            task = self._tasks[self._waiting.popleft()]
            state = self.run.tasks[task.task_id]
            state.status = TaskStatus.RUNNING
            state.started_at = utc_now()
            flight = Flight(task, state, TaskToken(), self._results_for(task))
            self._flights[task.task_id] = flight
            threading.Thread(
                target=self._worker,
                args=(flight,),
                name=f"pipeline-{self._plan.pipeline}-{task.task_id}",
                daemon=True,
            ).start()

    def _patience(self) -> float:
        """Seconds to wait for a landing before looking at deadlines and cancellation again."""
        deadlines = [
            flight.deadline for flight in self._flights.values() if flight.deadline is not None
        ]
        if not deadlines:
            return _POLL_SECONDS
        return max(0.0, min(_POLL_SECONDS, min(deadlines) - time.monotonic()))

    def _await(self) -> None:
        try:
            landed: str | None = self._inbox.get(timeout=self._patience())
        except queue.Empty:
            landed = None
        if landed is not None and self._flights.pop(landed, None) is not None:
            self._release(landed)
        self._expire()

    def _expire(self) -> None:
        now = time.monotonic()
        for task_id, flight in list(self._flights.items()):
            if flight.deadline is None or now < flight.deadline:
                continue
            with flight.lock:
                if flight.settled:
                    continue  # it finished in time; its landing is on the way
                flight.abandoned = True
            flight.token.cancel()
            del self._flights[task_id]
            self._time_out(flight)
            self._release(task_id)

    def _time_out(self, flight: Flight) -> None:
        state = flight.state
        state.status = TaskStatus.TIMEOUT
        state.error = f"TimeoutError: no result within {flight.task.timeout:g} s"
        state.finished_at = utc_now()
        self._reporter.save_task(state)
        self._reporter.task_event(TaskFailed, state, state.status.value, Outcome(error=state.error))
