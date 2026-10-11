"""Notifications page: the registered sinks, the routes, and a test message."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from automation_file.app import NotificationService
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.pages.base import BasePage, fill_table, make_table, selected_cell

_SINK_COLUMNS = ("Name", "Type", "Delivers to")
_ROUTE_COLUMNS = ("Route", "Sinks", "Types", "Sources", "Min severity", "Dedup (s)", "Rate")
_ALL_SINKS = "All sinks"
_SINK_IDENTITY = ("name", "type")
_DEFAULT_SEVERITY = "warning"


def _delivers_to(sink: dict[str, Any]) -> str:
    """Describe where a sink delivers, from what its description holds beyond name and type."""
    details = {key: value for key, value in sink.items() if key not in _SINK_IDENTITY}
    return ", ".join(f"{key}: {value}" for key, value in details.items())


def _rate(route: dict[str, Any]) -> str:
    if not route.get("rate_limit"):
        return "unlimited"
    return f"{route['rate_limit']} per {route.get('rate_period')} s"


class NotificationsPage(BasePage):
    """Shows sinks without their secrets, edits routes, sends a test message."""

    title = "Notifications"

    def __init__(self, service: NotificationService, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._service = service
        self._sinks: list[dict[str, Any]] = []
        self._routes: list[dict[str, Any]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(self._sinks_group(), 1)
        root.addWidget(self._routes_group(), 1)
        root.addWidget(self._route_form_group())
        root.addWidget(self.status_label())

    # ------------------------------------------------------------------ layout

    def _sinks_group(self) -> QGroupBox:
        box = QGroupBox("Sinks")
        layout = QVBoxLayout(box)
        layout.addWidget(
            self.muted_label(
                "Sinks are registered in code or from the configuration file (Settings). "
                "A webhook URL, a token or a password is never shown."
            )
        )
        self._sink_table = make_table(_SINK_COLUMNS)
        layout.addWidget(self._sink_table)
        row = QHBoxLayout()
        self._test_sink = QComboBox()
        self._test_sink.addItem(_ALL_SINKS)
        self._test_subject = QLineEdit()
        self._test_subject.setPlaceholderText("subject of the test message (optional)")
        row.addWidget(QLabel("Test"))
        row.addWidget(self._test_sink)
        row.addWidget(self._test_subject, 1)
        row.addWidget(self.make_button("Send test message", self.send_test))
        row.addWidget(self.make_button("Refresh", self.refresh))
        layout.addLayout(row)
        return box

    def _routes_group(self) -> QGroupBox:
        box = QGroupBox("Routes")
        layout = QVBoxLayout(box)
        self._router_state = QLabel("")
        self._route_table = make_table(_ROUTE_COLUMNS)
        layout.addWidget(self._router_state)
        layout.addWidget(self._route_table)
        layout.addWidget(self.make_button("Remove selected route", self.remove_selected))
        return box

    def _route_form_group(self) -> QGroupBox:
        box = QGroupBox("Add or replace a route")
        form = QFormLayout(box)
        self._name = QLineEdit()
        self._name.setPlaceholderText("unique route name; an existing name is replaced")
        self._route_sinks = QLineEdit()
        self._route_sinks.setPlaceholderText("sink names, comma-separated; empty means every sink")
        self._types = QLineEdit()
        self._types.setPlaceholderText(
            "pipeline.*, task.failed, integrity.violation; empty means all"
        )
        self._sources = QLineEdit()
        self._sources.setPlaceholderText("pipeline, scheduler, storage; empty means all")
        self._severity = QComboBox()
        self._severity.addItems(self._service.severities())
        self._severity.setCurrentText(_DEFAULT_SEVERITY)
        self._dedup = QLineEdit()
        self._dedup.setPlaceholderText("seconds a repeat is dropped; empty: 300, 0: off")
        self._rate_limit = QLineEdit()
        self._rate_limit.setPlaceholderText("messages per period; empty or 0: unlimited")
        self._rate_period = QLineEdit()
        self._rate_period.setPlaceholderText("seconds; empty: 60")
        form.addRow("Name", self._name)
        form.addRow("Sinks", self._route_sinks)
        form.addRow("Event types", self._types)
        form.addRow("Sources", self._sources)
        form.addRow("Minimum severity", self._severity)
        throttle = QHBoxLayout()
        throttle.addWidget(self._dedup)
        throttle.addWidget(self._rate_limit)
        throttle.addWidget(self._rate_period)
        form.addRow("Dedup / rate / period", throttle)
        form.addRow(self.make_button("Add route", self.add_route))
        return box

    # ------------------------------------------------------------------ data

    def sinks(self) -> list[dict[str, Any]]:
        """Return the sinks the table shows."""
        return list(self._sinks)

    def routes(self) -> list[dict[str, Any]]:
        """Return the routes the table shows."""
        return list(self._routes)

    def refresh(self) -> None:
        self.run_async(self._read, "read sinks and routes", self._show, key="refresh", quiet=True)

    def _read(self) -> dict[str, Any]:
        return {
            "sinks": self._service.sinks(),
            "routes": self._service.routes(),
            "active": self._service.router_active(),
        }

    def _show(self, data: dict[str, Any]) -> None:
        self._sinks, self._routes = data["sinks"], data["routes"]
        fill_table(
            self._sink_table,
            [[sink.get("name"), sink.get("type"), _delivers_to(sink)] for sink in self._sinks],
        )
        fill_table(
            self._route_table,
            [
                [
                    route.get("name"),
                    route.get("sinks") or "every sink",
                    route.get("types") or "every type",
                    route.get("sources") or "every source",
                    route.get("min_severity"),
                    route.get("dedup_seconds"),
                    _rate(route),
                ]
                for route in self._routes
            ],
        )
        self._router_state.setText(
            "The router is delivering events."
            if data["active"]
            else "The router is not running: it starts with the first route."
        )
        chosen = self._test_sink.currentText()
        self._test_sink.clear()
        self._test_sink.addItem(_ALL_SINKS)
        self._test_sink.addItems([str(sink.get("name")) for sink in self._sinks])
        self._test_sink.setCurrentText(chosen)

    # ------------------------------------------------------------------ routes

    def route_options(self) -> dict[str, Any]:
        """Return the route the form describes, as the service takes it."""
        return {
            "name": self._name.text().strip(),
            "sinks": self._route_sinks.text(),
            "types": self._types.text(),
            "sources": self._sources.text(),
            "min_severity": self._severity.currentText(),
            "dedup_seconds": self._dedup.text().strip(),
            "rate_limit": self._rate_limit.text().strip(),
            "rate_period": self._rate_period.text().strip(),
        }

    def add_route(self) -> None:
        options = self.route_options()
        self.run_async(
            lambda: self._service.add_route(options),
            f"add route {options['name']}",
            lambda route: self._after_change(f"route {route['name']} added"),
        )

    def remove_selected(self) -> None:
        name = selected_cell(self._route_table)
        if name is None:
            self.report_error("select a route to remove")
            return
        self.run_async(
            lambda: self._service.remove_route(name),
            f"remove route {name}",
            lambda removed: self._after_change(
                f"route {name} removed" if removed else f"there was no route {name}"
            ),
        )

    def _after_change(self, message: str) -> None:
        self.report(message)
        self.refresh()

    # ------------------------------------------------------------------ test message

    def send_test(self) -> None:
        chosen = self._test_sink.currentText()
        sink = None if chosen == _ALL_SINKS else chosen
        subject = self._test_subject.text().strip()
        self.run_async(
            lambda: self._service.send_test(sink, subject),
            f"send test message to {chosen}",
            self._show_outcomes,
        )

    def _show_outcomes(self, outcomes: dict[str, str]) -> None:
        text = "; ".join(f"{name}: {outcome}" for name, outcome in outcomes.items())
        if all(outcome == "sent" for outcome in outcomes.values()):
            self.report(f"test message: {text}")
        else:
            self.report_error(f"test message: {text}")
