###############
automation_file
###############

**A modular, JSON-driven file-automation framework for Python.**

``automation_file`` packages local file / directory / ZIP / tar operations,
SSRF-validated and resumable HTTP downloads, eleven remote storage backends
(Google Drive, S3, Azure Blob, Dropbox, OneDrive, Box, SFTP, FTP / FTPS,
WebDAV, SMB, fsspec), JSON-driven action execution over embedded TCP / HTTP /
MCP servers, a cron-style scheduler, file-watcher triggers, notification
fanout, an audit log, AES-256-GCM file encryption, Prometheus metrics, and a
PySide6 desktop GUI — all dispatched through one shared ``ActionRegistry``
and exposed from a single ``automation_file`` facade.

* **PyPI** — https://pypi.org/project/automation_file/
* **GitHub** — https://github.com/Integration-Automation/FileAutomation
* **Issues / RoadMap** — https://github.com/Integration-Automation/FileAutomation/issues
* **License** — MIT

Languages: **English** | `繁體中文 <https://fileautomation.readthedocs.io/zh_TW/latest/>`_ | `简体中文 <https://fileautomation.readthedocs.io/zh_CN/latest/>`_

.. note::

   Each language is served as its own Read the Docs project, linked as a
   translation of ``fileautomation``. RTD also exposes a built-in language
   selector inside the version flyout in the bottom-right of every page.

.. contents:: On this page
   :local:
   :depth: 1

----

Install
=======

.. code-block:: bash

   pip install automation_file

Every backend (Google Drive, S3, Azure Blob, Dropbox, OneDrive, Box, SFTP,
FTP, WebDAV, SMB, fsspec) and the PySide6 GUI are first-class runtime
dependencies — no optional extras to remember.

First action
============

An action is one of three JSON shapes — ``[name]``, ``[name, {kwargs}]``, or
``[name, [args]]``. An action list is an array of actions. The shared
executor runs them in order and returns a per-action result map.

.. code-block:: python

   from automation_file import execute_action

   results = execute_action([
       ["FA_create_dir",  {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
       ["FA_zip_dir",     {"dir_we_want_to_zip": "build", "zip_name": "build_snapshot"}],
   ])

The same list runs from the CLI (``python -m automation_file run actions.json``),
over a loopback TCP / HTTP server, through an MCP host, or from the GUI's
**JSON actions** tab — no rewrite needed. See :doc:`usage/quickstart` for
validation, dry-run, and parallel execution; :doc:`usage/cli` for the
argparse dispatcher; :doc:`architecture` for how the registry and executor
fit together.

----

What it gives you
=================

**Local operations** (:doc:`usage/local`)
   File / directory / ZIP / tar / archive ops, ``safe_join`` path-traversal
   guard, OS-index-aware ``fast_find``, streaming ``file_checksum`` and
   ``find_duplicates``, ``sync_dir`` rsync-style mirror, directory diffs,
   text patches, JSON / YAML / CSV / JSONL / Parquet edits, MIME detection,
   templates, trash send / restore, file versioning, conditional execution
   (``FA_if_exists`` / ``FA_if_newer`` / ``FA_if_size_gt``), variable
   substitution (``${env:…}`` / ``${date:%Y-%m-%d}`` / ``${uuid}``), shell
   subprocess with timeout, and AES-256-GCM file encryption.

**HTTP transfers** (:doc:`usage/transfer`)
   ``download_file`` validates every URL through ``validate_http_url``
   (rejects ``file://`` / ``ftp://`` / private / loopback / link-local /
   reserved targets), enforces size and timeout caps, supports resumable
   ``Range:`` downloads to ``<target>.part``, verifies an
   ``expected_sha256`` after transfer, and integrates with the progress
   registry for live transfer snapshots and cooperative cancellation.

**Cloud and remote storage** (:doc:`usage/cloud`)
   Google Drive (OAuth2), S3 (boto3), Azure Blob, Dropbox, OneDrive, Box,
   SFTP (paramiko + ``RejectPolicy``), FTP / FTPS, WebDAV, SMB / CIFS, and a
   fsspec bridge — all auto-registered by ``build_default_registry()`` and
   reachable from one shared singleton each. ``copy_between`` moves data
   between any two backends via URI prefixes.

**Action servers** (:doc:`usage/servers`)
   Loopback-only TCP and HTTP servers that accept JSON action lists, with
   optional shared-secret authentication, server-side ``ActionACL`` allow
   lists, ``GET /healthz`` / ``GET /readyz`` probes, ``GET /openapi.json``,
   a ``GET /progress`` WebSocket, and a typed ``HTTPActionClient`` SDK.

**MCP server** (:doc:`usage/mcp`)
   ``MCPServer`` bridges the registry to any Model Context Protocol host
   (Claude Desktop, Claude Code, MCP CLIs) over newline-delimited JSON-RPC
   2.0 on stdio. Every ``FA_*`` action becomes an MCP tool with an
   auto-generated input schema.

**Desktop GUI** (:doc:`usage/gui`)
   A PySide6 tabbed control surface — Home, Local, Transfer, Progress, JSON
   actions, Triggers, Scheduler, Servers, plus one tab per cloud backend —
   sharing the same singletons and dispatching through ``ActionWorker`` on
   the global thread pool.

**Reliability** (:doc:`usage/reliability`)
   ``retry_on_transient`` with capped exponential back-off, ``Quota`` size
   and time budgets, ``CircuitBreaker``, ``RateLimiter``, ``FileLock`` /
   ``SQLiteLock``, persistent ``ActionQueue``, SQLite ``AuditLog``,
   ``IntegrityMonitor`` for periodic manifest verification, and a typed
   ``FileAutomationException`` hierarchy.

**Triggers and scheduler** (:doc:`usage/events`)
   File-watcher triggers (``FA_watch_*``) run an action list on a
   filesystem event; the cron-style scheduler (``FA_schedule_*``) runs an
   action list on a recurring schedule with overlap protection — both fall
   back to notifications on failure.

**Notifications** (:doc:`usage/notifications`)
   Slack, Email (SMTP), Discord, Telegram, Microsoft Teams, PagerDuty, and
   generic webhook sinks composed by a ``NotificationManager`` with
   per-sink error isolation and sliding-window dedup.

**Configuration and secrets** (:doc:`usage/config`)
   Declare sinks and defaults in ``automation_file.toml``; ``${env:…}`` /
   ``${file:…}`` references are resolved through chained ``EnvSecretProvider``
   / ``FileSecretProvider``; ``ConfigWatcher`` polls and hot-reloads the
   file without restart.

**DAG action executor** (:doc:`usage/dag`)
   Run action lists as a DAG with declared dependencies, topological
   parallel fan-out, and per-branch skip-on-failure.

**Observability**
   ``start_metrics_server()`` exposes Prometheus counters and histograms
   for every action; ``start_web_ui()`` serves a stdlib-only HTMX dashboard
   for health, progress, and the registry.

**Plugins** (:doc:`usage/plugins`)
   Third-party packages register their own ``FA_*`` actions through
   ``[project.entry-points."automation_file.actions"]``; ``PackageLoader``
   imports a Python package and registers its top-level members as
   ``<package>_<member>``.

----

Reading order
=============

The docs are split by language and by content type. The manual follows a
typical reader journey — install, drive locally, reach remote storage,
expose servers, automate at scale — then dives into reliability,
configuration, and composition. The API reference is the auto-generated
Python reference for every public module.

.. toctree::
   :maxdepth: 1
   :caption: Get started

   usage/quickstart
   usage/cli
   architecture

.. toctree::
   :maxdepth: 1
   :caption: File and storage operations

   usage/local
   usage/transfer
   usage/cloud

.. toctree::
   :maxdepth: 1
   :caption: Servers and surfaces

   usage/servers
   usage/mcp
   usage/gui

.. toctree::
   :maxdepth: 1
   :caption: Run-time controls

   usage/reliability
   usage/events
   usage/notifications
   usage/config

.. toctree::
   :maxdepth: 1
   :caption: Composition and extensions

   usage/dag
   usage/plugins

.. toctree::
   :maxdepth: 1
   :caption: API reference

   api/core
   api/local
   api/remote
   api/server
   api/client
   api/trigger
   api/scheduler
   api/notify
   api/progress
   api/project
   api/ui
   api/utils

----

Indices
=======

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
