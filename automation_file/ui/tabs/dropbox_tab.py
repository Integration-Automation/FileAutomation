"""Dropbox tab."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
)

from automation_file.remote.dropbox_api.client import dropbox_instance
from automation_file.remote.dropbox_api.delete_ops import dropbox_delete_path
from automation_file.remote.dropbox_api.download_ops import dropbox_download_file
from automation_file.remote.dropbox_api.list_ops import dropbox_list_folder
from automation_file.remote.dropbox_api.upload_ops import (
    dropbox_upload_dir,
    dropbox_upload_file,
)
from automation_file.ui.tabs.base import RemoteBackendTab


class DropboxTab(RemoteBackendTab):
    """Form-driven Dropbox operations."""

    def _init_group(self) -> QGroupBox:
        box = QGroupBox("Client")
        form = QFormLayout(box)
        self._token = QLineEdit()
        self._token.setEchoMode(QLineEdit.EchoMode.Password)
        self._token.setPlaceholderText("OAuth2 access token")
        form.addRow("Access token", self._token)
        btn = QPushButton("Initialise Dropbox client")
        btn.clicked.connect(self._on_init)
        form.addRow(btn)
        return box

    def _ops_group(self) -> QGroupBox:
        box = QGroupBox("Operations")
        form = QFormLayout(box)
        self._local = QLineEdit()
        self._remote = QLineEdit()
        self._recursive = QCheckBox("Recursive list")
        form.addRow("Local path", self._local)
        form.addRow("Remote path", self._remote)
        form.addRow(self._recursive)
        form.addRow(self.make_button("Upload file", self._on_upload_file))
        form.addRow(self.make_button("Upload dir", self._on_upload_dir))
        form.addRow(self.make_button("Download", self._on_download))
        form.addRow(self.make_button("Delete path", self._on_delete))
        form.addRow(self.make_button("List folder", self._on_list))
        return box

    def _on_init(self) -> None:
        token = self._token.text().strip()
        self.run_action(
            dropbox_instance.later_init,
            "dropbox.later_init",
            kwargs={"oauth2_access_token": token},
        )

    def _on_upload_file(self) -> None:
        self.run_action(
            dropbox_upload_file,
            f"dropbox_upload_file {self._local.text().strip()}",
            kwargs={
                "file_path": self._local.text().strip(),
                "remote_path": self._remote.text().strip(),
            },
        )

    def _on_upload_dir(self) -> None:
        self.run_action(
            dropbox_upload_dir,
            f"dropbox_upload_dir {self._local.text().strip()}",
            kwargs={
                "dir_path": self._local.text().strip(),
                "remote_prefix": self._remote.text().strip() or "/",
            },
        )

    def _on_download(self) -> None:
        self.run_action(
            dropbox_download_file,
            f"dropbox_download_file {self._remote.text().strip()}",
            kwargs={
                "remote_path": self._remote.text().strip(),
                "target_path": self._local.text().strip(),
            },
        )

    def _on_delete(self) -> None:
        self.run_action(
            dropbox_delete_path,
            f"dropbox_delete_path {self._remote.text().strip()}",
            kwargs={"remote_path": self._remote.text().strip()},
        )

    def _on_list(self) -> None:
        self.run_action(
            dropbox_list_folder,
            f"dropbox_list_folder {self._remote.text().strip()}",
            kwargs={
                "remote_path": self._remote.text().strip(),
                "recursive": self._recursive.isChecked(),
            },
        )
