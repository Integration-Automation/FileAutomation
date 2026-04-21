"""Tab widgets assembled by :class:`automation_file.ui.main_window.MainWindow`."""

from __future__ import annotations

from automation_file.ui.tabs.action_tab import ActionRunnerTab
from automation_file.ui.tabs.azure_tab import AzureBlobTab
from automation_file.ui.tabs.drive_tab import GoogleDriveTab
from automation_file.ui.tabs.dropbox_tab import DropboxTab
from automation_file.ui.tabs.http_tab import HTTPDownloadTab
from automation_file.ui.tabs.local_tab import LocalOpsTab
from automation_file.ui.tabs.s3_tab import S3Tab
from automation_file.ui.tabs.server_tab import ServerTab
from automation_file.ui.tabs.sftp_tab import SFTPTab

__all__ = [
    "ActionRunnerTab",
    "AzureBlobTab",
    "DropboxTab",
    "GoogleDriveTab",
    "HTTPDownloadTab",
    "LocalOpsTab",
    "S3Tab",
    "SFTPTab",
    "ServerTab",
]
