應用層
======

``automation_file.app`` 是使用者介面所呼叫的那一層。導覽中的每個項目各有一個服務——
Dashboard、Files、Storage、Pipelines、Scheduler、Integrity、Audit、Notifications、
Settings——每個都是建立在領域套件（:doc:`storage`、:doc:`pipeline`、:doc:`events`、
:doc:`integrity`、:doc:`audit`、:doc:`notifications`、:doc:`event_bus`、
:doc:`config`）之上的普通 Python 物件。

PySide6 視窗（:doc:`gui`）與 Web UI（:doc:`servers`）只呼叫這些服務，不碰它們底下的
任何東西。這就是兩者顯示相同狀態的原因，也是第三種介面——終端機 UI、Web 應用程式、
聊天機器人——同樣不需要認識領域套件的原因。

這一層遵守四個承諾：

* 不匯入任何 GUI 工具組，也不匯入任何後端 SDK。``import automation_file.app`` 在
  基礎安裝上就能運作。
* 回傳 JSON 能容納的 dataclass、字典與清單。
* 在回傳的內容中遮蔽 token、密碼與 webhook URL。
* 拋出 ``FileAutomationException`` 的子類別：領域自己的（``StorageException``、
  ``PipelineException``……），以及只有這一層才檢查的情況所用的 ``AppException``。

最小範例
----------------

.. code-block:: python

   from automation_file.app import app_services

   services = app_services()                       # 每個行程一組

   summary = services.dashboard.summary()
   print(summary.status, summary.reasons)          # "ok" () 或 "attention" (...)

   for entry in services.files.list_dir("local:///data"):
       print(entry.name, entry.size)

   draft = services.pipelines.new_draft("nightly")
   draft.add_task("FA_storage_copy", "download",
                  arguments={"source": "s3://in/a.csv", "target": "local:///tmp/a.csv"})
   run = services.pipelines.start(draft)           # 立即回傳
   services.pipelines.wait(run["run_id"], timeout=60)
   print(services.pipelines.status(run["run_id"])["status"])

服務一覽
----------------

``automation_file.app.NAVIGATION`` 是九個項目依顯示順序排列的 tuple；
``AppServices`` 為每個項目各有一個屬性，名稱為小寫。

.. list-table::
   :header-rows: 1
   :widths: 18 24 58

   * - 項目
     - 屬性與類別
     - 用途
   * - Dashboard
     - ``dashboard``、``DashboardService``
     - 一份摘要：健康狀態、執行、完整性漂移、最近的事件、儲存狀態。
   * - Files
     - ``files``、``FileService``
     - 對儲存 URI 進行列出、stat、預覽、複製、搬移、刪除、mkdir。
   * - Storage
     - ``storage``、``StorageService``
     - Scheme、掛載點，以及每個後端能不能用。
   * - Pipelines
     - ``pipelines``、``PipelineService``
     - 草稿、驗證、試跑、背景執行、狀態、歷史、續跑、取消、定義檔。
   * - Scheduler
     - ``scheduler``、``SchedulerService``
     - 列出、新增與移除 cron 工作。
   * - Integrity
     - ``integrity``、``IntegrityService``
     - 基準、驗證、接受、狀態、啟動與停止監控器。
   * - Audit
     - ``audit``、``AuditService``
     - 設定、搜尋與計算稽核紀錄。
   * - Notifications
     - ``notifications``、``NotificationService``
     - 已註冊的 sink、路由、測試訊息。
   * - Settings
     - ``settings``、``SettingsService``
     - 載入並套用設定檔；哪些 extra 已安裝。

Dashboard
---------

.. code-block:: python

   summary = services.dashboard.summary()
   summary.to_dict()                    # 可序列化成 JSON

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - 欄位
     - 意義
   * - ``status``、``reasons``
     - ``"ok"``，或是 ``"attention"`` 並為每個原因附上一句話：最近有執行失敗、某個
       監控器發現漂移或無法驗證、匯流排上有嚴重程度為 ``error`` 以上的近期事件。
   * - ``health``
     - 計數與開關：已註冊的動作、執行中的執行、排程工作、監控器、sink、路由、路由器
       是否啟用、稽核軌跡的狀態。
   * - ``run_counts``
     - 最新五十次執行的結局：``running``、``succeeded``、``failed``、
       ``cancelled``。
   * - ``running_runs``、``recent_runs``
     - 不含任務細節的執行，新的在前。
   * - ``integrity``
     - 每個具名監控器上次發現了什麼。
   * - ``events``
     - 匯流排上最新的事件，新的在前，已遮蔽。
   * - ``storage``
     - 每個後端，附 ``usable``、``detail``，以及缺少套件時的 ``install_hint``。

各部分也可以分開取得：``health()``、``runs()``、``integrity()``、
``recent_events()``、``storage_status()``。``summary()`` 絕不會因為某個部分讀不到而
拋出例外；它會把那個部分列在原因裡。

Files
-----

.. code-block:: python

   files = services.files
   files.list_dir("s3://reports/2026")              # 目錄在前，其次依路徑
   files.stat("s3://reports/2026/q1.csv").size
   preview = files.preview("s3://reports/2026/q1.csv", max_bytes=4096)
   preview.text, preview.truncated, preview.binary
   files.copy("s3://reports/2026/q1.csv", "local:///backup/")   # 放進該目錄
   files.move("local:///inbox/a.csv", "local:///done/a.csv")
   files.mkdir("local:///backup/2026")
   files.delete("local:///backup/2026", recursive=True)

預覽有兩道上限。最多回傳 ``preview_bytes``\ （64 KiB），而大於 ``fetch_limit``\
（16 MiB）的遠端檔案不會被抓取：不支援範圍讀取的後端必須先把整個檔案下載下來，才讀得
到其中任何一部分。兩個上限都是 ``FileService`` 的引數。二進位內容會以十六進位傾印
回傳，並設定 ``binary``。

目錄會連同底下的一切一起複製，而且不能搬移。每個 URI 都經過儲存層，所以 ``..`` 與
URI 中的憑證都會被拒絕。

Storage
-------

.. code-block:: python

   storage = services.storage
   for backend in storage.backends():
       print(backend.name, backend.kind, backend.usable, backend.detail)
   storage.mount_local("sandbox://jobs", "/srv/jobs")     # 限制在那個目錄內
   storage.mounts()
   storage.capabilities("sandbox://jobs")
   storage.unmount("sandbox://jobs")

``backends()`` 為每個 scheme、每個掛載點，以及每個沒有 scheme 的共用 client 各回傳
一個 ``BackendStatus``。本機與記憶體後端、掛載點，以及 client 已初始化的雲端後端，
``usable`` 為真。否則 ``detail`` 會說明如何初始化；若該 extra 的套件沒有安裝，則帶有
``pip install`` 指令（也在 ``install_hint`` 中）。這裡不會開啟任何連線。

Pipelines
---------

草稿
~~~~

管線編輯器無法編輯 ``Pipeline``：那個物件拒絕任何無效的內容，而建構中的定義大部分
時間都是無效的。``PipelineDraft`` 保存目前為止輸入的一切。

.. code-block:: python

   from automation_file.app import PipelineDraft

   draft = PipelineDraft("daily-report")
   draft.set_params({"date": "2026-10-08"})
   draft.add_task("FA_storage_copy", "download",
                  arguments={"source": "s3://in/${params.date}.csv",
                             "target": "local:///tmp/report.csv"})
   draft.add_task("FA_storage_delete", "tidy", arguments={"uri": "local:///tmp/report.csv"})
   draft.connect("download", "tidy")               # tidy 相依於 download
   draft.set_retry("download", max_attempts=5, backoff=2.0, on=["ConnectionError"])
   draft.set_timeout("download", 300)
   draft.set_condition("tidy", "always")
   draft.rename_task("tidy", "clean-up")            # 邊與占位符會跟著改

   draft.problems()                                 # [] 或 Problem(path, message, task)
   draft.to_definition()                            # Pipeline.from_dict 所接受的文件

.. list-table::
   :header-rows: 1
   :widths: 36 64

   * - 方法
     - 效果
   * - ``add_task``、``remove_task``、``rename_task``
     - 改變任務集合。沒有指定 ID 時，會由動作名稱推導。
   * - ``set_action``、``set_arguments``
     - 動作，以及它的關鍵字對應、位置清單或 ``None``。
   * - ``set_retry``、``set_timeout``、``set_condition``、``set_idempotency_key``
     - 任務如何執行。
   * - ``connect``、``disconnect``、``set_dependencies``、``edges``
     - 相依邊。指向自己的邊，或會形成循環的邊，會以 ``AppException`` 拒絕。
   * - ``set_position``、``positions``、``auto_layout``、``layout``、``apply_layout``
     - 每個任務在畫布上的位置。這是編輯器的中繼資料：絕不會出現在
       ``to_definition()`` 中。
   * - ``set_name``、``set_description``、``set_max_workers``、``set_params``、``set_schedule``
     - 定義的表頭。
   * - ``add_listener``、``batch``
     - 每次變更後都會呼叫 ``listener(change)``，其值為 ``"structure"``、
       ``"task"``、``"header"`` 或 ``"position"``；在 ``with draft.batch():``
       之內，每一種只在結束時回報一次。
   * - ``problems``、``to_definition``、``from_definition``
     - 附上每個問題路徑的驗證，以及定義文件。

執行期會拒絕的值（負的逾時、未知的動作名稱）會被保留下來，並由 ``problems()`` 回報；
只有會讓草稿不一致的編輯（重複的 ID、循環）才會立刻拋出例外。草稿不是執行緒安全的：
請只從一個執行緒編輯它，交給 worker 的則是 ``draft.to_definition()``。

檢查與執行
~~~~~~~~~~~~

每個方法都接受草稿或定義對應，並回傳普通的字典。一次執行就是
``PipelineRun.to_dict()``，其中的機敏資訊已遮蔽，另外加上 ``active`` 旗標，說明這個
行程是否仍在執行它。

.. code-block:: python

   pipelines = services.pipelines

   pipelines.action_names()                         # 給動作清單用
   pipelines.describe_action("FA_storage_copy")     # 參數、預設值、摘要

   pipelines.validate(draft)                        # 也包含：未知的動作名稱
   plan = pipelines.dry_run(draft, {"date": "2026-10-09"})
   outcome = pipelines.test_task(draft, "download", {"date": "2026-10-09"})

   run = pipelines.start(draft, {"date": "2026-10-09"})     # 背景執行
   followed = pipelines.follow(run["run_id"])       # {"run": ..., "events": [...]}
   pipelines.cancel(run["run_id"])
   pipelines.wait(run["run_id"], timeout=30)

   pipelines.resume(run["run_id"], draft)           # 保留已成功的，執行其餘的
   pipelines.retry(run["run_id"], draft)            # 新的一次執行，參數相同
   pipelines.history("daily-report", limit=10)
   pipelines.running()

``start`` 與 ``resume`` 立即回傳；定義有問題時，會在任何東西執行之前拋出例外。
``test_task`` 單獨執行一個任務：它的動作會真的執行，它的上游任務則換成替身，回傳
``results=`` 中給的值（預設為 ``None``），而且這次測試不會記錄到任何 run store，也
不會發布到共用的匯流排。

定義檔與配置
~~~~~~~~~~~~

.. code-block:: python

   draft = pipelines.load("pipelines/daily-report.yaml")
   draft.load_notes                                 # 檔案有什麼問題（如果有的話）
   pipelines.save(draft, "pipelines/daily-report.yaml")

``save`` 把定義寫成 ``.yaml``、``.yml`` 或 ``.json``，並把畫布配置寫進旁邊的
``<file>.layout.json``。定義會拒絕未知的鍵，而配置不屬於會被執行的內容，所以兩者絕
不共用一個檔案。``load`` 會開啟能解析但無效的檔案，讓它可以被修好。

Scheduler
---------

.. code-block:: python

   scheduler = services.scheduler
   scheduler.add("nightly", "0 2 * * *",
                 [["FA_pipeline_run", {"definition": "pipelines/daily-report.yaml"}]])
   scheduler.jobs()
   scheduler.remove("nightly")
   scheduler.remove_all()

``add`` 也接受 JSON 文字形式的動作清單，也就是表單提供的形式。這個服務只呼叫
``schedule_add``、``schedule_remove``、``schedule_remove_all`` 與
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
   integrity.drift()                    # 每個監控器一個 MonitorDrift，給儀表板用
   integrity.stop_monitor("reports")
   integrity.stop_started()             # 這個服務啟動的監控器

在這裡啟動的監控器，就是 ``FA_integrity_*`` 動作看到的那個具名監控器。

Audit
-----

.. code-block:: python

   audit = services.audit
   audit.status()                       # 取得 store 之前為 {"configured": False, ...}
   audit.configure("/var/lib/automation_file/audit.sqlite")
   audit.search(status="error", resource_prefix="s3://reports/", limit=20)
   audit.count(actor="scheduler")
   audit.recent(limit=30)               # 尚未設定稽核時為 []

以 ``None`` 或空字串給定的篩選條件不會限制搜尋，所以表單的值可以原樣傳入。

Notifications
-------------

.. code-block:: python

   notifications = services.notifications
   notifications.sinks()                # 名稱、型別、送達位置；絕不含機敏資訊
   notifications.add_route({"name": "failures", "sinks": "team-alerts, ops-mail",
                            "types": "pipeline.failed, task.failed",
                            "min_severity": "error", "dedup_seconds": "600"})
   notifications.routes()
   notifications.remove_route("failures")
   notifications.send_test("team-alerts")           # {"team-alerts": "sent"}

清單可以是以逗號分隔的文字，數字也可以是文字。路由若指名未註冊的 sink 會被拒絕。
``send_test`` 為每個 sink 回傳一個結果：``"sent"`` 或錯誤，其中的 URL 只留下主機。

Settings
--------

.. code-block:: python

   settings = services.settings
   settings.load("automation_file.toml")            # 一份摘要；不改變任何東西
   settings.apply("automation_file.toml")           # 註冊 sink 與路由
   for extra in settings.extras():
       print(extra.name, extra.installed, extra.install_hint)
   settings.environment()                           # 版本、平台、日誌檔

摘要包含檔案的區段、sink 與路由，以及所有機敏資訊都已遮蔽的文件。

表單輔助函式
------------------------

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - 函式
     - 用途
   * - ``parse_argument_text(text)``
     - 把一個表單欄位變成值：文字是 JSON 就當 JSON，否則就是文字本身。
   * - ``format_argument_value(value)``
     - 反方向：產生讀回來會是同一個值的文字。
   * - ``parse_json_text(text, what)``
     - 從文字欄位取得 JSON 文件，否則拋出 ``AppException``，指出 ``what`` 與錯誤的
       位置。
   * - ``split_names(text)``
     - 把 ``"a, b"`` 變成 ``["a", "b"]``。
   * - ``describe_action(name, command)``
     - 動作的參數、預設值與摘要。

機敏資訊
----------------

``mask_secrets(value)`` 回傳可以安全顯示的副本，每個服務都會把它套用在回傳的內容上：

* 存放在表明自己是機敏資訊的名稱（``password``、``token``、``api_key``、
  ``authorization``……）底下的值，會變成 ``********``；
* 存放在 ``url`` 或 ``..._url`` 底下的值，只保留 scheme 與主機；
* 在其他任何文字中，URL 的使用者資訊與 ``Bearer`` 後面的 token 會被移除。

儲存 URI 不會被更動：它不可能帶有憑證。任務的結果會原樣回傳，所以不要把機敏資訊放進
結果裡。

共用與私有的服務
--------------------------------

``app_services()`` 為每個行程回傳一組服務，建立在行程內的單例之上（預設的 resolver、
預設的 run store、事件匯流排、稽核軌跡、通知管理器與路由器）。因此同一個行程中的視窗
與 Web UI 會顯示相同的執行、監控器與路由。

``build_services`` 則建立自己的一組：

.. code-block:: python

   from automation_file.app import ServiceOptions, build_services
   from automation_file.events import EventBus
   from automation_file.pipeline import SQLiteRunStore

   services = build_services(ServiceOptions(
       run_store=SQLiteRunStore("/var/lib/automation/pipelines.db"),
       bus=EventBus(),
   ))

``ServiceOptions`` 接受 ``resolver``、``run_store``、``registry``、``bus``、
``audit_trail``、``notification_manager`` 與 ``notification_router``。不論選項為何，
排程器與完整性監控器都是整個行程共用的。

撰寫另一種使用者介面
----------------------------------------

1. 取得服務：``app_services()``，或 ``build_services(...)``。
2. 由 ``NAVIGATION`` 建立導覽。
3. 每個檢視呼叫一個服務方法，並繪製它回傳的內容。攔截
   ``FileAutomationException`` 並顯示它的文字。
4. 會碰到儲存或網路的呼叫（``files.*``、``integrity.verify``、
   ``notifications.send_test``、``settings.apply``）請從 worker 執行緒進行。
   ``pipelines.start`` 與 ``pipelines.resume`` 本來就立即回傳。
5. 管線編輯器請保留一個 ``PipelineDraft``，只透過它的方法修改它，並在 listener 中
   依它重繪。

一個雖小但完整的終端機介面：

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

出問題時
----------------

``AppException``
    這一層拒絕了請求：草稿無法接受的編輯、不是 JSON 的表單文字、缺少名稱。訊息會說明
    該改什麼。

``dry_run``、``start`` 或 ``resume`` 拋出 ``PipelineDefinitionException``
    定義無效。``error.problems`` 保存每一項發現；``validate`` 會以 ``Problem`` 物件
    回傳相同的內容而不拋出例外。

``status`` 拋出「unknown run」
    這次執行既不在這個服務的追蹤之中，也不在它的 run store 裡。除非預設 store 是
    ``SQLiteRunStore``，或曾把它傳給 ``build_services``，否則執行紀錄只保存在
    記憶體中。

``cancel`` 回傳 ``False``
    這次執行不在這個行程中進行：它已經結束，或是由另一個行程啟動的。

後端不是 ``usable``
    請讀 ``detail``。初始化 client，或安裝 ``install_hint`` 指名的 extra。

``audit.search`` 拋出「audit is not configured」
    請先呼叫 ``audit.configure(path)``。``audit.recent()`` 則會回傳空清單。

機敏資訊出現在檢視中
    它存放在沒有表明自己是機敏資訊的名稱底下，或者它是任務結果的一部分。請改掉欄位
    名稱，或不要把它放進結果。

兩個介面顯示的內容不一致
    它們用的是不同的服務組。``app_services()`` 是共用的；``build_services()``
    不是。
