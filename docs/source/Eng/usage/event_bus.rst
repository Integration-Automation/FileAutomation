Events
======

Every component reports what happened as an :class:`~automation_file.Event` on
the :data:`~automation_file.event_bus`. Consumers subscribe to the bus; nothing
calls a notification sink or writes an audit row directly.

.. code-block:: python

   from automation_file import PipelineFailed, Severity, event_bus

   def page_someone(event):
       print(event.severity.value, event.subject, event.payload.get("error"))

   subscription = event_bus.subscribe(page_someone, min_severity=Severity.ERROR)
   event_bus.subscribe(print, types=["pipeline.*", "integrity.violation"])
   event_bus.subscribe(print, types=PipelineFailed)
   event_bus.recent(limit=20, min_severity=Severity.WARNING)   # newest first
   event_bus.unsubscribe(subscription)

The event
---------

An event is frozen and JSON-friendly (``event.to_dict()``).

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Field
     - Meaning
   * - ``type``
     - The kind, as a dotted name: ``pipeline.failed``.
   * - ``severity``
     - ``Severity.INFO``, ``WARNING``, ``ERROR`` or ``CRITICAL``. Each event class
       has a default; the emitter may override it.
   * - ``source``
     - The component that reports: ``pipeline``, ``integrity``, ``scheduler``,
       ``storage``, ``system``.
   * - ``subject``
     - One line for a human.
   * - ``payload``
     - The details, under conventional keys: ``pipeline``, ``run_id``, ``task``,
       ``attempt``, ``action``, ``resource``, ``backend``, ``status``,
       ``duration_ms``, ``error``, ``job``, ``trigger``.
   * - ``correlation_id``
     - Ties together everything that belongs to one run.
   * - ``actor``
     - On whose behalf it happened.
   * - ``id``, ``timestamp``
     - A unique ID and the UTC time.

Core events
-----------

.. list-table::
   :header-rows: 1
   :widths: 34 30 36

   * - Class
     - ``type``
     - Default severity
   * - ``PipelineStarted``
     - ``pipeline.started``
     - info
   * - ``PipelineCompleted``
     - ``pipeline.completed``
     - info
   * - ``PipelineFailed``
     - ``pipeline.failed``
     - error
   * - ``TaskStarted``
     - ``task.started``
     - info
   * - ``TaskCompleted``
     - ``task.completed``
     - info
   * - ``TaskFailed``
     - ``task.failed``
     - error
   * - ``IntegrityViolation``
     - ``integrity.violation``
     - error
   * - ``StorageError``
     - ``storage.error``
     - error
   * - ``SchedulerError``
     - ``scheduler.error``
     - error
   * - ``SystemErrorEvent``
     - ``system.error``
     - critical

``SystemErrorEvent`` is the roadmap's "SystemError"; the shorter name would
shadow Python's builtin exception.

Subscribing
-----------

``event_bus.subscribe(handler, types=None, min_severity=Severity.INFO)`` matches
by event class (subclasses included), by exact type name, or by prefix
(``"pipeline.*"``); without ``types`` the handler receives everything.
``publish`` delivers in the publisher's thread, in subscription order, and
returns how many handlers received the event. A handler that raises is logged
and skipped, so a broken consumer never reaches the code that reported the
event. Keep handlers quick; hand slow work to a queue or a thread.

``event_bus.recent(limit, types, min_severity, correlation_id)`` returns the
latest events the bus remembers (500 by default), newest first. A private bus is
an :class:`~automation_file.EventBus`.

Correlation and actor
---------------------

.. code-block:: python

   from automation_file import actor_scope, correlation_scope, emit, PipelineStarted

   with actor_scope("scheduler"), correlation_scope() as run_id:
       emit(PipelineStarted(source="pipeline", subject="daily-report started",
                            payload={"pipeline": "daily-report", "run_id": run_id}))
       ...   # every event and storage operation in here carries run_id and the actor

``correlation_scope()`` keeps the ID of an enclosing scope, so nested work shares
the outermost run's ID. Outside any scope each event gets an ID of its own, and
the actor is the user the process runs as. A scope does not follow work into
another thread by itself; the code that fans work out re-enters it there.

Storage operations
------------------

The storage layer reports ``upload``, ``download``, ``read``, ``delete``,
``mkdir``, ``copy`` and ``move`` to the listeners registered with
``automation_file.storage.observe.add_listener``: one
``StorageOperation(operation, uri, backend, status, duration_ms, source_uri,
error, error_type)`` per call, whether it succeeded or not. A copy or a move is
one operation, although it may be carried out as a download and an upload.
Lookups (``exists``, ``stat``, ``list_dir``, ``checksum``) are not reported.

A built-in listener publishes a ``StorageError`` event when the storage itself
fails: access denied, the backend unavailable, a transient failure, or an error
the backend could not classify. A missing file, an existing target or a
malformed URI is the caller's mistake: it raises to the caller without an event.
