"""Main window — tabbed interface over every built-in feature."""

from __future__ import annotations

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QMainWindow, QSplitter, QTabWidget, QVBoxLayout, QWidget

from automation_file.logging_config import file_automation_logger
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.tabs import (
    ActionRunnerTab,
    AzureBlobTab,
    DropboxTab,
    GoogleDriveTab,
    HTTPDownloadTab,
    LocalOpsTab,
    S3Tab,
    ServerTab,
    SFTPTab,
)

_WINDOW_TITLE = "automation_file"
_DEFAULT_SIZE = (1100, 780)


class MainWindow(QMainWindow):
    """Tab-based control surface for every registered FA_* feature."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(_WINDOW_TITLE)
        self.resize(*_DEFAULT_SIZE)

        self._pool = QThreadPool.globalInstance()
        self._log = LogPanel()

        tabs = QTabWidget()
        tabs.addTab(LocalOpsTab(self._log, self._pool), "Local")
        tabs.addTab(HTTPDownloadTab(self._log, self._pool), "HTTP")
        tabs.addTab(GoogleDriveTab(self._log, self._pool), "Google Drive")
        tabs.addTab(S3Tab(self._log, self._pool), "S3")
        tabs.addTab(AzureBlobTab(self._log, self._pool), "Azure Blob")
        tabs.addTab(DropboxTab(self._log, self._pool), "Dropbox")
        tabs.addTab(SFTPTab(self._log, self._pool), "SFTP")
        tabs.addTab(ActionRunnerTab(self._log, self._pool), "JSON actions")
        self._server_tab = ServerTab(self._log, self._pool)
        tabs.addTab(self._server_tab, "Servers")

        splitter = QSplitter()
        splitter.setOrientation(splitter.orientation().Vertical)
        splitter.addWidget(tabs)
        splitter.addWidget(self._log)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        self.statusBar().showMessage("Ready")
        file_automation_logger.info("ui: main window constructed")

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt override
        self._server_tab.closeEvent(event)
        super().closeEvent(event)
