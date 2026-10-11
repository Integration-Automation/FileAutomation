"""Notification sinks — webhook, Slack, email — wired through a fanout manager.

Every sink exposes the same :meth:`NotificationSink.send` contract so the
manager can dispatch to many channels from one call site. The manager
deduplicates identical messages within a sliding window so a stuck
trigger cannot flood the channel, and it catches per-sink failures so one
broken sink cannot starve the others.

The :class:`NotificationRouter` drives the sinks from the event bus: a
:class:`Route` says which events reach which sinks, with deduplication and a
rate limit per route and sink.
"""

from __future__ import annotations

from automation_file.notify.manager import (
    NotificationException,
    NotificationManager,
    notification_manager,
    notify_send,
    register_notify_ops,
)
from automation_file.notify.router import (
    NotificationMessage,
    NotificationRouter,
    Route,
    message_for,
    notification_router,
    notify_route_add,
    notify_route_list,
    notify_route_remove,
)
from automation_file.notify.sinks import (
    DiscordSink,
    EmailSink,
    NotificationSink,
    PagerDutySink,
    SlackSink,
    TeamsSink,
    TelegramSink,
    WebhookSink,
)

__all__ = [
    "DiscordSink",
    "EmailSink",
    "NotificationException",
    "NotificationManager",
    "NotificationMessage",
    "NotificationRouter",
    "NotificationSink",
    "PagerDutySink",
    "Route",
    "SlackSink",
    "TeamsSink",
    "TelegramSink",
    "WebhookSink",
    "message_for",
    "notification_manager",
    "notification_router",
    "notify_route_add",
    "notify_route_list",
    "notify_route_remove",
    "notify_send",
    "register_notify_ops",
]
