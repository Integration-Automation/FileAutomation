"""The event model: what happened, how bad it is, and which run it belongs to.

Every component reports through :class:`Event` objects instead of calling a
notification sink or the audit log itself. An event is frozen and JSON-friendly
(:meth:`Event.to_dict`), carries a severity and a correlation ID, and keeps its
details in ``payload`` under the keys listed in :data:`PAYLOAD_KEYS`.

The ten core events are subclasses that fix the ``type`` and the default
severity (which a caller may still override). ``SystemErrorEvent`` is the roadmap's "SystemError"; the shorter name
would shadow Python's builtin exception.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar

from automation_file.events.context import (
    current_actor,
    current_correlation_id,
    new_correlation_id,
)

#: Conventional ``payload`` keys, so consumers can rely on them across emitters.
PAYLOAD_KEYS = (
    "pipeline",  # pipeline name
    "run_id",  # one execution of a pipeline
    "task",  # task ID inside the pipeline
    "attempt",  # 1-based attempt number of a task
    "action",  # FA_* action or operation name
    "resource",  # storage URI or other target
    "backend",  # storage scheme
    "status",  # outcome word of the emitter
    "duration_ms",
    "error",  # "<ExceptionType>: <message>"
    "job",  # scheduler job name
    "trigger",  # what fired a run
)


class Severity(str, Enum):
    """How much attention an event needs, in rising order."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_ORDER.index(self)

    def at_least(self, other: Severity) -> bool:
        """Return whether this severity is ``other`` or worse."""
        return self.rank >= other.rank


_SEVERITY_ORDER = (Severity.INFO, Severity.WARNING, Severity.ERROR, Severity.CRITICAL)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _event_id() -> str:
    return uuid.uuid4().hex


def _correlation() -> str:
    return current_correlation_id() or new_correlation_id()


@dataclass(frozen=True, kw_only=True)
class Event:
    """Something that happened. Subclasses name the kind; ``payload`` holds the details."""

    type: ClassVar[str] = "event"

    source: str = ""
    subject: str = ""
    severity: Severity = Severity.INFO
    payload: Mapping[str, Any] = field(default_factory=dict, hash=False)
    correlation_id: str = field(default_factory=_correlation)
    actor: str = field(default_factory=current_actor)
    id: str = field(default_factory=_event_id)
    timestamp: datetime = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping of the event."""
        return {
            "id": self.id,
            "type": self.type,
            "severity": self.severity.value,
            "source": self.source,
            "subject": self.subject,
            "correlation_id": self.correlation_id,
            "actor": self.actor,
            "timestamp": self.timestamp.isoformat(),
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, kw_only=True)
class PipelineStarted(Event):
    type: ClassVar[str] = "pipeline.started"


@dataclass(frozen=True, kw_only=True)
class PipelineCompleted(Event):
    type: ClassVar[str] = "pipeline.completed"


@dataclass(frozen=True, kw_only=True)
class PipelineFailed(Event):
    type: ClassVar[str] = "pipeline.failed"
    severity: Severity = Severity.ERROR


@dataclass(frozen=True, kw_only=True)
class TaskStarted(Event):
    type: ClassVar[str] = "task.started"


@dataclass(frozen=True, kw_only=True)
class TaskCompleted(Event):
    type: ClassVar[str] = "task.completed"


@dataclass(frozen=True, kw_only=True)
class TaskFailed(Event):
    type: ClassVar[str] = "task.failed"
    severity: Severity = Severity.ERROR


@dataclass(frozen=True, kw_only=True)
class IntegrityViolation(Event):
    type: ClassVar[str] = "integrity.violation"
    severity: Severity = Severity.ERROR


@dataclass(frozen=True, kw_only=True)
class StorageError(Event):
    type: ClassVar[str] = "storage.error"
    severity: Severity = Severity.ERROR


@dataclass(frozen=True, kw_only=True)
class SchedulerError(Event):
    type: ClassVar[str] = "scheduler.error"
    severity: Severity = Severity.ERROR


@dataclass(frozen=True, kw_only=True)
class SystemErrorEvent(Event):
    type: ClassVar[str] = "system.error"
    severity: Severity = Severity.CRITICAL


CORE_EVENTS: tuple[type[Event], ...] = (
    PipelineStarted,
    PipelineCompleted,
    PipelineFailed,
    TaskStarted,
    TaskCompleted,
    TaskFailed,
    IntegrityViolation,
    StorageError,
    SchedulerError,
    SystemErrorEvent,
)
