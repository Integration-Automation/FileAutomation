"""Transfer progress + cancel management tab.

Polls :data:`~automation_file.core.progress.progress_registry` on a timer and
renders one row per active / finished transfer. Users can cancel a running
transfer or clear completed rows.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from automation_file.core.progress import (
    progress_clear,
    progress_list,
    progress_registry,
)
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.tabs.base import BaseTab

_REFRESH_INTERVAL_MS = 500
_COLUMNS = ("Name", "Status", "Progress", "Transferred", "Total")


class ProgressTab(BaseTab):
    """Live view of every registered transfer."""

    def __init__(self, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self._table_group(), 1)

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _table_group(self) -> QGroupBox:
        box = QGroupBox("Transfers")
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
        row.addWidget(self.make_button("Cancel selected", self._on_cancel_selected))
        row.addWidget(self.make_button("Clear finished", self._on_clear_finished))
        row.addStretch()
        layout.addLayout(row)
        return box

    def _on_cancel_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            self._log.append_line("progress: no row selected")
            return
        name_item = self._table.item(row, 0)
        if name_item is None:
            return
        name = name_item.text()
        if progress_registry.cancel(name):
            self._log.append_line(f"progress: cancel requested for {name!r}")
        else:
            self._log.append_line(f"progress: no such transfer: {name!r}")

    def _on_clear_finished(self) -> None:
        dropped = progress_clear()
        self._log.append_line(f"progress: cleared {dropped} finished transfer(s)")
        self._refresh()

    def _refresh(self) -> None:
        snapshots = progress_list()
        self._table.setRowCount(len(snapshots))
        for row, data in enumerate(snapshots):
            self._set_cell(row, 0, data["name"])
            self._set_cell(row, 1, data["status"])
            self._table.setCellWidget(row, 2, self._progress_widget(data))
            self._set_cell(row, 3, _format_bytes(data["transferred"]))
            total = data["total"]
            self._set_cell(row, 4, _format_bytes(total) if total else "unknown")

    def _progress_widget(self, data: dict[str, Any]) -> QProgressBar:
        bar = QProgressBar()
        total = data["total"]
        transferred = data["transferred"]
        if total and total > 0:
            bar.setRange(0, int(total))
            bar.setValue(min(int(transferred), int(total)))
        else:
            bar.setRange(0, 0)  # busy indicator
        return bar

    def _set_cell(self, row: int, col: int, text: str) -> None:
        self._table.setItem(row, col, QTableWidgetItem(text))


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "—"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"
