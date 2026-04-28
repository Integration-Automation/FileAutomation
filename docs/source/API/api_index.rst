==============================
automation_file API Reference
==============================

The API reference is the auto-generated Python reference for every public
module in ``automation_file``. Each chapter covers one slice of the package;
use the table of contents on the left, or jump straight to a chapter below.

.. contents:: On this page
   :local:
   :depth: 1

----

.. _api-core:

Chapter A — Core
================

``ActionRegistry``, ``ActionExecutor``, ``CallbackExecutor``,
``PackageLoader``, the JSON store, retry decorator, and quota guard.

.. toctree::
   :maxdepth: 2
   :caption: Core

   core

.. _api-local:

Chapter B — Local Operations
============================

File, directory, ZIP, tar, and ``safe_paths`` strategy modules.

.. toctree::
   :maxdepth: 2
   :caption: Local Operations

   local

.. _api-remote:

Chapter C — Remote Operations
=============================

URL validator, HTTP download, Google Drive, S3, Azure Blob, Dropbox,
OneDrive, Box, SFTP, FTP / FTPS, WebDAV, SMB, and fsspec backends.

.. toctree::
   :maxdepth: 2
   :caption: Remote Operations

   remote

.. _api-server:

Chapter D — Server
==================

``TCPActionServer``, ``HTTPActionServer``, ``MCPServer``,
``MetricsServer``, ``WebUIServer``, and the ``ActionACL``.

.. toctree::
   :maxdepth: 2
   :caption: Server

   server

.. _api-client:

Chapter E — Client SDK
======================

The Python client for talking to a running TCP / HTTP action server.

.. toctree::
   :maxdepth: 2
   :caption: Client SDK

   client

.. _api-trigger:

Chapter F — Triggers
====================

Composable trigger primitives that fire registered actions.

.. toctree::
   :maxdepth: 2
   :caption: Triggers

   trigger

.. _api-scheduler:

Chapter G — Scheduler
=====================

Cron-style scheduler for periodic action execution.

.. toctree::
   :maxdepth: 2
   :caption: Scheduler

   scheduler

.. _api-notify:

Chapter H — Notifications
=========================

Notification sinks (Slack, Email, Discord, Telegram, Teams, PagerDuty,
Webhook).

.. toctree::
   :maxdepth: 2
   :caption: Notifications

   notify

.. _api-progress:

Chapter I — Progress and Cancellation
=====================================

Progress reporting and cooperative cancellation primitives.

.. toctree::
   :maxdepth: 2
   :caption: Progress and Cancellation

   progress

.. _api-project:

Chapter J — Project Scaffolding
===============================

``ProjectBuilder`` and the project skeleton templates.

.. toctree::
   :maxdepth: 2
   :caption: Project Scaffolding

   project

.. _api-ui:

Chapter K — Graphical User Interface
====================================

``MainWindow``, ``ActionWorker``, ``LogPanel``, and the per-domain tab
modules.

.. toctree::
   :maxdepth: 2
   :caption: Graphical User Interface

   ui

.. _api-utils:

Chapter L — Utils
=================

File-discovery, fast-find, deduplicate, grep, and rotate helpers.

.. toctree::
   :maxdepth: 2
   :caption: Utils

   utils
