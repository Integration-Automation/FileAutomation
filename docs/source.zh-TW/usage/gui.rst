GUI（PySide6）
==============

分頁式控制面板封裝了所有功能：

.. code-block:: bash

   python -m automation_file ui
   # 或在儲存庫根目錄開發時：
   python main_ui.py

.. code-block:: python

   from automation_file import launch_ui

   launch_ui()

分頁：Home、Local、Transfer、Progress、JSON actions、Triggers、
Scheduler、Servers。所有分頁下方共用一個常駐日誌面板，
逐條輸出每次呼叫的結果或錯誤。背景工作透過 ``ActionWorker`` 在
``QThreadPool`` 上執行，UI 始終保持回應。

GUI 與函式庫其餘部分共用同一組單例——從 Python 註冊的 sink、
自訂動作、觸發器都會立即在執行中的視窗生效。
