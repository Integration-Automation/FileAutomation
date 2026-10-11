应用层
======

``automation_file.app`` 是用户界面所调用的那一层。导航中的每个条目各有一个服务——
Dashboard、Files、Storage、Pipelines、Scheduler、Integrity、Audit、Notifications、
Settings——每个都是建立在领域包（:doc:`storage`、:doc:`pipeline`、:doc:`events`、
:doc:`integrity`、:doc:`audit`、:doc:`notifications`、:doc:`event_bus`、
:doc:`config`）之上的普通 Python 对象。

PySide6 窗口（:doc:`gui`）与 Web UI（:doc:`servers`）只调用这些服务，不碰它们之下的
任何东西。这就是两者显示相同状态的原因，也是第三种界面——终端 UI、Web 应用、聊天
机器人——同样不需要了解领域包的原因。

这一层遵守四个承诺：

* 不导入任何 GUI 工具包，也不导入任何后端 SDK。``import automation_file.app`` 在
  基础安装上就能工作。
* 返回 JSON 能容纳的 dataclass、字典与列表。
* 在返回的内容中屏蔽 token、密码与 webhook URL。
* 抛出 ``FileAutomationException`` 的子类：领域自己的（``StorageException``、
  ``PipelineException``……），以及只有这一层才检查的情况所用的 ``AppException``。

最小示例
----------------

.. code-block:: python

   from automation_file.app import app_services

   services = app_services()                       # 每个进程一组

   summary = services.dashboard.summary()
   print(summary.status, summary.reasons)          # "ok" () 或 "attention" (...)

   for entry in services.files.list_dir("local:///data"):
       print(entry.name, entry.size)

   draft = services.pipelines.new_draft("nightly")
   draft.add_task("FA_storage_copy", "download",
                  arguments={"source": "s3://in/a.csv", "target": "local:///tmp/a.csv"})
   run = services.pipelines.start(draft)           # 立即返回
   services.pipelines.wait(run["run_id"], timeout=60)
   print(services.pipelines.status(run["run_id"])["status"])

服务一览
----------------

``automation_file.app.NAVIGATION`` 是九个条目按显示顺序排列的 tuple；
``AppServices`` 为每个条目各有一个属性，名称为小写。

.. list-table::
   :header-rows: 1
   :widths: 18 24 58

   * - 条目
     - 属性与类
     - 用途
   * - Dashboard
     - ``dashboard``、``DashboardService``
     - 一份摘要：健康状态、运行、完整性漂移、最近的事件、存储状态。
   * - Files
     - ``files``、``FileService``
     - 对存储 URI 进行列出、stat、预览、复制、移动、删除、mkdir。
   * - Storage
     - ``storage``、``StorageService``
     - Scheme、挂载点，以及每个后端能不能用。
   * - Pipelines
     - ``pipelines``、``PipelineService``
     - 草稿、验证、试运行、后台运行、状态、历史、续跑、取消、定义文件。
   * - Scheduler
     - ``scheduler``、``SchedulerService``
     - 列出、添加与移除 cron 作业。
   * - Integrity
     - ``integrity``、``IntegrityService``
     - 基线、验证、接受、状态、启动与停止监控器。
   * - Audit
     - ``audit``、``AuditService``
     - 配置、搜索与统计审计记录。
   * - Notifications
     - ``notifications``、``NotificationService``
     - 已注册的 sink、路由、测试消息。
   * - Settings
     - ``settings``、``SettingsService``
     - 加载并应用配置文件；哪些 extra 已安装。

Dashboard
---------

.. code-block:: python

   summary = services.dashboard.summary()
   summary.to_dict()                    # 可序列化成 JSON

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 字段
     - 含义
   * - ``status``、``reasons``
     - ``"ok"``，或是 ``"attention"`` 并为每个原因附上一句话：最近有运行失败、某个
       监控器发现漂移或无法验证、总线上有严重程度为 ``error`` 及以上的近期事件。
   * - ``health``
     - 计数与开关：已注册的动作、运行中的运行、调度作业、监控器、sink、路由、路由器
       是否启用、审计轨迹的状态。
   * - ``run_counts``
     - 最新五十次运行的结局：``running``、``succeeded``、``failed``、
       ``cancelled``。
   * - ``running_runs``、``recent_runs``
     - 不含任务细节的运行，新的在前。
   * - ``integrity``
     - 每个具名监控器上次发现了什么。
   * - ``events``
     - 总线上最新的事件，新的在前，已屏蔽。
   * - ``storage``
     - 每个后端，附 ``usable``、``detail``，以及缺少包时的 ``install_hint``。

各部分也可以分开获取：``health()``、``runs()``、``integrity()``、
``recent_events()``、``storage_status()``。``summary()`` 绝不会因为某个部分读不到而
抛出异常；它会把那个部分列在原因里。

Files
-----

.. code-block:: python

   files = services.files
   files.list_dir("s3://reports/2026")              # 目录在前，其次按路径
   files.stat("s3://reports/2026/q1.csv").size
   preview = files.preview("s3://reports/2026/q1.csv", max_bytes=4096)
   preview.text, preview.truncated, preview.binary
   files.copy("s3://reports/2026/q1.csv", "local:///backup/")   # 放进该目录
   files.move("local:///inbox/a.csv", "local:///done/a.csv")
   files.mkdir("local:///backup/2026")
   files.delete("local:///backup/2026", recursive=True)

预览有两道上限。最多返回 ``preview_bytes``\ （64 KiB），而大于 ``fetch_limit``\
（16 MiB）的远程文件不会被获取：不支持范围读取的后端必须先把整个文件下载下来，才读得
到其中任何一部分。两个上限都是 ``FileService`` 的参数。二进制内容会以十六进制转储
返回，并设置 ``binary``。

目录会连同其下的一切一起复制，而且不能移动。每个 URI 都经过存储层，所以 ``..`` 与
URI 中的凭据都会被拒绝。

Storage
-------

.. code-block:: python

   storage = services.storage
   for backend in storage.backends():
       print(backend.name, backend.kind, backend.usable, backend.detail)
   storage.mount_local("sandbox://jobs", "/srv/jobs")     # 限制在那个目录内
   storage.mounts()
   storage.capabilities("sandbox://jobs")
   storage.unmount("sandbox://jobs")

``backends()`` 为每个 scheme、每个挂载点，以及每个没有 scheme 的共享 client 各返回
一个 ``BackendStatus``。本地与内存后端、挂载点，以及 client 已初始化的云端后端，
``usable`` 为真。否则 ``detail`` 会说明如何初始化；若该 extra 的包没有安装，则带有
``pip install`` 命令（也在 ``install_hint`` 中）。这里不会打开任何连接。

Pipelines
---------

草稿
~~~~

流水线编辑器无法编辑 ``Pipeline``：那个对象拒绝任何无效的内容，而构建中的定义大部分
时间都是无效的。``PipelineDraft`` 保存到目前为止输入的一切。

.. code-block:: python

   from automation_file.app import PipelineDraft

   draft = PipelineDraft("daily-report")
   draft.set_params({"date": "2026-10-08"})
   draft.add_task("FA_storage_copy", "download",
                  arguments={"source": "s3://in/${params.date}.csv",
                             "target": "local:///tmp/report.csv"})
   draft.add_task("FA_storage_delete", "tidy", arguments={"uri": "local:///tmp/report.csv"})
   draft.connect("download", "tidy")               # tidy 依赖 download
   draft.set_retry("download", max_attempts=5, backoff=2.0, on=["ConnectionError"])
   draft.set_timeout("download", 300)
   draft.set_condition("tidy", "always")
   draft.rename_task("tidy", "clean-up")            # 边与占位符会跟着改

   draft.problems()                                 # [] 或 Problem(path, message, task)
   draft.to_definition()                            # Pipeline.from_dict 所接受的文档

.. list-table::
   :header-rows: 1
   :widths: 36 64

   * - 方法
     - 效果
   * - ``add_task``、``remove_task``、``rename_task``
     - 改变任务集合。没有指定 ID 时，会由动作名称推导。
   * - ``set_action``、``set_arguments``
     - 动作，以及它的关键字映射、位置列表或 ``None``。
   * - ``set_retry``、``set_timeout``、``set_condition``、``set_idempotency_key``
     - 任务如何运行。
   * - ``connect``、``disconnect``、``set_dependencies``、``edges``
     - 依赖边。指向自己的边，或会形成环的边，会以 ``AppException`` 拒绝。
   * - ``set_position``、``positions``、``auto_layout``、``layout``、``apply_layout``
     - 每个任务在画布上的位置。这是编辑器的元数据：绝不会出现在
       ``to_definition()`` 中。
   * - ``set_name``、``set_description``、``set_max_workers``、``set_params``、``set_schedule``
     - 定义的头部。
   * - ``add_listener``、``batch``
     - 每次变更后都会调用 ``listener(change)``，其值为 ``"structure"``、
       ``"task"``、``"header"`` 或 ``"position"``；在 ``with draft.batch():``
       之内，每一种只在结束时报告一次。
   * - ``problems``、``to_definition``、``from_definition``
     - 附上每个问题路径的验证，以及定义文档。

运行时会拒绝的值（负的超时、未知的动作名称）会被保留下来，并由 ``problems()`` 报告；
只有会让草稿不一致的编辑（重复的 ID、环）才会立刻抛出异常。草稿不是线程安全的：请只
从一个线程编辑它，交给 worker 的则是 ``draft.to_definition()``。

检查与运行
~~~~~~~~~~~~

每个方法都接受草稿或定义映射，并返回普通的字典。一次运行就是
``PipelineRun.to_dict()``，其中的机密信息已屏蔽，另外加上 ``active`` 标志，说明这个
进程是否仍在执行它。

.. code-block:: python

   pipelines = services.pipelines

   pipelines.action_names()                         # 给动作列表用
   pipelines.describe_action("FA_storage_copy")     # 参数、默认值、摘要

   pipelines.validate(draft)                        # 也包括：未知的动作名称
   plan = pipelines.dry_run(draft, {"date": "2026-10-09"})
   outcome = pipelines.test_task(draft, "download", {"date": "2026-10-09"})

   run = pipelines.start(draft, {"date": "2026-10-09"})     # 后台运行
   followed = pipelines.follow(run["run_id"])       # {"run": ..., "events": [...]}
   pipelines.cancel(run["run_id"])
   pipelines.wait(run["run_id"], timeout=30)

   pipelines.resume(run["run_id"], draft)           # 保留已成功的，运行其余的
   pipelines.retry(run["run_id"], draft)            # 新的一次运行，参数相同
   pipelines.history("daily-report", limit=10)
   pipelines.running()

``start`` 与 ``resume`` 立即返回；定义有问题时，会在任何东西运行之前抛出异常。
``test_task`` 单独执行一个任务：它的动作会真的执行，它的上游任务则换成替身，返回
``results=`` 中给的值（默认为 ``None``），而且这次测试不会记录到任何 run store，也
不会发布到共享的总线。

定义文件与布局
~~~~~~~~~~~~~~

.. code-block:: python

   draft = pipelines.load("pipelines/daily-report.yaml")
   draft.load_notes                                 # 文件有什么问题（如果有的话）
   pipelines.save(draft, "pipelines/daily-report.yaml")

``save`` 把定义写成 ``.yaml``、``.yml`` 或 ``.json``，并把画布布局写进旁边的
``<file>.layout.json``。定义会拒绝未知的键，而布局不属于会被运行的内容，所以两者绝
不共用一个文件。``load`` 会打开能解析但无效的文件，让它可以被修好。

Scheduler
---------

.. code-block:: python

   scheduler = services.scheduler
   scheduler.add("nightly", "0 2 * * *",
                 [["FA_pipeline_run", {"definition": "pipelines/daily-report.yaml"}]])
   scheduler.jobs()
   scheduler.remove("nightly")
   scheduler.remove_all()

``add`` 也接受 JSON 文本形式的动作列表，也就是表单提供的形式。这个服务只调用
``schedule_add``、``schedule_remove``、``schedule_remove_all`` 与
``schedule_list``\ （:doc:`events`）。

Integrity
---------

.. code-block:: python

   integrity = services.integrity
   integrity.baseline("s3://reports/2026", "local:///var/lib/fa/reports.json")
   report = integrity.verify("s3://reports/2026", "local:///var/lib/fa/reports.json")
   report["ok"], report["counts"], report["changes"]
   integrity.accept("s3://reports/2026", "local:///var/lib/fa/reports.json")

   integrity.start_monitor("reports", "s3://reports/2026",
                           "local:///var/lib/fa/reports.json", interval=300)
   integrity.drift()                    # 每个监控器一个 MonitorDrift，给仪表板用
   integrity.stop_monitor("reports")
   integrity.stop_started()             # 这个服务启动的监控器

在这里启动的监控器，就是 ``FA_integrity_*`` 动作看到的那个具名监控器。

Audit
-----

.. code-block:: python

   audit = services.audit
   audit.status()                       # 取得 store 之前为 {"configured": False, ...}
   audit.configure("/var/lib/automation_file/audit.sqlite")
   audit.search(status="error", resource_prefix="s3://reports/", limit=20)
   audit.count(actor="scheduler")
   audit.recent(limit=30)               # 尚未配置审计时为 []

以 ``None`` 或空字符串给定的筛选条件不会限制搜索，所以表单的值可以原样传入。

Notifications
-------------

.. code-block:: python

   notifications = services.notifications
   notifications.sinks()                # 名称、类型、送达位置；绝不含机密信息
   notifications.add_route({"name": "failures", "sinks": "team-alerts, ops-mail",
                            "types": "pipeline.failed, task.failed",
                            "min_severity": "error", "dedup_seconds": "600"})
   notifications.routes()
   notifications.remove_route("failures")
   notifications.send_test("team-alerts")           # {"team-alerts": "sent"}

列表可以是以逗号分隔的文本，数字也可以是文本。路由若指名未注册的 sink 会被拒绝。
``send_test`` 为每个 sink 返回一个结果：``"sent"`` 或错误，其中的 URL 只留下主机。

Settings
--------

.. code-block:: python

   settings = services.settings
   settings.load("automation_file.toml")            # 一份摘要；不改变任何东西
   settings.apply("automation_file.toml")           # 注册 sink 与路由
   for extra in settings.extras():
       print(extra.name, extra.installed, extra.install_hint)
   settings.environment()                           # 版本、平台、日志文件

摘要包含文件的区段、sink 与路由，以及所有机密信息都已屏蔽的文档。

表单辅助函数
------------------------

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - 函数
     - 用途
   * - ``parse_argument_text(text)``
     - 把一个表单字段变成值：文本是 JSON 就当 JSON，否则就是文本本身。
   * - ``format_argument_value(value)``
     - 反方向：生成读回来会是同一个值的文本。
   * - ``parse_json_text(text, what)``
     - 从文本字段取得 JSON 文档，否则抛出 ``AppException``，指出 ``what`` 与错误的
       位置。
   * - ``split_names(text)``
     - 把 ``"a, b"`` 变成 ``["a", "b"]``。
   * - ``describe_action(name, command)``
     - 动作的参数、默认值与摘要。

机密信息
----------------

``mask_secrets(value)`` 返回可以安全显示的副本，每个服务都会把它应用在返回的内容上：

* 存放在表明自己是机密信息的名称（``password``、``token``、``api_key``、
  ``authorization``……）之下的值，会变成 ``********``；
* 存放在 ``url`` 或 ``..._url`` 之下的值，只保留 scheme 与主机；
* 在其他任何文本中，URL 的用户信息与 ``Bearer`` 后面的 token 会被移除。

存储 URI 不会被改动：它不可能带有凭据。任务的结果会原样返回，所以不要把机密信息放进
结果里。

共享与私有的服务
--------------------------------

``app_services()`` 为每个进程返回一组服务，建立在进程内的单例之上（默认的 resolver、
默认的 run store、事件总线、审计轨迹、通知管理器与路由器）。因此同一个进程中的窗口
与 Web UI 会显示相同的运行、监控器与路由。

``build_services`` 则构建自己的一组：

.. code-block:: python

   from automation_file.app import ServiceOptions, build_services
   from automation_file.events import EventBus
   from automation_file.pipeline import SQLiteRunStore

   services = build_services(ServiceOptions(
       run_store=SQLiteRunStore("/var/lib/automation/pipelines.db"),
       bus=EventBus(),
   ))

``ServiceOptions`` 接受 ``resolver``、``run_store``、``registry``、``bus``、
``audit_trail``、``notification_manager`` 与 ``notification_router``。不论选项如何，
调度器与完整性监控器都是整个进程共用的。

编写另一种用户界面
------------------------------------

1. 取得服务：``app_services()``，或 ``build_services(...)``。
2. 由 ``NAVIGATION`` 构建导航。
3. 每个视图调用一个服务方法，并渲染它返回的内容。捕获
   ``FileAutomationException`` 并显示它的文本。
4. 会碰到存储或网络的调用（``files.*``、``integrity.verify``、
   ``notifications.send_test``、``settings.apply``）请从 worker 线程进行。
   ``pipelines.start`` 与 ``pipelines.resume`` 本来就立即返回。
5. 流水线编辑器请保留一个 ``PipelineDraft``，只通过它的方法修改它，并在 listener 中
   按它重绘。

一个虽小但完整的终端界面：

.. code-block:: python

   from automation_file.app import NAVIGATION, app_services
   from automation_file.exceptions import FileAutomationException

   services = app_services()
   views = {
       "Dashboard": lambda: services.dashboard.summary().to_dict(),
       "Storage": lambda: [backend.to_dict() for backend in services.storage.backends()],
       "Pipelines": lambda: services.pipelines.history(limit=10),
       "Scheduler": services.scheduler.jobs,
       "Integrity": lambda: [drift.to_dict() for drift in services.integrity.drift()],
       "Audit": services.audit.recent,
       "Notifications": services.notifications.routes,
       "Settings": lambda: [extra.to_dict() for extra in services.settings.extras()],
   }
   for number, name in enumerate(NAVIGATION, start=1):
       print(number, name)
   chosen = NAVIGATION[int(input("> ")) - 1]
   try:
       print(views.get(chosen, lambda: "use services.files for Files")())
   except FileAutomationException as error:
       print("failed:", error)

出问题时
----------------

``AppException``
    这一层拒绝了请求：草稿无法接受的编辑、不是 JSON 的表单文本、缺少名称。消息会说明
    该改什么。

``dry_run``、``start`` 或 ``resume`` 抛出 ``PipelineDefinitionException``
    定义无效。``error.problems`` 保存每一项发现；``validate`` 会以 ``Problem`` 对象
    返回相同的内容而不抛出异常。

``status`` 抛出“unknown run”
    这次运行既不在这个服务的跟踪之中，也不在它的 run store 里。除非默认 store 是
    ``SQLiteRunStore``，或曾把它传给 ``build_services``，否则运行记录只保存在
    内存中。

``cancel`` 返回 ``False``
    这次运行不在这个进程中进行：它已经结束，或是由另一个进程启动的。

后端不是 ``usable``
    请读 ``detail``。初始化 client，或安装 ``install_hint`` 指名的 extra。

``audit.search`` 抛出“audit is not configured”
    请先调用 ``audit.configure(path)``。``audit.recent()`` 则会返回空列表。

机密信息出现在视图中
    它存放在没有表明自己是机密信息的名称之下，或者它是任务结果的一部分。请改掉字段
    名称，或不要把它放进结果。

两个界面显示的内容不一致
    它们用的是不同的服务组。``app_services()`` 是共享的；``build_services()``
    不是。
