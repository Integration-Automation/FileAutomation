"""Tests for automation_file.core.tracing."""

from __future__ import annotations

from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from automation_file import (
    action_span,
    execute_action,
    executor,
    init_tracing,
)
from automation_file.core import tracing
from automation_file.exceptions import TracingException


class _CapturingExporter(SpanExporter):
    """Collect spans in memory so tests can assert on them."""

    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []
        self._shutdown = False

    def export(self, spans: Any) -> Any:
        if not self._shutdown:
            self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        self._shutdown = True


@pytest.fixture(name="exporter", scope="module")
def _exporter() -> Any:
    """Initialise tracing once per module.

    OpenTelemetry's ``trace.set_tracer_provider`` is one-shot per process,
    so we can't re-initialise between tests. A module-scoped fixture keeps
    all tracing tests sharing the same exporter.
    """
    # Force a clean state on entry in case another test suite touched tracing.
    tracing._shutdown_for_tests()
    exporter = _CapturingExporter()
    init_tracing("test-service", exporter=exporter)
    yield exporter
    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        shutdown()


def _flush() -> None:
    """Force any pending batch-exported spans out to the exporter."""
    provider = trace.get_tracer_provider()
    force_flush = getattr(provider, "force_flush", None)
    if callable(force_flush):
        force_flush()


def test_is_initialised_true_after_fixture(exporter: _CapturingExporter) -> None:
    del exporter  # fixture side effect only
    assert tracing.is_initialised() is True


def test_action_span_records_attributes(exporter: _CapturingExporter) -> None:
    before = len(exporter.spans)
    with action_span("probe", {"answer": 42}):
        pass
    _flush()
    new_spans = exporter.spans[before:]
    assert any(s.name == "automation_file.action" for s in new_spans)
    probe = next(s for s in new_spans if s.name == "automation_file.action")
    assert probe.attributes is not None
    assert probe.attributes["fa.action"] == "probe"
    assert probe.attributes["answer"] == 42


def test_init_tracing_returns_false_on_second_call(exporter: _CapturingExporter) -> None:
    del exporter
    assert init_tracing("svc") is False


def test_executor_wraps_actions_in_span(exporter: _CapturingExporter) -> None:
    before = len(exporter.spans)
    executor.registry.register("test_traced_echo", lambda value: value)
    execute_action([["test_traced_echo", {"value": "hi"}]])
    _flush()
    action_names = [
        span.attributes.get("fa.action")
        for span in exporter.spans[before:]
        if span.attributes is not None
    ]
    assert "test_traced_echo" in action_names


def test_action_span_noop_when_uninitialised() -> None:
    # Capture current state, drop to uninitialised, verify no-op, restore.
    previous = tracing._state["initialised"]
    tracing._state["initialised"] = False
    try:
        with action_span("probe"):
            pass  # must not raise
        assert tracing.is_initialised() is False
    finally:
        tracing._state["initialised"] = previous


def test_tracing_exception_is_exported() -> None:
    assert issubclass(TracingException, Exception)
