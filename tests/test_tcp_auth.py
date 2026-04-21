"""Tests for the TCP server's optional shared-secret authentication."""
from __future__ import annotations

import socket

from automation_file.core.action_executor import executor
from automation_file.server.tcp_server import start_autocontrol_socket_server


_END_MARKER = b"Return_Data_Over_JE\n"


def _send_and_read(host: str, port: int, payload: bytes) -> bytes:
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


def _ensure_echo() -> None:
    if "test_tcp_echo" not in executor.registry:
        executor.registry.register("test_tcp_echo", lambda value: value)


def test_tcp_server_rejects_missing_auth() -> None:
    _ensure_echo()
    server = start_autocontrol_socket_server(
        host="127.0.0.1", port=0, shared_secret="s3cr3t",
    )
    host, port = server.server_address
    try:
        response = _send_and_read(host, port, b'[["test_tcp_echo", {"value": "hi"}]]')
        assert b"auth error" in response
    finally:
        server.shutdown()


def test_tcp_server_accepts_valid_auth() -> None:
    _ensure_echo()
    server = start_autocontrol_socket_server(
        host="127.0.0.1", port=0, shared_secret="s3cr3t",
    )
    host, port = server.server_address
    try:
        response = _send_and_read(
            host, port, b'AUTH s3cr3t\n[["test_tcp_echo", {"value": "hi"}]]',
        )
        assert b"hi" in response
    finally:
        server.shutdown()


def test_tcp_server_rejects_bad_secret() -> None:
    _ensure_echo()
    server = start_autocontrol_socket_server(
        host="127.0.0.1", port=0, shared_secret="s3cr3t",
    )
    host, port = server.server_address
    try:
        response = _send_and_read(
            host, port, b'AUTH wrong\n[["test_tcp_echo", {"value": 1}]]',
        )
        assert b"auth error" in response
    finally:
        server.shutdown()
