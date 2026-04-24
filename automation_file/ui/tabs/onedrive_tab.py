"""OneDrive tab."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
)

from automation_file.remote.onedrive.client import onedrive_instance
from automation_file.remote.onedrive.delete_ops import onedrive_delete_item
from automation_file.remote.onedrive.download_ops import onedrive_download_file
from automation_file.remote.onedrive.list_ops import onedrive_list_folder
from automation_file.remote.onedrive.upload_ops import (
    onedrive_upload_dir,
    onedrive_upload_file,
)
from automation_file.ui.tabs.base import RemoteBackendTab


class OneDriveTab(RemoteBackendTab):
    """Form-driven OneDrive operations (Microsoft Graph)."""

    def _init_group(self) -> QGroupBox:
        box = QGroupBox("Client")
        form = QFormLayout(box)
        self._token = QLineEdit()
        self._token.setEchoMode(QLineEdit.EchoMode.Password)
        self._token.setPlaceholderText("OAuth2 access token (from MSAL)")
        form.addRow("Access token", self._token)
        btn = QPushButton("Initialise OneDrive client")
        btn.clicked.connect(self._on_init)
        form.addRow(btn)
        self._client_id = QLineEdit()
        self._tenant_id = QLineEdit()
        self._tenant_id.setPlaceholderText("(optional)")
        form.addRow("MSAL client id", self._client_id)
        form.addRow("MSAL tenant id", self._tenant_id)
        device_btn = QPushButton("Device-code login")
        device_btn.clicked.connect(self._on_device_code)
        form.addRow(device_btn)
        return box

    def _ops_group(self) -> QGroupBox:
        box = QGroupBox("Operations")
        form = QFormLayout(box)
        self._local = QLineEdit()
        self._remote = QLineEdit()
        form.addRow("Local path", self._local)
        form.addRow("Remote path", self._remote)
        form.addRow(self.make_button("Upload file", self._on_upload_file))
        form.addRow(self.make_button("Upload dir", self._on_upload_dir))
        form.addRow(self.make_button("Download", self._on_download))
        form.addRow(self.make_button("Delete", self._on_delete))
        form.addRow(self.make_button("List folder", self._on_list))
        return box

    def _on_init(self) -> None:
        token = self._token.text().strip()
        self.run_action(
            onedrive_instance.later_init,
            "onedrive.later_init",
            kwargs={"access_token": token},
        )

    def _on_device_code(self) -> None:
        client_id = self._client_id.text().strip()
        tenant_id = self._tenant_id.text().strip() or None
        self.run_action(
            onedrive_instance.device_code_login,
            "onedrive.device_code_login",
            kwargs={"client_id": client_id, "tenant_id": tenant_id},
        )

    def _on_upload_file(self) -> None:
        self.run_action(
            onedrive_upload_file,
            f"onedrive_upload_file {self._local.text().strip()}",
            kwargs={
                "file_path": self._local.text().strip(),
                "remote_path": self._remote.text().strip(),
            },
        )

    def _on_upload_dir(self) -> None:
        self.run_action(
            onedrive_upload_dir,
            f"onedrive_upload_dir {self._local.text().strip()}",
            kwargs={
                "dir_path": self._local.text().strip(),
                "remote_prefix": self._remote.text().strip(),
            },
        )

    def _on_download(self) -> None:
        self.run_action(
            onedrive_download_file,
            f"onedrive_download_file {self._remote.text().strip()}",
            kwargs={
                "remote_path": self._remote.text().strip(),
                "target_path": self._local.text().strip(),
            },
        )

    def _on_delete(self) -> None:
        self.run_action(
            onedrive_delete_item,
            f"onedrive_delete_item {self._remote.text().strip()}",
            kwargs={"remote_path": self._remote.text().strip()},
        )

    def _on_list(self) -> None:
        self.run_action(
            onedrive_list_folder,
            f"onedrive_list_folder {self._remote.text().strip()}",
            kwargs={"remote_path": self._remote.text().strip()},
        )
