使用指南
========

JSON 動作清單
-------------

動作可採三種形狀之一：

.. code-block:: json

   ["FA_name"]
   ["FA_name", {"kwarg": "value"}]
   ["FA_name", ["positional", "args"]]

動作清單是動作的陣列。執行器依序執行並回傳
``"execute: <action>" -> result | repr(error)`` 的對應表。

.. code-block:: python

   from automation_file import execute_action, read_action_json

   results = execute_action([
       ["FA_create_dir", {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
       ["FA_zip_dir", {"dir_we_want_to_zip": "build", "zip_name": "build_snapshot"}],
   ])

   # 或從檔案讀入：
   results = execute_action(read_action_json("actions.json"))

驗證、dry-run、平行執行
-----------------------

.. code-block:: python

   from automation_file import (
       execute_action, execute_action_parallel, validate_action,
   )

   # Fail-fast 驗證：若有未知名稱，執行前即中止整批。
   execute_action(actions, validate_first=True)

   # Dry-run：記錄將呼叫什麼但不實際呼叫。
   execute_action(actions, dry_run=True)

   # 平行：透過執行緒池執行彼此獨立的動作。
   execute_action_parallel(actions, max_workers=4)

   # 手動驗證——回傳已解析的名稱列表。
   names = validate_action(actions)

CLI
---

執行 JSON 動作清單的舊式參數::

   python -m automation_file --execute_file actions.json
   python -m automation_file --execute_dir ./actions/
   python -m automation_file --execute_str '[["FA_create_dir",{"dir_path":"x"}]]'
   python -m automation_file --create_project ./my_project

一次性操作的子命令::

   python -m automation_file ui
   python -m automation_file zip ./src out.zip --dir
   python -m automation_file unzip out.zip ./restored
   python -m automation_file download https://example.com/file.bin file.bin
   python -m automation_file create-file hello.txt --content "hi"
   python -m automation_file server --host 127.0.0.1 --port 9943
   python -m automation_file http-server --host 127.0.0.1 --port 9944
   python -m automation_file drive-upload my.txt --token token.json --credentials creds.json

Google Drive
------------

.. code-block:: python

   from automation_file import driver_instance, drive_upload_to_drive

   driver_instance.later_init("token.json", "credentials.json")
   drive_upload_to_drive("example.txt")

TCP 動作伺服器
--------------

.. code-block:: python

   from automation_file import start_autocontrol_socket_server

   server = start_autocontrol_socket_server(
       host="localhost", port=9943, shared_secret="optional-secret",
   )
   # 稍後：
   server.shutdown()
   server.server_close()

設定 ``shared_secret`` 後，client 必須在 JSON 動作清單之前加上
``AUTH <secret>\\n`` 前綴。伺服器預設仍綁定 loopback，除非顯式傳入
``allow_non_loopback=True``，否則拒絕非 loopback 綁定。

HTTP 動作伺服器
---------------

.. code-block:: python

   from automation_file import start_http_action_server

   server = start_http_action_server(
       host="127.0.0.1", port=9944, shared_secret="optional-secret",
   )

   # 客戶端：
   # curl -H 'Authorization: Bearer optional-secret' \
   #      -d '[["FA_create_dir",{"dir_path":"x"}]]' \
   #      http://127.0.0.1:9944/actions

HTTP 回應為 JSON。設定 ``shared_secret`` 後，客戶端必須送出
``Authorization: Bearer <secret>``。

可靠性
------

對自訂的可呼叫物件套用重試：

.. code-block:: python

   from automation_file import retry_on_transient

   @retry_on_transient(max_attempts=5, backoff_base=0.5)
   def flaky_network_call(): ...

對單一動作套用配額限制：

.. code-block:: python

   from automation_file import Quota

   quota = Quota(max_bytes=50 * 1024 * 1024, max_seconds=30.0)
   with quota.time_budget("bulk-upload"):
       bulk_upload_work()

路徑安全
--------

.. code-block:: python

   from automation_file import safe_join

   target = safe_join("/data/jobs", user_supplied_path)
   # -> 若解析後的路徑逃出 /data/jobs，會拋出 PathTraversalException。

雲端 / SFTP 後端
----------------

每個後端（S3、Azure Blob、Dropbox、SFTP）皆隨 ``automation_file`` 一併打包，
並由 :func:`~automation_file.core.action_registry.build_default_registry`
自動登錄。不需要額外安裝步驟——對單例呼叫 ``later_init`` 即可：

.. code-block:: python

   from automation_file import execute_action, s3_instance

   s3_instance.later_init(region_name="us-east-1")

   execute_action([
       ["FA_s3_upload_file", {"local_path": "report.csv", "bucket": "reports", "key": "report.csv"}],
   ])

所有後端都提供相同的五項操作：
``upload_file``、``upload_dir``、``download_file``、``delete_*``、``list_*``。
``register_<backend>_ops(registry)`` 依然公開，供自行建立登錄表的呼叫者使用。

SFTP 特別使用 :class:`paramiko.RejectPolicy`——未知主機會被拒絕而非自動加入。
請顯式提供 ``known_hosts``，或仰賴 ``~/.ssh/known_hosts``。

檔案監看觸發器
--------------

當受監看路徑發生檔案系統事件時執行動作清單。模組層的
:data:`~automation_file.trigger.trigger_manager` 以名稱為鍵維護一組活動
watcher，讓 JSON 介面與 GUI 共享同一個生命週期。

.. code-block:: python

   from automation_file import watch_start, watch_stop

   watch_start(
       name="inbox-sweeper",
       path="/data/inbox",
       action_list=[["FA_copy_all_file_to_dir", {"source_dir": "/data/inbox",
                                                 "target_dir": "/data/processed"}]],
       events=["created", "modified"],
       recursive=False,
   )
   # 稍後：
   watch_stop("inbox-sweeper")

也可以透過 JSON 動作清單以 ``FA_watch_start`` / ``FA_watch_stop`` /
``FA_watch_stop_all`` / ``FA_watch_list`` 操作。

Cron 排程器
-----------

按週期性排程執行動作清單。5 欄位 cron 解析器支援 ``*``、精確值、``a-b``
範圍、逗號分隔清單與 ``*/n`` 步進語法，並能使用 ``jan``..``dec`` /
``sun``..``sat`` 別名。

.. code-block:: python

   from automation_file import schedule_add

   schedule_add(
       name="nightly-snapshot",
       cron_expression="0 2 * * *",           # 每日本地時間 02:00
       action_list=[["FA_zip_dir", {"dir_we_want_to_zip": "/data",
                                    "zip_name": "/backup/data_nightly"}]],
   )

背景執行緒在分鐘邊界甦醒，因此不支援秒級精度的表達式。可透過 JSON 使用
``FA_schedule_add`` / ``FA_schedule_remove`` / ``FA_schedule_remove_all`` /
``FA_schedule_list``。

傳輸進度與取消
--------------

對 :func:`download_file`、:func:`s3_upload_file` 或 :func:`s3_download_file`
傳入 ``progress_name="<label>"`` 即可把傳輸登錄到共享進度登錄表。GUI
的 **Progress** 分頁每半秒輪詢登錄表；``FA_progress_list``、
``FA_progress_cancel`` 與 ``FA_progress_clear`` 讓 JSON 動作清單取得同樣的視圖。

.. code-block:: python

   from automation_file import download_file, progress_cancel

   # 一個執行緒：
   download_file("https://example.com/big.bin", "big.bin",
                 progress_name="big-download")

   # 另一執行緒 / GUI：
   progress_cancel("big-download")

取消會在傳輸迴圈中拋出 :class:`~automation_file.CancelledException`。
傳輸函式會捕捉這個例外、將 reporter 標記為 ``status="cancelled"`` 並
回傳 ``False``——呼叫者不需自行處理例外。

快速檔案搜尋
------------

:func:`fast_find` 會挑選主機上最便宜的後端——優先使用 OS 索引，否則
串流 scandir 走訪——以最小能耗掃描大型目錄樹：

* macOS： ``mdfind`` （Spotlight）
* Linux： ``plocate`` / ``locate`` 資料庫
* Windows：若已安裝 Everything 的 ``es.exe`` CLI
* 後備： ``os.scandir`` 產生器 + ``fnmatch`` 比對，並以 ``limit=`` 提早終止

.. code-block:: python

   from automation_file import fast_find, scandir_find, has_os_index

   # 有索引時查詢索引，否則落到 scandir。
   results = fast_find("/var/log", "*.log", limit=100)

   # 強制走可攜路徑（略過 OS 索引）。
   results = fast_find("/data", "report_*.csv", use_index=False)

   # 串流產生器——不需掃整棵樹即可提前終止。
   for path in scandir_find("/data", "*.csv"):
       if "2026" in path:
           break

   # fast_find 會嘗試哪個索引？回傳 "mdfind" / "locate" /
   # "plocate" / "es" / None。
   has_os_index()

JSON 動作清單也可使用 ``FA_fast_find``：

.. code-block:: json

   [["FA_fast_find", {"root": "/var/log", "pattern": "*.log", "limit": 50}]]

檢查碼與完整性驗證
------------------

以串流讀取器（支援 :mod:`hashlib` 的任何演算法）雜湊任何檔案，並以
常數時間比較驗證預期摘要：

.. code-block:: python

   from automation_file import file_checksum, verify_checksum

   digest = file_checksum("bundle.tar.gz")                 # 預設 sha256
   verify_checksum("bundle.tar.gz", digest)                # -> True
   verify_checksum("bundle.tar.gz", "deadbeef...", algorithm="blake2b")

相同函式在 JSON 動作清單中是 ``FA_file_checksum`` 與
``FA_verify_checksum``。

可續傳 HTTP 下載
----------------

:func:`~automation_file.download_file` 接受 ``resume=True``。內容會寫入
``<target>.part``；若暫存檔已存在，下次呼叫會送出 ``Range: bytes=<n>-``
讓傳輸從先前停止處接續。結合 ``expected_sha256=`` 可在最後一塊寫入後
立即驗證下載：

.. code-block:: python

   from automation_file import download_file

   download_file(
       "https://example.com/big.bin",
       "big.bin",
       resume=True,
       expected_sha256="3b0c44298fc1...",
   )

檔案去重
--------

:func:`~automation_file.find_duplicates` 以 ``os.scandir`` 走訪目錄樹一次，
並執行三階段 size → partial-hash → full-hash 管線。擁有唯一大小的檔案
完全不會被雜湊，因此數百萬檔案的樹掃描仍然便宜：

.. code-block:: python

   from automation_file import find_duplicates

   groups = find_duplicates("/data", min_size=1024)
   # groups: list[list[str]]，每個內層清單為一組完全相同的檔案，
   # 依大小遞減排序。

``FA_find_duplicates`` 公開同一個呼叫給 JSON 動作清單使用。

目錄增量同步
------------

:func:`~automation_file.sync_dir` 把 ``src`` 鏡像到 ``dst``，只複製新的
或已變更的檔案。變更偵測預設為 ``(size, mtime)``；當 mtime 不可靠時
請傳入 ``compare="checksum"``。``dst`` 下的額外檔案預設不會動到，
需傳入 ``delete=True`` 才會刪除（並可用 ``dry_run=True`` 預覽）：

.. code-block:: python

   from automation_file import sync_dir

   summary = sync_dir("/data/src", "/data/dst", delete=True)
   # summary: {"copied": [...], "skipped": [...], "deleted": [...],
   #           "errors": [...], "dry_run": False}

JSON 動作形式為 ``FA_sync_dir``。符號連結會以符號連結重建而非跟隨，
因此指向目錄樹外的連結不會打翻鏡像。

目錄清單快照
------------

把目錄樹下所有檔案的 JSON 清單寫下來，稍後驗證目錄樹未被變動。
適用於發行產物驗證、備份完整性檢查、搬移前的飛行前檢查：

.. code-block:: python

   from automation_file import write_manifest, verify_manifest

   write_manifest("/release/payload", "/release/MANIFEST.json")

   # 稍後……
   result = verify_manifest("/release/payload", "/release/MANIFEST.json")
   if not result["ok"]:
       raise SystemExit(f"manifest mismatch: {result}")

``result`` 分別報告 ``matched``、``missing``、``modified``、``extra`` 清單。
額外檔案不算驗證失敗（與 ``sync_dir`` 的「預設不刪除」行為一致）；
``missing`` 或 ``modified`` 則會。這兩個操作以 ``FA_write_manifest``
與 ``FA_verify_manifest`` 暴露給 JSON 動作清單。

通知
----

透過 webhook、Slack 或 SMTP 推送一次性訊息，或在觸發器 / 排程器失敗時
自動通知：

.. code-block:: python

   from automation_file import (
       SlackSink, WebhookSink, EmailSink,
       notification_manager, notify_send,
   )

   notification_manager.register(SlackSink("https://hooks.slack.com/services/T/B/X"))
   notify_send("deploy complete", body="rev abc123", level="info")

每個 sink 都實作同樣的 ``send(subject, body, level)`` 介面，扇出
:class:`~automation_file.NotificationManager` 負責：

- 每個 sink 的錯誤隔離——一個故障 sink 不會使其他 sink 死掉。
- 滑動視窗去重——在 ``dedup_seconds`` 內，完全相同的
  ``(subject, body, level)`` 訊息會被丟棄，避免卡住的觸發器灌爆通道。
- 對每個 webhook / Slack URL 做 SSRF 驗證。

排程器與觸發器調度器會在失敗時以 ``level="error"`` 自動通知——只要
登錄 sink 即可取得生產告警。JSON 動作形式為 ``FA_notify_send`` 與
``FA_notify_list``。

組態檔與密鑰提供者
------------------

把通知 sink 與預設值一次寫在 TOML 檔裡。密鑰引用在載入時會從環境變數
或檔案根目錄解析（Docker / K8s 風格）：

.. code-block:: toml

   # automation_file.toml

   [secrets]
   file_root = "/run/secrets"

   [defaults]
   dedup_seconds = 120

   [[notify.sinks]]
   type = "slack"
   name = "team-alerts"
   webhook_url = "${env:SLACK_WEBHOOK}"

   [[notify.sinks]]
   type = "email"
   name = "ops-email"
   host = "smtp.example.com"
   port = 587
   sender = "alerts@example.com"
   recipients = ["ops@example.com"]
   username = "${env:SMTP_USER}"
   password = "${file:smtp_password}"

.. code-block:: python

   from automation_file import AutomationConfig, notification_manager

   config = AutomationConfig.load("automation_file.toml")
   config.apply_to(notification_manager)

未解析的 ``${…}`` 引用會拋出
:class:`~automation_file.SecretNotFoundException` 而非默默變成空字串。
自訂的 provider 鏈可透過 :class:`~automation_file.ChainedSecretProvider` /
:class:`~automation_file.EnvSecretProvider` /
:class:`~automation_file.FileSecretProvider` 組裝，並傳給
``AutomationConfig.load(path, provider=…)``。

DAG 動作執行器
--------------

:func:`~automation_file.execute_action_dag` 依依賴關係執行動作。每個節點
形如 ``{"id": str, "action": [name, ...], "depends_on": [id, ...]}``。
彼此獨立的分支在執行緒池中扇出；當節點失敗時，其後續依賴會被標記為
``skipped``（``fail_fast=True``，預設）或仍會執行（``fail_fast=False``）：

.. code-block:: python

   from automation_file import execute_action_dag

   results = execute_action_dag([
       {"id": "fetch",  "action": ["FA_download_file",
                                   ["https://example.com/src.tar.gz", "src.tar.gz"]]},
       {"id": "verify", "action": ["FA_verify_checksum",
                                   ["src.tar.gz", "3b0c44298fc1..."]],
                        "depends_on": ["fetch"]},
       {"id": "unpack", "action": ["FA_unzip_file", ["src.tar.gz", "src"]],
                        "depends_on": ["verify"]},
       {"id": "report", "action": ["FA_fast_find", ["src", "*.py"]],
                        "depends_on": ["unpack"]},
   ])

循環、未知依賴、自我依賴與重複 id 會在任何節點執行前拋出
:class:`~automation_file.exceptions.DagException`。JSON 動作形式為
``FA_execute_action_dag``。

Entry-point 外掛
----------------

第三方套件可在自己的 ``pyproject.toml`` 中宣告 ``automation_file.actions``
entry point，以登錄自己的 ``FA_*`` 命令::

   [project.entry-points."automation_file.actions"]
   my_plugin = "my_plugin:register"

其中 ``register`` 是零參數的可呼叫物件，回傳
``Mapping[str, Callable]``。外掛安裝到同一虛擬環境後，
:func:`~automation_file.core.action_registry.build_default_registry`
會自動採用——呼叫端不需任何修改：

.. code-block:: python

   # my_plugin/__init__.py
   def greet(name: str) -> str:
       return f"hello {name}"

   def register() -> dict:
       return {"FA_greet": greet}

.. code-block:: python

   # 消費端（執行 `pip install my_plugin` 之後）
   from automation_file import execute_action
   execute_action([["FA_greet", {"name": "world"}]])

外掛失敗（匯入錯誤、factory 例外、回傳形狀錯誤、登錄表拒絕）會被記錄
並吞下，一個壞外掛不會破壞整個函式庫。

GUI（PySide6）
--------------

分頁式控制介面把每項功能都包起來：

.. code-block:: bash

   python -m automation_file ui
   # 或在 repo 根目錄以開發模式執行：
   python main_ui.py

.. code-block:: python

   from automation_file import launch_ui

   launch_ui()

分頁：Home、Local、Transfer、Progress、JSON actions、Triggers、Scheduler、
Servers。分頁下方的常駐 log panel 會即時串流每次呼叫的結果或錯誤。
背景工作透過 ``ActionWorker`` 在 ``QThreadPool`` 上執行，保持 UI 反應靈敏。

加入自訂命令
------------

.. code-block:: python

   from automation_file import add_command_to_executor, execute_action

   def greet(name: str) -> str:
       return f"hello {name}"

   add_command_to_executor({"greet": greet})
   execute_action([["greet", {"name": "world"}]])

動態套件登錄
------------

.. code-block:: python

   from automation_file import package_manager, execute_action

   package_manager.add_package_to_executor("math")
   execute_action([["math_sqrt", [16.0]]])   # -> 4.0

.. warning::

   ``package_manager.add_package_to_executor`` 實際上會登錄套件中所有頂層
   函式 / 類別 / 內建物件。切勿把它暴露給不受信任的輸入（例如透過 TCP 或
   HTTP 伺服器）。
