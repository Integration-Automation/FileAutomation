Application layer
=================

What a user interface calls: one service per navigation entry, on top of the
domain packages. The PySide6 window and the Web UI are both built on it. It
imports no GUI toolkit and no backend SDK, returns JSON-friendly data and masks
secrets in what it returns. Usage is described in the manual chapter
*Application layer*.

The set of services
-------------------

.. automodule:: automation_file.app

.. automodule:: automation_file.app.services
   :members:

Dashboard
---------

.. automodule:: automation_file.app.dashboard_service
   :members:

Files
-----

.. automodule:: automation_file.app.file_service
   :members:

Storage
-------

.. automodule:: automation_file.app.storage_service
   :members:

Pipelines
---------

.. automodule:: automation_file.app.pipeline_draft
   :members:

.. automodule:: automation_file.app.pipeline_service
   :members:

Scheduler
---------

.. automodule:: automation_file.app.scheduler_service
   :members:

Integrity
---------

.. automodule:: automation_file.app.integrity_service
   :members:

Audit
-----

.. automodule:: automation_file.app.audit_service
   :members:

Notifications
-------------

.. automodule:: automation_file.app.notification_service
   :members:

Settings
--------

.. automodule:: automation_file.app.settings_service
   :members:

Form helpers
------------

.. automodule:: automation_file.app.arguments
   :members:

Secrets
-------

.. automodule:: automation_file.app.masking
   :members:

Exceptions
----------

.. automodule:: automation_file.app.errors
   :members:
