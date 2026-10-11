"""Audit page: point the audit trail at a database, then search and count its records."""

from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
)

from automation_file.app import AuditService
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.pages.base import BasePage, fill_table, make_table

_COLUMNS = ("Time", "Actor", "Source", "Action", "Resource", "Status", "Duration (ms)", "Error")
_KEYS = ("timestamp", "actor", "source", "action", "resource", "status", "duration_ms", "error")
#: Filter name -> (label, placeholder); the order is the order of the form.
_FILTERS: dict[str, tuple[str, str]] = {
    "text": ("Contains", "text in the action, resource, error or metadata"),
    "status": ("Status", "ok, warning, error ..."),
    "action": ("Action", "pipeline.failed, upload ..."),
    "actor": ("Actor", ""),
    "source": ("Source", "pipeline, storage, scheduler ..."),
    "pipeline": ("Pipeline", ""),
    "task": ("Task", ""),
    "backend": ("Backend", "s3, local ..."),
    "resource_prefix": ("Resource starts with", "s3://reports/"),
    "correlation_id": ("Run / correlation ID", ""),
    "since": ("Since", "2026-10-01T00:00:00+00:00"),
    "until": ("Until", "2026-10-08T00:00:00+00:00"),
}
_COLUMNS_PER_ROW = 3
_DEFAULT_LIMIT = 100
_MAX_LIMIT = 10_000


class AuditPage(BasePage):
    """Who did what, when, against which resource, with what result."""

    title = "Audit"

    def __init__(self, service: AuditService, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._service = service
        self._records: list[dict[str, Any]] = []
        self._fields: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(self._configure_group())
        root.addWidget(self._filter_group())
        splitter = QSplitter()
        splitter.addWidget(self._results_group())
        splitter.addWidget(self._detail_group())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)
        root.addWidget(self.status_label())

    # ------------------------------------------------------------------ layout

    def _configure_group(self) -> QGroupBox:
        box = QGroupBox("Audit trail")
        form = QFormLayout(box)
        self._state = QLabel("Not read yet")
        self._db_path = QLineEdit()
        self._db_path.setPlaceholderText("SQLite database of the audit trail; created when missing")
        row = QHBoxLayout()
        row.addWidget(self._db_path, 1)
        row.addWidget(self.make_button("Browse…", self._on_browse))
        row.addWidget(self.make_button("Configure", self.configure))
        form.addRow("State", self._state)
        form.addRow("Database", row)
        return box

    def _filter_group(self) -> QGroupBox:
        box = QGroupBox("Search")
        layout = QVBoxLayout(box)
        grid = QGridLayout()
        for index, (name, (label, placeholder)) in enumerate(_FILTERS.items()):
            field = QLineEdit()
            field.setPlaceholderText(placeholder)
            field.returnPressed.connect(self.search)
            self._fields[name] = field
            row, column = divmod(index, _COLUMNS_PER_ROW)
            grid.addWidget(QLabel(label), row, column * 2)
            grid.addWidget(field, row, column * 2 + 1)
        layout.addLayout(grid)
        buttons = QHBoxLayout()
        self._limit = QSpinBox()
        self._limit.setRange(1, _MAX_LIMIT)
        self._limit.setValue(_DEFAULT_LIMIT)
        buttons.addWidget(QLabel("Limit"))
        buttons.addWidget(self._limit)
        buttons.addWidget(self.make_button("Search", self.search))
        buttons.addWidget(self.make_button("Count", self.count))
        buttons.addWidget(self.make_button("Clear filters", self.clear_filters))
        buttons.addStretch()
        layout.addLayout(buttons)
        return box

    def _results_group(self) -> QGroupBox:
        box = QGroupBox("Records (newest first)")
        layout = QVBoxLayout(box)
        self._table = make_table(_COLUMNS)
        self._table.itemSelectionChanged.connect(self._on_selection)
        layout.addWidget(self._table)
        return box

    def _detail_group(self) -> QGroupBox:
        box = QGroupBox("Selected record")
        layout = QVBoxLayout(box)
        self._detail = QPlainTextEdit()
        self._detail.setReadOnly(True)
        layout.addWidget(self._detail)
        return box

    # ------------------------------------------------------------------ configuration

    def refresh(self) -> None:
        self.run_async(
            self._service.status, "read state", self._show_state, key="state", quiet=True
        )

    def _show_state(self, state: dict[str, Any]) -> None:
        if not state.get("configured"):
            self._state.setText("Not configured: nothing is recorded yet")
            return
        where = state.get("db_path") or state.get("store")
        recording = "recording" if state.get("active") else "configured, not recording"
        self._state.setText(f"{recording} into {where}")
        if state.get("db_path") and not self._db_path.text():
            self._db_path.setText(str(state["db_path"]))

    def _on_browse(self) -> None:
        chosen = self.pick_save_file(
            "Audit database", "SQLite database (*.sqlite *.db);;All files (*)"
        )
        if chosen:
            self._db_path.setText(chosen)

    def configure(self) -> None:
        path = self._db_path.text().strip()
        if not path:
            self.report_error("enter the path of the audit database first")
            return
        self.run_async(lambda: self._service.configure(path), "configure", self._configured)

    def _configured(self, state: dict[str, Any]) -> None:
        self._show_state(state)
        self.report(f"audit records go to {state.get('db_path') or state.get('store')}")

    # ------------------------------------------------------------------ search

    def set_filter(self, name: str, value: str) -> None:
        """Fill in one filter field."""
        self._fields[name].setText(value)

    def filters(self) -> dict[str, Any]:
        """Return the filters as the form holds them; an empty field is left out."""
        return {
            name: field.text().strip()
            for name, field in self._fields.items()
            if field.text().strip()
        }

    def clear_filters(self) -> None:
        for field in self._fields.values():
            field.clear()

    def records(self) -> list[dict[str, Any]]:
        """Return the records the table shows."""
        return list(self._records)

    def search(self) -> None:
        filters = {**self.filters(), "limit": self._limit.value()}
        self.run_async(lambda: self._service.search(**filters), "search", self._show_records)

    def count(self) -> None:
        filters = self.filters()
        self.run_async(
            lambda: self._service.count(**filters),
            "count",
            lambda found: self.report(f"{found} record(s) match"),
        )

    def _show_records(self, records: list[dict[str, Any]]) -> None:
        self._records = records
        fill_table(
            self._table,
            [[record.get(key) for key in _KEYS] for record in records],
            keep_selection=False,
        )
        self._detail.clear()
        self.report(f"{len(records)} record(s) shown")

    def _on_selection(self) -> None:
        row = self._table.currentRow()
        if 0 <= row < len(self._records):
            self._detail.setPlainText(
                json.dumps(self._records[row], indent=2, ensure_ascii=False, default=str)
            )

    def detail_text(self) -> str:
        """Return what the detail pane shows."""
        return self._detail.toPlainText()
