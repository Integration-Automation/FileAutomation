"""Read-only observability Web UI (stdlib + HTMX).

Serves a single HTML page that polls HTML fragments using HTMX (loaded from a
pinned CDN URL). Every fragment but the transfer progress is rendered from the
application layer (:mod:`automation_file.app`), the same services the PySide6
window calls, so the two show the same health, runs, integrity drift, events,
storage status and audit records. Write operations are deliberately out of
scope; trigger actions through :mod:`http_server` / :mod:`tcp_server` with
their auth story intact.

Loopback-only by default; ``allow_non_loopback=True`` is required to bind
elsewhere. When ``shared_secret`` is supplied every request must carry
``Authorization: Bearer <secret>`` — the rendered HTML includes a
``hx-headers`` attribute so HTMX's polled requests carry the token.

Everything a fragment shows is escaped, and the application layer has already
masked tokens, passwords and webhook URLs in it.
"""

from __future__ import annotations

import hmac
import html as html_lib
import json
import threading
from collections.abc import Callable, Iterable, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from automation_file.app import NAVIGATION, AppServices, app_services
from automation_file.core.progress import progress_registry
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger
from automation_file.server.network_guards import ensure_loopback

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 9955
_HTMX_CDN = "https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js"
_HTMX_SRI = "sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2"
_EVENT_LIMIT = 30
_RUN_LIMIT = 15
_AUDIT_LIMIT = 30
_RUN_ID_LENGTH = 8
_AUDIT_KEYS = ("timestamp", "actor", "source", "action", "resource", "status", "error")
_EMPTY = "—"

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
  .ok {{ color: #2f8f3f; font-weight: bold; }}
  .attention {{ color: #b3261e; font-weight: bold; }}
  nav {{ font-size: 0.9rem; margin: 0.6rem 0 0; }}
  nav span {{ margin-right: 0.9rem; color: #555; }}
  code {{ background: #f3f3f3; padding: 0.1rem 0.3rem; border-radius: 3px; }}
</style>
</head>
<body hx-headers='{auth_headers}'>
<h1>automation_file</h1>
<p class="muted">Read-only dashboard. Write operations live on the action server.</p>
<nav>{navigation}</nav>

<h2>Health</h2>
<div id="health" hx-get="/ui/health" hx-trigger="load, every 5s" hx-swap="innerHTML">
  <em class="muted">loading…</em>
</div>

<h2>Pipeline runs</h2>
<div id="runs" hx-get="/ui/runs" hx-trigger="load, every 3s" hx-swap="innerHTML">
  <em class="muted">loading…</em>
</div>

<h2>Integrity</h2>
<div id="integrity" hx-get="/ui/integrity" hx-trigger="load, every 10s" hx-swap="innerHTML">
  <em class="muted">loading…</em>
</div>

<h2>Recent events</h2>
<div id="events" hx-get="/ui/events" hx-trigger="load, every 5s" hx-swap="innerHTML">
  <em class="muted">loading…</em>
</div>

<h2>Storage</h2>
<div id="storage" hx-get="/ui/storage" hx-trigger="load, every 30s" hx-swap="innerHTML">
  <em class="muted">loading…</em>
</div>

<h2>Audit</h2>
<div id="audit" hx-get="/ui/audit" hx-trigger="load, every 10s" hx-swap="innerHTML">
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


def _text(value: object) -> str:
    """Return ``value`` as escaped HTML text; nothing becomes a dash."""
    if value is None or value == "":
        return _EMPTY
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return html_lib.escape(", ".join(str(item) for item in value), quote=True) or _EMPTY
    return html_lib.escape(str(value), quote=True)


def _muted(message: str) -> str:
    return f"<p class='muted'>{html_lib.escape(message, quote=True)}</p>"


def _table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    """Render a table; every header and every cell is escaped here."""
    head = "".join(f"<th>{_text(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_text(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return f"<table><tr>{head}</tr>{body}</table>"


def _pairs(rows: Iterable[tuple[str, object]]) -> str:
    """Render a two-column table of names and values."""
    body = "".join(
        f"<tr><th>{_text(name)}</th><td>{_text(value)}</td></tr>" for name, value in rows
    )
    return f"<table>{body}</table>"


def _audit_state(audit: dict[str, Any]) -> str:
    if not audit.get("configured"):
        return "not configured"
    return "recording" if audit.get("active") else "configured, not recording"


def _render_health(services: AppServices) -> str:
    summary = services.dashboard.summary(events=_EVENT_LIMIT, runs=_RUN_LIMIT)
    health = summary.health
    status_class = "ok" if summary.status == "ok" else "attention"
    rows: list[tuple[str, object]] = [
        ("process", health.get("process", "alive")),
        ("registry size", health.get("registry_size")),
        ("running runs", health.get("running_runs")),
        ("scheduled jobs", health.get("scheduler_jobs")),
        ("integrity monitors", health.get("integrity_monitors")),
        ("notification sinks", health.get("notification_sinks")),
        ("notification routes", health.get("notification_routes")),
        ("audit", _audit_state(health.get("audit") or {})),
        ("time", health.get("time")),
    ]
    reasons = "".join(f"<li>{_text(reason)}</li>" for reason in summary.reasons)
    return (
        f"<p class='{status_class}'>status: {_text(summary.status)}</p>"
        + (f"<ul>{reasons}</ul>" if reasons else "")
        + _pairs(rows)
    )


def _run_row(run: dict[str, Any]) -> list[object]:
    statuses = run.get("task_statuses") or {}
    return [
        str(run.get("run_id") or "")[:_RUN_ID_LENGTH],
        run.get("pipeline"),
        run.get("status"),
        run.get("started_at"),
        run.get("finished_at"),
        ", ".join(f"{count} {status}" for status, count in statuses.items()),
        run.get("error"),
    ]


def _render_runs(services: AppServices) -> str:
    data = services.dashboard.runs(_RUN_LIMIT)
    runs = [*data["running"], *data["recent"]]
    counts = ", ".join(f"{count} {status}" for status, count in data["counts"].items())
    if not runs:
        return _muted("no pipeline runs recorded")
    headers = ("run", "pipeline", "status", "started", "finished", "tasks", "error")
    return f"<p class='muted'>{_text(counts)}</p>" + _table(headers, map(_run_row, runs))


def _drift(monitor: dict[str, Any]) -> str:
    if monitor.get("ok") is None:
        return "not verified yet"
    return "none" if monitor["ok"] else f"{monitor.get('changes', 0)} change(s)"


def _render_integrity(services: AppServices) -> str:
    monitors = services.dashboard.integrity()
    if not monitors:
        return _muted("no integrity monitor is running")
    headers = ("monitor", "target", "running", "drift", "last run", "error")
    return _table(
        headers,
        (
            [
                monitor.get("name"),
                monitor.get("target"),
                bool(monitor.get("running")),
                _drift(monitor),
                monitor.get("last_run"),
                monitor.get("last_error"),
            ]
            for monitor in monitors
        ),
    )


def _render_events(services: AppServices) -> str:
    events = services.dashboard.recent_events(_EVENT_LIMIT)
    if not events:
        return _muted("no events yet")
    headers = ("time", "severity", "type", "source", "subject", "error")
    return _table(
        headers,
        (
            [
                event.get("timestamp"),
                event.get("severity"),
                event.get("type"),
                event.get("source"),
                event.get("subject"),
                (event.get("payload") or {}).get("error"),
            ]
            for event in events
        ),
    )


def _render_storage(services: AppServices) -> str:
    headers = ("backend", "kind", "usable", "detail")
    return _table(
        headers,
        (
            [
                backend.get("name"),
                backend.get("kind"),
                bool(backend.get("usable")),
                backend.get("detail"),
            ]
            for backend in services.dashboard.storage_status()
        ),
    )


def _render_audit(services: AppServices) -> str:
    if not services.audit.is_configured():
        return _muted("audit is not configured; call configure_audit to start recording")
    records = services.audit.recent(_AUDIT_LIMIT)
    if not records:
        return _muted("no audit records yet")
    headers = ("time", "actor", "source", "action", "resource", "status", "error")
    return _table(headers, ([record.get(key) for key in _AUDIT_KEYS] for record in records))


def _render_progress(_services: AppServices) -> str:
    snapshots = progress_registry.list()
    if not snapshots:
        return "<p class='muted'>no active transfers</p>"
    rows = []
    for item in snapshots:
        name = html_lib.escape(str(item.get("name", "")), quote=True)
        status = html_lib.escape(str(item.get("status", "")), quote=True)
        transferred = int(item.get("transferred", 0) or 0)
        total = item.get("total")
        total_cell = "—" if total in (None, 0) else html_lib.escape(str(total), quote=True)
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


def _render_registry(services: AppServices) -> str:
    names = services.pipelines.action_names()
    if not names:
        return "<p class='muted'>registry empty</p>"
    items = "".join(f"<li><code>{html_lib.escape(name, quote=True)}</code></li>" for name in names)
    return f"<ul>{items}</ul>"


#: Fragment path -> the function that renders it from the application services.
_FRAGMENTS: dict[str, Callable[[AppServices], str]] = {
    "/ui/health": _render_health,
    "/ui/runs": _render_runs,
    "/ui/integrity": _render_integrity,
    "/ui/events": _render_events,
    "/ui/storage": _render_storage,
    "/ui/audit": _render_audit,
    "/ui/progress": _render_progress,
    "/ui/registry": _render_registry,
}


class _WebUIHandler(BaseHTTPRequestHandler):
    """Serves the dashboard page plus its HTMX fragment endpoints."""

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
        render = _FRAGMENTS.get(path)
        if render is None:
            self._send_html(HTTPStatus.NOT_FOUND, "<p>not found</p>")
            return
        self._send_html(HTTPStatus.OK, self._fragment(path, render))

    def _fragment(self, path: str, render: Callable[[AppServices], str]) -> str:
        """Render one fragment; a service that cannot answer becomes a note, not a broken page."""
        services: AppServices = getattr(self.server, "services", None) or app_services()
        try:
            return render(services)
        except FileAutomationException as error:
            file_automation_logger.warning("web_ui: %s cannot be rendered: %r", path, error)
            return _muted(f"unavailable: {type(error).__name__}")

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
        navigation = "".join(f"<span>{_text(name)}</span>" for name in NAVIGATION)
        return _INDEX_TEMPLATE.format(
            htmx_src=_HTMX_CDN,
            htmx_sri=_HTMX_SRI,
            auth_headers=auth_headers,
            navigation=navigation,
        )


class WebUIServer(ThreadingHTTPServer):
    """Threaded HTTP server for the HTMX dashboard.

    ``services`` is the set of application services the fragments read; the
    process-wide set by default, the one the desktop window uses too.
    """

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type = _WebUIHandler,
        shared_secret: str | None = None,
        services: AppServices | None = None,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.shared_secret: str | None = shared_secret
        self.services: AppServices = app_services() if services is None else services


def start_web_ui(
    host: str = _DEFAULT_HOST,
    port: int = _DEFAULT_PORT,
    allow_non_loopback: bool = False,
    shared_secret: str | None = None,
    services: AppServices | None = None,
) -> WebUIServer:
    """Start the Web UI server on a background thread.

    ``services`` replaces the process-wide application services, for a server
    that should show another run store, bus or resolver.
    """
    if not allow_non_loopback:
        ensure_loopback(host)
    if allow_non_loopback and not shared_secret:
        file_automation_logger.warning(
            "web_ui: non-loopback bind without shared_secret is insecure",
        )
    server = WebUIServer((host, port), shared_secret=shared_secret, services=services)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    file_automation_logger.info(
        "web_ui: listening on %s:%d (auth=%s)",
        host,
        port,
        "on" if shared_secret else "off",
    )
    return server
