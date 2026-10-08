"""Listeners for what the storage layer does.

Every backend reports its file operations -- ``upload``, ``download``, ``read``,
``delete``, ``mkdir``, ``copy`` and ``move`` -- to the listeners registered here,
with the outcome and the duration. The audit trail and the event bridge are
listeners; the storage layer itself knows nothing about either.

Lookups (``exists``, ``stat``, ``list_dir``, ``checksum``) are not reported: they
change nothing and would drown the operations that matter.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from automation_file.logging_config import file_automation_logger

STATUS_OK = "ok"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class StorageOperation:
    """One finished storage operation."""

    operation: str
    uri: str
    backend: str
    status: str
    duration_ms: float
    source_uri: str | None = None
    error: str | None = None
    error_type: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "uri": self.uri,
            "backend": self.backend,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "source_uri": self.source_uri,
            "error": self.error,
            "error_type": self.error_type,
        }


StorageListener = Callable[[StorageOperation], object]

_lock = threading.Lock()
_listeners: list[StorageListener] = []
_suppressed: ContextVar[bool] = ContextVar("fa_storage_observe_suppressed", default=False)


def add_listener(listener: StorageListener) -> None:
    """Call ``listener`` after every storage operation. Adding it twice has no effect."""
    if not callable(listener):
        raise TypeError("storage listener is not callable")
    with _lock:
        if listener not in _listeners:
            _listeners.append(listener)


def remove_listener(listener: StorageListener) -> bool:
    """Stop calling ``listener``; return whether it was registered."""
    with _lock:
        try:
            _listeners.remove(listener)
        except ValueError:
            return False
    return True


def has_listeners() -> bool:
    """Return whether an operation starting now should be reported."""
    return bool(_listeners) and not _suppressed.get()


@contextlib.contextmanager
def suppressed() -> Iterator[None]:
    """Do not report the operations started inside the block.

    A copy or a move is one operation to an observer, although it is carried out
    as a download, an upload and a delete.
    """
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)


def notify(operation: StorageOperation) -> None:
    """Hand ``operation`` to every listener; a listener that raises is logged and skipped."""
    with _lock:
        targets = list(_listeners)
    for listener in targets:
        try:
            listener(operation)
        except Exception as error:  # pylint: disable=broad-except
            # Boundary: an observer's failure must not fail the storage operation.
            file_automation_logger.error("storage observer %r failed: %r", listener, error)
