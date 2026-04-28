觸發器與排程器
==============

檔案監看觸發器
--------------

當被監看的路徑上有檔案系統事件時，自動執行一份動作清單。
模組層級的 :data:`~automation_file.trigger.trigger_manager` 維護一份
依名稱索引的活躍監看器表，讓 JSON 外觀與 GUI 共用同一個生命週期。

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
   # 稍後：
   watch_stop("inbox-sweeper")

也可以在 JSON 動作清單中呼叫 ``FA_watch_start`` /
``FA_watch_stop`` / ``FA_watch_stop_all`` / ``FA_watch_list``。

Cron 排程器
-----------

依重複時刻執行動作清單。5 欄位 cron 解析器支援
``*``、精確值、``a-b`` 區間、逗號分隔清單與 ``*/n`` 步長，
也支援 ``jan``..``dec`` / ``sun``..``sat`` 別名。

.. code-block:: python

   from automation_file import schedule_add

   schedule_add(
       name="nightly-snapshot",
       cron_expression="0 2 * * *",           # 每天本地時間 02:00
       action_list=[["FA_zip_dir", {"dir_we_want_to_zip": "/data",
                                    "zip_name": "/backup/data_nightly"}]],
   )

背景執行緒在每分鐘邊界喚醒，因此不支援小於一分鐘的精度。
JSON 形式：``FA_schedule_add`` / ``FA_schedule_remove`` /
``FA_schedule_remove_all`` / ``FA_schedule_list``。

當動作清單擲出
:class:`~automation_file.exceptions.FileAutomationException` 時，
兩個排程器都會呼叫
:func:`~automation_file.notify.manager.notify_on_failure`。
若未註冊任何 sink，該輔助函式即為 no-op，因此自動通知是
註冊 :class:`~automation_file.NotificationSink` 的可選副作用——
詳見 :doc:`notifications`。
