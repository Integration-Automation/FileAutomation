事件
====

每个组件都以 :class:`~automation_file.Event` 的形式，把发生的事报告到
:data:`~automation_file.event_bus`。使用方订阅事件总线即可；没有任何组件会直接
调用通知接收端或写入审计记录。

.. code-block:: python

   from automation_file import PipelineFailed, Severity, event_bus

   def page_someone(event):
       print(event.severity.value, event.subject, event.payload.get("error"))

   subscription = event_bus.subscribe(page_someone, min_severity=Severity.ERROR)
   event_bus.subscribe(print, types=["pipeline.*", "integrity.violation"])
   event_bus.subscribe(print, types=PipelineFailed)
   event_bus.recent(limit=20, min_severity=Severity.WARNING)   # 最新的在前
   event_bus.unsubscribe(subscription)

事件本身
--------

事件不可变，并且可以直接转成 JSON（``event.to_dict()``）。

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - 字段
     - 含义
   * - ``type``
     - 事件种类，以点分隔的名称表示：``pipeline.failed``。
   * - ``severity``
     - ``Severity.INFO``、``WARNING``、``ERROR`` 或 ``CRITICAL``。每个事件类都有
       默认值，发出者可以覆盖。
   * - ``source``
     - 报告的组件：``pipeline``、``integrity``、``scheduler``、``storage``、
       ``system``。
   * - ``subject``
     - 给人看的一行摘要。
   * - ``payload``
     - 细节，使用约定的键：``pipeline``、``run_id``、``task``、``attempt``、
       ``action``、``resource``、``backend``、``status``、``duration_ms``、
       ``error``、``job``、``trigger``。
   * - ``correlation_id``
     - 把属于同一次运行的所有事物串在一起。
   * - ``actor``
     - 这件事是代表谁执行的。
   * - ``id``、``timestamp``
     - 唯一 ID 与 UTC 时间。

核心事件
--------

.. list-table::
   :header-rows: 1
   :widths: 34 30 36

   * - 类
     - ``type``
     - 默认严重程度
   * - ``PipelineStarted``
     - ``pipeline.started``
     - info
   * - ``PipelineCompleted``
     - ``pipeline.completed``
     - info
   * - ``PipelineFailed``
     - ``pipeline.failed``
     - error
   * - ``TaskStarted``
     - ``task.started``
     - info
   * - ``TaskCompleted``
     - ``task.completed``
     - info
   * - ``TaskFailed``
     - ``task.failed``
     - error
   * - ``IntegrityViolation``
     - ``integrity.violation``
     - error
   * - ``StorageError``
     - ``storage.error``
     - error
   * - ``SchedulerError``
     - ``scheduler.error``
     - error
   * - ``SystemErrorEvent``
     - ``system.error``
     - critical

``SystemErrorEvent`` 就是路线图中的“SystemError”；较短的名称会遮蔽 Python 内置的
异常。

订阅
----

``event_bus.subscribe(handler, types=None, min_severity=Severity.INFO)`` 可以按事件
类（包含子类）、完整的 type 名称或前缀（``"pipeline.*"``）匹配；不指定 ``types``
时，处理函数会收到所有事件。``publish`` 在发布者的线程中，按订阅顺序逐一传递，并
返回收到事件的处理函数数量。处理函数如果抛出异常，只会被记录并跳过，因此有问题的
使用方永远不会影响报告事件的代码。处理函数应保持快速；耗时的工作请交给队列或
线程。

``event_bus.recent(limit, types, min_severity, correlation_id)`` 返回总线记得的
最近事件（默认 500 条），最新的在前。需要私有的总线时使用
:class:`~automation_file.EventBus`。

关联 ID 与 actor
----------------

.. code-block:: python

   from automation_file import actor_scope, correlation_scope, emit, PipelineStarted

   with actor_scope("scheduler"), correlation_scope() as run_id:
       emit(PipelineStarted(source="pipeline", subject="daily-report started",
                            payload={"pipeline": "daily-report", "run_id": run_id}))
       ...   # 这里面的每个事件与存储操作都带有 run_id 与 actor

``correlation_scope()`` 会沿用外层范围的 ID，因此嵌套的工作共用最外层那次运行的
ID。在任何范围之外，每个事件都有自己的 ID，actor 则是运行进程的用户。范围不会
自动跟着工作进入另一个线程；把工作分派出去的代码要在那里重新进入范围。

存储操作
--------

存储层会把 ``upload``、``download``、``read``、``delete``、``mkdir``、``copy`` 与
``move`` 报告给通过 ``automation_file.storage.observe.add_listener`` 注册的监听者：
每次调用一条 ``StorageOperation(operation, uri, backend, status, duration_ms,
source_uri, error, error_type)``，无论成功还是失败。复制或移动算作一条操作，即使它
实际上是由一次下载与一次上传完成。查询类操作（``exists``、``stat``、
``list_dir``、``checksum``）不会报告。

内置的监听者会在存储本身失败时发布 ``StorageError`` 事件：访问被拒、后端不可用、
暂时性失败，或后端无法分类的错误。文件不存在、目标已存在或 URI 格式错误属于调用方
的错误：只会抛给调用方，不会产生事件。
