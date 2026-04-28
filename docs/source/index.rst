automation_file
===============

Languages: **English** | `繁體中文 <../html-zh-TW/index.html>`_ | `简体中文 <../html-zh-CN/index.html>`_

A modular, JSON-driven file-automation framework for Python.

``automation_file`` packages local file / directory / ZIP operations,
SSRF-validated HTTP downloads, remote storage backends (Google Drive, S3,
Azure Blob, Dropbox, OneDrive, Box, SFTP, FTP, WebDAV, SMB, fsspec), and
JSON-driven action execution over embedded TCP / HTTP / MCP servers — all
dispatched through a shared ``ActionRegistry`` and exposed through a
PySide6 desktop GUI.

The documentation is split by language and by content type. Each language
manual is organised into chapters — Getting Started, CLI, Architecture,
Local Operations, HTTP Transfers, Cloud and SFTP Backends, Action Servers,
MCP Server, GUI, Reliability, Triggers and Scheduler, Notifications,
Configuration, DAG, and Plugins. The API Reference book holds the
auto-generated Python reference.

RoadMap
-------

Project tracker: https://github.com/Integration-Automation/FileAutomation/issues

.. toctree::
   :maxdepth: 2
   :caption: Manual

   Chapter 1 — Getting Started <usage/quickstart>
   Chapter 2 — CLI <usage/cli>
   Chapter 3 — Architecture <architecture>
   Chapter 4 — Local Operations <usage/local>
   Chapter 5 — HTTP Transfers <usage/transfer>
   Chapter 6 — Cloud and SFTP Backends <usage/cloud>
   Chapter 7 — Action Servers <usage/servers>
   Chapter 8 — MCP Server <usage/mcp>
   Chapter 9 — GUI <usage/gui>
   Chapter 10 — Reliability <usage/reliability>
   Chapter 11 — Triggers and Scheduler <usage/events>
   Chapter 12 — Notifications <usage/notifications>
   Chapter 13 — Configuration and Secrets <usage/config>
   Chapter 14 — DAG Action Executor <usage/dag>
   Chapter 15 — Plugins <usage/plugins>

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   Chapter A — Core <api/core>
   Chapter B — Local Operations <api/local>
   Chapter C — Remote Operations <api/remote>
   Chapter D — Server <api/server>
   Chapter E — Client SDK <api/client>
   Chapter F — Triggers <api/trigger>
   Chapter G — Scheduler <api/scheduler>
   Chapter H — Notifications <api/notify>
   Chapter I — Progress and Cancellation <api/progress>
   Chapter J — Project Scaffolding <api/project>
   Chapter K — Graphical User Interface <api/ui>
   Chapter L — Utils <api/utils>

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
