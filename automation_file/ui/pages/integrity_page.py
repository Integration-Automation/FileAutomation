"""Integrity page: baseline, verify, accept, and the named monitors."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from automation_file.app import IntegrityService, MonitorDrift
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.pages.base import BasePage, fill_table, make_table, selected_cell

_CHANGE_COLUMNS = ("Kind", "Path", "Previous path", "Fields", "Note")
_MONITOR_COLUMNS = ("Monitor", "Target", "Baseline", "Running", "Drift", "Last run", "Error")
_MAX_INTERVAL = 7 * 24 * 3600.0
_DEFAULT_INTERVAL = 60.0


def _drift_text(monitor: MonitorDrift) -> str:
    if monitor.ok is None:
        return "not verified yet"
    return "none" if monitor.ok else f"{monitor.changes} change(s)"


class IntegrityPage(BasePage):
    """Approve the state of a tree, compare it with what was approved, keep watching it."""

    title = "Integrity"

    def __init__(self, service: IntegrityService, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._service = service
        self._report: dict[str, Any] | None = None
        self._monitors: list[MonitorDrift] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(self._target_group())
        root.addWidget(self._report_group(), 1)
        root.addWidget(self._monitor_group(), 1)
        root.addWidget(self.status_label())

    # ------------------------------------------------------------------ layout

    def _target_group(self) -> QGroupBox:
        box = QGroupBox("Target and baseline")
        form = QFormLayout(box)
        self._target = QLineEdit()
        self._target.setPlaceholderText("the tree to check, e.g. s3://reports/2026 or a local path")
        self._baseline = QLineEdit()
        self._baseline.setPlaceholderText(
            "where the approved state is kept, e.g. local:///var/lib/fa/reports.json"
        )
        self._algorithm = QComboBox()
        self._algorithm.addItems(self._service.algorithms())
        self._deep = QCheckBox("Deep: hash every file (off: only files whose size or time changed)")
        self._deep.setChecked(True)
        form.addRow("Target", self._target)
        form.addRow("Baseline", self._baseline)
        form.addRow("Algorithm", self._algorithm)
        form.addRow(self._deep)
        row = QHBoxLayout()
        row.addWidget(self.make_button("Create baseline", self.create_baseline))
        row.addWidget(self.make_button("Verify", self.verify))
        row.addWidget(self.make_button("Accept current state", self.accept))
        row.addStretch()
        form.addRow(row)
        return box

    def _report_group(self) -> QGroupBox:
        box = QGroupBox("Last verification")
        layout = QVBoxLayout(box)
        self._summary = QLabel("Nothing verified yet.")
        self._summary.setWordWrap(True)
        self._changes = make_table(_CHANGE_COLUMNS)
        layout.addWidget(self._summary)
        layout.addWidget(self._changes)
        return box

    def _monitor_group(self) -> QGroupBox:
        box = QGroupBox("Monitors")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        self._name = QLineEdit()
        self._name.setPlaceholderText("monitor name")
        self._interval = QDoubleSpinBox()
        self._interval.setRange(1.0, _MAX_INTERVAL)
        self._interval.setDecimals(0)
        self._interval.setValue(_DEFAULT_INTERVAL)
        self._interval.setSuffix(" s")
        row.addWidget(self._name, 1)
        row.addWidget(QLabel("every"))
        row.addWidget(self._interval)
        row.addWidget(self.make_button("Start monitor", self.start_monitor))
        row.addWidget(self.make_button("Stop selected", self.stop_selected))
        row.addWidget(self.make_button("Refresh", self.refresh))
        layout.addLayout(row)
        self._monitor_table = make_table(_MONITOR_COLUMNS)
        layout.addWidget(self._monitor_table)
        return box

    # ------------------------------------------------------------------ baseline and verify

    def set_location(self, target: str, baseline: str) -> None:
        """Fill in the target and the baseline fields."""
        self._target.setText(target)
        self._baseline.setText(baseline)

    def last_report(self) -> dict[str, Any] | None:
        """Return the drift report the page shows."""
        return self._report

    def create_baseline(self) -> None:
        target, baseline = self._target.text(), self._baseline.text()
        algorithm = self._algorithm.currentText()
        self.run_async(
            lambda: self._service.baseline(target, baseline, algorithm),
            "create baseline",
            lambda stored: self.report(
                f"baseline of {stored['entries']} file(s) stored at {stored['baseline']}"
            ),
        )

    def verify(self) -> None:
        target, baseline = self._target.text(), self._baseline.text()
        deep = self._deep.isChecked()
        self.run_async(
            lambda: self._service.verify(target, baseline, deep), "verify", self._show_report
        )

    def accept(self) -> None:
        target, baseline = self._target.text(), self._baseline.text()
        if not self.confirm(
            "Approve the current state as the new baseline? Drift found so far will no longer be reported."
        ):
            return
        self.run_async(
            lambda: self._service.accept(target, baseline),
            "accept current state",
            lambda stored: self.report(
                f"accepted {stored['entries']} file(s) as the baseline at {stored['baseline']}"
            ),
        )

    def _show_report(self, report: dict[str, Any]) -> None:
        self._report = report
        changes = report.get("changes") or []
        fill_table(
            self._changes,
            [
                [
                    change.get("kind"),
                    change.get("path"),
                    change.get("previous_path"),
                    change.get("fields"),
                    change.get("note"),
                ]
                for change in changes
            ],
        )
        counts = ", ".join(
            f"{count} {kind}" for kind, count in (report.get("counts") or {}).items() if count
        )
        verdict = "no drift" if report.get("ok") else f"drift: {counts or len(changes)}"
        notes = " ".join(report.get("notes") or ())
        text = (
            f"{report.get('target')}: {verdict}; {report.get('hashed')} of "
            f"{report.get('checked')} file(s) hashed. {notes}"
        ).strip()
        self._summary.setText(text)
        if report.get("ok"):
            self.report(text)
        else:
            self.report_error(text)

    # ------------------------------------------------------------------ monitors

    def monitors(self) -> list[MonitorDrift]:
        """Return the monitors the table shows."""
        return list(self._monitors)

    def refresh(self) -> None:
        self.run_async(
            self._service.drift, "read monitors", self._show_monitors, key="refresh", quiet=True
        )

    def _show_monitors(self, monitors: list[MonitorDrift]) -> None:
        self._monitors = monitors
        fill_table(
            self._monitor_table,
            [
                [
                    monitor.name,
                    monitor.target,
                    monitor.baseline,
                    monitor.running,
                    _drift_text(monitor),
                    monitor.last_run,
                    monitor.last_error,
                ]
                for monitor in monitors
            ],
        )

    def start_monitor(self) -> None:
        name, interval = self._name.text(), float(self._interval.value())
        target, baseline = self._target.text(), self._baseline.text()
        self.run_async(
            lambda: self._service.start_monitor(name, target, baseline, interval),
            f"start monitor {name.strip()}",
            lambda status: self._after_change(
                f"monitor {status['name']} verifies {status['target']} every {interval:.0f} s"
            ),
        )

    def stop_selected(self) -> None:
        name = selected_cell(self._monitor_table)
        if name is None:
            self.report_error("select a monitor to stop")
            return
        self.run_async(
            lambda: self._service.stop_monitor(name),
            f"stop monitor {name}",
            lambda _status: self._after_change(f"monitor {name} stopped"),
        )

    def _after_change(self, message: str) -> None:
        self.report(message)
        self.refresh()

    def shutdown(self) -> None:
        """Stop the monitors this window started, so they do not outlive it."""
        stopped = self._service.stop_started()
        if stopped:
            self._log.append_line(f"{self.title}: stopped monitor(s) {', '.join(stopped)}")
        super().shutdown()
