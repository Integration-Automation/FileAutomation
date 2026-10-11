"""Settings page: the configuration file, the optional extras, the environment."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
)

from automation_file.app import ExtraStatus, SettingsService
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.pages.base import BasePage, fill_table, make_table

_EXTRA_COLUMNS = ("Extra", "Enables", "Installed", "Install command")
_ENVIRONMENT_ROWS = (
    ("version", "automation_file"),
    ("python", "Python"),
    ("platform", "Platform"),
    ("log_file", "Log file"),
    ("applied_config", "Applied configuration"),
)
_TOML_FILTER = "TOML files (*.toml);;All files (*)"


def _installed_text(extra: ExtraStatus) -> str:
    if extra.installed is None:
        return "unknown"
    return "yes" if extra.installed else f"no ({', '.join(extra.missing)} missing)"


class SettingsPage(BasePage):
    """Preview and apply ``automation_file.toml``; see which extras are installed."""

    title = "Settings"

    def __init__(self, service: SettingsService, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._service = service
        self._summary: dict[str, Any] | None = None
        self._extras: list[ExtraStatus] = []
        self._environment_labels: dict[str, QLabel] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(self._config_group(), 2)
        row = QHBoxLayout()
        row.addWidget(self._extras_group(), 3)
        row.addWidget(self._environment_group(), 2)
        root.addLayout(row, 2)
        root.addWidget(self.status_label())

    # ------------------------------------------------------------------ layout

    def _config_group(self) -> QGroupBox:
        box = QGroupBox("Configuration file")
        layout = QVBoxLayout(box)
        row = QHBoxLayout()
        self._path = QLineEdit()
        self._path.setPlaceholderText("automation_file.toml")
        row.addWidget(self._path, 1)
        row.addWidget(self.make_button("Browse…", self._on_browse))
        row.addWidget(self.make_button("Preview", self.preview))
        row.addWidget(self.make_button("Apply", self.apply))
        layout.addLayout(row)
        layout.addWidget(
            self.muted_label(
                "Preview reads the file and changes nothing. Apply registers its notification "
                "sinks and routes. Secrets are resolved from ${env:...} and ${file:...} and are "
                "shown masked."
            )
        )
        self._document = QPlainTextEdit()
        self._document.setReadOnly(True)
        self._document.setPlaceholderText("The configuration summary appears here.")
        layout.addWidget(self._document)
        return box

    def _extras_group(self) -> QGroupBox:
        box = QGroupBox("Optional extras")
        layout = QVBoxLayout(box)
        self._extras_table = make_table(_EXTRA_COLUMNS)
        layout.addWidget(self._extras_table)
        layout.addWidget(self.make_button("Refresh", self.refresh))
        return box

    def _environment_group(self) -> QGroupBox:
        box = QGroupBox("Environment")
        form = QFormLayout(box)
        for key, label in _ENVIRONMENT_ROWS:
            value = QLabel("")
            value.setWordWrap(True)
            self._environment_labels[key] = value
            form.addRow(label, value)
        return box

    # ------------------------------------------------------------------ extras and environment

    def extras(self) -> list[ExtraStatus]:
        """Return the extras the table shows."""
        return list(self._extras)

    def refresh(self) -> None:
        self.run_async(
            lambda: (self._service.extras(), self._service.environment()),
            "read extras",
            self._show_environment,
            key="refresh",
            quiet=True,
        )

    def _show_environment(self, result: tuple[list[ExtraStatus], dict[str, Any]]) -> None:
        self._extras, environment = result
        fill_table(
            self._extras_table,
            [
                [extra.name, extra.feature, _installed_text(extra), extra.install_hint]
                for extra in self._extras
            ],
        )
        for key, _label in _ENVIRONMENT_ROWS:
            value = environment.get(key)
            self._environment_labels[key].setText("none" if value is None else str(value))

    # ------------------------------------------------------------------ configuration

    def set_path(self, path: str) -> None:
        """Fill in the configuration file field."""
        self._path.setText(path)

    def summary(self) -> dict[str, Any] | None:
        """Return the configuration summary the page shows."""
        return self._summary

    def document_text(self) -> str:
        """Return what the summary pane shows."""
        return self._document.toPlainText()

    def _on_browse(self) -> None:
        chosen = self.pick_open_file("Configuration file", _TOML_FILTER)
        if chosen:
            self._path.setText(chosen)

    def preview(self) -> None:
        self._read("preview", self._service.load)

    def apply(self) -> None:
        self._read("apply", self._service.apply)

    def _read(self, verb: str, read: Callable[[str], dict[str, Any]]) -> None:
        path = self._path.text().strip()
        if not path:
            self.report_error("enter the path of the configuration file first")
            return
        self.run_async(lambda: read(path), f"{verb} {path}", self._show_summary)

    def _show_summary(self, summary: dict[str, Any]) -> None:
        self._summary = summary
        self._document.setPlainText(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
        sinks, routes = len(summary.get("sinks") or ()), len(summary.get("routes") or ())
        if summary.get("applied"):
            self.report(f"applied {summary.get('source')}: {sinks} sink(s), {routes} route(s)")
            self.refresh()
        else:
            self.report(
                f"{summary.get('source')} declares {sinks} sink(s) and {routes} route(s); "
                "nothing was changed"
            )
