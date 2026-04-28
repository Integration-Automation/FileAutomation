Notifications
=============

Push one-off messages or auto-notify on trigger / scheduler failures via
webhook, Slack, or SMTP:

.. code-block:: python

   from automation_file import (
       SlackSink, WebhookSink, EmailSink,
       notification_manager, notify_send,
   )

   notification_manager.register(SlackSink("https://hooks.slack.com/services/T/B/X"))
   notify_send("deploy complete", body="rev abc123", level="info")

Every sink implements the same ``send(subject, body, level)`` contract;
the fanout :class:`~automation_file.NotificationManager` handles:

- **Per-sink error isolation** — one broken sink doesn't starve the
  others.
- **Sliding-window dedup** — identical ``(subject, body, level)`` messages
  within ``dedup_seconds`` are dropped so a stuck trigger can't flood a
  channel.
- **SSRF validation** on every webhook / Slack URL.

Scheduler and trigger dispatchers auto-notify on failure at
``level="error"`` — registering a sink is all that's needed to get
production alerts. JSON forms: ``FA_notify_send`` / ``FA_notify_list``.
