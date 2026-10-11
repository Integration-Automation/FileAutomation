"""Dashboard page: health, runs, integrity drift, recent events and storage status."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from automation_file.app import DashboardService, DashboardSummary
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.pages.base import BasePage, cell_text, fill_table, make_table

_REFRESH_INTERVAL_MS = 5000
_HEADLINES = {"ok": "All clear", "attention": "Needs attention"}
_HEADLINE_STYLES = {
    "ok": "font-size: 18px; font-weight: bold; color: #2f8f3f;",
    "attention": "font-size: 18px; font-weight: bold; color: #b3261e;",
}
_HEALTH_ROWS = (
    ("registry_size", "Registered actions"),
    ("running_runs", "Running pipeline runs"),
    ("scheduler_jobs", "Scheduled jobs"),
    ("integrity_monitors", "Integrity monitors"),
    ("notification_sinks", "Notification sinks"),
    ("notification_routes", "Notification routes"),
    ("notification_router_active", "Notification router active"),
)
_RUN_COLUMNS = ("Run", "Pipeline", "Status", "Started", "Tasks", "Error")
_INTEGRITY_COLUMNS = ("Monitor", "Target", "Running", "Drift", "Last run", "Error")
_STORAGE_COLUMNS = ("Backend", "Kind", "Usable", "Detail")
_EVENT_COLUMNS = ("Time", "Severity", "Type", "Source", "Subject")
_RUN_ID_LENGTH = 8


def _run_row(run: dict[str, Any]) -> list[object]:
    statuses = run.get("task_statuses") or {}
    tasks = ", ".join(f"{count} {status}" for status, count in statuses.items())
    return [
        str(run.get("run_id") or "")[:_RUN_ID_LENGTH],
        run.get("pipeline"),
        run.get("status"),
        run.get("started_at"),
        tasks,
        run.get("error"),
    ]


def _drift_text(monitor: dict[str, Any]) -> str:
    if monitor.get("ok") is None:
        return "not verified yet"
    return "none" if monitor["ok"] else f"{monitor.get('changes', 0)} change(s)"


class DashboardPage(BasePage):
    """One look at how the installation is doing; it reads and starts nothing."""

    title = "Dashboard"

    def __init__(self, service: DashboardService, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._service = service
        self._summary: DashboardSummary | None = None
        self._health_labels: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addLayout(self._header())
        grid = QGridLayout()
        grid.setSpacing(10)
        grid.addWidget(self._health_group(), 0, 0)
        grid.addWidget(self._runs_group(), 0, 1)
        grid.addWidget(self._integrity_group(), 1, 0)
        grid.addWidget(self._storage_group(), 1, 1)
        grid.addWidget(self._events_group(), 2, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 2)
        root.addLayout(grid, 1)
        root.addWidget(self.status_label())

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start()

    # ------------------------------------------------------------------ layout

    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        self._headline = QLabel("Not read yet")
        self._headline.setStyleSheet("font-size: 18px; font-weight: bold; color: #777;")
        self._reasons = QLabel("")
        self._reasons.setWordWrap(True)
        self._auto = QCheckBox("Refresh every 5 s")
        self._auto.setChecked(True)
        row.addWidget(self._headline)
        row.addWidget(self._reasons, 1)
        row.addWidget(self._auto)
        row.addWidget(self.make_button("Refresh", self.refresh))
        return row

    def _health_group(self) -> QGroupBox:
        box = QGroupBox("Health")
        form = QFormLayout(box)
        for key, label in (*_HEALTH_ROWS, ("audit", "Audit trail"), ("time", "Read at")):
            value = QLabel(cell_text(None))
            self._health_labels[key] = value
            form.addRow(label, value)
        return box

    def _runs_group(self) -> QGroupBox:
        box = QGroupBox("Pipeline runs")
        layout = QVBoxLayout(box)
        self._run_counts = QLabel("No runs recorded")
        self._running_table = make_table(_RUN_COLUMNS)
        self._recent_table = make_table(_RUN_COLUMNS)
        layout.addWidget(self._run_counts)
        layout.addWidget(QLabel("Running"))
        layout.addWidget(self._running_table)
        layout.addWidget(QLabel("Latest results"))
        layout.addWidget(self._recent_table)
        return box

    def _integrity_group(self) -> QGroupBox:
        box = QGroupBox("Integrity drift")
        layout = QVBoxLayout(box)
        self._integrity_table = make_table(_INTEGRITY_COLUMNS)
        layout.addWidget(self._integrity_table)
        return box

    def _storage_group(self) -> QGroupBox:
        box = QGroupBox("Storage status")
        layout = QVBoxLayout(box)
        self._storage_table = make_table(_STORAGE_COLUMNS)
        layout.addWidget(self._storage_table)
        return box

    def _events_group(self) -> QGroupBox:
        box = QGroupBox("Recent events")
        layout = QVBoxLayout(box)
        self._events_table = make_table(_EVENT_COLUMNS)
        layout.addWidget(self._events_table)
        return box

    # ------------------------------------------------------------------ data

    def refresh(self) -> None:
        self.run_async(
            self._service.summary, "read summary", self.show_summary, key="refresh", quiet=True
        )

    def shutdown(self) -> None:
        self._timer.stop()
        super().shutdown()

    def _on_tick(self) -> None:
        if self._auto.isChecked() and self.isVisible():
            self.refresh()

    def summary(self) -> DashboardSummary | None:
        """Return the summary the page currently shows."""
        return self._summary

    def show_summary(self, summary: DashboardSummary) -> None:
        """Render ``summary``: the whole page is a function of it."""
        self._summary = summary
        self._headline.setText(_HEADLINES.get(summary.status, summary.status))
        self._headline.setStyleSheet(_HEADLINE_STYLES.get(summary.status, ""))
        self._reasons.setText("; ".join(summary.reasons))
        self._show_health(summary.health)
        counts = summary.run_counts
        self._run_counts.setText(
            ", ".join(f"{count} {status}" for status, count in counts.items()) or "No runs recorded"
        )
        fill_table(self._running_table, [_run_row(run) for run in summary.running_runs])
        fill_table(self._recent_table, [_run_row(run) for run in summary.recent_runs])
        fill_table(
            self._integrity_table,
            [
                [
                    monitor.get("name"),
                    monitor.get("target"),
                    bool(monitor.get("running")),
                    _drift_text(monitor),
                    monitor.get("last_run"),
                    monitor.get("last_error"),
                ]
                for monitor in summary.integrity
            ],
        )
        fill_table(
            self._storage_table,
            [
                [
                    backend.get("name"),
                    backend.get("kind"),
                    bool(backend.get("usable")),
                    backend.get("detail"),
                ]
                for backend in summary.storage
            ],
        )
        fill_table(
            self._events_table,
            [
                [
                    event.get("timestamp"),
                    event.get("severity"),
                    event.get("type"),
                    event.get("source"),
                    event.get("subject"),
                ]
                for event in summary.events
            ],
        )

    def _show_health(self, health: dict[str, Any]) -> None:
        for key, _label in _HEALTH_ROWS:
            self._health_labels[key].setText(cell_text(health.get(key)))
        audit = health.get("audit") or {}
        if not audit.get("configured"):
            described = "not configured"
        else:
            described = "recording" if audit.get("active") else "configured, not recording"
        self._health_labels["audit"].setText(described)
        self._health_labels["time"].setText(cell_text(health.get("time")))
