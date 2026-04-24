"""Box tab."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
)

from automation_file.remote.box.client import box_instance
from automation_file.remote.box.delete_ops import box_delete_file, box_delete_folder
from automation_file.remote.box.download_ops import box_download_file
from automation_file.remote.box.list_ops import box_list_folder
from automation_file.remote.box.upload_ops import box_upload_dir, box_upload_file
from automation_file.ui.tabs.base import RemoteBackendTab


class BoxTab(RemoteBackendTab):
    """Form-driven Box operations."""

    def _init_group(self) -> QGroupBox:
        box = QGroupBox("Client")
        form = QFormLayout(box)
        self._token = QLineEdit()
        self._token.setEchoMode(QLineEdit.EchoMode.Password)
        self._token.setPlaceholderText("OAuth2 access token")
        form.addRow("Access token", self._token)
        form.addRow(self.make_button("Initialise Box client", self._on_init))
        return box

    def _ops_group(self) -> QGroupBox:
        box = QGroupBox("Operations")
        form = QFormLayout(box)
        self._local = QLineEdit()
        self._folder_id = QLineEdit("0")
        self._file_id = QLineEdit()
        self._recursive = QCheckBox("Recursive delete")
        form.addRow("Local path", self._local)
        form.addRow("Folder id", self._folder_id)
        form.addRow("File id", self._file_id)
        form.addRow(self._recursive)
        form.addRow(self.make_button("Upload file", self._on_upload_file))
        form.addRow(self.make_button("Upload dir", self._on_upload_dir))
        form.addRow(self.make_button("Download", self._on_download))
        form.addRow(self.make_button("Delete file", self._on_delete_file))
        form.addRow(self.make_button("Delete folder", self._on_delete_folder))
        form.addRow(self.make_button("List folder", self._on_list))
        return box

    def _on_init(self) -> None:
        token = self._token.text().strip()
        self.run_action(
            box_instance.later_init,
            "box.later_init",
            kwargs={"access_token": token},
        )

    def _on_upload_file(self) -> None:
        self.run_action(
            box_upload_file,
            f"box_upload_file {self._local.text().strip()}",
            kwargs={
                "file_path": self._local.text().strip(),
                "parent_folder_id": self._folder_id.text().strip() or "0",
            },
        )

    def _on_upload_dir(self) -> None:
        self.run_action(
            box_upload_dir,
            f"box_upload_dir {self._local.text().strip()}",
            kwargs={
                "dir_path": self._local.text().strip(),
                "parent_folder_id": self._folder_id.text().strip() or "0",
            },
        )

    def _on_download(self) -> None:
        self.run_action(
            box_download_file,
            f"box_download_file {self._file_id.text().strip()}",
            kwargs={
                "file_id": self._file_id.text().strip(),
                "target_path": self._local.text().strip(),
            },
        )

    def _on_delete_file(self) -> None:
        self.run_action(
            box_delete_file,
            f"box_delete_file {self._file_id.text().strip()}",
            kwargs={"file_id": self._file_id.text().strip()},
        )

    def _on_delete_folder(self) -> None:
        self.run_action(
            box_delete_folder,
            f"box_delete_folder {self._folder_id.text().strip()}",
            kwargs={
                "folder_id": self._folder_id.text().strip(),
                "recursive": self._recursive.isChecked(),
            },
        )

    def _on_list(self) -> None:
        self.run_action(
            box_list_folder,
            f"box_list_folder {self._folder_id.text().strip()}",
            kwargs={"folder_id": self._folder_id.text().strip()},
        )
