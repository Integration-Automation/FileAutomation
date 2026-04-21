"""TCP socket server that executes JSON action payloads.

Binds to localhost by default. Explicitly rejects non-loopback binds unless
``allow_non_loopback`` is True because the server accepts arbitrary action
names from clients and should not be exposed to the network by accident.
"""
from __future__ import annotations

import ipaddress
import json
import socket
import socketserver
import sys
import threading
from typing import Any

from automation_file.core.action_executor import execute_action
from automation_file.logging_config import file_automation_logger

_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 9943
_RECV_BYTES = 8192
_END_MARKER = b"Return_Data_Over_JE\n"
_QUIT_COMMAND = "quit_server"


class _TCPServerHandler(socketserver.StreamRequestHandler):
    """One instance per connection; dispatches a single JSON payload."""

    def handle(self) -> None:
        raw = self.request.recv(_RECV_BYTES)
        if not raw:
            return
        try:
            command_string = raw.strip().decode("utf-8")
        except UnicodeDecodeError as error:
            self._send_line(f"decode error: {error!r}")
            self._send_bytes(_END_MARKER)
            return

        file_automation_logger.info("tcp_server: recv %s", command_string)
        if command_string == _QUIT_COMMAND:
            self.server.close_flag = True  # type: ignore[attr-defined]
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            self._send_line("server shutting down")
            return

        try:
            payload = json.loads(command_string)
            results = execute_action(payload)
            for key, value in results.items():
                self._send_line(f"{key} -> {value}")
        except json.JSONDecodeError as error:
            self._send_line(f"json error: {error!r}")
        except Exception as error:  # pylint: disable=broad-except
            file_automation_logger.error("tcp_server handler: %r", error)
            self._send_line(f"execution error: {error!r}")
        finally:
            self._send_bytes(_END_MARKER)

    def _send_line(self, text: str) -> None:
        self._send_bytes(text.encode("utf-8") + b"\n")

    def _send_bytes(self, data: bytes) -> None:
        try:
            self.request.sendall(data)
        except OSError as error:
            file_automation_logger.error("tcp_server sendall: %r", error)


class TCPActionServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded TCP server with an explicit close flag."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], request_handler_class: type) -> None:
        super().__init__(server_address, request_handler_class)
        self.close_flag: bool = False


def _ensure_loopback(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as error:
        raise ValueError(f"cannot resolve host: {host}") from error
    for info in infos:
        ip_obj = ipaddress.ip_address(info[4][0])
        if not ip_obj.is_loopback:
            raise ValueError(
                f"host {host} resolves to non-loopback {ip_obj}; pass allow_non_loopback=True "
                "if exposure is intentional"
            )


def start_autocontrol_socket_server(
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    allow_non_loopback: bool = False,
) -> TCPActionServer:
    """Start the action-dispatching TCP server on a background thread."""
    if not allow_non_loopback:
        _ensure_loopback(host)
    server = TCPActionServer((host, port), _TCPServerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    file_automation_logger.info("tcp_server: listening on %s:%d", host, port)
    return server


def main(argv: list[str] | None = None) -> Any:
    """Entry point for ``python -m automation_file.server.tcp_server``."""
    args = argv if argv is not None else sys.argv[1:]
    host = args[0] if len(args) >= 1 else _DEFAULT_HOST
    port = int(args[1]) if len(args) >= 2 else _DEFAULT_PORT
    return start_autocontrol_socket_server(host=host, port=port)


if __name__ == "__main__":
    main()
