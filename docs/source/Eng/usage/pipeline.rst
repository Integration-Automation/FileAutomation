Pipelines
=========

``automation_file.pipeline`` runs a set of tasks in dependency order, with
independent tasks in parallel, and adds what a recurring job needs: retry,
timeout, cancellation, conditions, idempotency keys, checkpoint and resume, a
dry run and an execution history.

A task is a Python callable or an ``FA_*`` action. A pipeline is built in Python
or written as a YAML / JSON document. A run reports only through events on the
bus (:doc:`event_bus`); it calls no notification sink and writes no audit row.

:func:`~automation_file.execute_action_dag` (:doc:`dag`) is unchanged. It runs a
list of actions once and returns their results; use a pipeline when the run has
to be recorded, retried, resumed or observed.

Minimal example
---------------

.. code-block:: python

   from automation_file.pipeline import Pipeline

   def count_rows(ctx):
       return len(ctx.results["read"].splitlines())

   pipeline = Pipeline("row-count")
   pipeline.task("read", ["FA_storage_read_text", {"uri": "local:///data/report.csv"}])
   pipeline.task("count", count_rows, depends_on=["read"])

   run = pipeline.run()
   run.status                      # RunStatus.SUCCEEDED; equal to "succeeded"
   run.tasks["count"].result       # 42
   run.tasks["count"].attempts     # 1

``run()`` returns when every task has ended. A task that fails does not raise:
the outcome is on ``run.status`` and on each entry of ``run.tasks``.

Production example
------------------

A nightly job: fetch a file with retry and a timeout, check it, publish it at
most once per date, take a half-published report back if publishing failed, and
keep the runs in a SQLite file so a failed run can be resumed.

.. code-block:: python

   from automation_file.pipeline import Pipeline, RetryPolicy, SQLiteRunStore

   WORK = "local:///var/tmp/report-${params.date}.csv"
   TARGET = "azure://reports/${params.date}.csv"
   store = SQLiteRunStore("/var/lib/automation/pipelines.db")

   def check(ctx):
       ctx.cancel.raise_if_cancelled()               # stop when cancelled or timed out
       if ctx.results["download"]["size"] == 0:
           raise ValueError("the report is empty")   # a task fails by raising
       return {"bytes": ctx.results["download"]["size"]}

   pipeline = Pipeline("daily-report", description="Fetch, check, publish", max_workers=4)
   pipeline.task(
       "download",
       ["FA_storage_copy", {"source": "s3://input/${params.date}.csv", "target": WORK}],
       retry=RetryPolicy(max_attempts=5, backoff_base=2.0, backoff_cap=60.0),
       timeout=300.0,
   )
   pipeline.task("check", check, depends_on=["download"], timeout=60.0)
   pipeline.task(
       "publish",
       ["FA_storage_copy", {"source": WORK, "target": TARGET}],
       depends_on=["check"],
       retry=RetryPolicy(max_attempts=3, backoff_base=1.0),
       idempotency_key="publish-${params.date}",     # never published twice for one date
   )
   pipeline.task(
       "withdraw",                                   # clean-up: runs only when publish failed
       ["FA_storage_delete", {"uri": TARGET, "missing_ok": True}],
       depends_on=["publish"],
       when="on_failure",
   )
   pipeline.task("tidy", ["FA_storage_delete", {"uri": WORK}], depends_on=["publish"])

   run = pipeline.run(params={"date": "2026-10-08"}, store=store)
   if run.status != "succeeded":
       for task_id, state in run.tasks.items():
           print(task_id, state.status.value, state.error or state.reason or "")

   # Later, in this process or another one, once the cause is fixed:
   run = pipeline.resume(run.run_id, store=store)    # runs only what did not succeed

When ``publish`` fails after its three attempts, ``withdraw`` runs, ``tidy`` is
skipped and the run is ``failed``. ``resume`` keeps ``download`` and ``check``,
runs ``publish`` again and then ``tidy``. A later run for the same date
downloads and checks again but skips ``publish``: its key has succeeded.

The same pipeline without Python, as ``daily-report.yaml``. ``check`` is a
callable and has no place in a document, so this version publishes what it
downloaded:

.. code-block:: yaml

   schema_version: 1
   name: daily-report
   description: Fetch and publish the daily report
   max_workers: 4
   schedule: {cron: "0 2 * * *", timezone: Asia/Taipei}
   params: {date: "2026-10-08"}
   tasks:
     download:
       action: ["FA_storage_copy", {"source": "s3://input/${params.date}.csv",
                                    "target": "local:///var/tmp/report-${params.date}.csv"}]
       retry: {max_attempts: 5, backoff: 2, backoff_cap: 60,
               on: [StorageTransientException, ConnectionError]}
       timeout: 300
     publish:
       action: ["FA_storage_copy", {"source": "local:///var/tmp/report-${params.date}.csv",
                                    "target": "azure://reports/${params.date}.csv"}]
       depends_on: [download]
       retry: {max_attempts: 3, backoff: 1}
       idempotency_key: "publish-${params.date}"
     withdraw:
       action: ["FA_storage_delete", {"uri": "azure://reports/${params.date}.csv",
                                      "missing_ok": true}]
       depends_on: [publish]
       when: on_failure
     tidy:
       action: ["FA_storage_delete", {"uri": "local:///var/tmp/report-${params.date}.csv"}]
       depends_on: [publish]

.. code-block:: python

   pipeline = Pipeline.from_file("daily-report.yaml")
   run = pipeline.run(params={"date": "2026-10-09"}, store=store)

Tasks
-----

A task's work is one of two things.

**A callable** taking one :class:`~automation_file.pipeline.model.TaskContext`.
What it returns is the task's result; raising fails the task.

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Field
     - Meaning
   * - ``pipeline``
     - The pipeline's name.
   * - ``run_id``
     - The ID of this run. It is also the correlation ID of every event.
   * - ``task``
     - The task's ID.
   * - ``attempt``
     - The attempt number, from 1 (``0`` in a ``when`` callable).
   * - ``params``
     - The run's parameters, read-only: the pipeline's defaults overridden by
       ``run(params=...)``.
   * - ``results``
     - Task ID to result, read-only, for every upstream task that succeeded,
       direct or not. A task that failed or was skipped has no entry.
   * - ``cancel``
     - A ``CancellationToken``, set when the run is cancelled or the task's
       timeout has passed. See `Timeout`_.
   * - ``dry_run``
     - Always ``False``: a dry run executes nothing.

**An action** in one of the three shapes ``[name]``, ``[name, {kwargs}]`` and
``[name, [args]]``. The name is looked up in the shared executor's registry (or
in the ``registry=`` given to the pipeline) and the command is called directly,
so a failure raises into the task. In the arguments, at any depth:

* ``${params.<name>}`` is replaced by the parameter. Inside longer text it is
  inserted as text; a string that is exactly one placeholder becomes the
  parameter itself, so ``"${params.limit}"`` stays the number ``20``.
* A string that is exactly ``${tasks.<id>.result}`` is replaced by the result
  object of that upstream task (``None`` if it did not succeed). The task must
  be upstream, and the placeholder cannot be part of longer text.

There is no expression language and nothing is evaluated. Any other ``${...}``
text is passed on unchanged. Because every string of the arguments is looked at,
a pipeline definition handed to ``FA_pipeline_run`` as an argument has its
placeholders filled in by the outer pipeline: pass a file path instead.

Task IDs and parameter names are non-empty strings without whitespace, ``.``,
``$``, ``{`` or ``}``.

Options
-------

``Pipeline(name, description="", max_workers=4, *, params=None, schedule=None, registry=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Option
     - Meaning
   * - ``name``
     - Identifies the pipeline in events, in the history and in idempotency keys.
   * - ``description``
     - Free text, kept in the definition.
   * - ``max_workers``
     - How many tasks run at the same time. Default ``4``.
   * - ``params``
     - Default parameters; ``run(params=...)`` adds to them and overrides them.
   * - ``schedule``
     - A ``Schedule(cron, timezone=None)``. It is kept on ``pipeline.schedule``
       for the scheduler and not acted on by the pipeline:
       ``scheduler.add_pipeline(pipeline)`` turns it into a cron trigger
       (:doc:`scheduler`).
   * - ``registry``
     - Where action names are looked up. Default: the shared executor's registry.

``pipeline.task(task_id, work, *, depends_on=None, retry=None, timeout=None, when="on_success", idempotency_key=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Option
     - Meaning
   * - ``task_id``
     - Unique in the pipeline. A second task with the same ID is rejected at once.
   * - ``work``
     - The callable or the action.
   * - ``depends_on``
     - IDs of the tasks that must end first. A task may be named before it is
       added; the graph is checked when the pipeline runs.
   * - ``retry``
     - A ``RetryPolicy``. Default: one attempt. See `Retry`_.
   * - ``timeout``
     - Seconds for the whole task. Default: no limit. See `Timeout`_.
   * - ``when``
     - ``"on_success"`` (default), ``"on_failure"``, ``"always"`` or a callable.
       See `Conditions`_.
   * - ``idempotency_key``
     - Text with ``${params.<name>}`` placeholders. See `Idempotency`_.

``RetryPolicy(max_attempts=1, backoff_base=0.0, backoff_cap=60.0, retry_on=(...))``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Option
     - Meaning
   * - ``max_attempts``
     - Attempts in total; ``1`` means no retry.
   * - ``backoff_base``
     - Seconds to wait after the first failed attempt; doubled after each
       further one.
   * - ``backoff_cap``
     - The longest wait.
   * - ``retry_on``
     - The exception classes worth another attempt. Default:
       ``StorageTransientException``, ``ConnectionError``, ``TimeoutError``.

``pipeline.run(params=None, *, dry_run=False, store=None, cancel=None, bus=None)``,
``pipeline.start(params=None, *, store=None, cancel=None, bus=None)`` and
``pipeline.resume(run_id, *, store=None, cancel=None, bus=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Option
     - Meaning
   * - ``params``
     - Parameters of this run.
   * - ``dry_run``
     - Plan without executing. See `Dry run`_.
   * - ``store``
     - The ``RunStore`` that records the run. Default: the default store.
   * - ``cancel``
     - A ``CancellationToken`` that stops the run when it is set.
   * - ``bus``
     - The ``EventBus`` that receives the events. Default: the process-wide bus.
   * - ``run_id``
     - For ``resume``: the run to continue.

``run`` works in the calling thread and returns the finished
:class:`~automation_file.pipeline.model.PipelineRun`. ``start`` returns the run at
once and works on a background thread: ``run.wait(timeout)`` blocks until it has
ended (and returns whether it has), ``run.done`` tells without blocking, and
``run.cancel()`` stops it. The interpreter does not exit while a started run is
still going.

Before anything runs, ``run``, ``start`` and ``resume`` raise
``PipelineDefinitionException`` for an empty pipeline, an unknown or repeated
dependency, a task that depends on itself, a cycle, a malformed placeholder, a
result placeholder that names a task which is not upstream, and a placeholder
for a parameter the run was not given. ``error.problems`` lists every finding
with its path; ``pipeline.problems()`` returns the same list without raising.

Statuses
--------

``run.tasks[task_id].status`` is a ``TaskStatus``, ``run.status`` a
``RunStatus``. Both compare equal to their text.

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Task status
     - Meaning
   * - ``pending``
     - Not started yet.
   * - ``running``
     - An attempt is in progress, or the task waits between two attempts.
   * - ``succeeded``
     - It returned; ``result`` holds the value.
   * - ``failed``
     - It raised and no attempt is left; ``error`` is
       ``"<ExceptionType>: <message>"``.
   * - ``skipped``
     - It did not run; ``reason`` says why (below).
   * - ``timeout``
     - It did not finish within its timeout.
   * - ``cancelled``
     - The run was cancelled before it started or while it ran, or the task
       raised ``CancelledException``.
   * - ``planned``
     - A dry run: it would be considered in this order.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - ``reason`` of a skip
     - Meaning
   * - ``idempotent``
     - Its idempotency key already has a succeeded execution; the stored result
       is reused and its dependents run.
   * - ``condition``
     - Its own ``on_failure`` or callable condition was not met.
   * - ``upstream_failed``
     - An ``on_success`` task one of whose dependencies failed, timed out or was
       cancelled.
   * - ``upstream_skipped``
     - An ``on_success`` task one of whose dependencies was skipped.

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Run status
     - Meaning
   * - ``running``
     - Not ended yet.
   * - ``succeeded``
     - Every task succeeded or was skipped.
   * - ``failed``
     - At least one task failed, timed out or was cancelled; ``run.error`` names
       them. A clean-up task that succeeds does not change this.
   * - ``cancelled``
     - The run was cancelled and at least one task did not run because of it.

A task state also has ``attempts``, ``started_at`` and ``finished_at`` (UTC),
``duration_ms``, ``level`` (0 for a task without dependencies) and
``idempotency_key`` (the key with its placeholders filled in). ``run.tasks`` is
in dependency order, and ``run.to_dict()`` is JSON-serialisable.

Conditions
----------

``when`` is looked at once, when every dependency of the task has ended.

``"on_success"``
    Every dependency succeeded (or was skipped as ``idempotent``). Otherwise the
    task is skipped, and that reaches its own ``on_success`` dependents.

``"on_failure"``
    At least one dependency failed, timed out or was cancelled. For clean-up.
    A dependency that was merely skipped does not count.

``"always"``
    Whatever happened to the dependencies.

A callable ``(TaskContext) -> bool``
    The task runs when it returns true. It decides alone: the outcome of the
    dependencies is not consulted, but ``ctx.results`` holds only those that
    succeeded. If the callable raises, the task is ``failed``.

Retry
-----

After a failed attempt the task is tried again when attempts are left and the
exception is an instance of one of ``retry_on``. The wait before attempt ``n + 1``
is ``backoff_base * 2 ** (n - 1)`` seconds, at most ``backoff_cap``.

The default ``retry_on`` holds the transient kind only. A ``ValueError`` or a
``KeyError`` is a bug or a wrong input and fails on its first attempt. Widen
``retry_on`` to the errors you know to be transient, never to ``Exception``.

Timeout
-------

``timeout`` is the budget in seconds for the whole task: every attempt and the
waits between them. When it is spent, the task is recorded as ``timeout``, its
cancellation token is set, and the run goes on with the other tasks.

**A thread cannot be killed.** The callable keeps running until it returns, and
whatever it returns or raises after the timeout is ignored. A long callable must
therefore look at its token:

.. code-block:: python

   def export(ctx):
       for chunk in chunks():
           ctx.cancel.raise_if_cancelled()     # raises CancelledException
           write(chunk)

An action cannot look at a token; give long transfers a timeout of their own
where the action has one. A task that timed out no longer counts towards
``max_workers``. Task threads are daemon threads, so one that never returns does
not keep the interpreter alive.

Cancellation
------------

``run.cancel()``, or setting the ``CancellationToken`` passed as ``cancel=``,
stops a run within a few hundredths of a second:

* every task that has not started becomes ``cancelled``, clean-up tasks included;
* every running task has its token set. The run waits for these tasks, and each
  keeps the outcome it really had: ``cancelled`` if it raised
  ``CancelledException``, ``succeeded`` if it finished anyway;
* a task waiting between two attempts stops waiting and becomes ``cancelled``.

.. code-block:: python

   run = pipeline.start(params={"date": "2026-10-08"})
   ...
   run.cancel()
   run.wait(30)
   run.status                      # "cancelled"

Idempotency
-----------

A task with an ``idempotency_key`` is not executed again once it has succeeded
under that key. Before the task starts, the key is rendered with the run's
parameters and looked up in the store for the same pipeline name and task ID.
When a succeeded execution is found, the task is ``skipped`` with the reason
``idempotent``, its ``result`` is the stored one, and its dependents run as if it
had succeeded.

The key is only as durable as the store: with the in-memory default it lasts
until the process ends, with a ``SQLiteRunStore`` it survives a restart. It is
not a lock: two runs that start at the same moment can both find nothing and
both execute the task. If the store cannot be read, the task fails instead of
running.

Checkpoint and resume
---------------------

Every transition of a task is written to the store as it happens: the start of
each attempt, each failed attempt, and the outcome. ``pipeline.resume(run_id)``
loads the run, keeps the tasks that ``succeeded`` together with their results,
and runs the others again under the same run ID and the same parameters.

.. code-block:: python

   store = SQLiteRunStore("pipelines.db")
   run = pipeline.run(params={"date": "2026-10-08"}, store=store)
   # ... the process may end here ...
   pipeline = build_pipeline()                    # the same tasks
   run = pipeline.resume(run.run_id, store=SQLiteRunStore("pipelines.db"))

The store holds the state of a run, not the pipeline: ``resume`` is called on a
pipeline with the same name. A result is stored as JSON; a value JSON cannot
hold is stored as its ``repr`` and ``result_is_repr`` is set, so after a resume
the downstream tasks see that text. Let a task whose result others need return
JSON data. A run that already succeeded is returned as stored. Do not resume a
run that is still executing somewhere else.

A kept task is not run again, so what it produced must still be there. A
clean-up task should remove what the failed task left behind, not the output of
a task that succeeded and that a later task still needs.

Dry run
-------

``pipeline.run(dry_run=True)`` executes nothing, records nothing and publishes
nothing. Every task comes back ``planned``, in dependency order with its
``level``. An action name the registry does not know and a placeholder for a
missing parameter are reported in the task's ``error``; the run is then
``failed``, otherwise ``succeeded``. A broken graph still raises.

.. code-block:: python

   plan = pipeline.run(params={"date": "2026-10-08"}, dry_run=True)
   for task_id, state in plan.tasks.items():
       print(state.level, task_id, state.error or "ok")

Run stores and history
----------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Store
     - Keeps runs
   * - ``MemoryRunStore(max_runs=1000)``
     - In memory, for the life of the process; the oldest runs are dropped
       first. This is the default store.
   * - ``SQLiteRunStore(path)``
     - In a SQLite file. Thread-safe, parameterised statements only, one commit
       per transition, and a schema version in the file.

.. code-block:: python

   from automation_file.pipeline import SQLiteRunStore, set_default_run_store

   store = SQLiteRunStore("/var/lib/automation/pipelines.db")
   set_default_run_store(store)                    # for run(), resume() and the actions

   store.get_run(run_id)                           # a PipelineRun, or None
   store.list_runs("daily-report", limit=10)       # newest first
   store.find_idempotent("daily-report", "publish", "publish-2026-10-08")

A store of your own subclasses ``RunStore`` and implements ``save_run``,
``save_task``, ``get_run``, ``list_runs`` and ``find_idempotent``; it raises
``PipelineException`` when it cannot read or write. Parameters and results are
stored as given: keep passwords and tokens out of both.

Definitions
-----------

A definition is a mapping with ``schema_version: 1``, from YAML, JSON or Python.

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Key
     - Value
   * - ``schema_version``
     - ``1``. Required; a document without it or with another value is rejected.
   * - ``name``
     - Required.
   * - ``description``, ``max_workers``, ``params``
     - As the options of ``Pipeline``.
   * - ``schedule``
     - ``{cron: "0 2 * * *", timezone: Asia/Taipei}``. ``cron`` has five fields;
       ``timezone`` is optional.
   * - ``tasks``
     - Required. Task ID to task.
   * - ``tasks.<id>.action``
     - Required. ``[name]``, ``[name, {kwargs}]`` or ``[name, [args]]``.
   * - ``tasks.<id>.depends_on``
     - A list of task IDs.
   * - ``tasks.<id>.retry``
     - ``{max_attempts, backoff, backoff_cap, on}``. ``on`` lists exception
       names: the classes of ``automation_file.exceptions``, ``TimeoutError``,
       ``ConnectionError`` and ``OSError``. Any other name is an error.
   * - ``tasks.<id>.timeout``
     - Seconds, above 0.
   * - ``tasks.<id>.when``
     - ``on_success``, ``on_failure`` or ``always``.
   * - ``tasks.<id>.idempotency_key``
     - Text with ``${params.<name>}`` placeholders.

.. code-block:: python

   from automation_file.pipeline import PIPELINE_SCHEMA, Pipeline, validate_definition

   validate_definition(document)        # [] when valid, else every problem with its path
   # ["max_workers: expected an integer >= 1, got 0",
   #  "tasks.verify.depends_on[0]: unknown task 'x'"]

   pipeline = Pipeline.from_dict(document)          # raises PipelineDefinitionException
   pipeline = Pipeline.from_file("daily-report.yaml")   # .yaml, .yml or .json
   pipeline.to_dict()                               # the document, defaults left out
   PIPELINE_SCHEMA                                  # JSON Schema (draft 2020-12), a dict

An unknown key is an error at every level. ``to_dict`` raises for a pipeline
that holds a Python callable, which a document cannot express.

YAML is read with ``yaml.safe_load``. Three things YAML does are handled:

* A key repeated in one mapping is an error (in JSON too), so a second task with
  the same ID cannot silently replace the first.
* YAML 1.1 reads a bare ``on`` as ``true``. ``from_file`` gives the ``retry``
  key back as ``on``; if you parse the YAML yourself, write ``"on"``.
* An unquoted date such as ``2026-10-08`` becomes a date object, which a
  definition cannot hold. Validation points at it: quote dates and times.

Events
------

Every event has ``source="pipeline"`` and the run ID as its ``correlation_id``,
also when it is published from a task's thread. Events published inside a task,
storage errors for instance, carry the same correlation ID and the actor of the
code that started the run.

.. list-table::
   :header-rows: 1
   :widths: 24 16 60

   * - Event
     - Severity
     - Published
   * - ``pipeline.started``
     - info
     - Once, before the first task. Again when a run is resumed.
   * - ``task.started``
     - info
     - At the start of every attempt.
   * - ``task.completed``
     - info
     - When an attempt succeeds.
   * - ``task.failed``
     - warning / error
     - When an attempt fails. ``status`` is ``retrying`` (warning: another
       attempt follows), ``failed``, ``timeout`` or ``cancelled`` (warning).
   * - ``pipeline.completed``
     - info
     - When the run ends ``succeeded``.
   * - ``pipeline.failed``
     - error / warning
     - When the run ends ``failed``, or ``cancelled`` (warning).

The payload uses the shared keys: ``pipeline``, ``run_id``, ``status``, and for
task events ``task`` and ``attempt``; ``duration_ms`` when something ended and
``error`` when it went wrong. A task that is skipped, or cancelled before it
started, publishes nothing: its state is in the run. A task whose ``when``
callable raised, or whose idempotency key could not be looked up, publishes one
``task.failed`` with ``attempt`` 0. A dry run publishes nothing.

.. code-block:: python

   from automation_file import Severity, event_bus

   def alert(event):
       print(event.subject, event.payload.get("error"))

   event_bus.subscribe(alert, types=["pipeline.failed", "task.failed"],
                       min_severity=Severity.ERROR)

Actions
-------

Pipelines are also reachable from JSON action lists, and so from the CLI, the
TCP and HTTP action servers and MCP hosts. ``definition`` is a mapping or the
path of a ``.yaml`` / ``.yml`` / ``.json`` file.

.. list-table::
   :header-rows: 1
   :widths: 26 40 34

   * - Action
     - Parameters
     - Returns
   * - ``FA_pipeline_run``
     - ``definition, params=None, dry_run=False``
     - The run (``PipelineRun.to_dict()``)
   * - ``FA_pipeline_validate``
     - ``definition``
     - ``{"valid": …, "errors": […]}``
   * - ``FA_pipeline_status``
     - ``run_id``
     - The recorded run
   * - ``FA_pipeline_history``
     - ``pipeline=None, limit=20``
     - Recorded runs, newest first
   * - ``FA_pipeline_resume``
     - ``run_id, definition``
     - The run after it was continued

.. code-block:: json

   [
     ["FA_pipeline_validate", {"definition": "pipelines/daily-report.yaml"}],
     ["FA_pipeline_run", {"definition": "pipelines/daily-report.yaml",
                          "params": {"date": "2026-10-08"}}],
     ["FA_pipeline_history", {"pipeline": "daily-report", "limit": 5}]
   ]

The actions use the default run store, so ``FA_pipeline_status``,
``FA_pipeline_history`` and ``FA_pipeline_resume`` see the runs of the same
process unless ``set_default_run_store`` was given a ``SQLiteRunStore``.
``FA_pipeline_run`` returns a run whose ``status`` is ``failed`` when a task
failed; it raises only for a definition that cannot be loaded or is invalid.
``register_pipeline_ops(registry)`` adds the actions to a registry of your own.

A definition names the actions its tasks call. As long as the definition is part
of the request, an :class:`~automation_file.ActionACL` on a TCP or HTTP action
server checks those names too, and so does ``--allowed-actions`` on the MCP
server. Neither can see inside a definition given as a file path, nor inside the
stored run ``FA_pipeline_resume`` continues: allow ``FA_pipeline_run`` and
``FA_pipeline_resume`` only for clients that may call every registered action,
or keep the definition files where those clients cannot write.

When something goes wrong
-------------------------

A task failed
    ``run.status`` is ``failed``, ``run.error`` names the tasks, and each state
    has ``error``, ``attempts`` and its times. Fix the cause and call
    ``resume(run_id)``: what succeeded is not repeated.

A task did not run
    Look at ``reason``. ``upstream_failed`` and ``upstream_skipped`` point at a
    dependency; give a task that must run anyway ``when="always"``.

A task succeeds although the work went wrong
    A task fails only by raising. An action that reports through its return
    value succeeds as a task: ``FA_storage_verify`` returns ``false`` on a
    mismatch unless it is given ``strict: true``, which makes it raise
    ``StorageChecksumException`` and so fail the task. Check any other such
    value in a callable that raises, or in a callable ``when`` of the next task.

A task is never retried
    Its exception is not in ``retry_on``. The default covers
    ``StorageTransientException``, ``ConnectionError`` and ``TimeoutError`` only.

A task is ``timeout`` but still seems to work
    Its thread could not be stopped. Make the callable watch ``ctx.cancel``, and
    make sure a second run cannot collide with what is left of the first.

A run was interrupted (the process died, Ctrl-C)
    The store has every transition up to that point, with tasks possibly left
    ``running``. ``resume(run_id)`` runs everything that had not succeeded.

``PipelineDefinitionException`` before anything ran
    The definition is wrong. ``error.problems`` holds every finding with its
    path; ``validate_definition`` and a dry run give them without running.

The history is incomplete
    A store that cannot write is logged as an error and the run goes on. The
    run itself is right; its record is not.

Both exceptions, ``PipelineException`` and its subclass
``PipelineDefinitionException``, derive from ``FileAutomationException``.
