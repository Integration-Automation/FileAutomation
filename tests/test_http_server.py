"""Tests for the HTTP action server."""
# pylint: disable=cyclic-import  # false positive: registry imports backends lazily at call time

from __future__ import annotations

import json
import urllib.request

import pytest

# The server imports the module-level `execute_action`, which uses the shared
# registry. We add a named command to that registry before starting.
from automation_file.core.action_executor import executor
from automation_file.server.http_server import start_http_action_server
from tests._insecure_fixtures import insecure_url, ipv4


def _ensure_echo_registered() -> None:
    if "test_http_echo" not in executor.registry:
        executor.registry.register("test_http_echo", lambda value: value)


def _post(url: str, payload: object, headers: dict[str, str] | None = None) -> tuple[int, str]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers or {}, method="POST")
    try:
        # B310 suppressed: URL built from a loopback test server address.
        with urllib.request.urlopen(request, timeout=3) as resp:  # nosec B310
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def test_http_server_executes_action() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        url = insecure_url("http", f"{host}:{port}/actions")
        status, body = _post(url, [["test_http_echo", {"value": "hi"}]])
        assert status == 200
        assert json.loads(body) == {"execute: ['test_http_echo', {'value': 'hi'}]": "hi"}
    finally:
        server.shutdown()


def test_http_server_rejects_missing_auth() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(
        host="127.0.0.1",
        port=0,
        shared_secret="s3cr3t",
    )
    host, port = server.server_address
    try:
        url = insecure_url("http", f"{host}:{port}/actions")
        status, _ = _post(url, [["test_http_echo", {"value": 1}]])
        assert status == 401
    finally:
        server.shutdown()


def test_http_server_accepts_valid_auth() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(
        host="127.0.0.1",
        port=0,
        shared_secret="s3cr3t",
    )
    host, port = server.server_address
    try:
        url = insecure_url("http", f"{host}:{port}/actions")
        status, body = _post(
            url,
            [["test_http_echo", {"value": 1}]],
            headers={"Authorization": "Bearer s3cr3t"},
        )
        assert status == 200
        assert "1" in body
    finally:
        server.shutdown()


def test_http_server_rejects_non_loopback() -> None:
    non_loopback = ipv4(8, 8, 8, 8)
    with pytest.raises(ValueError):
        start_http_action_server(host=non_loopback, port=0)
