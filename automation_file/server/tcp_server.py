"""TCP socket server that executes JSON action payloads.

Binds to localhost by default. Explicitly rejects non-loopback binds unless
``allow_non_loopback`` is True because the server accepts arbitrary action
names from clients and should not be exposed to the network by accident.

When a ``shared_secret`` is supplied the server requires each connection to
begin with ``AUTH <secret>\\n`` before the JSON payload. This is the minimum
bar for exposing the server beyond loopback; use a TLS-terminating proxy for
anything resembling production.

The server is je_action_core's action server with FileAutomation's dialect:
records are ``<key> -> <value>`` lines, failures say where they happened
(``json error``, ``forbidden``, ``execution error``, ``decode error``,
``auth error``), and every reply but the quit acknowledgement ends with
``Return_Data_Over_JE``.
"""

from __future__ import annotations

import sys
from typing import Any, cast

from je_action_core import (
    ActionTCPServer,
    ReplyMessages,
    SecretHeaderRequestHandler,
    SocketServerSettings,
    start_action_socket_server,
)

from automation_file.core.action_executor import execute_action
from automation_file.logging_config import file_automation_logger
from automation_file.server.action_acl import ActionACL
from automation_file.server.network_guards import ensure_loopback

_DEFAULT_HOST = "localhost"
_DEFAULT_PORT = 9943
_MESSAGES = ReplyMessages(
    record="{key} -> {value}",
    error="execution error: {error!r}",
    json_error="json error: {error!r}",
    refused="forbidden: {error}",
    decode_error="decode error: {error!r}",
    quit="server shutting down",
    auth_refused="auth error",
    log_command="tcp_server: recv {text}",
)


class TCPActionServer(ActionTCPServer):
    """Threaded TCP server with an explicit close flag."""

    daemon_threads = True
    allow_reuse_address = True


def _settings(shared_secret: str | None, action_acl: ActionACL | None) -> SocketServerSettings:
    return SocketServerSettings(
        execute=execute_action,
        validate=action_acl.enforce if action_acl is not None else None,
        messages=_MESSAGES,
        secret=shared_secret,
        log_info=file_automation_logger.info,
        log_error=file_automation_logger.error,
    )


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
    server = start_action_socket_server(
        host,
        port,
        _settings(shared_secret, action_acl),
        SecretHeaderRequestHandler,
        TCPActionServer,
    )
    file_automation_logger.info(
        "tcp_server: listening on %s:%d (auth=%s)",
        host,
        port,
        "on" if shared_secret else "off",
    )
    return cast(TCPActionServer, server)


def main(argv: list[str] | None = None) -> Any:
    """Entry point for ``python -m automation_file.server.tcp_server``."""
    args = argv if argv is not None else sys.argv[1:]
    host = args[0] if len(args) >= 1 else _DEFAULT_HOST
    port = int(args[1]) if len(args) >= 2 else _DEFAULT_PORT
    return start_autocontrol_socket_server(host=host, port=port)


if __name__ == "__main__":
    main()
