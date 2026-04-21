排程器
======

以 cron 風格執行週期性動作清單。解析器支援標準 5 欄位語法（分 時 日
月 星期），包含 ``*``、範圍、清單、``*/n`` 步進以及月份 / 星期別名。
背景執行緒在分鐘邊界甦醒，透過共享的 :class:`ActionExecutor` 調度
每個相符的任務。

.. automodule:: automation_file.scheduler
   :members:

.. automodule:: automation_file.scheduler.cron
   :members:

.. automodule:: automation_file.scheduler.manager
   :members:
