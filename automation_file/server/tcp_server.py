"""TCP socket server that executes JSON action payloads.

Binds to localhost by default. Explicitly rejects non-loopback binds unless
``allow_non_loopback`` is True because the server accepts arbitrary action
names from clients and should not be exposed to the network by accident.

When a ``shared_secret`` is supplied the server requires each connection to
begin with ``AUTH <secret>\\n`` before the JSON payload. This is the minimum
bar for exposing the server beyond loopback; use a TLS-terminating proxy for
anything resembling production.
"""

from __future__ import annotations

import hmac
import json
import socketserver
import sys
import threading
from typing import Any

from automation_file.core.action_executor import execute_action
from automation_file.exceptions import TCPAuthException
from automation_file.logging_config import file_automation_logger
from automation_file.server.action_acl import ActionACL, ActionNotPermittedException
from automation_file.server.network_guards import ensure_loopback

_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 9943
_RECV_BYTES = 8192
_END_MARKER = b"Return_Data_Over_JE\n"
_QUIT_COMMAND = "quit_server"
_AUTH_PREFIX = "AUTH "


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

        try:
            command_string = self._enforce_auth(command_string)
        except TCPAuthException as error:
            file_automation_logger.warning("tcp_server auth: %r", error)
            self._send_line("auth error")
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
            acl: ActionACL | None = getattr(self.server, "action_acl", None)
            if acl is not None:
                acl.enforce(payload)
            results = execute_action(payload)
            for key, value in results.items():
                self._send_line(f"{key} -> {value}")
        except json.JSONDecodeError as error:
            self._send_line(f"json error: {error!r}")
        except ActionNotPermittedException as error:
            file_automation_logger.warning("tcp_server acl: %r", error)
            self._send_line(f"forbidden: {error}")
        except Exception as error:  # pylint: disable=broad-except
            file_automation_logger.error("tcp_server handler: %r", error)
            self._send_line(f"execution error: {error!r}")
        finally:
            self._send_bytes(_END_MARKER)

    def _enforce_auth(self, command_string: str) -> str:
        secret: str | None = getattr(self.server, "shared_secret", None)
        if not secret:
            return command_string
        head, _, rest = command_string.partition("\n")
        if not head.startswith(_AUTH_PREFIX):
            raise TCPAuthException("missing AUTH header")
        supplied = head[len(_AUTH_PREFIX) :].strip()
        if not hmac.compare_digest(supplied, secret):
            raise TCPAuthException("bad shared secret")
        if not rest:
            raise TCPAuthException("empty payload after AUTH")
        return rest

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

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type,
        shared_secret: str | None = None,
        action_acl: ActionACL | None = None,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.close_flag: bool = False
        self.shared_secret: str | None = shared_secret
        self.action_acl: ActionACL | None = action_acl


def start_autocontrol_socket_server(
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    allow_non_loopback: bool = False,
    shared_secret: str | None = None,
    action_acl: ActionACL | None = None,
) -> TCPActionServer:
    """Start the action-dispatching TCP server on a background thread.

    ``shared_secret`` turns on per-connection authentication: clients must send
    ``AUTH <secret>\\n`` followed by the JSON payload. Binding to a non-loopback
    address without a shared secret is strongly discouraged. ``action_acl``
    filters each incoming payload; any referenced action the ACL denies causes
    the whole request to be rejected.
    """
    if not allow_non_loopback:
        ensure_loopback(host)
    if allow_non_loopback and not shared_secret:
        file_automation_logger.warning(
            "tcp_server: non-loopback bind without shared_secret is insecure",
        )
    server = TCPActionServer(
        (host, port),
        _TCPServerHandler,
        shared_secret=shared_secret,
        action_acl=action_acl,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    file_automation_logger.info(
        "tcp_server: listening on %s:%d (auth=%s)",
        host,
        port,
        "on" if shared_secret else "off",
    )
    return server


def main(argv: list[str] | None = None) -> Any:
    """Entry point for ``python -m automation_file.server.tcp_server``."""
    args = argv if argv is not None else sys.argv[1:]
    host = args[0] if len(args) >= 1 else _DEFAULT_HOST
    port = int(args[1]) if len(args) >= 2 else _DEFAULT_PORT
    return start_autocontrol_socket_server(host=host, port=port)


if __name__ == "__main__":
    main()
