"""Scheduler page: list, add and remove cron jobs."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from automation_file.app import SchedulerService
from automation_file.exceptions import FileAutomationException
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.pages.base import BasePage, fill_table, make_table, selected_cell

_COLUMNS = ("Name", "Cron", "Actions", "Runs", "Last run", "Running", "Skipped")
_KEYS = ("name", "cron", "actions", "runs", "last_run", "running", "skipped")


class SchedulerPage(BasePage):
    """Cron jobs of the process-wide scheduler, through the Scheduler service."""

    title = "Scheduler"

    def __init__(self, service: SchedulerService, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._service = service
        self._jobs: list[dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(self._add_group())
        root.addWidget(self._list_group(), 1)
        root.addWidget(self.status_label())

    def _add_group(self) -> QGroupBox:
        box = QGroupBox("Schedule a job")
        form = QFormLayout(box)
        self._name = QLineEdit()
        self._name.setPlaceholderText("unique job name")
        self._cron = QLineEdit("*/5 * * * *")
        self._cron.setPlaceholderText("minute hour day-of-month month day-of-week")
        self._actions = QPlainTextEdit()
        self._actions.setPlaceholderText(
            '[["FA_pipeline_run", {"definition": "pipelines/daily-report.yaml"}]]'
        )
        self._actions.setMinimumHeight(100)
        self._overlap = QCheckBox("Start a run even while the previous one is still going")
        form.addRow("Name", self._name)
        form.addRow("Cron", self._cron)
        form.addRow("Actions (JSON)", self._actions)
        form.addRow(self._overlap)
        form.addRow(self.make_button("Add job", self.add_job))
        return box

    def _list_group(self) -> QGroupBox:
        box = QGroupBox("Jobs")
        layout = QVBoxLayout(box)
        self._table = make_table(_COLUMNS)
        layout.addWidget(self._table)
        row = QHBoxLayout()
        row.addWidget(self.make_button("Refresh", self.refresh))
        row.addWidget(self.make_button("Remove selected", self.remove_selected))
        row.addWidget(self.make_button("Remove all", self.remove_all))
        row.addStretch()
        layout.addLayout(row)
        return box

    def jobs(self) -> list[dict[str, Any]]:
        """Return the jobs the table shows."""
        return list(self._jobs)

    def refresh(self) -> None:
        self.run_async(self._service.jobs, "read jobs", self._show, key="refresh", quiet=True)

    def _show(self, jobs: list[dict[str, Any]]) -> None:
        self._jobs = jobs
        fill_table(self._table, [[job.get(key) for key in _KEYS] for job in jobs])

    def add_job(self) -> None:
        name = self._name.text()
        cron = self._cron.text()
        actions = self._actions.toPlainText()
        overlap = self._overlap.isChecked()
        self.run_async(
            lambda: self._service.add(name, cron, actions, overlap),
            f"add job {name.strip()}",
            lambda job: self._after_change(f"added job {job.get('name')} ({job.get('cron')})"),
        )

    def remove_selected(self) -> None:
        name = selected_cell(self._table)
        if name is None:
            self.report_error("select a job to remove")
            return
        self.run_async(
            lambda: self._service.remove(name),
            f"remove job {name}",
            lambda _job: self._after_change(f"removed job {name}"),
        )

    def remove_all(self) -> None:
        self.run_async(
            self._service.remove_all,
            "remove all jobs",
            lambda jobs: self._after_change(f"removed {len(jobs)} job(s)"),
        )

    def _after_change(self, message: str) -> None:
        self.report(message)
        self.refresh()

    def shutdown(self) -> None:
        """Remove the jobs when the window closes, as the scheduler tab always did."""
        try:
            self._service.remove_all()
        except FileAutomationException as error:
            self._log.append_line(f"{self.title}: could not remove the jobs: {error}")
        super().shutdown()
