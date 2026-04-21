"""Cron scheduler management tab.

Lists active scheduled jobs, adds a new job from a cron expression plus an
inline JSON action list, and removes jobs individually or in bulk. All
dispatch goes through the shared :class:`ActionExecutor`.
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from automation_file.exceptions import FileAutomationException
from automation_file.scheduler import (
    schedule_add,
    schedule_list,
    schedule_remove,
    schedule_remove_all,
)
from automation_file.ui.tabs.base import BaseTab

_COLUMNS = ("Name", "Cron", "Actions", "Runs", "Last run")


class SchedulerTab(BaseTab):
    """Add / remove / list cron-scheduled jobs."""

    def __init__(self, log, pool) -> None:
        super().__init__(log, pool)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self._add_group())
        root.addWidget(self._list_group(), 1)
        self._refresh()

    def _add_group(self) -> QGroupBox:
        box = QGroupBox("Schedule a job")
        form = QFormLayout(box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)

        self._name = QLineEdit()
        self._name.setPlaceholderText("unique job name")
        self._cron = QLineEdit("*/5 * * * *")
        self._cron.setPlaceholderText("minute hour dom month dow  (e.g. */5 * * * *)")
        self._actions = QPlainTextEdit()
        self._actions.setPlaceholderText(
            '[["FA_create_file", {"file_path": "scheduled.txt", "content": "tick"}]]'
        )
        self._actions.setMinimumHeight(120)

        form.addRow("Name", self._name)
        form.addRow("Cron", self._cron)
        form.addRow("Actions (JSON)", self._actions)
        form.addRow(self.make_button("Add job", self._on_add))
        return box

    def _list_group(self) -> QGroupBox:
        box = QGroupBox("Active jobs")
        layout = QVBoxLayout(box)
        layout.setSpacing(8)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self._table)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.make_button("Refresh", self._refresh))
        row.addWidget(self.make_button("Remove selected", self._on_remove_selected))
        row.addWidget(self.make_button("Remove all", self._on_remove_all))
        row.addStretch()
        layout.addLayout(row)
        return box

    def _on_add(self) -> None:
        name = self._name.text().strip()
        cron = self._cron.text().strip()
        raw_actions = self._actions.toPlainText().strip()
        if not name or not cron or not raw_actions:
            self._log.append_line("scheduler: name, cron, and actions are all required")
            return
        try:
            action_list = json.loads(raw_actions)
        except json.JSONDecodeError as error:
            self._log.append_line(f"scheduler: invalid JSON: {error}")
            return
        if not isinstance(action_list, list):
            self._log.append_line("scheduler: action JSON must be an array")
            return
        try:
            snapshot = schedule_add(name, cron, action_list)
        except FileAutomationException as error:
            self._log.append_line(f"scheduler: add failed: {error!r}")
            return
        self._log.append_line(f"scheduler: added {snapshot}")
        self._refresh()

    def _on_remove_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            self._log.append_line("scheduler: no row selected")
            return
        name_item = self._table.item(row, 0)
        if name_item is None:
            return
        name = name_item.text()
        try:
            snapshot = schedule_remove(name)
        except FileAutomationException as error:
            self._log.append_line(f"scheduler: remove failed: {error!r}")
            return
        self._log.append_line(f"scheduler: removed {snapshot}")
        self._refresh()

    def _on_remove_all(self) -> None:
        snapshots = schedule_remove_all()
        self._log.append_line(f"scheduler: removed {len(snapshots)} job(s)")
        self._refresh()

    def _refresh(self) -> None:
        jobs = schedule_list()
        self._table.setRowCount(len(jobs))
        for row, data in enumerate(jobs):
            self._set_cell(row, 0, data["name"])
            self._set_cell(row, 1, data["cron"])
            self._set_cell(row, 2, str(data["actions"]))
            self._set_cell(row, 3, str(data["runs"]))
            self._set_cell(row, 4, data["last_run"] or "—")

    def _set_cell(self, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        self._table.setItem(row, col, item)

    def closeEvent(self, event: Any) -> None:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        schedule_remove_all()
        super().closeEvent(event)
