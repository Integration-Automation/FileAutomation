"""What fires a job.

A job has any number of triggers; a job without one runs only when it is fired
by hand (:meth:`~automation_file.scheduler.manager.Scheduler.run_now`).

* :class:`CronTrigger` is polled: the scheduler asks it once a minute.
* :class:`FileTrigger`, :class:`EventTrigger` and :class:`PipelineTrigger` are
  *armed*: they start a file watcher or subscribe on the event bus, and call the
  scheduler back through a :class:`TriggerPort` when their moment has come.

Every trigger turns into a JSON-friendly mapping (``to_dict``) and back
(:func:`trigger_from_dict`), which is the form the ``FA_schedule_*`` actions take.
"""

from __future__ import annotations

import datetime as dt
import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import Any, ClassVar

from automation_file.events import (
    Event,
    EventBus,
    EventFilter,
    PipelineCompleted,
    PipelineFailed,
    Severity,
)
from automation_file.pipeline.model import ALWAYS, ON_FAILURE, ON_SUCCESS, WHEN_CHOICES
from automation_file.scheduler.cron import CronException, CronExpression, resolve_timezone
from automation_file.scheduler.errors import SchedulerException
from automation_file.scheduler.runs import TriggerKind

Disarm = Callable[[], object]
_KIND = "kind"
_DEFAULT_FILE_EVENTS = ("created", "modified")
_PIPELINE_EVENTS: dict[str, tuple[type[Event], ...]] = {
    ON_SUCCESS: (PipelineCompleted,),
    ON_FAILURE: (PipelineFailed,),
    ALWAYS: (PipelineCompleted, PipelineFailed),
}


@dataclass(frozen=True)
class TriggerPort:
    """What an armed trigger works with: the bus it listens on and how it fires its job.

    ``fire(kind, detail, cause)`` asks the scheduler to run the job; ``detail``
    ends up on the run record and ``cause`` is the event that did it, ``None``
    when there is none. ``is_own(event)`` tells whether an event was published
    by a run of this very job, which must not fire the job again.
    """

    job: str
    bus: EventBus
    fire: Callable[[TriggerKind, Mapping[str, Any], Event | None], object]
    is_own: Callable[[Event], bool]


class Trigger(ABC):
    """Something that fires a job. A subclass says when."""

    kind: ClassVar[TriggerKind]

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-friendly form of the trigger, with its ``kind``."""

    def arm(self, port: TriggerPort) -> Disarm | None:
        """Start watching for the trigger's moment and return the call that stops it.

        The default starts nothing and returns ``None``: a cron trigger is
        polled by the scheduler instead.
        """
        return None


def _as_tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, type)):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True)
class CronTrigger(Trigger):
    """Fires at the minutes a 5-field cron expression names.

    With ``timezone`` (an IANA name such as ``"Asia/Taipei"``, or ``"UTC"``) the
    expression is read in that zone; without one it is read in the system's
    local time, as the scheduler always did, and follows the system clock with
    no special case: a repeated local hour fires twice. With a zone that has
    daylight saving time, a wall-clock time that does not exist on the day the clocks go forward
    is not fired, and one that occurs twice when they go back fires once, the
    first time. An expression whose hour field is ``*`` runs every hour anyway
    and keeps firing through the repeated hour.
    """

    cron: str | CronExpression
    timezone: str | None = None
    expression: CronExpression = field(init=False, repr=False, compare=False)
    zone: dt.tzinfo | None = field(init=False, repr=False, compare=False)

    kind: ClassVar[TriggerKind] = TriggerKind.CRON

    def __post_init__(self) -> None:
        expression: Any = self.cron
        if not isinstance(expression, CronExpression):
            if not isinstance(expression, str):
                raise CronException(
                    f"cron: expected an expression, got {type(expression).__name__}"
                )
            expression = CronExpression.parse(expression)
        zone = resolve_timezone(self.timezone)
        object.__setattr__(self, "cron", expression.source)
        if self.timezone is not None:
            object.__setattr__(self, "timezone", self.timezone.strip())
        object.__setattr__(self, "expression", expression)
        object.__setattr__(self, "zone", zone)

    def moment(self, instant: dt.datetime) -> dt.datetime:
        """Return ``instant`` as the wall-clock time the expression is compared with.

        That is an aware ``datetime`` in the trigger's zone, or a naive one in
        local time when the trigger has no zone.
        """
        if self.zone is None:
            return instant.astimezone().replace(tzinfo=None)
        return instant.astimezone(self.zone)

    def due(self, instant: dt.datetime) -> bool:
        """Return whether the trigger fires at ``instant`` (an aware ``datetime``)."""
        local = self.moment(instant)
        if not self.expression.matches(local):
            return False
        # ``fold`` marks the second pass through an hour the clocks repeat.
        return not local.fold or self.expression.every_hour

    def to_dict(self) -> dict[str, Any]:
        return {_KIND: self.kind.value, "cron": self.cron, "timezone": self.timezone}


@dataclass(frozen=True)
class FileTrigger(Trigger):
    """Fires when something happens to a file under ``path``.

    ``events`` holds any of ``created``, ``modified``, ``deleted`` and ``moved``.
    The watching is done by :class:`~automation_file.trigger.FileWatcher`, the
    one behind ``FA_watch_start``; the scheduler owns the watcher and stops it
    when the job is removed.
    """

    path: str
    events: tuple[str, ...] | str = _DEFAULT_FILE_EVENTS
    recursive: bool = True

    kind: ClassVar[TriggerKind] = TriggerKind.FILE

    def __post_init__(self) -> None:
        if not isinstance(self.path, (str, os.PathLike)) or not os.fspath(self.path):
            raise SchedulerException(f"file trigger: expected a path, got {self.path!r}")
        object.__setattr__(self, "path", os.fspath(self.path))
        object.__setattr__(self, "events", _as_tuple(self.events) or _DEFAULT_FILE_EVENTS)
        object.__setattr__(self, "recursive", bool(self.recursive))

    def arm(self, port: TriggerPort) -> Disarm | None:
        from automation_file.trigger.manager import FileWatcher

        def on_event(kind: str, path: str) -> None:
            port.fire(self.kind, {"path": path, "event": kind}, None)

        watcher = FileWatcher(
            f"scheduler[{port.job}]",
            self.path,
            [],
            events=_as_tuple(self.events),
            recursive=self.recursive,
            on_event=on_event,
        )
        watcher.start()
        return watcher.stop

    def to_dict(self) -> dict[str, Any]:
        return {
            _KIND: self.kind.value,
            "path": self.path,
            "events": list(_as_tuple(self.events)),
            "recursive": self.recursive,
        }


def _type_name(wanted: EventFilter) -> str:
    return wanted if isinstance(wanted, str) else wanted.type


def _checked_filters(types: Any) -> tuple[EventFilter, ...]:
    chosen = _as_tuple(types)
    for wanted in chosen:
        if not _is_text(wanted) and not (isinstance(wanted, type) and issubclass(wanted, Event)):
            raise SchedulerException(
                "event trigger: a type is a name ('task.failed'), a prefix ('pipeline.*') "
                f"or an Event class, got {wanted!r}"
            )
    return chosen


def _checked_sources(sources: Any) -> tuple[str, ...]:
    chosen = _as_tuple(sources)
    for source in chosen:
        if not _is_text(source):
            raise SchedulerException(f"event trigger: a source is a name, got {source!r}")
    return chosen


def _checked_severity(severity: Any) -> Severity:
    try:
        return Severity(severity)
    except ValueError as error:
        known = ", ".join(item.value for item in Severity)
        raise SchedulerException(
            f"event trigger: unknown severity {severity!r} (one of: {known})"
        ) from error


@dataclass(frozen=True)
class EventTrigger(Trigger):
    """Fires when a matching event is published on the event bus.

    ``types`` takes what the bus takes: type names (``"task.failed"``), prefixes
    (``"pipeline.*"``) and event classes. ``sources`` are exact ``event.source``
    values and ``min_severity`` is the lowest severity that counts. At least one
    type or source is required, so that a job cannot fire on everything. This is
    also how a webhook fires a job: the code that receives the request publishes
    an event, and the trigger matches it.

    An event published by a run of the job itself does not fire the job again.
    Jobs that fire one another through their events form a chain, and the
    firing that would make a chain longer than 16 runs is recorded as
    ``skipped`` with the reason ``chain``.
    """

    types: tuple[EventFilter, ...] | EventFilter = ()
    sources: tuple[str, ...] | str = ()
    min_severity: Severity | str = Severity.INFO

    kind: ClassVar[TriggerKind] = TriggerKind.EVENT

    def __post_init__(self) -> None:
        types = _checked_filters(self.types)
        sources = _checked_sources(self.sources)
        if not types and not sources:
            raise SchedulerException("event trigger: give at least one type or one source")
        object.__setattr__(self, "types", types)
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "min_severity", _checked_severity(self.min_severity))

    def arm(self, port: TriggerPort) -> Disarm | None:
        sources = _as_tuple(self.sources)

        def on_event(event: Event) -> None:
            if (sources and event.source not in sources) or port.is_own(event):
                return
            port.fire(
                self.kind,
                {
                    "event_type": event.type,
                    "event_id": event.id,
                    "source": event.source,
                    "subject": event.subject,
                    "correlation_id": event.correlation_id,
                },
                event,
            )

        subscription = port.bus.subscribe(
            on_event, types=_as_tuple(self.types) or None, min_severity=Severity(self.min_severity)
        )
        return partial(port.bus.unsubscribe, subscription)

    def to_dict(self) -> dict[str, Any]:
        return {
            _KIND: self.kind.value,
            "types": [_type_name(wanted) for wanted in _as_tuple(self.types)],
            "sources": list(_as_tuple(self.sources)),
            "min_severity": Severity(self.min_severity).value,
        }


@dataclass(frozen=True)
class PipelineTrigger(Trigger):
    """Fires when a run of the pipeline named ``pipeline`` has ended.

    ``when`` uses the pipeline's own words: ``"on_success"`` (the default: the
    run succeeded), ``"on_failure"`` (it failed or was cancelled) or
    ``"always"``. The trigger listens for ``pipeline.completed`` and
    ``pipeline.failed`` on the scheduler's bus, so it sees every run of that
    pipeline published there, whoever started it.
    """

    pipeline: str
    when: str = ON_SUCCESS

    kind: ClassVar[TriggerKind] = TriggerKind.PIPELINE

    def __post_init__(self) -> None:
        if not _is_text(self.pipeline):
            raise SchedulerException(
                f"pipeline trigger: expected a pipeline name, got {self.pipeline!r}"
            )
        if self.when not in WHEN_CHOICES:
            raise SchedulerException(
                f"pipeline trigger: when is one of {', '.join(WHEN_CHOICES)}, got {self.when!r}"
            )

    def arm(self, port: TriggerPort) -> Disarm | None:
        def on_event(event: Event) -> None:
            if event.payload.get("pipeline") != self.pipeline or port.is_own(event):
                return
            port.fire(
                self.kind,
                {
                    "pipeline": self.pipeline,
                    "run_id": event.payload.get("run_id"),
                    "status": event.payload.get("status"),
                },
                event,
            )

        subscription = port.bus.subscribe(on_event, types=_PIPELINE_EVENTS[self.when])
        return partial(port.bus.unsubscribe, subscription)

    def to_dict(self) -> dict[str, Any]:
        return {_KIND: self.kind.value, "pipeline": self.pipeline, "when": self.when}


@dataclass(frozen=True)
class _Shape:
    """How one kind of trigger is written as a mapping."""

    builder: Callable[..., Trigger]
    keys: tuple[str, ...]
    required: str | None = None


_SHAPES: dict[str, _Shape] = {
    TriggerKind.CRON.value: _Shape(CronTrigger, ("cron", "timezone"), "cron"),
    TriggerKind.FILE.value: _Shape(FileTrigger, ("path", "events", "recursive"), "path"),
    TriggerKind.EVENT.value: _Shape(EventTrigger, ("types", "sources", "min_severity")),
    TriggerKind.PIPELINE.value: _Shape(PipelineTrigger, ("pipeline", "when"), "pipeline"),
}


def trigger_from_dict(spec: Mapping[str, Any]) -> Trigger:
    """Build a trigger from its mapping: ``{"kind": "cron", "cron": "0 2 * * *", ...}``.

    The keys besides ``kind`` are the trigger's arguments. An unknown kind, an
    unknown key or a missing argument raises :class:`SchedulerException`.
    """
    if not isinstance(spec, Mapping):
        raise SchedulerException(f"trigger: expected a mapping, got {type(spec).__name__}")
    kind = spec.get(_KIND)
    if kind == TriggerKind.MANUAL.value:
        raise SchedulerException(
            "trigger: 'manual' needs no trigger; every job can be fired by hand "
            "(Scheduler.run_now, FA_schedule_run)"
        )
    if not isinstance(kind, str) or kind not in _SHAPES:
        raise SchedulerException(
            f"trigger: unknown kind {kind!r} (one of: {', '.join(sorted(_SHAPES))})"
        )
    shape = _SHAPES[kind]
    unknown = sorted(str(key) for key in spec if key != _KIND and key not in shape.keys)
    if unknown:
        raise SchedulerException(
            f"{kind} trigger: unknown key {', '.join(unknown)} (known: {', '.join(shape.keys)})"
        )
    if shape.required is not None and shape.required not in spec:
        raise SchedulerException(f"{kind} trigger: {shape.required!r} is required")
    return shape.builder(**{key: spec[key] for key in shape.keys if key in spec})


def as_triggers(triggers: Any) -> tuple[Trigger, ...]:
    """Return ``triggers`` as a tuple: ``None``, one trigger, one mapping, or several of either."""
    if triggers is None:
        return ()
    if isinstance(triggers, (Trigger, Mapping)):
        triggers = (triggers,)
    if isinstance(triggers, (str, bytes)) or not isinstance(triggers, Iterable):
        raise SchedulerException(
            f"triggers: expected triggers or their mappings, got {type(triggers).__name__}"
        )
    return tuple(
        entry if isinstance(entry, Trigger) else trigger_from_dict(entry) for entry in triggers
    )
