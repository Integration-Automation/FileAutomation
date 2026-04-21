调度器
======

以 cron 风格执行周期性动作列表。解析器支持标准 5 字段语法（分 时 日
月 星期），包含 ``*``、范围、列表、``*/n`` 步进以及月份 / 星期别名。
后台线程在分钟边界唤醒，通过共享的 :class:`ActionExecutor` 调度
每个匹配的任务。

.. automodule:: automation_file.scheduler
   :members:

.. automodule:: automation_file.scheduler.cron
   :members:

.. automodule:: automation_file.scheduler.manager
   :members:
