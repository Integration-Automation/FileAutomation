"""Unified transfer tab — sidebar of remote backends over one stack.

Collapses the six remote-backend tabs (HTTP, Google Drive, S3, Azure
Blob, Dropbox, SFTP) into a single tab with a sidebar picker. The
existing per-backend widgets are reused verbatim as the stack pages
so feature parity is preserved.
"""

from __future__ import annotations

from typing import NamedTuple

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QWidget,
)

from automation_file.ui.log_widget import LogPanel
from automation_file.ui.tabs.azure_tab import AzureBlobTab
from automation_file.ui.tabs.base import BaseTab
from automation_file.ui.tabs.box_tab import BoxTab
from automation_file.ui.tabs.drive_tab import GoogleDriveTab
from automation_file.ui.tabs.dropbox_tab import DropboxTab
from automation_file.ui.tabs.http_tab import HTTPDownloadTab
from automation_file.ui.tabs.onedrive_tab import OneDriveTab
from automation_file.ui.tabs.s3_tab import S3Tab
from automation_file.ui.tabs.sftp_tab import SFTPTab


class _BackendEntry(NamedTuple):
    label: str
    factory: type[BaseTab]


_BACKENDS: tuple[_BackendEntry, ...] = (
    _BackendEntry("HTTP download", HTTPDownloadTab),
    _BackendEntry("Google Drive", GoogleDriveTab),
    _BackendEntry("Amazon S3", S3Tab),
    _BackendEntry("Azure Blob", AzureBlobTab),
    _BackendEntry("Dropbox", DropboxTab),
    _BackendEntry("SFTP", SFTPTab),
    _BackendEntry("OneDrive", OneDriveTab),
    _BackendEntry("Box", BoxTab),
)


class TransferTab(BaseTab):
    """Sidebar-selectable container for every remote backend."""

    def __init__(self, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._sidebar = QListWidget()
        self._sidebar.setFixedWidth(180)
        self._stack = QStackedWidget()
        for entry in _BACKENDS:
            self._sidebar.addItem(QListWidgetItem(entry.label))
            self._stack.addWidget(entry.factory(log, pool))
        self._sidebar.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._sidebar.setCurrentRow(0)

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addWidget(self._sidebar)
        root.addWidget(self._stack, 1)

    def current_backend(self) -> str:
        row = self._sidebar.currentRow()
        return _BACKENDS[row].label if 0 <= row < len(_BACKENDS) else ""

    def select_backend(self, label: str) -> bool:
        for index, entry in enumerate(_BACKENDS):
            if entry.label == label:
                self._sidebar.setCurrentRow(index)
                return True
        return False

    def inner_widget(self, label: str) -> QWidget | None:
        for index, entry in enumerate(_BACKENDS):
            if entry.label == label:
                return self._stack.widget(index)
        return None
