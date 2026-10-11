Application layer
=================

``automation_file.app`` is what a user interface calls. It has one service per
navigation entry -- Dashboard, Files, Storage, Pipelines, Scheduler, Integrity,
Audit, Notifications, Settings -- each a plain Python object on top of the
domain packages (:doc:`storage`, :doc:`pipeline`, :doc:`events`,
:doc:`integrity`, :doc:`audit`, :doc:`notifications`, :doc:`event_bus`,
:doc:`config`).

The PySide6 window (:doc:`gui`) and the Web UI (:doc:`servers`) call these
services and nothing below them. That is why they show the same state, and why
a third interface -- a terminal UI, a web application, a chat bot -- needs no
knowledge of the domain packages either.

The layer keeps four promises:

* It imports no GUI toolkit and no backend SDK. ``import automation_file.app``
  works on the base install.
* It returns dataclasses, dictionaries and lists that JSON can hold.
* It masks tokens, passwords and webhook URLs in what it returns.
* It raises ``FileAutomationException`` subclasses: the domain's own
  (``StorageException``, ``PipelineException`` ...) and ``AppException`` for
  what only this layer checks.

Minimal example
---------------

.. code-block:: python

   from automation_file.app import app_services

   services = app_services()                       # one set per process

   summary = services.dashboard.summary()
   print(summary.status, summary.reasons)          # "ok" () or "attention" (...)

   for entry in services.files.list_dir("local:///data"):
       print(entry.name, entry.size)

   draft = services.pipelines.new_draft("nightly")
   draft.add_task("FA_storage_copy", "download",
                  arguments={"source": "s3://in/a.csv", "target": "local:///tmp/a.csv"})
   run = services.pipelines.start(draft)           # returns at once
   services.pipelines.wait(run["run_id"], timeout=60)
   print(services.pipelines.status(run["run_id"])["status"])

The services
------------

``automation_file.app.NAVIGATION`` is the tuple of the nine entries in display
order; ``AppServices`` has one attribute per entry, named in lower case.

.. list-table::
   :header-rows: 1
   :widths: 18 24 58

   * - Entry
     - Attribute and class
     - What it does
   * - Dashboard
     - ``dashboard``, ``DashboardService``
     - One summary: health, runs, integrity drift, recent events, storage
       status.
   * - Files
     - ``files``, ``FileService``
     - List, stat, preview, copy, move, delete, mkdir on storage URIs.
   * - Storage
     - ``storage``, ``StorageService``
     - Schemes, mounts, and whether each backend can be used.
   * - Pipelines
     - ``pipelines``, ``PipelineService``
     - Drafts, validation, dry run, background runs, status, history, resume,
       cancel, definition files.
   * - Scheduler
     - ``scheduler``, ``SchedulerService``
     - List, add and remove cron jobs.
   * - Integrity
     - ``integrity``, ``IntegrityService``
     - Baseline, verify, accept, status, start and stop a monitor.
   * - Audit
     - ``audit``, ``AuditService``
     - Configure, search and count audit records.
   * - Notifications
     - ``notifications``, ``NotificationService``
     - Registered sinks, routes, a test message.
   * - Settings
     - ``settings``, ``SettingsService``
     - Load and apply a configuration file; which extras are installed.

Dashboard
---------

.. code-block:: python

   summary = services.dashboard.summary()
   summary.to_dict()                    # JSON-serialisable

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Field
     - Meaning
   * - ``status``, ``reasons``
     - ``"ok"``, or ``"attention"`` with one sentence per reason: a recent run
       failed, a monitor found drift or could not verify, the bus holds a
       recent event of severity ``error`` or worse.
   * - ``health``
     - Counts and switches: registered actions, running runs, scheduled jobs,
       monitors, sinks, routes, router active, the state of the audit trail.
   * - ``run_counts``
     - How the newest fifty runs ended: ``running``, ``succeeded``,
       ``failed``, ``cancelled``.
   * - ``running_runs``, ``recent_runs``
     - Runs without their task details, newest first.
   * - ``integrity``
     - What every named monitor last found.
   * - ``events``
     - The latest events of the bus, newest first, masked.
   * - ``storage``
     - Every backend with ``usable``, ``detail`` and, when a package is
       missing, ``install_hint``.

The parts are also available one by one: ``health()``, ``runs()``,
``integrity()``, ``recent_events()``, ``storage_status()``. ``summary()`` never
raises for a part that cannot be read; it names the part among the reasons.

Files
-----

.. code-block:: python

   files = services.files
   files.list_dir("s3://reports/2026")              # directories first, then by path
   files.stat("s3://reports/2026/q1.csv").size
   preview = files.preview("s3://reports/2026/q1.csv", max_bytes=4096)
   preview.text, preview.truncated, preview.binary
   files.copy("s3://reports/2026/q1.csv", "local:///backup/")   # into the directory
   files.move("local:///inbox/a.csv", "local:///done/a.csv")
   files.mkdir("local:///backup/2026")
   files.delete("local:///backup/2026", recursive=True)

A preview is bounded twice. At most ``preview_bytes`` (64 KiB) are returned, and
a remote file larger than ``fetch_limit`` (16 MiB) is not fetched: a backend
without ranged reads has to download a file before any of it can be read. Both
limits are arguments of ``FileService``. Binary content comes back as a
hexadecimal dump with ``binary`` set.

A directory is copied with everything below it and cannot be moved. Every URI
goes through the storage layer, so ``..`` and credentials in a URI are refused.

Storage
-------

.. code-block:: python

   storage = services.storage
   for backend in storage.backends():
       print(backend.name, backend.kind, backend.usable, backend.detail)
   storage.mount_local("sandbox://jobs", "/srv/jobs")     # confined to that directory
   storage.mounts()
   storage.capabilities("sandbox://jobs")
   storage.unmount("sandbox://jobs")

``backends()`` returns one ``BackendStatus`` per scheme, per mount, and per
shared client without a scheme. ``usable`` is true for the local and in-memory
backends, for a mount, and for a cloud backend whose client was initialised.
Otherwise ``detail`` says how to initialise it or, when the package of its
extra is missing, carries the ``pip install`` command (also in
``install_hint``). Nothing here opens a connection.

Pipelines
---------

The draft
~~~~~~~~~

A pipeline editor cannot edit a ``Pipeline``: that object refuses anything
invalid, and a definition under construction is invalid most of the time. A
``PipelineDraft`` holds whatever was entered so far.

.. code-block:: python

   from automation_file.app import PipelineDraft

   draft = PipelineDraft("daily-report")
   draft.set_params({"date": "2026-10-08"})
   draft.add_task("FA_storage_copy", "download",
                  arguments={"source": "s3://in/${params.date}.csv",
                             "target": "local:///tmp/report.csv"})
   draft.add_task("FA_storage_delete", "tidy", arguments={"uri": "local:///tmp/report.csv"})
   draft.connect("download", "tidy")               # tidy depends on download
   draft.set_retry("download", max_attempts=5, backoff=2.0, on=["ConnectionError"])
   draft.set_timeout("download", 300)
   draft.set_condition("tidy", "always")
   draft.rename_task("tidy", "clean-up")            # edges and placeholders follow

   draft.problems()                                 # [] or Problem(path, message, task)
   draft.to_definition()                            # what Pipeline.from_dict takes

.. list-table::
   :header-rows: 1
   :widths: 36 64

   * - Method
     - Effect
   * - ``add_task``, ``remove_task``, ``rename_task``
     - Change the set of tasks. An ID is derived from the action name when
       none is given.
   * - ``set_action``, ``set_arguments``
     - The action and its keyword mapping, positional list or ``None``.
   * - ``set_retry``, ``set_timeout``, ``set_condition``, ``set_idempotency_key``
     - How the task runs.
   * - ``connect``, ``disconnect``, ``set_dependencies``, ``edges``
     - Dependency edges. An edge to itself or one that closes a cycle is
       refused with ``AppException``.
   * - ``set_position``, ``positions``, ``auto_layout``, ``layout``, ``apply_layout``
     - Where each task sits on a canvas. This is editor metadata: it never
       appears in ``to_definition()``.
   * - ``set_name``, ``set_description``, ``set_max_workers``, ``set_params``, ``set_schedule``
     - The header of the definition.
   * - ``add_listener``, ``batch``
     - ``listener(change)`` is called after every change with ``"structure"``,
       ``"task"``, ``"header"`` or ``"position"``; inside ``with draft.batch():``
       each kind is reported once, at the end.
   * - ``problems``, ``to_definition``, ``from_definition``
     - Validation with the path of every problem, and the definition document.

A value the runtime would refuse (a negative timeout, an unknown action name)
is kept and reported by ``problems()``; only an edit that would leave the draft
inconsistent (a duplicate ID, a cycle) raises at once. A draft is not
thread-safe: edit it from one thread and hand a worker ``draft.to_definition()``.

Checking and running
~~~~~~~~~~~~~~~~~~~~

Every method takes a draft or a definition mapping and returns plain
dictionaries. A run is ``PipelineRun.to_dict()`` with its secrets masked and an
``active`` flag that says whether this process is still executing it.

.. code-block:: python

   pipelines = services.pipelines

   pipelines.action_names()                         # for a palette
   pipelines.describe_action("FA_storage_copy")     # parameters, defaults, summary

   pipelines.validate(draft)                        # also: an unknown action name
   plan = pipelines.dry_run(draft, {"date": "2026-10-09"})
   outcome = pipelines.test_task(draft, "download", {"date": "2026-10-09"})

   run = pipelines.start(draft, {"date": "2026-10-09"})     # background
   followed = pipelines.follow(run["run_id"])       # {"run": ..., "events": [...]}
   pipelines.cancel(run["run_id"])
   pipelines.wait(run["run_id"], timeout=30)

   pipelines.resume(run["run_id"], draft)           # keep what succeeded, run the rest
   pipelines.retry(run["run_id"], draft)            # a new run, same parameters
   pipelines.history("daily-report", limit=10)
   pipelines.running()

``start`` and ``resume`` return at once; a definition problem raises before
anything runs. ``test_task`` executes one task alone: its action really runs,
its upstream tasks are replaced by stand-ins that return the values given in
``results=`` (``None`` by default), and the test is recorded in no run store and
published on no shared bus.

Definition files and layout
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   draft = pipelines.load("pipelines/daily-report.yaml")
   draft.load_notes                                 # what was wrong with the file, if anything
   pipelines.save(draft, "pipelines/daily-report.yaml")

``save`` writes the definition as ``.yaml``, ``.yml`` or ``.json`` and the canvas
layout into ``<file>.layout.json`` next to it. A definition refuses unknown
keys, and a layout is no part of what runs, so the two never share a file.
``load`` opens a file that parses but is not valid, so it can be repaired.

Scheduler
---------

.. code-block:: python

   scheduler = services.scheduler
   scheduler.add("nightly", "0 2 * * *",
                 [["FA_pipeline_run", {"definition": "pipelines/daily-report.yaml"}]])
   scheduler.jobs()
   scheduler.remove("nightly")
   scheduler.remove_all()

``add`` also takes the action list as JSON text, as a form supplies it. The
service calls only ``schedule_add``, ``schedule_remove``, ``schedule_remove_all``
and ``schedule_list`` (:doc:`events`).

Integrity
---------

.. code-block:: python

   integrity = services.integrity
   integrity.baseline("s3://reports/2026", "local:///var/lib/fa/reports.json")
   report = integrity.verify("s3://reports/2026", "local:///var/lib/fa/reports.json")
   report["ok"], report["counts"], report["changes"]
   integrity.accept("s3://reports/2026", "local:///var/lib/fa/reports.json")

   integrity.start_monitor("reports", "s3://reports/2026",
                           "local:///var/lib/fa/reports.json", interval=300)
   integrity.drift()                    # MonitorDrift per monitor, for a dashboard
   integrity.stop_monitor("reports")
   integrity.stop_started()             # the monitors this service started

A monitor started here is the named monitor the ``FA_integrity_*`` actions see.

Audit
-----

.. code-block:: python

   audit = services.audit
   audit.status()                       # {"configured": False, ...} until it has a store
   audit.configure("/var/lib/automation_file/audit.sqlite")
   audit.search(status="error", resource_prefix="s3://reports/", limit=20)
   audit.count(actor="scheduler")
   audit.recent(limit=30)               # [] while audit is not configured

A filter given as ``None`` or as an empty text does not restrict the search, so
the values of a form can be passed as they are.

Notifications
-------------

.. code-block:: python

   notifications = services.notifications
   notifications.sinks()                # name, type, destination; never a secret
   notifications.add_route({"name": "failures", "sinks": "team-alerts, ops-mail",
                            "types": "pipeline.failed, task.failed",
                            "min_severity": "error", "dedup_seconds": "600"})
   notifications.routes()
   notifications.remove_route("failures")
   notifications.send_test("team-alerts")           # {"team-alerts": "sent"}

Lists may be comma-separated text and numbers may be text. A route that names a
sink that is not registered is refused. ``send_test`` returns one outcome per
sink: ``"sent"`` or the error, with its URLs reduced to the host.

Settings
--------

.. code-block:: python

   settings = services.settings
   settings.load("automation_file.toml")            # a summary; nothing changes
   settings.apply("automation_file.toml")           # registers sinks and routes
   for extra in settings.extras():
       print(extra.name, extra.installed, extra.install_hint)
   settings.environment()                           # versions, platform, log file

The summary holds the file's sections, sinks and routes, and the document with
every secret masked.

Form helpers
------------

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Function
     - What it does
   * - ``parse_argument_text(text)``
     - One form field to a value: JSON when the text is JSON, else the text.
   * - ``format_argument_value(value)``
     - The way back: text that reads back as the same value.
   * - ``parse_json_text(text, what)``
     - A JSON document from a text field, or ``AppException`` naming ``what``
       and the position of the mistake.
   * - ``split_names(text)``
     - ``"a, b"`` to ``["a", "b"]``.
   * - ``describe_action(name, command)``
     - The parameters, the defaults and the summary of an action.

Secrets
-------

``mask_secrets(value)`` returns a copy that is safe to show, and every service
applies it to what it returns:

* a value stored under a name that says it is a secret (``password``,
  ``token``, ``api_key``, ``authorization`` ...) becomes ``********``;
* a value stored under ``url`` or ``..._url`` keeps its scheme and host;
* in any other text, the user information of a URL and the token after
  ``Bearer`` are removed.

A storage URI is left alone: it cannot carry credentials. A task's result is
returned as it is, so keep secrets out of results.

Shared and private services
---------------------------

``app_services()`` returns one set per process, built on the process-wide
singletons (the default resolver, the default run store, the event bus, the
audit trail, the notification manager and router). The window and the Web UI of
one process therefore show the same runs, monitors and routes.

``build_services`` makes a set of its own:

.. code-block:: python

   from automation_file.app import ServiceOptions, build_services
   from automation_file.events import EventBus
   from automation_file.pipeline import SQLiteRunStore

   services = build_services(ServiceOptions(
       run_store=SQLiteRunStore("/var/lib/automation/pipelines.db"),
       bus=EventBus(),
   ))

``ServiceOptions`` takes ``resolver``, ``run_store``, ``registry``, ``bus``,
``audit_trail``, ``notification_manager`` and ``notification_router``. The
scheduler and the integrity monitors are process-wide whatever the options.

Writing another user interface
------------------------------

1. Get the services: ``app_services()``, or ``build_services(...)``.
2. Build the navigation from ``NAVIGATION``.
3. For each view, call one service method and render what it returns. Catch
   ``FileAutomationException`` and show its text.
4. Call from a worker thread whatever touches storage or the network
   (``files.*``, ``integrity.verify``, ``notifications.send_test``,
   ``settings.apply``). ``pipelines.start`` and ``pipelines.resume`` already
   return at once.
5. For a pipeline editor, keep one ``PipelineDraft``, change it only through
   its methods, and redraw from it in a listener.

A complete, if small, terminal interface:

.. code-block:: python

   from automation_file.app import NAVIGATION, app_services
   from automation_file.exceptions import FileAutomationException

   services = app_services()
   views = {
       "Dashboard": lambda: services.dashboard.summary().to_dict(),
       "Storage": lambda: [backend.to_dict() for backend in services.storage.backends()],
       "Pipelines": lambda: services.pipelines.history(limit=10),
       "Scheduler": services.scheduler.jobs,
       "Integrity": lambda: [drift.to_dict() for drift in services.integrity.drift()],
       "Audit": services.audit.recent,
       "Notifications": services.notifications.routes,
       "Settings": lambda: [extra.to_dict() for extra in services.settings.extras()],
   }
   for number, name in enumerate(NAVIGATION, start=1):
       print(number, name)
   chosen = NAVIGATION[int(input("> ")) - 1]
   try:
       print(views.get(chosen, lambda: "use services.files for Files")())
   except FileAutomationException as error:
       print("failed:", error)

When something goes wrong
-------------------------

``AppException``
    The layer refused the request: an edit the draft cannot take, form text
    that is not JSON, a missing name. The message says what to change.

``PipelineDefinitionException`` from ``dry_run``, ``start`` or ``resume``
    The definition is not valid. ``error.problems`` holds every finding;
    ``validate`` returns the same as ``Problem`` objects without raising.

``status`` raises "unknown run"
    The run is neither tracked by this service nor in its run store. Runs are
    kept in memory unless a ``SQLiteRunStore`` is the default store or was
    passed to ``build_services``.

``cancel`` returns ``False``
    The run is not executing in this process: it has ended, or another process
    started it.

A backend is not ``usable``
    Read ``detail``. Initialise the client, or install the extra named by
    ``install_hint``.

``audit.search`` raises "audit is not configured"
    Call ``audit.configure(path)`` first. ``audit.recent()`` returns an empty
    list instead.

A secret shows up in a view
    It was stored under a name that does not say it is a secret, or it is part
    of a task's result. Rename the field, or keep it out of the result.

Two interfaces disagree
    They use different service sets. ``app_services()`` is shared;
    ``build_services()`` is not.
