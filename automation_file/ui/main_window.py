"""Main window: a sidebar of operational workflows over the application layer.

The navigation is the one :data:`automation_file.app.NAVIGATION` names --
Dashboard, Files, Storage, Pipelines, Scheduler, Integrity, Audit,
Notifications, Settings -- followed by Advanced, which keeps the tools that
address a single action or backend. Each of the nine pages talks only to its
service of :mod:`automation_file.app`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QMainWindow,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from automation_file.app import NAVIGATION, AppServices, app_services
from automation_file.logging_config import file_automation_logger
from automation_file.ui.log_widget import LogPanel
from automation_file.ui.pages import (
    AdvancedPage,
    AuditPage,
    BasePage,
    DashboardPage,
    FilesPage,
    IntegrityPage,
    NotificationsPage,
    PipelinesPage,
    SchedulerPage,
    SettingsPage,
    StoragePage,
)

ADVANCED = "Advanced"
_WINDOW_TITLE = "automation_file"
_DEFAULT_SIZE = (1280, 860)
_STATUS_DEFAULT = "Ready"
_SIDEBAR_WIDTH = 170
_STATUS_MESSAGE_MS = 5000
_SHORTCUT_COUNT = 9
_CLOSE_WAIT_MS = 2000


class MainWindow(QMainWindow):
    """Sidebar navigation over the nine workflow pages and the Advanced tools.

    ``services`` is the set of application services the pages use; the
    process-wide set by default, so the window shows what the rest of the
    process does.
    """

    def __init__(self, services: AppServices | None = None) -> None:
        super().__init__()
        self.setWindowTitle(_WINDOW_TITLE)
        self.resize(*_DEFAULT_SIZE)

        self._services = app_services() if services is None else services
        self._pool = QThreadPool.globalInstance()
        self._log = LogPanel()
        self._log.message_appended.connect(self._on_log_message)
        self._advanced = AdvancedPage(self._log, self._pool)
        self._pages: dict[str, BasePage] = {**self._workflow_pages(), ADVANCED: self._advanced}

        self._sidebar = QListWidget()
        self._sidebar.setFixedWidth(_SIDEBAR_WIDTH)
        self._stack = QStackedWidget()
        for name, page in self._pages.items():
            self._sidebar.addItem(name)
            self._stack.addWidget(page)
        self._sidebar.setCurrentRow(0)
        self._sidebar.currentRowChanged.connect(self._on_page_changed)

        self.setCentralWidget(self._central_widget())
        self._register_shortcuts()
        self.statusBar().showMessage(_STATUS_DEFAULT)
        # The first page reads its data once the event loop runs, not while the window is built.
        self._startup = QTimer(self)
        self._startup.setSingleShot(True)
        self._startup.timeout.connect(self._show_current_page)
        self._startup.start(0)
        file_automation_logger.info("ui: main window constructed")

    def _workflow_pages(self) -> dict[str, BasePage]:
        services, log, pool = self._services, self._log, self._pool
        pages: tuple[BasePage, ...] = (
            DashboardPage(services.dashboard, log, pool),
            FilesPage(services.files, log, pool),
            StoragePage(services.storage, log, pool),
            PipelinesPage(services.pipelines, log, pool),
            SchedulerPage(services.scheduler, log, pool),
            IntegrityPage(services.integrity, log, pool),
            AuditPage(services.audit, log, pool),
            NotificationsPage(services.notifications, log, pool),
            SettingsPage(services.settings, log, pool),
        )
        return dict(zip(NAVIGATION, pages, strict=True))

    def _central_widget(self) -> QWidget:
        navigation = QWidget()
        row = QHBoxLayout(navigation)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self._sidebar)
        row.addWidget(self._stack, 1)

        splitter = QSplitter()
        splitter.setOrientation(Qt.Orientation.Vertical)
        splitter.addWidget(navigation)
        splitter.addWidget(self._log)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(splitter)
        return container

    def _register_shortcuts(self) -> None:
        for index in range(min(self._stack.count(), _SHORTCUT_COUNT)):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self)
            shortcut.activated.connect(lambda i=index: self._sidebar.setCurrentRow(i))
        advanced = QShortcut(QKeySequence("Ctrl+0"), self)
        advanced.activated.connect(lambda: self.navigate(ADVANCED))

    # ------------------------------------------------------------------ navigation

    def page_names(self) -> list[str]:
        """Return the navigation entries, in display order."""
        return list(self._pages)

    def page(self, name: str) -> BasePage:
        """Return the page of the navigation entry ``name``."""
        return self._pages[name]

    def current_page_name(self) -> str:
        """Return the navigation entry that is shown."""
        return self.page_names()[self._stack.currentIndex()]

    def navigate(self, name: str) -> bool:
        """Show the page ``name``; return whether there is one."""
        names = self.page_names()
        if name not in names:
            return False
        self._sidebar.setCurrentRow(names.index(name))
        return True

    def open_tool(self, name: str) -> bool:
        """Show the Advanced tool ``name`` (Local, Transfer, ...); return whether there is one."""
        return self._advanced.open_tool(name) and self.navigate(ADVANCED)

    def _on_page_changed(self, row: int) -> None:
        if 0 <= row < self._stack.count():
            self._stack.setCurrentIndex(row)
            self._show_current_page()

    def _show_current_page(self) -> None:
        self._pages[self.current_page_name()].on_shown()

    def _on_log_message(self, message: str) -> None:
        self.statusBar().showMessage(message, _STATUS_MESSAGE_MS)

    def closeEvent(self, event) -> None:  # noqa: N802  # pylint: disable=invalid-name — Qt override
        self._startup.stop()
        self._advanced.close_tools(event)
        for page in self._pages.values():
            page.shutdown()
        # A refresh that is still reading must not outlive the objects its signals belong to.
        if not self._pool.waitForDone(_CLOSE_WAIT_MS):
            file_automation_logger.warning(
                "ui: background work was still running when the window closed"
            )
        super().closeEvent(event)
