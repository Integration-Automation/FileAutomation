"""Prometheus scrape endpoint (``GET /metrics``).

``start_metrics_server(host, port)`` spawns a threaded HTTP server that
serves the current metrics snapshot rendered by
:func:`automation_file.core.metrics.render`. Like the other servers in
this package it defaults to loopback and requires ``allow_non_loopback=True``
to bind elsewhere. No auth is attached by default — put it behind a
reverse proxy or use an ACL at the network layer if exposing beyond a
trusted host.
"""

from __future__ import annotations

import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from automation_file.core.metrics import render
from automation_file.logging_config import file_automation_logger
from automation_file.server.network_guards import ensure_loopback

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 9945
_METRICS_PATH = "/metrics"


class _MetricsHandler(BaseHTTPRequestHandler):
    """GET /metrics -> current Prometheus snapshot."""

    def log_message(  # pylint: disable=arguments-differ
        self, format_str: str, *args: object
    ) -> None:
        file_automation_logger.info("metrics_server: " + format_str, *args)

    def do_GET(self) -> None:  # pylint: disable=invalid-name — BaseHTTPRequestHandler API
        if self.path != _METRICS_PATH:
            self._send(HTTPStatus.NOT_FOUND, b"not found", "text/plain; charset=utf-8")
            return
        payload, content_type = render()
        self._send(HTTPStatus.OK, payload, content_type)

    def _send(self, status: HTTPStatus, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class MetricsServer(ThreadingHTTPServer):
    """Threaded HTTP server serving ``GET /metrics``."""


def start_metrics_server(
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    allow_non_loopback: bool = False,
) -> MetricsServer:
    """Start a metrics server on a background thread and return it."""
    if not allow_non_loopback:
        ensure_loopback(host)
    server = MetricsServer((host, port), _MetricsHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = server.server_address
    file_automation_logger.info("metrics_server: listening on %s:%d", address[0], address[1])
    return server
