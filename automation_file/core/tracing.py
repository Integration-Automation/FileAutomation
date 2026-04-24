"""OpenTelemetry tracing bridge for the action executor and DAG runner.

Callers opt in by calling :func:`init_tracing` once at startup (or the
``FA_tracing_init`` action) with a service name. Every subsequent action
dispatch through ``ActionExecutor._execute_event`` and every DAG node run
through ``dag_executor._run_action`` is wrapped in a span named
``automation_file.action`` with the action name on the ``fa.action`` attribute.

If ``init_tracing`` has not been called, :func:`action_span` returns a
cheap no-op context manager — the executor always pays exactly one
``trace.get_tracer`` call and nothing else, so tracing is zero-overhead
for callers who never enable it.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from automation_file.exceptions import TracingException
from automation_file.logging_config import file_automation_logger

_TRACER_NAME = "automation_file"
# Mutable container so helpers don't need ``global`` to flip the flag.
_state: dict[str, bool] = {"initialised": False}


def init_tracing(
    service_name: str = "automation_file",
    *,
    exporter: SpanExporter | None = None,
    resource_attributes: dict[str, Any] | None = None,
) -> bool:
    """Install a global :class:`TracerProvider` and register ``exporter``.

    Returns True on the first call, False if tracing is already initialised.
    ``exporter`` defaults to a :class:`SpanExporter` that discards everything —
    so that spans are created (and tooling can inspect them) without requiring
    the caller to wire up a backend. Pass an OTLP / Jaeger / Zipkin exporter
    from the matching ``opentelemetry-exporter-*`` package when you want spans
    to leave the process.
    """
    if _state["initialised"]:
        return False
    attributes: dict[str, Any] = {SERVICE_NAME: service_name}
    if resource_attributes:
        attributes.update(resource_attributes)
    resource = Resource.create(attributes)
    provider = TracerProvider(resource=resource)
    active_exporter = exporter if exporter is not None else _NullExporter()
    provider.add_span_processor(BatchSpanProcessor(active_exporter))
    try:
        trace.set_tracer_provider(provider)
    except Exception as err:  # pylint: disable=broad-exception-caught
        raise TracingException(f"cannot install tracer provider: {err}") from err
    _state["initialised"] = True
    file_automation_logger.info("tracing: initialised (service=%s)", service_name)
    return True


def is_initialised() -> bool:
    """Return True when :func:`init_tracing` has already run."""
    return _state["initialised"]


@contextmanager
def action_span(action_name: str, attributes: dict[str, Any] | None = None) -> Iterator[None]:
    """Open a span named ``automation_file.action`` for ``action_name``.

    When tracing is not initialised this is a no-op — the executor can wrap
    every action unconditionally without paying for an unused tracer on the
    hot path.
    """
    if not _state["initialised"]:
        yield
        return
    tracer = trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span("automation_file.action") as span:
        span.set_attribute("fa.action", action_name)
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield


def _shutdown_for_tests() -> None:
    """Reset module state so a fresh :func:`init_tracing` call works again.

    OpenTelemetry's :func:`trace.set_tracer_provider` is a one-shot guarded
    by an internal ``Once`` sentinel — repeated calls are silently ignored.
    Tests need to flip tracing off and back on, so we reach into the
    ``opentelemetry.trace`` module and reset the sentinel. This is the
    conventional pattern used by the opentelemetry-python test suite itself.
    """
    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    if callable(shutdown):
        # Exporter shutdown is best-effort when a test already tore it down.
        with contextlib.suppress(Exception):
            shutdown()
    # pylint: disable=protected-access  # test-only reset of OTel's Once sentinel
    once_cls = type(trace._TRACER_PROVIDER_SET_ONCE)  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER_SET_ONCE = once_cls()  # type: ignore[attr-defined]
    trace._TRACER_PROVIDER = None  # type: ignore[attr-defined]
    _state["initialised"] = False


class _NullExporter(SpanExporter):
    """Default exporter: accept spans, discard them."""

    def export(self, spans: Any) -> Any:  # type: ignore[override]
        from opentelemetry.sdk.trace.export import SpanExportResult

        del spans
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:  # type: ignore[override]
        return None
