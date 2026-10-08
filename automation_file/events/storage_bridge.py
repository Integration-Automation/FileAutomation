"""Turn failed storage operations into :class:`StorageError` events.

Only failures of the storage itself are reported: a denied, unavailable or
transiently failing backend, or an error the backend could not classify. A
missing file, an existing target or a malformed URI is the caller's mistake and
raises to the caller without an event.
"""

from __future__ import annotations

from automation_file.events.bus import EventBus, event_bus
from automation_file.events.model import StorageError
from automation_file.storage import observe

#: Exception type names that describe the caller's request, not the storage's health.
_CALLER_ERRORS = frozenset(
    {
        "StorageNotFoundException",
        "StorageAlreadyExistsException",
        "StoragePathTypeException",
        "StorageNotEmptyException",
        "StorageURIException",
        "StorageUnsupportedException",
        "PathTraversalException",
    }
)
_SOURCE = "storage"


class StorageErrorBridge:
    """A storage observer that publishes on one :class:`EventBus`."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def __call__(self, operation: observe.StorageOperation) -> None:
        if operation.ok or operation.error_type in _CALLER_ERRORS:
            return
        self._bus.publish(
            StorageError(
                source=_SOURCE,
                subject=f"{operation.operation} failed: {operation.uri}",
                payload={
                    "action": operation.operation,
                    "resource": operation.uri,
                    "backend": operation.backend,
                    "status": operation.status,
                    "duration_ms": operation.duration_ms,
                    "error": operation.error,
                    "error_type": operation.error_type,
                },
            )
        )


_default_bridge = StorageErrorBridge(event_bus)


def install_storage_bridge() -> None:
    """Report storage failures on the process-wide bus. Calling it again changes nothing."""
    observe.add_listener(_default_bridge)


def uninstall_storage_bridge() -> bool:
    """Stop reporting storage failures on the process-wide bus."""
    return observe.remove_listener(_default_bridge)
