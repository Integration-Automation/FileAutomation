"""The TCP server's wire replies, byte for byte (kept when the server moves onto je_action_core)."""

from __future__ import annotations

import json
import secrets
import socket
import time

import pytest

from automation_file.core.action_executor import executor
from automation_file.server.action_acl import ActionACL
from automation_file.server.tcp_server import start_autocontrol_socket_server

END = b"Return_Data_Over_JE\n"
SECRET = secrets.token_hex(16)


def _wire_echo(value: str) -> str:
    return value


executor.registry.register("test_tcp_wire_echo", _wire_echo)


def _ask(port: int, payload: bytes) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(payload)
        sock.shutdown(socket.SHUT_WR)  # end of request, so an empty one is seen as such
        chunks = []
        chunk = sock.recv(4096)
        while chunk:  # the server closes the connection after its reply
            chunks.append(chunk)
            chunk = sock.recv(4096)
    return b"".join(chunks)


@pytest.fixture(name="serve")
def _serve():
    servers = []

    def start(**kwargs):
        server = start_autocontrol_socket_server(host="127.0.0.1", port=0, **kwargs)
        servers.append(server)
        return server, server.server_address[1]

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _echo(value: str) -> bytes:
    return json.dumps([["test_tcp_wire_echo", {"value": value}]]).encode()


def test_records_are_key_arrow_value_lines(serve) -> None:
    _, port = serve()
    expected = b"execute[0]: ['test_tcp_wire_echo', {'value': 'hi'}] -> hi\n" + END
    assert _ask(port, _echo("hi")) == expected


def test_bad_json(serve) -> None:
    _, port = serve()
    reply = _ask(port, b"not json")
    assert (
        reply == b"json error: JSONDecodeError('Expecting value: line 1 column 1 (char 0)')\n" + END
    )


def test_undecodable_bytes(serve) -> None:
    _, port = serve()
    reply = _ask(port, b"\xff\xfe")
    assert reply.startswith(b"decode error: UnicodeDecodeError(")
    assert reply.endswith(b"\n" + END)


def test_empty_request_gets_no_reply(serve) -> None:
    _, port = serve()
    assert _ask(port, b"") == b""


def test_quit_replies_and_stops(serve) -> None:
    server, port = serve()
    assert _ask(port, b"quit_server") == b"server shutting down\n"
    deadline = time.monotonic() + 5
    while not server.close_flag and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.close_flag


@pytest.mark.parametrize(
    "payload",
    [b'[["test_tcp_wire_echo", ["x"]]]', b"AUTH wrong\n[]", b"AUTH " + SECRET.encode()],
)
def test_auth_failures(serve, payload: bytes) -> None:
    _, port = serve(shared_secret=SECRET)
    assert _ask(port, payload) == b"auth error\n" + END


def test_auth_success_runs_the_payload(serve) -> None:
    _, port = serve(shared_secret=SECRET)
    reply = _ask(port, b"AUTH " + SECRET.encode() + b"\n" + _echo("ok"))
    assert reply == b"execute[0]: ['test_tcp_wire_echo', {'value': 'ok'}] -> ok\n" + END


def test_acl_refusal(serve) -> None:
    _, port = serve(action_acl=ActionACL.build(denied=["test_tcp_wire_echo"]))
    reply = _ask(port, _echo("no"))
    assert reply.startswith(b"forbidden: ")
    assert reply.endswith(b"\n" + END)
