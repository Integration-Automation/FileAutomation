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
   │   ├── callback_executor.py
   │   ├── package_loader.py
   │   ├── json_store.py
   │   ├── retry.py             # @retry_on_transient
   │   └── quota.py             # Quota(max_bytes, max_seconds)
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
   ├── project/
   │   ├── project_builder.py
   │   └── templates.py
   ├── ui/                      # PySide6 GUI
   │   ├── launcher.py          # launch_ui(argv)
   │   ├── main_window.py       # 9-tab MainWindow
   │   ├── worker.py            # ActionWorker (QRunnable)
   │   ├── log_widget.py        # LogPanel
   │   └── tabs/                # one tab per backend + JSON runner + servers
   └── utils/
       └── file_discovery.py

Execution modes
---------------

The shared executor supports four orthogonal modes:

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

Reliability utilities
---------------------

* :func:`automation_file.core.retry.retry_on_transient` — decorator that
  retries ``ConnectionError`` / ``TimeoutError`` / ``OSError`` with capped
  exponential back-off. Used by :func:`automation_file.download_file`.
* :class:`automation_file.core.quota.Quota` — dataclass bundling an optional
  ``max_bytes`` size cap and an optional ``max_seconds`` time budget.

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
