"""Tests for :class:`HTTPActionClient`."""
# pylint: disable=cyclic-import

from __future__ import annotations

import pytest

from automation_file.client import HTTPActionClient, HTTPActionClientException
from automation_file.core.action_executor import executor
from automation_file.server.action_acl import ActionACL
from automation_file.server.http_server import start_http_action_server


def _ensure_echo_registered() -> None:
    if "test_client_echo" not in executor.registry:
        executor.registry.register("test_client_echo", lambda value: value)


def _base_url(server) -> str:
    host, port = server.server_address
    return f"http://{host}:{port}"


def test_client_executes_action_round_trip() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0)
    try:
        with HTTPActionClient(_base_url(server)) as client:
            result = client.execute([["test_client_echo", {"value": "hello"}]])
        assert isinstance(result, dict)
        assert any(value == "hello" for value in result.values())
    finally:
        server.shutdown()


def test_client_sends_bearer_token_when_configured() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0, shared_secret="topsecret")
    try:
        with HTTPActionClient(_base_url(server), shared_secret="topsecret") as client:
            result = client.execute([["test_client_echo", {"value": 42}]])
        assert any(value == 42 for value in result.values())
    finally:
        server.shutdown()


def test_client_unauthorized_when_missing_secret() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0, shared_secret="topsecret")
    try:
        with (
            HTTPActionClient(_base_url(server)) as client,
            pytest.raises(HTTPActionClientException, match="unauthorized"),
        ):
            client.execute([["test_client_echo", {"value": 1}]])
    finally:
        server.shutdown()


def test_client_forbidden_when_denied_by_acl() -> None:
    _ensure_echo_registered()
    acl = ActionACL.build(denied=["test_client_echo"])
    server = start_http_action_server(host="127.0.0.1", port=0, action_acl=acl)
    try:
        with (
            HTTPActionClient(_base_url(server)) as client,
            pytest.raises(HTTPActionClientException, match="forbidden"),
        ):
            client.execute([["test_client_echo", {"value": 1}]])
    finally:
        server.shutdown()


def test_client_rejects_bad_action_type() -> None:
    client = HTTPActionClient("http://127.0.0.1:1")
    try:
        with pytest.raises(HTTPActionClientException, match="list or dict"):
            client.execute("not-a-list")  # type: ignore[arg-type]
    finally:
        client.close()


def test_client_requires_base_url() -> None:
    with pytest.raises(HTTPActionClientException, match="non-empty"):
        HTTPActionClient("")


def test_client_connection_error_wraps_request_exception() -> None:
    # Port 1 is unlikely to have a server — connect should fail quickly.
    client = HTTPActionClient("http://127.0.0.1:1", timeout=1.0)
    try:
        with pytest.raises(HTTPActionClientException, match="failed"):
            client.execute([["noop"]])
    finally:
        client.close()


def test_client_ping_reaches_running_server() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0)
    try:
        with HTTPActionClient(_base_url(server)) as client:
            assert client.ping() is True
    finally:
        server.shutdown()


def test_client_ping_returns_false_for_dead_endpoint() -> None:
    client = HTTPActionClient("http://127.0.0.1:1", timeout=1.0)
    try:
        assert client.ping() is False
    finally:
        client.close()


def test_client_surfaces_via_facade() -> None:
    import automation_file

    assert automation_file.HTTPActionClient is HTTPActionClient
    assert automation_file.HTTPActionClientException is HTTPActionClientException
