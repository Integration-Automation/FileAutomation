"""Azure Blob Storage tab."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
)

from automation_file.remote.azure_blob.client import azure_blob_instance
from automation_file.remote.azure_blob.delete_ops import azure_blob_delete_blob
from automation_file.remote.azure_blob.download_ops import azure_blob_download_file
from automation_file.remote.azure_blob.list_ops import azure_blob_list_container
from automation_file.remote.azure_blob.upload_ops import (
    azure_blob_upload_dir,
    azure_blob_upload_file,
)
from automation_file.ui.tabs.base import RemoteBackendTab


class AzureBlobTab(RemoteBackendTab):
    """Form-driven Azure Blob operations."""

    def _init_group(self) -> QGroupBox:
        box = QGroupBox("Client")
        form = QFormLayout(box)
        self._conn_string = QLineEdit()
        self._conn_string.setEchoMode(QLineEdit.EchoMode.Password)
        self._account_url = QLineEdit()
        form.addRow("Connection string", self._conn_string)
        form.addRow("Account URL (fallback)", self._account_url)
        btn = QPushButton("Initialise Azure client")
        btn.clicked.connect(self._on_init)
        form.addRow(btn)
        return box

    def _ops_group(self) -> QGroupBox:
        box = QGroupBox("Operations")
        form = QFormLayout(box)
        self._local = QLineEdit()
        self._container = QLineEdit()
        self._blob = QLineEdit()
        form.addRow("Local path", self._local)
        form.addRow("Container", self._container)
        form.addRow("Blob name / prefix", self._blob)
        form.addRow(self.make_button("Upload file", self._on_upload_file))
        form.addRow(self.make_button("Upload dir", self._on_upload_dir))
        form.addRow(self.make_button("Download to local", self._on_download))
        form.addRow(self.make_button("Delete blob", self._on_delete))
        form.addRow(self.make_button("List container", self._on_list))
        return box

    def _on_init(self) -> None:
        conn = self._conn_string.text().strip()
        account = self._account_url.text().strip()
        self.run_action(
            azure_blob_instance.later_init,
            "azure_blob.later_init",
            kwargs={"connection_string": conn or None, "account_url": account or None},
        )

    def _on_upload_file(self) -> None:
        self.run_action(
            azure_blob_upload_file,
            f"azure_blob_upload_file {self._local.text().strip()}",
            kwargs={
                "file_path": self._local.text().strip(),
                "container": self._container.text().strip(),
                "blob_name": self._blob.text().strip(),
            },
        )

    def _on_upload_dir(self) -> None:
        self.run_action(
            azure_blob_upload_dir,
            f"azure_blob_upload_dir {self._local.text().strip()}",
            kwargs={
                "dir_path": self._local.text().strip(),
                "container": self._container.text().strip(),
                "name_prefix": self._blob.text().strip(),
            },
        )

    def _on_download(self) -> None:
        self.run_action(
            azure_blob_download_file,
            f"azure_blob_download_file {self._blob.text().strip()}",
            kwargs={
                "container": self._container.text().strip(),
                "blob_name": self._blob.text().strip(),
                "target_path": self._local.text().strip(),
            },
        )

    def _on_delete(self) -> None:
        self.run_action(
            azure_blob_delete_blob,
            f"azure_blob_delete_blob {self._blob.text().strip()}",
            kwargs={
                "container": self._container.text().strip(),
                "blob_name": self._blob.text().strip(),
            },
        )

    def _on_list(self) -> None:
        self.run_action(
            azure_blob_list_container,
            f"azure_blob_list_container {self._container.text().strip()}",
            kwargs={
                "container": self._container.text().strip(),
                "name_prefix": self._blob.text().strip(),
            },
        )
