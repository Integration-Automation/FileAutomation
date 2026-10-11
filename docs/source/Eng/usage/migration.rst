Migrating to 1.0
================

Code written for 0.0.x keeps running: no ``FA_*`` action, facade name or command
line flag was removed. This page lists the few things that behave differently,
and, for each older interface, the newer one and when to prefer it.

What you have to do
-------------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - If you
     - Then
   * - install the package and use a cloud backend, Parquet or the GUI
     - Name the extra. The base install no longer brings the SDKs:
       ``pip install "automation_file[s3,sftp]"``, or ``[all]`` for what 0.0.x
       installed. A missing SDK fails at the first call with the command to run.
   * - use time zones in a schedule on Windows
     - Nothing: ``tzdata`` is installed with the package there.
   * - call ``copy_between`` with ``sftp://host/path`` or ``ftp://host/path``
     - Two slashes now mean a host and an absolute path, and the host must be the
       one the session is connected to. The documented one-slash form
       (``sftp:/path``, relative to the login directory) is unchanged.
   * - rely on ``copy_between`` raising ``RuntimeError`` for a backend that was
       not initialised
     - Catch ``StorageUnavailableException`` (a ``FileAutomationException``).
   * - pass a path to ``WebDAVClient`` that is a full URL on another host, or
       rely on it following redirects to another host
     - That is refused now. Build a client for that host.
   * - read ``job.cron`` or assign to it on a scheduled job
     - Reading still works. Assigning no longer reschedules the job: remove it
       and add it again.
   * - count on a scheduled action list being recorded as run when one of its
       actions raised
     - The run is now ``failed`` and publishes ``scheduler.error``. The rest of
       the list still runs.
   * - give an action server an ``ActionACL``
     - Check your allow list: an action nested in the arguments of another
       (``FA_execute_action``, a pipeline definition, a scheduled list) is now
       checked too, and must be allowed as well.
   * - narrowed the MCP server with ``--allowed-actions``
     - The same applies: a tool can no longer run an action the server does not
       expose.
   * - compared the text of a notification sink's error
     - URLs in it are now cut to the host, so a token in a path is not shown.
   * - import ``HomeTab`` or ``SchedulerTab`` to embed them
     - They still import, but the window no longer mounts them; the Dashboard
       and Scheduler pages replaced them.

Everything else in this release is an addition.

Older and newer interfaces
--------------------------

Both columns are supported. Nothing on the left is deprecated.

.. list-table::
   :header-rows: 1
   :widths: 30 34 36

   * - Older
     - Newer
     - Prefer the newer one when
   * - ``FA_s3_upload_file``, ``FA_sftp_download_file`` and the other
       per-backend actions
     - ``File`` / ``Storage`` and ``FA_storage_*`` (:doc:`storage`)
     - the same code should work on more than one backend, or you want typed
       errors, the audit trail and the events
   * - ``copy_between`` / ``FA_copy_between``
     - ``File(source).copy_to(target)``, ``FA_storage_copy``
     - you want an error instead of ``False``, and the result described
   * - ``write_manifest`` / ``verify_manifest``
     - ``IntegrityMonitor`` (:doc:`integrity`)
     - the tree is not local, or you need renames, metadata changes, watching or
       an approved baseline
   * - ``IntegrityMonitor(root, manifest_path, …)`` and ``check_once()``
     - ``IntegrityMonitor(target, baseline=…)`` with ``verify()``, ``accept()``
     - you want a ``DriftReport`` and not a summary dictionary. A baseline that
       ``accept()`` or ``create_baseline()`` wrote is no longer readable by
       ``verify_manifest``
   * - ``execute_action_dag``
     - ``Pipeline`` (:doc:`pipeline`)
     - you need retries, timeouts, resume after a crash or a history of runs
   * - ``AuditLog``
     - ``configure_audit`` and ``audit_search`` (:doc:`audit`)
     - you want every event and storage operation recorded without calling
       ``record`` yourself. ``SQLiteAuditStore.import_v1()`` copies the old rows
   * - ``notification_manager.notify`` and ``notify_on_failure``
     - notification routes (:doc:`notifications`)
     - different events should reach different sinks, with their own
       deduplication and rate limit
   * - ``FA_schedule_add`` with a cron expression
     - ``FA_schedule_job``, ``FA_schedule_pipeline`` and triggers
       (:doc:`scheduler`)
     - a job should run in a time zone, on an event, after another pipeline, or
       run a pipeline
   * - the ``FA_*`` tools of the MCP server
     - the semantic tools (:doc:`mcp`)
     - an AI host should be confined to named locations and start read-only
   * - the GUI's per-backend tabs
     - the workflow pages; the tabs are under Advanced (:doc:`gui`)
     - always, unless you need a backend-specific operation

A notification that used to arrive
----------------------------------

Two components notified the process-wide ``notification_manager`` directly and
still do: the integrity monitor on drift, and ``notify_on_failure`` for a failed
trigger or schedule. Once you start the notification router, it delivers those
events through its routes and the direct notification stops, so nothing is
announced twice. If you start the router, add a route for the events you were
being told about (``integrity.violation``, ``scheduler.error``,
``system.error``); otherwise they are published and reach no sink.

Before you upgrade production
-----------------------------

1. Install the new version with the extras you need in a fresh environment.
2. Run your tests with ``-W error::DeprecationWarning``.
3. Run ``python -m automation_file storage schemes`` and one real transfer per
   backend you use.
4. If an action server has an ``ActionACL``, send it one request of each kind
   your clients send.
5. Follow :doc:`deployment` for the state that should now live in files (the
   audit trail, the pipeline run store).
