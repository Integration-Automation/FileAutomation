"""Tab widgets assembled by :class:`automation_file.ui.main_window.MainWindow`."""

from __future__ import annotations

from automation_file.ui.tabs.azure_tab import AzureBlobTab
from automation_file.ui.tabs.drive_tab import GoogleDriveTab
from automation_file.ui.tabs.dropbox_tab import DropboxTab
from automation_file.ui.tabs.http_tab import HTTPDownloadTab
from automation_file.ui.tabs.json_editor_tab import JSONEditorTab
from automation_file.ui.tabs.local_tab import LocalOpsTab
from automation_file.ui.tabs.s3_tab import S3Tab
from automation_file.ui.tabs.server_tab import ServerTab
from automation_file.ui.tabs.sftp_tab import SFTPTab
from automation_file.ui.tabs.transfer_tab import TransferTab

__all__ = [
    "AzureBlobTab",
    "DropboxTab",
    "GoogleDriveTab",
    "HTTPDownloadTab",
    "JSONEditorTab",
    "LocalOpsTab",
    "S3Tab",
    "SFTPTab",
    "ServerTab",
    "TransferTab",
]
