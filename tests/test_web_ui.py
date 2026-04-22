"""Tests for the HTMX Web UI server."""
# pylint: disable=cyclic-import

from __future__ import annotations

import urllib.request

import pytest

from automation_file.core.action_executor import executor
from automation_file.core.progress import progress_registry
from automation_file.server.web_ui import start_web_ui
from tests._insecure_fixtures import insecure_url, ipv4


def _loopback(host: str, port: int, path: str = "") -> str:
    return insecure_url("http", f"{host}:{port}{path}")


def _ensure_echo_registered() -> None:
    if "test_webui_echo" not in executor.registry:
        executor.registry.register("test_webui_echo", lambda value: value)


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, str]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=3) as resp:  # nosec B310
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def test_index_returns_html_with_htmx_script() -> None:
    _ensure_echo_registered()
    server = start_web_ui(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        status, body = _get(_loopback(host, port, "/"))
        assert status == 200
        assert "htmx.org" in body
        assert 'hx-get="/ui/progress"' in body
        assert 'hx-get="/ui/registry"' in body
        assert 'hx-get="/ui/health"' in body
    finally:
        server.shutdown()


def test_registry_fragment_lists_actions() -> None:
    _ensure_echo_registered()
    server = start_web_ui(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        status, body = _get(_loopback(host, port, "/ui/registry"))
        assert status == 200
        assert "<ul>" in body or "registry empty" in body
        assert "test_webui_echo" in body
    finally:
        server.shutdown()


def test_progress_fragment_reflects_registry() -> None:
    _ensure_echo_registered()
    reporter, _ = progress_registry.create("webui_probe", total=100)
    reporter.update(50)
    server = start_web_ui(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        status, body = _get(_loopback(host, port, "/ui/progress"))
        assert status == 200
        assert "webui_probe" in body
        assert "50.0%" in body
    finally:
        progress_registry.forget("webui_probe")
        server.shutdown()


def test_health_fragment_contains_registry_size() -> None:
    _ensure_echo_registered()
    server = start_web_ui(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        status, body = _get(_loopback(host, port, "/ui/health"))
        assert status == 200
        assert "registry size" in body
        assert "alive" in body
    finally:
        server.shutdown()


def test_rejects_non_loopback() -> None:
    with pytest.raises(ValueError):
        start_web_ui(host=ipv4(8, 8, 8, 8), port=0)


def test_shared_secret_required_when_set() -> None:
    _ensure_echo_registered()
    server = start_web_ui(host="127.0.0.1", port=0, shared_secret="s3cr3t")
    host, port = server.server_address
    try:
        status, _ = _get(_loopback(host, port, "/"))
        assert status == 401
        status, body = _get(_loopback(host, port, "/"), headers={"Authorization": "Bearer s3cr3t"})
        assert status == 200
        assert "Bearer s3cr3t" in body  # echoed into hx-headers for polling
    finally:
        server.shutdown()


def test_unknown_path_returns_404() -> None:
    _ensure_echo_registered()
    server = start_web_ui(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        status, _ = _get(_loopback(host, port, "/nope"))
        assert status == 404
    finally:
        server.shutdown()
