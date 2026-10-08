流水线（Pipeline）
======================

``automation_file.pipeline`` 按依赖顺序执行一组任务，互不依赖的任务并行执行，并补上
周期性作业需要的功能：重试、超时、取消、条件、幂等键、检查点与续跑、试运行，以及运行
历史。

任务可以是 Python 可调用对象，也可以是 ``FA_*`` 动作。流水线可以用 Python 构建，也可以
写成 YAML / JSON 文档。一次运行只通过事件总线上的事件报告（见 :doc:`event_bus`）；
它不会调用任何通知 sink，也不会写入审计记录。

:func:`~automation_file.execute_action_dag`\ （见 :doc:`dag`）保持不变。它把一份动作
列表执行一次并返回结果；当运行需要被记录、重试、续跑或观察时，请改用流水线。

最小示例
----------------

.. code-block:: python

   from automation_file.pipeline import Pipeline

   def count_rows(ctx):
       return len(ctx.results["read"].splitlines())

   pipeline = Pipeline("row-count")
   pipeline.task("read", ["FA_storage_read_text", {"uri": "local:///data/report.csv"}])
   pipeline.task("count", count_rows, depends_on=["read"])

   run = pipeline.run()
   run.status                      # RunStatus.SUCCEEDED；等于 "succeeded"
   run.tasks["count"].result       # 42
   run.tasks["count"].attempts     # 1

``run()`` 在所有任务都结束后才返回。任务失败不会抛出异常：结果记在 ``run.status``
以及 ``run.tasks`` 的每一项上。

生产环境示例
------------------------

一个每晚运行的作业：带重试与超时地获取文件、检查内容、同一个日期最多发布一次、发布
失败时撤回发布到一半的报表，并把运行记录存进 SQLite 文件，让失败的运行可以续跑。

.. code-block:: python

   from automation_file.pipeline import Pipeline, RetryPolicy, SQLiteRunStore

   WORK = "local:///var/tmp/report-${params.date}.csv"
   TARGET = "azure://reports/${params.date}.csv"
   store = SQLiteRunStore("/var/lib/automation/pipelines.db")

   def check(ctx):
       ctx.cancel.raise_if_cancelled()               # 被取消或超时就停下来
       if ctx.results["download"]["size"] == 0:
           raise ValueError("the report is empty")   # 任务通过抛出异常表示失败
       return {"bytes": ctx.results["download"]["size"]}

   pipeline = Pipeline("daily-report", description="Fetch, check, publish", max_workers=4)
   pipeline.task(
       "download",
       ["FA_storage_copy", {"source": "s3://input/${params.date}.csv", "target": WORK}],
       retry=RetryPolicy(max_attempts=5, backoff_base=2.0, backoff_cap=60.0),
       timeout=300.0,
   )
   pipeline.task("check", check, depends_on=["download"], timeout=60.0)
   pipeline.task(
       "publish",
       ["FA_storage_copy", {"source": WORK, "target": TARGET}],
       depends_on=["check"],
       retry=RetryPolicy(max_attempts=3, backoff_base=1.0),
       idempotency_key="publish-${params.date}",     # 同一个日期绝不发布两次
   )
   pipeline.task(
       "withdraw",                                   # 清理：只在 publish 失败时执行
       ["FA_storage_delete", {"uri": TARGET, "missing_ok": True}],
       depends_on=["publish"],
       when="on_failure",
   )
   pipeline.task("tidy", ["FA_storage_delete", {"uri": WORK}], depends_on=["publish"])

   run = pipeline.run(params={"date": "2026-10-08"}, store=store)
   if run.status != "succeeded":
       for task_id, state in run.tasks.items():
           print(task_id, state.status.value, state.error or state.reason or "")

   # 稍后，在同一个或另一个进程中，等原因排除之后：
   run = pipeline.resume(run.run_id, store=store)    # 只执行尚未成功的部分

``publish`` 三次尝试都失败时，``withdraw`` 会执行，``tidy`` 被跳过，这次运行的状态为
``failed``。``resume`` 保留 ``download`` 与 ``check``，重新执行 ``publish``，接着执行
``tidy``。之后同一个日期的另一次运行会重新下载与检查，但跳过 ``publish``：它的键已经
成功过。

同一条流水线不写 Python 的版本，保存为 ``daily-report.yaml``。``check`` 是可调用对象，
无法写进文档，所以这个版本直接发布下载到的内容：

.. code-block:: yaml

   schema_version: 1
   name: daily-report
   description: Fetch and publish the daily report
   max_workers: 4
   schedule: {cron: "0 2 * * *", timezone: Asia/Taipei}
   params: {date: "2026-10-08"}
   tasks:
     download:
       action: ["FA_storage_copy", {"source": "s3://input/${params.date}.csv",
                                    "target": "local:///var/tmp/report-${params.date}.csv"}]
       retry: {max_attempts: 5, backoff: 2, backoff_cap: 60,
               on: [StorageTransientException, ConnectionError]}
       timeout: 300
     publish:
       action: ["FA_storage_copy", {"source": "local:///var/tmp/report-${params.date}.csv",
                                    "target": "azure://reports/${params.date}.csv"}]
       depends_on: [download]
       retry: {max_attempts: 3, backoff: 1}
       idempotency_key: "publish-${params.date}"
     withdraw:
       action: ["FA_storage_delete", {"uri": "azure://reports/${params.date}.csv",
                                      "missing_ok": true}]
       depends_on: [publish]
       when: on_failure
     tidy:
       action: ["FA_storage_delete", {"uri": "local:///var/tmp/report-${params.date}.csv"}]
       depends_on: [publish]

.. code-block:: python

   pipeline = Pipeline.from_file("daily-report.yaml")
   run = pipeline.run(params={"date": "2026-10-09"}, store=store)

任务
--------

任务要做的事有两种写法。

**可调用对象**：接收一个 :class:`~automation_file.pipeline.model.TaskContext`。它的
返回值就是任务的结果；抛出异常则任务失败。

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - 字段
     - 含义
   * - ``pipeline``
     - 流水线的名称。
   * - ``run_id``
     - 这次运行的 ID，同时也是每个事件的关联 ID。
   * - ``task``
     - 任务的 ID。
   * - ``attempt``
     - 第几次尝试，从 1 开始（在 ``when`` 可调用对象中为 ``0``）。
   * - ``params``
     - 这次运行的参数，只读：流水线的默认值，再由 ``run(params=...)`` 覆盖。
   * - ``results``
     - 任务 ID 到结果的映射，只读，涵盖所有成功的上游任务，不论是否直接依赖。失败
       或被跳过的任务不会出现在其中。
   * - ``cancel``
     - ``CancellationToken``。运行被取消或任务超时后会被置位。见 `超时`_。
   * - ``dry_run``
     - 永远是 ``False``：试运行不会执行任何东西。

**动作**：三种形式之一，``[name]``、``[name, {kwargs}]`` 与 ``[name, [args]]``。名称
会在共享执行器的注册表（或传给流水线的 ``registry=``）中查找，并直接调用该命令，因此
失败时异常会抛进任务。在调用参数中，不论嵌套多深：

* ``${params.<name>}`` 会被替换为该参数。夹在较长的文本中时以文本插入；整个字符串
  恰好就是一个占位符时，会替换为参数本身，所以 ``"${params.limit}"`` 仍然是数字 ``20``。
* 整个字符串恰好是 ``${tasks.<id>.result}`` 时，会替换为该上游任务的结果对象（如果它
  没有成功则为 ``None``）。该任务必须是上游任务，而且这个占位符不能夹在较长的文本中。

这里没有表达式语言，也不会对任何内容求值。其他的 ``${...}`` 文本会原样传递。由于
调用参数中的每个字符串都会被检查，把流水线定义作为参数交给 ``FA_pipeline_run`` 时，
其中的占位符会被外层流水线填入：请改为传入文件路径。

任务 ID 与参数名称是非空字符串，不能包含空白、``.``、``$``、``{`` 或 ``}``。

选项
--------

``Pipeline(name, description="", max_workers=4, *, params=None, schedule=None, registry=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 选项
     - 含义
   * - ``name``
     - 在事件、历史与幂等键中用来标识这条流水线。
   * - ``description``
     - 自由文本，保存在定义中。
   * - ``max_workers``
     - 同时执行的任务数量上限。默认为 ``4``。
   * - ``params``
     - 默认参数；``run(params=...)`` 会加入并覆盖它们。
   * - ``schedule``
     - ``Schedule(cron, timezone=None)``。保存在 ``pipeline.schedule`` 供调度器
       使用，流水线本身不会据此行动。
   * - ``registry``
     - 查找动作名称的地方。默认：共享执行器的注册表。

``pipeline.task(task_id, work, *, depends_on=None, retry=None, timeout=None, when="on_success", idempotency_key=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 选项
     - 含义
   * - ``task_id``
     - 在流水线中必须唯一。加入第二个相同 ID 的任务会立刻被拒绝。
   * - ``work``
     - 可调用对象或动作。
   * - ``depends_on``
     - 必须先结束的任务 ID。可以先写出尚未加入的任务；依赖图在流水线运行时才
       检查。
   * - ``retry``
     - ``RetryPolicy``。默认：只尝试一次。见 `重试`_。
   * - ``timeout``
     - 整个任务可用的秒数。默认：没有限制。见 `超时`_。
   * - ``when``
     - ``"on_success"``\ （默认）、``"on_failure"``、``"always"`` 或可调用对象。
       见 `条件`_。
   * - ``idempotency_key``
     - 可含 ``${params.<name>}`` 占位符的文本。见 `幂等`_。

``RetryPolicy(max_attempts=1, backoff_base=0.0, backoff_cap=60.0, retry_on=(...))``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 选项
     - 含义
   * - ``max_attempts``
     - 总共尝试几次；``1`` 表示不重试。
   * - ``backoff_base``
     - 第一次尝试失败后等待的秒数；之后每失败一次就加倍。
   * - ``backoff_cap``
     - 等待时间的上限。
   * - ``retry_on``
     - 值得再试一次的异常类。默认：``StorageTransientException``、
       ``ConnectionError``、``TimeoutError``。

``pipeline.run(params=None, *, dry_run=False, store=None, cancel=None, bus=None)``、
``pipeline.start(params=None, *, store=None, cancel=None, bus=None)`` 与
``pipeline.resume(run_id, *, store=None, cancel=None, bus=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 选项
     - 含义
   * - ``params``
     - 这次运行的参数。
   * - ``dry_run``
     - 只规划而不执行。见 `试运行`_。
   * - ``store``
     - 记录这次运行的 ``RunStore``。默认：默认的存储。
   * - ``cancel``
     - ``CancellationToken``，被置位时会停止这次运行。
   * - ``bus``
     - 接收事件的 ``EventBus``。默认：整个进程共用的总线。
   * - ``run_id``
     - 用于 ``resume``：要接续的那次运行。

``run`` 在调用它的线程中工作，并返回已结束的
:class:`~automation_file.pipeline.model.PipelineRun`。``start`` 立刻返回运行对象，
并在后台线程中工作：``run.wait(timeout)`` 会等到它结束（并返回是否已结束），
``run.done`` 不等待就能得知，``run.cancel()`` 则会停止它。已启动的运行还没结束时，
解释器不会退出。

在任何任务开始之前，``run``、``start`` 与 ``resume`` 会对以下情况抛出
``PipelineDefinitionException``：流水线是空的、依赖的任务不存在或重复、任务依赖于
自己、依赖图有环、占位符格式错误、结果占位符指向不是上游的任务，以及占位符用到
这次运行没有提供的参数。``error.problems`` 列出每一项问题及其路径；
``pipeline.problems()`` 返回同一份列表但不抛出异常。

状态
--------

``run.tasks[task_id].status`` 是 ``TaskStatus``，``run.status`` 是 ``RunStatus``。
两者都可以直接与它们的文本比较。

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - 任务状态
     - 含义
   * - ``pending``
     - 尚未开始。
   * - ``running``
     - 正在进行某一次尝试，或正在两次尝试之间等待。
   * - ``succeeded``
     - 已返回；``result`` 保存返回值。
   * - ``failed``
     - 抛出了异常，而且没有剩余的尝试次数；``error`` 的形式为
       ``"<ExceptionType>: <message>"``。
   * - ``skipped``
     - 没有执行；``reason`` 说明原因（见下表）。
   * - ``timeout``
     - 没有在超时时间内完成。
   * - ``cancelled``
     - 运行在它开始之前或执行期间被取消，或任务抛出了 ``CancelledException``。
   * - ``planned``
     - 试运行：它会按这个顺序被考虑。

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - 跳过的 ``reason``
     - 含义
   * - ``idempotent``
     - 它的幂等键已经有一次成功的执行；沿用存储的结果，依赖于它的任务照常执行。
   * - ``condition``
     - 它自己的 ``on_failure`` 条件或可调用条件没有成立。
   * - ``upstream_failed``
     - ``on_success`` 任务，而它的某个依赖任务失败、超时或被取消。
   * - ``upstream_skipped``
     - ``on_success`` 任务，而它的某个依赖任务被跳过。

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - 运行状态
     - 含义
   * - ``running``
     - 尚未结束。
   * - ``succeeded``
     - 每个任务都成功或被跳过。
   * - ``failed``
     - 至少有一个任务失败、超时或被取消；``run.error`` 会列出它们。清理任务成功
       并不会改变这个结果。
   * - ``cancelled``
     - 运行被取消，而且至少有一个任务因此没有执行。

任务状态还有 ``attempts``、``started_at`` 与 ``finished_at``\ （UTC）、
``duration_ms``、``level``\ （没有依赖的任务为 0）以及 ``idempotency_key``\ （已填入
占位符的键）。``run.tasks`` 按依赖顺序排列，``run.to_dict()`` 可以序列化为 JSON。

条件
--------

``when`` 只在任务的所有依赖任务都结束时检查一次。

``"on_success"``
    每个依赖任务都成功（或以 ``idempotent`` 被跳过）。否则任务被跳过，而且这会
    传到它自己的 ``on_success`` 下游任务。

``"on_failure"``
    至少有一个依赖任务失败、超时或被取消。用于清理。只是被跳过的依赖任务不算。

``"always"``
    不论依赖任务的结果如何。

可调用对象 ``(TaskContext) -> bool``
    返回真值时任务才执行。它独自决定：不会参考依赖任务的结果，但 ``ctx.results``
    只包含成功的那些。可调用对象抛出异常时，任务为 ``failed``。

重试
--------

一次尝试失败后，如果还有剩余次数，而且异常是 ``retry_on`` 中某个类的实例，任务就会
再试一次。第 ``n + 1`` 次尝试之前等待 ``backoff_base * 2 ** (n - 1)`` 秒，最多
``backoff_cap`` 秒。

默认的 ``retry_on`` 只包含暂时性的错误。``ValueError`` 或 ``KeyError`` 意味着程序错误
或输入有误，第一次尝试就会失败。请把 ``retry_on`` 放宽到你确知是暂时性的错误，绝对
不要放宽到 ``Exception``。

超时
--------

``timeout`` 是整个任务可用的秒数：包含每一次尝试以及尝试之间的等待。用完之后，任务
被记录为 ``timeout``，它的取消令牌被置位，其余任务继续执行。

**线程无法被强制终止。**\ 可调用对象会继续运行直到它自己返回，而它在超时之后返回
或抛出的任何东西都会被忽略。因此运行时间长的可调用对象必须检查自己的令牌：

.. code-block:: python

   def export(ctx):
       for chunk in chunks():
           ctx.cancel.raise_if_cancelled()     # 抛出 CancelledException
           write(chunk)

动作无法检查令牌；动作本身若有超时参数，请为长时间的传输设置它。超时的任务不再
计入 ``max_workers``。任务线程是 daemon 线程，所以永不返回的线程不会让解释器无法
退出。

取消
--------

``run.cancel()``，或置位以 ``cancel=`` 传入的 ``CancellationToken``，会在百分之几秒内
停止一次运行：

* 所有尚未开始的任务变成 ``cancelled``，清理任务也一样；
* 所有执行中任务的令牌被置位。运行会等待这些任务，而每个任务保留它实际的结果：
  抛出 ``CancelledException`` 的为 ``cancelled``，照样完成的为 ``succeeded``；
* 正在两次尝试之间等待的任务会停止等待，变成 ``cancelled``。

.. code-block:: python

   run = pipeline.start(params={"date": "2026-10-08"})
   ...
   run.cancel()
   run.wait(30)
   run.status                      # "cancelled"

幂等
--------

带有 ``idempotency_key`` 的任务，一旦以该键成功过，就不会再次执行。任务开始之前，
会用这次运行的参数算出键，并在存储中查找相同流水线名称与任务 ID 的记录。找到成功的
执行时，任务为 ``skipped``，原因是 ``idempotent``，它的 ``result`` 是存储的那一份，
依赖于它的任务会像它成功了一样照常执行。

键的持久程度取决于存储：使用默认的内存存储时，只维持到进程结束；使用
``SQLiteRunStore`` 时，重新启动后仍然有效。它不是锁：同时开始的两次运行可能都查不到
记录，于是都执行该任务。如果存储无法读取，任务会失败而不是照常执行。

检查点与续跑
------------------------

任务的每一次状态转换都会在发生时写入存储：每次尝试的开始、每次失败的尝试，以及
最后的结果。``pipeline.resume(run_id)`` 载入该次运行，保留 ``succeeded`` 的任务及其
结果，并以相同的运行 ID 与相同的参数重新执行其余任务。

.. code-block:: python

   store = SQLiteRunStore("pipelines.db")
   run = pipeline.run(params={"date": "2026-10-08"}, store=store)
   # ... 进程可能在这里结束 ...
   pipeline = build_pipeline()                    # 相同的任务
   run = pipeline.resume(run.run_id, store=SQLiteRunStore("pipelines.db"))

存储保存的是一次运行的状态，而不是流水线本身：``resume`` 要在名称相同的流水线上
调用。结果以 JSON 存储；JSON 无法表示的值会以它的 ``repr`` 存储，并设置
``result_is_repr``，所以续跑之后下游任务看到的是那段文本。其他任务需要用到的结果，
请让任务返回 JSON 数据。已经成功的运行会按存储的内容原样返回。不要续跑仍在别处
执行中的运行。

被保留的任务不会再执行一次，所以它产生的东西必须还在。清理任务应该移除失败任务
留下的东西，而不是某个已成功、后续任务还需要的任务的输出。

试运行
------------

``pipeline.run(dry_run=True)`` 不执行任何东西、不记录任何东西，也不发布任何事件。
每个任务都以 ``planned`` 返回，按依赖顺序排列并带有 ``level``。注册表中找不到的动作
名称，以及用到缺少参数的占位符，会报告在任务的 ``error`` 中；这时运行状态为
``failed``，否则为 ``succeeded``。依赖图有问题时仍然会抛出异常。

.. code-block:: python

   plan = pipeline.run(params={"date": "2026-10-08"}, dry_run=True)
   for task_id, state in plan.tasks.items():
       print(state.level, task_id, state.error or "ok")

运行记录存储与历史
------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 存储
     - 运行记录保存在
   * - ``MemoryRunStore(max_runs=1000)``
     - 内存中，维持到进程结束；最旧的运行最先被丢弃。这是默认的存储。
   * - ``SQLiteRunStore(path)``
     - SQLite 文件中。线程安全、只使用参数化语句、每次转换提交一次，文件中带有
       结构版本。

.. code-block:: python

   from automation_file.pipeline import SQLiteRunStore, set_default_run_store

   store = SQLiteRunStore("/var/lib/automation/pipelines.db")
   set_default_run_store(store)                    # 供 run()、resume() 与动作使用

   store.get_run(run_id)                           # PipelineRun，或 None
   store.list_runs("daily-report", limit=10)       # 最新的在前
   store.find_idempotent("daily-report", "publish", "publish-2026-10-08")

自定义的存储要继承 ``RunStore``，并实现 ``save_run``、``save_task``、``get_run``、
``list_runs`` 与 ``find_idempotent``；无法读取或写入时抛出 ``PipelineException``。
参数与结果会原样存储：不要把密码与令牌放进其中任何一个。

定义文件
----------------

定义是一份带有 ``schema_version: 1`` 的映射，来源可以是 YAML、JSON 或 Python。

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 键
     - 值
   * - ``schema_version``
     - ``1``。必填；没有这个键或值不同的文档会被拒绝。
   * - ``name``
     - 必填。
   * - ``description``、``max_workers``、``params``
     - 与 ``Pipeline`` 的选项相同。
   * - ``schedule``
     - ``{cron: "0 2 * * *", timezone: Asia/Taipei}``。``cron`` 有五个字段；
       ``timezone`` 可省略。
   * - ``tasks``
     - 必填。任务 ID 到任务的映射。
   * - ``tasks.<id>.action``
     - 必填。``[name]``、``[name, {kwargs}]`` 或 ``[name, [args]]``。
   * - ``tasks.<id>.depends_on``
     - 任务 ID 的列表。
   * - ``tasks.<id>.retry``
     - ``{max_attempts, backoff, backoff_cap, on}``。``on`` 列出异常名称：
       ``automation_file.exceptions`` 中的类、``TimeoutError``、
       ``ConnectionError`` 与 ``OSError``。其他名称都是错误。
   * - ``tasks.<id>.timeout``
     - 秒数，必须大于 0。
   * - ``tasks.<id>.when``
     - ``on_success``、``on_failure`` 或 ``always``。
   * - ``tasks.<id>.idempotency_key``
     - 可含 ``${params.<name>}`` 占位符的文本。

.. code-block:: python

   from automation_file.pipeline import PIPELINE_SCHEMA, Pipeline, validate_definition

   validate_definition(document)        # 有效时为 []，否则是每一项问题及其路径
   # ["max_workers: expected an integer >= 1, got 0",
   #  "tasks.verify.depends_on[0]: unknown task 'x'"]

   pipeline = Pipeline.from_dict(document)          # 会抛出 PipelineDefinitionException
   pipeline = Pipeline.from_file("daily-report.yaml")   # .yaml、.yml 或 .json
   pipeline.to_dict()                               # 定义文档，省略默认值
   PIPELINE_SCHEMA                                  # JSON Schema（draft 2020-12），是一个 dict

每一层出现未知的键都是错误。流水线中含有 Python 可调用对象时，``to_dict`` 会抛出
异常，因为文档无法表示它。

YAML 以 ``yaml.safe_load`` 读取。YAML 的三种行为已经处理：

* 同一个映射中重复的键是错误（JSON 也一样），所以第二个相同 ID 的任务不会悄悄地
  取代第一个。
* YAML 1.1 会把没有加引号的 ``on`` 读成 ``true``。``from_file`` 会把 ``retry`` 下面
  的这个键还原为 ``on``；如果你自己解析 YAML，请写成 ``"on"``。
* 没有加引号的日期（例如 ``2026-10-08``）会变成日期对象，定义无法保存它。验证会
  指出这一点：请为日期与时间加上引号。

事件
--------

每个事件的 ``source`` 都是 ``"pipeline"``，``correlation_id`` 都是运行 ID，从任务的
线程发布时也一样。在任务内部发布的事件（例如存储错误）带有相同的关联 ID，以及
启动这次运行的代码的 actor。

.. list-table::
   :header-rows: 1
   :widths: 24 16 60

   * - 事件
     - 严重程度
     - 发布时机
   * - ``pipeline.started``
     - info
     - 一次，在第一个任务之前。续跑时会再发布一次。
   * - ``task.started``
     - info
     - 每次尝试开始时。
   * - ``task.completed``
     - info
     - 某次尝试成功时。
   * - ``task.failed``
     - warning / error
     - 某次尝试失败时。``status`` 为 ``retrying``\ （warning：接着还有一次
       尝试）、``failed``、``timeout`` 或 ``cancelled``\ （warning）。
   * - ``pipeline.completed``
     - info
     - 运行以 ``succeeded`` 结束时。
   * - ``pipeline.failed``
     - error / warning
     - 运行以 ``failed`` 或 ``cancelled``\ （warning）结束时。

payload 使用共用的键：``pipeline``、``run_id``、``status``，任务事件另有 ``task`` 与
``attempt``；某件事结束时有 ``duration_ms``，出错时有 ``error``。被跳过的任务，以及
开始之前就被取消的任务，不会发布任何事件：它的状态记在运行上。``when`` 可调用对象
抛出异常，或幂等键无法查找的任务，会发布一个 ``attempt`` 为 0 的 ``task.failed``。
试运行不会发布任何事件。

.. code-block:: python

   from automation_file import Severity, event_bus

   def alert(event):
       print(event.subject, event.payload.get("error"))

   event_bus.subscribe(alert, types=["pipeline.failed", "task.failed"],
                       min_severity=Severity.ERROR)

动作
--------

流水线也可以从 JSON 动作列表使用，因此 CLI、TCP 与 HTTP 动作服务器以及 MCP 主机都能
调用。``definition`` 是一份映射，或 ``.yaml`` / ``.yml`` / ``.json`` 文件的路径。

.. list-table::
   :header-rows: 1
   :widths: 26 40 34

   * - 动作
     - 参数
     - 返回值
   * - ``FA_pipeline_run``
     - ``definition, params=None, dry_run=False``
     - 这次运行（``PipelineRun.to_dict()``）
   * - ``FA_pipeline_validate``
     - ``definition``
     - ``{"valid": …, "errors": […]}``
   * - ``FA_pipeline_status``
     - ``run_id``
     - 已记录的运行
   * - ``FA_pipeline_history``
     - ``pipeline=None, limit=20``
     - 已记录的运行，最新的在前
   * - ``FA_pipeline_resume``
     - ``run_id, definition``
     - 续跑之后的运行

.. code-block:: json

   [
     ["FA_pipeline_validate", {"definition": "pipelines/daily-report.yaml"}],
     ["FA_pipeline_run", {"definition": "pipelines/daily-report.yaml",
                          "params": {"date": "2026-10-08"}}],
     ["FA_pipeline_history", {"pipeline": "daily-report", "limit": 5}]
   ]

这些动作使用默认的运行记录存储，因此 ``FA_pipeline_status``、``FA_pipeline_history``
与 ``FA_pipeline_resume`` 看到的是同一个进程中的运行，除非已用
``set_default_run_store`` 指定 ``SQLiteRunStore``。任务失败时，``FA_pipeline_run``
返回 ``status`` 为 ``failed`` 的运行；只有定义无法载入或无效时才会抛出异常。
``register_pipeline_ops(registry)`` 可以把这些动作加入你自己的注册表。

定义会写出它的任务要调用哪些动作。只要定义本身包含在请求里，TCP 或 HTTP 动作服务器上的
:class:`~automation_file.ActionACL` 与 MCP 服务器的 ``--allowed-actions`` 也都会检查
这些名称。两者都看不到以文件路径指定的定义，也看不到 ``FA_pipeline_resume`` 所接续的
已存储运行：请只对可以调用全部已注册动作的客户端开放 ``FA_pipeline_run`` 与
``FA_pipeline_resume``，或把定义文件放在这些客户端无法写入的位置。

出问题时
----------------

任务失败
    ``run.status`` 为 ``failed``，``run.error`` 列出这些任务，每个任务状态都有
    ``error``、``attempts`` 与时间。排除原因之后调用 ``resume(run_id)``：已成功的
    部分不会重做。

任务没有执行
    请看 ``reason``。``upstream_failed`` 与 ``upstream_skipped`` 指向某个依赖任务；
    无论如何都必须执行的任务请设置 ``when="always"``。

工作出了问题，任务却成功
    任务只有在抛出异常时才算失败。以返回值报告的动作会让任务成功：
    ``FA_storage_verify`` 在不匹配时返回 ``false``，除非传入 ``strict: true``，此时它会
    抛出 ``StorageChecksumException``，任务因而失败。其他这类返回值，请在会抛出异常的
    可调用对象中，或在下一个任务的可调用 ``when`` 中检查。

任务从不重试
    它的异常不在 ``retry_on`` 中。默认只涵盖 ``StorageTransientException``、
    ``ConnectionError`` 与 ``TimeoutError``。

任务已经 ``timeout``，却好像还在工作
    它的线程无法被停止。请让可调用对象检查 ``ctx.cancel``，并确保第二次运行不会
    与第一次遗留的工作相冲突。

运行被中断（进程结束、Ctrl-C）
    存储中有到那一刻为止的每一次转换，其中可能有任务停在 ``running``。
    ``resume(run_id)`` 会执行所有尚未成功的任务。

还没执行任何任务就抛出 ``PipelineDefinitionException``
    定义有误。``error.problems`` 保存每一项问题及其路径；``validate_definition``
    与试运行可以在不执行的情况下取得它们。

历史不完整
    存储无法写入时会记录为错误，运行则继续进行。运行本身是正确的；它的记录则
    不是。

两个异常，``PipelineException`` 与其子类 ``PipelineDefinitionException``，都派生自
``FileAutomationException``。
