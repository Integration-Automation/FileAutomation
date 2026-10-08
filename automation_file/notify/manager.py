"""Notification fanout manager.

Owns a set of registered :class:`NotificationSink` instances and exposes
one :meth:`NotificationManager.notify` entry point. Per-sink failures are
logged and swallowed so one broken sink cannot starve the others.

A sliding deduplication window drops identical ``(subject, body, level)``
messages seen within the window, which is the minimum safety net against
a stuck trigger flooding a channel. ``dedup_seconds=0`` disables the
guard.

:meth:`NotificationManager.send_to` delivers to one named sink without that
window; the :class:`~automation_file.notify.router.NotificationRouter` uses it
and applies its own deduplication and rate limits per route.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from automation_file.core.action_registry import ActionRegistry
from automation_file.core.metrics import record_notification
from automation_file.events import Event, SchedulerError, SystemErrorEvent, emit
from automation_file.exceptions import FileAutomationException
from automation_file.logging_config import file_automation_logger
from automation_file.notify.sinks import (
    NotificationException,
    NotificationSink,
    _describe,
)

_DEFAULT_DEDUP_SECONDS = 60.0
OUTCOME_SENT = "sent"
OUTCOME_DEDUP = "dedup"
OUTCOME_ERROR = "error"
_REDACTED = "<redacted>"
# A webhook URL or a bot token is a secret, and the HTTP client quotes the URL
# in its error text. Keep the host, drop everything after it.
_URL_PATTERN = re.compile(r"(?i)\b(https?://)(?:[^/\s@'\"]*@)?([^/\s'\"]+)[^\s'\")]*")
_URL_PATH_PATTERN = re.compile(r"(?i)(\burl: )\S+")
_CONTEXT_PATTERN = re.compile(r"(?P<kind>[A-Za-z_]+)\[(?P<name>.*)\]", re.DOTALL)
_SCHEDULER_KIND = "scheduler"
_TRIGGER_KIND = "trigger"
_SYSTEM_SOURCE = "system"


def redact_urls(text: str) -> str:
    """Return ``text`` with the path and credentials of every URL removed."""
    text = _URL_PATTERN.sub(rf"\1\2/{_REDACTED}", text)
    return _URL_PATH_PATTERN.sub(rf"\1{_REDACTED}", text)


def describe_error(error: BaseException) -> str:
    """Return ``"<ExceptionType>: <message>"`` for ``error`` with its URLs redacted."""
    return f"{type(error).__name__}: {redact_urls(str(error))}"


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

    def names(self) -> tuple[str, ...]:
        """Return the names of the registered sinks, in registration order."""
        with self._lock:
            return tuple(self._sinks)

    def has_sinks(self) -> bool:
        """Return whether at least one sink is currently registered."""
        with self._lock:
            return bool(self._sinks)

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
        _check_subject(subject)
        with self._lock:
            sinks = list(self._sinks.values())
            duplicate = self._should_dedup(subject, body, level)
        if duplicate:
            for sink in sinks:
                record_notification(sink.name, OUTCOME_DEDUP)
            return {sink.name: OUTCOME_DEDUP for sink in sinks}
        results: dict[str, Any] = {}
        for sink in sinks:
            results[sink.name] = self._deliver(sink, subject, body, level)
        return results

    def send_to(self, name: str, subject: str, body: str = "", level: str = "info") -> str:
        """Deliver one message to the sink registered as ``name``.

        Returns ``"sent"``, or ``"<ExceptionType>: <message>"`` when the sink
        failed; the failure is logged and never raised. The deduplication
        window of :meth:`notify` does not apply. Raises
        :class:`NotificationException` when no sink has that name.
        """
        _check_subject(subject)
        with self._lock:
            sink = self._sinks.get(name)
        if sink is None:
            raise NotificationException(f"no notification sink is registered as {name!r}")
        failure = self._attempt(sink, subject, body, level)
        return OUTCOME_SENT if failure is None else describe_error(failure)

    def _deliver(
        self,
        sink: NotificationSink,
        subject: str,
        body: str,
        level: str,
    ) -> str:
        failure = self._attempt(sink, subject, body, level)
        return OUTCOME_SENT if failure is None else redact_urls(repr(failure))

    def _attempt(
        self,
        sink: NotificationSink,
        subject: str,
        body: str,
        level: str,
    ) -> Exception | None:
        """Send through ``sink``; return what it raised, or ``None`` when it delivered."""
        try:
            sink.send(subject, body, level)
        except NotificationException as err:
            file_automation_logger.error(
                "notify: sink %r failed: %s", sink.name, describe_error(err)
            )
            record_notification(sink.name, OUTCOME_ERROR)
            return err
        except Exception as err:  # pylint: disable=broad-except
            # Boundary: one sink's bug must not reach the other sinks or the caller.
            file_automation_logger.error(
                "notify: sink %r raised unexpectedly: %s", sink.name, describe_error(err)
            )
            record_notification(sink.name, OUTCOME_ERROR)
            return err
        record_notification(sink.name, OUTCOME_SENT)
        return None

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


def _check_subject(subject: str) -> None:
    if not isinstance(subject, str) or not subject:
        raise NotificationException("subject must be a non-empty string")


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


def failure_event(context: str, error: BaseException) -> Event:
    """Return the event that reports ``context`` failing with ``error``.

    ``scheduler[<job>]`` becomes a :class:`SchedulerError` whose payload names
    the ``job``. Any other context becomes a :class:`SystemErrorEvent`; its
    source is the word before the brackets (``trigger[inbox]`` gives
    ``trigger``, with the name under the ``trigger`` key) or ``system`` when
    the context has none.
    """
    subject = f"{context} failed"
    payload: dict[str, Any] = {
        "status": OUTCOME_ERROR,
        "error": describe_error(error),
        "context": context,
    }
    match = _CONTEXT_PATTERN.fullmatch(context)
    if match is None:
        return SystemErrorEvent(source=_SYSTEM_SOURCE, subject=subject, payload=payload)
    kind, name = match.group("kind"), match.group("name")
    if kind == _SCHEDULER_KIND:
        payload["job"] = name
        return SchedulerError(source=_SCHEDULER_KIND, subject=subject, payload=payload)
    if kind == _TRIGGER_KIND:
        payload["trigger"] = name
    return SystemErrorEvent(source=kind, subject=subject, payload=payload)


def notify_on_failure(context: str, error: FileAutomationException | Exception) -> None:
    """Report that ``context`` failed.

    The failure is always published on the event bus. When the notification
    router is active it delivers the event and nothing else is sent; when it is
    not, the ``error``-level message goes straight to every registered sink, as
    it did before the router existed.

    Does nothing more when no sinks are registered, so callers can call this
    unconditionally without having to check the configuration.
    """
    from automation_file.notify.router import notification_router

    emit(failure_event(context, error))
    if notification_router.active or not notification_manager.has_sinks():
        return
    try:
        notification_manager.notify(
            f"automation_file: {context} failed", repr(error), level="error"
        )
    except NotificationException as err:
        file_automation_logger.error("notify_on_failure: manager rejected message: %r", err)


def register_notify_ops(registry: ActionRegistry) -> None:
    """Wire ``FA_notify_*`` actions into a registry."""
    from automation_file.notify.router import (
        notify_route_add,
        notify_route_list,
        notify_route_remove,
    )

    registry.register_many(
        {
            "FA_notify_send": notify_send,
            "FA_notify_list": notify_list,
            "FA_notify_route_add": notify_route_add,
            "FA_notify_route_remove": notify_route_remove,
            "FA_notify_route_list": notify_route_list,
        }
    )
