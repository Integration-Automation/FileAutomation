通知
====

可主动推送消息，也可在触发器 / 调度器失败时自动通知，
支持 webhook、Slack 与 SMTP：

.. code-block:: python

   from automation_file import (
       SlackSink, WebhookSink, EmailSink,
       notification_manager, notify_send,
   )

   notification_manager.register(SlackSink("https://hooks.slack.com/services/T/B/X"))
   notify_send("deploy complete", body="rev abc123", level="info")

每个 sink 都实现相同的 ``send(subject, body, level)`` 契约；
扇出 :class:`~automation_file.NotificationManager` 负责：

- **逐 sink 错误隔离** —— 一个坏 sink 不会拖累其他。
- **滑动窗口去重** —— ``dedup_seconds`` 内相同的
  ``(subject, body, level)`` 会被丢弃，防止卡住的触发器把通道刷爆。
- **SSRF 校验** —— 每个 webhook / Slack URL 都会被检查。

调度器与触发器在失败时会自动以 ``level="error"`` 通知——
只要注册任意一个 sink，就能拿到生产告警。JSON 形式：
``FA_notify_send`` / ``FA_notify_list``。
