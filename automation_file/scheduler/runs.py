"""What the scheduler records about one firing of a job.

Every firing leaves a :class:`JobRun`, whatever fired it and whether or not the
job ran: a firing that meets a run still in progress is recorded as ``skipped``.
A :class:`RunHistory` keeps the latest records of one scheduler in memory.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from automation_file.scheduler.errors import SchedulerException

DEFAULT_HISTORY = 1000
DEFAULT_QUERY_LIMIT = 50

#: ``JobRun.target`` values.
TARGET_ACTIONS = "actions"
TARGET_PIPELINE = "pipeline"

#: ``JobRun.reason``: skipped because the job was still running / skipped because
#: too many runs had fired one another / stopped by ``cancel``.
REASON_OVERLAP = "overlap"
REASON_CHAIN = "chain"
REASON_CANCELLED = "cancelled"


class RunState(str, Enum):
    """Where one firing of a job stands."""

    SCHEDULED = "scheduled"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"

    @property
    def is_final(self) -> bool:
        """Whether the record will not change state any more."""
        return self not in (RunState.SCHEDULED, RunState.STARTED)


class TriggerKind(str, Enum):
    """What fired a run."""

    CRON = "cron"
    MANUAL = "manual"
    FILE = "file"
    EVENT = "event"
    PIPELINE = "pipeline"


def as_utc(moment: datetime) -> datetime:
    """Return ``moment`` as an aware UTC ``datetime``; a naive one is taken as local time."""
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat(timespec="microseconds")


@dataclass
class JobRun:
    """One firing of a job: what fired it, how far it got, and how it ended.

    The times are timezone-aware UTC. ``correlation_id`` is the ID carried by
    every event the run publishes: the run's own ID for an action list, and the
    pipeline's run ID once a pipeline target has started (the ID
    ``FA_pipeline_status`` takes). ``detail`` says what fired the run: the cron
    expression, the file, the event, the pipeline. ``pipeline`` names the
    pipeline of a pipeline target. ``reason`` says why a firing was skipped
    (``overlap``, ``chain``) or that a run was ``cancelled``; ``error`` says
    what went wrong in a ``failed`` or ``timeout`` run.
    """

    run_id: str
    job: str
    trigger: TriggerKind
    scheduled_at: datetime
    target: str = TARGET_ACTIONS
    pipeline: str | None = None
    state: RunState = RunState.SCHEDULED
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    reason: str | None = None
    correlation_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    _settled: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.correlation_id:
            self.correlation_id = self.run_id

    @property
    def done(self) -> bool:
        """Whether the run has reached a final state."""
        return self.state.is_final

    @property
    def duration_ms(self) -> float | None:
        """Return the milliseconds between start and end, ``None`` while either is missing."""
        if self.started_at is None or self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at).total_seconds() * 1000, 3)

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the scheduler is done with the run or ``timeout`` seconds passed.

        Returns whether the run has a final state. A run that ended by itself is
        released once its job counts as not running any more; a run that timed
        out or was cancelled is released at that moment, although its thread may
        still be busy.
        """
        self._settled.wait(timeout)
        return self.done

    def close(
        self,
        state: RunState,
        moment: datetime,
        error: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Give the run its final state. The scheduler calls this; nothing else should."""
        self.finished_at = moment
        self.error = error
        self.reason = reason
        self.state = state

    def settle(self) -> None:
        """Release everything blocked in :meth:`wait`. The scheduler calls this."""
        self._settled.set()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the record."""
        return {
            "run_id": self.run_id,
            "job": self.job,
            "trigger": self.trigger.value,
            "target": self.target,
            "pipeline": self.pipeline,
            "state": self.state.value,
            "scheduled_at": _iso(self.scheduled_at),
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "duration_ms": self.duration_ms,
            "error": self.error,
            "reason": self.reason,
            "correlation_id": self.correlation_id,
            "detail": dict(self.detail),
        }


def as_run_state(state: RunState | str) -> RunState:
    """Return ``state`` as a :class:`RunState`; an unknown word raises ``SchedulerException``."""
    try:
        return RunState(state)
    except ValueError as error:
        known = ", ".join(item.value for item in RunState)
        raise SchedulerException(f"unknown run state {state!r} (one of: {known})") from error


class RunHistory:
    """The latest runs of one scheduler, oldest dropped first. Thread-safe."""

    def __init__(self, limit: int = DEFAULT_HISTORY) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise SchedulerException(f"history limit: expected an integer >= 1, got {limit!r}")
        self._lock = threading.Lock()
        self._runs: deque[JobRun] = deque(maxlen=limit)

    def __len__(self) -> int:
        with self._lock:
            return len(self._runs)

    def add(self, run: JobRun) -> None:
        """Remember ``run``; the oldest record goes when the history is full."""
        with self._lock:
            self._runs.append(run)

    def query(
        self,
        job: str | None = None,
        state: RunState | str | None = None,
        limit: int = DEFAULT_QUERY_LIMIT,
    ) -> list[JobRun]:
        """Return up to ``limit`` records, newest first, of one job and/or in one state."""
        wanted = None if state is None else as_run_state(state)
        with self._lock:
            runs = list(self._runs)
        chosen = [
            run
            for run in reversed(runs)
            if (job is None or run.job == job) and (wanted is None or run.state is wanted)
        ]
        return chosen[: max(limit, 0)]

    def clear(self) -> None:
        """Forget every record."""
        with self._lock:
            self._runs.clear()
