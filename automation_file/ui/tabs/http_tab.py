"""HTTP download tab (SSRF-validated, retrying)."""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLineEdit, QPushButton, QVBoxLayout

from automation_file.remote.http_download import download_file
from automation_file.ui.tabs.base import BaseTab


class HTTPDownloadTab(BaseTab):
    """Trigger :func:`download_file` from a URL + destination form."""

    def __init__(self, log, pool) -> None:
        super().__init__(log, pool)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        form.setHorizontalSpacing(12)
        self._url = QLineEdit()
        self._url.setPlaceholderText("https://example.com/file.bin")
        self._dest = QLineEdit()
        self._dest.setPlaceholderText("local filename")
        form.addRow("URL", self._url)
        form.addRow("Save as", self._dest)
        button = QPushButton("Download")
        button.clicked.connect(self._on_download)
        form.addRow(button)
        root.addLayout(form)
        root.addStretch()

    def _on_download(self) -> None:
        url = self._url.text().strip()
        dest = self._dest.text().strip()
        self.run_action(
            download_file,
            f"download {url}",
            kwargs={"file_url": url, "file_name": dest},
        )
