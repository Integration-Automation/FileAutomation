Audit trail
===========

The audit trail answers one question about everything the library does: **who**
did **what**, **when**, against **which resource**, using **which backend**, and
with **what result**. It is audit schema v2. Nothing writes an audit row itself:
components publish :doc:`events <event_bus>`, the storage layer reports its
operations, and an :class:`~automation_file.audit.trail.AuditTrail` turns both
into :class:`~automation_file.audit.record.AuditRecord` rows in an
:class:`~automation_file.audit.store.AuditStore`.

The v1 :class:`~automation_file.core.audit.AuditLog` stays as it is; see
`Migrating from v1`_.

Minimal example
---------------

.. code-block:: python

   from automation_file import audit_search, configure_audit

   configure_audit("audit.sqlite")          # creates the database, starts recording

   ...                                      # run pipelines, copy files, publish events

   for entry in audit_search(status="error", limit=20):
       print(entry["timestamp"], entry["actor"], entry["action"], entry["resource"],
             entry["error"])

``configure_audit`` takes the path of a SQLite database or a ready store,
points the process-wide ``audit_trail`` at it and starts it. Until it is called
the trail has no store and records nothing. ``audit_search`` returns plain
dictionaries, newest first.

Production example
------------------

.. code-block:: python

   from automation_file import (
       File, PipelineCompleted, PipelineStarted, actor_scope, audit_search,
       audit_trail, configure_audit, correlation_scope, emit,
   )

   configure_audit("/var/lib/automation_file/audit.sqlite")

   with actor_scope("scheduler"), correlation_scope() as run_id:
       emit(PipelineStarted(source="pipeline", subject="daily-report started",
                            payload={"pipeline": "daily-report", "run_id": run_id}))
       File("s3://reports/q1.csv").copy_to("local:///backup/q1.csv")   # recorded
       audit_trail.record("approve", resource="s3://reports/q1.csv", backend="s3",
                          source="review", metadata={"ticket": "OPS-12"})
       emit(PipelineCompleted(source="pipeline", subject="daily-report completed",
                              payload={"pipeline": "daily-report", "duration_ms": 812.0}))

   audit_search(correlation_id=run_id)                 # the whole run, newest first
   audit_search(resource_prefix="s3://reports/", since="2026-10-01T00:00:00+00:00")
   audit_trail.count(actor="scheduler", status="error")
   audit_trail.purge(older_than_seconds=90 * 24 * 3600)   # keep 90 days

Open the store once at start-up and let it fail fast: ``configure_audit``
raises :class:`~automation_file.AuditException` when the database cannot be
opened. Run the purge from a scheduled job. Everything inside the two scopes
carries the same correlation ID and actor, so one filter returns the run.

A trail of your own, on a private bus or with another store:

.. code-block:: python

   from automation_file import AuditTrail, EventBus, SQLiteAuditStore

   trail = AuditTrail(SQLiteAuditStore("tenant-a.sqlite"), bus=EventBus())
   trail.start()
   ...
   trail.stop()
   trail.store.close()

The record
----------

An ``AuditRecord`` is frozen and JSON-friendly (``to_dict()`` /
``AuditRecord.from_dict()``).

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Field
     - Meaning
   * - ``id``
     - A unique ID. The record of an event has the event's ID.
   * - ``timestamp``
     - When it happened, as an aware UTC ``datetime``. A time without a time
       zone is rejected.
   * - ``actor``
     - **Who**: the actor of the enclosing ``actor_scope``, or the user the
       process runs as.
   * - ``source``
     - The component that reported: ``pipeline``, ``storage``, ``scheduler``,
       ``notify``, ...
   * - ``pipeline``, ``task``
     - The pipeline and the task it belongs to, when there is one.
   * - ``action``
     - **What**: the event type (``task.failed``) or the storage operation
       (``upload``, ``download``, ``read``, ``delete``, ``mkdir``, ``copy``,
       ``move``).
   * - ``resource``
     - **Which resource**: a storage URI or another target.
   * - ``backend``
     - **Which backend**: the storage scheme (``s3``, ``local``, ...).
   * - ``status``
     - **What result**: ``ok``, ``warning``, ``error``, or the word the emitter
       chose.
   * - ``duration_ms``
     - How long it took, when that is known.
   * - ``error``
     - ``"<ExceptionType>: <message>"`` when it failed.
   * - ``metadata``
     - Everything else, as JSON values. What JSON cannot hold is kept as its
       ``repr``.
   * - ``correlation_id``
     - The run it belongs to; ``None`` outside any ``correlation_scope``.

What is recorded
----------------

**Events.** Every event on the bus becomes one record. ``source``, ``actor``,
``timestamp`` and ``correlation_id`` are the event's; ``action`` is the event
type; ``pipeline``, ``task``, ``resource``, ``backend``, ``status``,
``duration_ms`` and ``error`` come from the payload keys of the same name. The
event's ``subject`` and ``severity`` and every other payload key go under
``metadata``. When the payload has no ``status``, the severity decides: ``ok``
for info, ``warning`` for warning, ``error`` for error and critical.

**Storage operations.** Every upload, download, read, delete, mkdir, copy and
move becomes one record with ``source="storage"``, the operation as the
``action``, the URI as the ``resource`` and the scheme as the ``backend``,
whether it succeeded or not. A copy or a move is one record; its origin is
``metadata["source_uri"]``.

**A failed storage operation is recorded once.** The storage layer reports the
operation, and the storage bridge also publishes a ``storage.error`` event for
it. The trail keeps the operation and skips that event.

**By hand.** ``audit_trail.record(action, **fields)`` appends one record; the
actor and the correlation ID default to the current scopes.

Filters
-------

``search`` and ``count`` take the same filters by name; ``search`` returns the
newest records first.

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Filter
     - Matches
   * - ``since``, ``until``
     - The time range: ``since`` is included, ``until`` is excluded. An aware
       ``datetime``, an ISO 8601 string with an offset or a ``Z``, or seconds
       since the epoch.
   * - ``actor``, ``source``, ``pipeline``, ``task``, ``action``, ``backend``,
       ``status``, ``correlation_id``
     - The field is exactly this value.
   * - ``resource_prefix``
     - The resource starts with this text.
   * - ``text``
     - The text occurs in the action, resource, error, actor, source, pipeline,
       task, backend or the JSON of the metadata.
   * - ``limit``, ``offset``
     - Paging. ``limit`` defaults to 100 and may not exceed 10 000. ``count``
       ignores both.

``resource_prefix`` and ``text`` take the text literally -- ``%`` and ``_`` are
ordinary characters -- and ignore the case of ASCII letters. A filter given as
``None`` does not restrict the search. An unknown filter name or a value of the
wrong kind raises ``AuditException`` instead of quietly returning everything.

The store interface
-------------------

``AuditStore`` is the interface a store implements: the SQLite store today, a
PostgreSQL or remote store later.

.. code-block:: python

   from automation_file import AuditQuery, AuditRecord, AuditStore

   class MyStore(AuditStore):
       def append(self, record: AuditRecord) -> None: ...
       def search(self, **filters) -> list[AuditRecord]:
           query = AuditQuery.from_filters(filters)      # validated filters
           ...
       def count(self, **filters) -> int: ...
       def purge(self, older_than_seconds: float) -> int: ...
       def close(self) -> None: ...

A store is append-only, safe to share between threads, answers ``search``
newest first, rejects a record whose ``id`` it already holds, and raises
``AuditException`` for every failure. ``AuditQuery.from_filters`` validates the
filters the same way for every store.

``SQLiteAuditStore(path)`` keeps the records in one table with a second table
that states the schema version (``2``), and indexes on the timestamp, the
correlation ID, the resource and the action. Every value reaches SQLite as a
bound parameter and the ``LIKE`` wildcards in a filter are escaped. One
connection is shared by all threads behind a lock, in WAL mode, so another
process can read while this one writes. ``MemoryAuditStore()`` keeps the
records in the process and is meant for tests.

Migrating from v1
-----------------

.. code-block:: python

   from automation_file import SQLiteAuditStore

   store = SQLiteAuditStore("audit.sqlite")
   store.import_v1("old-audit.sqlite3")      # returns how many rows were new

Each v1 row becomes a record with ``source="audit.v1"`` and the actor
``unknown``; its payload and result go under ``metadata``. The v1 database is
only read, and importing it again adds nothing.

Actions
-------

``register_audit_ops(registry)`` wires four actions; they act on the
process-wide trail.

.. code-block:: json

   [
     ["FA_audit_configure", {"db_path": "/var/lib/automation_file/audit.sqlite"}],
     ["FA_audit_search", {"status": "error", "since": "2026-10-01T00:00:00+00:00", "limit": 50}],
     ["FA_audit_count", {"correlation_id": "4f0c2b6e9d5a4c1f8a7b3e2d1c0f9a8b"}],
     ["FA_audit_purge", {"older_than_seconds": 7776000}]
   ]

``FA_audit_search`` and ``FA_audit_count`` take the filters above;
``FA_audit_search`` returns each record as its ``to_dict()``.

A client that may purge the trail can erase its own tracks. On a TCP or HTTP
action server pass an :class:`~automation_file.ActionACL` that denies
``FA_audit_purge`` and ``FA_audit_configure``, and on the MCP server leave them
out of ``--allowed-actions``, unless remote clients are meant to manage the
trail.

When something goes wrong
-------------------------

- **A record cannot be written.** The failure is logged
  (``audit trail: cannot write the record of ...``) and the record is dropped.
  It is never raised into the code that is being audited: a full disk must not
  stop a pipeline. Watch the log for that line, and alert on it.
- **The database cannot be opened.** ``configure_audit`` and
  ``SQLiteAuditStore`` raise ``AuditException``. Open the store at start-up so
  this is seen at once.
- **The database was written by a newer version.** The store refuses to open
  it rather than guess at its layout.
- **Durability.** The SQLite store commits every record. In WAL mode a crash of
  the process loses nothing; a power failure may lose the last moments. Keep
  the database on a local disk: WAL does not work on a network share.
- **Growth.** Nothing is deleted on its own. Call ``purge`` or
  ``FA_audit_purge`` on a schedule with your retention period.
- **Searching before configuring.** ``audit_search`` raises ``AuditException``
  when no store is configured, so an empty answer always means "no match".
- **Threads.** A scope does not follow work into another thread by itself; the
  code that fans work out re-enters ``correlation_scope`` and ``actor_scope``
  there, or its records carry no correlation ID.
- **Secrets.** Payloads are stored as they are. Do not put a credential in an
  event payload or in ``metadata``.

Operational metrics
-------------------

The same events and storage operations feed Prometheus counters, next to the
per-action metrics ``automation_file_actions_total`` and
``automation_file_action_duration_seconds``:

.. code-block:: python

   from automation_file import install_operational_metrics, start_metrics_server

   install_operational_metrics()        # once; calling it again changes nothing
   start_metrics_server(host="127.0.0.1", port=9945)

.. list-table::
   :header-rows: 1
   :widths: 62 38

   * - Metric
     - Labels
   * - ``automation_file_events_total``
     - ``type``, ``severity``
   * - ``automation_file_notifications_total``
     - ``sink``, ``outcome`` (``sent``, ``dedup``, ``rate_limited``, ``error``)
   * - ``automation_file_storage_operations_total``
     - ``operation``, ``backend``, ``status``
   * - ``automation_file_storage_operation_duration_seconds`` (histogram)
     - ``operation``, ``backend``

``install_operational_metrics()`` subscribes to the event bus and to the
storage observers. The notification counter needs no installation: the
notification manager and the router count every delivery themselves. No label
ever carries a path, a URI or a correlation ID, and each label keeps at most
100 distinct values; further values are counted as ``other``.
