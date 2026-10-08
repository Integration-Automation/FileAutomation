"""Running jobs: admit a firing or skip it, follow the run to its end, record every step.

A firing that is admitted gets a thread of its own. The record moves from
``scheduled`` to ``started`` and then to ``completed`` or ``failed``; a firing
that meets a run still in progress is recorded as ``skipped`` instead.

Python cannot stop a thread. When a run's timeout passes or it is cancelled, the
record is closed at that moment (``timeout`` / ``cancelled``) and the run's
cancellation token is set: a pipeline stops through it, and an action list stops
before its next action. The job keeps counting as running until the thread has
really ended, so overlap protection holds in between.

A run that fails or times out is published as a ``scheduler.error`` event.

Runs may fire one another through events. Every run knows how many runs led to
it, and a firing at the end of a chain of :data:`MAX_CHAIN` runs is recorded as
``skipped``, so two jobs that fire each other cannot go on for ever.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from automation_file.core.progress import CancellationToken
from automation_file.events import (
    Event,
    EventBus,
    SchedulerError,
    actor_scope,
    correlation_scope,
    new_correlation_id,
)
from automation_file.logging_config import file_automation_logger
from automation_file.scheduler.job import ScheduledJob
from automation_file.scheduler.runs import (
    REASON_CANCELLED,
    REASON_CHAIN,
    REASON_OVERLAP,
    JobRun,
    RunHistory,
    RunState,
    TriggerKind,
    as_utc,
)
from automation_file.scheduler.targets import Outcome, describe, fill_params, run_pipeline

ACTOR = "scheduler"
SOURCE = "scheduler"
#: How many runs may fire one another, each through an event of the one before.
MAX_CHAIN = 16
_SUBJECTS = {RunState.FAILED: "failed", RunState.TIMEOUT: "timed out"}

Clock = Callable[[], datetime]
ActionRunner = Callable[[str, list[list[Any]], CancellationToken], Outcome]


@dataclass(frozen=True)
class Firing:
    """Why a job is fired: what fired it, the time it was due, and the details for the record.

    ``scheduled`` is the time the run was due (the minute, for cron); ``now`` is
    when the firing was decided, which is where a timeout starts counting.
    ``depth`` counts the runs that led to this firing through events: ``0`` for a
    firing no run caused.
    """

    kind: TriggerKind
    scheduled: datetime
    now: datetime | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)
    depth: int = 0


@dataclass
class Flight:
    """A run in the air: its job, its record, how to stop it, and when its time is up."""

    job: ScheduledJob
    record: JobRun
    cancel: CancellationToken = field(default_factory=CancellationToken)
    deadline: datetime | None = None
    depth: int = 0


@dataclass(frozen=True)
class Services:
    """What the dispatcher works with.

    ``lock`` is the scheduler's own lock: the job counters, the flights and the
    records change under it together.
    """

    lock: AbstractContextManager[Any]
    bus: EventBus
    clock: Clock
    history: RunHistory
    run_actions: ActionRunner


class Dispatcher:
    """Starts runs, ends them, and keeps the overlap accounting of every job."""

    def __init__(self, services: Services) -> None:
        self._lock = services.lock
        self._bus = services.bus
        self._clock = services.clock
        self._history = services.history
        self._run_actions = services.run_actions
        self._flights: dict[str, Flight] = {}
        self._local = threading.local()

    def _now(self) -> datetime:
        return as_utc(self._clock())

    # ------------------------------------------------------------------ starting

    def dispatch(self, job: ScheduledJob, moment: datetime, firing: Firing) -> JobRun:
        """Fire ``job``: start a run on a thread of its own, or record the firing as skipped.

        ``moment`` is the firing time as the job reads its clock; it becomes the
        job's ``last_run``.
        """
        record = JobRun(
            run_id=new_correlation_id(),
            job=job.name,
            trigger=firing.kind,
            scheduled_at=as_utc(firing.scheduled),
            target=job.target,
            pipeline=None if job.pipeline is None else job.pipeline.name,
            detail=dict(firing.detail),
        )
        flight = self._admit(job, record, moment, firing)
        if flight is None:
            return record
        file_automation_logger.info(
            "scheduler[%s]: firing at %s (run %s, trigger=%s)",
            job.name,
            moment.isoformat(),
            record.run_id,
            firing.kind.value,
        )
        worker = threading.Thread(
            target=self._fly, args=(flight,), name=f"fa-scheduler-{job.name}", daemon=True
        )
        try:
            worker.start()
        except RuntimeError as error:
            # No thread could be started: the run ends here, and the job is released.
            self._land(flight, Outcome(RunState.FAILED, describe(error)))
        return record

    def _admit(
        self, job: ScheduledJob, record: JobRun, moment: datetime, firing: Firing
    ) -> Flight | None:
        """Count the firing as a run, or as skipped when it overlaps or ends a long chain."""
        flight: Flight | None = None
        deadline = self._deadline(job, firing)
        with self._lock:
            self._history.add(record)
            reason = self._refusal(job, firing)
            if reason is None:
                flight = Flight(job, record, deadline=deadline, depth=firing.depth)
                self._flights[record.run_id] = flight
                job.running = True
                job.active += 1
                job.last_run = moment
                job.runs += 1
            else:
                job.skipped += 1
                record.close(RunState.SKIPPED, record.scheduled_at, reason=reason)
            skipped = job.skipped
        if reason == REASON_OVERLAP:
            file_automation_logger.warning(
                "scheduler[%s]: previous run still active — skipping (skipped=%d)",
                job.name,
                skipped,
            )
        elif reason is not None:
            file_automation_logger.warning(
                "scheduler[%s]: %d runs have fired one another — skipping (skipped=%d)",
                job.name,
                firing.depth,
                skipped,
            )
        if flight is None:
            record.settle()
        return flight

    @staticmethod
    def _refusal(job: ScheduledJob, firing: Firing) -> str | None:
        """Return why the firing starts no run, ``None`` when it does."""
        if firing.depth >= MAX_CHAIN:
            return REASON_CHAIN
        if job.running and not job.allow_overlap:
            return REASON_OVERLAP
        return None

    @staticmethod
    def _deadline(job: ScheduledJob, firing: Firing) -> datetime | None:
        if job.timeout is None:
            return None
        return as_utc(firing.now or firing.scheduled) + timedelta(seconds=job.timeout)

    # ------------------------------------------------------------------ the run

    def _fly(self, flight: Flight) -> None:
        """The run's thread: whatever ends it, the record is closed and the job released."""
        self._local.flight = flight
        outcome = Outcome(RunState.FAILED, "the run's thread ended without a result")
        try:
            outcome = self._attempt(flight)
        finally:
            self._land(flight, outcome)

    def _take_off(self, flight: Flight) -> bool:
        """Mark the run started; ``False`` when it was already cancelled or out of time."""
        with self._lock:
            if flight.record.state.is_final:
                return False
            flight.record.started_at = self._now()
            flight.record.state = RunState.STARTED
        return True

    def _attempt(self, flight: Flight) -> Outcome:
        job, record = flight.job, flight.record
        if not self._take_off(flight):
            return Outcome(record.state)
        try:
            with actor_scope(ACTOR), correlation_scope(record.run_id):
                if job.pipeline is None:
                    return self._run_actions(job.name, job.action_list, flight.cancel)
                params = fill_params(job.params, job.local(record.scheduled_at))
                return run_pipeline(job.pipeline, params, record, flight.cancel, self._bus)
        except Exception as error:  # pylint: disable=broad-except
            # Boundary of the run's thread: whatever the target raised, the run
            # is recorded and the job is released.
            problem = describe(error)
            file_automation_logger.error(
                "scheduler[%s]: run %s raised %s", job.name, record.run_id, problem
            )
            return Outcome(RunState.FAILED, problem)

    def _land(self, flight: Flight, outcome: Outcome) -> None:
        """The run's thread has ended: close the record, report, release the job.

        The job is released before the failure is published, so a subscriber
        may fire it again at once; the job is released whatever closing does.
        """
        decided = True
        try:
            decided = self._conclude(flight, outcome)
        finally:
            self._release(flight)
        try:
            self._tell(flight, outcome, decided)
        finally:
            flight.record.settle()

    def _release(self, flight: Flight) -> None:
        with self._lock:
            self._flights.pop(flight.record.run_id, None)
            flight.job.active = max(flight.job.active - 1, 0)
            flight.job.running = flight.job.active > 0

    def _conclude(self, flight: Flight, outcome: Outcome) -> bool:
        """Close the record unless a timeout or a cancellation did; return whether one had."""
        with self._lock:
            decided = flight.record.state.is_final
            if not decided:
                flight.record.close(outcome.state, self._now(), outcome.error)
                flight.job.last_state = outcome.state.value
        return decided

    def _tell(self, flight: Flight, outcome: Outcome, decided: bool) -> None:
        job, record = flight.job, flight.record
        if decided:
            file_automation_logger.info(
                "scheduler[%s]: run %s ended after it was recorded as %s",
                job.name,
                record.run_id,
                record.state.value,
            )
        else:
            self._announce(record, outcome.reported)

    # ------------------------------------------------------------------ reporting

    def _announce(self, record: JobRun, reported: bool = False) -> None:
        """Log how the run ended and publish ``scheduler.error`` for a failure or a timeout."""
        if record.state is RunState.COMPLETED:
            file_automation_logger.info(
                "scheduler[%s]: run %s completed", record.job, record.run_id
            )
            return
        file_automation_logger.warning(
            "scheduler[%s]: run %s %s: %s",
            record.job,
            record.run_id,
            record.state.value,
            record.error or record.reason,
        )
        subject = _SUBJECTS.get(record.state)
        if subject is None or reported:
            return
        payload: dict[str, Any] = {
            "job": record.job,
            "trigger": record.trigger.value,
            "status": record.state.value,
            "error": record.error,
            "target": record.target,
            "scheduler_run_id": record.run_id,
        }
        if record.duration_ms is not None:
            payload["duration_ms"] = record.duration_ms
        if record.pipeline is not None:
            payload["pipeline"] = record.pipeline
        if record.correlation_id != record.run_id:
            payload["run_id"] = record.correlation_id  # the pipeline's run, once it had started
        with actor_scope(ACTOR), correlation_scope(record.correlation_id):
            self._bus.publish(
                SchedulerError(
                    source=SOURCE, subject=f"scheduler[{record.job}] {subject}", payload=payload
                )
            )

    # ------------------------------------------------------------------ stopping

    def expire(self, instant: datetime) -> list[JobRun]:
        """Close every run whose timeout has passed at ``instant`` and return those records."""
        with self._lock:
            late = [
                flight
                for flight in self._flights.values()
                if flight.deadline is not None
                and instant >= flight.deadline
                and not flight.record.state.is_final
            ]
            for flight in late:
                flight.record.close(
                    RunState.TIMEOUT,
                    instant,
                    f"TimeoutError: not finished within {flight.job.timeout:g} s",
                )
                flight.job.last_state = RunState.TIMEOUT.value
        for flight in late:
            flight.cancel.cancel()
        for flight in late:
            # The report belongs to this run: a run it fires is the next link of its chain.
            self._local.flight = flight
            try:
                self._announce(flight.record)
            finally:
                self._local.flight = None
                flight.record.settle()
        return [flight.record for flight in late]

    def cancel(self, name: str | None = None) -> list[JobRun]:
        """Cancel the runs in progress of the job ``name`` (of every job when ``None``)."""
        with self._lock:
            chosen = [
                flight
                for flight in self._flights.values()
                if (name is None or flight.job.name == name) and not flight.record.state.is_final
            ]
            moment = self._now()
            for flight in chosen:
                flight.record.close(RunState.CANCELLED, moment, reason=REASON_CANCELLED)
                flight.job.last_state = RunState.CANCELLED.value
        for flight in chosen:
            flight.cancel.cancel()
            self._announce(flight.record)
            flight.record.settle()
        return [flight.record for flight in chosen]

    def is_own(self, name: str, event: Event) -> bool:
        """Return whether ``event`` was published by a run of the job ``name`` itself.

        That is an event published on the thread of one of its runs, one that
        carries the correlation ID of a run in progress, or a
        ``scheduler.error`` about the job.
        """
        if isinstance(event, SchedulerError) and event.payload.get("job") == name:
            return True
        return any(flight.job.name == name for flight in self._publishers(event))

    def depth_after(self, event: Event) -> int:
        """Return the chain depth of a run that ``event`` fires.

        That is one more than the depth of the run that published ``event``, and
        ``0`` when no run in progress did.
        """
        return max((flight.depth + 1 for flight in self._publishers(event)), default=0)

    def _publishers(self, event: Event) -> list[Flight]:
        """Return the runs in progress that published ``event``.

        A run published it when it is published on the run's own thread, or
        carries the run's correlation ID (the events of a pipeline's tasks, and
        a timeout reported by the scheduler's thread).
        """
        current: Flight | None = getattr(self._local, "flight", None)
        with self._lock:
            found = [
                flight
                for flight in self._flights.values()
                if event.correlation_id in (flight.record.run_id, flight.record.correlation_id)
            ]
        if current is not None and all(flight is not current for flight in found):
            found.append(current)
        return found
