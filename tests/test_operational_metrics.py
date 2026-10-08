"""Operational metrics: events, notifications and storage operations."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from prometheus_client import REGISTRY

from automation_file.core import metrics
from automation_file.core.metrics import (
    install_operational_metrics,
    record_event,
    record_notification,
    record_storage_operation,
    render,
    uninstall_operational_metrics,
)
from automation_file.events import (
    EventBus,
    PipelineStarted,
    Severity,
    TaskFailed,
    correlation_scope,
    event_bus,
)
from automation_file.exceptions import StorageNotFoundException
from automation_file.notify import (
    NotificationException,
    NotificationManager,
    NotificationRouter,
    NotificationSink,
    Route,
)
from automation_file.storage import MemoryStorage
from automation_file.storage.observe import StorageOperation

_EVENTS = "automation_file_events_total"
_NOTIFICATIONS = "automation_file_notifications_total"
_OPERATIONS = "automation_file_storage_operations_total"
_DURATION = "automation_file_storage_operation_duration_seconds"


def _sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


@pytest.fixture
def bus() -> Iterator[EventBus]:
    """A private bus that feeds the metrics, removed again afterwards."""
    private = EventBus()
    assert install_operational_metrics(private) is True
    yield private
    assert uninstall_operational_metrics(private) is True


class _Sink(NotificationSink):
    def __init__(self, name: str, fail: bool = False) -> None:
        self.name = name
        self._fail = fail

    def send(self, subject: str, body: str, level: str = "info") -> None:
        if self._fail:
            raise NotificationException("channel is down")


def test_published_events_are_counted_by_type_and_severity(bus: EventBus) -> None:
    failed = _sample(_EVENTS, type="task.failed", severity="error")
    started = _sample(_EVENTS, type="pipeline.started", severity="info")
    warned = _sample(_EVENTS, type="pipeline.started", severity="warning")
    bus.publish(TaskFailed(source="pipeline", subject="load failed"))
    bus.publish(PipelineStarted())
    bus.publish(PipelineStarted())
    bus.publish(PipelineStarted(severity=Severity.WARNING))
    assert _sample(_EVENTS, type="task.failed", severity="error") == failed + 1
    assert _sample(_EVENTS, type="pipeline.started", severity="info") == started + 2
    assert _sample(_EVENTS, type="pipeline.started", severity="warning") == warned + 1


def test_installing_twice_counts_an_event_once(bus: EventBus) -> None:
    assert install_operational_metrics(bus) is False
    before = _sample(_EVENTS, type="task.failed", severity="error")
    bus.publish(TaskFailed())
    assert _sample(_EVENTS, type="task.failed", severity="error") == before + 1


def test_uninstalling_stops_the_counting() -> None:
    private = EventBus()
    assert uninstall_operational_metrics(private) is False
    install_operational_metrics(private)
    assert uninstall_operational_metrics(private) is True
    before = _sample(_EVENTS, type="task.failed", severity="error")
    private.publish(TaskFailed())
    assert _sample(_EVENTS, type="task.failed", severity="error") == before


def test_the_process_wide_bus_is_the_default() -> None:
    installed_here = install_operational_metrics()
    try:
        assert install_operational_metrics() is False
        before = _sample(_EVENTS, type="pipeline.started", severity="info")
        event_bus.publish(PipelineStarted(subject="metrics on the process-wide bus"))
        assert _sample(_EVENTS, type="pipeline.started", severity="info") == before + 1
    finally:
        if installed_here:
            assert uninstall_operational_metrics() is True


@pytest.mark.usefixtures("bus")
def test_storage_operations_are_counted_with_their_duration() -> None:
    uploads = _sample(_OPERATIONS, operation="upload", backend="memory", status="ok")
    reads = _sample(_OPERATIONS, operation="read", backend="memory", status="ok")
    misses = _sample(_OPERATIONS, operation="read", backend="memory", status="error")
    timed = _sample(f"{_DURATION}_count", operation="read", backend="memory")
    spent = _sample(f"{_DURATION}_sum", operation="read", backend="memory")
    storage = MemoryStorage("metrics")
    storage.write_bytes("a.txt", b"x")
    storage.read_bytes("a.txt")
    with pytest.raises(StorageNotFoundException):
        storage.read_bytes("missing.txt")
    assert _sample(_OPERATIONS, operation="upload", backend="memory", status="ok") == uploads + 1
    assert _sample(_OPERATIONS, operation="read", backend="memory", status="ok") == reads + 1
    assert _sample(_OPERATIONS, operation="read", backend="memory", status="error") == misses + 1
    assert _sample(f"{_DURATION}_count", operation="read", backend="memory") == timed + 2
    assert _sample(f"{_DURATION}_sum", operation="read", backend="memory") >= spent


def test_a_duration_is_observed_in_seconds() -> None:
    labels = {"operation": "copy", "backend": "metrics-seconds"}
    record_storage_operation(
        StorageOperation(
            operation="copy",
            uri="metrics-seconds://bucket/a.txt",
            backend="metrics-seconds",
            status="ok",
            duration_ms=2500.0,
        )
    )
    assert _sample(f"{_DURATION}_sum", **labels) == pytest.approx(2.5)
    assert _sample(f"{_DURATION}_bucket", le="2.5", **labels) == 1
    assert _sample(f"{_DURATION}_bucket", le="1.0", **labels) == 0


def test_notifications_are_counted_by_sink_and_outcome() -> None:
    manager = NotificationManager(dedup_seconds=60.0)
    manager.register(_Sink("metrics-good"))
    manager.register(_Sink("metrics-bad", fail=True))
    manager.notify("subject", "body", "info")
    manager.notify("subject", "body", "info")
    manager.send_to("metrics-good", "direct")
    assert _sample(_NOTIFICATIONS, sink="metrics-good", outcome="sent") == 2
    assert _sample(_NOTIFICATIONS, sink="metrics-good", outcome="dedup") == 1
    assert _sample(_NOTIFICATIONS, sink="metrics-bad", outcome="error") == 1
    assert _sample(_NOTIFICATIONS, sink="metrics-bad", outcome="dedup") == 1
    assert _sample(_NOTIFICATIONS, sink="metrics-bad", outcome="sent") == 0


def test_the_router_counts_what_it_holds_back() -> None:
    manager = NotificationManager(dedup_seconds=0.0)
    manager.register(_Sink("metrics-routed"))
    router = NotificationRouter(manager, EventBus())
    router.add_route(Route("limited", types=("task.failed",), rate_limit=1))
    router.add_route(Route("typo", sinks=("metrics-missing",), types=("task.failed",)))
    router.handle(TaskFailed(subject="one"))
    router.handle(TaskFailed(subject="one"))
    router.handle(TaskFailed(subject="two"))
    assert _sample(_NOTIFICATIONS, sink="metrics-routed", outcome="sent") == 1
    assert _sample(_NOTIFICATIONS, sink="metrics-routed", outcome="dedup") == 1
    assert _sample(_NOTIFICATIONS, sink="metrics-routed", outcome="rate_limited") == 1
    assert _sample(_NOTIFICATIONS, sink="metrics-missing", outcome="error") == 2
    assert _sample(_NOTIFICATIONS, sink="metrics-missing", outcome="dedup") == 1


def test_no_label_carries_a_path_or_a_correlation_id(bus: EventBus) -> None:
    with correlation_scope("metrics-correlation-id"):
        bus.publish(TaskFailed(source="pipeline", subject="metrics-secret-subject"))
        MemoryStorage("metrics-private-bucket").write_bytes("metrics-private-file.txt", b"x")
    exposition = render()[0].decode("utf-8")
    for name in (_EVENTS, _NOTIFICATIONS, _OPERATIONS, _DURATION):
        assert name in exposition
    for leaked in (
        "metrics-correlation-id",
        "metrics-secret-subject",
        "metrics-private-bucket",
        "metrics-private-file.txt",
    ):
        assert leaked not in exposition
    label_names = {
        label
        for metric in REGISTRY.collect()
        if metric.name.startswith("automation_file_")
        for sample in metric.samples
        for label in sample.labels
    }
    assert label_names <= {
        "action",
        "status",
        "type",
        "severity",
        "sink",
        "outcome",
        "operation",
        "backend",
        "le",
    }


def test_a_label_takes_a_bounded_number_of_values() -> None:
    label = metrics._BoundedLabel(limit=2)  # pylint: disable=protected-access
    assert [label(value) for value in ("a", "b", "c", "a", "d", "b", "", None)] == [
        "a",
        "b",
        "other",
        "a",
        "other",
        "b",
        "other",
        "other",
    ]
    assert metrics.MAX_LABEL_VALUES == 100
    roomy = metrics._BoundedLabel()  # pylint: disable=protected-access
    assert roomy("") == "unknown"


def test_recording_never_raises() -> None:
    record_event(object())
    record_storage_operation(object())
    record_notification("metrics-odd", "sent")
    record_notification("", "")
    assert _sample(_NOTIFICATIONS, sink="unknown", outcome="unknown") >= 1
