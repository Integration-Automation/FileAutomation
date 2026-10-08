"""The event bus: publishers on one side, subscribers on the other.

``publish`` delivers an event to every matching subscriber in the publisher's
thread, in subscription order. A subscriber that raises is logged and skipped,
so one broken consumer never reaches the code that reported the event. The bus
also keeps the most recent events for dashboards and status tools.

A subscription matches by event class (subclasses included), by type name
(``"task.failed"``), by type prefix (``"pipeline.*"``), and by a minimum
severity; with no filter it receives everything.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from automation_file.events.model import Event, Severity
from automation_file.logging_config import file_automation_logger

EventHandler = Callable[[Event], object]
EventFilter = type[Event] | str
_DEFAULT_HISTORY = 500
_PREFIX_SUFFIX = ".*"


def _matches_one(event: Event, wanted: EventFilter) -> bool:
    if isinstance(wanted, str):
        if wanted.endswith(_PREFIX_SUFFIX):
            return event.type.startswith(wanted[: -len(_PREFIX_SUFFIX)] + ".")
        return event.type == wanted
    return isinstance(event, wanted)


@dataclass(frozen=True)
class Subscription:
    """A handle returned by :meth:`EventBus.subscribe`; pass it to ``unsubscribe``."""

    handler: EventHandler
    types: tuple[EventFilter, ...] = ()
    min_severity: Severity = Severity.INFO

    def matches(self, event: Event) -> bool:
        if not event.severity.at_least(self.min_severity):
            return False
        return not self.types or any(_matches_one(event, wanted) for wanted in self.types)


class EventBus:
    """A thread-safe, synchronous publish/subscribe hub."""

    def __init__(self, history: int = _DEFAULT_HISTORY) -> None:
        self._lock = threading.RLock()
        self._subscriptions: list[Subscription] = []
        self._recent: deque[Event] = deque(maxlen=max(history, 0))

    def subscribe(
        self,
        handler: EventHandler,
        *,
        types: Iterable[EventFilter] | EventFilter | None = None,
        min_severity: Severity = Severity.INFO,
    ) -> Subscription:
        """Call ``handler`` for every published event that matches the filters."""
        if not callable(handler):
            raise TypeError("event handler is not callable")
        if types is None:
            wanted: tuple[EventFilter, ...] = ()
        elif isinstance(types, (str, type)):
            wanted = (types,)
        else:
            wanted = tuple(types)
        subscription = Subscription(handler, wanted, Severity(min_severity))
        with self._lock:
            self._subscriptions.append(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> bool:
        """Remove a subscription; return whether it was registered."""
        with self._lock:
            try:
                self._subscriptions.remove(subscription)
            except ValueError:
                return False
        return True

    def publish(self, event: Event) -> int:
        """Deliver ``event`` and return how many subscribers received it."""
        with self._lock:
            self._recent.append(event)
            targets = [entry for entry in self._subscriptions if entry.matches(event)]
        delivered = 0
        for subscription in targets:
            try:
                subscription.handler(event)
            except Exception as error:  # pylint: disable=broad-except
                # Boundary: a subscriber's failure must not reach the publisher.
                file_automation_logger.error(
                    "event bus: subscriber %r failed on %s: %r",
                    getattr(subscription.handler, "__qualname__", subscription.handler),
                    event.type,
                    error,
                )
            else:
                delivered += 1
        return delivered

    def recent(
        self,
        limit: int = 100,
        *,
        types: Iterable[EventFilter] | EventFilter | None = None,
        min_severity: Severity = Severity.INFO,
        correlation_id: str | None = None,
    ) -> list[Event]:
        """Return up to ``limit`` of the latest events, newest first."""
        probe = Subscription(_ignore, _as_filters(types), Severity(min_severity))
        with self._lock:
            events = list(self._recent)
        chosen = [
            event
            for event in reversed(events)
            if probe.matches(event)
            and (correlation_id is None or event.correlation_id == correlation_id)
        ]
        return chosen[: max(limit, 0)]

    def clear(self) -> None:
        """Drop every subscription and the remembered events."""
        with self._lock:
            self._subscriptions.clear()
            self._recent.clear()


def _ignore(_event: Event) -> None:
    return None


def _as_filters(types: Iterable[EventFilter] | EventFilter | None) -> tuple[EventFilter, ...]:
    if types is None:
        return ()
    if isinstance(types, (str, type)):
        return (types,)
    return tuple(types)


event_bus: EventBus = EventBus()


def emit(event: Event) -> int:
    """Publish ``event`` on the process-wide :data:`event_bus`."""
    return event_bus.publish(event)
