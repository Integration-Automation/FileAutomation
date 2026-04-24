"""Tests for the Prometheus metrics exporter."""

# pylint: disable=protected-access  # prometheus_client exposes counter state via ._value

from __future__ import annotations

import urllib.request

import pytest

from automation_file import (
    ACTION_COUNT,
    execute_action,
    record_action,
    render_metrics,
    start_metrics_server,
)
from automation_file.core.action_executor import executor
from tests._insecure_fixtures import insecure_url, ipv4


def _register_probes() -> None:
    if "test_metric_ok" not in executor.registry:
        executor.registry.register("test_metric_ok", lambda: "ok")
    if "test_metric_fail" not in executor.registry:

        def _boom() -> None:
            raise RuntimeError("boom")

        executor.registry.register("test_metric_fail", _boom)


def test_record_action_increments_counter() -> None:
    before = ACTION_COUNT.labels(action="unit.test", status="ok")._value.get()
    record_action("unit.test", 0.01, ok=True)
    after = ACTION_COUNT.labels(action="unit.test", status="ok")._value.get()
    assert after == before + 1


def test_record_action_clamps_negative_duration() -> None:
    # Must not raise.
    record_action("unit.clamp", -5.0, ok=True)


def test_render_metrics_content_type() -> None:
    payload, content_type = render_metrics()
    assert content_type.startswith("text/plain")
    assert b"automation_file_actions_total" in payload


def test_execute_action_increments_ok_counter() -> None:
    _register_probes()
    before = ACTION_COUNT.labels(action="test_metric_ok", status="ok")._value.get()
    execute_action([["test_metric_ok"]])
    after = ACTION_COUNT.labels(action="test_metric_ok", status="ok")._value.get()
    assert after == before + 1


def test_execute_action_increments_error_counter() -> None:
    _register_probes()
    before = ACTION_COUNT.labels(action="test_metric_fail", status="error")._value.get()
    execute_action([["test_metric_fail"]])
    after = ACTION_COUNT.labels(action="test_metric_fail", status="error")._value.get()
    assert after == before + 1


def test_metrics_server_serves_metrics_endpoint() -> None:
    _register_probes()
    execute_action([["test_metric_ok"]])
    server = start_metrics_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        url = insecure_url("http", f"{host}:{port}/metrics")
        with urllib.request.urlopen(url, timeout=3) as resp:  # nosec B310 - loopback test server
            body = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "automation_file_actions_total" in body
    finally:
        server.shutdown()


def test_metrics_server_returns_404_for_other_paths() -> None:
    server = start_metrics_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        url = insecure_url("http", f"{host}:{port}/other")
        with (
            pytest.raises(urllib.error.HTTPError) as info,
            # nosec B310 - loopback test server
            urllib.request.urlopen(url, timeout=3),  # nosec B310
        ):
            pass
        assert info.value.code == 404
    finally:
        server.shutdown()


def test_metrics_server_rejects_non_loopback() -> None:
    non_loopback = ipv4(8, 8, 8, 8)
    with pytest.raises(ValueError):
        start_metrics_server(host=non_loopback, port=0)
