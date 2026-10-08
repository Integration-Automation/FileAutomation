檔案完整性監控
==============

``automation_file.integrity`` 只回答一個關於目錄樹的問題：它是否仍然是當初核可的
樣子？:class:`~automation_file.integrity.monitor.IntegrityMonitor` 把核可的狀態記錄
為 *基準*\ （baseline），拿目錄樹與它比對，並把每一處差異回報為六種變更之一。

它透過\ :doc:`儲存層 <storage>`\ 讀取，所以目錄樹與基準都是儲存 URI，可以放在任何
後端。偏移（drift）會以事件的形式發布（見 :doc:`event_bus`）；監控器本身絕不呼叫通知
接收端。除非你傳入補救政策，否則它只會讀取。

``IntegrityMonitor`` 仍然可以從 ``automation_file`` 與 ``automation_file.core.fim``
匯入，為第一代監控器寫的呼叫方式也照常運作（見 `第一代監控器`_）。

最小範例
--------

.. code-block:: python

   from automation_file.integrity import IntegrityMonitor

   monitor = IntegrityMonitor("/srv/site", baseline="/var/lib/fa/site.baseline.json")
   monitor.create_baseline()                 # 核可目前的內容

   report = monitor.verify()                 # 雜湊每個檔案，與基準比對
   if not report.ok:
       print(report.counts)                  # {'created': 0, 'modified': 1, 'deleted': 0, ...}
       for change in report.changes:
           print(change.kind.value, change.path)
       monitor.accept(report)                # 檢視之後：核可這份報告所看到的狀態

正式環境範例
------------

基準放在它所描述的 bucket 之外，監控器在執行緒上驗證，事件被導向通知接收端，補救則
明確地開啟。

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

   # integrity.violation 與 integrity.remediated；補救成功的事件是 "info"。
   event_bus.subscribe(route, types="integrity.*", min_severity=Severity.WARNING)

   monitor = IntegrityMonitor(
       "s3://reports/2026",
       baseline="local:///var/lib/fa/baselines/reports-2026.json",
       algorithm="sha256",
       interval=900,                                   # 持續模式：每 15 分鐘一次
       remediation=RemediationPolicy(                  # 需明確開啟；不傳就不會變更任何東西
           quarantine="s3://reports-quarantine/2026",
           restore_from="s3://reports-mirror/2026",
           on_created="quarantine",
           on_modified="restore",
           on_deleted="restore",
       ),
   )
   if not monitor.has_baseline():
       monitor.create_baseline()

   monitor.start()                                     # 常駐執行緒；立即返回
   ...
   monitor.status()                                    # running、last_run、last_error、last_report
   monitor.stop()

請把基準放在「能改動目錄樹的人改不到」的地方。把基準放在目標之內也能運作，監控器會
把那個檔案排除在快照之外，但這樣一來同一份寫入權限就同時涵蓋兩者。

四種模式
--------

.. list-table::
   :header-rows: 1
   :widths: 16 30 54

   * - 模式
     - 呼叫
     - 作用
   * - snapshot（快照）
     - ``monitor.snapshot()``
     - 讀取目錄樹並回傳
       :class:`~automation_file.integrity.snapshot.Snapshot`。不儲存任何東西，
       也不需要基準。
   * - verify（驗證）
     - ``monitor.verify(deep=True)``
     - 拿目錄樹與基準比對一次，回傳
       :class:`~automation_file.integrity.report.DriftReport`。
   * - watch（監看）
     - ``monitor.watch()``
     - 在變更發生時即時反應，回傳帶有 ``stop()`` 的控制代碼。本機目標透過檔案系統
       事件觀察：在 ``debounce`` 秒（預設 0.5）之內變更的路徑會一起驗證，而且只讀取
       這些路徑。其他後端則每隔 ``poll_interval`` 秒以快速驗證輪詢一次。偏移在出現時
       回報一次，維持不變期間不會重複回報。
   * - continuous（持續）
     - ``monitor.start()`` / ``monitor.stop()``
     - 在常駐執行緒上每隔 ``interval`` 秒（預設 60）驗證一次；第一次驗證在經過一個
       間隔之後執行。每一次發現偏移的驗證都會發布一個事件。

``monitor.create_baseline()`` 把快照存為基準，``monitor.accept(report)`` 則核可
一次偏移。傳入報告時，``accept`` 存下的正是那次驗證所看到的目錄樹，因此報告之後才
發生的變更不會在沒人看過的情況下被核可；不傳報告時則重新讀取目錄樹。

``monitor.verify_paths(["a.txt", "config"])`` 只驗證這些路徑（目錄代表其下的所有
檔案），並把報告標記為 ``partial``。監看模式就是對變更的路徑執行它；當有其他來源
（例如 bucket 通知）告訴你哪些東西變了，也可以自己呼叫。

監看模式啟動時不會先驗證整棵目錄樹，而且作業系統的事件佇列溢位時會無聲地丟棄事件。
監看模式縮短的是偵測所需的時間；真正能證明目錄樹完好的，仍然是定期的深度驗證。

深度驗證與快速驗證
------------------

``verify(deep=True)`` 會雜湊每一個檔案。在遠端後端上，這表示要讀取每一個檔案。

``verify(deep=False)`` 會先拿每個檔案的大小、修改時間與 etag 與基準比對，只雜湊其中
任何一項不同的檔案。報告會說明這一點：``report.deep`` 為 ``False``，
``report.hashed`` 是 ``report.checked`` 個檔案中實際被讀取的數量，``report.notes``
則包含 ``"quick pass: 2 of 1840 files hashed; size, modification time and etag
decided the rest"``。三項都沒變的變更，快速驗證察覺不到，所以也請排定深度驗證。
基準項目若既沒有記錄時間也沒有記錄 etag（舊格式），一律會被雜湊。

報告包含 ``changes``、``counts``\ （每種變更一個數字，包含零）、``ok``、``deep``、
``partial``、``checked``、``hashed``、``notes``、``remediation``、``verified_at``
與 ``correlation_id``。``report.to_dict()`` 的結果可直接序列化為 JSON。

Manifest 格式
-------------

基準是一份帶有結構版本的 JSON 文件，稱為 *manifest*：

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

   * - 欄位
     - 意義
   * - ``schema_version``
     - ``2``。其他數字一律以 ``IntegrityException`` 拒絕，因此較新版本寫出的文件絕
       不會被一知半解地讀取。
   * - ``created_at``
     - 快照的建立時間，UTC 的 ISO 8601 格式。
   * - ``root``、``backend``
     - 目錄樹的 URI，以及提供它的後端的 scheme。
   * - ``algorithm``
     - 所有校驗碼使用的雜湊演算法。驗證時就用它來雜湊。
   * - ``entries``
     - 每個檔案一個物件，依 ``path`` 排序（相對於 ``root``，以 ``/`` 分隔）。目錄
       不會被記錄，因此空目錄是看不見的。
   * - ``size``、``modified_at``、``content_type``、``version``、``etag``
     - 後端回報的內容。後端無法提供的欄位為 ``null``。
   * - ``mode``
     - 以整數表示的權限位元（``420`` 即 ``0o644``）。只有本機檔案系統上的檔案才會
       記錄。

``write_manifest`` / ``FA_write_manifest`` 寫出的 manifest（沒有
``schema_version``，以 ``files`` 對應表記錄 ``size`` 與 ``checksum``）同樣可以讀取，
並在讀取時轉換。``create_baseline()`` 與 ``accept()`` 一律寫出第 2 版；之後
``verify_manifest`` 會以 ``ManifestException`` 拒絕該檔案，並在訊息中指出
``FA_integrity_verify``。

基準管理員會先把 manifest 寫到同目錄的暫存檔，再把它移過去取代基準，所以讀取端永遠
不會看到寫到一半的文件。這個移動在本機檔案系統上是重新命名，在其他後端則是把完成的
檔案整個寫入一次。

變更種類
--------

.. list-table::
   :header-rows: 1
   :widths: 24 60 16

   * - 種類
     - 回報時機
     - 嚴重程度
   * - ``created``
     - 基準中沒有的路徑。
     - warning
   * - ``modified``
     - 校驗碼或記錄的大小不同。
     - error
   * - ``deleted``
     - 基準中的路徑不見了。
     - error
   * - ``renamed``
     - 一個被刪除的檔案與一個新建立的檔案有相同的校驗碼與大小。
       ``change.previous_path`` 是舊路徑。
     - error
   * - ``metadata_changed``
     - 校驗碼相同，但修改時間、內容類型、版本或 etag 不同；``change.fields`` 會
       指出是哪些。任何一邊沒有記錄的欄位不會被比對。
     - warning
   * - ``permission_changed``
     - 權限位元不同。兩者都發生時，會與 ``modified`` 一併回報。
     - error

當多個被刪除或多個新建立的檔案共用同一個校驗碼時，配對就有歧義。此時它們會被回報為
``deleted`` 與 ``created``，各自的 ``change.note`` 會設為 ``"ambiguous rename: 2
deleted and 1 created files share the checksum 9f86d081884c...; reported
separately"``。

事件
----

每一次發現偏移的驗證都會在 ``event_bus``\ （或以 ``bus=`` 傳入的事件匯流排）上發布
一個 :class:`~automation_file.events.model.IntegrityViolation`。驗證在關聯範圍
（correlation scope）內執行，所以這個事件、補救事件與 ``report.correlation_id`` 共用
同一個 ID；若外層已有範圍，則沿用外層的 ID。

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - 欄位
     - 值
   * - ``type``、``source``
     - ``integrity.violation``、``integrity``
   * - ``severity``
     - 所發現的變更種類中最嚴重的一級：有東西被修改、刪除、重新命名或權限被變更時
       為 ``error``；只有新增或中繼資料變更時為 ``warning``。
   * - ``payload["resource"]``、``["backend"]``
     - 目標的 URI 與它的後端。
   * - ``payload["status"]``
     - ``drift``；驗證無法執行時為 ``error``\ （此時 ``payload["error"]`` 說明原因）。
   * - ``payload["counts"]``
     - 每種變更的數量。
   * - ``payload["changes"]``
     - 前 20 筆變更，格式為 ``{"kind": ..., "path": ...}``；``total`` 是實際數量，
       ``truncated`` 表示是否有省略。
   * - ``payload["baseline"]``、``["algorithm"]``、``["deep"]``、``["partial"]``
     - 這次驗證比對的對象，以及它有多徹底。

傳入 ``alerts=AlertPolicy(severities={"created": "error"}, max_changes=50)`` 可以
改變某種變更的嚴重程度，或事件中列出的變更數量。

``verify()`` 無法執行時會拋出例外。持續模式、監看模式與 ``check_once()`` 沒有對象
可以拋出：它們會發布同一種事件並帶有 ``status: "error"``，把原因留在
``monitor.last_error``，然後繼續執行。

補救
----

預設關閉。除非把 :class:`~automation_file.integrity.remediation.RemediationPolicy`
傳給監控器，否則不會搬移或複製任何東西；而所有動作都維持 ``"none"`` 的政策同樣什麼
都不做。

.. code-block:: python

   RemediationPolicy(
       quarantine="s3://reports-quarantine/2026",   # 或 None
       restore_from="s3://reports-mirror/2026",     # 或 None；基準的鏡像
       on_created="quarantine",                     # "none" | "quarantine"
       on_modified="restore",                       # "none" | "quarantine" | "restore"
       on_deleted="restore",                        # "none" | "restore"
   )

``quarantine``\ （隔離）
    把有問題的檔案搬到 ``<quarantine>/<UTC 時間戳記>/<path>``。同一次驗證的所有檔案
    共用一個時間戳記目錄，而且隔離區中的任何東西都不會被覆寫。

``restore``\ （還原）
    從 ``restore_from`` 把檔案複製回來。鏡像中的副本會先被雜湊，與基準不符就拒絕，
    因此過期或被竄改的鏡像絕不會被複製到原位；還原後的檔案會再雜湊一次，通過之後
    這個步驟才算完成。若設定了隔離區，被修改的檔案會先搬進隔離區；沒有隔離區時，
    它的內容會被覆寫。

重新命名會拆成兩半處理：舊路徑視為被刪除，新路徑視為新建立。中繼資料與權限的變更
絕不會被補救。隔離區與鏡像都必須位於目標之外。

每個步驟都會記錄在 ``report.remediation``\ （``action``、``path``、``kind``、
``ok``、``source``、``destination``、``error``），並以型別為
``integrity.remediated`` 的 ``IntegrityRemediated`` 事件發布：成功時為 ``info``，
失敗時為 ``error``。失敗的步驟只會被回報，絕不會拋出例外；檔案維持原狀。報告描述的
是補救之前的目錄樹，因此有執行過補救步驟時，``accept(report)`` 會重新讀取目錄樹。

還原後的檔案有新的修改時間，下一次驗證會把它回報為 ``metadata_changed``，直到基準被
核可為止。

演算法
------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 演算法
     - 用途
   * - ``sha256``
     - 預設值。
   * - ``sha512``、``blake2b``
     - 強度至少相同的替代選擇。
   * - ``md5``、``sha1``
     - 除非傳入 ``allow_weak=True``，否則一律拒絕。兩者都有實際可行的碰撞：檔案可以
       被換成另一個摘要相同的檔案，而這個變更不會被察覺。保留它們只是為了繼續讀取
       當初以它們寫出的基準，絕不會作為預設值。

``algorithm=`` 是 ``snapshot()`` 與 ``create_baseline()`` 使用的雜湊演算法。驗證一律
使用所讀取基準的演算法，``accept()`` 也會沿用它。要把基準換成另一種演算法，請先檢視
目錄樹，再用以新演算法建立的監控器呼叫 ``create_baseline()``。

檔案透過儲存層的 ``checksum``，在執行緒池上平行雜湊（預設 ``max_workers=8``）。

動作
----

.. list-table::
   :header-rows: 1
   :widths: 30 36 34

   * - 動作
     - 參數
     - 回傳值
   * - ``FA_integrity_snapshot``
     - ``target, algorithm="sha256"``
     - 快照：``root``、``backend``、``algorithm``、``created_at``、``entries``
   * - ``FA_integrity_baseline``
     - ``target, baseline, algorithm="sha256"``
     - ``target``、``baseline``、``backend``、``algorithm``、``created_at`` 以及
       ``entries`` 的數量
   * - ``FA_integrity_verify``
     - ``target, baseline, deep=True``
     - 偏移報告
   * - ``FA_integrity_accept``
     - ``target, baseline``
     - 與 ``FA_integrity_baseline`` 相同
   * - ``FA_integrity_watch_start``
     - ``name, target, baseline, interval=60.0``
     - 新監控器的狀態
   * - ``FA_integrity_watch_stop``
     - ``name``
     - 它最後的狀態
   * - ``FA_integrity_status``
     - ``name=None``
     - 狀態的清單：單一監控器，或全部

``FA_integrity_watch_start`` 讓一個具名的監控器維持在持續模式，直到
``FA_integrity_watch_stop``；基準必須先存在。狀態包含 ``name``、``target``、
``baseline``、``algorithm``、``interval``、``running``、``last_run``、
``last_error`` 與 ``last_report``。

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

這些動作會把偏移發布到整個行程共用的 ``event_bus``。它們不接受弱演算法，也不接受
補救政策：這兩者都只能在 Python 中選用。與儲存動作一樣，它們能存取行程所能存取的
一切，而且 ``FA_integrity_baseline`` 與 ``FA_integrity_accept`` 會寫入檔案，因此在
TCP 或 HTTP 動作伺服器上請傳入 ``ActionACL``，在 MCP 伺服器上請使用
``--allowed-actions``，只開放用戶端需要的動作。
``register_integrity_ops(registry)`` 可把它們加入你自己的註冊表。

第一代監控器
------------

為第一代 ``IntegrityMonitor`` 寫的程式照常運作：

.. code-block:: python

   from automation_file import IntegrityMonitor, notification_manager, write_manifest

   write_manifest("/srv/site", "/srv/MANIFEST.json")
   monitor = IntegrityMonitor(
       "/srv/site",                 # 仍然接受 root= 與 manifest_path= 這兩個關鍵字
       "/srv/MANIFEST.json",
       interval=60.0,
       manager=notification_manager,
       on_drift=lambda summary: print("drift:", summary),
   )
   summary = monitor.check_once()   # {"matched": [...], "missing": [...], "modified": [...],
                                    #  "extra": [...], "ok": False}
   monitor.start()

``check_once()`` 回傳同樣的摘要字典，驗證無法執行時會帶有 ``error``；``on_drift``
會收到它，``last_summary`` 會保留它。與以往一樣，除非 ``alert_on_extra=True``，否則
新增的檔案對 ``on_drift`` 與通知而言不算偏移，而重新命名會以 ``missing`` 加上
``extra`` 的形式出現。

通知的去向與以往相同：透過你傳入的 ``manager`` 送出，沒有傳入時則使用整個行程共用的
``notification_manager``。新增的只有一點：每一次偏移（包含新增）也都會以
``IntegrityViolation`` 事件的形式發布。如果你改由這個事件（訂閱者或通知路由）把偏移
送到通知管道，請傳入 ``notify=False``，同一次偏移才不會被通知兩次。

發生問題時
----------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - 你看到的現象
     - 它的意思與處理方式
   * - ``IntegrityException: no baseline at …``
     - 基準 URI 上沒有任何東西。請檢查 URI，然後呼叫 ``create_baseline()``。執行中
       的監控器的基準消失，本身就是一項發現：它會以帶有 ``status: "error"`` 的事件
       送達。
   * - ``… is not readable JSON`` / ``… is not a valid manifest``
     - 基準已損毀或被編輯過。請從副本還原，或檢視目錄樹之後重新建立。不要核可一棵
       你無從比對的目錄樹。
   * - ``… has manifest schema version 3``
     - 基準是由較新的版本寫出的。請升級，或用目前的版本重新建立基準。
   * - ``md5 is refused for integrity checks …``
     - 基準使用了弱演算法。傳入 ``allow_weak=True`` 以便讀取，再以 ``sha256`` 呼叫
       ``create_baseline()``。
   * - ``target … does not exist``
     - 檔案系統上的目錄不見了。在物件儲存上，什麼都沒有的前綴則是一棵空的目錄樹：
       每個檔案都是 ``deleted``。
   * - ``StorageUnavailableException``
     - 後端尚未初始化：請先呼叫 ``s3_instance.later_init(...)`` 或對應的函式。
   * - 驗證過程中出現 ``StoragePermissionException`` 或
       ``StorageTransientException``
     - 整次驗證失敗；無法完整讀取的目錄樹絕不會被回報為完好。持續模式會在
       ``interval`` 之後再試一次。
   * - 快速驗證沒問題，深度驗證卻回報 ``modified``
     - 內容變了，大小與修改時間卻沒變。一般工具不會這樣做；請視為竄改。
   * - 所有檔案都是 ``metadata_changed``
     - 檔案被複製或還原過，因而有了新的時間。檢視之後呼叫 ``accept()``。
   * - 補救步驟的 ``ok`` 為 ``False``
     - ``step.error`` 說明原因（鏡像中沒有副本、鏡像與基準不符、存取被拒）。檔案
       維持原狀；並已發布嚴重程度為 ``error`` 的 ``integrity.remediated`` 事件。
   * - 每個間隔都收到同一個事件
     - 只要偏移還在，持續模式每次驗證都會回報。請修正目錄樹或呼叫 ``accept()``，
       或在訂閱端去除重複（``NotificationManager`` 會這麼做）。
   * - 監看模式漏掉了某個變更
     - 檔案系統事件可能遺失。請在監看之外，另外排程執行深度的 ``verify()``。

一個監控器一次只執行一次驗證：在持續模式的執行緒正在驗證時呼叫 ``verify()``，會等它
完成。
