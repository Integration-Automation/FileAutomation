事件
====

每個元件都以 :class:`~automation_file.Event` 的形式，把發生的事回報到
:data:`~automation_file.event_bus`。使用端訂閱事件匯流排即可；沒有任何元件會直接
呼叫通知接收端或寫入稽核紀錄。

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

事件不可變，且可直接轉成 JSON（``event.to_dict()``）。

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - 欄位
     - 意義
   * - ``type``
     - 事件種類，以點分隔的名稱表示：``pipeline.failed``。
   * - ``severity``
     - ``Severity.INFO``、``WARNING``、``ERROR`` 或 ``CRITICAL``。每個事件類別都有
       預設值，發出者可以覆寫。
   * - ``source``
     - 回報的元件：``pipeline``、``integrity``、``scheduler``、``storage``、
       ``system``。
   * - ``subject``
     - 給人看的一行摘要。
   * - ``payload``
     - 細節，使用約定的鍵：``pipeline``、``run_id``、``task``、``attempt``、
       ``action``、``resource``、``backend``、``status``、``duration_ms``、
       ``error``、``job``、``trigger``。
   * - ``correlation_id``
     - 把屬於同一次執行的所有事物串在一起。
   * - ``actor``
     - 這件事是代表誰執行的。
   * - ``id``、``timestamp``
     - 唯一 ID 與 UTC 時間。

核心事件
--------

.. list-table::
   :header-rows: 1
   :widths: 34 30 36

   * - 類別
     - ``type``
     - 預設嚴重程度
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

``SystemErrorEvent`` 就是路線圖中的「SystemError」；較短的名稱會遮蔽 Python 內建的
例外。

訂閱
----

``event_bus.subscribe(handler, types=None, min_severity=Severity.INFO)`` 可依事件
類別（包含子類別）、完整的 type 名稱或前綴（``"pipeline.*"``）比對；不指定
``types`` 時，處理函式會收到所有事件。``publish`` 在發布者的執行緒中，依訂閱順序
逐一傳遞，並回傳收到事件的處理函式數量。處理函式若拋出例外，只會被記錄並略過，
因此有問題的使用端永遠不會影響回報事件的程式。處理函式應保持快速；耗時的工作請
交給佇列或執行緒。

``event_bus.recent(limit, types, min_severity, correlation_id)`` 回傳匯流排記得的
最近事件（預設 500 筆），最新的在前。需要私有的匯流排時使用
:class:`~automation_file.EventBus`。

關聯 ID 與 actor
----------------

.. code-block:: python

   from automation_file import actor_scope, correlation_scope, emit, PipelineStarted

   with actor_scope("scheduler"), correlation_scope() as run_id:
       emit(PipelineStarted(source="pipeline", subject="daily-report started",
                            payload={"pipeline": "daily-report", "run_id": run_id}))
       ...   # 這裡面的每個事件與儲存操作都帶有 run_id 與 actor

``correlation_scope()`` 會沿用外層範圍的 ID，因此巢狀的工作共用最外層那次執行的
ID。在任何範圍之外，每個事件都有自己的 ID，actor 則是執行行程的使用者。範圍不會
自動跟著工作進入另一個執行緒；把工作分派出去的程式要在那裡重新進入範圍。

儲存操作
--------

儲存層會把 ``upload``、``download``、``read``、``delete``、``mkdir``、``copy`` 與
``move`` 回報給以 ``automation_file.storage.observe.add_listener`` 註冊的監聽者：
每次呼叫一筆 ``StorageOperation(operation, uri, backend, status, duration_ms,
source_uri, error, error_type)``，無論成功或失敗。複製或搬移算作一筆操作，即使它
實際上是由一次下載與一次上傳完成。查詢類操作（``exists``、``stat``、
``list_dir``、``checksum``）不會回報。

內建的監聽者會在儲存本身失敗時發布 ``StorageError`` 事件：存取被拒、後端無法
使用、暫時性失敗，或後端無法分類的錯誤。檔案不存在、目標已存在或 URI 格式錯誤
屬於呼叫方的錯誤：只會拋給呼叫方，不會產生事件。
