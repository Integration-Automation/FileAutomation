"""Landing dashboard — overview, backend readiness, quick actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from PySide6.QtCore import QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from automation_file.remote.azure_blob.client import azure_blob_instance
from automation_file.remote.dropbox_api.client import dropbox_instance
from automation_file.remote.google_drive.client import driver_instance
from automation_file.remote.s3.client import s3_instance
from automation_file.remote.sftp.client import sftp_instance
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.tabs.base import BaseTab

_REFRESH_INTERVAL_MS = 2000


class _BackendProbe(NamedTuple):
    label: str
    is_ready: Callable[[], bool]


_BACKENDS: tuple[_BackendProbe, ...] = (
    _BackendProbe("Google Drive", lambda: driver_instance.service is not None),
    _BackendProbe("Amazon S3", lambda: s3_instance.client is not None),
    _BackendProbe("Azure Blob", lambda: azure_blob_instance.service is not None),
    _BackendProbe("Dropbox", lambda: dropbox_instance.client is not None),
    _BackendProbe("SFTP", lambda: getattr(sftp_instance, "_sftp", None) is not None),
)


class HomeTab(BaseTab):
    """Dashboard with overview text, backend status, and quick-nav buttons."""

    navigate_to_tab = Signal(str)

    def __init__(self, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._status_labels: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self._overview_group())
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self._status_group(), 1)
        row.addWidget(self._actions_group(), 1)
        root.addLayout(row)
        root.addStretch()

        self._refresh_status()
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start()

    def _overview_group(self) -> QGroupBox:
        box = QGroupBox("automation_file")
        layout = QVBoxLayout(box)
        headline = QLabel(
            "Automate local and remote file work through a shared registry of "
            "<code>FA_*</code> actions."
        )
        headline.setWordWrap(True)
        layout.addWidget(headline)
        details = QLabel(
            "Use <b>Local</b> for direct filesystem / ZIP operations, "
            "<b>Transfer</b> to move bytes to cloud backends (HTTP, Drive, S3, "
            "Azure, Dropbox, SFTP), and <b>JSON actions</b> for visual editing "
            "of reusable action lists. <b>Servers</b> exposes the same registry "
            "over localhost TCP or HTTP."
        )
        details.setWordWrap(True)
        layout.addWidget(details)
        return box

    def _status_group(self) -> QGroupBox:
        box = QGroupBox("Remote backends")
        form = QFormLayout(box)
        for probe in _BACKENDS:
            label = QLabel("—")
            self._status_labels[probe.label] = label
            form.addRow(probe.label, label)
        return box

    def _actions_group(self) -> QGroupBox:
        box = QGroupBox("Jump to…")
        layout = QVBoxLayout(box)
        for tab_name in ("Local", "Transfer", "JSON actions", "Servers"):
            button = self.make_button(tab_name, self._emit_nav(tab_name))
            layout.addWidget(button)
        layout.addStretch()
        return box

    def _emit_nav(self, tab_name: str) -> Callable[[], None]:
        return lambda: self.navigate_to_tab.emit(tab_name)

    def _refresh_status(self) -> None:
        for probe in _BACKENDS:
            label = self._status_labels.get(probe.label)
            if label is None:
                continue
            try:
                ready = bool(probe.is_ready())
            except Exception:  # pylint: disable=broad-except
                ready = False
            label.setText("Ready" if ready else "Not initialised")
            label.setStyleSheet("color: #2f8f3f;" if ready else "color: #888;")
