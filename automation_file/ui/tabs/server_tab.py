"""Control panel for the embedded TCP and HTTP action servers."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from automation_file.logging_config import file_automation_logger
from automation_file.server.http_server import HTTPActionServer, start_http_action_server
from automation_file.server.tcp_server import TCPActionServer, start_autocontrol_socket_server
from automation_file.ui.tabs.base import BaseTab


class ServerTab(BaseTab):
    """Start / stop the embedded TCP and HTTP action servers."""

    def __init__(self, log, pool) -> None:
        super().__init__(log, pool)
        self._tcp_server: TCPActionServer | None = None
        self._http_server: HTTPActionServer | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        root.addWidget(self._tcp_group())
        root.addWidget(self._http_group())
        root.addStretch()

    def _tcp_group(self) -> QGroupBox:
        box = QGroupBox("TCP action server")
        form = QFormLayout(box)
        self._tcp_host = QLineEdit("127.0.0.1")
        self._tcp_port = QSpinBox()
        self._tcp_port.setRange(1, 65535)
        self._tcp_port.setValue(9943)
        self._tcp_secret = QLineEdit()
        self._tcp_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._tcp_secret.setPlaceholderText("optional shared secret")
        form.addRow("Host", self._tcp_host)
        form.addRow("Port", self._tcp_port)
        form.addRow("Shared secret", self._tcp_secret)

        start = QPushButton("Start TCP server")
        start.clicked.connect(self._on_start_tcp)
        stop = QPushButton("Stop TCP server")
        stop.clicked.connect(self._on_stop_tcp)
        form.addRow(start)
        form.addRow(stop)
        return box

    def _http_group(self) -> QGroupBox:
        box = QGroupBox("HTTP action server")
        form = QFormLayout(box)
        self._http_host = QLineEdit("127.0.0.1")
        self._http_port = QSpinBox()
        self._http_port.setRange(1, 65535)
        self._http_port.setValue(9944)
        self._http_secret = QLineEdit()
        self._http_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._http_secret.setPlaceholderText("optional shared secret")
        form.addRow("Host", self._http_host)
        form.addRow("Port", self._http_port)
        form.addRow("Shared secret", self._http_secret)

        start = QPushButton("Start HTTP server")
        start.clicked.connect(self._on_start_http)
        stop = QPushButton("Stop HTTP server")
        stop.clicked.connect(self._on_stop_http)
        form.addRow(start)
        form.addRow(stop)
        return box

    def _on_start_tcp(self) -> None:
        if self._tcp_server is not None:
            self._log.append_line("TCP server already running")
            return
        try:
            self._tcp_server = start_autocontrol_socket_server(
                host=self._tcp_host.text().strip(),
                port=int(self._tcp_port.value()),
                shared_secret=self._tcp_secret.text().strip() or None,
            )
        except (OSError, ValueError) as error:
            self._log.append_line(f"TCP start failed: {error!r}")
            return
        self._log.append_line(
            f"TCP server listening on {self._tcp_host.text().strip()}:{int(self._tcp_port.value())}"
        )

    def _on_stop_tcp(self) -> None:
        server = self._tcp_server
        if server is None:
            self._log.append_line("TCP server not running")
            return
        self._tcp_server = None
        try:
            server.shutdown()
            server.server_close()
        except OSError as error:
            self._log.append_line(f"TCP shutdown error: {error!r}")
            return
        file_automation_logger.info("ui: tcp server stopped")
        self._log.append_line("TCP server stopped")

    def _on_start_http(self) -> None:
        if self._http_server is not None:
            self._log.append_line("HTTP server already running")
            return
        try:
            self._http_server = start_http_action_server(
                host=self._http_host.text().strip(),
                port=int(self._http_port.value()),
                shared_secret=self._http_secret.text().strip() or None,
            )
        except (OSError, ValueError) as error:
            self._log.append_line(f"HTTP start failed: {error!r}")
            return
        self._log.append_line(
            f"HTTP server listening on {self._http_host.text().strip()}:"
            f"{int(self._http_port.value())}"
        )

    def _on_stop_http(self) -> None:
        server = self._http_server
        if server is None:
            self._log.append_line("HTTP server not running")
            return
        self._http_server = None
        try:
            server.shutdown()
            server.server_close()
        except OSError as error:
            self._log.append_line(f"HTTP shutdown error: {error!r}")
            return
        file_automation_logger.info("ui: http server stopped")
        self._log.append_line("HTTP server stopped")

    def closeEvent(self, event) -> None:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        if self._tcp_server is not None:
            self._tcp_server.shutdown()
            self._tcp_server.server_close()
            self._tcp_server = None
        if self._http_server is not None:
            self._http_server.shutdown()
            self._http_server.server_close()
            self._http_server = None
        super().closeEvent(event)
