"""Pages of the main window, one per navigation entry of the application layer."""

from __future__ import annotations

from automation_file.ui.pages.advanced_page import ADVANCED_TOOLS, AdvancedPage
from automation_file.ui.pages.audit_page import AuditPage
from automation_file.ui.pages.base import BasePage
from automation_file.ui.pages.dashboard_page import DashboardPage
from automation_file.ui.pages.files_page import FilesPage
from automation_file.ui.pages.integrity_page import IntegrityPage
from automation_file.ui.pages.notifications_page import NotificationsPage
from automation_file.ui.pages.pipeline_canvas import (
    ACTION_MIME,
    ActionPalette,
    EdgeItem,
    PipelineCanvas,
    TaskNode,
)
from automation_file.ui.pages.pipelines_page import PipelinesPage
from automation_file.ui.pages.run_panel import RunPanel
from automation_file.ui.pages.scheduler_page import SchedulerPage
from automation_file.ui.pages.settings_page import SettingsPage
from automation_file.ui.pages.storage_page import StoragePage
from automation_file.ui.pages.task_form import ArgumentsEditor, TaskForm

__all__ = [
    "ACTION_MIME",
    "ADVANCED_TOOLS",
    "ActionPalette",
    "AdvancedPage",
    "ArgumentsEditor",
    "AuditPage",
    "BasePage",
    "DashboardPage",
    "EdgeItem",
    "FilesPage",
    "IntegrityPage",
    "NotificationsPage",
    "PipelineCanvas",
    "PipelinesPage",
    "RunPanel",
    "SchedulerPage",
    "SettingsPage",
    "StoragePage",
    "TaskForm",
    "TaskNode",
]
