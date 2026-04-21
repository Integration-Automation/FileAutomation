Architecture
============

``automation_file`` follows a layered architecture built around five design
patterns:

**Facade**
   :mod:`automation_file` (the top-level ``__init__``) is the only name users
   should need to import. Every public function and singleton is re-exported
   from there.

**Registry + Command**
   :class:`~automation_file.core.action_registry.ActionRegistry` maps an action
   name (a string that appears in a JSON action list) to a Python callable.
   An action is a Command object of shape ``[name]``, ``[name, {kwargs}]``, or
   ``[name, [args]]``.

**Template Method**
   :class:`~automation_file.core.action_executor.ActionExecutor` defines the
   single-action lifecycle: resolve the name, dispatch the call, capture the
   return value or exception. The outer iteration template guarantees that one
   bad action never aborts the batch unless ``validate_first=True`` is set.

**Strategy**
   Each ``local/*_ops.py``, ``remote/*_ops.py``, and cloud subpackage is a
   collection of independent strategy functions. Every backend — local, HTTP,
   Google Drive, S3, Azure Blob, Dropbox, SFTP — is auto-registered by
   :func:`automation_file.core.action_registry.build_default_registry`. The
   ``register_<backend>_ops(registry)`` helpers stay exported for callers that
   assemble custom registries.

**Singleton (module-level)**
   ``executor``, ``callback_executor``, ``package_manager``, ``driver_instance``,
   ``s3_instance``, ``azure_blob_instance``, ``dropbox_instance``, and
   ``sftp_instance`` are shared instances wired in ``__init__`` so plugins
   pick up the same state as the CLI.

Module layout
-------------

.. code-block:: text

   automation_file/
   ├── __init__.py           # Facade — every public name
   ├── __main__.py           # CLI with subcommands
   ├── exceptions.py         # FileAutomationException hierarchy
   ├── logging_config.py     # file_automation_logger
   ├── core/
   │   ├── action_registry.py
   │   ├── action_executor.py   # serial, parallel, dry-run, validate-first
   │   ├── dag_executor.py      # topological scheduler with parallel fan-out
   │   ├── callback_executor.py
   │   ├── package_loader.py
   │   ├── plugins.py           # entry-point plugin discovery
   │   ├── json_store.py
   │   ├── retry.py             # @retry_on_transient
   │   ├── quota.py             # Quota(max_bytes, max_seconds)
   │   ├── checksum.py          # file_checksum, verify_checksum
   │   └── progress.py          # CancellationToken, ProgressReporter, progress_registry
   ├── local/
   │   ├── file_ops.py
   │   ├── dir_ops.py
   │   ├── zip_ops.py
   │   └── safe_paths.py        # safe_join + is_within
   ├── remote/
   │   ├── url_validator.py     # SSRF guard
   │   ├── http_download.py     # retried HTTP download
   │   ├── google_drive/
   │   ├── s3/                  # auto-registered in build_default_registry()
   │   ├── azure_blob/          # auto-registered in build_default_registry()
   │   ├── dropbox_api/         # auto-registered in build_default_registry()
   │   └── sftp/                # auto-registered in build_default_registry()
   ├── server/
   │   ├── tcp_server.py        # loopback-only, optional shared-secret
   │   └── http_server.py       # POST /actions, Bearer auth
   ├── trigger/
   │   └── manager.py           # FileWatcher + TriggerManager (watchdog-backed)
   ├── scheduler/
   │   ├── cron.py              # 5-field cron expression parser
   │   └── manager.py           # Scheduler background thread + ScheduledJob
   ├── project/
   │   ├── project_builder.py
   │   └── templates.py
   ├── ui/                      # PySide6 GUI
   │   ├── launcher.py          # launch_ui(argv)
   │   ├── main_window.py       # tabbed MainWindow (Home, Local, Transfer,
   │   │                        #   Progress, JSON actions, Triggers,
   │   │                        #   Scheduler, Servers)
   │   ├── worker.py            # ActionWorker (QRunnable)
   │   ├── log_widget.py        # LogPanel
   │   └── tabs/                # one tab per backend + JSON runner + servers
   └── utils/
       ├── file_discovery.py
       ├── fast_find.py         # OS-index (mdfind/locate/es) + scandir fallback
       └── deduplicate.py       # size → partial-hash → full-hash dedup pipeline

Execution modes
---------------

The shared executor supports five orthogonal modes:

* ``execute_action(actions)`` — default serial execution; each failure is
  captured and reported without aborting the batch.
* ``execute_action(actions, validate_first=True)`` — resolve every name
  against the registry before running anything. A typo aborts the batch
  up-front instead of after half the actions have already run.
* ``execute_action(actions, dry_run=True)`` — parse each action and log what
  would be called without invoking the underlying function.
* ``execute_action_parallel(actions, max_workers=4)`` — dispatch actions
  concurrently through a thread pool. The caller is responsible for ensuring
  the chosen actions are independent.
* ``execute_action_dag(nodes, max_workers=4, fail_fast=True)`` — Kahn-style
  topological scheduling. Each node is ``{"id": str, "action": [...],
  "depends_on": [id, ...]}``. Independent branches run in parallel, failed
  branches mark their transitive dependents ``skipped`` (or still run them
  under ``fail_fast=False``). Cycles / unknown deps / duplicate ids are
  rejected before any node runs.

Reliability utilities
---------------------

* :func:`automation_file.core.retry.retry_on_transient` — decorator that
  retries ``ConnectionError`` / ``TimeoutError`` / ``OSError`` with capped
  exponential back-off. Used by :func:`automation_file.download_file`.
* :class:`automation_file.core.quota.Quota` — dataclass bundling an optional
  ``max_bytes`` size cap and an optional ``max_seconds`` time budget.
* :func:`automation_file.core.checksum.file_checksum` and
  :func:`automation_file.core.checksum.verify_checksum` — streaming file
  hashing (any :mod:`hashlib` algorithm) with constant-time digest comparison.
  :func:`automation_file.download_file` accepts ``expected_sha256=`` to
  verify the target immediately after the HTTP transfer completes.
* Resumable downloads: :func:`automation_file.download_file` accepts
  ``resume=True``, which writes to ``<target>.part`` and sends
  ``Range: bytes=<n>-`` so interrupted transfers continue from the existing
  byte count instead of restarting from zero.
* :func:`automation_file.utils.deduplicate.find_duplicates` — three-stage
  size → partial-hash → full-hash pipeline; most files never get hashed
  because unique-size buckets are discarded before any digest is read.
* :class:`automation_file.core.progress.CancellationToken` and
  :class:`automation_file.core.progress.ProgressReporter` — opt-in per-transfer
  instrumentation. HTTP download and S3 upload/download accept a
  ``progress_name=`` kwarg that wires both primitives into the transfer loop;
  JSON actions ``FA_progress_list`` / ``FA_progress_cancel`` /
  ``FA_progress_clear`` address the central registry.

Event-driven dispatch
---------------------

Two long-running subsystems reuse the shared executor instead of forking
their own dispatch paths:

* :mod:`automation_file.trigger` wraps ``watchdog`` observers. Each
  :class:`~automation_file.trigger.FileWatcher` forwards matching filesystem
  events to an action list dispatched through the shared registry.
  :data:`~automation_file.trigger.trigger_manager` owns the name → watcher
  map so the GUI and JSON actions share one lifecycle.
* :mod:`automation_file.scheduler` runs one background thread that wakes on
  minute boundaries, iterates registered
  :class:`~automation_file.scheduler.ScheduledJob` instances, and dispatches
  every matching job on a short-lived worker thread so a slow action can't
  starve subsequent jobs.

Security boundaries
-------------------

* **SSRF guard**: every outbound HTTP URL passes through
  :func:`automation_file.remote.url_validator.validate_http_url`.
* **Path traversal**:
  :func:`automation_file.local.safe_paths.safe_join` resolves user paths under
  a caller-specified root and rejects ``..`` escapes, absolute paths outside
  the root, and symlinks pointing out of it.
* **TCP / HTTP auth**: both servers accept an optional ``shared_secret``.
  When set, the TCP server requires ``AUTH <secret>\\n`` before the payload
  and the HTTP server requires ``Authorization: Bearer <secret>``. Both bind
  to loopback by default and refuse non-loopback binds unless
  ``allow_non_loopback=True`` is passed.
* **SFTP host verification**: the SFTP client uses
  :class:`paramiko.RejectPolicy` and never auto-adds unknown host keys.
* **Plugin loading**: :class:`automation_file.core.package_loader.PackageLoader`
  registers arbitrary module members; never expose it to untrusted input.
  The entry-point discovery path
  (:func:`automation_file.core.plugins.load_entry_point_plugins`) is safer —
  only packages the user has explicitly installed can contribute commands —
  but every plugin still runs with full library privileges, so review
  third-party plugins before installing them.

Entry-point plugins
-------------------

Third-party packages can ship extra actions without ``automation_file``
having to import them. A plugin advertises itself in its
``pyproject.toml``::

   [project.entry-points."automation_file.actions"]
   my_plugin = "my_plugin:register"

where ``register`` is a zero-argument callable returning a
``Mapping[str, Callable]`` — the same shape you would hand to
:func:`automation_file.add_command_to_executor`.
:func:`automation_file.core.action_registry.build_default_registry`
invokes :func:`automation_file.core.plugins.load_entry_point_plugins` after
the built-ins are wired in, so installed plugins populate every
freshly-built registry automatically. Plugin failures (import errors,
factory exceptions, bad return shape, registry rejection) are logged and
swallowed so one broken plugin does not break the library.

Shared singletons
-----------------

``automation_file/__init__.py`` creates the following process-wide singletons:

* ``executor`` — :class:`ActionExecutor` used by :func:`execute_action`.
* ``callback_executor`` — :class:`CallbackExecutor` bound to ``executor.registry``.
* ``package_manager`` — :class:`PackageLoader` bound to the same registry.
* ``driver_instance``, ``s3_instance``, ``azure_blob_instance``,
  ``dropbox_instance``, ``sftp_instance`` — lazy clients for each cloud
  backend.

All executors share one :class:`ActionRegistry` instance, so calling
:func:`add_command_to_executor` (or any ``register_*_ops`` helper) makes the
new command visible to every dispatcher at once.
