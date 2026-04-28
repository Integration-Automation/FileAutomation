GUI（PySide6）
==============

分页式控制面板封装了所有功能：

.. code-block:: bash

   python -m automation_file ui
   # 或在仓库根目录开发时：
   python main_ui.py

.. code-block:: python

   from automation_file import launch_ui

   launch_ui()

标签页：Home、Local、Transfer、Progress、JSON actions、Triggers、
Scheduler、Servers。所有标签页下方共用一个常驻日志面板，
逐条输出每次调用的结果或错误。后台任务通过 ``ActionWorker`` 在
``QThreadPool`` 上执行，UI 始终保持响应。

GUI 与库其余部分共用同一组单例——从 Python 注册的 sink、
自定义动作、触发器都会立即在运行中的窗口生效。
