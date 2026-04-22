圖形介面
========

PySide6 前端。匯入 ``automation_file.ui`` 會立即載入 Qt；facade 上的
``automation_file.launch_ui`` 屬性則是延遲載入（只在存取時才拉入 Qt），
因此非 UI 工作負載可維持低匯入成本。

啟動器
------

.. automodule:: automation_file.ui.launcher
   :members:

主視窗
------

.. automodule:: automation_file.ui.main_window
   :members:

背景 worker
-----------

.. automodule:: automation_file.ui.worker
   :members:

Log 面板
--------

.. automodule:: automation_file.ui.log_widget
   :members:

分頁
----

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
