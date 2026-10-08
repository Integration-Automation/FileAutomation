"""The event model, the bus, the scopes, and the storage-error bridge."""

# pylint: disable=redefined-outer-name  # pytest passes fixtures by matching name
# pylint: disable=too-many-function-args  # the call is expected to be refused
# pylint: disable=use-implicit-booleaness-not-comparison  # an exact empty value is what is asserted

from __future__ import annotations

import dataclasses
import json
import threading
from collections.abc import Iterator
from datetime import timedelta

import pytest

import automation_file
from automation_file.events import (
    CORE_EVENTS,
    Event,
    EventBus,
    IntegrityViolation,
    PipelineCompleted,
    PipelineFailed,
    PipelineStarted,
    Severity,
    StorageError,
    StorageErrorBridge,
    SystemErrorEvent,
    TaskFailed,
    actor_scope,
    correlation_scope,
    current_actor,
    current_correlation_id,
    emit,
    event_bus,
    new_correlation_id,
)
from automation_file.exceptions import StorageNotFoundException, StoragePermissionException
from automation_file.storage import MemoryStorage, observe


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


# ---------------------------------------------------------------------- model


def test_the_ten_core_events_have_distinct_types() -> None:
    assert [event.type for event in CORE_EVENTS] == [
        "pipeline.started",
        "pipeline.completed",
        "pipeline.failed",
        "task.started",
        "task.completed",
        "task.failed",
        "integrity.violation",
        "storage.error",
        "scheduler.error",
        "system.error",
    ]


@pytest.mark.parametrize(
    "event_class,severity",
    [
        (PipelineStarted, Severity.INFO),
        (PipelineCompleted, Severity.INFO),
        (PipelineFailed, Severity.ERROR),
        (TaskFailed, Severity.ERROR),
        (IntegrityViolation, Severity.ERROR),
        (StorageError, Severity.ERROR),
        (SystemErrorEvent, Severity.CRITICAL),
    ],
)
def test_each_core_event_has_its_default_severity(
    event_class: type[Event], severity: Severity
) -> None:
    assert event_class().severity is severity
    assert event_class(severity=Severity.WARNING).severity is Severity.WARNING


def test_an_event_fills_in_its_identity() -> None:
    first, second = PipelineStarted(source="pipeline"), PipelineStarted(source="pipeline")
    assert first.id != second.id
    assert len(first.id) == 32
    assert first.timestamp.utcoffset() == timedelta(0)
    assert first.correlation_id != second.correlation_id
    assert first.actor == current_actor()
    assert dict(first.payload) == {}


def test_an_event_is_frozen_and_keyword_only() -> None:
    event = TaskFailed(subject="boom", payload={"task": "load"})
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.subject = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        TaskFailed("positional")  # type: ignore[misc]
    assert isinstance(hash(event), int)


def test_to_dict_is_json_serialisable() -> None:
    event = TaskFailed(
        source="pipeline",
        subject="load failed",
        payload={"pipeline": "daily", "task": "load", "attempt": 2, "error": "X: y"},
        correlation_id="run-1",
        actor="scheduler",
    )
    document = json.loads(json.dumps(event.to_dict()))
    assert document["type"] == "task.failed"
    assert document["severity"] == "error"
    assert document["correlation_id"] == "run-1"
    assert document["actor"] == "scheduler"
    assert document["payload"]["attempt"] == 2
    assert document["timestamp"].endswith("+00:00")
    assert document["id"] == event.id


def test_severity_order() -> None:
    assert [severity.rank for severity in Severity] == [0, 1, 2, 3]
    assert Severity.ERROR.at_least(Severity.WARNING) is True
    assert Severity.ERROR.at_least(Severity.ERROR) is True
    assert Severity.WARNING.at_least(Severity.ERROR) is False
    assert Severity("critical") is Severity.CRITICAL


# ---------------------------------------------------------------------- scopes


def test_correlation_scope_is_shared_by_nested_scopes() -> None:
    assert current_correlation_id() is None
    with correlation_scope() as outer:
        assert current_correlation_id() == outer
        assert PipelineStarted().correlation_id == outer
        with correlation_scope() as inner:
            assert inner == outer
        with correlation_scope("explicit") as explicit:
            assert explicit == "explicit"
            assert PipelineStarted().correlation_id == "explicit"
        assert current_correlation_id() == outer
    assert current_correlation_id() is None
    assert len(new_correlation_id()) == 32


def test_actor_scope() -> None:
    default = current_actor()
    assert default
    with actor_scope("scheduler"):
        assert current_actor() == "scheduler"
        assert PipelineStarted().actor == "scheduler"
        with actor_scope("mcp"):
            assert current_actor() == "mcp"
        assert current_actor() == "scheduler"
    assert current_actor() == default


def test_scopes_do_not_leak_into_other_threads() -> None:
    seen: list[str | None] = []
    with correlation_scope("main-run"):
        thread = threading.Thread(target=lambda: seen.append(current_correlation_id()))
        thread.start()
        thread.join()
    assert seen == [None]


# ---------------------------------------------------------------------- bus


def test_publish_reaches_every_matching_subscriber_in_order(bus: EventBus) -> None:
    calls: list[str] = []
    bus.subscribe(lambda event: calls.append(f"all:{event.type}"))
    bus.subscribe(lambda event: calls.append("class"), types=PipelineFailed)
    bus.subscribe(lambda event: calls.append("name"), types="task.failed")
    bus.subscribe(lambda event: calls.append("prefix"), types="pipeline.*")
    bus.subscribe(lambda event: calls.append("several"), types=[TaskFailed, "storage.error"])
    assert bus.publish(PipelineFailed()) == 3
    assert calls == ["all:pipeline.failed", "class", "prefix"]
    calls.clear()
    assert bus.publish(TaskFailed()) == 3
    assert calls == ["all:task.failed", "name", "several"]
    calls.clear()
    assert bus.publish(StorageError()) == 2
    assert calls == ["all:storage.error", "several"]


def test_a_prefix_does_not_match_a_longer_word(bus: EventBus) -> None:
    calls: list[str] = []
    bus.subscribe(lambda event: calls.append(event.type), types="task.*")

    @dataclasses.dataclass(frozen=True, kw_only=True)
    class Tasklist(Event):
        type = "tasklist.updated"

    bus.publish(Tasklist())
    bus.publish(TaskFailed())
    assert calls == ["task.failed"]


def test_min_severity_filters(bus: EventBus) -> None:
    calls: list[str] = []
    bus.subscribe(lambda event: calls.append(event.type), min_severity=Severity.ERROR)
    bus.publish(PipelineStarted())
    bus.publish(PipelineStarted(severity=Severity.CRITICAL))
    bus.publish(TaskFailed())
    bus.publish(TaskFailed(severity=Severity.WARNING))
    assert calls == ["pipeline.started", "task.failed"]


def test_a_failing_subscriber_does_not_stop_the_others(bus: EventBus) -> None:
    calls: list[str] = []

    def broken(_event: Event) -> None:
        raise RuntimeError("subscriber bug")

    bus.subscribe(broken)
    bus.subscribe(lambda event: calls.append(event.type))
    assert bus.publish(PipelineStarted()) == 1
    assert calls == ["pipeline.started"]


def test_unsubscribe(bus: EventBus) -> None:
    calls: list[str] = []
    subscription = bus.subscribe(lambda event: calls.append(event.type))
    assert bus.unsubscribe(subscription) is True
    assert bus.unsubscribe(subscription) is False
    assert bus.publish(PipelineStarted()) == 0
    assert calls == []


def test_subscribe_rejects_a_non_callable(bus: EventBus) -> None:
    with pytest.raises(TypeError):
        bus.subscribe("not callable")  # type: ignore[arg-type]


def test_recent_returns_the_latest_events_newest_first(bus: EventBus) -> None:
    with correlation_scope("run-1"):
        started = PipelineStarted()
        failed = TaskFailed()
    other = StorageError()
    for event in (started, failed, other):
        bus.publish(event)
    assert bus.recent() == [other, failed, started]
    assert bus.recent(limit=1) == [other]
    assert bus.recent(types="task.*") == [failed]
    assert bus.recent(min_severity=Severity.ERROR) == [other, failed]
    assert bus.recent(correlation_id="run-1") == [failed, started]
    assert bus.recent(limit=0) == []


def test_history_is_bounded() -> None:
    bus = EventBus(history=3)
    events = [PipelineStarted() for _ in range(5)]
    for event in events:
        bus.publish(event)
    assert bus.recent() == list(reversed(events[2:]))


def test_clear_forgets_subscriptions_and_history(bus: EventBus) -> None:
    calls: list[str] = []
    bus.subscribe(lambda event: calls.append(event.type))
    bus.publish(PipelineStarted())
    bus.clear()
    assert bus.recent() == []
    assert bus.publish(PipelineStarted()) == 0
    assert calls == ["pipeline.started"]


def test_emit_publishes_on_the_process_wide_bus() -> None:
    calls: list[Event] = []
    subscription = event_bus.subscribe(calls.append, types="pipeline.completed")
    try:
        event = PipelineCompleted(subject="done")
        assert emit(event) >= 1
    finally:
        event_bus.unsubscribe(subscription)
    assert calls == [event]


# ---------------------------------------------------------------------- storage bridge


@pytest.fixture
def bridged(bus: EventBus) -> Iterator[list[Event]]:
    bridge = StorageErrorBridge(bus)
    received: list[Event] = []
    bus.subscribe(received.append)
    observe.add_listener(bridge)
    yield received
    observe.remove_listener(bridge)


def test_a_storage_failure_becomes_a_storage_error_event(
    bridged: list[Event], monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = MemoryStorage("events")

    def _deny(*_args: object) -> None:
        raise StoragePermissionException("memory://events/a.txt: denied")

    monkeypatch.setattr(storage, "_upload", _deny)
    with correlation_scope("run-7"), pytest.raises(StoragePermissionException):
        storage.write_bytes("a.txt", b"x")
    assert len(bridged) == 1
    event = bridged[0]
    assert isinstance(event, StorageError)
    assert event.source == "storage"
    assert event.severity is Severity.ERROR
    assert event.correlation_id == "run-7"
    assert event.subject == "upload failed: memory://events/a.txt"
    assert event.payload["resource"] == "memory://events/a.txt"
    assert event.payload["backend"] == "memory"
    assert event.payload["error_type"] == "StoragePermissionException"


def test_a_caller_mistake_raises_without_an_event(bridged: list[Event]) -> None:
    storage = MemoryStorage("events")
    with pytest.raises(StorageNotFoundException):
        storage.read_bytes("nope.txt")
    storage.write_bytes("a.txt", b"x")
    assert bridged == []


def test_the_facade_exports_the_events() -> None:
    for name in (
        "Event",
        "EventBus",
        "Severity",
        "event_bus",
        "emit",
        "correlation_scope",
        "actor_scope",
        "PipelineStarted",
        "PipelineCompleted",
        "PipelineFailed",
        "TaskStarted",
        "TaskCompleted",
        "TaskFailed",
        "IntegrityViolation",
        "StorageError",
        "SchedulerError",
        "SystemErrorEvent",
    ):
        assert name in automation_file.__all__
        assert hasattr(automation_file, name)
