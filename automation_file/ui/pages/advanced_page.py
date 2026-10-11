"""Advanced page: the tools that address one action or one backend directly.

These are the tabs the main window had before it was organised by workflow.
They are reused as they are, so everything they could do is still here: local
file, directory and ZIP actions, the per-backend transfer panels (where a cloud
client is given its credentials), live transfer progress, the JSON action
editor, file triggers and the TCP / HTTP action servers.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from automation_file.ui.log_widget import LogPanel
from automation_file.ui.pages.base import BasePage
from automation_file.ui.tabs import (
    JSONEditorTab,
    LocalOpsTab,
    ProgressTab,
    ServerTab,
    TransferTab,
    TriggerTab,
)

#: The tools of the page, in display order.
ADVANCED_TOOLS: tuple[str, ...] = (
    "Local",
    "Transfer",
    "Progress",
    "JSON actions",
    "Triggers",
    "Servers",
)


class AdvancedPage(BasePage):
    """Local, Transfer, Progress, JSON actions, Triggers and Servers, each in a tab."""

    title = "Advanced"

    def __init__(self, log: LogPanel, pool: QThreadPool) -> None:
        super().__init__(log, pool)
        self._trigger_tab = TriggerTab(log, pool)
        self._server_tab = ServerTab(log, pool)
        tools: tuple[QWidget, ...] = (
            LocalOpsTab(log, pool),
            TransferTab(log, pool),
            ProgressTab(log, pool),
            JSONEditorTab(log, pool),
            self._trigger_tab,
            self._server_tab,
        )
        self._tabs = QTabWidget()
        for name, tool in zip(ADVANCED_TOOLS, tools, strict=True):
            self._tabs.addTab(tool, name)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self._tabs)

    def tool_names(self) -> list[str]:
        """Return the names of the tools, in display order."""
        return [self._tabs.tabText(index) for index in range(self._tabs.count())]

    def current_tool(self) -> str:
        """Return the name of the tool that is shown."""
        return self._tabs.tabText(self._tabs.currentIndex())

    def tool(self, name: str) -> QWidget | None:
        """Return the widget of the tool called ``name``, or ``None``."""
        for index in range(self._tabs.count()):
            if self._tabs.tabText(index) == name:
                return self._tabs.widget(index)
        return None

    def open_tool(self, name: str) -> bool:
        """Show the tool called ``name``; return whether there is one."""
        for index in range(self._tabs.count()):
            if self._tabs.tabText(index) == name:
                self._tabs.setCurrentIndex(index)
                return True
        return False

    def close_tools(self, event: Any) -> None:
        """Stop what the tools started: the action servers and the file triggers."""
        self._server_tab.closeEvent(event)
        self._trigger_tab.closeEvent(event)
