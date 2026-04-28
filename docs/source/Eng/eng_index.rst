================================
automation_file English Manual
================================

The English manual is split into chapters that follow a typical reader
journey: install → run JSON actions → drive locally → reach remote storage
→ expose servers → automate at scale. Use the table of contents on the
left, or jump straight to a chapter below.

.. contents:: On this page
   :local:
   :depth: 1

----

.. _eng-getting-started:

Chapter 1 — Getting Started
===========================

Install ``automation_file``, run your first JSON action list, and
understand the registry-and-executor split.

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   usage/quickstart

.. _eng-cli:

Chapter 2 — CLI
===============

Drive the framework from the ``python -m automation_file`` argparse
dispatcher — subcommands, legacy flags, and JSON file execution.

.. toctree::
   :maxdepth: 2
   :caption: CLI

   usage/cli

.. _eng-architecture:

Chapter 3 — Architecture
========================

The layered architecture, design patterns (Facade, Registry, Command,
Strategy, Template Method, Singleton, Builder), and how the executor talks
to the registry.

.. toctree::
   :maxdepth: 2
   :caption: Architecture

   architecture

.. _eng-local:

Chapter 4 — Local Operations
============================

File, directory, ZIP, tar, and archive operations exposed by the ``local/``
strategy modules; the ``safe_join`` path-traversal guard; OS-index-aware
``fast_find``; streaming ``file_checksum`` and ``find_duplicates``;
``sync_dir`` rsync-style mirror; directory diffs and text patches; JSON /
YAML / CSV / JSONL / Parquet edits; MIME detection; templates; trash send /
restore; file versioning; conditional execution; variable substitution;
shell subprocess with timeout; and AES-256-GCM file encryption.

.. toctree::
   :maxdepth: 2
   :caption: Local Operations

   usage/local

.. _eng-transfer:

Chapter 5 — HTTP Transfers
==========================

SSRF-validated outbound HTTP downloads with size, timeout, retry, and
``expected_sha256`` caps via ``http_download``. Resumable ``Range:``
downloads to ``<target>.part`` and live progress snapshots.

.. toctree::
   :maxdepth: 2
   :caption: HTTP Transfers

   usage/transfer

.. _eng-cloud:

Chapter 6 — Cloud and SFTP Backends
===================================

Google Drive, S3, Azure Blob, Dropbox, OneDrive, Box, SFTP, FTP / FTPS,
WebDAV, SMB, and fsspec — auto-registered through ``build_default_registry``.
``copy_between`` moves data across backends via URI prefixes.

.. toctree::
   :maxdepth: 2
   :caption: Cloud and SFTP Backends

   usage/cloud

.. _eng-servers:

Chapter 7 — Action Servers
==========================

Loopback-only TCP and HTTP servers that accept JSON action lists, with
optional shared-secret authentication, ``ActionACL`` allow lists,
``GET /healthz`` / ``GET /readyz`` probes, ``GET /openapi.json``, a
``GET /progress`` WebSocket, and the typed ``HTTPActionClient`` SDK.

.. toctree::
   :maxdepth: 2
   :caption: Action Servers

   usage/servers

.. _eng-mcp:

Chapter 8 — MCP Server
======================

``MCPServer`` bridges the registry to any Model Context Protocol host
(Claude Desktop, Claude Code, MCP CLIs) over newline-delimited JSON-RPC
2.0 on stdio.

.. toctree::
   :maxdepth: 2
   :caption: MCP Server

   usage/mcp

.. _eng-gui:

Chapter 9 — GUI
===============

The PySide6 desktop control surface — tabbed layout, log panel, and
``ActionWorker`` thread-pool model.

.. toctree::
   :maxdepth: 2
   :caption: GUI

   usage/gui

.. _eng-reliability:

Chapter 10 — Reliability
========================

``retry_on_transient`` with capped exponential back-off, ``Quota`` size
and time budgets, ``CircuitBreaker``, ``RateLimiter``, ``FileLock`` /
``SQLiteLock``, persistent ``ActionQueue``, SQLite ``AuditLog``,
``IntegrityMonitor`` for periodic manifest verification, and the typed
``FileAutomationException`` hierarchy.

.. toctree::
   :maxdepth: 2
   :caption: Reliability

   usage/reliability

.. _eng-events:

Chapter 11 — Triggers and Scheduler
===================================

File-watcher triggers (``FA_watch_*``) run an action list on a filesystem
event; the cron-style scheduler (``FA_schedule_*``) runs an action list on
a recurring schedule with overlap protection.

.. toctree::
   :maxdepth: 2
   :caption: Triggers and Scheduler

   usage/events

.. _eng-notifications:

Chapter 12 — Notifications
==========================

Slack, Email (SMTP), Discord, Telegram, Microsoft Teams, PagerDuty, and
generic webhook sinks composed by a ``NotificationManager`` with per-sink
error isolation and sliding-window dedup.

.. toctree::
   :maxdepth: 2
   :caption: Notifications

   usage/notifications

.. _eng-config:

Chapter 13 — Configuration and Secrets
======================================

Declare sinks and defaults in ``automation_file.toml``; ``${env:…}`` /
``${file:…}`` references resolve through chained ``EnvSecretProvider`` /
``FileSecretProvider``; ``ConfigWatcher`` polls and hot-reloads the file
without restart.

.. toctree::
   :maxdepth: 2
   :caption: Configuration and Secrets

   usage/config

.. _eng-dag:

Chapter 14 — DAG Action Executor
================================

Run action lists as a DAG with declared dependencies, topological parallel
fan-out, and per-branch skip-on-failure.

.. toctree::
   :maxdepth: 2
   :caption: DAG Action Executor

   usage/dag

.. _eng-plugins:

Chapter 15 — Plugins
====================

Third-party packages register their own ``FA_*`` actions through
``[project.entry-points."automation_file.actions"]``; ``PackageLoader``
imports a Python package and registers its top-level members as
``<package>_<member>``.

.. toctree::
   :maxdepth: 2
   :caption: Plugins

   usage/plugins
