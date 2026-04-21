"""File-watcher trigger management tab.

Lists active watchers, starts a new one from an inline JSON action list,
and stops watchers individually or as a batch. All dispatch still goes
through the shared :class:`ActionExecutor`; this tab is a thin GUI over
:mod:`automation_file.trigger`.
"""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
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
from automation_file.trigger import (
    trigger_manager,
    watch_start,
    watch_stop,
    watch_stop_all,
)
from automation_file.ui.tabs.base import BaseTab

_COLUMNS = ("Name", "Path", "Events", "Recursive", "Actions", "Running")


class TriggerTab(BaseTab):
    """Start / stop / list file-system watchers."""

    def __init__(self, log, pool) -> None:
        super().__init__(log, pool)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self._start_group())
        root.addWidget(self._list_group(), 1)
        self._refresh()

    def _start_group(self) -> QGroupBox:
        box = QGroupBox("Start a watcher")
        form = QFormLayout(box)
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)

        self._name = QLineEdit()
        self._name.setPlaceholderText("unique watcher name")
        self._path = QLineEdit()
        self._path.setPlaceholderText("absolute path to watch")
        self._events = QLineEdit("created,modified")
        self._events.setPlaceholderText("comma-separated: created,modified,deleted,moved")
        self._recursive = QCheckBox("Recursive")
        self._recursive.setChecked(True)
        self._actions = QPlainTextEdit()
        self._actions.setPlaceholderText(
            '[["FA_create_file", {"file_path": "triggered.txt", "content": "hi"}]]'
        )
        self._actions.setMinimumHeight(120)

        form.addRow("Name", self._name)
        form.addRow("Path", self._path)
        form.addRow("Events", self._events)
        form.addRow(self._recursive)
        form.addRow("Actions (JSON)", self._actions)
        form.addRow(self.make_button("Start watcher", self._on_start))
        return box

    def _list_group(self) -> QGroupBox:
        box = QGroupBox("Active watchers")
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
        row.addWidget(self.make_button("Stop selected", self._on_stop_selected))
        row.addWidget(self.make_button("Stop all", self._on_stop_all))
        row.addStretch()
        layout.addLayout(row)
        return box

    def _on_start(self) -> None:
        name = self._name.text().strip()
        path = self._path.text().strip()
        raw_events = [event.strip() for event in self._events.text().split(",") if event.strip()]
        raw_actions = self._actions.toPlainText().strip()
        if not name or not path or not raw_actions:
            self._log.append_line("trigger: name, path, and actions are all required")
            return
        try:
            action_list = json.loads(raw_actions)
        except json.JSONDecodeError as error:
            self._log.append_line(f"trigger: invalid JSON: {error}")
            return
        if not isinstance(action_list, list):
            self._log.append_line("trigger: action JSON must be an array")
            return
        try:
            snapshot = watch_start(
                name=name,
                path=path,
                action_list=action_list,
                events=raw_events or None,
                recursive=self._recursive.isChecked(),
            )
        except FileAutomationException as error:
            self._log.append_line(f"trigger: start failed: {error!r}")
            return
        self._log.append_line(f"trigger: started {snapshot}")
        self._refresh()

    def _on_stop_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            self._log.append_line("trigger: no row selected")
            return
        name_item = self._table.item(row, 0)
        if name_item is None:
            return
        name = name_item.text()
        try:
            snapshot = watch_stop(name)
        except FileAutomationException as error:
            self._log.append_line(f"trigger: stop failed: {error!r}")
            return
        self._log.append_line(f"trigger: stopped {snapshot}")
        self._refresh()

    def _on_stop_all(self) -> None:
        snapshots = watch_stop_all()
        self._log.append_line(f"trigger: stopped {len(snapshots)} watcher(s)")
        self._refresh()

    def _refresh(self) -> None:
        watchers = trigger_manager.list()
        self._table.setRowCount(len(watchers))
        for row, data in enumerate(watchers):
            self._set_cell(row, 0, data["name"])
            self._set_cell(row, 1, data["path"])
            self._set_cell(row, 2, ", ".join(data["events"]))
            self._set_cell(row, 3, "yes" if data["recursive"] else "no")
            self._set_cell(row, 4, str(data["actions"]))
            self._set_cell(row, 5, "yes" if data["running"] else "no")

    def _set_cell(self, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        self._table.setItem(row, col, item)

    def closeEvent(self, event: Any) -> None:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        watch_stop_all()
        super().closeEvent(event)
