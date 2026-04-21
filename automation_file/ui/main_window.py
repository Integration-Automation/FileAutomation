"""Main window — tabbed interface over every built-in feature."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow, QSplitter, QTabWidget, QVBoxLayout, QWidget

from automation_file.logging_config import file_automation_logger
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.tabs import (
    HomeTab,
    JSONEditorTab,
    LocalOpsTab,
    ServerTab,
    TransferTab,
)

_WINDOW_TITLE = "automation_file"
_DEFAULT_SIZE = (1100, 780)
_STATUS_DEFAULT = "Ready"


class MainWindow(QMainWindow):
    """Tab-based control surface for every registered FA_* feature."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(_WINDOW_TITLE)
        self.resize(*_DEFAULT_SIZE)

        self._pool = QThreadPool.globalInstance()
        self._log = LogPanel()
        self._log.message_appended.connect(self._on_log_message)

        self._tabs = QTabWidget()
        self._home_tab = HomeTab(self._log, self._pool)
        self._home_tab.navigate_to_tab.connect(self._focus_tab_by_name)
        self._tabs.addTab(self._home_tab, "Home")
        self._tabs.addTab(LocalOpsTab(self._log, self._pool), "Local")
        self._tabs.addTab(TransferTab(self._log, self._pool), "Transfer")
        self._tabs.addTab(JSONEditorTab(self._log, self._pool), "JSON actions")
        self._server_tab = ServerTab(self._log, self._pool)
        self._tabs.addTab(self._server_tab, "Servers")

        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Vertical)
        splitter.addWidget(self._tabs)
        splitter.addWidget(self._log)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        self._register_shortcuts()
        self.statusBar().showMessage(_STATUS_DEFAULT)
        file_automation_logger.info("ui: main window constructed")

    def _register_shortcuts(self) -> None:
        for index in range(self._tabs.count()):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda i=index: self._tabs.setCurrentIndex(i))

    def _focus_tab_by_name(self, name: str) -> None:
        for index in range(self._tabs.count()):
            if self._tabs.tabText(index) == name:
                self._tabs.setCurrentIndex(index)
                return

    def _on_log_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)

    def closeEvent(self, event) -> None:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        self._server_tab.closeEvent(event)
        super().closeEvent(event)
