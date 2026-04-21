"""TCP + HTTP server ACL integration tests."""

from __future__ import annotations

import json
import socket
from http.client import HTTPConnection

from automation_file import (
    ActionACL,
    start_autocontrol_socket_server,
    start_http_action_server,
)
from automation_file.core.action_executor import executor

_END_MARKER = b"Return_Data_Over_JE\n"


def _ensure_echo() -> None:
    if "test_acl_echo" not in executor.registry:
        executor.registry.register("test_acl_echo", lambda value=0: value)
    if "test_acl_forbidden" not in executor.registry:
        executor.registry.register("test_acl_forbidden", lambda: "nope")


def _tcp_send(host: str, port: int, payload: bytes) -> bytes:
    with socket.create_connection((host, port), timeout=3) as sock:
        sock.sendall(payload)
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            chunks.append(chunk)
            if _END_MARKER in b"".join(chunks):
                break
        return b"".join(chunks)


def test_tcp_server_rejects_denied_action() -> None:
    _ensure_echo()
    acl = ActionACL.build(denied=["test_acl_forbidden"])
    server = start_autocontrol_socket_server(host="127.0.0.1", port=0, action_acl=acl)
    host, port = server.server_address
    try:
        response = _tcp_send(host, port, b'[["test_acl_forbidden"]]')
        assert b"forbidden" in response
        response_ok = _tcp_send(host, port, b'[["test_acl_echo", {"value": 7}]]')
        assert b"7" in response_ok
    finally:
        server.shutdown()


def test_tcp_server_allowlist_rejects_outside_actions() -> None:
    _ensure_echo()
    acl = ActionACL.build(allowed=["test_acl_echo"])
    server = start_autocontrol_socket_server(host="127.0.0.1", port=0, action_acl=acl)
    host, port = server.server_address
    try:
        response = _tcp_send(host, port, b'[["test_acl_forbidden"]]')
        assert b"forbidden" in response
    finally:
        server.shutdown()


def test_http_server_rejects_denied_action_with_403() -> None:
    _ensure_echo()
    acl = ActionACL.build(denied=["test_acl_forbidden"])
    server = start_http_action_server(host="127.0.0.1", port=0, action_acl=acl)
    host, port = server.server_address
    try:
        body = json.dumps([["test_acl_forbidden"]]).encode("utf-8")
        conn = HTTPConnection(host, port, timeout=3)
        conn.request(
            "POST",
            "/actions",
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        response = conn.getresponse()
        assert response.status == 403
        payload = json.loads(response.read().decode("utf-8"))
        assert "not permitted" in payload["error"]
        conn.close()
    finally:
        server.shutdown()


def test_http_server_allows_permitted_action() -> None:
    _ensure_echo()
    acl = ActionACL.build(allowed=["test_acl_echo"])
    server = start_http_action_server(host="127.0.0.1", port=0, action_acl=acl)
    host, port = server.server_address
    try:
        body = json.dumps([["test_acl_echo", {"value": 42}]]).encode("utf-8")
        conn = HTTPConnection(host, port, timeout=3)
        conn.request(
            "POST",
            "/actions",
            body=body,
            headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        )
        response = conn.getresponse()
        assert response.status == 200
        payload = json.loads(response.read().decode("utf-8"))
        assert 42 in payload.values()
        conn.close()
    finally:
        server.shutdown()
