触发器
======

以 ``watchdog`` 监视本地路径，并在匹配的文件系统事件发生时调度动作列表。
模块级的 :data:`~automation_file.trigger.trigger_manager` 以名称为键维护
一组活动 watcher，让 JSON 接口与 GUI 共享同一个生命周期。

.. automodule:: automation_file.trigger
   :members:

.. automodule:: automation_file.trigger.manager
   :members:
