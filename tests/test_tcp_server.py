"""Tests for automation_file.server.tcp_server."""

from __future__ import annotations

import json
import socket

import pytest

from automation_file.server.tcp_server import (
    _END_MARKER,
    start_autocontrol_socket_server,
)
from tests._insecure_fixtures import ipv4

_HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((_HOST, 0))
        return sock.getsockname()[1]


def _recv_until_marker(sock: socket.socket, timeout: float = 5.0) -> bytes:
    sock.settimeout(timeout)
    buffer = bytearray()
    while _END_MARKER not in buffer:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buffer.extend(chunk)
    return bytes(buffer)


@pytest.fixture(name="server")
def _server():
    port = _free_port()
    srv = start_autocontrol_socket_server(host=_HOST, port=port)
    try:
        yield srv, port
    finally:
        srv.shutdown()
        srv.server_close()


def test_server_executes_action(server) -> None:
    _, port = server
    payload = json.dumps([["FA_create_dir", {"dir_path": "server_smoke_dir"}]])
    with socket.create_connection((_HOST, port), timeout=5) as sock:
        sock.sendall(payload.encode("utf-8"))
        data = _recv_until_marker(sock)
    assert _END_MARKER in data

    # cleanup
    import shutil

    shutil.rmtree("server_smoke_dir", ignore_errors=True)


def test_server_reports_bad_json(server) -> None:
    _, port = server
    with socket.create_connection((_HOST, port), timeout=5) as sock:
        sock.sendall(b"this is not json")
        data = _recv_until_marker(sock)
    assert b"json error" in data


def test_start_server_rejects_non_loopback() -> None:
    non_loopback = ipv4(8, 8, 8, 8)
    with pytest.raises(ValueError):
        start_autocontrol_socket_server(host=non_loopback, port=_free_port())


def test_start_server_allows_non_loopback_when_opted_in() -> None:
    # Bind to a port that's guaranteed local but simulate the opt-in path.
    # We re-bind to 127.0.0.1 under allow_non_loopback=True to exercise the code
    # path without actually opening the machine to the network.
    srv = start_autocontrol_socket_server(host=_HOST, port=_free_port(), allow_non_loopback=True)
    try:
        assert srv.server_address[0] == _HOST
    finally:
        srv.shutdown()
        srv.server_close()
