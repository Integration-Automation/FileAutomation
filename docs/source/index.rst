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

* **PyPI**: https://pypi.org/project/automation_file/
* **GitHub**: https://github.com/Integration-Automation/FileAutomation
* **Issues / RoadMap**: https://github.com/Integration-Automation/FileAutomation/issues
* **License**: MIT

----

The documentation is split by language and by content type. Each language
manual is organised into chapters (Getting Started, CLI, Architecture, Local
Operations, HTTP Transfers, Cloud and SFTP Backends, Action Servers, MCP
Server, GUI, Reliability, Triggers and Scheduler, Notifications,
Configuration, DAG, Plugins); the API book holds the auto-generated Python
reference for every public module. Pick a language from the table of
contents on the left, or jump straight to a section below.

.. toctree::
   :maxdepth: 2
   :caption: English manual

   Eng/eng_index.rst

.. toctree::
   :maxdepth: 2
   :caption: 繁體中文手冊

   Zh-TW/zh_tw_index.rst

.. toctree::
   :maxdepth: 2
   :caption: 简体中文手册

   Zh-CN/zh_cn_index.rst

.. toctree::
   :maxdepth: 2
   :caption: API reference

   API/api_index.rst

----

RoadMap
-------

* Project tracker: https://github.com/Integration-Automation/FileAutomation/issues

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
