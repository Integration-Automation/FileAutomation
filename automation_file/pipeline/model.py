"""The pipeline's data model: tasks, retry policies, and the recorded state of a run.

A :class:`Task` is what a pipeline was told to do; a :class:`TaskRun` is what
happened to it in one :class:`PipelineRun`. Both run records turn into
JSON-friendly mappings (``to_dict``) and back (``from_dict``), which is the form
a :class:`~automation_file.pipeline.store.RunStore` keeps.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from automation_file.core.progress import CancellationToken
from automation_file.exceptions import StorageTransientException
from automation_file.pipeline.errors import PipelineDefinitionException

#: ``when`` values: run when every dependency succeeded / when one failed / in any case.
ON_SUCCESS = "on_success"
ON_FAILURE = "on_failure"
ALWAYS = "always"
WHEN_CHOICES: tuple[str, ...] = (ON_SUCCESS, ON_FAILURE, ALWAYS)

#: ``TaskRun.reason`` values of a skipped task.
REASON_IDEMPOTENT = "idempotent"
REASON_CONDITION = "condition"
REASON_UPSTREAM_FAILED = "upstream_failed"
REASON_UPSTREAM_SKIPPED = "upstream_skipped"

#: Failures worth a second attempt; anything else is a bug or a wrong input.
DEFAULT_RETRY_ON: tuple[type[BaseException], ...] = (
    StorageTransientException,
    ConnectionError,
    TimeoutError,
)
_MAX_BACKOFF_EXPONENT = 62


class TaskStatus(str, Enum):
    """Where a task stands in one run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    PLANNED = "planned"

    @property
    def is_final(self) -> bool:
        """Whether the task will not change any more in this run."""
        return self not in (TaskStatus.PENDING, TaskStatus.RUNNING)

    @property
    def is_failure(self) -> bool:
        """Whether the task failed, timed out or was cancelled."""
        return self in (TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED)


class RunStatus(str, Enum):
    """Where a whole run stands."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``."""
    return datetime.now(timezone.utc)


def _iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.isoformat(timespec="microseconds")


def _moment(text: str | None) -> datetime | None:
    return None if text is None else datetime.fromisoformat(text)


def json_safe(value: Any) -> tuple[Any, bool]:
    """Return ``value`` as plain JSON data, or ``(repr(value), True)`` when JSON cannot hold it."""
    try:
        return json.loads(json.dumps(value)), False
    except (TypeError, ValueError, RecursionError):
        return repr(value), True


def describe_error(error: BaseException) -> str:
    """Return ``"<ExceptionType>: <message>"``, the form the events and the store keep."""
    message = str(error)
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


@dataclass(frozen=True)
class RetryPolicy:
    """How often a task is tried again, how long to wait, and after which errors.

    The wait after attempt ``n`` is ``backoff_base * 2 ** (n - 1)`` seconds, at most
    ``backoff_cap``. Only an error that is an instance of one of ``retry_on`` is
    retried; the default is the transient kind, so a bug fails on its first attempt.
    """

    max_attempts: int = 1
    backoff_base: float = 0.0
    backoff_cap: float = 60.0
    retry_on: tuple[type[BaseException], ...] = DEFAULT_RETRY_ON

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise PipelineDefinitionException("retry.max_attempts: expected an integer >= 1")
        if self.max_attempts < 1:
            raise PipelineDefinitionException("retry.max_attempts: expected an integer >= 1")
        if self.backoff_base < 0 or self.backoff_cap < 0:
            raise PipelineDefinitionException("retry: a back-off cannot be negative")
        kinds = tuple(self.retry_on)
        for kind in kinds:
            if not (isinstance(kind, type) and issubclass(kind, BaseException)):
                raise PipelineDefinitionException(f"retry.retry_on: {kind!r} is not an exception")
        object.__setattr__(self, "retry_on", kinds)

    def delay(self, attempt: int) -> float:
        """Return the seconds to wait after the failed attempt number ``attempt`` (1-based)."""
        exponent = min(max(attempt - 1, 0), _MAX_BACKOFF_EXPONENT)
        return float(min(self.backoff_cap, self.backoff_base * 2**exponent))

    def retries(self, error: BaseException) -> bool:
        """Return whether ``error`` is one this policy tries again after."""
        return isinstance(error, self.retry_on)


@dataclass(frozen=True)
class Schedule:
    """When a pipeline should run by itself; kept for the scheduler, not acted on here."""

    cron: str
    timezone: str | None = None

    def to_dict(self) -> dict[str, str]:
        """Return the ``schedule`` entry of a definition."""
        document = {"cron": self.cron}
        if self.timezone is not None:
            document["timezone"] = self.timezone
        return document


@dataclass(frozen=True)
class TaskContext:
    """What a task callable (or a ``when`` callable) is given.

    ``results`` maps the ID of every upstream task that succeeded to its result.
    ``cancel`` is set when the run is cancelled or the task's timeout has passed;
    a long task must look at it, because a running thread cannot be stopped from
    outside. ``attempt`` is 1-based (``0`` in a ``when`` callable).
    """

    pipeline: str
    run_id: str
    task: str
    attempt: int
    params: Mapping[str, Any]
    results: Mapping[str, Any]
    cancel: CancellationToken
    dry_run: bool = False


TaskCallable = Callable[[TaskContext], Any]
Condition = Callable[[TaskContext], bool]
TaskWork = TaskCallable | list[Any]


@dataclass(frozen=True)
class Task:
    """One unit of work in a pipeline and the rules for running it.

    ``work`` is a callable taking a :class:`TaskContext`, or an action
    (``[name]``, ``[name, {kwargs}]``, ``[name, [args]]``).
    """

    task_id: str
    work: TaskWork
    depends_on: tuple[str, ...] = ()
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout: float | None = None
    when: str | Condition = ON_SUCCESS
    idempotency_key: str | None = None

    @property
    def action_name(self) -> str | None:
        """Return the ``FA_*`` name of an action task, ``None`` for a callable."""
        return None if callable(self.work) else str(self.work[0])


@dataclass
class TaskRun:
    """What happened to one task in one run.

    ``result`` is the task's return value while the run is in memory. A store
    keeps it as JSON; a value JSON cannot hold is kept as its ``repr`` and
    ``result_is_repr`` is set, so a resumed run sees that text, not the object.
    ``reason`` says why a ``skipped`` task did not run.
    """

    task: str
    status: TaskStatus = TaskStatus.PENDING
    level: int = 0
    attempts: int = 0
    result: Any = None
    error: str | None = None
    reason: str | None = None
    idempotency_key: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_is_repr: bool = False

    @property
    def satisfied(self) -> bool:
        """Whether dependents can count on this task: it succeeded now or in an earlier run."""
        if self.status is TaskStatus.SUCCEEDED:
            return True
        return self.status is TaskStatus.SKIPPED and self.reason == REASON_IDEMPOTENT

    @property
    def duration_ms(self) -> float | None:
        """Return the milliseconds between start and finish, ``None`` while either is missing."""
        if self.started_at is None or self.finished_at is None:
            return None
        return round((self.finished_at - self.started_at).total_seconds() * 1000, 3)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the task's state."""
        result, converted = json_safe(self.result)
        return {
            "task": self.task,
            "status": self.status.value,
            "level": self.level,
            "attempts": self.attempts,
            "result": result,
            "result_is_repr": self.result_is_repr or converted,
            "error": self.error,
            "reason": self.reason,
            "idempotency_key": self.idempotency_key,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "duration_ms": self.duration_ms,
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> TaskRun:
        """Rebuild a task state from :meth:`to_dict`."""
        return cls(
            task=record["task"],
            status=TaskStatus(record["status"]),
            level=int(record.get("level", 0)),
            attempts=int(record.get("attempts", 0)),
            result=record.get("result"),
            error=record.get("error"),
            reason=record.get("reason"),
            idempotency_key=record.get("idempotency_key"),
            started_at=_moment(record.get("started_at")),
            finished_at=_moment(record.get("finished_at")),
            result_is_repr=bool(record.get("result_is_repr", False)),
        )


@dataclass
class PipelineRun:
    """One execution of a pipeline: its status, its parameters and every task's state.

    ``tasks`` is in dependency order. :meth:`cancel` asks a run to stop and
    :meth:`wait` blocks until it has ended; both matter for a run started in the
    background with :meth:`~automation_file.pipeline.pipeline.Pipeline.start`.
    """

    run_id: str
    pipeline: str
    status: RunStatus = RunStatus.RUNNING
    params: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    tasks: dict[str, TaskRun] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    cancel_token: CancellationToken = field(
        default_factory=CancellationToken, repr=False, compare=False
    )
    _ended: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False, compare=False
    )

    @property
    def done(self) -> bool:
        """Whether the run has ended."""
        return self._ended.is_set() and self.status is not RunStatus.RUNNING

    def cancel(self) -> None:
        """Ask the run to stop: unstarted tasks become ``cancelled``, running ones are told."""
        self.cancel_token.cancel()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the run has ended or ``timeout`` seconds passed; return whether it ended.

        A run read back from a store is a snapshot that nothing will change, so
        this returns at once, ``False`` if the snapshot is of a run still going.
        """
        self._ended.wait(timeout)
        return self.done

    def mark_done(self) -> None:
        """Release everything blocked in :meth:`wait`. The runtime calls this when the run ends."""
        self._ended.set()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the run and its tasks."""
        return {
            "run_id": self.run_id,
            "pipeline": self.pipeline,
            "status": self.status.value,
            "dry_run": self.dry_run,
            "params": {str(name): json_safe(value)[0] for name, value in self.params.items()},
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "error": self.error,
            "tasks": {task_id: state.to_dict() for task_id, state in self.tasks.items()},
        }

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> PipelineRun:
        """Rebuild a run from :meth:`to_dict`: a snapshot, with nothing left to wait for."""
        run = cls(
            run_id=record["run_id"],
            pipeline=record["pipeline"],
            status=RunStatus(record["status"]),
            params=dict(record.get("params") or {}),
            dry_run=bool(record.get("dry_run", False)),
            tasks={
                task_id: TaskRun.from_dict(state)
                for task_id, state in (record.get("tasks") or {}).items()
            },
            started_at=_moment(record.get("started_at")),
            finished_at=_moment(record.get("finished_at")),
            error=record.get("error"),
        )
        run.mark_done()
        return run
