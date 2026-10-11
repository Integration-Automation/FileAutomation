"""Events: one way for every component to say what happened.

Components publish :class:`Event` objects on the :data:`event_bus`; the
notification router, the audit trail and the metrics subscribe to it. Nothing
calls a sink or writes an audit row directly.

Importing this package installs the bridge that turns failed storage operations
into :class:`StorageError` events.
"""

from __future__ import annotations

from automation_file.events.bus import (
    EventBus,
    EventFilter,
    EventHandler,
    Subscription,
    emit,
    event_bus,
)
from automation_file.events.context import (
    actor_scope,
    correlation_scope,
    current_actor,
    current_correlation_id,
    new_correlation_id,
)
from automation_file.events.model import (
    CORE_EVENTS,
    PAYLOAD_KEYS,
    Event,
    IntegrityViolation,
    PipelineCompleted,
    PipelineFailed,
    PipelineStarted,
    SchedulerError,
    Severity,
    StorageError,
    SystemErrorEvent,
    TaskCompleted,
    TaskFailed,
    TaskStarted,
)
from automation_file.events.storage_bridge import (
    StorageErrorBridge,
    install_storage_bridge,
    uninstall_storage_bridge,
)

install_storage_bridge()

__all__ = [
    "CORE_EVENTS",
    "PAYLOAD_KEYS",
    "Event",
    "EventBus",
    "EventFilter",
    "EventHandler",
    "IntegrityViolation",
    "PipelineCompleted",
    "PipelineFailed",
    "PipelineStarted",
    "SchedulerError",
    "Severity",
    "StorageError",
    "StorageErrorBridge",
    "Subscription",
    "SystemErrorEvent",
    "TaskCompleted",
    "TaskFailed",
    "TaskStarted",
    "actor_scope",
    "correlation_scope",
    "current_actor",
    "current_correlation_id",
    "emit",
    "event_bus",
    "install_storage_bridge",
    "new_correlation_id",
    "uninstall_storage_bridge",
]
