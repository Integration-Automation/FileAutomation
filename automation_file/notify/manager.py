"""Notification fanout manager.

Owns a set of registered :class:`NotificationSink` instances and exposes
one :meth:`NotificationManager.notify` entry point. Per-sink failures are
logged and swallowed so one broken sink cannot starve the others.

A sliding deduplication window drops identical ``(subject, body, level)``
messages seen within the window, which is the minimum safety net against
a stuck trigger flooding a channel. ``dedup_seconds=0`` disables the
guard.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from automation_file.core.action_registry import ActionRegistry
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger
from automation_file.notify.sinks import (
    NotificationException,
    NotificationSink,
    _describe,
)

_DEFAULT_DEDUP_SECONDS = 60.0


class NotificationManager:
    """Fanout to registered sinks with dedup + per-sink error isolation."""

    def __init__(self, dedup_seconds: float = _DEFAULT_DEDUP_SECONDS) -> None:
        self._lock = threading.Lock()
        self._sinks: dict[str, NotificationSink] = {}
        self._recent: dict[tuple[str, str, str], float] = {}
        self.dedup_seconds = float(dedup_seconds)

    def register(self, sink: NotificationSink) -> None:
        """Register a sink under its ``sink.name`` (overwrites existing)."""
        if not isinstance(sink, NotificationSink):
            raise NotificationException(f"expected NotificationSink, got {type(sink).__name__}")
        with self._lock:
            self._sinks[sink.name] = sink
        file_automation_logger.info(
            "notify: registered sink %r (%s)", sink.name, type(sink).__name__
        )

    def unregister(self, name: str) -> bool:
        """Remove the sink registered under ``name``. Returns ``True`` if found."""
        with self._lock:
            removed = self._sinks.pop(name, None) is not None
        if removed:
            file_automation_logger.info("notify: unregistered sink %r", name)
        return removed

    def unregister_all(self) -> int:
        with self._lock:
            count = len(self._sinks)
            self._sinks.clear()
            self._recent.clear()
        return count

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            sinks = list(self._sinks.values())
        return [_describe(sink) for sink in sinks]

    def notify(
        self,
        subject: str,
        body: str = "",
        level: str = "info",
    ) -> dict[str, Any]:
        """Fan ``(subject, body, level)`` out to every registered sink.

        Returns a per-sink status dict: ``{name: "sent" | "dedup" | <error-repr>}``.
        Missing sinks return an empty dict — callers can use that to detect
        an unconfigured notifier rather than silently succeeding.
        """
        if not isinstance(subject, str) or not subject:
            raise NotificationException("subject must be a non-empty string")
        with self._lock:
            sinks = list(self._sinks.values())
            if self._should_dedup(subject, body, level):
                return {sink.name: "dedup" for sink in sinks}
        results: dict[str, Any] = {}
        for sink in sinks:
            results[sink.name] = self._deliver(sink, subject, body, level)
        return results

    def _deliver(
        self,
        sink: NotificationSink,
        subject: str,
        body: str,
        level: str,
    ) -> str:
        try:
            sink.send(subject, body, level)
        except NotificationException as err:
            file_automation_logger.error("notify: sink %r failed: %r", sink.name, err)
            return repr(err)
        except Exception as err:  # pylint: disable=broad-except
            file_automation_logger.error("notify: sink %r raised unexpectedly: %r", sink.name, err)
            return repr(err)
        return "sent"

    def _should_dedup(self, subject: str, body: str, level: str) -> bool:
        if self.dedup_seconds <= 0.0:
            return False
        key = (subject, body, level)
        now = time.monotonic()
        self._prune(now)
        if key in self._recent:
            return True
        self._recent[key] = now
        return False

    def _prune(self, now: float) -> None:
        cutoff = now - self.dedup_seconds
        stale = [key for key, ts in self._recent.items() if ts < cutoff]
        for key in stale:
            self._recent.pop(key, None)


notification_manager: NotificationManager = NotificationManager()


def notify_send(
    subject: str,
    body: str = "",
    level: str = "info",
) -> dict[str, Any]:
    """Module-level shim that dispatches through :data:`notification_manager`."""
    return notification_manager.notify(subject, body, level)


def notify_list() -> list[dict[str, Any]]:
    """Return a description of every registered sink."""
    return notification_manager.list()


def notify_on_failure(context: str, error: FileAutomationException | Exception) -> None:
    """Helper for auto-notify hooks — sends an ``error``-level message.

    Does nothing when no sinks are registered, so callers can call this
    unconditionally without having to check the configuration.
    """
    with notification_manager._lock:
        if not notification_manager._sinks:
            return
    try:
        notification_manager.notify(
            f"automation_file: {context} failed", repr(error), level="error"
        )
    except NotificationException as err:
        file_automation_logger.error("notify_on_failure: manager rejected message: %r", err)


def register_notify_ops(registry: ActionRegistry) -> None:
    """Wire ``FA_notify_*`` actions into a registry."""
    registry.register_many(
        {
            "FA_notify_send": notify_send,
            "FA_notify_list": notify_list,
        }
    )
