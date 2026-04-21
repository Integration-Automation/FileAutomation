"""Append-only activity log rendered in the main window footer."""

from __future__ import annotations

import time

from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QPlainTextEdit


class LogPanel(QPlainTextEdit):
    """Read-only text panel that timestamps and appends log lines."""

    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self.setPlaceholderText("Activity log — run an action to see output here.")

    def append_line(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.appendPlainText(f"[{stamp}] {message}")
        self.moveCursor(QTextCursor.MoveOperation.End)
