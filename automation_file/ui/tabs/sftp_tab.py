"""SFTP tab (paramiko with RejectPolicy)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
)

from automation_file.remote.sftp.client import sftp_instance
from automation_file.remote.sftp.delete_ops import sftp_delete_path
from automation_file.remote.sftp.download_ops import sftp_download_file
from automation_file.remote.sftp.list_ops import sftp_list_dir
from automation_file.remote.sftp.upload_ops import sftp_upload_dir, sftp_upload_file
from automation_file.ui.tabs.base import RemoteBackendTab


class SFTPTab(RemoteBackendTab):
    """Form-driven SFTP operations."""

    def _init_group(self) -> QGroupBox:
        box = QGroupBox("Connection (host keys validated against known_hosts)")
        form = QFormLayout(box)
        self._host = QLineEdit()
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(22)
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_filename = QLineEdit()
        self._known_hosts = QLineEdit()
        self._known_hosts.setPlaceholderText("~/.ssh/known_hosts")
        form.addRow("Host", self._host)
        form.addRow("Port", self._port)
        form.addRow("Username", self._username)
        form.addRow("Password", self._password)
        form.addRow("Key filename", self._key_filename)
        form.addRow("known_hosts", self._known_hosts)

        connect_btn = QPushButton("Connect")
        connect_btn.clicked.connect(self._on_connect)
        close_btn = QPushButton("Close session")
        close_btn.clicked.connect(self._on_close)
        form.addRow(connect_btn)
        form.addRow(close_btn)
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
        form.addRow(self.make_button("Delete remote path", self._on_delete))
        form.addRow(self.make_button("List remote dir", self._on_list))
        return box

    def _on_connect(self) -> None:
        self.run_action(
            sftp_instance.later_init,
            f"sftp.later_init {self._host.text().strip()}",
            kwargs={
                "host": self._host.text().strip(),
                "username": self._username.text().strip(),
                "password": self._password.text().strip() or None,
                "key_filename": self._key_filename.text().strip() or None,
                "port": int(self._port.value()),
                "known_hosts": self._known_hosts.text().strip() or None,
            },
        )

    def _on_close(self) -> None:
        self.run_action(sftp_instance.close, "sftp.close")

    def _on_upload_file(self) -> None:
        self.run_action(
            sftp_upload_file,
            f"sftp_upload_file {self._local.text().strip()}",
            kwargs={
                "file_path": self._local.text().strip(),
                "remote_path": self._remote.text().strip(),
            },
        )

    def _on_upload_dir(self) -> None:
        self.run_action(
            sftp_upload_dir,
            f"sftp_upload_dir {self._local.text().strip()}",
            kwargs={
                "dir_path": self._local.text().strip(),
                "remote_prefix": self._remote.text().strip(),
            },
        )

    def _on_download(self) -> None:
        self.run_action(
            sftp_download_file,
            f"sftp_download_file {self._remote.text().strip()}",
            kwargs={
                "remote_path": self._remote.text().strip(),
                "target_path": self._local.text().strip(),
            },
        )

    def _on_delete(self) -> None:
        self.run_action(
            sftp_delete_path,
            f"sftp_delete_path {self._remote.text().strip()}",
            kwargs={"remote_path": self._remote.text().strip()},
        )

    def _on_list(self) -> None:
        self.run_action(
            sftp_list_dir,
            f"sftp_list_dir {self._remote.text().strip() or '.'}",
            kwargs={"remote_path": self._remote.text().strip() or "."},
        )
