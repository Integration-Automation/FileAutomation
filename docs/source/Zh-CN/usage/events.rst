触发器与调度器
==============

文件监听触发器
--------------

当被监听的路径上有文件系统事件时，自动执行一份动作列表。
模块级的 :data:`~automation_file.trigger.trigger_manager` 维护一份
按名称索引的活跃监听器表，让 JSON 外观与 GUI 共用同一份生命周期。

.. code-block:: python

   from automation_file import watch_start, watch_stop

   watch_start(
       name="inbox-sweeper",
       path="/data/inbox",
       action_list=[["FA_copy_all_file_to_dir",
                     {"source_dir": "/data/inbox",
                      "target_dir": "/data/processed"}]],
       events=["created", "modified"],
       recursive=False,
   )
   # 稍后：
   watch_stop("inbox-sweeper")

也可以从 JSON 动作列表里调用 ``FA_watch_start`` /
``FA_watch_stop`` / ``FA_watch_stop_all`` / ``FA_watch_list``。

调度器
------------

按带时区的 cron 表达式、文件事件、事件总线上的事件、另一条流水线结束之后，或以手动
方式运行动作列表或流水线，都写在 :doc:`scheduler` 中，其中也说明了运行记录、重叠保护、
超时与 ``FA_schedule_*`` 动作。需要在文件事件发生时运行并为每次运行留下记录的作业，
请使用调度器的 ``FileTrigger``，而不是 ``FA_watch_start``。

当动作列表抛出
:class:`~automation_file.exceptions.FileAutomationException` 时，
监听器会调用
:func:`~automation_file.notify.manager.notify_on_failure`。
若未注册任何 sink，该助手是 no-op，因此自动通知是
注册 :class:`~automation_file.NotificationSink` 的可选副作用——
详见 :doc:`notifications`。调度器对它无法分派的动作列表也会这么做，其他每一次
失败的运行则发布成 ``scheduler.error`` 事件。
