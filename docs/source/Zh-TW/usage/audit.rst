稽核軌跡
================

稽核軌跡針對函式庫所做的每一件事回答同一個問題：**誰** 在 **什麼時候** 做了
**什麼**，對象是 **哪個資源**，使用 **哪個後端**，以及 **結果如何**。這是稽核
結構描述 v2。沒有任何元件會自行寫入稽核資料列：元件發布
:doc:`事件 <event_bus>`，儲存層回報它的操作，再由
:class:`~automation_file.audit.trail.AuditTrail` 把兩者轉成
:class:`~automation_file.audit.record.AuditRecord`，寫進
:class:`~automation_file.audit.store.AuditStore`。

v1 的 :class:`~automation_file.core.audit.AuditLog` 維持原樣；請見
`從 v1 遷移`_。

最小範例
----------------

.. code-block:: python

   from automation_file import audit_search, configure_audit

   configure_audit("audit.sqlite")          # 建立資料庫並開始記錄

   ...                                      # 執行管線、複製檔案、發布事件

   for entry in audit_search(status="error", limit=20):
       print(entry["timestamp"], entry["actor"], entry["action"], entry["resource"],
             entry["error"])

``configure_audit`` 接受 SQLite 資料庫的路徑或一個現成的儲存庫，把行程層級的
``audit_trail`` 指向它並啟動。在呼叫之前，軌跡沒有儲存庫，也不會記錄任何內容。
``audit_search`` 回傳一般的字典，最新的在前。

正式環境範例
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
       File("s3://reports/q1.csv").copy_to("local:///backup/q1.csv")   # 會被記錄
       audit_trail.record("approve", resource="s3://reports/q1.csv", backend="s3",
                          source="review", metadata={"ticket": "OPS-12"})
       emit(PipelineCompleted(source="pipeline", subject="daily-report completed",
                              payload={"pipeline": "daily-report", "duration_ms": 812.0}))

   audit_search(correlation_id=run_id)                 # 整次執行，最新的在前
   audit_search(resource_prefix="s3://reports/", since="2026-10-01T00:00:00+00:00")
   audit_trail.count(actor="scheduler", status="error")
   audit_trail.purge(older_than_seconds=90 * 24 * 3600)   # 保留 90 天

請在啟動時就開啟儲存庫，讓問題立刻浮現：資料庫無法開啟時，``configure_audit``
會拋出 :class:`~automation_file.AuditException`。清除舊紀錄的工作請交給排程。
兩個範圍內的所有事物都帶有相同的關聯 ID 與 actor，因此只要一個篩選條件就能取回
整次執行。

自行建立軌跡，使用私有的匯流排或其他儲存庫：

.. code-block:: python

   from automation_file import AuditTrail, EventBus, SQLiteAuditStore

   trail = AuditTrail(SQLiteAuditStore("tenant-a.sqlite"), bus=EventBus())
   trail.start()
   ...
   trail.stop()
   trail.store.close()

紀錄
--------

``AuditRecord`` 不可變，且可直接轉成 JSON（``to_dict()`` /
``AuditRecord.from_dict()``）。

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 欄位
     - 意義
   * - ``id``
     - 唯一 ID。由事件產生的紀錄沿用該事件的 ID。
   * - ``timestamp``
     - 發生的時間，為帶時區的 UTC ``datetime``。不含時區的時間會被拒絕。
   * - ``actor``
     - **誰**：外層 ``actor_scope`` 的 actor，或執行行程的使用者。
   * - ``source``
     - 回報的元件：``pipeline``、``storage``、``scheduler``、``notify`` 等。
   * - ``pipeline``、``task``
     - 所屬的管線與任務（如果有的話）。
   * - ``action``
     - **做了什麼**：事件的 type（``task.failed``）或儲存操作（``upload``、
       ``download``、``read``、``delete``、``mkdir``、``copy``、
       ``move``）。
   * - ``resource``
     - **哪個資源**：儲存 URI 或其他對象。
   * - ``backend``
     - **哪個後端**：儲存的 scheme（``s3``、``local`` 等）。
   * - ``status``
     - **結果如何**：``ok``、``warning``、``error``，或發出者自行選用的字詞。
   * - ``duration_ms``
     - 花費的時間（已知時）。
   * - ``error``
     - 失敗時為 ``"<ExceptionType>: <message>"``。
   * - ``metadata``
     - 其餘的所有資訊，以 JSON 值保存。JSON 無法表示的值會保存為它的 ``repr``。
   * - ``correlation_id``
     - 所屬的那次執行；在任何 ``correlation_scope`` 之外為 ``None``。

記錄哪些內容
------------------------

**事件。** 匯流排上的每個事件都會變成一筆紀錄。``source``、``actor``、
``timestamp`` 與 ``correlation_id`` 取自事件；``action`` 是事件的 type；
``pipeline``、``task``、``resource``、``backend``、``status``、
``duration_ms`` 與 ``error`` 取自 payload 中同名的鍵。事件的 ``subject``、
``severity`` 以及 payload 的其他鍵都放在 ``metadata`` 之下。payload 沒有
``status`` 時由嚴重程度決定：info 為 ``ok``，warning 為 ``warning``，error 與
critical 為 ``error``。

**儲存操作。** 每一次上傳、下載、讀取、刪除、建立目錄、複製與搬移都會變成一筆
紀錄：``source="storage"``，``action`` 是操作名稱，``resource`` 是 URI，
``backend`` 是 scheme，無論成功或失敗。複製或搬移算作一筆紀錄，其來源位於
``metadata["source_uri"]``。

**失敗的儲存操作只記錄一次。** 儲存層會回報該操作，儲存橋接器也會為它發布一個
``storage.error`` 事件。軌跡保留操作本身，略過那個事件。

**手動記錄。** ``audit_trail.record(action, **fields)`` 會附加一筆紀錄；actor 與
關聯 ID 預設取自目前的範圍。

篩選條件
----------------

``search`` 與 ``count`` 接受相同的具名篩選條件；``search`` 回傳的紀錄最新的在前。

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - 篩選條件
     - 符合的紀錄
   * - ``since``、``until``
     - 時間範圍：包含 ``since``，不包含 ``until``。可以是帶時區的 ``datetime``、
       帶有時差或 ``Z`` 的 ISO 8601 字串，或自 epoch 起算的秒數。
   * - ``actor``、``source``、``pipeline``、``task``、``action``、
       ``backend``、``status``、``correlation_id``
     - 欄位與此值完全相同。
   * - ``resource_prefix``
     - 資源以此文字開頭。
   * - ``text``
     - 此文字出現在 action、resource、error、actor、source、pipeline、task、
       backend 或 metadata 的 JSON 之中。
   * - ``limit``、``offset``
     - 分頁。``limit`` 預設為 100，且不得超過 10 000。``count`` 會忽略這兩者。

``resource_prefix`` 與 ``text`` 會把文字當成字面值（``%`` 與 ``_`` 都是普通
字元），並忽略 ASCII 字母的大小寫。值為 ``None`` 的篩選條件不會限制搜尋。未知的
篩選條件名稱或型別錯誤的值會拋出 ``AuditException``，而不是悄悄回傳所有紀錄。

儲存介面
----------------

``AuditStore`` 是儲存庫要實作的介面：目前是 SQLite 儲存庫，日後可以是
PostgreSQL 或遠端儲存庫。

.. code-block:: python

   from automation_file import AuditQuery, AuditRecord, AuditStore

   class MyStore(AuditStore):
       def append(self, record: AuditRecord) -> None: ...
       def search(self, **filters) -> list[AuditRecord]:
           query = AuditQuery.from_filters(filters)      # 驗證過的篩選條件
           ...
       def count(self, **filters) -> int: ...
       def purge(self, older_than_seconds: float) -> int: ...
       def close(self) -> None: ...

儲存庫只能附加、可在執行緒之間共用、``search`` 以最新的在前回傳、拒絕 ``id``
已存在的紀錄，並且所有失敗都以 ``AuditException`` 拋出。
``AuditQuery.from_filters`` 以相同的方式為每一種儲存庫驗證篩選條件。

``SQLiteAuditStore(path)`` 把紀錄保存在一張資料表中，另有一張資料表記載結構描述
版本（``2``），並在時間戳記、關聯 ID、資源與 action 上建立索引。所有的值都以
繫結參數傳給 SQLite，篩選條件中的 ``LIKE`` 萬用字元也會被跳脫。所有執行緒透過一把
鎖共用同一條連線，並使用 WAL 模式，因此另一個行程可以在這個行程寫入時讀取。
``MemoryAuditStore()`` 把紀錄保存在行程內，供測試使用。

從 v1 遷移
--------------------

.. code-block:: python

   from automation_file import SQLiteAuditStore

   store = SQLiteAuditStore("audit.sqlite")
   store.import_v1("old-audit.sqlite3")      # 回傳新增的資料列數

每一筆 v1 資料列都會變成一筆 ``source="audit.v1"``、actor 為 ``unknown`` 的
紀錄；它的 payload 與 result 放在 ``metadata`` 之下。v1 資料庫只會被讀取，重複
匯入不會新增任何紀錄。

動作
--------

``register_audit_ops(registry)`` 會註冊四個動作；它們作用於行程層級的軌跡。

.. code-block:: json

   [
     ["FA_audit_configure", {"db_path": "/var/lib/automation_file/audit.sqlite"}],
     ["FA_audit_search", {"status": "error", "since": "2026-10-01T00:00:00+00:00", "limit": 50}],
     ["FA_audit_count", {"correlation_id": "4f0c2b6e9d5a4c1f8a7b3e2d1c0f9a8b"}],
     ["FA_audit_purge", {"older_than_seconds": 7776000}]
   ]

``FA_audit_search`` 與 ``FA_audit_count`` 接受上述的篩選條件；
``FA_audit_search`` 以 ``to_dict()`` 的形式回傳每一筆紀錄。

能夠清除軌跡的用戶端，就能抹去自己的痕跡。除非遠端用戶端本來就該管理軌跡，否則在
TCP 或 HTTP 動作伺服器上請傳入拒絕 ``FA_audit_purge`` 與 ``FA_audit_configure`` 的
:class:`~automation_file.ActionACL`，在 MCP 伺服器上則不要把它們列入
``--allowed-actions``。

發生問題時
--------------------

- **紀錄無法寫入。** 失敗會被記錄到日誌
  （``audit trail: cannot write the record of ...``），該筆紀錄則被捨棄。它絕對
  不會拋進被稽核的程式：磁碟已滿不應該讓管線停擺。請監看日誌中的這一行並設定
  告警。
- **資料庫無法開啟。** ``configure_audit`` 與 ``SQLiteAuditStore`` 會拋出
  ``AuditException``。請在啟動時開啟儲存庫，才能立刻發現問題。
- **資料庫是由較新的版本寫入的。** 儲存庫會拒絕開啟，而不是猜測它的結構。
- **持久性。** SQLite 儲存庫每寫入一筆紀錄就提交一次。在 WAL 模式下，行程當掉
  不會遺失任何資料；斷電則可能遺失最後一小段時間的紀錄。請把資料庫放在本機
  磁碟：WAL 無法在網路共用磁碟上運作。
- **成長。** 沒有任何紀錄會自動刪除。請依照保存期限，定期呼叫 ``purge`` 或
  ``FA_audit_purge``。
- **尚未設定就搜尋。** 沒有設定儲存庫時，``audit_search`` 會拋出
  ``AuditException``，因此空的結果永遠代表「沒有符合的紀錄」。
- **執行緒。** 範圍不會自動跟著工作進入另一個執行緒；把工作分派出去的程式要在
  那裡重新進入 ``correlation_scope`` 與 ``actor_scope``，否則它的紀錄不會帶有
  關聯 ID。
- **機密。** payload 會原樣保存。請不要把憑證放進事件的 payload 或 ``metadata``。

維運指標
----------------

同一批事件與儲存操作也會餵給 Prometheus 計數器，與每個動作的指標
``automation_file_actions_total``、``automation_file_action_duration_seconds``
並列：

.. code-block:: python

   from automation_file import install_operational_metrics, start_metrics_server

   install_operational_metrics()        # 一次即可；重複呼叫不會有任何改變
   start_metrics_server(host="127.0.0.1", port=9945)

.. list-table::
   :header-rows: 1
   :widths: 62 38

   * - 指標
     - 標籤
   * - ``automation_file_events_total``
     - ``type``、``severity``
   * - ``automation_file_notifications_total``
     - ``sink``、``outcome`` （``sent``、``dedup``、``rate_limited``、
       ``error``）
   * - ``automation_file_storage_operations_total``
     - ``operation``、``backend``、``status``
   * - ``automation_file_storage_operation_duration_seconds`` （直方圖）
     - ``operation``、``backend``

``install_operational_metrics()`` 會訂閱事件匯流排與儲存觀察者。通知計數器不需要
安裝：通知管理器與路由器會自行計算每一次投遞。標籤絕對不會帶有路徑、URI 或關聯
ID，而且每個標籤最多保留 100 個不同的值；超出的值會計入 ``other``。
