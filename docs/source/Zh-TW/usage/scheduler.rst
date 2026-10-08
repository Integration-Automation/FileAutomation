排程器（Scheduler）
========================

``automation_file.scheduler`` 會在某件事觸發時執行一份動作清單或一條
:doc:`管線 <pipeline>`\ ：可以帶時區的 cron 運算式、檔案事件、事件匯流排上的事件、
另一條管線的執行結束，或是一次呼叫。cron 只是多種觸發器之一，所有工作都經過同一個
排程器。

每一次觸發都會留下一筆紀錄，狀態是七種之一：``scheduled``、``started``、
``completed``、``failed``、``skipped``、``timeout`` 與 ``cancelled``。除非工作自己
允許，否則它不會與自己重疊；一次執行可以設定逾時，也可以被取消；失敗或逾時的執行會
發布成 ``scheduler.error`` 事件（見 :doc:`event_bus`）。

最小範例
----------------

.. code-block:: python

   from automation_file.scheduler import scheduler

   scheduler.add(
       "nightly-snapshot",
       "0 2 * * *",                              # 每天 02:00 ...
       [["FA_zip_dir", {"dir_we_want_to_zip": "/data",
                        "zip_name": "/backup/data_nightly"}]],
       timezone="Asia/Taipei",                   # ... 台北時間；不給就是本地時間
   )

   scheduler.history(job="nightly-snapshot", limit=5)    # 最近的執行，最新的在前

``scheduler`` 是整個行程共用的實例。加入第一個工作時會啟動它的背景執行緒；那是
daemon 執行緒，行程要靠你自己保持存活。

正式環境範例
------------------------

每晚台北時間 02:00 執行一條管線，第一條成功之後執行第二條管線，並在某次執行失敗或
跑太久時通知團隊。

.. code-block:: python

   import os

   from automation_file import Route, SlackSink, notification_manager, notification_router
   from automation_file.pipeline import SQLiteRunStore, set_default_run_store
   from automation_file.scheduler import PipelineTrigger, scheduler

   # 排程的管線把執行紀錄寫進預設的執行紀錄儲存。
   set_default_run_store(SQLiteRunStore("/var/lib/automation/pipelines.db"))

   # 失敗或逾時的執行是一個 scheduler.error 事件；這條路由負責送出它。
   notification_manager.register(SlackSink(os.environ["SLACK_WEBHOOK"], name="team-alerts"))
   notification_router.add_route(
       Route("scheduler-failures", sinks=("team-alerts",), types=("scheduler.error",))
   )
   notification_router.start()

   # daily-report.yaml 宣告了   schedule: {cron: "0 2 * * *", timezone: Asia/Taipei}
   scheduler.add_pipeline(
       "pipelines/daily-report.yaml",
       params={"date": "${date:%Y-%m-%d}"},      # 工作觸發當下的台北日期
       timeout=3600,                             # 一小時後取消
   )

   # 沒有自己的排程：每當 daily-report 的一次執行成功，它就會執行。
   scheduler.add_pipeline(
       "pipelines/publish-summary.yaml",
       triggers=PipelineTrigger("daily-report"),
       timeout=900,
   )

   for run in scheduler.history(state="failed", limit=10):
       print(run.job, run.scheduled_at, run.error, run.correlation_id)

``daily-report`` 在 UTC 18:00 啟動，也就是台北的 02:00，``date`` 則是台北的日期。它的
執行以 ``succeeded`` 結束時，``publish-summary`` 會被觸發；它失敗時，``publish-summary``
不會被觸發，路由則送出 ``[ERROR] scheduler.error: scheduler[daily-report] failed``。
``daily-report`` 的一次執行還在進行時，下一次觸發會記錄為 ``skipped``。

失敗的管線自己也會發布 ``pipeline.failed`` 與 ``task.failed``。請把這兩者或
``scheduler.error`` 其中一邊路由到 sink；同時涵蓋兩邊的路由會為一次失敗送出兩則訊息。

工作與目標
--------------------

一個工作有名稱、目標，以及任意數量的觸發器。

**動作清單**\ 透過共用的執行器執行，一個動作接著一個動作。拋出例外的動作會讓這次
執行失敗，其餘的動作仍會執行，與 ``execute_action`` 相同。動作的回傳值不會保留。

**管線**\ 可以是 :class:`~automation_file.pipeline.Pipeline`、定義的對應表，或是
``.yaml`` / ``.yml`` / ``.json`` 定義檔的路徑。定義在工作註冊時檢查，檔案也只在那一刻
讀取一次：修改檔案之後，請移除工作再重新註冊。每一次觸發都以預設的執行紀錄儲存呼叫
``pipeline.run()``，所以 ``FA_pipeline_status`` 與 ``FA_pipeline_history`` 看得到這次
執行。

``add_pipeline`` 會讀取管線的 ``schedule``，把它變成 cron 觸發器，時區也一併帶入；
除非給了 ``name``，工作會以管線的名稱命名。``add_job`` 也接受管線，但不會讀取它的
``schedule``。

``params`` 是管線工作每一次執行的參數；它們會加到管線自己的預設值上並覆寫同名的
項目。在任何深度的字串中，``${date:FORMAT}`` 會在工作觸發時被取代（``FORMAT`` 是
``strftime`` 格式；單獨的 ``${date}`` 會得到 ``2026-10-08T02:00:00``）。使用的是工作
自己的時間：第一個 cron 觸發器的時區，沒有 cron 觸發器時則是本地時間。除此之外不會
取代任何東西，動作清單也不接受 ``params``。

觸發器
------------

.. list-table::
   :header-rows: 1
   :widths: 14 36 50

   * - 種類
     - Python 寫法
     - 何時觸發
   * - ``cron``
     - ``CronTrigger(cron, timezone=None)``
     - 在運算式指定的那些分鐘。
   * - ``manual``
     - ``scheduler.run_now(name)``
     - 被呼叫時。每個工作都能這樣觸發。
   * - ``file``
     - ``FileTrigger(path, events=("created", "modified"), recursive=True)``
     - ``path`` 底下的檔案被建立、修改、刪除或搬移時。
   * - ``event``
     - ``EventTrigger(types=(), sources=(), min_severity=Severity.INFO)``
     - 事件匯流排上發布了符合條件的事件時。
   * - ``pipeline``
     - ``PipelineTrigger(pipeline, when="on_success")``
     - 指定名稱的管線有一次執行結束時。

.. code-block:: python

   from automation_file.scheduler import (
       CronTrigger, EventTrigger, FileTrigger, PipelineTrigger, scheduler,
   )

   scheduler.add_job(
       "sweep-inbox",
       [["FA_copy_all_file_to_dir", {"source_dir": "/data/inbox",
                                     "target_dir": "/data/processed"}]],
       triggers=[
           CronTrigger("*/30 * * * *", "UTC"),                      # 每半小時
           FileTrigger("/data/inbox", events=["created"]),          # 以及有新檔案時
       ],
   )

一個工作可以有好幾個任何種類的觸發器，重疊保護涵蓋全部。沒有觸發器的工作只在手動
觸發時執行。

Cron
~~~~

五個欄位：分（0-59）、時（0-23）、日（1-31）、月（1-12）與星期（0-6，星期日是 0 或
7）。每個欄位都接受 ``*``、單一值、區間 ``a-b``、清單 ``a,b,c``，以及步長 ``*/n`` 或
``a-b/n``；月份與星期還接受 ``jan``..``dec`` 與 ``sun``..``sat``。沒有秒，也沒有
``@daily`` 這類別名。

排程器每秒看一次時鐘，每一分鐘只處理一次。行程沒在執行或機器在睡眠的那些分鐘，事後
不會補跑。時區請見 `時區與日光節約時間`_。

手動
~~~~~~~~

.. code-block:: python

   run = scheduler.run_now("nightly-snapshot")     # 一個 JobRun
   run.wait(600)                                   # 執行結束後為 True
   run.state                                       # RunState.COMPLETED；等於 "completed"

``run_now`` 會立刻回傳這次觸發的紀錄。工作還在執行且不允許重疊時，紀錄是
``skipped``。在 JSON 中，也就是透過 HTTP 動作伺服器時，它是 ``FA_schedule_run``。

檔案事件
~~~~~~~~~~~~~~~~

``FileTrigger`` 使用 :class:`~automation_file.trigger.FileWatcher`，也就是
``FA_watch_start`` 背後的監看器（見 :doc:`events`）。監看器歸排程器所有：它不會出現在
``FA_watch_list`` 中，工作被移除時它就停止。執行紀錄的 ``detail`` 記著檔案與事件
（``{"path": "/data/inbox/a.csv", "event": "created"}``）。

儲存一個檔案常常會產生好幾個事件。每一個都是一次觸發；工作還在執行時到達的那些會
記錄為 ``skipped``。

事件與 webhook
~~~~~~~~~~~~~~~~~~~~~~~~

``EventTrigger`` 比對的方式與匯流排相同：``types`` 中放 type 名稱（``"task.failed"``）、
前綴（``"pipeline.*"``）與事件類別，``sources`` 中放完全相符的 ``event.source`` 值，
另外還有最低嚴重程度。至少要給一個 type 或一個來源。

webhook 也是這樣觸發工作的。收到請求的程式碼發布一個事件，每個觸發器符合的工作都會
執行：

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

   # 在你的網頁框架的處理函式中，請求通過驗證之後：
   emit(DeployFinished(source="webhook", subject="release 1.4 deployed"))

對 HTTP 動作伺服器（見 :doc:`servers`）的請求也可以改用名稱觸發單一工作：
``[["FA_schedule_run", {"name": "smoke-test"}]]``。這樣的執行會記錄為 ``manual``。

觸發器的處理函式在發布事件的執行緒中執行，而且只負責啟動這次執行。由工作自己的執行
所發布的事件不會再次觸發該工作，所以監聽 ``scheduler.error`` 的工作不會因為自己的
失敗而不斷循環。

透過事件互相觸發的工作會形成一條鏈。會讓一條鏈超過 16 次執行的那次觸發不會啟動任何
東西：它會記錄為 ``skipped``，原因是 ``chain``，所以互相觸發的兩個工作會停下來，而不是
永遠持續下去。

管線相依
~~~~~~~~~~~~~~~~

``PipelineTrigger("daily-report")`` 會在名為 ``daily-report`` 的管線有一次執行結束時
觸發。``when`` 沿用管線自己的用詞：

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - ``when``
     - 在這次執行……時觸發
   * - ``"on_success"``
     - 成功。這是預設值。
   * - ``"on_failure"``
     - 失敗或被取消。
   * - ``"always"``
     - 結束，不論結果如何。

這個觸發器監聽 ``pipeline.completed`` 與 ``pipeline.failed``，所以它看得到排程器的
匯流排上該管線的每一次執行：排程器啟動的、用 ``pipeline.run()`` 啟動的，以及由
``FA_pipeline_run`` 啟動的。紀錄的 ``detail`` 記著觸發它的那次執行的管線、執行 ID 與
狀態。管線工作不能相依於自己的管線，而互相相依的兩條管線會被上述的鏈長度上限擋下。

選項
--------

``scheduler.add(name, cron_expression, action_list, *, allow_overlap=False, timezone=None, timeout=None)``

``scheduler.add_job(name, target, *, triggers=None, allow_overlap=False, timeout=None, params=None)``

``scheduler.add_pipeline(pipeline, *, name=None, triggers=None, allow_overlap=False, timeout=None, params=None)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 選項
     - 意義
   * - ``name``
     - 識別這個工作。第二個同名的工作會被拒絕。``add_pipeline`` 的預設值是管線的
       名稱。
   * - ``cron_expression``
     - ``add`` 的五個欄位。
   * - ``action_list`` / ``target`` / ``pipeline``
     - 工作要執行的東西。見 `工作與目標`_。
   * - ``triggers``
     - 一個或多個觸發器：物件，或它們的對應表（見 `動作`_）。
   * - ``allow_overlap``
     - 允許工作還在執行時就啟動新的觸發。預設 ``False``。
   * - ``timezone``
     - ``add`` 解讀運算式所用的時區。預設：本地時間。
   * - ``timeout``
     - 一次執行可以花的秒數，必須大於 0。預設：不限制。見 `逾時`_。
   * - ``params``
     - 管線工作每次執行的參數。

這三個方法都回傳工作的快照，也就是 ``scheduler.list()`` 為每個工作保存的對應表：

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 鍵
     - 值
   * - ``name``
     - 工作的名稱。
   * - ``cron``、``timezone``
     - 第一個 cron 觸發器的運算式與時區；工作沒有 cron 觸發器時是 ``""`` 與
       ``None``。
   * - ``triggers``
     - 以對應表表示的每一個觸發器。
   * - ``target``、``pipeline``、``actions``
     - ``"actions"`` 或 ``"pipeline"``、管線的名稱，以及清單中的動作數量。
   * - ``allow_overlap``、``timeout``
     - 與傳入的值相同。
   * - ``runs``、``skipped``
     - 啟動了幾次觸發，以及略過了幾次。
   * - ``running``
     - 是否還有執行的執行緒活著。見 `逾時`_。
   * - ``last_run``
     - 最後一次執行被觸發的時間，以工作自己的時間表示：工作有時區時帶偏移量，
       沒有時則是本地時間。
   * - ``last_state``
     - 最後一次執行結束時的狀態。

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - 呼叫
     - 作用
   * - ``remove(name)``、``remove_all()``
     - 移除工作並停止它們的觸發器。進行中的執行會繼續。
   * - ``list()``
     - 每個工作的快照。
   * - ``run_now(name)``
     - 手動觸發一個工作；回傳 ``JobRun``。
   * - ``cancel(name)``
     - 取消該工作進行中的執行；回傳它們的紀錄。
   * - ``history(job=None, state=None, limit=50)``
     - 最近的紀錄，最新的在前。
   * - ``start()``、``shutdown(timeout=5.0, *, cancel_running=False)``
     - 見 `啟動與停止`_。
   * - ``tick(now=None)``
     - 為手動驅動的排程器處理一次目前這一分鐘與逾時。見 `啟動與停止`_。

執行紀錄與狀態
----------------------------

``scheduler.history()`` 回傳 :class:`~automation_file.scheduler.JobRun` 物件；
``run.to_dict()`` 可以序列化成 JSON。

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 欄位
     - 意義
   * - ``run_id``
     - 這次觸發的 ID。
   * - ``job``
     - 工作的名稱。
   * - ``trigger``
     - ``cron``、``manual``、``file``、``event`` 或 ``pipeline``。
   * - ``detail``
     - 是什麼觸發了這次執行：運算式與時區、檔案與事件、事件的 type、ID、來源與
       主旨，或是管線、執行 ID 與狀態。
   * - ``target``、``pipeline``
     - ``"actions"`` 或 ``"pipeline"``，以及管線的名稱。
   * - ``state``
     - 一個 ``RunState``。它與自己的文字比較時相等。
   * - ``scheduled_at``
     - 這次執行應該開始的時間：對 cron 而言就是那一分鐘。
   * - ``started_at``、``finished_at``
     - 目標開始執行的時間，以及紀錄結案的時間。
   * - ``duration_ms``
     - 兩者之間的時間。
   * - ``error``
     - 出了什麼問題，用於 ``failed`` 與 ``timeout``。
   * - ``reason``
     - 被略過的觸發是 ``overlap`` 或 ``chain``，被取消的執行是
       ``cancelled``。
   * - ``correlation_id``
     - 這次執行的每個事件所帶的 ID。對動作清單而言它就是 ``run_id``。對管線而言，
       管線一開始執行它就變成管線的執行 ID，也就是 ``FA_pipeline_status`` 接受的
       那個 ID。

所有時間都是帶時區的 UTC。目標在 ``correlation_scope(run_id)`` 之內、以 actor
``scheduler`` 執行，所以這次執行的儲存錯誤與稽核紀錄都帶著同一個 ID。

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - 狀態
     - 意義
   * - ``scheduled``
     - 觸發已被接受，它的執行緒還沒開始。
   * - ``started``
     - 目標正在執行。
   * - ``completed``
     - 每個動作都回傳了，或管線的執行成功了。
   * - ``failed``
     - 至少一個動作拋出例外、管線的執行沒有成功，或目標根本無法執行。``error``
       會說明是哪一種。
   * - ``skipped``
     - 什麼都沒有啟動：工作還在執行而且不允許重疊，或是這次觸發落在一條 16 次執行的
       鏈的尾端。
   * - ``timeout``
     - 執行沒有在逾時時間內結束。
   * - ``cancelled``
     - ``cancel`` 停止了這次執行。

歷史保存在記憶體中，每個排程器各有一份，保留最近的 1000 筆紀錄
（``Scheduler(history_limit=...)``）；最舊的先被丟掉。它不會在行程結束後留存。排程
管線的執行同時也在管線的執行紀錄儲存中，而每一次失敗都是事件，:doc:`稽核軌跡 <audit>`
可以把它保存下來。

重疊保護
----------------

除非工作註冊時給了 ``allow_overlap=True``，否則在工作執行期間到達的觸發不會啟動任何
東西。它會記錄為 ``skipped``，原因是 ``overlap``，計入工作的 ``skipped``，並以警告
寫入日誌。每一種觸發器都是如此，``run_now`` 也不例外。

在執行的執行緒真正結束之前，工作都算是執行中。逾時或取消之後，這個時間點可能比紀錄
上寫的還晚。

逾時
--------

``timeout`` 是一次執行可以花的秒數，從它被觸發的那一刻起算。排程器每秒檢查一次。
時間到了的時候，紀錄會變成 ``timeout``，發布一個 ``scheduler.error`` 事件，並要求這次
執行停止：

* 管線會透過它的取消權杖被取消，與 ``run.cancel()`` 完全相同：尚未開始的任務變成
  ``cancelled``，執行中的任務則透過 ``ctx.cancel`` 得知；
* 動作清單會在下一個動作之前停止。

**執行緒無法被強制終止。**\ 正在執行的動作，或不檢查權杖的管線任務，會一直執行到它
回傳為止。在那之前工作都算是執行中，所以下一次觸發會被略過，兩次執行絕不會相撞。
執行緒在逾時之後做的事不會改變紀錄。

也請為管線的任務設定它們自己的逾時（見 :doc:`pipeline`）：任務的逾時只讓一個任務
失敗，清理任務仍會執行；工作的逾時則會停止整次執行。

取消
--------

.. code-block:: python

   cancelled = scheduler.cancel("daily-report")    # 這些紀錄，現在是 "cancelled"

``cancel(name)`` 會把該工作進行中的執行的紀錄結案為 ``cancelled``，並以與逾時相同的
方式停止這些執行。工作沒有在執行時它回傳空清單；名稱既沒有註冊也沒有在執行時則拋出
``SchedulerException``。被取消的執行不會發布 ``scheduler.error``。移除工作不會取消
進行中的執行。

時區與日光節約時間
------------------------------------

``timezone`` 是 IANA 名稱，例如 ``Asia/Taipei`` 或 ``America/New_York``，或是
``UTC``。時區資料來自標準函式庫的 ``zoneinfo``，它讀取系統的資料庫。Windows 沒有這個
資料庫：請在那裡安裝 ``tzdata`` 套件（``pip install tzdata``）。``UTC`` 不需要它就能
使用。找不到的名稱會在工作註冊時拋出 ``CronException``。

沒有時區的 cron 觸發器以機器的本地時間解讀，排程器一直以來都是如此。在容器中那通常
是 UTC：請為正式環境的工作指定時區。

在有日光節約時間的時區中：

* **不存在的本地時間不會觸發。**\ 在時鐘從 02:00 直接跳到 03:00 的那一天，
  ``30 2 * * *`` 不會執行；
* **出現兩次的本地時間只觸發一次**\ ，在第一次出現時。在時鐘從 02:00 撥回 01:00 的
  那一天，``30 1 * * *`` 只執行一次；
* 小時欄位是 ``*`` 的運算式本來就每小時執行，所以在重複的那一小時中仍會持續觸發：
  ``*/15 * * * *`` 在這兩天都是每 15 分鐘（實際經過的時間）執行一次。

必須以固定間隔執行，或不論時鐘怎麼變都必須每天剛好執行一次的工作，最好排在 ``UTC``。
沒有時區的觸發器跟隨系統時鐘，不會得到上述任何處理：重複的那一小時會觸發兩次。

事件
--------

以 ``failed`` 或 ``timeout`` 結束的執行會在排程器的匯流排上發布一個
``SchedulerError``\ （``scheduler.error``，嚴重程度 ``error``，來源 ``scheduler``）。它的
主旨是 ``scheduler[<job>] failed`` 或 ``scheduler[<job>] timed out``，它的關聯 ID 是
紀錄的 ``correlation_id``。

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - payload 的鍵
     - 值
   * - ``job``
     - 工作的名稱。
   * - ``trigger``
     - 是什麼觸發了這次執行。
   * - ``status``
     - ``failed`` 或 ``timeout``。
   * - ``error``
     - 紀錄的 ``error``。其中的 URL 會被截到只剩主機。
   * - ``target``
     - ``actions`` 或 ``pipeline``。
   * - ``scheduler_run_id``
     - 紀錄的 ``run_id``。
   * - ``duration_ms``
     - 目標已經開始執行時才有。
   * - ``pipeline``、``run_id``
     - 目標是管線時：它的名稱，以及管線開始執行之後的管線執行 ID。

``completed``、``skipped`` 與 ``cancelled`` 不會發布任何事件；它們記在歷史與日誌中。

有一種失敗的回報方式不同。執行器完全不接受的動作清單（空的清單、不是清單的東西）
仍像以前一樣透過 :func:`~automation_file.notify.manager.notify_on_failure` 回報。它
自己在整個行程共用的匯流排上發布 ``scheduler.error`` 事件，payload 是 ``job``、
``status``\ （``error``）、``error`` 與 ``context``；而在通知路由器沒有啟用時，它還會把
訊息直接送到每一個已註冊的 sink（見 :doc:`notifications`）。其他所有失敗都只是事件：
想收到通知，請為 ``scheduler.error`` 加一條路由。

動作
--------

.. list-table::
   :header-rows: 1
   :widths: 26 44 30

   * - 動作
     - 參數
     - 回傳
   * - ``FA_schedule_add``
     - ``name, cron_expression, action_list, allow_overlap=False, timezone=None,
       timeout=None``
     - 工作的快照
   * - ``FA_schedule_job``
     - ``name, action_list, triggers=None, allow_overlap=False, timeout=None``
     - 工作的快照
   * - ``FA_schedule_pipeline``
     - ``definition, name=None, triggers=None, params=None, allow_overlap=False,
       timeout=None``
     - 工作的快照
   * - ``FA_schedule_run``
     - ``name``
     - 這次觸發的紀錄
   * - ``FA_schedule_cancel``
     - ``name``
     - 被取消的紀錄
   * - ``FA_schedule_history``
     - ``job=None, state=None, limit=50``
     - 紀錄，最新的在前
   * - ``FA_schedule_list``
     - （無）
     - 每個工作的快照
   * - ``FA_schedule_remove``
     - ``name``
     - 被移除工作的快照
   * - ``FA_schedule_remove_all``
     - （無）
     - 被移除的各個工作的快照

它們操作的是整個行程共用的 ``scheduler``。``definition`` 是對應表或定義檔的路徑，它的
``schedule`` 會變成 cron 觸發器。在 ``FA_schedule_add`` 中，``allow_overlap``、
``timezone`` 與 ``timeout`` 要以名稱傳入。觸發器是一個對應表，內含它的 ``kind`` 與該
種類的引數：

.. list-table::
   :header-rows: 1
   :widths: 14 86

   * - ``kind``
     - 鍵
   * - ``cron``
     - ``cron``\ （必填）、``timezone``
   * - ``file``
     - ``path``\ （必填）、``events``、``recursive``
   * - ``event``
     - ``types``、``sources``、``min_severity``；type 以名稱與前綴表示
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

``register_scheduler_ops(registry)`` 可以把這些動作加進你自己的 registry。

工作會記下它之後要執行的動作名稱。只要動作清單或定義是請求的一部分，TCP 或 HTTP
動作伺服器上的 :class:`~automation_file.ActionACL` 也會檢查這些名稱。它看不到以檔案
路徑指定的定義內部，而 ``FA_schedule_run`` 會執行已註冊工作所持有的任何內容：請只對
可以呼叫全部已註冊動作的用戶端開放 ``FA_schedule_pipeline`` 與 ``FA_schedule_run``。

啟動與停止
--------------------

.. code-block:: python

   from automation_file.scheduler import Scheduler

   scheduler = Scheduler(history_limit=5000)      # 你自己的排程器
   scheduler.shutdown()                           # 停止執行緒與每一個觸發器
   scheduler.start()                              # ... 再把它們帶回來

``Scheduler(*, clock=None, bus=None, history_limit=1000, autostart=True)``

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 選項
     - 意義
   * - ``clock``
     - 回傳目前時間（帶時區的 ``datetime``）的可呼叫物件。預設：系統時鐘的 UTC
       時間。
   * - ``bus``
     - 排程器監聽與回報所用的 ``EventBus``，也是它的管線發布事件的地方。預設：
       整個行程共用的匯流排。
   * - ``history_limit``
     - 保留幾筆紀錄。預設 ``1000``。
   * - ``autostart``
     - 加入工作時啟動背景執行緒。預設 ``True``。

``shutdown()`` 會停止背景執行緒，以及排程器建立的每一個檔案監看器與每一個匯流排
訂閱。工作仍保持註冊；``start()`` 或再加入一個工作會讓它們重新就緒。進行中的執行會
跑完，除非使用 ``shutdown(cancel_running=True)``。排程器的所有執行緒都是 daemon
執行緒，所以它們絕不會讓直譯器無法結束。

使用 ``autostart=False`` 時，什麼都不會自己發生：``tick(now)`` 會處理 ``now`` 所在的
那一分鐘以及在 ``now`` 到期的逾時，並回傳它所觸發的紀錄。不必等待就能測試排程的做法
就是這樣：

.. code-block:: python

   from datetime import datetime, timezone

   from automation_file.scheduler import Scheduler

   engine = Scheduler(autostart=False)
   engine.add("nightly", "0 2 * * *", [["FA_schedule_list"]], timezone="Asia/Taipei")
   engine.tick(datetime(2026, 10, 7, 17, 59, tzinfo=timezone.utc))      # []
   (run,) = engine.tick(datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc))
   run.wait(10)
   run.state                                       # "completed"

出問題時
----------------

工作沒有在它的時間執行
    先找有沒有 ``skipped`` 紀錄：那表示上一次執行還在進行。如果完全沒有紀錄，表示
    那一分鐘沒有被處理：行程沒在執行或機器在睡眠（錯過的分鐘不會補跑）、那一天不
    存在那個本地時間，或是運算式其實以另一個時區解讀。沒有 ``timezone`` 的觸發器使用
    機器的本地時間。

``CronException: unknown time zone``
    名稱拼錯了，或機器沒有時區資料：在 Windows 上請安裝 ``tzdata``。

執行是 ``failed``，但大部分都成功了
    有一個動作拋出例外，清單的其餘部分仍然執行了。``error`` 會依位置與名稱列出失敗
    的動作。

執行是 ``completed``，工作卻出了問題
    只有動作拋出例外或管線的執行沒有成功時，執行才算失敗。以回傳值回報的動作會
    完成：請見 :doc:`pipeline` 中的同一個條目。

執行已是 ``timeout`` 或 ``cancelled``，工作卻仍顯示 ``running``
    它的執行緒無法被停止，還停在原本的動作或任務中。在那回傳之前，工作都是忙碌的，
    它的觸發也都會被略過。請為長時間的傳輸設定它們自己的逾時，並讓長時間的管線
    任務檢查 ``ctx.cancel``。

工作觸發得比預期頻繁
    儲存一個檔案會產生好幾個檔案事件；同一個工作的兩個觸發器都會觸發它；設定了
    ``allow_overlap=True`` 的工作不會被進行中的執行擋下。

紀錄是 ``skipped``，原因是 ``chain``
    已經有十六次執行接連互相觸發：兩個工作監聽彼此的事件，或兩條管線互相相依。請
    打破這個循環；需要重複執行的工作應該使用 cron 觸發器。

相依的管線從不觸發
    ``PipelineTrigger`` 中的名稱不是上游管線的 ``name``、上游的執行沒有以 ``when``
    要求的方式結束，或它發布事件的匯流排不是排程器的那一個。

事件觸發器沒有觸發
    請對照 ``event_bus.recent()`` 檢查 ``types``、``sources`` 與 ``min_severity``。
    由工作自己的執行所發布的事件是刻意被忽略的。

沒有收到通知
    路由器必須已經啟動，而且必須有一條符合 ``scheduler.error`` 的路由。沒有路由器
    時，只有執行器拒絕的動作清單會被直接送到 sink。

歷史是空的
    它保存在記憶體中，隨行程結束而消失；你自己建立的排程器有它自己的歷史。管線的
    執行則在執行紀錄儲存中。

``shutdown()`` 之後什麼都不觸發
    工作仍然註冊著，但它們的觸發器已經停止。請呼叫 ``start()``。

重複或未知的工作、錯誤的觸發器、錯誤的逾時與錯誤的歷史查詢會拋出
``SchedulerException``；無法理解的運算式或時區則拋出 ``CronException``。錯誤的定義會
拋出 ``PipelineDefinitionException``，不存在的監看路徑則拋出 ``TriggerException``，
兩者都發生在工作註冊時。它們全都衍生自 ``FileAutomationException``。
