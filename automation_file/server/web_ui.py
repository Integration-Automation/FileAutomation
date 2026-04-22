"""Read-only observability Web UI (stdlib + HTMX).

Serves a single HTML page that polls three HTML fragments — registered
actions, live progress, and health summary — using HTMX (loaded from a
pinned CDN URL). Write operations are deliberately out of scope; trigger
actions through :mod:`http_server` / :mod:`tcp_server` with their auth
story intact.

Loopback-only by default; ``allow_non_loopback=True`` is required to bind
elsewhere. When ``shared_secret`` is supplied every request must carry
``Authorization: Bearer <secret>`` — the rendered HTML includes a
``hx-headers`` attribute so HTMX's polled requests carry the token.
"""

from __future__ import annotations

import hmac
import html as html_lib
import json
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from automation_file.core.action_executor import executor
from automation_file.core.progress import progress_registry
from automation_file.logging_config import file_automation_logger
from automation_file.server.network_guards import ensure_loopback

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 9955
_HTMX_CDN = "https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js"
_HTMX_SRI = "sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2"

_INDEX_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>automation_file</title>
<script src="{htmx_src}" integrity="{htmx_sri}" crossorigin="anonymous"></script>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1d1f21; }}
  h1 {{ font-size: 1.4rem; margin-bottom: 0.2rem; }}
  h2 {{ font-size: 1.05rem; margin-top: 1.5rem; color: #555; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
  th, td {{ padding: 0.35rem 0.6rem; border-bottom: 1px solid #eee; text-align: left; }}
  th {{ background: #f5f5f5; }}
  .muted {{ color: #888; }}
  code {{ background: #f3f3f3; padding: 0.1rem 0.3rem; border-radius: 3px; }}
</style>
</head>
<body hx-headers='{auth_headers}'>
<h1>automation_file</h1>
<p class="muted">Read-only dashboard. Write operations live on the action server.</p>

<h2>Health</h2>
<div id="health" hx-get="/ui/health" hx-trigger="load, every 5s" hx-swap="innerHTML">
  <em class="muted">loading…</em>
</div>

<h2>Progress</h2>
<div id="progress" hx-get="/ui/progress" hx-trigger="load, every 2s" hx-swap="innerHTML">
  <em class="muted">loading…</em>
</div>

<h2>Registered actions</h2>
<div id="registry" hx-get="/ui/registry" hx-trigger="load, every 30s" hx-swap="innerHTML">
  <em class="muted">loading…</em>
</div>
</body>
</html>
"""


class _WebUIHandler(BaseHTTPRequestHandler):
    """Serves the dashboard page plus its three HTMX fragment endpoints."""

    def log_message(  # pylint: disable=arguments-differ
        self, format_str: str, *args: object
    ) -> None:
        file_automation_logger.info("web_ui: " + format_str, *args)

    def do_GET(self) -> None:  # pylint: disable=invalid-name
        if not self._authorized():
            self._send_html(HTTPStatus.UNAUTHORIZED, "<p>unauthorized</p>")
            return
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send_html(HTTPStatus.OK, self._render_index())
            return
        if path == "/ui/health":
            self._send_html(HTTPStatus.OK, _render_health())
            return
        if path == "/ui/progress":
            self._send_html(HTTPStatus.OK, _render_progress())
            return
        if path == "/ui/registry":
            self._send_html(HTTPStatus.OK, _render_registry())
            return
        self._send_html(HTTPStatus.NOT_FOUND, "<p>not found</p>")

    def _authorized(self) -> bool:
        secret: str | None = getattr(self.server, "shared_secret", None)
        if not secret:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header[len("Bearer ") :], secret)

    def _send_html(self, status: HTTPStatus, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _render_index(self) -> str:
        secret: str | None = getattr(self.server, "shared_secret", None)
        auth_headers_obj = {"Authorization": f"Bearer {secret}"} if secret else {}
        auth_headers = html_lib.escape(json.dumps(auth_headers_obj), quote=True)
        return _INDEX_TEMPLATE.format(
            htmx_src=_HTMX_CDN,
            htmx_sri=_HTMX_SRI,
            auth_headers=auth_headers,
        )


def _render_health() -> str:
    names = list(executor.registry.event_dict.keys())
    return (
        "<table>"
        "<tr><th>process</th><td>alive</td></tr>"
        f"<tr><th>registry size</th><td>{len(names)}</td></tr>"
        f"<tr><th>time</th><td>{html_lib.escape(time.strftime('%Y-%m-%d %H:%M:%S'))}</td></tr>"
        "</table>"
    )


def _render_progress() -> str:
    snapshots = progress_registry.list()
    if not snapshots:
        return "<p class='muted'>no active transfers</p>"
    rows = []
    for item in snapshots:
        name = html_lib.escape(str(item.get("name", "")))
        status = html_lib.escape(str(item.get("status", "")))
        transferred = int(item.get("transferred", 0) or 0)
        total = item.get("total")
        total_cell = "—" if total in (None, 0) else str(total)
        pct = ""
        if isinstance(total, int) and total > 0:
            pct = f" ({(transferred / total) * 100:.1f}%)"
        rows.append(
            "<tr>"
            f"<td><code>{name}</code></td>"
            f"<td>{status}</td>"
            f"<td>{transferred}{pct}</td>"
            f"<td>{total_cell}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<tr><th>name</th><th>status</th><th>transferred</th><th>total</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def _render_registry() -> str:
    names = sorted(executor.registry.event_dict.keys())
    if not names:
        return "<p class='muted'>registry empty</p>"
    items = "".join(f"<li><code>{html_lib.escape(name)}</code></li>" for name in names)
    return f"<ul>{items}</ul>"


class WebUIServer(ThreadingHTTPServer):
    """Threaded HTTP server for the HTMX dashboard."""

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type = _WebUIHandler,
        shared_secret: str | None = None,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.shared_secret: str | None = shared_secret


def start_web_ui(
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    allow_non_loopback: bool = False,
    shared_secret: str | None = None,
) -> WebUIServer:
    """Start the Web UI server on a background thread."""
    if not allow_non_loopback:
        ensure_loopback(host)
    if allow_non_loopback and not shared_secret:
        file_automation_logger.warning(
            "web_ui: non-loopback bind without shared_secret is insecure",
        )
    server = WebUIServer((host, port), shared_secret=shared_secret)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    file_automation_logger.info(
        "web_ui: listening on %s:%d (auth=%s)",
        host,
        port,
        "on" if shared_secret else "off",
    )
    return server
