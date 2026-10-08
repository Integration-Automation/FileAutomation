审计轨迹
================

审计轨迹针对库所做的每一件事回答同一个问题：**谁** 在 **什么时候** 做了
**什么**，对象是 **哪个资源**，使用 **哪个后端**，以及 **结果如何**。这是审计
模式 v2。没有任何组件会自行写入审计行：组件发布 :doc:`事件 <event_bus>`，
存储层报告它的操作，再由 :class:`~automation_file.audit.trail.AuditTrail`
把两者转成 :class:`~automation_file.audit.record.AuditRecord`，写进
:class:`~automation_file.audit.store.AuditStore`。

v1 的 :class:`~automation_file.core.audit.AuditLog` 保持原样；请见
`从 v1 迁移`_。

最小示例
----------------

.. code-block:: python

   from automation_file import audit_search, configure_audit

   configure_audit("audit.sqlite")          # 创建数据库并开始记录

   ...                                      # 运行管道、复制文件、发布事件

   for entry in audit_search(status="error", limit=20):
       print(entry["timestamp"], entry["actor"], entry["action"], entry["resource"],
             entry["error"])

``configure_audit`` 接受 SQLite 数据库的路径或一个现成的存储库，把进程级的
``audit_trail`` 指向它并启动。在调用之前，轨迹没有存储库，也不会记录任何内容。
``audit_search`` 返回普通的字典，最新的在前。

生产环境示例
------------------------

.. code-block:: python

   from automation_file import (
       File, PipelineCompleted, PipelineStarted, actor_scope, audit_search,
       audit_trail, configure_audit, correlation_scope, emit,
   )

   configure_audit("/var/lib/automation_file/audit.sqlite")

   with actor_scope("scheduler"), correlation_scope() as run_id:
       emit(PipelineStarted(source="pipeline", subject="daily-report started",
                            payload={"pipeline": "daily-report", "run_id": run_id}))
       File("s3://reports/q1.csv").copy_to("local:///backup/q1.csv")   # 会被记录
       audit_trail.record("approve", resource="s3://reports/q1.csv", backend="s3",
                          source="review", metadata={"ticket": "OPS-12"})
       emit(PipelineCompleted(source="pipeline", subject="daily-report completed",
                              payload={"pipeline": "daily-report", "duration_ms": 812.0}))

   audit_search(correlation_id=run_id)                 # 整次运行，最新的在前
   audit_search(resource_prefix="s3://reports/", since="2026-10-01T00:00:00+00:00")
   audit_trail.count(actor="scheduler", status="error")
   audit_trail.purge(older_than_seconds=90 * 24 * 3600)   # 保留 90 天

请在启动时就打开存储库，让问题立刻暴露：数据库无法打开时，``configure_audit``
会抛出 :class:`~automation_file.AuditException`。清理旧记录的工作请交给调度任务。
两个范围内的所有事物都带有相同的关联 ID 与 actor，因此只要一个筛选条件就能取回
整次运行。

自行创建轨迹，使用私有的总线或其他存储库：

.. code-block:: python

   from automation_file import AuditTrail, EventBus, SQLiteAuditStore

   trail = AuditTrail(SQLiteAuditStore("tenant-a.sqlite"), bus=EventBus())
   trail.start()
   ...
   trail.stop()
   trail.store.close()

记录
--------

``AuditRecord`` 不可变，并且可以直接转成 JSON（``to_dict()`` /
``AuditRecord.from_dict()``）。

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 字段
     - 含义
   * - ``id``
     - 唯一 ID。由事件产生的记录沿用该事件的 ID。
   * - ``timestamp``
     - 发生的时间，为带时区的 UTC ``datetime``。不含时区的时间会被拒绝。
   * - ``actor``
     - **谁**：外层 ``actor_scope`` 的 actor，或运行进程的用户。
   * - ``source``
     - 报告的组件：``pipeline``、``storage``、``scheduler``、``notify`` 等。
   * - ``pipeline``、``task``
     - 所属的管道与任务（如果有的话）。
   * - ``action``
     - **做了什么**：事件的 type（``task.failed``）或存储操作（``upload``、
       ``download``、``read``、``delete``、``mkdir``、``copy``、
       ``move``）。
   * - ``resource``
     - **哪个资源**：存储 URI 或其他对象。
   * - ``backend``
     - **哪个后端**：存储的 scheme（``s3``、``local`` 等）。
   * - ``status``
     - **结果如何**：``ok``、``warning``、``error``，或发出者自行选用的词。
   * - ``duration_ms``
     - 花费的时间（已知时）。
   * - ``error``
     - 失败时为 ``"<ExceptionType>: <message>"``。
   * - ``metadata``
     - 其余的所有信息，以 JSON 值保存。JSON 无法表示的值会保存为它的 ``repr``。
   * - ``correlation_id``
     - 所属的那次运行；在任何 ``correlation_scope`` 之外为 ``None``。

记录哪些内容
------------------------

**事件。** 总线上的每个事件都会变成一条记录。``source``、``actor``、
``timestamp`` 与 ``correlation_id`` 取自事件；``action`` 是事件的 type；
``pipeline``、``task``、``resource``、``backend``、``status``、
``duration_ms`` 与 ``error`` 取自 payload 中同名的键。事件的 ``subject``、
``severity`` 以及 payload 的其他键都放在 ``metadata`` 之下。payload 没有
``status`` 时由严重程度决定：info 为 ``ok``，warning 为 ``warning``，error 与
critical 为 ``error``。

**存储操作。** 每一次上传、下载、读取、删除、创建目录、复制与移动都会变成一条
记录：``source="storage"``，``action`` 是操作名称，``resource`` 是 URI，
``backend`` 是 scheme，无论成功还是失败。复制或移动算作一条记录，其来源位于
``metadata["source_uri"]``。

**失败的存储操作只记录一次。** 存储层会报告该操作，存储桥接器也会为它发布一个
``storage.error`` 事件。轨迹保留操作本身，跳过那个事件。

**手动记录。** ``audit_trail.record(action, **fields)`` 会追加一条记录；actor 与
关联 ID 默认取自当前的范围。

筛选条件
----------------

``search`` 与 ``count`` 接受相同的具名筛选条件；``search`` 返回的记录最新的在前。

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - 筛选条件
     - 匹配的记录
   * - ``since``、``until``
     - 时间范围：包含 ``since``，不包含 ``until``。可以是带时区的 ``datetime``、
       带有时差或 ``Z`` 的 ISO 8601 字符串，或自 epoch 起算的秒数。
   * - ``actor``、``source``、``pipeline``、``task``、``action``、
       ``backend``、``status``、``correlation_id``
     - 字段与此值完全相同。
   * - ``resource_prefix``
     - 资源以此文本开头。
   * - ``text``
     - 此文本出现在 action、resource、error、actor、source、pipeline、task、
       backend 或 metadata 的 JSON 之中。
   * - ``limit``、``offset``
     - 分页。``limit`` 默认为 100，且不得超过 10 000。``count`` 会忽略这两者。

``resource_prefix`` 与 ``text`` 会把文本当成字面值（``%`` 与 ``_`` 都是普通
字符），并忽略 ASCII 字母的大小写。值为 ``None`` 的筛选条件不会限制搜索。未知的
筛选条件名称或类型错误的值会抛出 ``AuditException``，而不是悄悄返回所有记录。

存储接口
----------------

``AuditStore`` 是存储库要实现的接口：目前是 SQLite 存储库，日后可以是
PostgreSQL 或远程存储库。

.. code-block:: python

   from automation_file import AuditQuery, AuditRecord, AuditStore

   class MyStore(AuditStore):
       def append(self, record: AuditRecord) -> None: ...
       def search(self, **filters) -> list[AuditRecord]:
           query = AuditQuery.from_filters(filters)      # 校验过的筛选条件
           ...
       def count(self, **filters) -> int: ...
       def purge(self, older_than_seconds: float) -> int: ...
       def close(self) -> None: ...

存储库只能追加、可以在线程之间共用、``search`` 以最新的在前返回、拒绝 ``id``
已存在的记录，并且所有失败都以 ``AuditException`` 抛出。
``AuditQuery.from_filters`` 以相同的方式为每一种存储库校验筛选条件。

``SQLiteAuditStore(path)`` 把记录保存在一张表中，另有一张表记载模式版本
（``2``），并在时间戳、关联 ID、资源与 action 上建立索引。所有的值都以绑定参数
传给 SQLite，筛选条件中的 ``LIKE`` 通配符也会被转义。所有线程通过一把锁共用同一条
连接，并使用 WAL 模式，因此另一个进程可以在这个进程写入时读取。
``MemoryAuditStore()`` 把记录保存在进程内，供测试使用。

从 v1 迁移
--------------------

.. code-block:: python

   from automation_file import SQLiteAuditStore

   store = SQLiteAuditStore("audit.sqlite")
   store.import_v1("old-audit.sqlite3")      # 返回新增的行数

每一条 v1 行都会变成一条 ``source="audit.v1"``、actor 为 ``unknown`` 的记录；
它的 payload 与 result 放在 ``metadata`` 之下。v1 数据库只会被读取，重复导入不会
新增任何记录。

动作
--------

``register_audit_ops(registry)`` 会注册四个动作；它们作用于进程级的轨迹。

.. code-block:: json

   [
     ["FA_audit_configure", {"db_path": "/var/lib/automation_file/audit.sqlite"}],
     ["FA_audit_search", {"status": "error", "since": "2026-10-01T00:00:00+00:00", "limit": 50}],
     ["FA_audit_count", {"correlation_id": "4f0c2b6e9d5a4c1f8a7b3e2d1c0f9a8b"}],
     ["FA_audit_purge", {"older_than_seconds": 7776000}]
   ]

``FA_audit_search`` 与 ``FA_audit_count`` 接受上述的筛选条件；
``FA_audit_search`` 以 ``to_dict()`` 的形式返回每一条记录。

能够清除轨迹的客户端，就能抹去自己的痕迹。除非远程客户端本来就该管理轨迹，否则在
TCP 或 HTTP 动作服务器上请传入拒绝 ``FA_audit_purge`` 与 ``FA_audit_configure`` 的
:class:`~automation_file.ActionACL`，在 MCP 服务器上则不要把它们列入
``--allowed-actions``。

出现问题时
--------------------

- **记录无法写入。** 失败会被记录到日志
  （``audit trail: cannot write the record of ...``），该条记录则被丢弃。它绝对
  不会抛进被审计的代码：磁盘已满不应该让管道停摆。请监控日志中的这一行并设置
  告警。
- **数据库无法打开。** ``configure_audit`` 与 ``SQLiteAuditStore`` 会抛出
  ``AuditException``。请在启动时打开存储库，才能立刻发现问题。
- **数据库是由较新的版本写入的。** 存储库会拒绝打开，而不是猜测它的结构。
- **持久性。** SQLite 存储库每写入一条记录就提交一次。在 WAL 模式下，进程崩溃
  不会丢失任何数据；断电则可能丢失最后一小段时间的记录。请把数据库放在本地
  磁盘：WAL 无法在网络共享盘上工作。
- **增长。** 没有任何记录会自动删除。请按照保留期限，定期调用 ``purge`` 或
  ``FA_audit_purge``。
- **尚未配置就搜索。** 没有配置存储库时，``audit_search`` 会抛出
  ``AuditException``，因此空的结果永远代表“没有匹配的记录”。
- **线程。** 范围不会自动跟着工作进入另一个线程；把工作分派出去的代码要在那里
  重新进入 ``correlation_scope`` 与 ``actor_scope``，否则它的记录不会带有关联
  ID。
- **机密。** payload 会原样保存。请不要把凭据放进事件的 payload 或 ``metadata``。

运维指标
----------------

同一批事件与存储操作也会送入 Prometheus 计数器，与每个动作的指标
``automation_file_actions_total``、``automation_file_action_duration_seconds``
并列：

.. code-block:: python

   from automation_file import install_operational_metrics, start_metrics_server

   install_operational_metrics()        # 一次即可；重复调用不会有任何改变
   start_metrics_server(host="127.0.0.1", port=9945)

.. list-table::
   :header-rows: 1
   :widths: 62 38

   * - 指标
     - 标签
   * - ``automation_file_events_total``
     - ``type``、``severity``
   * - ``automation_file_notifications_total``
     - ``sink``、``outcome`` （``sent``、``dedup``、``rate_limited``、
       ``error``）
   * - ``automation_file_storage_operations_total``
     - ``operation``、``backend``、``status``
   * - ``automation_file_storage_operation_duration_seconds`` （直方图）
     - ``operation``、``backend``

``install_operational_metrics()`` 会订阅事件总线与存储观察者。通知计数器不需要
安装：通知管理器与路由器会自行统计每一次投递。标签绝对不会带有路径、URI 或关联
ID，而且每个标签最多保留 100 个不同的值；超出的值会计入 ``other``。
