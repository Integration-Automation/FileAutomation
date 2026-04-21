"""HTTP action server (stdlib only).

Listens for ``POST /actions`` requests whose body is a JSON action list; the
response body is a JSON object mirroring :func:`execute_action`'s return
value. Bound to loopback by default with the same opt-in semantics as
:mod:`tcp_server`. When ``shared_secret`` is supplied clients must send
``Authorization: Bearer <secret>`` — useful when placing the server behind a
reverse proxy.
"""

from __future__ import annotations

import hmac
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from automation_file.core.action_executor import execute_action
from automation_file.exceptions import TCPAuthException
from automation_file.logging_config import file_automation_logger
from automation_file.server.action_acl import ActionACL, ActionNotPermittedException
from automation_file.server.network_guards import ensure_loopback

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 9944
_MAX_CONTENT_BYTES = 1 * 1024 * 1024


class _HTTPActionHandler(BaseHTTPRequestHandler):
    """POST /actions -> JSON results."""

    def log_message(  # pylint: disable=arguments-differ
        self, format_str: str, *args: object
    ) -> None:
        file_automation_logger.info("http_server: " + format_str, *args)

    def do_POST(self) -> None:  # pylint: disable=invalid-name — BaseHTTPRequestHandler API
        if self.path != "/actions":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            payload = self._read_payload()
        except TCPAuthException as error:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": str(error)})
            return
        except ValueError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return

        acl: ActionACL | None = getattr(self.server, "action_acl", None)
        if acl is not None:
            try:
                acl.enforce(payload)
            except ActionNotPermittedException as error:
                file_automation_logger.warning("http_server acl: %r", error)
                self._send_json(HTTPStatus.FORBIDDEN, {"error": str(error)})
                return

        try:
            results = execute_action(payload)
        except Exception as error:  # pylint: disable=broad-except
            file_automation_logger.error("http_server handler: %r", error)
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": repr(error)})
            return
        self._send_json(HTTPStatus.OK, results)

    def _read_payload(self) -> list:
        secret: str | None = getattr(self.server, "shared_secret", None)
        if secret:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                raise TCPAuthException("missing bearer token")
            if not hmac.compare_digest(header[len("Bearer ") :], secret):
                raise TCPAuthException("bad shared secret")

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("invalid Content-Length") from error
        if length <= 0:
            raise ValueError("empty body")
        if length > _MAX_CONTENT_BYTES:
            raise ValueError(f"body {length} exceeds cap {_MAX_CONTENT_BYTES}")

        body = self.rfile.read(length)
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(f"bad JSON: {error!r}") from error

    def _send_json(self, status: HTTPStatus, data: object) -> None:
        payload = json.dumps(data, default=repr).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class HTTPActionServer(ThreadingHTTPServer):
    """Threaded HTTP server carrying an optional shared secret."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type = _HTTPActionHandler,
        shared_secret: str | None = None,
        action_acl: ActionACL | None = None,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.shared_secret: str | None = shared_secret
        self.action_acl: ActionACL | None = action_acl


def start_http_action_server(
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    allow_non_loopback: bool = False,
    shared_secret: str | None = None,
    action_acl: ActionACL | None = None,
) -> HTTPActionServer:
    """Start the HTTP action server on a background thread."""
    if not allow_non_loopback:
        ensure_loopback(host)
    if allow_non_loopback and not shared_secret:
        file_automation_logger.warning(
            "http_server: non-loopback bind without shared_secret is insecure",
        )
    server = HTTPActionServer((host, port), shared_secret=shared_secret, action_acl=action_acl)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    file_automation_logger.info(
        "http_server: listening on %s:%d (auth=%s)",
        host,
        port,
        "on" if shared_secret else "off",
    )
    return server
