"""Shared base class and helpers for the pages of the main window.

A page is a thin view over one service of :mod:`automation_file.app`. It reads
its widgets, calls the service off the UI thread through
:meth:`BasePage.run_async`, and shows what comes back. It imports nothing below
the application layer.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from automation_file.app import mask_text
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.worker import ActionWorker

EMPTY_CELL = "—"
_OK_STYLE = "color: #2f8f3f;"
_ERROR_STYLE = "color: #b3261e;"
_MUTED_STYLE = "color: #777;"


def cell_text(value: object) -> str:
    """Return what a table cell shows for ``value``."""
    if value is None or value == "":
        return EMPTY_CELL
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or EMPTY_CELL
    return str(value)


def make_table(columns: Sequence[str]) -> QTableWidget:
    """Build a read-only table that selects whole rows."""
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    return table


def fill_table(
    table: QTableWidget, rows: Sequence[Sequence[object]], *, keep_selection: bool = True
) -> None:
    """Replace the rows of ``table``; every value is shown through :func:`cell_text`.

    The selection follows the entry, not the row number: the row whose first
    cell reads the same as before stays selected, and when there is none (or
    ``keep_selection`` is false) nothing is selected. A button that acts on the
    selection can therefore never hit an entry that merely moved into its row.
    """
    selected = selected_cell(table) if keep_selection else None
    table.setRowCount(len(rows))
    for row, values in enumerate(rows):
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(cell_text(value)))
    table.clearSelection()
    table.setCurrentCell(-1, -1)
    if selected is None:
        return
    for row, values in enumerate(rows):
        if values and cell_text(values[0]) == selected:
            table.selectRow(row)
            return


def selected_cell(table: QTableWidget, column: int = 0) -> str | None:
    """Return the text of ``column`` in the selected row, or ``None`` without a selection."""
    row = table.currentRow()
    item = table.item(row, column) if row >= 0 else None
    return None if item is None else item.text()


class BasePage(QWidget):
    """Common behaviour of every page: background calls, a status line, the activity log."""

    #: The navigation entry of the page; it prefixes the page's log lines.
    title = ""

    def __init__(self, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__()
        self._log = log
        self._pool = pool
        self._workers: set[ActionWorker] = set()
        self._in_flight: set[str] = set()
        self._closed = False
        self._status = QLabel("")
        self._status.setWordWrap(True)

    # ------------------------------------------------------------------ lifecycle

    def refresh(self) -> None:
        """Read the page's data again. The default page has none."""

    def on_shown(self) -> None:
        """Called by the main window when the page becomes the visible one."""
        self.refresh()

    def shutdown(self) -> None:
        """Called by the main window when it closes: results that arrive later are dropped."""
        self._closed = True

    # ------------------------------------------------------------------ background work

    def run_async(
        self,
        target: Callable[..., Any],
        label: str,
        on_done: Callable[[Any], None] | None = None,
        *,
        key: str | None = None,
        quiet: bool = False,
        on_error: Callable[[], None] | None = None,
    ) -> bool:
        """Call ``target()`` on the thread pool and hand its result to ``on_done`` on the UI thread.

        With ``key``, a call is skipped (and ``False`` returned) while an earlier
        call with the same key is still running: a timer cannot pile up requests.
        ``quiet`` keeps the start of the call out of the activity log; a failure
        is always logged and shown on the status line, and then ``on_error`` is
        called, for a page that has to stop something when a call fails.
        """
        if key is not None:
            if key in self._in_flight:
                return False
            self._in_flight.add(key)
        worker = ActionWorker(target, label=f"{self.title}: {label}")
        self._workers.add(worker)
        if not quiet:
            self._log.append_line(f"{self.title}: {label} ...")
        worker.signals.finished.connect(
            lambda result: self._on_finished(worker, key, on_done, result)
        )
        worker.signals.failed.connect(
            lambda error: self._on_failed(worker, key, f"{label} failed: {error}", on_error)
        )
        self._pool.start(worker)
        return True

    def _release(self, worker: ActionWorker, key: str | None) -> None:
        self._workers.discard(worker)
        if key is not None:
            self._in_flight.discard(key)

    def _on_finished(
        self,
        worker: ActionWorker,
        key: str | None,
        on_done: Callable[[Any], None] | None,
        result: Any,
    ) -> None:
        self._release(worker, key)
        if not self._closed and on_done is not None:
            on_done(result)

    def _on_failed(
        self,
        worker: ActionWorker,
        key: str | None,
        message: str,
        on_error: Callable[[], None] | None,
    ) -> None:
        self._release(worker, key)
        if self._closed:
            return
        self.report_error(message)
        if on_error is not None:
            on_error()

    # ------------------------------------------------------------------ feedback

    def status_label(self) -> QLabel:
        """Return the page's status line, for the page to place in its layout."""
        return self._status

    def status_text(self) -> str:
        """Return what the status line currently says."""
        return self._status.text()

    def report(self, message: str) -> None:
        """Show ``message`` on the status line and append it to the activity log."""
        self._set_status(message, _OK_STYLE)

    def report_error(self, message: str) -> None:
        """Show ``message`` as a failure on the status line and in the activity log."""
        self._set_status(message, _ERROR_STYLE)

    def _set_status(self, message: str, style: str) -> None:
        shown = mask_text(message)
        self._status.setStyleSheet(style)
        self._status.setText(shown)
        self._log.append_line(f"{self.title}: {shown}")

    def confirm(self, question: str) -> bool:
        """Ask the user to confirm something that cannot be undone."""
        answer = QMessageBox.question(self, self.title, question)
        return answer == QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------------ small widgets

    @staticmethod
    def make_button(label: str, handler: Callable[[], Any]) -> QPushButton:
        """Build a ``QPushButton`` that calls ``handler`` when clicked."""
        button = QPushButton(label)
        button.clicked.connect(lambda _checked=False: handler())
        return button

    @staticmethod
    def muted_label(text: str) -> QLabel:
        """Build a word-wrapped explanatory label."""
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet(_MUTED_STYLE)
        return label

    def pick_directory(self) -> str | None:
        """Let the user choose a directory; ``None`` when the dialog is cancelled."""
        return QFileDialog.getExistingDirectory(self, "Select directory") or None

    def pick_open_file(self, caption: str, name_filter: str = "") -> str | None:
        """Let the user choose an existing file; ``None`` when the dialog is cancelled."""
        return QFileDialog.getOpenFileName(self, caption, "", name_filter)[0] or None

    def pick_save_file(self, caption: str, name_filter: str = "") -> str | None:
        """Let the user choose where to save; ``None`` when the dialog is cancelled."""
        return QFileDialog.getSaveFileName(self, caption, "", name_filter)[0] or None
