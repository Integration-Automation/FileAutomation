"""Tests for the /healthz /readyz /openapi.json /progress endpoints."""
# pylint: disable=cyclic-import

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import urllib.request

import pytest

from automation_file.core.action_executor import executor
from automation_file.server._websocket import compute_accept_key
from automation_file.server.http_server import start_http_action_server


def _ensure_echo_registered() -> None:
    if "test_http_echo" not in executor.registry:
        executor.registry.register("test_http_echo", lambda value: value)


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, str]:
    request = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=3) as resp:  # nosec B310
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8")


def test_healthz_returns_ok() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        status, body = _get(f"http://{host}:{port}/healthz")
        assert status == 200
        assert json.loads(body) == {"status": "ok"}
    finally:
        server.shutdown()


def test_readyz_returns_ok_with_registry() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        status, body = _get(f"http://{host}:{port}/readyz")
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "ready"
    finally:
        server.shutdown()


def test_openapi_describes_endpoints() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        status, body = _get(f"http://{host}:{port}/openapi.json")
        assert status == 200
        spec = json.loads(body)
        assert spec["openapi"].startswith("3.")
        for path in ("/actions", "/healthz", "/readyz", "/progress"):
            assert path in spec["paths"]
    finally:
        server.shutdown()


def test_progress_without_upgrade_returns_426() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        status, _ = _get(f"http://{host}:{port}/progress")
        assert status == 426
    finally:
        server.shutdown()


def test_progress_websocket_handshake_and_frame() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    ws_key = base64.b64encode(os.urandom(16)).decode("ascii")
    expected_accept = compute_accept_key(ws_key)

    raw = socket.create_connection((host, port), timeout=3)
    try:
        request = (
            f"GET /progress HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        raw.sendall(request.encode("ascii"))
        raw.settimeout(3)

        header = b""
        while b"\r\n\r\n" not in header:
            chunk = raw.recv(1024)
            if not chunk:
                break
            header += chunk
        headers_text, _, remainder = header.partition(b"\r\n\r\n")
        assert b"101" in headers_text.split(b"\r\n", 1)[0]
        assert f"Sec-WebSocket-Accept: {expected_accept}".encode() in headers_text

        frame = remainder
        while len(frame) < 2:
            frame += raw.recv(1024)
        assert frame[0] == 0x81  # FIN + text
        length = frame[1] & 0x7F
        if length == 126:
            while len(frame) < 4:
                frame += raw.recv(1024)
            length = struct.unpack(">H", frame[2:4])[0]
            offset = 4
        elif length == 127:
            while len(frame) < 10:
                frame += raw.recv(1024)
            length = struct.unpack(">Q", frame[2:10])[0]
            offset = 10
        else:
            offset = 2
        while len(frame) < offset + length:
            frame += raw.recv(4096)
        payload = json.loads(frame[offset : offset + length].decode("utf-8"))
        assert "progress" in payload
    finally:
        raw.close()
        server.shutdown()


def test_progress_websocket_rejects_bad_secret() -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0, shared_secret="s3cr3t")
    host, port = server.server_address
    ws_key = base64.b64encode(os.urandom(16)).decode("ascii")

    raw = socket.create_connection((host, port), timeout=3)
    try:
        request = (
            f"GET /progress HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {ws_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"Authorization: Bearer wrong\r\n"
            f"\r\n"
        )
        raw.sendall(request.encode("ascii"))
        raw.settimeout(3)
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = raw.recv(1024)
            if not chunk:
                break
            header += chunk
        assert b"401" in header.split(b"\r\n", 1)[0]
    finally:
        raw.close()
        server.shutdown()


@pytest.mark.parametrize("path", ["/notfound", "/actions/extra"])
def test_unknown_get_paths_404(path: str) -> None:
    _ensure_echo_registered()
    server = start_http_action_server(host="127.0.0.1", port=0)
    host, port = server.server_address
    try:
        status, _ = _get(f"http://{host}:{port}{path}")
        assert status == 404
    finally:
        server.shutdown()
