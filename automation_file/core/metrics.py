"""Prometheus metrics — per-action counters and duration histogram.

The module exposes two metrics that are updated from
:class:`~automation_file.core.action_executor.ActionExecutor` on every
call:

* ``automation_file_actions_total{action, status}`` — counter incremented
  with ``status="ok"`` or ``status="error"`` per action.
* ``automation_file_action_duration_seconds{action}`` — histogram of wall
  time spent inside the registered callable.

:func:`render` returns the wire-format text and matching ``Content-Type``
suitable for a ``GET /metrics`` handler. :func:`record_action` is the
single write path — failures are swallowed so a broken metrics backend
can never abort a real action.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest

from automation_file.logging_config import file_automation_logger

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


def record_action(action: str, duration_seconds: float, ok: bool) -> None:
    """Record one action execution. Never raises."""
    status = "ok" if ok else "error"
    try:
        ACTION_COUNT.labels(action=action, status=status).inc()
        ACTION_DURATION.labels(action=action).observe(max(0.0, float(duration_seconds)))
    except Exception as err:  # pragma: no cover - defensive
        file_automation_logger.error("metrics.record_action failed: %r", err)


def render() -> tuple[bytes, str]:
    """Return ``(payload, content_type)`` for a ``/metrics`` response."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
