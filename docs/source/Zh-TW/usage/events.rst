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

排程器
------------

依帶時區的 cron 運算式、檔案事件、事件匯流排上的事件、另一條管線結束之後，或以手動
方式執行動作清單或管線，都寫在 :doc:`scheduler` 中，其中也說明了執行紀錄、重疊保護、
逾時與 ``FA_schedule_*`` 動作。需要在檔案事件發生時執行並為每次執行留下紀錄的工作，
請使用排程器的 ``FileTrigger``，而不是 ``FA_watch_start``。

當動作清單擲出
:class:`~automation_file.exceptions.FileAutomationException` 時，
監看器會呼叫
:func:`~automation_file.notify.manager.notify_on_failure`。
若未註冊任何 sink，該輔助函式即為 no-op，因此自動通知是
註冊 :class:`~automation_file.NotificationSink` 的可選副作用——
詳見 :doc:`notifications`。排程器對它無法分派的動作清單也會這麼做，其他每一次
失敗的執行則發布成 ``scheduler.error`` 事件。
