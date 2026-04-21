"""Notification sinks — webhook, Slack, email — wired through a fanout manager.

Every sink exposes the same :meth:`NotificationSink.send` contract so the
manager can dispatch to many channels from one call site. The manager
deduplicates identical messages within a sliding window so a stuck
trigger cannot flood the channel, and it catches per-sink failures so one
broken sink cannot starve the others.
"""

from __future__ import annotations

from automation_file.notify.manager import (
    NotificationException,
    NotificationManager,
    notification_manager,
    notify_send,
    register_notify_ops,
)
from automation_file.notify.sinks import (
    EmailSink,
    NotificationSink,
    SlackSink,
    WebhookSink,
)

__all__ = [
    "EmailSink",
    "NotificationException",
    "NotificationManager",
    "NotificationSink",
    "SlackSink",
    "WebhookSink",
    "notification_manager",
    "notify_send",
    "register_notify_ops",
]
