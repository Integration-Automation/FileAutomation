"""Route events to notification sinks.

Modules publish events; they do not call a sink. A :class:`Route` says which
events go to which sinks, and the :class:`NotificationRouter` subscribes to the
event bus and delivers every matching event through the
:class:`~automation_file.notify.manager.NotificationManager`:

.. code-block:: python

    from automation_file import Route, Severity, notification_router

    notification_router.add_route(
        Route("pipeline-failures", sinks=("team-alerts",), types=("pipeline.*", "task.failed"),
              min_severity=Severity.ERROR, dedup_seconds=600, rate_limit=10, rate_period=60)
    )
    notification_router.start()

Per route and sink the router drops a repeat of the same event (same type,
source and subject) inside ``dedup_seconds`` and sends at most ``rate_limit``
messages per ``rate_period``. One sink failing never affects another; the
failure is published as a ``system.error`` event from the source ``notify``,
which the router itself never routes, so a broken sink cannot feed a loop.
"""

from __future__ import annotations

import itertools
import json
import math
import threading
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, fields
from typing import Any

from automation_file.core.metrics import record_notification
from automation_file.events import (
    Event,
    EventBus,
    EventFilter,
    Severity,
    Subscription,
    SystemErrorEvent,
    event_bus,
)
from automation_file.logging_config import file_automation_logger
from automation_file.notify.manager import (
    OUTCOME_DEDUP,
    OUTCOME_ERROR,
    OUTCOME_SENT,
    NotificationManager,
    describe_error,
    notification_manager,
)
from automation_file.notify.sinks import NotificationException

OUTCOME_RATE_LIMITED = "rate_limited"
#: The ``source`` of the events the router publishes about its own deliveries.
NOTIFY_SOURCE = "notify"
#: The origin of the routes loaded from ``automation_file.toml``.
CONFIG_ORIGIN = "config"

_THROTTLED = frozenset({OUTCOME_DEDUP, OUTCOME_RATE_LIMITED})
_FAILURE_ACTION = "notify.deliver"
_LEVELS = {
    Severity.INFO: "info",
    Severity.WARNING: "warning",
    Severity.ERROR: "error",
    Severity.CRITICAL: "error",
}
_DEFAULT_DEDUP_SECONDS = 300.0
_DEFAULT_RATE_PERIOD = 60.0
_PRUNE_INTERVAL = 30.0
_MAX_DEDUP_KEYS = 10_000
#: When the dedup memory is full, one part in this many is forgotten at once.
_FLOOD_SHARE = 10
_MAX_SUBJECT = 200
_MISSING = "-"

_DedupKey = tuple[str, str, str, str, str]
_RateKey = tuple[str, str]


def _ignore(_event: Event) -> None:
    return None


def _as_names(value: object, option: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, Iterable):
        raise NotificationException(f"route {option} must be a list of names, got {value!r}")
    names = tuple(value)
    for name in names:
        if not isinstance(name, str) or not name:
            raise NotificationException(f"route {option} must be non-empty strings, got {name!r}")
    return tuple(dict.fromkeys(names))


def _as_filters(value: object) -> tuple[EventFilter, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, type)):
        value = (value,)
    if not isinstance(value, Iterable):
        raise NotificationException(f"route types must be a list of event types, got {value!r}")
    filters = tuple(value)
    for wanted in filters:
        named = isinstance(wanted, str) and bool(wanted)
        if not named and not (isinstance(wanted, type) and issubclass(wanted, Event)):
            raise NotificationException(
                f"a route type is an event class, a type name or a 'prefix.*', got {wanted!r}"
            )
    return filters


def _as_severity(value: object) -> Severity:
    if isinstance(value, Severity):
        return value
    allowed = [severity.value for severity in Severity]
    wanted = value.strip().lower() if isinstance(value, str) else None
    if wanted in allowed:
        return Severity(wanted)
    raise NotificationException(f"min_severity must be one of {allowed}, got {value!r}")


def _as_seconds(value: object, option: str, *, positive: bool = False) -> float:
    number = math.nan
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
    if math.isfinite(number) and (number > 0 or (number == 0 and not positive)):
        return number
    wanted = "a positive number" if positive else "a number, 0 or more"
    raise NotificationException(f"route {option} must be {wanted}, got {value!r}")


def _as_count(value: object, option: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise NotificationException(f"route {option} must be an integer, 0 or more, got {value!r}")


def _filter_name(wanted: EventFilter) -> str:
    return wanted if isinstance(wanted, str) else wanted.type


@dataclass(frozen=True)
class Route:
    """Which events reach which sinks, and how often.

    ``sinks`` are names registered on the manager; empty means every sink.
    ``types`` are the bus's filters (an event class, a type name such as
    ``"task.failed"``, or a prefix such as ``"pipeline.*"``); empty means every
    type. ``sources`` are exact ``event.source`` values; empty means every
    source. ``dedup_seconds=0`` and ``rate_limit=0`` switch each guard off.
    """

    name: str
    sinks: tuple[str, ...] = ()
    types: tuple[EventFilter, ...] = ()
    sources: tuple[str, ...] = ()
    min_severity: Severity = Severity.WARNING
    dedup_seconds: float = _DEFAULT_DEDUP_SECONDS
    rate_limit: int = 0
    rate_period: float = _DEFAULT_RATE_PERIOD

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise NotificationException(f"a route needs a non-empty name, got {self.name!r}")
        normalized = {
            "sinks": _as_names(self.sinks, "sinks"),
            "types": _as_filters(self.types),
            "sources": _as_names(self.sources, "sources"),
            "min_severity": _as_severity(self.min_severity),
            "dedup_seconds": _as_seconds(self.dedup_seconds, "dedup_seconds"),
            "rate_limit": _as_count(self.rate_limit, "rate_limit"),
            "rate_period": _as_seconds(self.rate_period, "rate_period", positive=True),
        }
        for option, value in normalized.items():
            object.__setattr__(self, option, value)

    @classmethod
    def from_mapping(cls, options: Mapping[str, Any]) -> Route:
        """Build a route from a TOML table or a JSON action's arguments."""
        known = {entry.name for entry in fields(cls)}
        unknown = sorted(set(options) - known)
        if unknown:
            raise NotificationException(f"unknown route option(s) {unknown}")
        if options.get("name") is None:
            raise NotificationException("a route needs a 'name'")
        given = {key: value for key, value in options.items() if value is not None}
        return cls(**given)

    def matches(self, event: Event) -> bool:
        """Return whether ``event`` is one this route delivers."""
        if self.sources and event.source not in self.sources:
            return False
        return Subscription(_ignore, self.types, self.min_severity).matches(event)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable mapping; an event class appears as its type name."""
        return {
            "name": self.name,
            "sinks": list(self.sinks),
            "types": [_filter_name(wanted) for wanted in self.types],
            "sources": list(self.sources),
            "min_severity": self.min_severity.value,
            "dedup_seconds": self.dedup_seconds,
            "rate_limit": self.rate_limit,
            "rate_period": self.rate_period,
        }


@dataclass(frozen=True)
class NotificationMessage:
    """What one event looks like to a sink."""

    subject: str
    body: str
    level: str


def message_for(event: Event) -> NotificationMessage:
    """Build the subject, the body and the sink level of ``event``.

    The body lists the severity, type, source, subject, time, correlation ID and
    actor, then the JSON of ``event.to_dict()``. ``critical`` is sent at the
    ``error`` level, the highest one a sink accepts.
    """
    severity = event.severity.value
    headline = (
        " ".join(event.subject.split()) or f"reported by {event.source or 'an unnamed source'}"
    )
    subject = f"[{severity.upper()}] {event.type}: {headline}"
    if len(subject) > _MAX_SUBJECT:
        subject = subject[: _MAX_SUBJECT - 1] + "…"
    lines = [
        f"Severity: {severity}",
        f"Type: {event.type}",
        f"Source: {event.source or _MISSING}",
        f"Subject: {event.subject or _MISSING}",
        f"Time: {event.timestamp.isoformat()}",
        f"Correlation ID: {event.correlation_id}",
        f"Actor: {event.actor}",
    ]
    error = event.payload.get("error")
    if error:
        lines.append(f"Error: {error}")
    document = json.dumps(
        event.to_dict(), indent=2, sort_keys=True, ensure_ascii=False, default=repr
    )
    return NotificationMessage(
        subject=subject,
        body="\n".join([*lines, "", "Event:", document]),
        level=_LEVELS[event.severity],
    )


def _is_delivery_failure(event: Event) -> bool:
    """Return whether ``event`` is a router's report about a failed delivery."""
    return event.source == NOTIFY_SOURCE and event.type == SystemErrorEvent.type


class NotificationRouter:
    """Deliver events to sinks along configurable routes."""

    def __init__(
        self,
        manager: NotificationManager | None = None,
        bus: EventBus | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._manager = manager if manager is not None else notification_manager
        self._bus = bus if bus is not None else event_bus
        self._clock = clock
        self._lock = threading.RLock()
        self._routes: dict[str, Route] = {}
        self._origins: dict[str, str] = {}
        self._subscription: Subscription | None = None
        self._seen: dict[_DedupKey, float] = {}
        self._sent: dict[_RateKey, deque[float]] = {}
        self._next_prune = -math.inf

    @property
    def manager(self) -> NotificationManager:
        return self._manager

    @property
    def bus(self) -> EventBus:
        return self._bus

    @property
    def active(self) -> bool:
        """Whether the router is subscribed to its bus (between ``start`` and ``stop``)."""
        with self._lock:
            return self._subscription is not None

    def add_route(self, route: Route, *, origin: str = "") -> None:
        """Add ``route``, replacing the one with the same name.

        ``origin`` records where the route came from, for :meth:`sync_routes`.
        """
        _check_route(route)
        with self._lock:
            self._put(route, origin)
        file_automation_logger.info("notify router: route %r added", route.name)

    def remove_route(self, name: str) -> bool:
        """Remove the route called ``name``; return whether there was one."""
        with self._lock:
            removed = self._drop(name)
        if removed:
            file_automation_logger.info("notify router: route %r removed", name)
        return removed

    def routes(self) -> list[Route]:
        """Return the routes, in the order they were added."""
        with self._lock:
            return list(self._routes.values())

    def sync_routes(self, routes: Iterable[Route], *, origin: str) -> int:
        """Make ``routes`` the complete set of routes that came from ``origin``.

        Routes added earlier under the same origin and missing from ``routes``
        are removed; routes added under another origin stay. A reloaded
        configuration file uses this so a deleted table stops routing. Returns
        how many routes were removed.
        """
        wanted = list(routes)
        for route in wanted:
            _check_route(route)
        names = {route.name for route in wanted}
        with self._lock:
            stale = [
                name
                for name, owner in self._origins.items()
                if owner == origin and name not in names
            ]
            for name in stale:
                self._drop(name)
            for route in wanted:
                self._put(route, origin)
        file_automation_logger.info(
            "notify router: %d route(s) from %r, %d removed", len(wanted), origin, len(stale)
        )
        return len(stale)

    def start(self) -> None:
        """Subscribe to the bus. Starting an active router changes nothing."""
        with self._lock:
            if self._subscription is not None:
                return
            self._subscription = self._bus.subscribe(self.handle)
        file_automation_logger.info("notify router: started")

    def stop(self) -> None:
        """Unsubscribe from the bus. Stopping an inactive router changes nothing."""
        with self._lock:
            subscription, self._subscription = self._subscription, None
        if subscription is None:
            return
        self._bus.unsubscribe(subscription)
        file_automation_logger.info("notify router: stopped")

    def handle(self, event: Event) -> dict[str, str]:
        """Deliver ``event`` along every matching route.

        Returns one outcome per sink: ``"sent"``, ``"dedup"``, ``"rate_limited"``
        or the error as ``"<ExceptionType>: <message>"``. A sink reached by
        several routes gets the event once: the first route that is allowed to
        send delivers it. An event that matches no route gives an empty mapping.
        """
        if _is_delivery_failure(event):
            return {}
        outcomes: dict[str, str] = {}
        message: NotificationMessage | None = None
        for route in self._matching(event):
            for sink in route.sinks or self._manager.names():
                previous = outcomes.get(sink)
                if previous is not None and previous not in _THROTTLED:
                    continue  # an earlier route already tried this sink
                verdict = self._admit(route, sink, event)
                if verdict is not None:
                    outcomes.setdefault(sink, verdict)
                    continue
                message = message or message_for(event)
                outcomes[sink] = self._send(route, sink, event, message)
        for sink, outcome in outcomes.items():
            if outcome in _THROTTLED:
                record_notification(sink, outcome)
        return outcomes

    def _matching(self, event: Event) -> list[Route]:
        with self._lock:
            return [route for route in self._routes.values() if route.matches(event)]

    def _admit(self, route: Route, sink: str, event: Event) -> str | None:
        """Return why ``event`` must not go to ``sink`` now, or ``None`` and count it as sent."""
        now = self._clock()
        key = (route.name, sink, event.type, event.source, event.subject)
        with self._lock:
            self._prune(now)
            if route.dedup_seconds > 0 and self._seen.get(key, -math.inf) > now:
                return OUTCOME_DEDUP
            if route.rate_limit > 0:
                times = self._sent.setdefault((route.name, sink), deque())
                while times and times[0] <= now - route.rate_period:
                    times.popleft()
                if len(times) >= route.rate_limit:
                    return OUTCOME_RATE_LIMITED
                times.append(now)
            if route.dedup_seconds > 0:
                self._seen[key] = now + route.dedup_seconds
        return None

    def _send(self, route: Route, sink: str, event: Event, message: NotificationMessage) -> str:
        try:
            outcome = self._manager.send_to(sink, message.subject, message.body, message.level)
        except NotificationException as error:
            # The route names a sink the manager does not have.
            outcome = describe_error(error)
            record_notification(sink, OUTCOME_ERROR)
            file_automation_logger.error("notify router: route %r: %s", route.name, outcome)
        if outcome != OUTCOME_SENT:
            self._report_failure(route, sink, event, outcome)
        return outcome

    def _report_failure(self, route: Route, sink: str, event: Event, error: str) -> None:
        self._bus.publish(
            SystemErrorEvent(
                source=NOTIFY_SOURCE,
                subject=f"notification sink {sink!r} failed",
                payload={
                    "action": _FAILURE_ACTION,
                    "resource": sink,
                    "status": OUTCOME_ERROR,
                    "error": error,
                    "route": route.name,
                    "event_type": event.type,
                    "event_id": event.id,
                },
                correlation_id=event.correlation_id,
            )
        )

    def _put(self, route: Route, origin: str) -> None:
        if self._routes.get(route.name) != route:
            self._forget(route.name)
        self._routes[route.name] = route
        self._origins[route.name] = origin

    def _drop(self, name: str) -> bool:
        self._origins.pop(name, None)
        self._forget(name)
        return self._routes.pop(name, None) is not None

    def _forget(self, name: str) -> None:
        """Drop what is remembered about the deliveries of the route ``name``."""
        for seen in [key for key in self._seen if key[0] == name]:
            del self._seen[seen]
        for sent in [key for key in self._sent if key[0] == name]:
            del self._sent[sent]

    def _prune(self, now: float) -> None:
        if len(self._seen) > _MAX_DEDUP_KEYS:
            # A flood of distinct subjects: forget the oldest share of them.
            for key in list(itertools.islice(self._seen, _MAX_DEDUP_KEYS // _FLOOD_SHARE)):
                del self._seen[key]
        if now < self._next_prune:
            return
        self._next_prune = now + _PRUNE_INTERVAL
        for seen in [key for key, expires in self._seen.items() if expires <= now]:
            del self._seen[seen]
        idle = [key for key, times in self._sent.items() if not times or key[0] not in self._routes]
        for sent in idle:
            del self._sent[sent]


def _check_route(route: object) -> None:
    if not isinstance(route, Route):
        raise NotificationException(f"expected Route, got {type(route).__name__}")


notification_router: NotificationRouter = NotificationRouter()


def notify_route_add(
    name: str,
    sinks: list[str] | None = None,
    types: list[str] | None = None,
    sources: list[str] | None = None,
    min_severity: str = Severity.WARNING.value,
    **throttle: Any,
) -> dict[str, Any]:
    """Add or replace a route on the process-wide router, and start routing.

    ``throttle`` takes ``dedup_seconds``, ``rate_limit`` and ``rate_period``.
    Returns the route as stored.
    """
    route = Route.from_mapping(
        {
            "name": name,
            "sinks": sinks,
            "types": types,
            "sources": sources,
            "min_severity": min_severity,
            **throttle,
        }
    )
    notification_router.add_route(route)
    notification_router.start()
    return route.to_dict()


def notify_route_remove(name: str) -> bool:
    """Remove a route from the process-wide router; stop routing when none is left."""
    removed = notification_router.remove_route(name)
    if removed and not notification_router.routes():
        notification_router.stop()
    return removed


def notify_route_list() -> list[dict[str, Any]]:
    """Return every route of the process-wide router."""
    return [route.to_dict() for route in notification_router.routes()]
