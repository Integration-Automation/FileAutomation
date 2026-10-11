调度器（Scheduler）
========================

``automation_file.scheduler`` 会在某件事触发时执行一份动作列表或一条
:doc:`流水线 <pipeline>`\ ：可以带时区的 cron 表达式、文件事件、事件总线上的事件、
另一条流水线的运行结束，或是一次调用。cron 只是多种触发器之一，所有作业都经过同一个
调度器。

每一次触发都会留下一条记录，状态是七种之一：``scheduled``、``started``、
``completed``、``failed``、``skipped``、``timeout`` 与 ``cancelled``。除非作业自己
允许，否则它不会与自己重叠；一次运行可以设置超时，也可以被取消；失败或超时的运行会
发布成 ``scheduler.error`` 事件（见 :doc:`event_bus`）。

最小示例
----------------

.. code-block:: python

   from automation_file.scheduler import scheduler

   scheduler.add(
       "nightly-snapshot",
       "0 2 * * *",                              # 每天 02:00 ...
       [["FA_zip_dir", {"dir_we_want_to_zip": "/data",
                        "zip_name": "/backup/data_nightly"}]],
       timezone="Asia/Taipei",                   # ... 台北时间；不给就是本地时间
   )

   scheduler.history(job="nightly-snapshot", limit=5)    # 最近的运行，最新的在前

``scheduler`` 是整个进程共用的实例。加入第一个作业时会启动它的后台线程；那是
daemon 线程，进程要靠你自己保持存活。

生产环境示例
------------------------

每晚台北时间 02:00 运行一条流水线，第一条成功之后运行第二条流水线，并在某次运行失败
或跑得太久时通知团队。

.. code-block:: python

   import os

   from automation_file import Route, SlackSink, notification_manager, notification_router
   from automation_file.pipeline import SQLiteRunStore, set_default_run_store
   from automation_file.scheduler import PipelineTrigger, scheduler

   # 被调度的流水线把运行记录写进默认的运行记录存储。
   set_default_run_store(SQLiteRunStore("/var/lib/automation/pipelines.db"))

   # 失败或超时的运行是一个 scheduler.error 事件；这条路由负责投递它。
   notification_manager.register(SlackSink(os.environ["SLACK_WEBHOOK"], name="team-alerts"))
   notification_router.add_route(
       Route("scheduler-failures", sinks=("team-alerts",), types=("scheduler.error",))
   )
   notification_router.start()

   # daily-report.yaml 声明了   schedule: {cron: "0 2 * * *", timezone: Asia/Taipei}
   scheduler.add_pipeline(
       "pipelines/daily-report.yaml",
       params={"date": "${date:%Y-%m-%d}"},      # 作业触发当时的台北日期
       timeout=3600,                             # 一小时后取消
   )

   # 没有自己的调度：每当 daily-report 的一次运行成功，它就会运行。
   scheduler.add_pipeline(
       "pipelines/publish-summary.yaml",
       triggers=PipelineTrigger("daily-report"),
       timeout=900,
   )

   for run in scheduler.history(state="failed", limit=10):
       print(run.job, run.scheduled_at, run.error, run.correlation_id)

``daily-report`` 在 UTC 18:00 启动，也就是台北的 02:00，``date`` 则是台北的日期。它的
运行以 ``succeeded`` 结束时，``publish-summary`` 会被触发；它失败时，``publish-summary``
不会被触发，路由则发出 ``[ERROR] scheduler.error: scheduler[daily-report] failed``。
``daily-report`` 的一次运行还在进行时，下一次触发会记录为 ``skipped``。

失败的流水线自己也会发布 ``pipeline.failed`` 与 ``task.failed``。请把这两者或
``scheduler.error`` 其中一边路由到 sink；同时涵盖两边的路由会为一次失败发出两条消息。

作业与目标
--------------------

一个作业有名称、目标，以及任意数量的触发器。

**动作列表**\ 通过共享的执行器执行，一个动作接着一个动作。抛出异常的动作会让这次
运行失败，其余的动作仍会执行，与 ``execute_action`` 相同。动作的返回值不会保留。

**流水线**\ 可以是 :class:`~automation_file.pipeline.Pipeline`、定义的映射，或是
``.yaml`` / ``.yml`` / ``.json`` 定义文件的路径。定义在作业注册时检查，文件也只在那一刻
读取一次：修改文件之后，请移除作业再重新注册。每一次触发都以默认的运行记录存储调用
``pipeline.run()``，所以 ``FA_pipeline_status`` 与 ``FA_pipeline_history`` 看得到这次
运行。

``add_pipeline`` 会读取流水线的 ``schedule``，把它变成 cron 触发器，时区也一并带入；
除非给了 ``name``，作业会以流水线的名称命名。``add_job`` 也接受流水线，但不会读取它的
``schedule``。

``params`` 是流水线作业每一次运行的参数；它们会加到流水线自己的默认值上并覆盖同名的
项目。在任何深度的字符串中，``${date:FORMAT}`` 会在作业触发时被替换（``FORMAT`` 是
``strftime`` 格式；单独的 ``${date}`` 会得到 ``2026-10-08T02:00:00``）。使用的是作业
自己的时间：第一个 cron 触发器的时区，没有 cron 触发器时则是本地时间。除此之外不会
替换任何东西，动作列表也不接受 ``params``。

触发器
------------

.. list-table::
   :header-rows: 1
   :widths: 14 36 50

   * - 种类
     - Python 写法
     - 何时触发
   * - ``cron``
     - ``CronTrigger(cron, timezone=None)``
     - 在表达式指定的那些分钟。
   * - ``manual``
     - ``scheduler.run_now(name)``
     - 被调用时。每个作业都能这样触发。
   * - ``file``
     - ``FileTrigger(path, events=("created", "modified"), recursive=True)``
     - ``path`` 下面的文件被创建、修改、删除或移动时。
   * - ``event``
     - ``EventTrigger(types=(), sources=(), min_severity=Severity.INFO)``
     - 事件总线上发布了符合条件的事件时。
   * - ``pipeline``
     - ``PipelineTrigger(pipeline, when="on_success")``
     - 指定名称的流水线有一次运行结束时。

.. code-block:: python

   from automation_file.scheduler import (
       CronTrigger, EventTrigger, FileTrigger, PipelineTrigger, scheduler,
   )

   scheduler.add_job(
       "sweep-inbox",
       [["FA_copy_all_file_to_dir", {"source_dir": "/data/inbox",
                                     "target_dir": "/data/processed"}]],
       triggers=[
           CronTrigger("*/30 * * * *", "UTC"),                      # 每半小时
           FileTrigger("/data/inbox", events=["created"]),          # 以及有新文件时
       ],
   )

一个作业可以有好几个任何种类的触发器，重叠保护涵盖全部。没有触发器的作业只在手动
触发时运行。

Cron
~~~~

五个字段：分（0-59）、时（0-23）、日（1-31）、月（1-12）与星期（0-6，星期日是 0 或
7）。每个字段都接受 ``*``、单个值、区间 ``a-b``、列表 ``a,b,c``，以及步长 ``*/n`` 或
``a-b/n``；月份与星期还接受 ``jan``..``dec`` 与 ``sun``..``sat``。没有秒，也没有
``@daily`` 这类别名。

调度器每秒看一次时钟，每一分钟只处理一次。进程没在运行或机器在休眠的那些分钟，事后
不会补跑。时区请见 `时区与夏令时`_。

手动
~~~~~~~~

.. code-block:: python

   run = scheduler.run_now("nightly-snapshot")     # 一个 JobRun
   run.wait(600)                                   # 运行结束后为 True
   run.state                                       # RunState.COMPLETED；等于 "completed"

``run_now`` 会立刻返回这次触发的记录。作业还在运行且不允许重叠时，记录是
``skipped``。在 JSON 中，也就是通过 HTTP 动作服务器时，它是 ``FA_schedule_run``。

文件事件
~~~~~~~~~~~~~~~~

``FileTrigger`` 使用 :class:`~automation_file.trigger.FileWatcher`，也就是
``FA_watch_start`` 背后的监听器（见 :doc:`events`）。监听器归调度器所有：它不会出现在
``FA_watch_list`` 中，作业被移除时它就停止。运行记录的 ``detail`` 记着文件与事件
（``{"path": "/data/inbox/a.csv", "event": "created"}``）。

保存一个文件常常会产生好几个事件。每一个都是一次触发；作业还在运行时到达的那些会
记录为 ``skipped``。

事件与 webhook
~~~~~~~~~~~~~~~~~~~~~~~~

``EventTrigger`` 匹配的方式与总线相同：``types`` 中放 type 名称（``"task.failed"``）、
前缀（``"pipeline.*"``）与事件类，``sources`` 中放完全相同的 ``event.source`` 值，
另外还有最低严重程度。至少要给一个 type 或一个来源。

webhook 也是这样触发作业的。收到请求的代码发布一个事件，每个触发器匹配的作业都会
运行：

.. code-block:: python

   from dataclasses import dataclass
   from typing import ClassVar

   from automation_file import Event, emit
   from automation_file.scheduler import EventTrigger, scheduler

   @dataclass(frozen=True, kw_only=True)
   class DeployFinished(Event):
       type: ClassVar[str] = "deploy.finished"

   scheduler.add_job(
       "smoke-test",
       [["FA_execute_files", [["checks/smoke.json"]]]],
       triggers=EventTrigger(types="deploy.finished", sources="webhook"),
   )

   # 在你的 Web 框架的处理函数中，请求通过验证之后：
   emit(DeployFinished(source="webhook", subject="release 1.4 deployed"))

对 HTTP 动作服务器（见 :doc:`servers`）的请求也可以改用名称触发单个作业：
``[["FA_schedule_run", {"name": "smoke-test"}]]``。这样的运行会记录为 ``manual``。

触发器的处理函数在发布事件的线程中执行，而且只负责启动这次运行。由作业自己的运行
所发布的事件不会再次触发该作业，所以监听 ``scheduler.error`` 的作业不会因为自己的
失败而不断循环。

通过事件互相触发的作业会形成一条链。会让一条链超过 16 次运行的那次触发不会启动任何
东西：它会记录为 ``skipped``，原因是 ``chain``，所以互相触发的两个作业会停下来，而不是
永远持续下去。

流水线依赖
~~~~~~~~~~~~~~~~~~~~

``PipelineTrigger("daily-report")`` 会在名为 ``daily-report`` 的流水线有一次运行结束时
触发。``when`` 沿用流水线自己的用词：

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - ``when``
     - 在这次运行……时触发
   * - ``"on_success"``
     - 成功。这是默认值。
   * - ``"on_failure"``
     - 失败或被取消。
   * - ``"always"``
     - 结束，不论结果如何。

这个触发器监听 ``pipeline.completed`` 与 ``pipeline.failed``，所以它看得到调度器的
总线上该流水线的每一次运行：调度器启动的、用 ``pipeline.run()`` 启动的，以及由
``FA_pipeline_run`` 启动的。记录的 ``detail`` 记着触发它的那次运行的流水线、运行 ID 与
状态。流水线作业不能依赖自己的流水线，而互相依赖的两条流水线会被上述的链长度上限挡下。

选项
--------

``scheduler.add(name, cron_expression, action_list, *, allow_overlap=False, timezone=None, timeout=None)``

``scheduler.add_job(name, target, *, triggers=None, allow_overlap=False, timeout=None, params=None)``

``scheduler.add_pipeline(pipeline, *, name=None, triggers=None, allow_overlap=False, timeout=None, params=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 选项
     - 含义
   * - ``name``
     - 标识这个作业。第二个同名的作业会被拒绝。``add_pipeline`` 的默认值是流水线的
       名称。
   * - ``cron_expression``
     - ``add`` 的五个字段。
   * - ``action_list`` / ``target`` / ``pipeline``
     - 作业要运行的东西。见 `作业与目标`_。
   * - ``triggers``
     - 一个或多个触发器：对象，或它们的映射（见 `动作`_）。
   * - ``allow_overlap``
     - 允许作业还在运行时就启动新的触发。默认 ``False``。
   * - ``timezone``
     - ``add`` 解读表达式所用的时区。默认：本地时间。
   * - ``timeout``
     - 一次运行可以花的秒数，必须大于 0。默认：不限制。见 `超时`_。
   * - ``params``
     - 流水线作业每次运行的参数。

这三个方法都返回作业的快照，也就是 ``scheduler.list()`` 为每个作业保存的映射：

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 键
     - 值
   * - ``name``
     - 作业的名称。
   * - ``cron``、``timezone``
     - 第一个 cron 触发器的表达式与时区；作业没有 cron 触发器时是 ``""`` 与
       ``None``。
   * - ``triggers``
     - 以映射表示的每一个触发器。
   * - ``target``、``pipeline``、``actions``
     - ``"actions"`` 或 ``"pipeline"``、流水线的名称，以及列表中的动作数量。
   * - ``allow_overlap``、``timeout``
     - 与传入的值相同。
   * - ``runs``、``skipped``
     - 启动了几次触发，以及跳过了几次。
   * - ``running``
     - 是否还有运行的线程活着。见 `超时`_。
   * - ``last_run``
     - 最后一次运行被触发的时间，以作业自己的时间表示：作业有时区时带偏移量，
       没有时则是本地时间。
   * - ``last_state``
     - 最后一次运行结束时的状态。

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - 调用
     - 作用
   * - ``remove(name)``、``remove_all()``
     - 移除作业并停止它们的触发器。进行中的运行会继续。
   * - ``list()``
     - 每个作业的快照。
   * - ``run_now(name)``
     - 手动触发一个作业；返回 ``JobRun``。
   * - ``cancel(name)``
     - 取消该作业进行中的运行；返回它们的记录。
   * - ``history(job=None, state=None, limit=50)``
     - 最近的记录，最新的在前。
   * - ``start()``、``shutdown(timeout=5.0, *, cancel_running=False)``
     - 见 `启动与停止`_。
   * - ``tick(now=None)``
     - 为手动驱动的调度器处理一次当前这一分钟与超时。见 `启动与停止`_。

运行记录与状态
----------------------------

``scheduler.history()`` 返回 :class:`~automation_file.scheduler.JobRun` 对象；
``run.to_dict()`` 可以序列化成 JSON。

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 字段
     - 含义
   * - ``run_id``
     - 这次触发的 ID。
   * - ``job``
     - 作业的名称。
   * - ``trigger``
     - ``cron``、``manual``、``file``、``event`` 或 ``pipeline``。
   * - ``detail``
     - 是什么触发了这次运行：表达式与时区、文件与事件、事件的 type、ID、来源与
       主题，或是流水线、运行 ID 与状态。
   * - ``target``、``pipeline``
     - ``"actions"`` 或 ``"pipeline"``，以及流水线的名称。
   * - ``state``
     - 一个 ``RunState``。它与自己的文本比较时相等。
   * - ``scheduled_at``
     - 这次运行应该开始的时间：对 cron 而言就是那一分钟。
   * - ``started_at``、``finished_at``
     - 目标开始执行的时间，以及记录关闭的时间。
   * - ``duration_ms``
     - 两者之间的时间。
   * - ``error``
     - 出了什么问题，用于 ``failed`` 与 ``timeout``。
   * - ``reason``
     - 被跳过的触发是 ``overlap`` 或 ``chain``，被取消的运行是
       ``cancelled``。
   * - ``correlation_id``
     - 这次运行的每个事件所带的 ID。对动作列表而言它就是 ``run_id``。对流水线而言，
       流水线一开始运行它就变成流水线的运行 ID，也就是 ``FA_pipeline_status`` 接受的
       那个 ID。

所有时间都是带时区的 UTC。目标在 ``correlation_scope(run_id)`` 之内、以 actor
``scheduler`` 执行，所以这次运行的存储错误与审计记录都带着同一个 ID。

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - 状态
     - 含义
   * - ``scheduled``
     - 触发已被接受，它的线程还没开始。
   * - ``started``
     - 目标正在执行。
   * - ``completed``
     - 每个动作都返回了，或流水线的运行成功了。
   * - ``failed``
     - 至少一个动作抛出异常、流水线的运行没有成功，或目标根本无法执行。``error``
       会说明是哪一种。
   * - ``skipped``
     - 什么都没有启动：作业还在运行而且不允许重叠，或是这次触发落在一条 16 次运行的
       链的末端。
   * - ``timeout``
     - 运行没有在超时时间内结束。
   * - ``cancelled``
     - ``cancel`` 停止了这次运行。

历史保存在内存中，每个调度器各有一份，保留最近的 1000 条记录
（``Scheduler(history_limit=...)``）；最旧的先被丢弃。它不会在进程结束后留存。被调度
流水线的运行同时也在流水线的运行记录存储中，而每一次失败都是事件，:doc:`审计轨迹 <audit>`
可以把它保存下来。

重叠保护
----------------

除非作业注册时给了 ``allow_overlap=True``，否则在作业运行期间到达的触发不会启动任何
东西。它会记录为 ``skipped``，原因是 ``overlap``，计入作业的 ``skipped``，并以警告
写入日志。每一种触发器都是如此，``run_now`` 也不例外。

在运行的线程真正结束之前，作业都算是运行中。超时或取消之后，这个时间点可能比记录上
写的还晚。

超时
--------

``timeout`` 是一次运行可以花的秒数，从它被触发的那一刻起算。调度器每秒检查一次。
时间到了的时候，记录会变成 ``timeout``，发布一个 ``scheduler.error`` 事件，并要求这次
运行停止：

* 流水线会通过它的取消令牌被取消，与 ``run.cancel()`` 完全相同：尚未开始的任务变成
  ``cancelled``，运行中的任务则通过 ``ctx.cancel`` 得知；
* 动作列表会在下一个动作之前停止。

**线程无法被强制终止。**\ 正在执行的动作，或不检查令牌的流水线任务，会一直执行到它
返回为止。在那之前作业都算是运行中，所以下一次触发会被跳过，两次运行绝不会相撞。
线程在超时之后做的事不会改变记录。

也请为流水线的任务设置它们自己的超时（见 :doc:`pipeline`）：任务的超时只让一个任务
失败，清理任务仍会执行；作业的超时则会停止整次运行。

取消
--------

.. code-block:: python

   cancelled = scheduler.cancel("daily-report")    # 这些记录，现在是 "cancelled"

``cancel(name)`` 会把该作业进行中的运行的记录关闭为 ``cancelled``，并以与超时相同的
方式停止这些运行。作业没有在运行时它返回空列表；名称既没有注册也没有在运行时则抛出
``SchedulerException``。被取消的运行不会发布 ``scheduler.error``。移除作业不会取消
进行中的运行。

时区与夏令时
------------------------

``timezone`` 是 IANA 名称，例如 ``Asia/Taipei`` 或 ``America/New_York``，或是
``UTC``。时区数据来自标准库的 ``zoneinfo``，它读取系统的数据库。Windows 没有这个
数据库：请在那里安装 ``tzdata`` 包（``pip install tzdata``）。``UTC`` 不需要它就能
使用。找不到的名称会在作业注册时抛出 ``CronException``。

没有时区的 cron 触发器以机器的本地时间解读，调度器一直以来都是如此。在容器中那通常
是 UTC：请为生产环境的作业指定时区。

在有夏令时的时区中：

* **不存在的本地时间不会触发。**\ 在时钟从 02:00 直接跳到 03:00 的那一天，
  ``30 2 * * *`` 不会运行；
* **出现两次的本地时间只触发一次**\ ，在第一次出现时。在时钟从 02:00 拨回 01:00 的
  那一天，``30 1 * * *`` 只运行一次；
* 小时字段是 ``*`` 的表达式本来就每小时运行，所以在重复的那一小时中仍会持续触发：
  ``*/15 * * * *`` 在这两天都是每 15 分钟（实际经过的时间）运行一次。

必须以固定间隔运行，或不论时钟怎么变都必须每天刚好运行一次的作业，最好排在 ``UTC``。
没有时区的触发器跟随系统时钟，不会得到上述任何处理：重复的那一小时会触发两次。

事件
--------

以 ``failed`` 或 ``timeout`` 结束的运行会在调度器的总线上发布一个
``SchedulerError``\ （``scheduler.error``，严重程度 ``error``，来源 ``scheduler``）。它的
主题是 ``scheduler[<job>] failed`` 或 ``scheduler[<job>] timed out``，它的关联 ID 是
记录的 ``correlation_id``。

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - payload 的键
     - 值
   * - ``job``
     - 作业的名称。
   * - ``trigger``
     - 是什么触发了这次运行。
   * - ``status``
     - ``failed`` 或 ``timeout``。
   * - ``error``
     - 记录的 ``error``。其中的 URL 会被截到只剩主机。
   * - ``target``
     - ``actions`` 或 ``pipeline``。
   * - ``scheduler_run_id``
     - 记录的 ``run_id``。
   * - ``duration_ms``
     - 目标已经开始执行时才有。
   * - ``pipeline``、``run_id``
     - 目标是流水线时：它的名称，以及流水线开始运行之后的流水线运行 ID。

``completed``、``skipped`` 与 ``cancelled`` 不会发布任何事件；它们记在历史与日志中。

有一种失败的报告方式不同。执行器完全不接受的动作列表（空的列表、不是列表的东西）
仍像以前一样通过 :func:`~automation_file.notify.manager.notify_on_failure` 报告。它
自己在整个进程共用的总线上发布 ``scheduler.error`` 事件，payload 是 ``job``、
``status``\ （``error``）、``error`` 与 ``context``；而在通知路由器没有启用时，它还会把
消息直接发到每一个已注册的 sink（见 :doc:`notifications`）。其他所有失败都只是事件：
想收到通知，请为 ``scheduler.error`` 加一条路由。

动作
--------

.. list-table::
   :header-rows: 1
   :widths: 26 44 30

   * - 动作
     - 参数
     - 返回
   * - ``FA_schedule_add``
     - ``name, cron_expression, action_list, allow_overlap=False, timezone=None,
       timeout=None``
     - 作业的快照
   * - ``FA_schedule_job``
     - ``name, action_list, triggers=None, allow_overlap=False, timeout=None``
     - 作业的快照
   * - ``FA_schedule_pipeline``
     - ``definition, name=None, triggers=None, params=None, allow_overlap=False,
       timeout=None``
     - 作业的快照
   * - ``FA_schedule_run``
     - ``name``
     - 这次触发的记录
   * - ``FA_schedule_cancel``
     - ``name``
     - 被取消的记录
   * - ``FA_schedule_history``
     - ``job=None, state=None, limit=50``
     - 记录，最新的在前
   * - ``FA_schedule_list``
     - （无）
     - 每个作业的快照
   * - ``FA_schedule_remove``
     - ``name``
     - 被移除作业的快照
   * - ``FA_schedule_remove_all``
     - （无）
     - 被移除的各个作业的快照

它们操作的是整个进程共用的 ``scheduler``。``definition`` 是映射或定义文件的路径，它的
``schedule`` 会变成 cron 触发器。在 ``FA_schedule_add`` 中，``allow_overlap``、
``timezone`` 与 ``timeout`` 要以名称传入。触发器是一个映射，内含它的 ``kind`` 与该
种类的参数：

.. list-table::
   :header-rows: 1
   :widths: 14 86

   * - ``kind``
     - 键
   * - ``cron``
     - ``cron``\ （必填）、``timezone``
   * - ``file``
     - ``path``\ （必填）、``events``、``recursive``
   * - ``event``
     - ``types``、``sources``、``min_severity``；type 以名称与前缀表示
   * - ``pipeline``
     - ``pipeline``\ （必填）、``when``

.. code-block:: json

   [
     ["FA_schedule_pipeline", {"definition": "pipelines/daily-report.yaml",
                               "params": {"date": "${date:%Y-%m-%d}"},
                               "timeout": 3600}],
     ["FA_schedule_pipeline", {"definition": "pipelines/publish-summary.yaml",
                               "triggers": [{"kind": "pipeline",
                                             "pipeline": "daily-report"}]}],
     ["FA_schedule_job", {"name": "sweep-inbox",
                          "action_list": [["FA_copy_all_file_to_dir",
                                           {"source_dir": "/data/inbox",
                                            "target_dir": "/data/processed"}]],
                          "triggers": [{"kind": "file", "path": "/data/inbox",
                                        "events": ["created"]}]}],
     ["FA_schedule_run", {"name": "daily-report"}],
     ["FA_schedule_history", {"job": "daily-report", "limit": 5}]
   ]

``register_scheduler_ops(registry)`` 可以把这些动作加进你自己的 registry。

作业会记下它之后要运行的动作名称。只要动作列表或定义是请求的一部分，TCP 或 HTTP
动作服务器上的 :class:`~automation_file.ActionACL` 也会检查这些名称。它看不到以文件
路径指定的定义内部，而 ``FA_schedule_run`` 会运行已注册作业所持有的任何内容：请只对
可以调用全部已注册动作的客户端开放 ``FA_schedule_pipeline`` 与 ``FA_schedule_run``。

启动与停止
--------------------

.. code-block:: python

   from automation_file.scheduler import Scheduler

   scheduler = Scheduler(history_limit=5000)      # 你自己的调度器
   scheduler.shutdown()                           # 停止线程与每一个触发器
   scheduler.start()                              # ... 再把它们带回来

``Scheduler(*, clock=None, bus=None, history_limit=1000, autostart=True)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 选项
     - 含义
   * - ``clock``
     - 返回当前时间（带时区的 ``datetime``）的可调用对象。默认：系统时钟的 UTC
       时间。
   * - ``bus``
     - 调度器监听与报告所用的 ``EventBus``，也是它的流水线发布事件的地方。默认：
       整个进程共用的总线。
   * - ``history_limit``
     - 保留几条记录。默认 ``1000``。
   * - ``autostart``
     - 加入作业时启动后台线程。默认 ``True``。

``shutdown()`` 会停止后台线程，以及调度器建立的每一个文件监听器与每一个总线订阅。
作业仍保持注册；``start()`` 或再加入一个作业会让它们重新就绪。进行中的运行会跑完，
除非使用 ``shutdown(cancel_running=True)``。调度器的所有线程都是 daemon 线程，所以
它们绝不会让解释器无法退出。

使用 ``autostart=False`` 时，什么都不会自己发生：``tick(now)`` 会处理 ``now`` 所在的
那一分钟以及在 ``now`` 到期的超时，并返回它所触发的记录。不必等待就能测试调度的做法
就是这样：

.. code-block:: python

   from datetime import datetime, timezone

   from automation_file.scheduler import Scheduler

   engine = Scheduler(autostart=False)
   engine.add("nightly", "0 2 * * *", [["FA_schedule_list"]], timezone="Asia/Taipei")
   engine.tick(datetime(2026, 10, 7, 17, 59, tzinfo=timezone.utc))      # []
   (run,) = engine.tick(datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc))
   run.wait(10)
   run.state                                       # "completed"

出问题时
----------------

作业没有在它的时间运行
    先找有没有 ``skipped`` 记录：那表示上一次运行还在进行。如果完全没有记录，表示
    那一分钟没有被处理：进程没在运行或机器在休眠（错过的分钟不会补跑）、那一天不
    存在那个本地时间，或是表达式其实以另一个时区解读。没有 ``timezone`` 的触发器使用
    机器的本地时间。

``CronException: unknown time zone``
    名称拼错了，或机器没有时区数据：在 Windows 上请安装 ``tzdata``。

运行是 ``failed``，但大部分都成功了
    有一个动作抛出异常，列表的其余部分仍然执行了。``error`` 会按位置与名称列出失败
    的动作。

运行是 ``completed``，工作却出了问题
    只有动作抛出异常或流水线的运行没有成功时，运行才算失败。以返回值报告的动作会
    完成：请见 :doc:`pipeline` 中的同一个条目。

运行已是 ``timeout`` 或 ``cancelled``，作业却仍显示 ``running``
    它的线程无法被停止，还停在原本的动作或任务中。在那返回之前，作业都是忙碌的，
    它的触发也都会被跳过。请为长时间的传输设置它们自己的超时，并让长时间的流水线
    任务检查 ``ctx.cancel``。

作业触发得比预期频繁
    保存一个文件会产生好几个文件事件；同一个作业的两个触发器都会触发它；设置了
    ``allow_overlap=True`` 的作业不会被进行中的运行挡下。

记录是 ``skipped``，原因是 ``chain``
    已经有十六次运行接连互相触发：两个作业监听彼此的事件，或两条流水线互相依赖。请
    打破这个循环；需要重复运行的作业应该使用 cron 触发器。

依赖的流水线从不触发
    ``PipelineTrigger`` 中的名称不是上游流水线的 ``name``、上游的运行没有以 ``when``
    要求的方式结束，或它发布事件的总线不是调度器的那一个。

事件触发器没有触发
    请对照 ``event_bus.recent()`` 检查 ``types``、``sources`` 与 ``min_severity``。
    由作业自己的运行所发布的事件是刻意被忽略的。

没有收到通知
    路由器必须已经启动，而且必须有一条匹配 ``scheduler.error`` 的路由。没有路由器
    时，只有执行器拒绝的动作列表会被直接发到 sink。

历史是空的
    它保存在内存中，随进程结束而消失；你自己建立的调度器有它自己的历史。流水线的
    运行则在运行记录存储中。

``shutdown()`` 之后什么都不触发
    作业仍然注册着，但它们的触发器已经停止。请调用 ``start()``。

重复或未知的作业、错误的触发器、错误的超时与错误的历史查询会抛出
``SchedulerException``；无法理解的表达式或时区则抛出 ``CronException``。错误的定义会
抛出 ``PipelineDefinitionException``，不存在的监听路径则抛出 ``TriggerException``，
两者都发生在作业注册时。它们全都派生自 ``FileAutomationException``。
