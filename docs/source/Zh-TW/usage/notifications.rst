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

事件路由
----------------

通知可以改由 :doc:`事件 <event_bus>` 驅動，而不是由各個模組自行呼叫 sink：元件
發布事件，再由 :class:`~automation_file.notify.router.NotificationRouter` 決定
哪些 sink 會收到。

.. code-block:: python

   from automation_file import (
       Route, Severity, SlackSink, notification_manager, notification_router,
   )

   notification_manager.register(SlackSink("https://hooks.slack.com/services/T/B/X",
                                           name="team-alerts"))
   notification_router.add_route(Route(
       "pipeline-failures",
       sinks=("team-alerts",),
       types=("pipeline.*", "task.failed"),
       min_severity=Severity.ERROR,
       dedup_seconds=600,
       rate_limit=10,
       rate_period=60,
   ))
   notification_router.start()          # 在事件匯流排上訂閱

路由器在呼叫 ``start()`` 之前不會運作；``stop()`` 會取消訂閱，``active`` 則表示
目前的狀態。``add_route`` 會取代同名的路由，``remove_route(name)`` 移除一條路由，
``routes()`` 列出所有路由。需要私有的路由器時使用
``NotificationRouter(manager, bus)``。

路由
~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 22 18 60

   * - 欄位
     - 預設值
     - 意義
   * - ``name``
     - 必填
     - 路由的識別名稱。
   * - ``sinks``
     - ``()``
     - 在 ``NotificationManager`` 上註冊的名稱。留空代表所有 sink。
   * - ``types``
     - ``()``
     - 匯流排的篩選條件：事件類別、type 名稱（``"task.failed"``）或前綴
       （``"pipeline.*"``）。留空代表所有 type。
   * - ``sources``
     - ``()``
     - 完全相同的 ``event.source`` 值。留空代表所有來源。
   * - ``min_severity``
     - ``Severity.WARNING``
     - 這條路由會投遞的最低嚴重程度。
   * - ``dedup_seconds``
     - ``300.0``
     - 去重視窗。``0`` 表示關閉。
   * - ``rate_limit``
     - ``0``
     - 每個 ``rate_period`` 內允許的訊息數。``0`` 表示不限制。
   * - ``rate_period``
     - ``60.0``
     - 速率限制視窗的長度，單位為秒。

同一個 sink 即使被多條路由涵蓋，同一個事件也只會收到一次：由第一條獲准發送的
路由負責投遞。不符合任何路由的事件不會被投遞。

sink 收到的內容
~~~~~~~~~~~~~~~~~~~~~~~~

訊息由事件組成。主旨類似 ``[ERROR] task.failed: load failed``；內文依序列出
嚴重程度、type、來源、主旨、時間、關聯 ID 與 actor，接著是
``event.to_dict()`` 的 JSON。嚴重程度會對應到 sink 接受的等級：``info``、
``warning`` 與 ``error`` 維持原名，``critical`` 則以 ``error`` 發送。

去重與速率限制
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

兩者都是以「每條路由、每個 sink」為單位分別計算。

- **去重** —— 同一個事件（type、來源與主旨都相同）在第一次之後的
  ``dedup_seconds`` 內再次出現時會被丟棄；不會比較 payload。失敗的嘗試也算在內，
  因此故障的 sink 不會在每次重複時都被再試一次。
- **速率限制** —— 每個 ``rate_period`` 內最多發送 ``rate_limit`` 則訊息。被限制
  擋下的事件不會被記成已發送，因此它下一次出現時仍然可以送出；重複的事件不會
  消耗額度。

``notification_router.handle(event)`` 會針對每個 sink 回傳一個結果：``sent``、
``dedup``、``rate_limited``，或以 ``"<ExceptionType>: <message>"`` 表示的錯誤。

投遞是在發布事件的執行緒中進行的。請讓 sink 的逾時時間保持簡短；這兩道防護限制了
緩慢的 sink 被呼叫的頻率。

失敗
~~~~~~~~

單一 sink 失敗絕對不會影響其他 sink。每一次失敗都會被記錄到日誌，並以
``source="notify"`` 的 ``SystemErrorEvent`` 發布；它的 payload 會指出 sink
（``resource``）、``route``、``error``，以及無法投遞的那個事件的 ``event_type`` 與
``event_id``。路由器絕對不會路由這類事件，因此故障的 sink 不會形成迴圈；要查看
它們，請訂閱匯流排，或搜尋 :doc:`稽核軌跡 <audit>`。錯誤文字中的 URL 只會保留
主機名稱，因為 webhook URL 或 bot token 都屬於機密。

``automation_file.toml`` 中的路由
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: toml

   [[notify.sinks]]
   type = "slack"
   name = "team-alerts"
   webhook_url = "${env:SLACK_WEBHOOK}"

   [[notify.routes]]
   name = "pipeline-failures"
   sinks = ["team-alerts"]
   types = ["pipeline.*", "task.failed"]
   sources = ["pipeline"]
   min_severity = "error"
   dedup_seconds = 600
   rate_limit = 10
   rate_period = 60

.. code-block:: python

   from automation_file import (
       AutomationConfig, ConfigWatcher, notification_manager, notification_router,
   )

   def apply(config):
       config.apply_to(notification_manager, notification_router)

   watcher = ConfigWatcher("automation_file.toml", apply)
   apply(watcher.start())               # 立即載入，之後每當檔案變更就重新載入

``apply_to(manager, router)`` 會註冊 sink，並讓 ``[[notify.routes]]`` 表格成為
路由器的設定路由：從檔案中移除的表格會在下一次重新載入時停止路由，而在程式中
加入的路由則保留。檔案宣告了路由時會啟動路由器；重新載入移除了最後一條路由時
則會停止。
路由只能指向檔案中宣告的、或已經在管理器上註冊的 sink；未知的 sink、未知的
嚴重程度、未知的選項或重複的名稱，都會在任何變更發生之前拋出
:class:`~automation_file.ConfigException`，因此失敗的重新載入會保留先前的路由。
沒有傳入 ``router`` 引數時，路由不會被套用。

動作
~~~~~~~~

.. code-block:: json

   [
     ["FA_notify_route_add", {"name": "pipeline-failures", "sinks": ["team-alerts"],
                              "types": ["pipeline.*", "task.failed"], "min_severity": "error",
                              "dedup_seconds": 600, "rate_limit": 10, "rate_period": 60}],
     ["FA_notify_route_list"],
     ["FA_notify_route_remove", {"name": "pipeline-failures"}]
   ]

這些動作作用於行程層級的路由器。``FA_notify_route_add`` 會啟動它，
``FA_notify_route_remove`` 則在最後一條路由被移除時停止它。

``notify_on_failure``
~~~~~~~~~~~~~~~~~~~~~

排程器與觸發器仍然呼叫 ``notify_on_failure(context, error)``。它現在一律會發布
一個事件：context 是排程工作（``scheduler[nightly]``）時為 ``SchedulerError``，
其餘情況為 ``SystemErrorEvent``。接著：

- **路由器運作中** —— 由路由器依照路由投遞該事件，不會再發送其他訊息，因此
  沒有人會收到兩次通知；
- **路由器未運作** —— ``error`` 等級的訊息也會直接送到每一個已註冊的 sink，與
  以往完全相同，因此不會有人收不到通知。

路由器運作時由路由決定：沒有任何路由符合的失敗不會被投遞。像
``Route("failures", types=("scheduler.error", "system.error"))`` 這樣的路由可以
讓這些告警持續送達。
