图形界面
========

PySide6 前端。导入 ``automation_file.ui`` 会立即加载 Qt；facade 上的
``automation_file.launch_ui`` 属性则是延迟加载（只在访问时才拉入 Qt），
因此非 UI 工作负载可维持较低的导入成本。

启动器
------

.. automodule:: automation_file.ui.launcher
   :members:

主窗口
------

.. automodule:: automation_file.ui.main_window
   :members:

后台 worker
-----------

.. automodule:: automation_file.ui.worker
   :members:

Log 面板
--------

.. automodule:: automation_file.ui.log_widget
   :members:

标签页
------

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
