"""The set of services a user interface works with, and the navigation they stand for.

.. code-block:: python

    from automation_file.app import NAVIGATION, app_services

    services = app_services()          # the shared set, on the process-wide singletons
    NAVIGATION                         # ("Dashboard", "Files", "Storage", ...)
    services.dashboard.summary()
    services.files.list_dir("local:///data")

:func:`app_services` returns one set per process, so the desktop window and the
web page of one process show the same runs, monitors and routes.
:func:`build_services` makes a set of its own, on the stores and buses it is
given: tests and embedded uses want that.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from automation_file.app.audit_service import AuditService
from automation_file.app.dashboard_service import DashboardService, DashboardSources
from automation_file.app.file_service import FileService
from automation_file.app.integrity_service import IntegrityService
from automation_file.app.notification_service import NotificationService
from automation_file.app.pipeline_service import PipelineService
from automation_file.app.scheduler_service import SchedulerService
from automation_file.app.settings_service import SettingsService
from automation_file.app.storage_service import StorageService
from automation_file.audit import AuditTrail
from automation_file.events import EventBus
from automation_file.notify import NotificationManager, NotificationRouter
from automation_file.pipeline import RunStore
from automation_file.storage import StorageResolver

if TYPE_CHECKING:
    from automation_file.core.action_registry import ActionRegistry

#: The navigation entries of every user interface, in display order.
NAVIGATION: tuple[str, ...] = (
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


@dataclass(frozen=True)
class AppServices:
    """One service per navigation entry."""

    dashboard: DashboardService
    files: FileService
    storage: StorageService
    pipelines: PipelineService
    scheduler: SchedulerService
    integrity: IntegrityService
    audit: AuditService
    notifications: NotificationService
    settings: SettingsService


@dataclass(frozen=True)
class ServiceOptions:
    """What a set of services is built on; ``None`` means the process-wide singleton."""

    resolver: StorageResolver | None = None
    run_store: RunStore | None = None
    registry: ActionRegistry | None = None
    bus: EventBus | None = None
    audit_trail: AuditTrail | None = None
    notification_manager: NotificationManager | None = None
    notification_router: NotificationRouter | None = None


def build_services(options: ServiceOptions | None = None) -> AppServices:
    """Build a set of services on ``options`` (the process-wide singletons by default)."""
    chosen = ServiceOptions() if options is None else options
    files = FileService(chosen.resolver)
    storage = StorageService(chosen.resolver)
    pipelines = PipelineService(chosen.run_store, registry=chosen.registry, bus=chosen.bus)
    scheduler = SchedulerService()
    integrity = IntegrityService()
    audit = AuditService(chosen.audit_trail)
    notifications = NotificationService(chosen.notification_manager, chosen.notification_router)
    settings = SettingsService(chosen.notification_manager, chosen.notification_router)
    dashboard = DashboardService(
        DashboardSources(
            pipelines=pipelines,
            integrity=integrity,
            storage=storage,
            scheduler=scheduler,
            audit=audit,
            notifications=notifications,
        ),
        bus=chosen.bus,
    )
    return AppServices(
        dashboard=dashboard,
        files=files,
        storage=storage,
        pipelines=pipelines,
        scheduler=scheduler,
        integrity=integrity,
        audit=audit,
        notifications=notifications,
        settings=settings,
    )


_shared: dict[str, AppServices] = {}
_shared_lock = threading.Lock()
_SHARED_KEY = "services"


def app_services() -> AppServices:
    """Return the process-wide set of services, built on first use."""
    with _shared_lock:
        services = _shared.get(_SHARED_KEY)
        if services is None:
            services = _shared[_SHARED_KEY] = build_services()
        return services


def reset_app_services() -> None:
    """Forget the process-wide set, so the next :func:`app_services` builds a new one."""
    with _shared_lock:
        _shared.clear()
