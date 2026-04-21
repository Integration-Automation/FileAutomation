Graphical user interface
========================

PySide6 front-end. Importing ``automation_file.ui`` loads Qt eagerly; the
facade ``automation_file.launch_ui`` attribute is lazy (only pulls Qt when
accessed) so non-UI workloads keep their import cost low.

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

Tabs
----

.. automodule:: automation_file.ui.tabs
   :members:

.. automodule:: automation_file.ui.tabs.base
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

.. automodule:: automation_file.ui.tabs.action_tab
   :members:

.. automodule:: automation_file.ui.tabs.server_tab
   :members:
