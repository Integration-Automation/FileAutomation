Scheduler
=========

``automation_file.scheduler`` runs an action list or a :doc:`pipeline <pipeline>`
when something fires it: a cron expression with an optional time zone, a file
event, an event on the bus, the end of another pipeline's run, or a call. Cron is
one trigger among several, and every job goes through the same scheduler.

Every firing leaves a record in one of seven states: ``scheduled``, ``started``,
``completed``, ``failed``, ``skipped``, ``timeout`` and ``cancelled``. A job does
not overlap itself unless it says so, a run can be given a timeout and can be
cancelled, and a run that fails or times out is published as a
``scheduler.error`` event (:doc:`event_bus`).

Minimal example
---------------

.. code-block:: python

   from automation_file.scheduler import scheduler

   scheduler.add(
       "nightly-snapshot",
       "0 2 * * *",                              # every day at 02:00 ...
       [["FA_zip_dir", {"dir_we_want_to_zip": "/data",
                        "zip_name": "/backup/data_nightly"}]],
       timezone="Asia/Taipei",                   # ... in Taipei; local time without it
   )

   scheduler.history(job="nightly-snapshot", limit=5)    # the latest runs, newest first

``scheduler`` is the process-wide instance. Adding the first job starts its
background thread, which is a daemon thread: keep the process alive yourself.

Production example
------------------

A pipeline every night at 02:00 Taipei time, a second pipeline that runs when the
first one has succeeded, and a message to the team when a run fails or takes too
long.

.. code-block:: python

   import os

   from automation_file import Route, SlackSink, notification_manager, notification_router
   from automation_file.pipeline import SQLiteRunStore, set_default_run_store
   from automation_file.scheduler import PipelineTrigger, scheduler

   # Scheduled pipelines record their runs in the default run store.
   set_default_run_store(SQLiteRunStore("/var/lib/automation/pipelines.db"))

   # A failed or timed-out run is a scheduler.error event; this route delivers it.
   notification_manager.register(SlackSink(os.environ["SLACK_WEBHOOK"], name="team-alerts"))
   notification_router.add_route(
       Route("scheduler-failures", sinks=("team-alerts",), types=("scheduler.error",))
   )
   notification_router.start()

   # daily-report.yaml declares   schedule: {cron: "0 2 * * *", timezone: Asia/Taipei}
   scheduler.add_pipeline(
       "pipelines/daily-report.yaml",
       params={"date": "${date:%Y-%m-%d}"},      # the date in Taipei when the job fires
       timeout=3600,                             # cancelled after an hour
   )

   # No schedule of its own: it runs whenever a run of daily-report has succeeded.
   scheduler.add_pipeline(
       "pipelines/publish-summary.yaml",
       triggers=PipelineTrigger("daily-report"),
       timeout=900,
   )

   for run in scheduler.history(state="failed", limit=10):
       print(run.job, run.scheduled_at, run.error, run.correlation_id)

``daily-report`` starts at 18:00 UTC, which is 02:00 in Taipei, with ``date`` set
to the Taipei date. When its run ends ``succeeded``, ``publish-summary`` is fired;
when it fails, ``publish-summary`` is not fired and the route sends
``[ERROR] scheduler.error: scheduler[daily-report] failed``. While a run of
``daily-report`` is still going, the next firing is recorded as ``skipped``.

A pipeline that fails also publishes ``pipeline.failed`` and ``task.failed`` by
itself. Route either those or ``scheduler.error`` to a sink; a route with both
sends two messages for one failure.

Jobs and targets
----------------

A job has a name, a target, and any number of triggers.

**An action list** runs through the shared executor, one action after the other.
An action that raises fails the run, and the remaining actions still run, as in
``execute_action``. The values the actions return are not kept.

**A pipeline** is a :class:`~automation_file.pipeline.Pipeline`, a definition
mapping, or the path of a ``.yaml`` / ``.yml`` / ``.json`` definition file. The
definition is checked when the job is registered, and a file is read once, at
that moment: remove the job and register it again after changing the file. Each
firing calls ``pipeline.run()`` with the default run store, so
``FA_pipeline_status`` and ``FA_pipeline_history`` see the run.

``add_pipeline`` reads the pipeline's ``schedule`` and makes it a cron trigger,
time zone included; the job is named after the pipeline unless ``name`` is given.
``add_job`` takes a pipeline too and does not read its ``schedule``.

``params`` are the parameters of every run of a pipeline job; they are added to
the pipeline's own defaults and override them. In a string, at any depth,
``${date:FORMAT}`` is replaced when the job fires (``FORMAT`` is a ``strftime``
format; a bare ``${date}`` gives ``2026-10-08T02:00:00``). The time used is the
job's own: the zone of its first cron trigger, or local time when it has none.
Nothing else is replaced, and an action list takes no ``params``.

Triggers
--------

.. list-table::
   :header-rows: 1
   :widths: 14 36 50

   * - Kind
     - In Python
     - Fires
   * - ``cron``
     - ``CronTrigger(cron, timezone=None)``
     - At the minutes the expression names.
   * - ``manual``
     - ``scheduler.run_now(name)``
     - When it is called. Every job can be fired this way.
   * - ``file``
     - ``FileTrigger(path, events=("created", "modified"), recursive=True)``
     - When a file under ``path`` is created, modified, deleted or moved.
   * - ``event``
     - ``EventTrigger(types=(), sources=(), min_severity=Severity.INFO)``
     - When a matching event is published on the event bus.
   * - ``pipeline``
     - ``PipelineTrigger(pipeline, when="on_success")``
     - When a run of the named pipeline has ended.

.. code-block:: python

   from automation_file.scheduler import (
       CronTrigger, EventTrigger, FileTrigger, PipelineTrigger, scheduler,
   )

   scheduler.add_job(
       "sweep-inbox",
       [["FA_copy_all_file_to_dir", {"source_dir": "/data/inbox",
                                     "target_dir": "/data/processed"}]],
       triggers=[
           CronTrigger("*/30 * * * *", "UTC"),                      # every half hour
           FileTrigger("/data/inbox", events=["created"]),          # and on a new file
       ],
   )

A job may have several triggers, of any kinds, and overlap protection covers all
of them. A job without a trigger runs only when it is fired by hand.

Cron
~~~~

Five fields: minute (0-59), hour (0-23), day of month (1-31), month (1-12) and
day of week (0-6, Sunday is 0 or 7). Each takes ``*``, a value, a range
``a-b``, a list ``a,b,c`` and a step ``*/n`` or ``a-b/n``; months and weekdays
also take ``jan``..``dec`` and ``sun``..``sat``. There are no seconds and no
``@daily`` aliases.

The scheduler looks at the clock every second and handles each minute once. A
minute during which the process was not running, or the machine was asleep, is
not made up afterwards. See `Time zones and daylight saving time`_ for the zone.

Manual
~~~~~~

.. code-block:: python

   run = scheduler.run_now("nightly-snapshot")     # a JobRun
   run.wait(600)                                   # True once the run has ended
   run.state                                       # RunState.COMPLETED; equal to "completed"

``run_now`` returns the record of the firing at once. The record is ``skipped``
when the job is still running and does not allow overlap. From JSON, and so from
the HTTP action server, it is ``FA_schedule_run``.

File events
~~~~~~~~~~~

``FileTrigger`` uses :class:`~automation_file.trigger.FileWatcher`, the watcher
behind ``FA_watch_start`` (:doc:`events`). The scheduler owns the watcher: it is
not listed by ``FA_watch_list`` and it stops when the job is removed. The record
of a run holds the file and the event in ``detail``
(``{"path": "/data/inbox/a.csv", "event": "created"}``).

Saving one file often produces several events. Each one is a firing; those that
arrive while the job is running are recorded as ``skipped``.

Events and webhooks
~~~~~~~~~~~~~~~~~~~

``EventTrigger`` matches what the bus matches: type names (``"task.failed"``),
prefixes (``"pipeline.*"``) and event classes in ``types``, exact
``event.source`` values in ``sources``, and a lowest severity. At least one type
or one source is required.

This is also how a webhook fires a job. The code that receives the request
publishes an event, and every job with a matching trigger runs:

.. code-block:: python

   from dataclasses import dataclass
   from typing import ClassVar

   from automation_file import Event, emit
   from automation_file.scheduler import EventTrigger, scheduler

   @dataclass(frozen=True, kw_only=True)
   class DeployFinished(Event):
       type: ClassVar[str] = "deploy.finished"

   scheduler.add_job(
       "smoke-test",
       [["FA_execute_files", [["checks/smoke.json"]]]],
       triggers=EventTrigger(types="deploy.finished", sources="webhook"),
   )

   # In the handler of your web framework, once the request has been verified:
   emit(DeployFinished(source="webhook", subject="release 1.4 deployed"))

A request to the HTTP action server (:doc:`servers`) can fire one job by name
instead: ``[["FA_schedule_run", {"name": "smoke-test"}]]``. That run is recorded
as ``manual``.

The trigger's handler runs in the thread that published the event and only
starts the run. An event published by a run of the job itself does not fire the
job again, so a job that listens for ``scheduler.error`` does not loop on its
own failure.

Jobs that fire one another through their events form a chain. The firing that
would make a chain longer than 16 runs starts nothing: it is recorded as
``skipped`` with the reason ``chain``, so two jobs that fire each other stop
instead of going on for ever.

Pipeline dependency
~~~~~~~~~~~~~~~~~~~

``PipelineTrigger("daily-report")`` fires when a run of the pipeline named
``daily-report`` has ended. ``when`` uses the pipeline's own words:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - ``when``
     - Fires when the run
   * - ``"on_success"``
     - succeeded. This is the default.
   * - ``"on_failure"``
     - failed or was cancelled.
   * - ``"always"``
     - ended, however it ended.

The trigger listens for ``pipeline.completed`` and ``pipeline.failed``, so it
sees every run of that pipeline on the scheduler's bus: one the scheduler
started, one started with ``pipeline.run()``, one started by ``FA_pipeline_run``.
The record's ``detail`` names the pipeline, the run ID and the status of the run
that fired it. A pipeline job cannot depend on its own pipeline, and two
pipelines that depend on each other are stopped by the chain limit above.

Options
-------

``scheduler.add(name, cron_expression, action_list, *, allow_overlap=False, timezone=None, timeout=None)``

``scheduler.add_job(name, target, *, triggers=None, allow_overlap=False, timeout=None, params=None)``

``scheduler.add_pipeline(pipeline, *, name=None, triggers=None, allow_overlap=False, timeout=None, params=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Option
     - Meaning
   * - ``name``
     - Identifies the job. A second job with the same name is refused. For
       ``add_pipeline`` the default is the pipeline's name.
   * - ``cron_expression``
     - The five fields of ``add``.
   * - ``action_list`` / ``target`` / ``pipeline``
     - What the job runs. See `Jobs and targets`_.
   * - ``triggers``
     - One trigger or several: objects, or their mappings (see `Actions`_).
   * - ``allow_overlap``
     - Let a firing start while the job is still running. Default ``False``.
   * - ``timezone``
     - The zone ``add`` reads its expression in. Default: local time.
   * - ``timeout``
     - Seconds a run may take, above 0. Default: no limit. See `Timeout`_.
   * - ``params``
     - Parameters of a pipeline job's runs.

Each of the three returns the job's snapshot, the mapping ``scheduler.list()``
holds for every job:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Key
     - Value
   * - ``name``
     - The job's name.
   * - ``cron``, ``timezone``
     - The expression and the zone of the first cron trigger; ``""`` and
       ``None`` when the job has none.
   * - ``triggers``
     - Every trigger as a mapping.
   * - ``target``, ``pipeline``, ``actions``
     - ``"actions"`` or ``"pipeline"``, the pipeline's name, and the number of
       actions in the list.
   * - ``allow_overlap``, ``timeout``
     - As given.
   * - ``runs``, ``skipped``
     - How many firings were started, and how many were skipped.
   * - ``running``
     - Whether a run's thread is still alive. See `Timeout`_.
   * - ``last_run``
     - When the last run was fired, in the job's own time: with an offset when
       the job has a time zone, in local time without one.
   * - ``last_state``
     - The state the last run ended in.

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Call
     - Does
   * - ``remove(name)``, ``remove_all()``
     - Remove jobs and stop their triggers. A run in progress goes on.
   * - ``list()``
     - The snapshot of every job.
   * - ``run_now(name)``
     - Fire a job by hand; returns the ``JobRun``.
   * - ``cancel(name)``
     - Cancel the job's runs in progress; returns their records.
   * - ``history(job=None, state=None, limit=50)``
     - The latest records, newest first.
   * - ``start()``, ``shutdown(timeout=5.0, *, cancel_running=False)``
     - See `Starting and stopping`_.
   * - ``tick(now=None)``
     - Handle the current minute and the timeouts once, for a scheduler that is
       driven by hand. See `Starting and stopping`_.

Run records and states
----------------------

``scheduler.history()`` returns :class:`~automation_file.scheduler.JobRun`
objects; ``run.to_dict()`` is JSON-serialisable.

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Field
     - Meaning
   * - ``run_id``
     - The ID of this firing.
   * - ``job``
     - The job's name.
   * - ``trigger``
     - ``cron``, ``manual``, ``file``, ``event`` or ``pipeline``.
   * - ``detail``
     - What fired the run: the expression and zone, the file and event, the
       event's type, ID, source and subject, or the pipeline, run ID and status.
   * - ``target``, ``pipeline``
     - ``"actions"`` or ``"pipeline"``, and the pipeline's name.
   * - ``state``
     - A ``RunState``. It compares equal to its text.
   * - ``scheduled_at``
     - When the run was due: the minute, for cron.
   * - ``started_at``, ``finished_at``
     - When the target started and when the record was closed.
   * - ``duration_ms``
     - The time between the two.
   * - ``error``
     - What went wrong, for ``failed`` and ``timeout``.
   * - ``reason``
     - ``overlap`` or ``chain`` for a skipped firing, ``cancelled`` for a
       cancelled run.
   * - ``correlation_id``
     - The ID every event of the run carries. For an action list it is
       ``run_id``. For a pipeline it becomes the pipeline's run ID as soon as the
       pipeline starts, which is the ID ``FA_pipeline_status`` takes.

All times are timezone-aware UTC. The target runs inside
``correlation_scope(run_id)`` with the actor ``scheduler``, so storage errors
and audit records of the run carry the same ID.

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - State
     - Meaning
   * - ``scheduled``
     - The firing was accepted and its thread has not begun yet.
   * - ``started``
     - The target is running.
   * - ``completed``
     - Every action returned, or the pipeline's run succeeded.
   * - ``failed``
     - At least one action raised, the pipeline's run did not succeed, or the
       target could not be run at all. ``error`` says which.
   * - ``skipped``
     - Nothing was started: the job was still running and does not allow overlap,
       or the firing came at the end of a chain of 16 runs.
   * - ``timeout``
     - The run did not end within its timeout.
   * - ``cancelled``
     - ``cancel`` stopped the run.

The history is kept in memory, per scheduler, and holds the latest 1000 records
(``Scheduler(history_limit=...)``); the oldest go first. It does not survive the
process. The runs of a scheduled pipeline are also in the pipeline's run store,
and every failure is an event that the :doc:`audit trail <audit>` can keep.

Overlap protection
------------------

Unless a job was registered with ``allow_overlap=True``, a firing that arrives
while the job is running starts nothing. It is recorded as ``skipped`` with the
reason ``overlap``, counted in the job's ``skipped``, and logged as a warning.
This holds for every kind of trigger, ``run_now`` included.

A job counts as running until the thread of its run has really ended. After a
timeout or a cancellation that can be later than the record says.

Timeout
-------

``timeout`` is the number of seconds a run may take, counted from the moment it
was fired. The scheduler checks once a second. When the time is up, the record
becomes ``timeout``, a ``scheduler.error`` event is published, and the run is
told to stop:

* a pipeline is cancelled through its cancellation token, exactly as
  ``run.cancel()`` does: tasks that have not started become ``cancelled`` and
  running tasks are told through ``ctx.cancel``;
* an action list stops before its next action.

**A thread cannot be killed.** The action that is running, or a pipeline task
that does not look at its token, goes on until it returns. The job keeps
counting as running until then, so the next firing is skipped and two runs never
collide. What the thread does after the timeout does not change the record.

Give a pipeline's tasks timeouts of their own as well (:doc:`pipeline`): a task
timeout fails one task and lets clean-up tasks run, while the job's timeout
stops the whole run.

Cancellation
------------

.. code-block:: python

   cancelled = scheduler.cancel("daily-report")    # the records, now "cancelled"

``cancel(name)`` closes the records of the job's runs in progress as
``cancelled`` and stops the runs the same way a timeout does. It returns an empty
list when the job is not running, and raises ``SchedulerException`` for a name
that is neither registered nor running. A cancelled run publishes no
``scheduler.error``. Removing a job does not cancel a run in progress.

Time zones and daylight saving time
-----------------------------------

``timezone`` is an IANA name such as ``Asia/Taipei`` or ``America/New_York``, or
``UTC``. Zone data comes from the standard library's ``zoneinfo``, which reads
the system's database. Windows has none: install the ``tzdata`` package there
(``pip install tzdata``). ``UTC`` works without it. A name that cannot be found
raises ``CronException`` when the job is registered.

A cron trigger without a time zone is read in the local time of the machine, as
the scheduler always did. In a container that is usually UTC: give production
jobs a zone.

In a zone with daylight saving time:

* **a local time that does not exist is not fired.** On the day the clocks go
  from 02:00 to 03:00, ``30 2 * * *`` does not run;
* **a local time that occurs twice fires once**, the first time. On the day the
  clocks go back from 02:00 to 01:00, ``30 1 * * *`` runs once;
* an expression whose hour field is ``*`` runs every hour anyway, so it keeps
  firing through the repeated hour: ``*/15 * * * *`` runs every 15 minutes of
  real time on both days.

A job that must run at a fixed interval, or exactly once a day whatever the
clocks do, is best scheduled in ``UTC``. A trigger without a time zone follows
the system clock and gets none of this treatment: the repeated hour fires twice.

Events
------

A run that ends ``failed`` or ``timeout`` publishes one ``SchedulerError``
(``scheduler.error``, severity ``error``, source ``scheduler``) on the
scheduler's bus. Its subject is ``scheduler[<job>] failed`` or
``scheduler[<job>] timed out`` and its correlation ID is the record's
``correlation_id``.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Payload key
     - Value
   * - ``job``
     - The job's name.
   * - ``trigger``
     - What fired the run.
   * - ``status``
     - ``failed`` or ``timeout``.
   * - ``error``
     - The record's ``error``. URLs in it are cut down to their host.
   * - ``target``
     - ``actions`` or ``pipeline``.
   * - ``scheduler_run_id``
     - The record's ``run_id``.
   * - ``duration_ms``
     - Present when the target had started.
   * - ``pipeline``, ``run_id``
     - For a pipeline target: its name, and the pipeline's run ID once the
       pipeline had started.

``completed``, ``skipped`` and ``cancelled`` publish nothing; they are in the
history and in the log.

One failure is reported differently. An action list that the executor does not
accept at all (an empty list, something that is not a list) is reported through
:func:`~automation_file.notify.manager.notify_on_failure`, as before. It
publishes the ``scheduler.error`` event itself, with the payload ``job``,
``status`` (``error``), ``error`` and ``context``, on the process-wide bus; and
while the notification router is not active it also sends the message straight
to every registered sink (:doc:`notifications`). Every other failure is an event
only: add a route for ``scheduler.error`` to be told about it.

Actions
-------

.. list-table::
   :header-rows: 1
   :widths: 26 44 30

   * - Action
     - Parameters
     - Returns
   * - ``FA_schedule_add``
     - ``name, cron_expression, action_list, allow_overlap=False, timezone=None,
       timeout=None``
     - The job's snapshot
   * - ``FA_schedule_job``
     - ``name, action_list, triggers=None, allow_overlap=False, timeout=None``
     - The job's snapshot
   * - ``FA_schedule_pipeline``
     - ``definition, name=None, triggers=None, params=None, allow_overlap=False,
       timeout=None``
     - The job's snapshot
   * - ``FA_schedule_run``
     - ``name``
     - The record of the firing
   * - ``FA_schedule_cancel``
     - ``name``
     - The cancelled records
   * - ``FA_schedule_history``
     - ``job=None, state=None, limit=50``
     - Records, newest first
   * - ``FA_schedule_list``
     - (none)
     - Every job's snapshot
   * - ``FA_schedule_remove``
     - ``name``
     - The removed job's snapshot
   * - ``FA_schedule_remove_all``
     - (none)
     - The removed jobs' snapshots

They act on the process-wide ``scheduler``. ``definition`` is a mapping or the
path of a definition file, and its ``schedule`` becomes a cron trigger. In
``FA_schedule_add``, ``allow_overlap``, ``timezone`` and ``timeout`` are passed by
name. A trigger is a mapping with its ``kind`` and that kind's arguments:

.. list-table::
   :header-rows: 1
   :widths: 14 86

   * - ``kind``
     - Keys
   * - ``cron``
     - ``cron`` (required), ``timezone``
   * - ``file``
     - ``path`` (required), ``events``, ``recursive``
   * - ``event``
     - ``types``, ``sources``, ``min_severity``; types are names and prefixes
   * - ``pipeline``
     - ``pipeline`` (required), ``when``

.. code-block:: json

   [
     ["FA_schedule_pipeline", {"definition": "pipelines/daily-report.yaml",
                               "params": {"date": "${date:%Y-%m-%d}"},
                               "timeout": 3600}],
     ["FA_schedule_pipeline", {"definition": "pipelines/publish-summary.yaml",
                               "triggers": [{"kind": "pipeline",
                                             "pipeline": "daily-report"}]}],
     ["FA_schedule_job", {"name": "sweep-inbox",
                          "action_list": [["FA_copy_all_file_to_dir",
                                           {"source_dir": "/data/inbox",
                                            "target_dir": "/data/processed"}]],
                          "triggers": [{"kind": "file", "path": "/data/inbox",
                                        "events": ["created"]}]}],
     ["FA_schedule_run", {"name": "daily-report"}],
     ["FA_schedule_history", {"job": "daily-report", "limit": 5}]
   ]

``register_scheduler_ops(registry)`` adds the actions to a registry of your own.

A job names the actions it will run later. As long as the action list or the
definition is part of the request, an :class:`~automation_file.ActionACL` on a
TCP or HTTP action server checks those names too. It cannot see inside a
definition given as a file path, and ``FA_schedule_run`` runs whatever a job that
is already registered holds: allow ``FA_schedule_pipeline`` and
``FA_schedule_run`` only for clients that may call every registered action.

Starting and stopping
---------------------

.. code-block:: python

   from automation_file.scheduler import Scheduler

   scheduler = Scheduler(history_limit=5000)      # a scheduler of your own
   scheduler.shutdown()                           # stop the thread and every trigger
   scheduler.start()                              # ... and bring them back

``Scheduler(*, clock=None, bus=None, history_limit=1000, autostart=True)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Option
     - Meaning
   * - ``clock``
     - A callable returning the current time as an aware ``datetime``. Default:
       the system clock in UTC.
   * - ``bus``
     - The ``EventBus`` the scheduler listens and reports on, and the one its
       pipelines publish on. Default: the process-wide bus.
   * - ``history_limit``
     - How many records are kept. Default ``1000``.
   * - ``autostart``
     - Start the background thread when a job is added. Default ``True``.

``shutdown()`` stops the background thread, every file watcher and every bus
subscription the scheduler made. The jobs stay registered; ``start()``, or adding
another job, arms them again. Runs in progress are left to finish unless
``shutdown(cancel_running=True)`` is used. All the scheduler's threads are daemon
threads, so they never keep the interpreter alive.

With ``autostart=False`` nothing happens by itself: ``tick(now)`` handles the
minute of ``now`` and the timeouts due at ``now``, and returns the records of
what it fired. That is how to test a schedule without waiting for it:

.. code-block:: python

   from datetime import datetime, timezone

   from automation_file.scheduler import Scheduler

   engine = Scheduler(autostart=False)
   engine.add("nightly", "0 2 * * *", [["FA_schedule_list"]], timezone="Asia/Taipei")
   engine.tick(datetime(2026, 10, 7, 17, 59, tzinfo=timezone.utc))      # []
   (run,) = engine.tick(datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc))
   run.wait(10)
   run.state                                       # "completed"

When something goes wrong
-------------------------

A job did not run at its time
    Look for a ``skipped`` record first: the previous run was still going. If
    there is no record at all, the minute was not handled: the process was not
    running or the machine was asleep (minutes are not made up), the local time
    did not exist that day, or the expression is read in another zone than you
    think. A trigger without ``timezone`` uses the machine's local time.

``CronException: unknown time zone``
    The name is misspelt, or the machine has no zone data: on Windows, install
    ``tzdata``.

A run is ``failed`` although most of it worked
    One action raised and the rest of the list ran. ``error`` lists the actions
    that failed, by position and name.

A run is ``completed`` although the work went wrong
    A run fails only when an action raises or a pipeline's run does not succeed.
    An action that reports through its return value completes: see the same
    entry in :doc:`pipeline`.

A run is ``timeout`` or ``cancelled`` but the job still shows ``running``
    Its thread could not be stopped and is still in the action or the task it
    was in. The job stays busy, and its firings are skipped, until that returns.
    Give long transfers a timeout of their own, and make long pipeline tasks
    watch ``ctx.cancel``.

A job fires more often than expected
    One saved file is several file events; two triggers of one job both fire it;
    a job with ``allow_overlap=True`` is not held back by a run in progress.

A record is ``skipped`` with the reason ``chain``
    Sixteen runs fired one another in a row: two jobs listen for each other's
    events, or two pipelines depend on each other. Break the cycle; a job that
    has to repeat belongs on a cron trigger.

A dependent pipeline never fires
    The name in ``PipelineTrigger`` is not the upstream pipeline's ``name``, the
    upstream run did not end the way ``when`` asks for, or it published on
    another bus than the scheduler's.

An event trigger does not fire
    Check ``types``, ``sources`` and ``min_severity`` against
    ``event_bus.recent()``. Events published by the job's own run are ignored on
    purpose.

No notification arrived
    The router must be started and must have a route that matches
    ``scheduler.error``. Without the router, only an action list the executor
    rejects is sent straight to the sinks.

The history is empty
    It is kept in memory and ends with the process; a scheduler of your own has
    a history of its own. Pipeline runs are in the run store.

Nothing fires after ``shutdown()``
    The jobs are still registered but their triggers are stopped. Call
    ``start()``.

``SchedulerException`` is raised for a duplicate or unknown job, a wrong
trigger, a wrong timeout and a wrong history query, and ``CronException`` for an
expression or a time zone that cannot be understood. A definition that is wrong
raises ``PipelineDefinitionException`` and a watch path that does not exist
``TriggerException``, both when the job is registered. All of them derive from
``FileAutomationException``.
