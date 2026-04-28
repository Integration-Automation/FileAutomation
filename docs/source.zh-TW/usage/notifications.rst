通知
====

可主動推送訊息，也可在觸發器 / 排程器失敗時自動通知，
支援 webhook、Slack 與 SMTP：

.. code-block:: python

   from automation_file import (
       SlackSink, WebhookSink, EmailSink,
       notification_manager, notify_send,
   )

   notification_manager.register(SlackSink("https://hooks.slack.com/services/T/B/X"))
   notify_send("deploy complete", body="rev abc123", level="info")

每個 sink 皆實作相同的 ``send(subject, body, level)`` 契約；
扇出 :class:`~automation_file.NotificationManager` 負責：

- **逐 sink 錯誤隔離** —— 一個壞 sink 不會拖累其他。
- **滑動視窗去重** —— ``dedup_seconds`` 內相同的
  ``(subject, body, level)`` 會被丟棄，防止卡住的觸發器把通道刷爆。
- **SSRF 檢查** —— 每個 webhook / Slack URL 都會被檢查。

排程器與觸發器在失敗時會自動以 ``level="error"`` 通知——
只要註冊任意一個 sink，就能取得正式環境告警。JSON 形式：
``FA_notify_send`` / ``FA_notify_list``。
