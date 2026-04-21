"""Transfer progress + cancellation primitives.

Long-running transfers (HTTP downloads, S3 uploads/downloads, …) accept a
named handle from the shared :data:`progress_registry`. The registry keeps a
:class:`ProgressReporter` (bytes transferred, optional total) and a
:class:`CancellationToken` per name so the GUI or a JSON action can observe
progress or cancel mid-flight.

Instrumentation is opt-in: callers pass ``progress_name="<label>"`` to enable
tracking. When omitted, transfers run exactly as before with zero overhead
beyond one attribute lookup.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from automation_file.exceptions import FileAutomationException


class CancelledException(FileAutomationException):
    """Raised when a cancellable operation is asked to stop mid-flight."""


class CancellationToken:
    """Thread-safe boolean flag, pollable from worker threads."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise CancelledException("operation cancelled")


@dataclass
class ProgressReporter:
    """Tracks bytes transferred for one named operation."""

    name: str
    total: int | None = None
    transferred: int = 0
    status: str = "running"
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, delta: int) -> None:
        if delta <= 0:
            return
        with self._lock:
            self.transferred += delta

    def finish(self, status: str = "done") -> None:
        with self._lock:
            self.status = status
            self.finished_at = time.monotonic()

    @property
    def is_finished(self) -> bool:
        return self.finished_at is not None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "name": self.name,
                "total": self.total,
                "transferred": self.transferred,
                "status": self.status,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }


class ProgressRegistry:
    """Named handles so JSON actions / the GUI can address ongoing transfers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[ProgressReporter, CancellationToken]] = {}

    def create(
        self, name: str, total: int | None = None
    ) -> tuple[ProgressReporter, CancellationToken]:
        reporter = ProgressReporter(name=name, total=total)
        token = CancellationToken()
        with self._lock:
            self._entries[name] = (reporter, token)
        return reporter, token

    def lookup(self, name: str) -> tuple[ProgressReporter, CancellationToken] | None:
        with self._lock:
            return self._entries.get(name)

    def cancel(self, name: str) -> bool:
        with self._lock:
            entry = self._entries.get(name)
        if entry is None:
            return False
        entry[1].cancel()
        return True

    def forget(self, name: str) -> bool:
        with self._lock:
            return self._entries.pop(name, None) is not None

    def clear_finished(self) -> int:
        with self._lock:
            finished = [
                name for name, (reporter, _) in self._entries.items() if reporter.is_finished
            ]
            for name in finished:
                self._entries.pop(name, None)
        return len(finished)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            snapshots = [reporter.snapshot() for reporter, _ in self._entries.values()]
        return snapshots

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._entries


progress_registry: ProgressRegistry = ProgressRegistry()


def progress_list() -> list[dict[str, Any]]:
    """Snapshot of every registered transfer."""
    return progress_registry.list()


def progress_cancel(name: str) -> bool:
    """Cancel the named transfer. Returns ``False`` if no such handle."""
    return progress_registry.cancel(name)


def progress_clear() -> int:
    """Drop every finished transfer from the registry."""
    return progress_registry.clear_finished()


def register_progress_ops(registry: Any) -> None:
    """Wire ``FA_progress_*`` actions into an :class:`ActionRegistry`."""
    registry.register_many(
        {
            "FA_progress_list": progress_list,
            "FA_progress_cancel": progress_cancel,
            "FA_progress_clear": progress_clear,
        }
    )
