Graphical user interface
========================

PySide6 front-end. Importing ``automation_file.ui`` loads Qt eagerly; the
facade ``automation_file.launch_ui`` attribute is lazy (only pulls Qt when
accessed) so non-UI workloads keep their import cost low.

The main window is a sidebar over nine workflow pages -- Dashboard, Files,
Storage, Pipelines, Scheduler, Integrity, Audit, Notifications, Settings --
and an Advanced page that keeps the earlier tabs. Every workflow page is a
view over one service of :mod:`automation_file.app` and imports nothing below
that layer. Usage is described in the manual chapter *GUI*.

Launcher
--------

.. automodule:: automation_file.ui.launcher
   :members:

Main window
-----------

.. automodule:: automation_file.ui.main_window
   :members:

Background worker
-----------------

.. automodule:: automation_file.ui.worker
   :members:

Log panel
---------

.. automodule:: automation_file.ui.log_widget
   :members:

Pages
-----

.. automodule:: automation_file.ui.pages
   :members:

.. automodule:: automation_file.ui.pages.base
   :members:

.. automodule:: automation_file.ui.pages.dashboard_page
   :members:

.. automodule:: automation_file.ui.pages.files_page
   :members:

.. automodule:: automation_file.ui.pages.storage_page
   :members:

.. automodule:: automation_file.ui.pages.scheduler_page
   :members:

.. automodule:: automation_file.ui.pages.integrity_page
   :members:

.. automodule:: automation_file.ui.pages.audit_page
   :members:

.. automodule:: automation_file.ui.pages.notifications_page
   :members:

.. automodule:: automation_file.ui.pages.settings_page
   :members:

.. automodule:: automation_file.ui.pages.advanced_page
   :members:

Pipeline editor
---------------

.. automodule:: automation_file.ui.pages.pipelines_page
   :members:

.. automodule:: automation_file.ui.pages.pipeline_canvas
   :members:

.. automodule:: automation_file.ui.pages.task_form
   :members:

.. automodule:: automation_file.ui.pages.run_panel
   :members:

Tabs
----

The tabs of the earlier window. ``LocalOpsTab``, ``TransferTab`` (with one
panel per backend), ``ProgressTab``, ``JSONEditorTab``, ``TriggerTab`` and
``ServerTab`` are shown by the Advanced page. ``HomeTab`` and ``SchedulerTab``
are no longer part of the main window (the Dashboard and Scheduler pages took
their place); they remain importable widgets.

.. automodule:: automation_file.ui.tabs
   :members:

.. automodule:: automation_file.ui.tabs.base
   :members:

.. automodule:: automation_file.ui.tabs.home_tab
   :members:

.. automodule:: automation_file.ui.tabs.local_tab
   :members:

.. automodule:: automation_file.ui.tabs.http_tab
   :members:

.. automodule:: automation_file.ui.tabs.drive_tab
   :members:

.. automodule:: automation_file.ui.tabs.s3_tab
   :members:

.. automodule:: automation_file.ui.tabs.azure_tab
   :members:

.. automodule:: automation_file.ui.tabs.dropbox_tab
   :members:

.. automodule:: automation_file.ui.tabs.sftp_tab
   :members:

.. automodule:: automation_file.ui.tabs.onedrive_tab
   :members:

.. automodule:: automation_file.ui.tabs.box_tab
   :members:

.. automodule:: automation_file.ui.tabs.transfer_tab
   :members:

.. automodule:: automation_file.ui.tabs.json_editor_tab
   :members:

.. automodule:: automation_file.ui.tabs.server_tab
   :members:

.. automodule:: automation_file.ui.tabs.trigger_tab
   :members:

.. automodule:: automation_file.ui.tabs.scheduler_tab
   :members:

.. automodule:: automation_file.ui.tabs.progress_tab
   :members:
