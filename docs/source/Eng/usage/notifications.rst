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

Routing events
--------------

Notifications can be driven by :doc:`events <event_bus>` instead of by modules
calling a sink: a component publishes an event, and the
:class:`~automation_file.notify.router.NotificationRouter` decides which sinks
hear about it.

.. code-block:: python

   from automation_file import (
       Route, Severity, SlackSink, notification_manager, notification_router,
   )

   notification_manager.register(SlackSink("https://hooks.slack.com/services/T/B/X",
                                           name="team-alerts"))
   notification_router.add_route(Route(
       "pipeline-failures",
       sinks=("team-alerts",),
       types=("pipeline.*", "task.failed"),
       min_severity=Severity.ERROR,
       dedup_seconds=600,
       rate_limit=10,
       rate_period=60,
   ))
   notification_router.start()          # subscribe on the event bus

The router is inactive until ``start()``; ``stop()`` unsubscribes it and
``active`` tells which state it is in. ``add_route`` replaces a route with the
same name, ``remove_route(name)`` drops one and ``routes()`` lists them. A
private router is ``NotificationRouter(manager, bus)``.

Routes
~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 22 18 60

   * - Field
     - Default
     - Meaning
   * - ``name``
     - required
     - Identifies the route.
   * - ``sinks``
     - ``()``
     - Names registered on the ``NotificationManager``. Empty means every sink.
   * - ``types``
     - ``()``
     - The bus's filters: an event class, a type name (``"task.failed"``) or a
       prefix (``"pipeline.*"``). Empty means every type.
   * - ``sources``
     - ``()``
     - Exact ``event.source`` values. Empty means every source.
   * - ``min_severity``
     - ``Severity.WARNING``
     - The lowest severity the route delivers.
   * - ``dedup_seconds``
     - ``300.0``
     - The deduplication window. ``0`` switches it off.
   * - ``rate_limit``
     - ``0``
     - Messages allowed per ``rate_period``. ``0`` means no limit.
   * - ``rate_period``
     - ``60.0``
     - The length of the rate-limit window, in seconds.

A sink reached by several routes gets an event once: the first route that is
allowed to send delivers it. An event that matches no route is not delivered.

What a sink receives
~~~~~~~~~~~~~~~~~~~~

The message is built from the event. The subject reads
``[ERROR] task.failed: load failed``; the body lists the severity, the type,
the source, the subject, the time, the correlation ID and the actor, then the
JSON of ``event.to_dict()``. The severity becomes a level the sinks accept:
``info``, ``warning`` and ``error`` keep their name, and ``critical`` is sent
as ``error``.

Deduplication and rate limiting
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Both are kept per route and per sink.

- **Deduplication** — a repeat of the same event (same type, source and
  subject) within ``dedup_seconds`` of the first one is dropped; the payload
  is not compared. A failed attempt counts too, so a dead sink is not tried
  again for every repeat.
- **Rate limiting** — at most ``rate_limit`` messages per ``rate_period``.
  An event held back by the limit is not remembered as sent, so its next
  occurrence can still go out; a duplicate does not use up the limit.

``notification_router.handle(event)`` returns one outcome per sink: ``sent``,
``dedup``, ``rate_limited``, or the error as
``"<ExceptionType>: <message>"``.

Delivery happens in the thread that published the event. Keep sink timeouts
short; the two guards bound how often a slow sink is called.

Failures
~~~~~~~~

One sink failing never affects another. Each failure is logged and published
as a ``SystemErrorEvent`` with ``source="notify"``; its payload names the sink
(``resource``), the ``route``, the ``error``, and the ``event_type`` and
``event_id`` of the event that could not be delivered. The router never routes
these events, so a broken sink cannot feed a loop; subscribe to the bus, or
search the :doc:`audit trail <audit>`, to see them. URLs in an error text are
cut down to their host, because a webhook URL or a bot token is a secret.

Routes in ``automation_file.toml``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: toml

   [[notify.sinks]]
   type = "slack"
   name = "team-alerts"
   webhook_url = "${env:SLACK_WEBHOOK}"

   [[notify.routes]]
   name = "pipeline-failures"
   sinks = ["team-alerts"]
   types = ["pipeline.*", "task.failed"]
   sources = ["pipeline"]
   min_severity = "error"
   dedup_seconds = 600
   rate_limit = 10
   rate_period = 60

.. code-block:: python

   from automation_file import (
       AutomationConfig, ConfigWatcher, notification_manager, notification_router,
   )

   def apply(config):
       config.apply_to(notification_manager, notification_router)

   watcher = ConfigWatcher("automation_file.toml", apply)
   apply(watcher.start())               # load now, and again whenever the file changes

``apply_to(manager, router)`` registers the sinks and makes the
``[[notify.routes]]`` tables the router's configured routes: a table removed
from the file stops routing at the next reload, while routes added in code
stay. The router is started when the file declares a route, and stopped when a
reload takes its last route away. A route may only name a sink declared in the file or
already registered on the manager; an unknown sink, an unknown severity, an
unknown option or a name used twice raises
:class:`~automation_file.ConfigException` before anything is changed, so a bad
reload leaves the previous routes in place. Without the ``router`` argument
the routes are not applied.

Actions
~~~~~~~

.. code-block:: json

   [
     ["FA_notify_route_add", {"name": "pipeline-failures", "sinks": ["team-alerts"],
                              "types": ["pipeline.*", "task.failed"], "min_severity": "error",
                              "dedup_seconds": 600, "rate_limit": 10, "rate_period": 60}],
     ["FA_notify_route_list"],
     ["FA_notify_route_remove", {"name": "pipeline-failures"}]
   ]

They act on the process-wide router. ``FA_notify_route_add`` starts it, and
``FA_notify_route_remove`` stops it when the last route is gone.

``notify_on_failure``
~~~~~~~~~~~~~~~~~~~~~

The scheduler and the triggers still call
``notify_on_failure(context, error)``. It now always publishes an event: a
``SchedulerError`` when the context is a scheduler job (``scheduler[nightly]``),
a ``SystemErrorEvent`` otherwise. Then:

- **router active** — the router delivers the event along its routes, and
  nothing else is sent, so nobody is notified twice;
- **router inactive** — the ``error``-level message also goes straight to
  every registered sink, exactly as before, so nobody stops being notified.

With the router active, the routes decide: a failure that no route matches is
not delivered. A route such as ``Route("failures", types=("scheduler.error",
"system.error"))`` keeps those alerts coming.
