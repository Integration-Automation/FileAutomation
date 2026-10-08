管線（Pipeline）
====================

``automation_file.pipeline`` 依相依順序執行一組任務，互不相依的任務平行執行，並補上
週期性工作需要的功能：重試、逾時、取消、條件、冪等鍵、檢查點與續跑、試跑，以及執行
歷史。

任務可以是 Python 可呼叫物件，也可以是 ``FA_*`` 動作。管線可以用 Python 建立，也可以
寫成 YAML / JSON 文件。一次執行只透過事件匯流排上的事件回報（見 :doc:`event_bus`）；
它不會呼叫任何通知 sink，也不會寫入稽核紀錄。

:func:`~automation_file.execute_action_dag`\ （見 :doc:`dag`）維持不變。它把一份動作
清單執行一次並回傳結果；當執行需要被記錄、重試、續跑或觀察時，請改用管線。

最小範例
----------------

.. code-block:: python

   from automation_file.pipeline import Pipeline

   def count_rows(ctx):
       return len(ctx.results["read"].splitlines())

   pipeline = Pipeline("row-count")
   pipeline.task("read", ["FA_storage_read_text", {"uri": "local:///data/report.csv"}])
   pipeline.task("count", count_rows, depends_on=["read"])

   run = pipeline.run()
   run.status                      # RunStatus.SUCCEEDED；等於 "succeeded"
   run.tasks["count"].result       # 42
   run.tasks["count"].attempts     # 1

``run()`` 在所有任務都結束後才回傳。任務失敗不會拋出例外：結果記在 ``run.status``
以及 ``run.tasks`` 的每個項目上。

正式環境範例
------------------------

一個每晚執行的工作：以重試與逾時抓取檔案、檢查內容、同一個日期最多發布一次、發布
失敗時收回發布到一半的報表，並把執行紀錄存進 SQLite 檔案，讓失敗的執行可以續跑。

.. code-block:: python

   from automation_file.pipeline import Pipeline, RetryPolicy, SQLiteRunStore

   WORK = "local:///var/tmp/report-${params.date}.csv"
   TARGET = "azure://reports/${params.date}.csv"
   store = SQLiteRunStore("/var/lib/automation/pipelines.db")

   def check(ctx):
       ctx.cancel.raise_if_cancelled()               # 被取消或逾時就停下來
       if ctx.results["download"]["size"] == 0:
           raise ValueError("the report is empty")   # 任務以拋出例外表示失敗
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
       idempotency_key="publish-${params.date}",     # 同一個日期絕不發布兩次
   )
   pipeline.task(
       "withdraw",                                   # 清理：只在 publish 失敗時執行
       ["FA_storage_delete", {"uri": TARGET, "missing_ok": True}],
       depends_on=["publish"],
       when="on_failure",
   )
   pipeline.task("tidy", ["FA_storage_delete", {"uri": WORK}], depends_on=["publish"])

   run = pipeline.run(params={"date": "2026-10-08"}, store=store)
   if run.status != "succeeded":
       for task_id, state in run.tasks.items():
           print(task_id, state.status.value, state.error or state.reason or "")

   # 稍後，在同一個或另一個行程中，等原因排除之後：
   run = pipeline.resume(run.run_id, store=store)    # 只執行尚未成功的部分

``publish`` 三次嘗試都失敗時，``withdraw`` 會執行，``tidy`` 被略過，這次執行的狀態為
``failed``。``resume`` 保留 ``download`` 與 ``check``，重新執行 ``publish``，接著執行
``tidy``。之後同一個日期的另一次執行會重新下載與檢查，但略過 ``publish``：它的鍵已經
成功過。

同一條管線不寫 Python 的版本，存成 ``daily-report.yaml``。``check`` 是可呼叫物件，無法
寫進文件，所以這個版本直接發布下載到的內容：

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

任務
--------

任務要做的事有兩種寫法。

**可呼叫物件**：接收一個 :class:`~automation_file.pipeline.model.TaskContext`。它的
回傳值就是任務的結果；拋出例外則任務失敗。

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - 欄位
     - 意義
   * - ``pipeline``
     - 管線的名稱。
   * - ``run_id``
     - 這次執行的 ID，同時也是每個事件的關聯 ID。
   * - ``task``
     - 任務的 ID。
   * - ``attempt``
     - 第幾次嘗試，從 1 開始（在 ``when`` 可呼叫物件中為 ``0``）。
   * - ``params``
     - 這次執行的參數，唯讀：管線的預設值，再由 ``run(params=...)`` 覆寫。
   * - ``results``
     - 任務 ID 對應到結果，唯讀，涵蓋所有成功的上游任務，不論是否直接相依。失敗
       或被略過的任務不會出現在其中。
   * - ``cancel``
     - ``CancellationToken``。執行被取消或任務逾時後會被設定。見 `逾時`_。
   * - ``dry_run``
     - 永遠是 ``False``：試跑不會執行任何東西。

**動作**：三種形式之一，``[name]``、``[name, {kwargs}]`` 與 ``[name, [args]]``。名稱
會在共用執行器的註冊表（或傳給管線的 ``registry=``）中查找，並直接呼叫該指令，因此
失敗時例外會拋進任務。在引數中，不論巢狀多深：

* ``${params.<name>}`` 會被換成該參數。夾在較長的文字中時以文字插入；整個字串剛好
  就是一個占位符時，會換成參數本身，所以 ``"${params.limit}"`` 仍然是數字 ``20``。
* 整個字串剛好是 ``${tasks.<id>.result}`` 時，會換成該上游任務的結果物件（若它沒有
  成功則為 ``None``）。該任務必須是上游任務，而且這個占位符不能夾在較長的文字中。

這裡沒有運算式語言，也不會對任何內容求值。其他的 ``${...}`` 文字會原樣傳遞。由於
引數中的每個字串都會被檢查，把管線定義當成引數交給 ``FA_pipeline_run`` 時，其中的
占位符會被外層管線填入：請改為傳入檔案路徑。

任務 ID 與參數名稱是非空字串，不能包含空白、``.``、``$``、``{`` 或 ``}``。

選項
--------

``Pipeline(name, description="", max_workers=4, *, params=None, schedule=None, registry=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 選項
     - 意義
   * - ``name``
     - 在事件、歷史與冪等鍵中用來辨識這條管線。
   * - ``description``
     - 自由文字，保存在定義中。
   * - ``max_workers``
     - 同時執行的任務數量上限。預設為 ``4``。
   * - ``params``
     - 預設參數；``run(params=...)`` 會加入並覆寫它們。
   * - ``schedule``
     - ``Schedule(cron, timezone=None)``。保存在 ``pipeline.schedule`` 供排程器
       使用，管線本身不會據此行動。
   * - ``registry``
     - 查找動作名稱的地方。預設：共用執行器的註冊表。

``pipeline.task(task_id, work, *, depends_on=None, retry=None, timeout=None, when="on_success", idempotency_key=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 選項
     - 意義
   * - ``task_id``
     - 在管線中必須唯一。加入第二個相同 ID 的任務會立刻被拒絕。
   * - ``work``
     - 可呼叫物件或動作。
   * - ``depends_on``
     - 必須先結束的任務 ID。可以先寫出尚未加入的任務；相依圖在管線執行時才
       檢查。
   * - ``retry``
     - ``RetryPolicy``。預設：只嘗試一次。見 `重試`_。
   * - ``timeout``
     - 整個任務可用的秒數。預設：沒有限制。見 `逾時`_。
   * - ``when``
     - ``"on_success"``\ （預設）、``"on_failure"``、``"always"`` 或可呼叫物件。
       見 `條件`_。
   * - ``idempotency_key``
     - 可含 ``${params.<name>}`` 占位符的文字。見 `冪等`_。

``RetryPolicy(max_attempts=1, backoff_base=0.0, backoff_cap=60.0, retry_on=(...))``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 選項
     - 意義
   * - ``max_attempts``
     - 總共嘗試幾次；``1`` 表示不重試。
   * - ``backoff_base``
     - 第一次嘗試失敗後等待的秒數；之後每失敗一次就加倍。
   * - ``backoff_cap``
     - 等待時間的上限。
   * - ``retry_on``
     - 值得再試一次的例外類別。預設：``StorageTransientException``、
       ``ConnectionError``、``TimeoutError``。

``pipeline.run(params=None, *, dry_run=False, store=None, cancel=None, bus=None)``、
``pipeline.start(params=None, *, store=None, cancel=None, bus=None)`` 與
``pipeline.resume(run_id, *, store=None, cancel=None, bus=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 選項
     - 意義
   * - ``params``
     - 這次執行的參數。
   * - ``dry_run``
     - 只規劃而不執行。見 `試跑`_。
   * - ``store``
     - 記錄這次執行的 ``RunStore``。預設：預設的儲存。
   * - ``cancel``
     - ``CancellationToken``，被設定時會停止這次執行。
   * - ``bus``
     - 接收事件的 ``EventBus``。預設：整個行程共用的匯流排。
   * - ``run_id``
     - 用於 ``resume``：要接續的那次執行。

``run`` 在呼叫它的執行緒中工作，並回傳已結束的
:class:`~automation_file.pipeline.model.PipelineRun`。``start`` 立刻回傳執行物件，
並在背景執行緒中工作：``run.wait(timeout)`` 會等到它結束（並回傳是否已結束），
``run.done`` 不等待就能得知，``run.cancel()`` 則會停止它。已啟動的執行還沒結束時，
直譯器不會結束。

在任何任務開始之前，``run``、``start`` 與 ``resume`` 會對以下情況拋出
``PipelineDefinitionException``：管線是空的、相依的任務不存在或重複、任務相依於
自己、相依圖有循環、占位符格式錯誤、結果占位符指向不是上游的任務，以及占位符用到
這次執行沒有提供的參數。``error.problems`` 列出每一項問題及其路徑；
``pipeline.problems()`` 回傳同一份清單但不拋出例外。

狀態
--------

``run.tasks[task_id].status`` 是 ``TaskStatus``，``run.status`` 是 ``RunStatus``。
兩者都可以直接與它們的文字比較。

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - 任務狀態
     - 意義
   * - ``pending``
     - 尚未開始。
   * - ``running``
     - 正在進行某一次嘗試，或正在兩次嘗試之間等待。
   * - ``succeeded``
     - 已回傳；``result`` 保存回傳值。
   * - ``failed``
     - 拋出了例外，而且沒有剩餘的嘗試次數；``error`` 的形式為
       ``"<ExceptionType>: <message>"``。
   * - ``skipped``
     - 沒有執行；``reason`` 說明原因（見下表）。
   * - ``timeout``
     - 沒有在逾時時間內完成。
   * - ``cancelled``
     - 執行在它開始之前或執行期間被取消，或任務拋出了 ``CancelledException``。
   * - ``planned``
     - 試跑：它會依這個順序被考慮。

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - 略過的 ``reason``
     - 意義
   * - ``idempotent``
     - 它的冪等鍵已經有一次成功的執行；沿用儲存的結果，相依於它的任務照常執行。
   * - ``condition``
     - 它自己的 ``on_failure`` 條件或可呼叫條件沒有成立。
   * - ``upstream_failed``
     - ``on_success`` 任務，而它的某個相依任務失敗、逾時或被取消。
   * - ``upstream_skipped``
     - ``on_success`` 任務，而它的某個相依任務被略過。

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - 執行狀態
     - 意義
   * - ``running``
     - 尚未結束。
   * - ``succeeded``
     - 每個任務都成功或被略過。
   * - ``failed``
     - 至少有一個任務失敗、逾時或被取消；``run.error`` 會列出它們。清理任務成功
       並不會改變這個結果。
   * - ``cancelled``
     - 執行被取消，而且至少有一個任務因此沒有執行。

任務狀態還有 ``attempts``、``started_at`` 與 ``finished_at``\ （UTC）、
``duration_ms``、``level``\ （沒有相依的任務為 0）以及 ``idempotency_key``\ （已填入
占位符的鍵）。``run.tasks`` 依相依順序排列，``run.to_dict()`` 可以序列化為 JSON。

條件
--------

``when`` 只在任務的所有相依任務都結束時檢查一次。

``"on_success"``
    每個相依任務都成功（或以 ``idempotent`` 被略過）。否則任務被略過，而且這會
    傳到它自己的 ``on_success`` 下游任務。

``"on_failure"``
    至少有一個相依任務失敗、逾時或被取消。用於清理。只是被略過的相依任務不算。

``"always"``
    不論相依任務的結果如何。

可呼叫物件 ``(TaskContext) -> bool``
    回傳真值時任務才執行。它獨自決定：不會參考相依任務的結果，但 ``ctx.results``
    只包含成功的那些。可呼叫物件拋出例外時，任務為 ``failed``。

重試
--------

一次嘗試失敗後，如果還有剩餘次數，而且例外是 ``retry_on`` 中某個類別的實例，任務
就會再試一次。第 ``n + 1`` 次嘗試之前等待 ``backoff_base * 2 ** (n - 1)`` 秒，最多
``backoff_cap`` 秒。

預設的 ``retry_on`` 只包含暫時性的錯誤。``ValueError`` 或 ``KeyError`` 代表程式錯誤
或輸入有誤，第一次嘗試就會失敗。請把 ``retry_on`` 放寬到你確知是暫時性的錯誤，絕對
不要放寬到 ``Exception``。

逾時
--------

``timeout`` 是整個任務可用的秒數：包含每一次嘗試以及嘗試之間的等待。用完之後，任務
被記錄為 ``timeout``，它的取消權杖被設定，其餘任務繼續執行。

**執行緒無法被強制終止。**\ 可呼叫物件會繼續執行直到它自己返回，而它在逾時之後回傳
或拋出的任何東西都會被忽略。因此執行時間長的可呼叫物件必須檢查自己的權杖：

.. code-block:: python

   def export(ctx):
       for chunk in chunks():
           ctx.cancel.raise_if_cancelled()     # 拋出 CancelledException
           write(chunk)

動作無法檢查權杖；動作本身若有逾時參數，請為長時間的傳輸設定它。逾時的任務不再
計入 ``max_workers``。任務執行緒是 daemon 執行緒，所以永不返回的執行緒不會讓直譯器
無法結束。

取消
--------

``run.cancel()``，或設定以 ``cancel=`` 傳入的 ``CancellationToken``，會在百分之幾秒內
停止一次執行：

* 所有尚未開始的任務變成 ``cancelled``，清理任務也一樣；
* 所有執行中任務的權杖被設定。執行會等待這些任務，而每個任務保留它實際的結果：
  拋出 ``CancelledException`` 的為 ``cancelled``，照樣完成的為 ``succeeded``；
* 正在兩次嘗試之間等待的任務會停止等待，變成 ``cancelled``。

.. code-block:: python

   run = pipeline.start(params={"date": "2026-10-08"})
   ...
   run.cancel()
   run.wait(30)
   run.status                      # "cancelled"

冪等
--------

帶有 ``idempotency_key`` 的任務，一旦以該鍵成功過，就不會再次執行。任務開始之前，
會以這次執行的參數算出鍵，並在儲存中查找相同管線名稱與任務 ID 的紀錄。找到成功的
執行時，任務為 ``skipped``，原因是 ``idempotent``，它的 ``result`` 是儲存的那一份，
相依於它的任務會像它成功了一樣照常執行。

鍵的持久程度取決於儲存：使用預設的記憶體儲存時，只維持到行程結束；使用
``SQLiteRunStore`` 時，重新啟動後仍然有效。它不是鎖：同時開始的兩次執行可能都查不到
紀錄，於是都執行該任務。如果儲存無法讀取，任務會失敗而不是照常執行。

檢查點與續跑
------------------------

任務的每一次狀態轉換都會在發生當下寫入儲存：每次嘗試的開始、每次失敗的嘗試，以及
最後的結果。``pipeline.resume(run_id)`` 載入該次執行，保留 ``succeeded`` 的任務及其
結果，並以相同的執行 ID 與相同的參數重新執行其餘任務。

.. code-block:: python

   store = SQLiteRunStore("pipelines.db")
   run = pipeline.run(params={"date": "2026-10-08"}, store=store)
   # ... 行程可能在這裡結束 ...
   pipeline = build_pipeline()                    # 相同的任務
   run = pipeline.resume(run.run_id, store=SQLiteRunStore("pipelines.db"))

儲存保存的是一次執行的狀態，而不是管線本身：``resume`` 要在名稱相同的管線上呼叫。
結果以 JSON 儲存；JSON 無法表示的值會以它的 ``repr`` 儲存，並設定
``result_is_repr``，所以續跑之後下游任務看到的是那段文字。其他任務需要用到的結果，
請讓任務回傳 JSON 資料。已經成功的執行會照儲存的內容原樣回傳。不要續跑仍在別處
執行中的執行。

被保留的任務不會再執行一次，所以它產生的東西必須還在。清理任務應該移除失敗任務
留下的東西，而不是某個已成功、後續任務還需要的任務的輸出。

試跑
--------

``pipeline.run(dry_run=True)`` 不執行任何東西、不記錄任何東西，也不發布任何事件。
每個任務都以 ``planned`` 回傳，依相依順序排列並帶有 ``level``。註冊表中找不到的動作
名稱，以及用到缺少參數的占位符，會回報在任務的 ``error`` 中；這時執行狀態為
``failed``，否則為 ``succeeded``。相依圖有問題時仍然會拋出例外。

.. code-block:: python

   plan = pipeline.run(params={"date": "2026-10-08"}, dry_run=True)
   for task_id, state in plan.tasks.items():
       print(state.level, task_id, state.error or "ok")

執行紀錄儲存與歷史
------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 儲存
     - 執行紀錄保存在
   * - ``MemoryRunStore(max_runs=1000)``
     - 記憶體中，維持到行程結束；最舊的執行最先被捨棄。這是預設的儲存。
   * - ``SQLiteRunStore(path)``
     - SQLite 檔案中。執行緒安全、只使用參數化陳述式、每次轉換提交一次，檔案中
       帶有結構版本。

.. code-block:: python

   from automation_file.pipeline import SQLiteRunStore, set_default_run_store

   store = SQLiteRunStore("/var/lib/automation/pipelines.db")
   set_default_run_store(store)                    # 供 run()、resume() 與動作使用

   store.get_run(run_id)                           # PipelineRun，或 None
   store.list_runs("daily-report", limit=10)       # 最新的在前
   store.find_idempotent("daily-report", "publish", "publish-2026-10-08")

自訂的儲存要繼承 ``RunStore``，並實作 ``save_run``、``save_task``、``get_run``、
``list_runs`` 與 ``find_idempotent``；無法讀取或寫入時拋出 ``PipelineException``。
參數與結果會原樣儲存：不要把密碼與權杖放進其中任何一個。

定義檔
------------

定義是一份帶有 ``schema_version: 1`` 的對應表，來源可以是 YAML、JSON 或 Python。

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 鍵
     - 值
   * - ``schema_version``
     - ``1``。必填；沒有這個鍵或值不同的文件會被拒絕。
   * - ``name``
     - 必填。
   * - ``description``、``max_workers``、``params``
     - 與 ``Pipeline`` 的選項相同。
   * - ``schedule``
     - ``{cron: "0 2 * * *", timezone: Asia/Taipei}``。``cron`` 有五個欄位；
       ``timezone`` 可省略。
   * - ``tasks``
     - 必填。任務 ID 對應到任務。
   * - ``tasks.<id>.action``
     - 必填。``[name]``、``[name, {kwargs}]`` 或 ``[name, [args]]``。
   * - ``tasks.<id>.depends_on``
     - 任務 ID 的清單。
   * - ``tasks.<id>.retry``
     - ``{max_attempts, backoff, backoff_cap, on}``。``on`` 列出例外名稱：
       ``automation_file.exceptions`` 中的類別、``TimeoutError``、
       ``ConnectionError`` 與 ``OSError``。其他名稱都是錯誤。
   * - ``tasks.<id>.timeout``
     - 秒數，必須大於 0。
   * - ``tasks.<id>.when``
     - ``on_success``、``on_failure`` 或 ``always``。
   * - ``tasks.<id>.idempotency_key``
     - 可含 ``${params.<name>}`` 占位符的文字。

.. code-block:: python

   from automation_file.pipeline import PIPELINE_SCHEMA, Pipeline, validate_definition

   validate_definition(document)        # 有效時為 []，否則是每一項問題及其路徑
   # ["max_workers: expected an integer >= 1, got 0",
   #  "tasks.verify.depends_on[0]: unknown task 'x'"]

   pipeline = Pipeline.from_dict(document)          # 會拋出 PipelineDefinitionException
   pipeline = Pipeline.from_file("daily-report.yaml")   # .yaml、.yml 或 .json
   pipeline.to_dict()                               # 定義文件，省略預設值
   PIPELINE_SCHEMA                                  # JSON Schema（draft 2020-12），是一個 dict

每一層出現未知的鍵都是錯誤。管線中含有 Python 可呼叫物件時，``to_dict`` 會拋出
例外，因為文件無法表示它。

YAML 以 ``yaml.safe_load`` 讀取。YAML 的三種行為已經處理：

* 同一個對應表中重複的鍵是錯誤（JSON 也一樣），所以第二個相同 ID 的任務不會無聲地
  取代第一個。
* YAML 1.1 會把沒有加引號的 ``on`` 讀成 ``true``。``from_file`` 會把 ``retry`` 底下
  的這個鍵還原為 ``on``；如果你自己解析 YAML，請寫成 ``"on"``。
* 沒有加引號的日期（例如 ``2026-10-08``）會變成日期物件，定義無法保存它。驗證會
  指出這一點：請為日期與時間加上引號。

事件
--------

每個事件的 ``source`` 都是 ``"pipeline"``，``correlation_id`` 都是執行 ID，從任務的
執行緒發布時也一樣。在任務內部發布的事件（例如儲存錯誤）帶有相同的關聯 ID，以及
啟動這次執行的程式的 actor。

.. list-table::
   :header-rows: 1
   :widths: 24 16 60

   * - 事件
     - 嚴重程度
     - 發布時機
   * - ``pipeline.started``
     - info
     - 一次，在第一個任務之前。續跑時會再發布一次。
   * - ``task.started``
     - info
     - 每次嘗試開始時。
   * - ``task.completed``
     - info
     - 某次嘗試成功時。
   * - ``task.failed``
     - warning / error
     - 某次嘗試失敗時。``status`` 為 ``retrying``\ （warning：接著還有一次
       嘗試）、``failed``、``timeout`` 或 ``cancelled``\ （warning）。
   * - ``pipeline.completed``
     - info
     - 執行以 ``succeeded`` 結束時。
   * - ``pipeline.failed``
     - error / warning
     - 執行以 ``failed`` 或 ``cancelled``\ （warning）結束時。

payload 使用共用的鍵：``pipeline``、``run_id``、``status``，任務事件另有 ``task`` 與
``attempt``；某件事結束時有 ``duration_ms``，出錯時有 ``error``。被略過的任務，以及
開始之前就被取消的任務，不會發布任何事件：它的狀態記在執行上。``when`` 可呼叫物件
拋出例外，或冪等鍵無法查找的任務，會發布一個 ``attempt`` 為 0 的 ``task.failed``。
試跑不會發布任何事件。

.. code-block:: python

   from automation_file import Severity, event_bus

   def alert(event):
       print(event.subject, event.payload.get("error"))

   event_bus.subscribe(alert, types=["pipeline.failed", "task.failed"],
                       min_severity=Severity.ERROR)

動作
--------

管線也能從 JSON 動作清單使用，因此 CLI、TCP 與 HTTP 動作伺服器以及 MCP 主機都能
呼叫。``definition`` 是一份對應表，或 ``.yaml`` / ``.yml`` / ``.json`` 檔案的路徑。

.. list-table::
   :header-rows: 1
   :widths: 26 40 34

   * - 動作
     - 參數
     - 回傳值
   * - ``FA_pipeline_run``
     - ``definition, params=None, dry_run=False``
     - 這次執行（``PipelineRun.to_dict()``）
   * - ``FA_pipeline_validate``
     - ``definition``
     - ``{"valid": …, "errors": […]}``
   * - ``FA_pipeline_status``
     - ``run_id``
     - 已記錄的執行
   * - ``FA_pipeline_history``
     - ``pipeline=None, limit=20``
     - 已記錄的執行，最新的在前
   * - ``FA_pipeline_resume``
     - ``run_id, definition``
     - 續跑之後的執行

.. code-block:: json

   [
     ["FA_pipeline_validate", {"definition": "pipelines/daily-report.yaml"}],
     ["FA_pipeline_run", {"definition": "pipelines/daily-report.yaml",
                          "params": {"date": "2026-10-08"}}],
     ["FA_pipeline_history", {"pipeline": "daily-report", "limit": 5}]
   ]

這些動作使用預設的執行紀錄儲存，因此 ``FA_pipeline_status``、``FA_pipeline_history``
與 ``FA_pipeline_resume`` 看到的是同一個行程中的執行，除非已用
``set_default_run_store`` 指定 ``SQLiteRunStore``。任務失敗時，``FA_pipeline_run``
回傳 ``status`` 為 ``failed`` 的執行；只有定義無法載入或無效時才會拋出例外。
``register_pipeline_ops(registry)`` 可把這些動作加入你自己的註冊表。

定義會寫出它的任務要呼叫哪些動作。只要定義本身包含在請求裡，TCP 或 HTTP 動作伺服器上的
:class:`~automation_file.ActionACL` 與 MCP 伺服器的 ``--allowed-actions`` 也都會檢查
這些名稱。兩者都看不到以檔案路徑指定的定義，也看不到 ``FA_pipeline_resume`` 所接續的
已儲存執行：請只對可以呼叫全部已註冊動作的用戶端開放 ``FA_pipeline_run`` 與
``FA_pipeline_resume``，或把定義檔放在這些用戶端無法寫入的位置。

出問題時
----------------

任務失敗
    ``run.status`` 為 ``failed``，``run.error`` 列出這些任務，每個任務狀態都有
    ``error``、``attempts`` 與時間。排除原因之後呼叫 ``resume(run_id)``：已成功的
    部分不會重做。

任務沒有執行
    請看 ``reason``。``upstream_failed`` 與 ``upstream_skipped`` 指向某個相依任務；
    無論如何都必須執行的任務請設定 ``when="always"``。

工作出了問題，任務卻成功
    任務只有在拋出例外時才算失敗。以回傳值回報的動作會讓任務成功：
    ``FA_storage_verify`` 在不相符時回傳 ``false``，除非傳入 ``strict: true``，此時它會
    拋出 ``StorageChecksumException``，任務因而失敗。其他這類回傳值，請在會拋出例外的
    可呼叫物件中，或在下一個任務的可呼叫 ``when`` 中檢查。

任務從不重試
    它的例外不在 ``retry_on`` 中。預設只涵蓋 ``StorageTransientException``、
    ``ConnectionError`` 與 ``TimeoutError``。

任務已經 ``timeout``，卻好像還在工作
    它的執行緒無法被停止。請讓可呼叫物件檢查 ``ctx.cancel``，並確保第二次執行不會
    與第一次遺留的工作相衝突。

執行被中斷（行程結束、Ctrl-C）
    儲存中有到那一刻為止的每一次轉換，其中可能有任務停在 ``running``。
    ``resume(run_id)`` 會執行所有尚未成功的任務。

還沒執行任何任務就拋出 ``PipelineDefinitionException``
    定義有誤。``error.problems`` 保存每一項問題及其路徑；``validate_definition``
    與試跑可以在不執行的情況下取得它們。

歷史不完整
    儲存無法寫入時會記錄為錯誤，執行則繼續進行。執行本身是正確的；它的紀錄則
    不是。

兩個例外，``PipelineException`` 與其子類別 ``PipelineDefinitionException``，都衍生自
``FileAutomationException``。
