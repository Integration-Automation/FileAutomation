"""Amazon S3 tab — initialise the client, upload, download, delete, list."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
)

from automation_file.remote.s3.client import s3_instance
from automation_file.remote.s3.delete_ops import s3_delete_object
from automation_file.remote.s3.download_ops import s3_download_file
from automation_file.remote.s3.list_ops import s3_list_bucket
from automation_file.remote.s3.upload_ops import s3_upload_dir, s3_upload_file
from automation_file.ui.tabs.base import RemoteBackendTab


class S3Tab(RemoteBackendTab):
    """Form-driven S3 operations. Secrets default to the AWS credential chain."""

    def _init_group(self) -> QGroupBox:
        box = QGroupBox("Client (leave blank to use the default AWS chain)")
        form = QFormLayout(box)
        self._access_key = QLineEdit()
        self._secret_key = QLineEdit()
        self._secret_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._region = QLineEdit()
        self._endpoint = QLineEdit()
        form.addRow("Access key ID", self._access_key)
        form.addRow("Secret access key", self._secret_key)
        form.addRow("Region", self._region)
        form.addRow("Endpoint URL", self._endpoint)
        btn = QPushButton("Initialise S3 client")
        btn.clicked.connect(self._on_init)
        form.addRow(btn)
        return box

    def _ops_group(self) -> QGroupBox:
        box = QGroupBox("Operations")
        form = QFormLayout(box)
        self._local = QLineEdit()
        self._bucket = QLineEdit()
        self._key = QLineEdit()
        form.addRow("Local path", self._local)
        form.addRow("Bucket", self._bucket)
        form.addRow("Key / prefix", self._key)

        form.addRow(self.make_button("Upload file", self._on_upload_file))
        form.addRow(self.make_button("Upload dir", self._on_upload_dir))
        form.addRow(self.make_button("Download to local", self._on_download))
        form.addRow(self.make_button("Delete object", self._on_delete))
        form.addRow(self.make_button("List bucket", self._on_list))
        return box

    def _on_init(self) -> None:
        self.run_action(
            s3_instance.later_init,
            "s3.later_init",
            kwargs={
                "aws_access_key_id": self._access_key.text().strip() or None,
                "aws_secret_access_key": self._secret_key.text().strip() or None,
                "region_name": self._region.text().strip() or None,
                "endpoint_url": self._endpoint.text().strip() or None,
            },
        )

    def _on_upload_file(self) -> None:
        self.run_action(
            s3_upload_file,
            f"s3_upload_file {self._local.text().strip()}",
            kwargs={
                "file_path": self._local.text().strip(),
                "bucket": self._bucket.text().strip(),
                "key": self._key.text().strip(),
            },
        )

    def _on_upload_dir(self) -> None:
        self.run_action(
            s3_upload_dir,
            f"s3_upload_dir {self._local.text().strip()}",
            kwargs={
                "dir_path": self._local.text().strip(),
                "bucket": self._bucket.text().strip(),
                "key_prefix": self._key.text().strip(),
            },
        )

    def _on_download(self) -> None:
        self.run_action(
            s3_download_file,
            f"s3_download_file {self._key.text().strip()}",
            kwargs={
                "bucket": self._bucket.text().strip(),
                "key": self._key.text().strip(),
                "target_path": self._local.text().strip(),
            },
        )

    def _on_delete(self) -> None:
        self.run_action(
            s3_delete_object,
            f"s3_delete_object {self._key.text().strip()}",
            kwargs={"bucket": self._bucket.text().strip(), "key": self._key.text().strip()},
        )

    def _on_list(self) -> None:
        self.run_action(
            s3_list_bucket,
            f"s3_list_bucket {self._bucket.text().strip()}",
            kwargs={"bucket": self._bucket.text().strip(), "prefix": self._key.text().strip()},
        )
