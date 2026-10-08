"""UI smoke tests — construct the main window, every page and every tab offscreen.

These tests don't exercise the event loop; they just confirm the widget tree
builds without raising, which catches import errors, bad signal wiring, and
drift between ops-module signatures and tab form fields. What the pages do with
their services is in ``test_ui_pages.py`` and ``test_ui_pipeline_editor.py``.
"""

# pylint: disable=protected-access  # the tests look at private state on purpose
# pylint: disable=unnecessary-lambda  # the lambda is looked up late, when it is called

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

pytest.importorskip("PySide6")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

NAVIGATION = (
    "Dashboard",
    "Files",
    "Storage",
    "Pipelines",
    "Scheduler",
    "Integrity",
    "Audit",
    "Notifications",
    "Settings",
)
ADVANCED_TOOLS = ("Local", "Transfer", "Progress", "JSON actions", "Triggers", "Servers")
PAGES = (
    ("Dashboard", "DashboardPage", "dashboard"),
    ("Files", "FilesPage", "files"),
    ("Storage", "StoragePage", "storage"),
    ("Pipelines", "PipelinesPage", "pipelines"),
    ("Scheduler", "SchedulerPage", "scheduler"),
    ("Integrity", "IntegrityPage", "integrity"),
    ("Audit", "AuditPage", "audit"),
    ("Notifications", "NotificationsPage", "notifications"),
    ("Settings", "SettingsPage", "settings"),
)


@pytest.fixture(name="window")
def _window(qt_app) -> Iterator:
    from automation_file.ui.main_window import MainWindow

    assert qt_app is not None
    window = MainWindow()
    try:
        yield window
    finally:
        window.close()


def test_launch_ui_is_lazy_facade_attr() -> None:
    import automation_file

    launcher = automation_file.launch_ui
    assert callable(launcher)


def test_launch_ui_shows_the_main_window_and_returns_the_exit_code(
    qt_app, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QApplication

    from automation_file.ui import launcher
    from automation_file.ui.main_window import MainWindow

    shown: list[MainWindow] = []
    monkeypatch.setattr(MainWindow, "show", lambda self: shown.append(self))
    monkeypatch.setattr(QApplication, "exec", lambda *_args: 7)
    assert qt_app is not None
    try:
        assert launcher.launch_ui([]) == 7
        assert len(shown) == 1
        assert shown[0].current_page_name() == "Dashboard"
    finally:
        for window in shown:
            window.close()


def test_launch_ui_names_the_gui_extra_when_pyside6_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from automation_file.core.optional import install_hint
    from automation_file.exceptions import OptionalDependencyException
    from automation_file.ui import launcher

    asked: list[tuple[str, str]] = []

    def missing(name: str, *, extra: str) -> None:
        asked.append((name, extra))
        raise OptionalDependencyException(f"PySide6 is not installed: {install_hint(extra)}")

    monkeypatch.setattr(launcher, "require_module", missing)
    with pytest.raises(OptionalDependencyException, match=r"automation_file\[gui\]"):
        launcher.launch_ui([])
    assert asked == [("PySide6.QtWidgets", "gui")]


def test_main_window_constructs(window) -> None:
    assert window.windowTitle() == "automation_file"


def test_closing_the_window_shuts_every_page_down(qt_app) -> None:
    from automation_file.ui.main_window import MainWindow

    assert qt_app is not None
    window = MainWindow()
    closed: list[str] = []
    for name in window.page_names():
        page = window.page(name)
        original = page.shutdown

        def shutdown(original=original, name=name) -> None:
            closed.append(name)
            original()

        page.shutdown = shutdown  # type: ignore[method-assign]
    window.close()
    assert closed == [*NAVIGATION, "Advanced"]
    assert window.page("Dashboard")._timer.isActive() is False


def test_the_sidebar_lists_the_nine_workflows_and_then_advanced(window) -> None:
    from automation_file import app

    assert app.NAVIGATION == NAVIGATION
    assert window.page_names() == [*NAVIGATION, "Advanced"]
    assert window.current_page_name() == "Dashboard"


@pytest.mark.parametrize(("name", "page_class", "_service"), PAGES)
def test_every_navigation_entry_has_its_page(window, name: str, page_class: str, _service) -> None:
    from automation_file.ui import pages

    assert isinstance(window.page(name), getattr(pages, page_class))
    assert window.page(name).title == name
    assert window.navigate(name) is True
    assert window.current_page_name() == name


def test_the_old_tabs_are_reachable_under_advanced(window) -> None:
    from automation_file.ui import tabs
    from automation_file.ui.pages import AdvancedPage

    advanced = window.page("Advanced")
    assert isinstance(advanced, AdvancedPage)
    assert advanced.tool_names() == list(ADVANCED_TOOLS)
    expected = {
        "Local": tabs.LocalOpsTab,
        "Transfer": tabs.TransferTab,
        "Progress": tabs.ProgressTab,
        "JSON actions": tabs.JSONEditorTab,
        "Triggers": tabs.TriggerTab,
        "Servers": tabs.ServerTab,
    }
    for name, tab_class in expected.items():
        assert isinstance(advanced.tool(name), tab_class)
        assert window.open_tool(name) is True
        assert window.current_page_name() == "Advanced"
        assert advanced.current_tool() == name
    assert window.open_tool("No such tool") is False
    assert advanced.tool("No such tool") is None


def test_every_cloud_backend_panel_is_still_under_transfer(window) -> None:
    from automation_file.ui import tabs

    transfer = window.page("Advanced").tool("Transfer")
    panels = {
        "HTTP download": tabs.HTTPDownloadTab,
        "Google Drive": tabs.GoogleDriveTab,
        "Amazon S3": tabs.S3Tab,
        "Azure Blob": tabs.AzureBlobTab,
        "Dropbox": tabs.DropboxTab,
        "SFTP": tabs.SFTPTab,
        "OneDrive": tabs.OneDriveTab,
        "Box": tabs.BoxTab,
    }
    for label, panel_class in panels.items():
        assert isinstance(transfer.inner_widget(label), panel_class)
        assert transfer.select_backend(label) is True


def test_navigating_to_an_unknown_page_changes_nothing(window) -> None:
    assert window.navigate("Files") is True
    assert window.navigate("Nowhere") is False
    assert window.current_page_name() == "Files"


@pytest.mark.parametrize(("name", "page_class", "service"), PAGES)
def test_each_page_constructs(qt_app, name: str, page_class: str, service: str) -> None:
    from PySide6.QtCore import QThreadPool

    from automation_file.app import build_services
    from automation_file.ui import pages
    from automation_file.ui.log_widget import LogPanel

    assert qt_app is not None
    log = LogPanel()
    page = getattr(pages, page_class)(
        getattr(build_services(), service), log, QThreadPool.globalInstance()
    )
    try:
        assert page.title == name
        assert page.status_text() == ""
    finally:
        page.shutdown()
        page.deleteLater()
        log.deleteLater()


def test_the_advanced_page_constructs_on_its_own(qt_app) -> None:
    from PySide6.QtCore import QThreadPool
    from PySide6.QtGui import QCloseEvent

    from automation_file.ui import pages
    from automation_file.ui.log_widget import LogPanel
    from automation_file.ui.pages import AdvancedPage

    assert qt_app is not None
    log = LogPanel()
    page = AdvancedPage(log, QThreadPool.globalInstance())
    try:
        assert pages.ADVANCED_TOOLS == ADVANCED_TOOLS
        assert page.tool_names() == list(ADVANCED_TOOLS)
    finally:
        page.close_tools(QCloseEvent())
        page.deleteLater()
        log.deleteLater()


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
        "OneDriveTab",
        "BoxTab",
        "JSONEditorTab",
        "ServerTab",
        "TransferTab",
        "TriggerTab",
        "SchedulerTab",
        "ProgressTab",
        "HomeTab",
    ],
)
def test_each_tab_constructs(qt_app, tab_name: str) -> None:
    from PySide6.QtCore import QThreadPool

    from automation_file.ui import tabs
    from automation_file.ui.log_widget import LogPanel

    assert qt_app is not None
    pool = QThreadPool.globalInstance()
    log = LogPanel()
    tab_cls = getattr(tabs, tab_name)
    tab = tab_cls(log, pool)
    try:
        assert tab is not None
    finally:
        tab.deleteLater()
        log.deleteLater()
