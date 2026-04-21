"""Shared base class for UI tabs.

Each tab gets a reference to the main window's :class:`LogPanel` plus a
:class:`QThreadPool` so long-running actions stay off the GUI thread.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

from automation_file.ui.log_widget import LogPanel
from automation_file.ui.worker import ActionWorker


class BaseTab(QWidget):
    """Common helpers for every feature tab."""

    def __init__(self, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__()
        self._log = log
        self._pool = pool

    def run_action(
        self,
        target: Callable[..., Any],
        label: str,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        worker = ActionWorker(target, args=args, kwargs=kwargs, label=label)
        worker.signals.log.connect(self._log.append_line)
        worker.signals.finished.connect(
            lambda result: self._log.append_line(f"result:  {label} -> {result!r}")
        )
        self._pool.start(worker)

    @staticmethod
    def path_picker_row(
        line_edit: QLineEdit,
        button_text: str,
        pick: Callable[[QWidget], str | None],
    ) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(line_edit)
        button = QPushButton(button_text)

        def _on_click() -> None:
            chosen = pick(line_edit)
            if chosen:
                line_edit.setText(chosen)

        button.clicked.connect(_on_click)
        row.addWidget(button)
        return row

    @staticmethod
    def pick_existing_file(parent: QWidget) -> str | None:
        path, _ = QFileDialog.getOpenFileName(parent, "Select file")
        return path or None

    @staticmethod
    def pick_save_file(parent: QWidget) -> str | None:
        path, _ = QFileDialog.getSaveFileName(parent, "Save as")
        return path or None

    @staticmethod
    def pick_directory(parent: QWidget) -> str | None:
        path = QFileDialog.getExistingDirectory(parent, "Select directory")
        return path or None
