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

事件路由
----------------

通知可以改由 :doc:`事件 <event_bus>` 驱动，而不是由各个模块自行调用 sink：组件
发布事件，再由 :class:`~automation_file.notify.router.NotificationRouter` 决定
哪些 sink 会收到。

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
   notification_router.start()          # 在事件总线上订阅

路由器在调用 ``start()`` 之前不会工作；``stop()`` 会取消订阅，``active`` 则表示
当前的状态。``add_route`` 会替换同名的路由，``remove_route(name)`` 移除一条路由，
``routes()`` 列出所有路由。需要私有的路由器时使用
``NotificationRouter(manager, bus)``。

路由
~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 22 18 60

   * - 字段
     - 默认值
     - 含义
   * - ``name``
     - 必填
     - 路由的标识名称。
   * - ``sinks``
     - ``()``
     - 在 ``NotificationManager`` 上注册的名称。留空代表所有 sink。
   * - ``types``
     - ``()``
     - 总线的筛选条件：事件类、type 名称（``"task.failed"``）或前缀
       （``"pipeline.*"``）。留空代表所有 type。
   * - ``sources``
     - ``()``
     - 完全相同的 ``event.source`` 值。留空代表所有来源。
   * - ``min_severity``
     - ``Severity.WARNING``
     - 这条路由会投递的最低严重程度。
   * - ``dedup_seconds``
     - ``300.0``
     - 去重窗口。``0`` 表示关闭。
   * - ``rate_limit``
     - ``0``
     - 每个 ``rate_period`` 内允许的消息数。``0`` 表示不限制。
   * - ``rate_period``
     - ``60.0``
     - 速率限制窗口的长度，单位为秒。

同一个 sink 即使被多条路由覆盖，同一个事件也只会收到一次：由第一条获准发送的
路由负责投递。不匹配任何路由的事件不会被投递。

sink 收到的内容
~~~~~~~~~~~~~~~~~~~~~~~~

消息由事件组成。主题类似 ``[ERROR] task.failed: load failed``；正文依次列出
严重程度、type、来源、主题、时间、关联 ID 与 actor，接着是
``event.to_dict()`` 的 JSON。严重程度会对应到 sink 接受的级别：``info``、
``warning`` 与 ``error`` 保持原名，``critical`` 则以 ``error`` 发送。

去重与速率限制
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

两者都是以“每条路由、每个 sink”为单位分别计算。

- **去重** —— 同一个事件（type、来源与主题都相同）在第一次之后的
  ``dedup_seconds`` 内再次出现时会被丢弃；不会比较 payload。失败的尝试也算在内，
  因此故障的 sink 不会在每次重复时都被再试一次。
- **速率限制** —— 每个 ``rate_period`` 内最多发送 ``rate_limit`` 条消息。被限制
  挡下的事件不会被记成已发送，因此它下一次出现时仍然可以送出；重复的事件不会
  消耗额度。

``notification_router.handle(event)`` 会针对每个 sink 返回一个结果：``sent``、
``dedup``、``rate_limited``，或以 ``"<ExceptionType>: <message>"`` 表示的错误。

投递是在发布事件的线程中进行的。请让 sink 的超时时间保持简短；这两道防护限制了
缓慢的 sink 被调用的频率。

失败
~~~~~~~~

单个 sink 失败绝对不会影响其他 sink。每一次失败都会被记录到日志，并以
``source="notify"`` 的 ``SystemErrorEvent`` 发布；它的 payload 会指出 sink
（``resource``）、``route``、``error``，以及无法投递的那个事件的 ``event_type`` 与
``event_id``。路由器绝对不会路由这类事件，因此故障的 sink 不会形成循环；要查看
它们，请订阅总线，或搜索 :doc:`审计轨迹 <audit>`。错误文本中的 URL 只会保留
主机名，因为 webhook URL 或 bot token 都属于机密。

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
   apply(watcher.start())               # 立即加载，之后每当文件变更就重新加载

``apply_to(manager, router)`` 会注册 sink，并让 ``[[notify.routes]]`` 表成为
路由器的配置路由：从文件中移除的表会在下一次重新加载时停止路由，而在代码中
加入的路由则保留。文件声明了路由时会启动路由器；重新加载移除了最后一条路由时
则会停止。
路由只能指向文件中声明的、或已经在管理器上注册的 sink；未知的 sink、未知的
严重程度、未知的选项或重复的名称，都会在任何变更发生之前抛出
:class:`~automation_file.ConfigException`，因此失败的重新加载会保留先前的路由。
没有传入 ``router`` 参数时，路由不会被应用。

动作
~~~~~~~~

.. code-block:: json

   [
     ["FA_notify_route_add", {"name": "pipeline-failures", "sinks": ["team-alerts"],
                              "types": ["pipeline.*", "task.failed"], "min_severity": "error",
                              "dedup_seconds": 600, "rate_limit": 10, "rate_period": 60}],
     ["FA_notify_route_list"],
     ["FA_notify_route_remove", {"name": "pipeline-failures"}]
   ]

这些动作作用于进程级的路由器。``FA_notify_route_add`` 会启动它，
``FA_notify_route_remove`` 则在最后一条路由被移除时停止它。

``notify_on_failure``
~~~~~~~~~~~~~~~~~~~~~

调度器与触发器仍然调用 ``notify_on_failure(context, error)``。它现在总是会发布
一个事件：context 是调度作业（``scheduler[nightly]``）时为 ``SchedulerError``，
其余情况为 ``SystemErrorEvent``。接着：

- **路由器工作中** —— 由路由器按照路由投递该事件，不会再发送其他消息，因此
  没有人会收到两次通知；
- **路由器未工作** —— ``error`` 级别的消息也会直接送到每一个已注册的 sink，与
  以往完全相同，因此不会有人收不到通知。

路由器工作时由路由决定：没有任何路由匹配的失败不会被投递。像
``Route("failures", types=("scheduler.error", "system.error"))`` 这样的路由可以
让这些告警持续送达。

调度器会为它无法分派的动作列表调用 ``notify_on_failure``。以其他任何方式失败、或
超过超时的调度运行，则由调度器自己发布成 ``scheduler.error`` 事件，只有通过路由才会
送到 sink：见 :doc:`scheduler`。
