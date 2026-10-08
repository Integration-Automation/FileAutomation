"""The Notifications service: the registered sinks, the routes, and a test message.

.. code-block:: python

    from automation_file.app import app_services

    notifications = app_services().notifications
    notifications.sinks()            # [{"name": "team-alerts", "type": "SlackSink", ...}]
    notifications.add_route({"name": "failures", "sinks": ["team-alerts"],
                             "types": ["pipeline.failed", "task.failed"],
                             "min_severity": "error"})
    notifications.send_test("team-alerts")      # {"team-alerts": "sent"}

A sink is described by its name, its type and where it delivers, never by its
webhook URL, token or password. Sinks themselves are registered in code or from
the configuration file (see the Settings service).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from automation_file.app.arguments import parse_argument_text, split_names
from automation_file.app.errors import AppException
from automation_file.app.masking import mask_secrets
from automation_file.events import Severity
from automation_file.notify import (
    NotificationManager,
    NotificationRouter,
    Route,
    notification_manager,
    notification_router,
)

TEST_SUBJECT = "automation_file: test notification"
TEST_BODY = "This message was sent to check that the notification sink delivers."
_LIST_OPTIONS = ("sinks", "types", "sources")
_NUMBER_OPTIONS = ("dedup_seconds", "rate_limit", "rate_period")


def _option(key: str, value: Any) -> Any:
    """Return a route option as the router expects it, read from form text when it is text."""
    if key in _LIST_OPTIONS:
        return split_names(value)
    if key in _NUMBER_OPTIONS and isinstance(value, str):
        return parse_argument_text(value)
    return value


class NotificationService:
    """Sinks and routes of one notification manager and router."""

    def __init__(
        self,
        manager: NotificationManager | None = None,
        router: NotificationRouter | None = None,
    ) -> None:
        self._manager = notification_manager if manager is None else manager
        self._router = notification_router if router is None else router

    def severities(self) -> list[str]:
        """Return the severity names a route may use as its minimum, in rising order."""
        return [severity.value for severity in Severity]

    def sinks(self) -> list[dict[str, Any]]:
        """Return a description of every registered sink, without its secrets."""
        return [mask_secrets(described) for described in self._manager.list()]

    def sink_names(self) -> list[str]:
        """Return the names of the registered sinks, in registration order."""
        return list(self._manager.names())

    def routes(self) -> list[dict[str, Any]]:
        """Return every route, in the order they were added."""
        return [route.to_dict() for route in self._router.routes()]

    def router_active(self) -> bool:
        """Return whether the router is delivering events."""
        return self._router.active

    def add_route(self, options: Mapping[str, Any]) -> dict[str, Any]:
        """Add or replace a route and start routing; return the route as stored.

        ``options`` holds ``name`` and, optionally, ``sinks``, ``types``,
        ``sources``, ``min_severity``, ``dedup_seconds``, ``rate_limit`` and
        ``rate_period``. The three lists may be given as comma-separated text.
        A sink that is not registered is refused, so a typing mistake does not
        become a route that never delivers.
        """
        given = {
            key: _option(key, value)
            for key, value in options.items()
            if value is not None and value != ""
        }
        route = Route.from_mapping(given)
        known = self._manager.names()
        unknown = [sink for sink in route.sinks if sink not in known]
        if unknown:
            raise AppException(
                f"route {route.name!r} names unknown sink(s) {unknown} (registered: {list(known)})"
            )
        self._router.add_route(route)
        self._router.start()
        return route.to_dict()

    def remove_route(self, name: str) -> bool:
        """Remove the route ``name``; stop routing when none is left. Return whether it existed."""
        removed = self._router.remove_route(name)
        if removed and not self._router.routes():
            self._router.stop()
        return removed

    def send_test(
        self,
        sink: str | None = None,
        subject: str = TEST_SUBJECT,
        body: str = TEST_BODY,
    ) -> dict[str, str]:
        """Send a test message to ``sink``, or to every sink, and return one outcome per sink.

        An outcome is ``"sent"`` or the error as ``"<ExceptionType>: <message>"``
        with its URLs reduced to the host. The deduplication window is not
        applied: a test is sent every time.
        """
        names = [sink] if sink else self.sink_names()
        if not names:
            raise AppException("no notification sink is registered; there is nothing to test")
        return {
            name: self._manager.send_to(name, subject or TEST_SUBJECT, body, "info")
            for name in names
        }
