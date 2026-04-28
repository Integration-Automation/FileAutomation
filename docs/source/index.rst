automation_file
===============

Languages: **English** | `繁體中文 <../html-zh-TW/index.html>`_ | `简体中文 <../html-zh-CN/index.html>`_

A modular automation framework for local file / directory / ZIP operations,
SSRF-validated HTTP downloads, remote storage (Google Drive, S3, Azure Blob,
Dropbox, SFTP, FTP, WebDAV, SMB, fsspec), and JSON-driven action execution
over embedded TCP / HTTP servers. Ships with a PySide6 GUI that exposes every
feature through tabs. All public functionality is re-exported from the
top-level ``automation_file`` facade.

Highlights
----------

**Core primitives**

* JSON action lists executed by a shared
  :class:`~automation_file.core.action_executor.ActionExecutor` — validate,
  dry-run, parallel, DAG.
* Path traversal guard (:func:`~automation_file.local.safe_paths.safe_join`),
  SSRF validator for outbound URLs, loopback-first TCP / HTTP servers with
  optional shared-secret auth and per-action ACLs.
* Reliability helpers: ``retry_on_transient`` decorator, ``Quota`` size and
  time budgets, streaming checksums, resumable HTTP downloads.

**Backends**

* Local file / directory / ZIP / tar operations.
* HTTP downloads with SSRF protection, size / timeout caps, retries,
  resumable transfers, and optional SHA-256 verification.
* First-class Google Drive, S3, Azure Blob, Dropbox, SFTP, FTP / FTPS,
  WebDAV, SMB / CIFS, and fsspec backends — all auto-registered.
* Cross-backend copy through URI syntax (``local://``, ``s3://``,
  ``drive://``, ``sftp://``, ``azure://``, ``dropbox://``, ``ftp://``, …).

**Event-driven execution**

* File-watcher triggers via ``FA_watch_*`` — run action lists on path
  changes.
* Cron scheduler (``FA_schedule_*``) on a stdlib-only 5-field parser, with
  overlap guard and auto-notify on failure.
* Transfer progress + cancellation tokens exposed through ``progress_name``.

**Observability + integrations**

* Notification sinks — webhook / Slack / SMTP / Telegram / Discord / Teams /
  PagerDuty with per-sink error isolation and sliding-window dedup.
* Prometheus metrics exporter (``start_metrics_server``), SQLite audit log,
  file integrity monitor.
* HTMX web UI (``start_web_ui``), MCP server bridging the registry to Claude
  Desktop / MCP CLIs over JSON-RPC 2.0.
* PySide6 desktop GUI (``python -m automation_file ui``).

**Supply chain**

* Config + secrets — declare sinks and defaults in ``automation_file.toml``;
  ``${env:…}`` / ``${file:…}`` references resolve through Env / File /
  Chained providers so secrets stay out of the file.
* Entry-point plugins — third-party packages register their own ``FA_*``
  actions via ``[project.entry-points."automation_file.actions"]``.

Architecture at a glance
------------------------

.. code-block:: text

   User / CLI / JSON batch
          │
          ▼
   ┌─────────────────────────────────────────┐
   │  automation_file (facade)               │
   │  execute_action, driver_instance,       │
   │  start_autocontrol_socket_server,       │
   │  start_http_action_server, Quota, …     │
   └─────────────────────────────────────────┘
          │
          ▼
   ┌──────────────┐     ┌────────────────────┐
   │  core        │────▶│ ActionRegistry     │
   │  executor,   │     │ (FA_* commands)    │
   │  retry,      │     └────────────────────┘
   │  quota,      │              │
   │  progress    │              ▼
   └──────────────┘     ┌────────────────────┐
                        │ local / remote /   │
                        │ server / triggers /│
                        │ scheduler / ui     │
                        └────────────────────┘

See :doc:`architecture` for the full module tree and design patterns.

Installation
------------

.. code-block:: bash

   pip install automation_file

All backends (S3, Azure Blob, Dropbox, SFTP, PySide6) are first-class
runtime dependencies — no extras required for common use.

Quick start
-----------

Run a JSON action list from the CLI:

.. code-block:: bash

   python -m automation_file --execute_file my_actions.json

Drive the library from Python:

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_create_dir", {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
       ["FA_zip_dir", {"source": "build", "target": "build.zip"}],
   ])

Validate a batch before running it, or run actions in parallel:

.. code-block:: python

   from automation_file import executor

   problems = executor.validate(actions)
   if problems:
       raise SystemExit("\n".join(problems))
   executor.execute_action_parallel(actions, max_workers=4)

Start the PySide6 GUI:

.. code-block:: bash

   python -m automation_file ui

Expose the registry over a loopback HTTP server with shared-secret auth:

.. code-block:: python

   from automation_file import start_http_action_server

   server = start_http_action_server(port=8765, shared_secret="s3kret")

Action-list shape
-----------------

An action is a list of one of three shapes, dispatched by name through the
registry:

.. code-block:: python

   ["FA_create_dir"]                                  # no-args
   ["FA_create_dir", {"dir_path": "build"}]           # keyword args
   ["FA_copy_file", ["src.txt", "dst.txt"]]           # positional args

A JSON action list is simply a list of these lists.

.. toctree::
   :maxdepth: 2
   :caption: Architecture

   architecture

.. toctree::
   :maxdepth: 3
   :caption: Usage guide

   usage/index

.. toctree::
   :maxdepth: 2
   :caption: API reference

   api/index

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
