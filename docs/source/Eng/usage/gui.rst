GUI (PySide6)
=============

The desktop window is organised by what you want to get done, not by backend:
a sidebar with nine workflow pages, and an **Advanced** entry that keeps the
tools addressing a single action or a single backend.

Every page is a thin view over one service of the application layer
(:doc:`app_layer`). The window holds no logic of its own, so what it shows is
what the Web UI (:doc:`servers`), the CLI and your own Python code see.

.. code-block:: bash

   pip install "automation_file[gui]"      # PySide6 is an extra, not a base dependency
   python -m automation_file ui
   # or from the repo root during development:
   python main_ui.py

.. code-block:: python

   from automation_file import launch_ui

   launch_ui()

Without PySide6, ``launch_ui`` raises ``OptionalDependencyException`` with the
``pip install`` command above.

Navigation
----------

.. list-table::
   :header-rows: 1
   :widths: 18 12 70

   * - Entry
     - Shortcut
     - What it is for
   * - Dashboard
     - ``Ctrl+1``
     - Health, running and recent pipeline runs, integrity drift, recent
       events and storage status at one glance.
   * - Files
     - ``Ctrl+2``
     - Browse a storage URI, preview a file, copy, move, delete, create a
       directory.
   * - Storage
     - ``Ctrl+3``
     - Which backends exist, whether each can be used, and the mounts.
   * - Pipelines
     - ``Ctrl+4``
     - The visual pipeline editor: build, validate, dry-run, test, run, resume.
   * - Scheduler
     - ``Ctrl+5``
     - Cron jobs: list, add, remove.
   * - Integrity
     - ``Ctrl+6``
     - Baseline, verify and accept a tree; start and stop monitors.
   * - Audit
     - ``Ctrl+7``
     - Point the audit trail at a database, search and count its records.
   * - Notifications
     - ``Ctrl+8``
     - Registered sinks, routes, and a test message.
   * - Settings
     - ``Ctrl+9``
     - The configuration file, the optional extras, the environment.
   * - Advanced
     - ``Ctrl+0``
     - Local, Transfer, Progress, JSON actions, Triggers and Servers: the tabs
       of the earlier window. See `Where the old tabs went`_.

The window
----------

The sidebar is on the left and the selected page on the right. Below both is
the **activity log**, shared by every page: each action writes a line when it
starts and another with its outcome, prefixed with the page name. The newest
line also appears in the status bar for a few seconds.

Every page has a **status line** at its bottom edge. It holds the outcome of
the last thing you did on that page: green when it worked, red when it did not.

Nothing blocks the window. A page hands every call to a thread pool
(``ActionWorker`` on ``QThreadPool``) and shows the result when it arrives. A
page reads its data when you open it and again when you press its **Refresh**
button. Two views refresh by themselves: the Dashboard every five seconds while
it is visible, and a followed pipeline run twice a second until it has ended.

The window shares the process-wide singletons with the rest of the library. A
sink registered from Python, a pipeline started through the HTTP action server
or a monitor started by a JSON action shows up after the next refresh.

Dashboard
---------

**All clear** or **Needs attention**, with the reasons next to it. The
dashboard asks for attention when one of the newest fifty runs failed, a
monitor found drift or could not verify, or the event bus holds a recent event
of severity ``error`` or worse.

* **Health**: registered actions, running runs, scheduled jobs, integrity
  monitors, notification sinks and routes, whether the router is active, and
  whether the audit trail is recording.
* **Pipeline runs**: how the newest runs ended, the runs still going, and the
  latest results with their error.
* **Integrity drift**: each named monitor, its target, and what it last found.
* **Storage status**: each backend and whether it can be used.
* **Recent events**: the twenty latest events of the bus, newest first.

**Refresh every 5 s** turns the timer off and on; **Refresh** reads at once.
The dashboard only reads: it starts nothing and changes nothing.

Files
-----

Type a storage URI or a local path (``s3://reports/2026``, ``local:///data``,
``C:\data``, ``memory://demo``) and press **Open**. **Up** goes to the parent,
**Browse local…** picks a directory. Double-click a directory to enter it and a
file to preview it.

A preview is bounded: at most 64 KiB is shown, and a file on a remote backend
that is larger than 16 MiB is not fetched at all (the status line says so).
Binary content is shown as a hexadecimal dump of its first 256 bytes.

The operations act on the selected entry:

* **Copy** / **Move** to the target URI, in the same backend or another one. An
  existing directory as the target receives the file under its own name. A
  directory is copied with everything below it; a directory cannot be moved
  (copy it, check the copy, delete the original).
* **Create directory** below the current location.
* **Delete selected** asks first. A directory with entries needs **Delete a
  directory with its contents**.

Every path goes through the storage layer (:doc:`storage`): ``..`` is refused,
credentials in a URI are refused, and a mounted directory cannot be left.

Storage
-------

One row per backend:

.. list-table::
   :header-rows: 1
   :widths: 14 86

   * - Kind
     - Meaning
   * - ``scheme``
     - A URI scheme with a factory: ``local``, ``memory``, ``s3``, ``azure``,
       ``gdrive``, ``dropbox``, ``onedrive``, ``sftp``, ``ftp``, ``ftps``.
   * - ``mount``
     - A backend mounted at a URI. Its name is that URI.
   * - ``client``
     - A shared client that has ``FA_*`` actions but no storage scheme (Box).

**Usable** is ``yes`` for the local and in-memory backends, for a mount, and
for a cloud backend whose client has been initialised. **Detail** says what is
missing: how to initialise the client, or, when the package of its extra is not
installed, the ``pip install`` command.

**Mount a local directory** serves a URI of your choice from a directory and
confines it to that directory (``sandbox://jobs`` on ``/srv/jobs``). Use it for
paths that come from outside the process. **Unmount selected** removes a mount.
Selecting a mount, ``local`` or ``memory`` shows what the backend provides
(directories, modification times, ETags ...).

Pipelines
---------

The page is an editor for a pipeline definition (:doc:`pipeline`) and a
console for its runs.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Area
     - What it holds
   * - Top row
     - **New**, **Open…**, **Save**, **Save as…**, **Auto layout**, and the file
       name (with ``(modified)`` while there are unsaved changes).
   * - Second row
     - The pipeline's name, **Max workers**, description, default parameters
       (JSON) and schedule (a cron expression, kept for the scheduler).
   * - Actions (left)
     - Every registered action, with a filter.
   * - Canvas (centre)
     - One node per task and one arrow per dependency, with **Connect**,
       **Disconnect** and **Remove selected** above it.
   * - Selected task (right)
     - The form of the task selected on the canvas.
   * - Run bar
     - The run parameters (JSON) and **Validate**, **Dry run**, **Test task**,
       **Run**, **Resume**, **Retry**, **Cancel**, **Refresh history**,
       **Follow selected run**.
   * - Tabs at the bottom
     - **Problems**, **Tasks**, **Log**, **History**.

The pipeline editor step by step
--------------------------------

1. **Start.** Press **New** for an empty definition or **Open…** for a
   ``.yaml`` / ``.yml`` / ``.json`` file. A file that is not a valid definition
   still opens: whatever has the right shape is shown, and the **Problems** tab
   lists what is wrong with it.

2. **Name it.** Fill in the name, the number of workers and, if you like, the
   description, the default parameters as a JSON object and the schedule.

3. **Add tasks.** Drag an action from the **Actions** list onto the canvas: the
   task appears where you drop it. Double-clicking an action, or selecting it
   and pressing **Add task**, adds it below the lowest task. The filter narrows
   the list (``storage`` shows the ``FA_storage_*`` actions). The task's ID is
   derived from the action name; change it in the form.

4. **Arrange.** Drag the nodes where you want them. **Auto layout** puts each
   task in a column by its dependency depth. Positions are editor metadata:
   they are saved next to the definition, never in it.

5. **Connect.** Click the upstream task, ``Ctrl``-click the task that depends
   on it, and press **Connect**. The button shows the direction it will use
   (``Connect download -> publish``): the order in which you selected the two
   tasks is the direction of the arrow. An arrow that would close a dependency
   cycle is refused. You can also tick the upstream task under **Depends on**
   in the task form.

   To remove a dependency, click its arrow (or select its two tasks) and press
   **Disconnect**. **Remove selected** removes the selected arrows, or, when no
   arrow is selected, the selected tasks with their arrows.

6. **Edit the selected task.** The form shows the task selected last:

   .. list-table::
      :header-rows: 1
      :widths: 24 76

      * - Field
        - Meaning
      * - Task ID
        - Unique in the pipeline. Renaming keeps the arrows and rewrites the
          ``${tasks.<id>.result}`` placeholders that point at the task.
      * - Action
        - A registered action. Its signature and summary appear below it.
      * - Arguments
        - One row per parameter of the action, with its default. A value is
          JSON when it parses as JSON (``12``, ``true``, ``["a", "b"]``,
          ``"12"``) and text otherwise, so a URI or ``${params.date}`` needs no
          quotes. A row left empty is not passed, so the default applies.
          **Add argument** adds a row for an action that takes ``**kwargs``.
          **Edit as JSON** shows the arguments as one JSON document; positional
          arguments (a JSON array) can only be edited that way.
      * - Depends on
        - Tick the tasks that must end first.
      * - Attempts, Back-off, Back-off cap, Retry on
        - Attempts in total, the first back-off and its cap, and the exception
          names worth another attempt (empty: the transient ones).
      * - Timeout
        - Seconds for the whole task; empty for no limit.
      * - Run when
        - ``on_success``, ``on_failure`` or ``always``.
      * - Idempotency key
        - Text with ``${params.<name>}`` placeholders; empty for none.

   Nothing changes until you press **Apply changes**. **Revert** throws away
   what you typed, and so does selecting another task. When the draft refuses a
   value, the form says why and keeps what you typed.

7. **Validate.** The **Problems** tab lists every finding with the path of the
   entry it is about (``tasks.publish.depends_on[0]: unknown task 'x'``),
   including an action name the registry does not know. Click a problem to
   select its task. **Dry run**, **Test task**, **Run**, **Resume** and
   **Retry** validate first and stop when there is a problem.

8. **Dry run.** Enter the run parameters as a JSON object and press
   **Dry run**. Nothing is executed or recorded. The **Tasks** tab shows every
   task as ``planned`` with its level, and a task that would not run as planned
   says why (a parameter the run was not given, for instance).

9. **Test one task.** Select a task and press **Test task**. Its action really
   runs, with its retry policy and its timeout. Its upstream tasks do not: each
   is replaced by a stand-in that returns nothing, so a
   ``${tasks.<id>.result}`` placeholder receives ``null``. A test is recorded in
   no run store and published on no shared event bus.

10. **Run.** **Run** starts the pipeline in the background and follows it: the
    **Tasks** tab shows status, attempts, duration and error of every task, the
    **Log** tab the events of the run, and each node takes the colour of its
    status (grey pending, blue running, green succeeded, red failed or timed
    out, orange cancelled, yellow skipped). **Cancel** asks the run to stop.

11. **Resume or retry.** After a failure, fix the cause. **Resume** continues
    the same run: tasks that succeeded are kept, the rest run again, with the
    same run ID and parameters. **Retry** starts a new run with the parameters
    of the followed one.

12. **Look back.** The **History** tab lists the recorded runs, newest first.
    Double-click one, or select it and press **Follow selected run**, to see
    its tasks and events again; **Resume** and **Retry** then act on it.

13. **Save.** **Save as…** writes the definition as ``.yaml``, ``.yml`` or
    ``.json``, and the canvas layout into ``<file>.layout.json`` next to it. The
    definition file is exactly what ``Pipeline.from_file`` and
    ``FA_pipeline_run`` take.

Scheduler
---------

**Schedule a job** takes a unique name, a five-field cron expression and the
action list as JSON, and **Add job** registers it. Tick the checkbox to let a
run start while the previous one is still going; otherwise that tick is skipped
and counted under **Skipped**. The table shows every job with its runs and its
last run; **Remove selected** and **Remove all** remove jobs. To run a pipeline
on a schedule, schedule ``FA_pipeline_run`` with the path of its definition.

The jobs are removed when the window closes.

Integrity
---------

Enter the **Target** (the tree to check) and the **Baseline** (where the
approved state is kept), both storage URIs or local paths.

* **Create baseline** approves what is there now.
* **Verify** compares the tree with the baseline and lists every change with
  its kind and path. With **Deep** off, only files whose size or time changed
  are hashed, and the summary says it was a quick pass.
* **Accept current state** asks first, then stores the current tree as the new
  baseline.

Under **Monitors**, give a name and an interval and press **Start monitor** to
verify the target on a thread; the table shows what each monitor last found.
Monitors started from the window stop when it closes. See :doc:`integrity`.

Audit
-----

The audit trail records nothing until it has a store. Enter the path of a
SQLite database (it is created when missing) and press **Configure**; **State**
then says where the records go.

Fill in any of the filters and press **Search** (newest first, up to
**Limit**) or **Count**. A filter left empty does not restrict the search.
**Since** and **Until** take an ISO 8601 time with an offset. Select a record
to see all of it, as JSON. See :doc:`audit`.

Notifications
-------------

**Sinks** lists the registered sinks by name, type and destination. Sinks are
registered in code or from the configuration file (Settings); this page does
not create them. Choose a sink (or **All sinks**), optionally a subject, and
press **Send test message**; the status line shows one outcome per sink.

**Routes** lists which events reach which sinks. **Add or replace a route**
takes a name, sink names, event types (``pipeline.*``, ``task.failed``),
sources, the minimum severity, and the throttling values; lists are separated
by commas. A route that names a sink that is not registered is refused. The
router starts with the first route and stops when the last one is removed. See
:doc:`notifications`.

Settings
--------

Enter the path of ``automation_file.toml`` (:doc:`config`).

* **Preview** reads the file and shows its summary. Nothing changes.
* **Apply** registers its notification sinks and routes.

**Optional extras** lists every extra with what it enables, whether it is
installed, and the ``pip install`` command when it is not. **Environment**
shows the package and Python versions, the platform, the log file and the
configuration applied last.

Where the old tabs went
-----------------------

Nothing was removed. The **Advanced** entry holds the earlier tabs, unchanged:

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Earlier tab
     - Now
   * - Home
     - **Dashboard** (backend readiness is under *Storage status*, and on the
       **Storage** page).
   * - Local
     - **Advanced** → *Local*. Browsing and copying are also on **Files**.
   * - Transfer (HTTP, Google Drive, S3, Azure Blob, Dropbox, SFTP, OneDrive,
       Box)
     - **Advanced** → *Transfer*. This is where a cloud client is given its
       credentials.
   * - Progress
     - **Advanced** → *Progress*.
   * - JSON actions
     - **Advanced** → *JSON actions*.
   * - Triggers
     - **Advanced** → *Triggers*.
   * - Scheduler
     - **Scheduler**.
   * - Servers
     - **Advanced** → *Servers*.

Secrets
-------

No page shows a secret. Sinks are described by name, type and destination; a
configuration summary has its passwords and tokens replaced by ``********`` and
its webhook URLs reduced to the host; events, audit records and run parameters
are masked the same way before they are displayed; credentials inside a URL and
bearer tokens are removed from the messages a page shows.

A value is masked when the *name* it is stored under says it is a secret
(``password``, ``token``, ``api_key``, ``authorization`` ...). A task's result
is shown as the task returned it. So give a secret parameter such a name, and
keep secrets out of results.

Running without a display
-------------------------

Qt needs a display to open a window. On a server without one:

* Use the Web UI (:doc:`servers`) for the read-only views; it is rendered from
  the same application layer.
* Use the application layer itself from Python (:doc:`app_layer`), or the
  ``FA_*`` actions through the CLI and the action servers. Everything the
  window does is a call to one of them.
* To construct the window without showing it (tests, screenshots in CI), set
  ``QT_QPA_PLATFORM=offscreen`` before Qt is imported:

  .. code-block:: python

     import os
     os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

     from PySide6.QtWidgets import QApplication
     from automation_file.app import build_services
     from automation_file.ui.main_window import MainWindow

     app = QApplication([])
     window = MainWindow(build_services())     # or MainWindow() for the shared services
     window.navigate("Pipelines")
     window.close()

``import automation_file`` and ``import automation_file.app`` never import
PySide6; only ``automation_file.ui`` does.

When something goes wrong
-------------------------

A button seems to do nothing
    Read the status line at the bottom of the page and the activity log. Every
    refusal and every failure is reported there, with the reason.

``launch_ui`` raises ``OptionalDependencyException``
    PySide6 is not installed: ``pip install "automation_file[gui]"``.

The window does not open: "could not load the Qt platform plugin"
    There is no display. See `Running without a display`_.

A cloud backend is "not initialised"
    Its shared client has no credentials yet. Open **Advanced** → *Transfer*,
    choose the backend and fill in *Credentials*, or run its
    ``FA_*_later_init`` action.

Detail says a package "is not installed"
    Install the extra the row names; **Settings** lists every extra with its
    command.

**Connect** is refused
    The arrow would close a dependency cycle, or fewer or more than two tasks
    are selected.

**Run** stops at "problem(s): see the Problems tab"
    The definition is not valid. Each problem starts with the path of the entry
    it is about; click it to select the task.

A run stays ``running`` after **Cancel**
    A running action cannot be interrupted. Tasks that had not started are
    cancelled at once; the run ends when the running ones return.

**Resume** is refused
    The run is still executing, belongs to a pipeline with another name, or the
    definition now needs a parameter the stored run does not have.

The history is empty after a restart
    Runs are kept in memory by default. Call
    ``set_default_run_store(SQLiteRunStore(path))`` before ``launch_ui()`` to
    keep them in a file.

**Search** says audit is not configured
    Give the audit trail a database first, on the same page.

A test message fails
    The status line shows the error of each sink, with URLs reduced to their
    host. The sink itself is described in :doc:`notifications`.

The page shows old data
    Press **Refresh**. Only the Dashboard and a followed run refresh by
    themselves.

Something kept running after the window closed
    Closing the window removes the scheduled jobs, stops the monitors, action
    servers and triggers it started, and leaves pipeline runs alone: a run
    that was started goes on to its end, and the process does not exit before.
