文件完整性监控
==============

``automation_file.integrity`` 只回答一个关于目录树的问题：它是否仍然是当初批准的
样子？:class:`~automation_file.integrity.monitor.IntegrityMonitor` 把批准的状态记录
为 *基线*\ （baseline），拿目录树与它比较，并把每一处差异报告为六种变更之一。

它通过\ :doc:`存储层 <storage>`\ 读取，所以目录树与基线都是存储 URI，可以放在任何
后端。偏移（drift）会以事件的形式发布（见 :doc:`event_bus`）；监控器本身绝不调用通知
接收端。除非你传入补救策略，否则它只会读取。

``IntegrityMonitor`` 仍然可以从 ``automation_file`` 与 ``automation_file.core.fim``
导入，为第一代监控器写的调用方式也照常工作（见 `第一代监控器`_）。

最小示例
--------

.. code-block:: python

   from automation_file.integrity import IntegrityMonitor

   monitor = IntegrityMonitor("/srv/site", baseline="/var/lib/fa/site.baseline.json")
   monitor.create_baseline()                 # 批准当前的内容

   report = monitor.verify()                 # 对每个文件计算哈希，与基线比较
   if not report.ok:
       print(report.counts)                  # {'created': 0, 'modified': 1, 'deleted': 0, ...}
       for change in report.changes:
           print(change.kind.value, change.path)
       monitor.accept(report)                # 审查之后：批准这份报告所看到的状态

生产环境示例
------------

基线放在它所描述的 bucket 之外，监控器在线程上验证，事件被转发到通知接收端，补救则
显式开启。

.. code-block:: python

   import json

   from automation_file import Severity, SlackSink, event_bus, notification_manager, s3_instance
   from automation_file.integrity import IntegrityMonitor, RemediationPolicy

   s3_instance.later_init(region_name="eu-west-1")
   notification_manager.register(SlackSink(slack_webhook_url))

   def route(event):
       level = "error" if event.severity.at_least(Severity.ERROR) else "warning"
       details = event.payload.get("error") or json.dumps(event.payload.get("counts", {}))
       notification_manager.notify(event.subject, details, level)

   # integrity.violation 与 integrity.remediated；补救成功的事件是 "info"。
   event_bus.subscribe(route, types="integrity.*", min_severity=Severity.WARNING)

   monitor = IntegrityMonitor(
       "s3://reports/2026",
       baseline="local:///var/lib/fa/baselines/reports-2026.json",
       algorithm="sha256",
       interval=900,                                   # 持续模式：每 15 分钟一次
       remediation=RemediationPolicy(                  # 需显式开启；不传就不会更改任何东西
           quarantine="s3://reports-quarantine/2026",
           restore_from="s3://reports-mirror/2026",
           on_created="quarantine",
           on_modified="restore",
           on_deleted="restore",
       ),
   )
   if not monitor.has_baseline():
       monitor.create_baseline()

   monitor.start()                                     # 守护线程；立即返回
   ...
   monitor.status()                                    # running、last_run、last_error、last_report
   monitor.stop()

请把基线放在“能改动目录树的人改不到”的地方。把基线放在目标之内也能工作，监控器会
把那个文件排除在快照之外，但这样一来同一份写入权限就同时覆盖两者。

四种模式
--------

.. list-table::
   :header-rows: 1
   :widths: 16 30 54

   * - 模式
     - 调用
     - 作用
   * - snapshot（快照）
     - ``monitor.snapshot()``
     - 读取目录树并返回
       :class:`~automation_file.integrity.snapshot.Snapshot`。不存储任何东西，
       也不需要基线。
   * - verify（验证）
     - ``monitor.verify(deep=True)``
     - 拿目录树与基线比较一次，返回
       :class:`~automation_file.integrity.report.DriftReport`。
   * - watch（监视）
     - ``monitor.watch()``
     - 在变更发生时即时响应，返回带有 ``stop()`` 的句柄。本地目标通过文件系统事件
       观察：在 ``debounce`` 秒（默认 0.5）之内变更的路径会一起验证，而且只读取这些
       路径。其他后端则每隔 ``poll_interval`` 秒以快速验证轮询一次。偏移在出现时
       报告一次，保持不变期间不会重复报告。
   * - continuous（持续）
     - ``monitor.start()`` / ``monitor.stop()``
     - 在守护线程上每隔 ``interval`` 秒（默认 60）验证一次；第一次验证在经过一个
       间隔之后执行。每一次发现偏移的验证都会发布一个事件。

``monitor.create_baseline()`` 把快照存为基线，``monitor.accept(report)`` 则批准
一次偏移。传入报告时，``accept`` 存下的正是那次验证所看到的目录树，因此报告之后才
发生的变更不会在没人看过的情况下被批准；不传报告时则重新读取目录树。

``monitor.verify_paths(["a.txt", "config"])`` 只验证这些路径（目录代表其下的所有
文件），并把报告标记为 ``partial``。监视模式就是对变更的路径执行它；当有其他来源
（例如 bucket 通知）告诉你哪些东西变了，也可以自己调用。

监视模式启动时不会先验证整棵目录树，而且操作系统的事件队列溢出时会悄悄丢弃事件。
监视模式缩短的是检测所需的时间；真正能证明目录树完好的，仍然是定期的深度验证。

深度验证与快速验证
------------------

``verify(deep=True)`` 会对每一个文件计算哈希。在远程后端上，这意味着要读取每一个
文件。

``verify(deep=False)`` 会先拿每个文件的大小、修改时间与 etag 与基线比较，只对其中
任何一项不同的文件计算哈希。报告会说明这一点：``report.deep`` 为 ``False``，
``report.hashed`` 是 ``report.checked`` 个文件中实际被读取的数量，``report.notes``
则包含 ``"quick pass: 2 of 1840 files hashed; size, modification time and etag
decided the rest"``。三项都没变的变更，快速验证察觉不到，所以也请安排深度验证。
基线条目若既没有记录时间也没有记录 etag（旧格式），一律会被计算哈希。

报告包含 ``changes``、``counts``\ （每种变更一个数字，包含零）、``ok``、``deep``、
``partial``、``checked``、``hashed``、``notes``、``remediation``、``verified_at``
与 ``correlation_id``。``report.to_dict()`` 的结果可直接序列化为 JSON。

Manifest 格式
-------------

基线是一份带有结构版本的 JSON 文档，称为 *manifest*：

.. code-block:: json

   {
     "schema_version": 2,
     "created_at": "2026-10-08T10:15:30.123456+00:00",
     "root": "s3://reports/2026",
     "backend": "s3",
     "algorithm": "sha256",
     "entries": [
       {
         "path": "q1.csv",
         "size": 1024,
         "modified_at": "2026-10-01T08:00:00+00:00",
         "checksum": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
         "algorithm": "sha256",
         "content_type": "text/csv",
         "backend": "s3",
         "version": null,
         "etag": "5d41402abc4b2a76b9719d911017c592",
         "mode": null
       }
     ]
   }

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 字段
     - 含义
   * - ``schema_version``
     - ``2``。其他数字一律以 ``IntegrityException`` 拒绝，因此较新版本写出的文档绝
       不会被一知半解地读取。
   * - ``created_at``
     - 快照的创建时间，UTC 的 ISO 8601 格式。
   * - ``root``、``backend``
     - 目录树的 URI，以及提供它的后端的 scheme。
   * - ``algorithm``
     - 所有校验码使用的哈希算法。验证时就用它来计算哈希。
   * - ``entries``
     - 每个文件一个对象，按 ``path`` 排序（相对于 ``root``，以 ``/`` 分隔）。目录
       不会被记录，因此空目录是看不见的。
   * - ``size``、``modified_at``、``content_type``、``version``、``etag``
     - 后端报告的内容。后端无法提供的字段为 ``null``。
   * - ``mode``
     - 以整数表示的权限位（``420`` 即 ``0o644``）。只有本地文件系统上的文件才会
       记录。

``write_manifest`` / ``FA_write_manifest`` 写出的 manifest（没有
``schema_version``，以 ``files`` 映射记录 ``size`` 与 ``checksum``）同样可以读取，
并在读取时转换。``create_baseline()`` 与 ``accept()`` 一律写出第 2 版；之后
``verify_manifest`` 会以 ``ManifestException`` 拒绝该文件，并在消息中指出
``FA_integrity_verify``。

基线管理器会先把 manifest 写到同目录的临时文件，再把它移过去取代基线，所以读取方永远
不会看到写到一半的文档。这个移动在本地文件系统上是重命名，在其他后端则是把完成的
文件整个写入一次。

变更种类
--------

.. list-table::
   :header-rows: 1
   :widths: 24 60 16

   * - 种类
     - 报告时机
     - 严重程度
   * - ``created``
     - 基线中没有的路径。
     - warning
   * - ``modified``
     - 校验码或记录的大小不同。
     - error
   * - ``deleted``
     - 基线中的路径不见了。
     - error
   * - ``renamed``
     - 一个被删除的文件与一个新创建的文件有相同的校验码与大小。
       ``change.previous_path`` 是旧路径。
     - error
   * - ``metadata_changed``
     - 校验码相同，但修改时间、内容类型、版本或 etag 不同；``change.fields`` 会
       指出是哪些。任何一边没有记录的字段不会被比较。
     - warning
   * - ``permission_changed``
     - 权限位不同。两者都发生时，会与 ``modified`` 一并报告。
     - error

当多个被删除或多个新创建的文件共用同一个校验码时，配对就有歧义。此时它们会被报告为
``deleted`` 与 ``created``，各自的 ``change.note`` 会设为 ``"ambiguous rename: 2
deleted and 1 created files share the checksum 9f86d081884c...; reported
separately"``。

事件
----

每一次发现偏移的验证都会在 ``event_bus``\ （或以 ``bus=`` 传入的事件总线）上发布
一个 :class:`~automation_file.events.model.IntegrityViolation`。验证在关联范围
（correlation scope）内执行，所以这个事件、补救事件与 ``report.correlation_id`` 共用
同一个 ID；若外层已有范围，则沿用外层的 ID。

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - 字段
     - 值
   * - ``type``、``source``
     - ``integrity.violation``、``integrity``
   * - ``severity``
     - 所发现的变更种类中最严重的一级：有东西被修改、删除、重命名或权限被更改时
       为 ``error``；只有新增或元数据变更时为 ``warning``。
   * - ``payload["resource"]``、``["backend"]``
     - 目标的 URI 与它的后端。
   * - ``payload["status"]``
     - ``drift``；验证无法执行时为 ``error``\ （此时 ``payload["error"]`` 说明原因）。
   * - ``payload["counts"]``
     - 每种变更的数量。
   * - ``payload["changes"]``
     - 前 20 条变更，格式为 ``{"kind": ..., "path": ...}``；``total`` 是实际数量，
       ``truncated`` 表示是否有省略。
   * - ``payload["baseline"]``、``["algorithm"]``、``["deep"]``、``["partial"]``
     - 这次验证比较的对象，以及它有多彻底。

传入 ``alerts=AlertPolicy(severities={"created": "error"}, max_changes=50)`` 可以
改变某种变更的严重程度，或事件中列出的变更数量。

``verify()`` 无法执行时会抛出异常。持续模式、监视模式与 ``check_once()`` 没有对象
可以抛出：它们会发布同一种事件并带有 ``status: "error"``，把原因留在
``monitor.last_error``，然后继续执行。

补救
----

默认关闭。除非把 :class:`~automation_file.integrity.remediation.RemediationPolicy`
传给监控器，否则不会移动或复制任何东西；而所有动作都保持 ``"none"`` 的策略同样什么
都不做。

.. code-block:: python

   RemediationPolicy(
       quarantine="s3://reports-quarantine/2026",   # 或 None
       restore_from="s3://reports-mirror/2026",     # 或 None；基线的镜像
       on_created="quarantine",                     # "none" | "quarantine"
       on_modified="restore",                       # "none" | "quarantine" | "restore"
       on_deleted="restore",                        # "none" | "restore"
   )

``quarantine``\ （隔离）
    把有问题的文件移到 ``<quarantine>/<UTC 时间戳>/<path>``。同一次验证的所有文件
    共用一个时间戳目录，而且隔离区中的任何东西都不会被覆盖。

``restore``\ （还原）
    从 ``restore_from`` 把文件复制回来。镜像中的副本会先被计算哈希，与基线不符就
    拒绝，因此过期或被篡改的镜像绝不会被复制到原位；还原后的文件会再计算一次哈希，
    通过之后这个步骤才算完成。若配置了隔离区，被修改的文件会先移进隔离区；没有
    隔离区时，它的内容会被覆盖。

重命名会拆成两半处理：旧路径视为被删除，新路径视为新创建。元数据与权限的变更绝不会
被补救。隔离区与镜像都必须位于目标之外。

每个步骤都会记录在 ``report.remediation``\ （``action``、``path``、``kind``、
``ok``、``source``、``destination``、``error``），并以类型为
``integrity.remediated`` 的 ``IntegrityRemediated`` 事件发布：成功时为 ``info``，
失败时为 ``error``。失败的步骤只会被报告，绝不会抛出异常；文件保持原状。报告描述的
是补救之前的目录树，因此执行过补救步骤时，``accept(report)`` 会重新读取目录树。

还原后的文件有新的修改时间，下一次验证会把它报告为 ``metadata_changed``，直到基线被
批准为止。

算法
----

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 算法
     - 用途
   * - ``sha256``
     - 默认值。
   * - ``sha512``、``blake2b``
     - 强度至少相同的替代选择。
   * - ``md5``、``sha1``
     - 除非传入 ``allow_weak=True``，否则一律拒绝。两者都有实际可行的碰撞：文件可以
       被换成另一个摘要相同的文件，而这个变更不会被察觉。保留它们只是为了继续读取
       当初以它们写出的基线，绝不会作为默认值。

``algorithm=`` 是 ``snapshot()`` 与 ``create_baseline()`` 使用的哈希算法。验证一律
使用所读取基线的算法，``accept()`` 也会沿用它。要把基线换成另一种算法，请先审查
目录树，再用以新算法创建的监控器调用 ``create_baseline()``。

文件通过存储层的 ``checksum``，在线程池上并行计算哈希（默认 ``max_workers=8``）。

动作
----

.. list-table::
   :header-rows: 1
   :widths: 30 36 34

   * - 动作
     - 参数
     - 返回值
   * - ``FA_integrity_snapshot``
     - ``target, algorithm="sha256"``
     - 快照：``root``、``backend``、``algorithm``、``created_at``、``entries``
   * - ``FA_integrity_baseline``
     - ``target, baseline, algorithm="sha256"``
     - ``target``、``baseline``、``backend``、``algorithm``、``created_at`` 以及
       ``entries`` 的数量
   * - ``FA_integrity_verify``
     - ``target, baseline, deep=True``
     - 偏移报告
   * - ``FA_integrity_accept``
     - ``target, baseline``
     - 与 ``FA_integrity_baseline`` 相同
   * - ``FA_integrity_watch_start``
     - ``name, target, baseline, interval=60.0``
     - 新监控器的状态
   * - ``FA_integrity_watch_stop``
     - ``name``
     - 它最后的状态
   * - ``FA_integrity_status``
     - ``name=None``
     - 状态的列表：单个监控器，或全部

``FA_integrity_watch_start`` 让一个具名的监控器保持在持续模式，直到
``FA_integrity_watch_stop``；基线必须先存在。状态包含 ``name``、``target``、
``baseline``、``algorithm``、``interval``、``running``、``last_run``、
``last_error`` 与 ``last_report``。

.. code-block:: json

   [
     ["FA_integrity_baseline", {"target": "s3://reports/2026",
                                "baseline": "local:///var/lib/fa/reports-2026.json"}],
     ["FA_integrity_verify", {"target": "s3://reports/2026",
                              "baseline": "local:///var/lib/fa/reports-2026.json",
                              "deep": false}],
     ["FA_integrity_watch_start", {"name": "reports", "target": "s3://reports/2026",
                                   "baseline": "local:///var/lib/fa/reports-2026.json",
                                   "interval": 900}],
     ["FA_integrity_status", {"name": "reports"}]
   ]

这些动作会把偏移发布到整个进程共用的 ``event_bus``。它们不接受弱算法，也不接受
补救策略：这两者都只能在 Python 中选用。与存储动作一样，它们能访问进程所能访问的
一切，而且 ``FA_integrity_baseline`` 与 ``FA_integrity_accept`` 会写入文件，因此在
TCP 或 HTTP 动作服务器上请传入 ``ActionACL``，在 MCP 服务器上请使用
``--allowed-actions``，只开放客户端需要的动作。
``register_integrity_ops(registry)`` 可把它们加入你自己的注册表。

第一代监控器
------------

为第一代 ``IntegrityMonitor`` 写的代码照常工作：

.. code-block:: python

   from automation_file import IntegrityMonitor, notification_manager, write_manifest

   write_manifest("/srv/site", "/srv/MANIFEST.json")
   monitor = IntegrityMonitor(
       "/srv/site",                 # 仍然接受 root= 与 manifest_path= 这两个关键字
       "/srv/MANIFEST.json",
       interval=60.0,
       manager=notification_manager,
       on_drift=lambda summary: print("drift:", summary),
   )
   summary = monitor.check_once()   # {"matched": [...], "missing": [...], "modified": [...],
                                    #  "extra": [...], "ok": False}
   monitor.start()

``check_once()`` 返回同样的摘要字典，验证无法执行时会带有 ``error``；``on_drift``
会收到它，``last_summary`` 会保留它。与以往一样，除非 ``alert_on_extra=True``，否则
新增的文件对 ``on_drift`` 与通知而言不算偏移，而重命名会以 ``missing`` 加上
``extra`` 的形式出现。

通知的去向与以往相同：通过你传入的 ``manager`` 发送，没有传入时则使用整个进程共用的
``notification_manager``。新增的只有一点：每一次偏移（包含新增）也都会以
``IntegrityViolation`` 事件的形式发布。通知路由器启用期间（见 :doc:`notifications`），
这个事件由路由负责送达，不再直接通知进程共用的管理器，同一次偏移因此不会被通知两次；
你自己传入的 ``manager`` 则一律会收到通知。``notify=False`` 会完全关闭这项直接通知。

出现问题时
----------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - 你看到的现象
     - 它的含义与处理方式
   * - ``IntegrityException: no baseline at …``
     - 基线 URI 上没有任何东西。请检查 URI，然后调用 ``create_baseline()``。运行中
       的监控器的基线消失，本身就是一项发现：它会以带有 ``status: "error"`` 的事件
       送达。
   * - ``… is not readable JSON`` / ``… is not a valid manifest``
     - 基线已损坏或被编辑过。请从副本还原，或审查目录树之后重新创建。不要批准一棵
       你无从比较的目录树。
   * - ``… has manifest schema version 3``
     - 基线是由较新的版本写出的。请升级，或用当前的版本重新创建基线。
   * - ``md5 is refused for integrity checks …``
     - 基线使用了弱算法。传入 ``allow_weak=True`` 以便读取，再以 ``sha256`` 调用
       ``create_baseline()``。
   * - ``target … does not exist``
     - 文件系统上的目录不见了。在对象存储上，什么都没有的前缀则是一棵空的目录树：
       每个文件都是 ``deleted``。
   * - ``StorageUnavailableException``
     - 后端尚未初始化：请先调用 ``s3_instance.later_init(...)`` 或对应的函数。
   * - 验证过程中出现 ``StoragePermissionException`` 或
       ``StorageTransientException``
     - 整次验证失败；无法完整读取的目录树绝不会被报告为完好。持续模式会在
       ``interval`` 之后再试一次。
   * - 快速验证没问题，深度验证却报告 ``modified``
     - 内容变了，大小与修改时间却没变。一般工具不会这样做；请视为篡改。
   * - 所有文件都是 ``metadata_changed``
     - 文件被复制或还原过，因而有了新的时间。审查之后调用 ``accept()``。
   * - 补救步骤的 ``ok`` 为 ``False``
     - ``step.error`` 说明原因（镜像中没有副本、镜像与基线不符、访问被拒）。文件
       保持原状；并已发布严重程度为 ``error`` 的 ``integrity.remediated`` 事件。
   * - 每个间隔都收到同一个事件
     - 只要偏移还在，持续模式每次验证都会报告。请修正目录树或调用 ``accept()``，
       或在订阅方去除重复（``NotificationManager`` 会这么做）。
   * - 监视模式漏掉了某个变更
     - 文件系统事件可能丢失。请在监视之外，另外定期执行深度的 ``verify()``。

一个监控器一次只执行一次验证：在持续模式的线程正在验证时调用 ``verify()``，会等它
完成。
