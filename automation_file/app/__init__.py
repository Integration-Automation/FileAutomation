"""The application layer: what a user interface calls.

One service per navigation entry -- Dashboard, Files, Storage, Pipelines,
Scheduler, Integrity, Audit, Notifications, Settings -- each a plain Python
object on top of the domain packages. The PySide6 window and the web page both
call these services and nothing below them, so they show the same state and a
third interface needs no knowledge of the domain packages either.

.. code-block:: python

    from automation_file.app import app_services

    services = app_services()
    services.dashboard.summary().status
    services.files.list_dir("memory://demo")
    draft = services.pipelines.new_draft("nightly")

The layer imports no GUI toolkit and no backend SDK, returns dataclasses,
dictionaries and lists that JSON can hold, masks secrets in what it returns,
and raises :class:`~automation_file.exceptions.FileAutomationException`
subclasses.
"""

from __future__ import annotations

from automation_file.app.arguments import (
    ActionInfo,
    ActionParameter,
    describe_action,
    format_argument_value,
    parse_argument_text,
    parse_json_text,
    split_names,
)
from automation_file.app.audit_service import AuditService
from automation_file.app.dashboard_service import (
    DashboardService,
    DashboardSources,
    DashboardSummary,
    brief_run,
)
from automation_file.app.errors import AppException
from automation_file.app.file_service import FileEntry, FilePreview, FileService
from automation_file.app.integrity_service import IntegrityService, MonitorDrift
from automation_file.app.masking import MASK, mask_secrets, mask_text, mask_url
from automation_file.app.notification_service import NotificationService
from automation_file.app.pipeline_draft import DraftTask, PipelineDraft, Problem
from automation_file.app.pipeline_service import PipelineService, layout_path
from automation_file.app.scheduler_service import SchedulerService
from automation_file.app.services import (
    NAVIGATION,
    AppServices,
    ServiceOptions,
    app_services,
    build_services,
    reset_app_services,
)
from automation_file.app.settings_service import ExtraStatus, SettingsService
from automation_file.app.storage_service import BackendStatus, MountInfo, StorageService

__all__ = [
    "MASK",
    "NAVIGATION",
    "ActionInfo",
    "ActionParameter",
    "AppException",
    "AppServices",
    "AuditService",
    "BackendStatus",
    "DashboardService",
    "DashboardSources",
    "DashboardSummary",
    "DraftTask",
    "ExtraStatus",
    "FileEntry",
    "FilePreview",
    "FileService",
    "IntegrityService",
    "MonitorDrift",
    "MountInfo",
    "NotificationService",
    "PipelineDraft",
    "PipelineService",
    "Problem",
    "SchedulerService",
    "ServiceOptions",
    "SettingsService",
    "StorageService",
    "app_services",
    "brief_run",
    "build_services",
    "describe_action",
    "format_argument_value",
    "layout_path",
    "mask_secrets",
    "mask_text",
    "mask_url",
    "parse_argument_text",
    "parse_json_text",
    "reset_app_services",
    "split_names",
]
