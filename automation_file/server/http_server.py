"""HTTP action server (stdlib only).

Accepts ``POST /actions`` whose body is a JSON action list; the response is
a JSON object mirroring :func:`execute_action`'s return value. Additional
observability endpoints:

* ``GET /healthz``      — liveness (always 200 while the process is alive)
* ``GET /readyz``       — readiness (registry resolves + ACL intact)
* ``GET /openapi.json`` — OpenAPI 3.0 description of the above
* ``GET /progress``     — WebSocket stream of progress registry snapshots

Bound to loopback by default with the same opt-in semantics as
:mod:`tcp_server`. When ``shared_secret`` is supplied ``POST /actions`` and
``/progress`` require ``Authorization: Bearer <secret>`` — useful when
placing the server behind a reverse proxy.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from automation_file.core.action_executor import execute_action, executor
from automation_file.core.progress import progress_registry
from automation_file.exceptions import TCPAuthException
from automation_file.logging_config import file_automation_logger
from automation_file.server._websocket import (
    compute_accept_key,
    send_close,
    send_text,
)
from automation_file.server.action_acl import ActionACL, ActionNotPermittedException
from automation_file.server.network_guards import ensure_loopback

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 9944
_MAX_CONTENT_BYTES = 1 * 1024 * 1024
_PROGRESS_POLL_SECONDS = 1.0
_PROGRESS_MAX_FRAMES = 10_000


class _HTTPActionHandler(BaseHTTPRequestHandler):
    """Routes: POST /actions, GET /{healthz,readyz,openapi.json,progress}."""

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

    def do_GET(self) -> None:  # pylint: disable=invalid-name — BaseHTTPRequestHandler API
        if self.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        if self.path == "/readyz":
            ready, reason = _readiness()
            status = HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE
            self._send_json(status, {"status": "ready" if ready else "not_ready", "reason": reason})
            return
        if self.path == "/openapi.json":
            self._send_json(HTTPStatus.OK, _openapi_spec())
            return
        if self.path == "/progress":
            self._handle_progress_ws()
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

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

    def _handle_progress_ws(self) -> None:
        upgrade = self.headers.get("Upgrade", "").lower()
        connection = self.headers.get("Connection", "").lower()
        ws_key = self.headers.get("Sec-WebSocket-Key")
        if upgrade != "websocket" or "upgrade" not in connection or not ws_key:
            self._send_json(HTTPStatus.UPGRADE_REQUIRED, {"error": "websocket upgrade required"})
            return

        secret: str | None = getattr(self.server, "shared_secret", None)
        if secret:
            header = self.headers.get("Authorization", "")
            token_ok = header.startswith("Bearer ") and hmac.compare_digest(
                header[len("Bearer ") :], secret
            )
            if not token_ok:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "bad shared secret"})
                return

        accept = compute_accept_key(ws_key)
        self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        self._stream_progress_frames()

    def _stream_progress_frames(self) -> None:
        frames_sent = 0
        try:
            while frames_sent < _PROGRESS_MAX_FRAMES:
                snapshot = progress_registry.list()
                send_text(self.wfile, json.dumps({"progress": snapshot}, default=repr))
                frames_sent += 1
                time.sleep(_PROGRESS_POLL_SECONDS)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as error:  # pylint: disable=broad-except
            file_automation_logger.warning("http_server progress: %r", error)
        finally:
            with contextlib.suppress(OSError):
                send_close(self.wfile)


def _readiness() -> tuple[bool, str]:
    try:
        if not executor.registry.event_dict:
            return False, "registry empty"
    except Exception as error:  # pylint: disable=broad-except
        return False, f"registry error: {error!r}"
    return True, "ok"


def _openapi_spec() -> dict[str, object]:
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "automation_file HTTP action server",
            "version": "1.0.0",
            "description": (
                "Executes JSON action lists and exposes health / readiness / progress endpoints."
            ),
        },
        "paths": {
            "/actions": {
                "post": {
                    "summary": "Execute a JSON action list.",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"type": "array"},
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {"description": "Action results as a JSON object."},
                        "400": {"description": "Malformed JSON body."},
                        "401": {"description": "Missing or invalid shared-secret token."},
                        "403": {"description": "Action denied by ACL."},
                        "500": {"description": "Server error while dispatching."},
                    },
                }
            },
            "/healthz": {
                "get": {
                    "summary": "Liveness probe.",
                    "responses": {"200": {"description": "Server process alive."}},
                }
            },
            "/readyz": {
                "get": {
                    "summary": "Readiness probe.",
                    "responses": {
                        "200": {"description": "Registry populated and accepting actions."},
                        "503": {"description": "Not ready."},
                    },
                }
            },
            "/progress": {
                "get": {
                    "summary": "WebSocket stream of progress registry snapshots.",
                    "responses": {
                        "101": {"description": "Switching protocols to WebSocket."},
                        "401": {"description": "Missing or invalid shared-secret token."},
                        "426": {"description": "WebSocket upgrade required."},
                    },
                }
            },
        },
    }


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
