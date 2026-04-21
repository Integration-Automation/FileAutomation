"""Google Drive tab — init credentials, upload, list, delete."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
)

from automation_file.remote.google_drive.client import driver_instance
from automation_file.remote.google_drive.delete_ops import drive_delete_file
from automation_file.remote.google_drive.download_ops import drive_download_file
from automation_file.remote.google_drive.search_ops import drive_search_all_file
from automation_file.remote.google_drive.upload_ops import drive_upload_to_drive
from automation_file.ui.tabs.base import RemoteBackendTab


class GoogleDriveTab(RemoteBackendTab):
    """Initialise Drive credentials and dispatch a subset of FA_drive_* ops."""

    def _init_group(self) -> QGroupBox:
        box = QGroupBox("Credentials")
        form = QFormLayout(box)
        self._token = QLineEdit()
        self._token.setPlaceholderText("token.json")
        self._creds = QLineEdit()
        self._creds.setPlaceholderText("credentials.json")
        form.addRow("Token path", self._token)
        form.addRow("Credentials path", self._creds)
        init_btn = QPushButton("Initialise Drive client")
        init_btn.clicked.connect(self._on_init)
        form.addRow(init_btn)
        return box

    def _ops_group(self) -> QGroupBox:
        box = QGroupBox("Operations")
        form = QFormLayout(box)
        self._upload_path = QLineEdit()
        form.addRow("Upload local file", self._upload_path)
        upload_btn = QPushButton("Upload")
        upload_btn.clicked.connect(self._on_upload)
        form.addRow(upload_btn)

        self._download_id = QLineEdit()
        self._download_name = QLineEdit()
        form.addRow("Download file_id", self._download_id)
        form.addRow("Save as", self._download_name)
        download_btn = QPushButton("Download")
        download_btn.clicked.connect(self._on_download)
        form.addRow(download_btn)

        self._delete_id = QLineEdit()
        form.addRow("Delete file_id", self._delete_id)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._on_delete)
        form.addRow(delete_btn)

        list_btn = QPushButton("List all files")
        list_btn.clicked.connect(self._on_list)
        form.addRow(list_btn)
        return box

    def _on_init(self) -> None:
        token = self._token.text().strip()
        creds = self._creds.text().strip()
        self.run_action(
            driver_instance.later_init,
            "drive.later_init",
            kwargs={"token_path": token, "credentials_path": creds},
        )

    def _on_upload(self) -> None:
        path = self._upload_path.text().strip()
        self.run_action(
            drive_upload_to_drive,
            f"drive_upload {path}",
            kwargs={"file_path": path},
        )

    def _on_download(self) -> None:
        file_id = self._download_id.text().strip()
        name = self._download_name.text().strip()
        self.run_action(
            drive_download_file,
            f"drive_download {file_id}",
            kwargs={"file_id": file_id, "file_name": name},
        )

    def _on_delete(self) -> None:
        file_id = self._delete_id.text().strip()
        self.run_action(
            drive_delete_file,
            f"drive_delete {file_id}",
            kwargs={"file_id": file_id},
        )

    def _on_list(self) -> None:
        self.run_action(drive_search_all_file, "drive_search_all_file")
