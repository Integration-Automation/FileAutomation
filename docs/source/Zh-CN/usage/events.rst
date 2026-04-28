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

Cron 调度器
-----------

按重复时刻执行动作列表。5 字段 cron 解析器支持
``*``、精确值、``a-b`` 区间、逗号分隔列表与 ``*/n`` 步长，
也支持 ``jan``..``dec`` / ``sun``..``sat`` 别名。

.. code-block:: python

   from automation_file import schedule_add

   schedule_add(
       name="nightly-snapshot",
       cron_expression="0 2 * * *",           # 每天本地时间 02:00
       action_list=[["FA_zip_dir", {"dir_we_want_to_zip": "/data",
                                    "zip_name": "/backup/data_nightly"}]],
   )

后台线程在每分钟边界唤醒，因此不支持小于一分钟的精度。
JSON 形式：``FA_schedule_add`` / ``FA_schedule_remove`` /
``FA_schedule_remove_all`` / ``FA_schedule_list``。

当动作列表抛出
:class:`~automation_file.exceptions.FileAutomationException` 时，
两个调度器都会调用
:func:`~automation_file.notify.manager.notify_on_failure`。
若未注册任何 sink，该助手是 no-op，因此自动通知是
注册 :class:`~automation_file.NotificationSink` 的可选副作用——
详见 :doc:`notifications`。
