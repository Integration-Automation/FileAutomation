"""UI smoke tests — construct every tab with the offscreen Qt platform.

These tests don't exercise the event loop; they just confirm the widget tree
builds without raising, which catches import errors, bad signal wiring, and
drift between ops-module signatures and tab form fields.
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qt_app():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_launch_ui_is_lazy_facade_attr() -> None:
    import automation_file

    launcher = automation_file.launch_ui
    assert callable(launcher)


def test_main_window_constructs(qt_app) -> None:
    from automation_file.ui.main_window import MainWindow

    window = MainWindow()
    try:
        assert window.windowTitle() == "automation_file"
    finally:
        window.close()


@pytest.mark.parametrize(
    "tab_name",
    [
        "LocalOpsTab",
        "HTTPDownloadTab",
        "GoogleDriveTab",
        "S3Tab",
        "AzureBlobTab",
        "DropboxTab",
        "SFTPTab",
        "JSONEditorTab",
        "ServerTab",
        "TransferTab",
        "HomeTab",
    ],
)
def test_each_tab_constructs(qt_app, tab_name: str) -> None:
    from PySide6.QtCore import QThreadPool

    from automation_file.ui import tabs
    from automation_file.ui.log_widget import LogPanel

    pool = QThreadPool.globalInstance()
    log = LogPanel()
    tab_cls = getattr(tabs, tab_name)
    tab = tab_cls(log, pool)
    try:
        assert tab is not None
    finally:
        tab.deleteLater()
        log.deleteLater()
