"""Prometheus metrics: actions, events, notifications and storage operations.

Per-action metrics, updated by
:class:`~automation_file.core.action_executor.ActionExecutor` on every call:

* ``automation_file_actions_total{action, status}`` — counter incremented
  with ``status="ok"`` or ``status="error"`` per action.
* ``automation_file_action_duration_seconds{action}`` — histogram of wall
  time spent inside the registered callable.

Operational metrics:

* ``automation_file_events_total{type, severity}`` — events published on the
  event bus.
* ``automation_file_notifications_total{sink, outcome}`` — notifications per
  sink, with ``outcome`` one of ``sent``, ``dedup``, ``rate_limited`` or
  ``error``.
* ``automation_file_storage_operations_total{operation, backend, status}`` —
  uploads, downloads, reads, deletes, mkdirs, copies and moves of the storage
  layer.
* ``automation_file_storage_operation_duration_seconds{operation, backend}`` —
  histogram of the time one storage operation took.

The event and storage metrics are fed by a bus subscriber and a storage
observer that :func:`install_operational_metrics` registers once. The
notification counter is fed by the notification manager and router, which
are the only places that know a delivery succeeded.

No label ever carries a path, a URI or a correlation ID, and each label keeps
at most :data:`MAX_LABEL_VALUES` distinct values; further values are counted
under ``other``.

:func:`render` returns the wire-format text and matching ``Content-Type``
suitable for a ``GET /metrics`` handler. Every write path swallows its own
failures so a broken metrics backend can never abort a real action.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest

from automation_file.logging_config import file_automation_logger

if TYPE_CHECKING:
    from automation_file.events.bus import EventBus, Subscription
    from automation_file.events.model import Event
    from automation_file.storage.observe import StorageOperation

_DURATION_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
)

#: Distinct values one label may take before the rest is counted as ``other``.
MAX_LABEL_VALUES = 100
OTHER_LABEL = "other"
_UNKNOWN_LABEL = "unknown"
_MILLISECONDS = 1000.0

ACTION_COUNT = Counter(
    "automation_file_actions_total",
    "Total actions executed, partitioned by outcome.",
    labelnames=("action", "status"),
)
ACTION_DURATION = Histogram(
    "automation_file_action_duration_seconds",
    "Time spent inside a registered action callable.",
    labelnames=("action",),
    buckets=_DURATION_BUCKETS,
)
EVENT_COUNT = Counter(
    "automation_file_events_total",
    "Events published on the event bus, by type and severity.",
    labelnames=("type", "severity"),
)
NOTIFICATION_COUNT = Counter(
    "automation_file_notifications_total",
    "Notifications per sink, by outcome (sent, dedup, rate_limited, error).",
    labelnames=("sink", "outcome"),
)
STORAGE_OPERATION_COUNT = Counter(
    "automation_file_storage_operations_total",
    "Storage operations, by operation, backend and status.",
    labelnames=("operation", "backend", "status"),
)
STORAGE_OPERATION_DURATION = Histogram(
    "automation_file_storage_operation_duration_seconds",
    "Time one storage operation took.",
    labelnames=("operation", "backend"),
    buckets=_DURATION_BUCKETS,
)


class _BoundedLabel:
    """Let a label take a limited number of distinct values; the rest become ``other``."""

    def __init__(self, limit: int = MAX_LABEL_VALUES) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self._known: set[str] = set()

    def __call__(self, value: object) -> str:
        text = str(value) if value else _UNKNOWN_LABEL
        with self._lock:
            if text in self._known:
                return text
            if len(self._known) < self._limit:
                self._known.add(text)
                return text
        return OTHER_LABEL


_event_type = _BoundedLabel()
_sink_name = _BoundedLabel()
_notification_outcome = _BoundedLabel()
_storage_operation = _BoundedLabel()
_storage_backend = _BoundedLabel()
_storage_status = _BoundedLabel()

_install_lock = threading.Lock()
_subscriptions: list[tuple[EventBus, Subscription]] = []


def record_action(action: str, duration_seconds: float, ok: bool) -> None:
    """Record one action execution. Never raises."""
    status = "ok" if ok else "error"
    try:
        ACTION_COUNT.labels(action=action, status=status).inc()
        ACTION_DURATION.labels(action=action).observe(max(0.0, float(duration_seconds)))
    except Exception as err:  # pylint: disable=broad-except  # pragma: no cover - defensive
        file_automation_logger.error("metrics.record_action failed: %r", err)


def record_event(event: Event) -> None:
    """Count one published event by type and severity. Never raises."""
    try:
        EVENT_COUNT.labels(type=_event_type(event.type), severity=event.severity.value).inc()
    except Exception as err:  # pylint: disable=broad-except  # pragma: no cover - defensive
        file_automation_logger.error("metrics.record_event failed: %r", err)


def record_notification(sink: str, outcome: str) -> None:
    """Count one notification for ``sink`` with its ``outcome``. Never raises."""
    try:
        NOTIFICATION_COUNT.labels(
            sink=_sink_name(sink), outcome=_notification_outcome(outcome)
        ).inc()
    except Exception as err:  # pylint: disable=broad-except  # pragma: no cover - defensive
        file_automation_logger.error("metrics.record_notification failed: %r", err)


def record_storage_operation(operation: StorageOperation) -> None:
    """Count one storage operation and observe how long it took. Never raises."""
    try:
        name = _storage_operation(operation.operation)
        backend = _storage_backend(operation.backend)
        STORAGE_OPERATION_COUNT.labels(
            operation=name, backend=backend, status=_storage_status(operation.status)
        ).inc()
        STORAGE_OPERATION_DURATION.labels(operation=name, backend=backend).observe(
            max(0.0, float(operation.duration_ms)) / _MILLISECONDS
        )
    except Exception as err:  # pylint: disable=broad-except  # pragma: no cover - defensive
        file_automation_logger.error("metrics.record_storage_operation failed: %r", err)


def install_operational_metrics(bus: EventBus | None = None) -> bool:
    """Feed the event and storage metrics from ``bus`` and the storage observers.

    ``bus`` defaults to the process-wide event bus. Calling it again for the
    same bus changes nothing; the return value tells whether this call
    subscribed.
    """
    from automation_file.events.bus import event_bus
    from automation_file.storage import observe

    target = bus if bus is not None else event_bus
    with _install_lock:
        if any(known is target for known, _ in _subscriptions):
            return False
        _subscriptions.append((target, target.subscribe(record_event)))
        observe.add_listener(record_storage_operation)
    return True


def uninstall_operational_metrics(bus: EventBus | None = None) -> bool:
    """Stop feeding the metrics from ``bus``; return whether it was installed.

    The storage observer goes with the last bus. The collected values stay.
    """
    from automation_file.events.bus import event_bus
    from automation_file.storage import observe

    target = bus if bus is not None else event_bus
    with _install_lock:
        installed = [entry for entry in _subscriptions if entry[0] is target]
        for entry in installed:
            _subscriptions.remove(entry)
            target.unsubscribe(entry[1])
        if not _subscriptions:
            observe.remove_listener(record_storage_operation)
    return bool(installed)


def render() -> tuple[bytes, str]:
    """Return ``(payload, content_type)`` for a ``/metrics`` response."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
