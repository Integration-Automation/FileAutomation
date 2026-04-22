架構
====

``automation_file`` 採用分層架構，核心由五種設計模式組成：

**Facade（外觀）**
   :mod:`automation_file`（頂層 ``__init__``）是使用者唯一需要匯入的名稱。
   所有公開函式與單例都從這裡重新匯出。

**Registry + Command（登錄 + 命令）**
   :class:`~automation_file.core.action_registry.ActionRegistry` 將動作名稱
   （出現於 JSON 動作清單中的字串）對應到 Python 可呼叫物件。一個動作是
   形如 ``[name]``、``[name, {kwargs}]`` 或 ``[name, [args]]`` 的命令物件。

**Template Method（樣板方法）**
   :class:`~automation_file.core.action_executor.ActionExecutor` 定義單一動作
   的生命週期：解析名稱 → 調度呼叫 → 捕捉回傳值或例外。外層迭代樣板保證一個
   錯誤動作不會中斷整批執行，除非設定 ``validate_first=True``。

**Strategy（策略）**
   每個 ``local/*_ops.py``、``remote/*_ops.py`` 與雲端子套件都是一組獨立的
   策略函式。所有後端——本地、HTTP、Google Drive、S3、Azure Blob、Dropbox、
   SFTP——由 :func:`automation_file.core.action_registry.build_default_registry`
   自動登錄。``register_<backend>_ops(registry)`` 輔助函式仍保留為公開 API，
   供自行組裝登錄表的呼叫者使用。

**Singleton（模組層單例）**
   ``executor``、``callback_executor``、``package_manager``、``driver_instance``、
   ``s3_instance``、``azure_blob_instance``、``dropbox_instance``、
   ``sftp_instance`` 是在 ``__init__`` 中連結的共享實例，讓外掛與 CLI 看到
   相同的狀態。

模組結構
--------

.. code-block:: text

   automation_file/
   ├── __init__.py           # Facade——所有公開名稱
   ├── __main__.py           # 具備子命令的 CLI
   ├── exceptions.py         # FileAutomationException 例外階層
   ├── logging_config.py     # file_automation_logger
   ├── core/
   │   ├── action_registry.py
   │   ├── action_executor.py   # 序列 / 平行 / dry-run / validate-first
   │   ├── dag_executor.py      # 具平行展開的拓撲排程器
   │   ├── callback_executor.py
   │   ├── package_loader.py
   │   ├── plugins.py           # entry-point 外掛探索
   │   ├── json_store.py
   │   ├── retry.py             # @retry_on_transient
   │   ├── quota.py             # Quota(max_bytes, max_seconds)
   │   ├── checksum.py          # file_checksum、verify_checksum
   │   ├── manifest.py          # write_manifest、verify_manifest
   │   ├── config.py            # AutomationConfig（TOML 載入器 + 密鑰解析）
   │   ├── secrets.py           # Env/File/Chained 密鑰提供者
   │   └── progress.py          # CancellationToken、ProgressReporter、progress_registry
   ├── local/
   │   ├── file_ops.py
   │   ├── dir_ops.py
   │   ├── zip_ops.py
   │   ├── sync_ops.py          # rsync 風格的增量同步
   │   └── safe_paths.py        # safe_join + is_within
   ├── remote/
   │   ├── url_validator.py     # SSRF 防護
   │   ├── http_download.py     # 具重試的 HTTP 下載
   │   ├── google_drive/
   │   ├── s3/                  # 由 build_default_registry() 自動登錄
   │   ├── azure_blob/          # 由 build_default_registry() 自動登錄
   │   ├── dropbox_api/         # 由 build_default_registry() 自動登錄
   │   └── sftp/                # 由 build_default_registry() 自動登錄
   ├── server/
   │   ├── tcp_server.py        # 僅限 loopback、可選共享密鑰
   │   └── http_server.py       # POST /actions、Bearer 驗證
   ├── trigger/
   │   └── manager.py           # FileWatcher + TriggerManager（以 watchdog 為底層）
   ├── scheduler/
   │   ├── cron.py              # 5 欄位 cron 表達式解析器
   │   └── manager.py           # Scheduler 背景執行緒 + ScheduledJob
   ├── notify/
   │   ├── sinks.py             # Webhook / Slack / Email sink
   │   └── manager.py           # NotificationManager（扇出 + 去重 + auto-notify hook）
   ├── project/
   │   ├── project_builder.py
   │   └── templates.py
   ├── ui/                      # PySide6 GUI
   │   ├── launcher.py          # launch_ui(argv)
   │   ├── main_window.py       # 分頁式 MainWindow（Home、Local、Transfer、
   │   │                        #   Progress、JSON actions、Triggers、
   │   │                        #   Scheduler、Servers）
   │   ├── worker.py            # ActionWorker（QRunnable）
   │   ├── log_widget.py        # LogPanel
   │   └── tabs/                # 每個後端一個分頁 + JSON runner + servers
   └── utils/
       ├── file_discovery.py
       ├── fast_find.py         # OS 索引（mdfind/locate/es）+ scandir 後備
       └── deduplicate.py       # size → partial-hash → full-hash 去重管線

執行模式
--------

共享執行器支援五種互相正交的模式：

* ``execute_action(actions)``——預設的序列執行；每個錯誤都會被捕捉並記錄，
  不會中斷整批執行。
* ``execute_action(actions, validate_first=True)``——執行前先解析所有名稱；
  發現拼寫錯誤會在任何動作執行前即時中止。
* ``execute_action(actions, dry_run=True)``——解析每個動作並記錄將呼叫的內容，
  但不實際呼叫底層函式。
* ``execute_action_parallel(actions, max_workers=4)``——透過執行緒池平行
  調度動作。呼叫者需自行確保所選動作彼此獨立。
* ``execute_action_dag(nodes, max_workers=4, fail_fast=True)``——Kahn 風格的
  拓撲排程。每個節點形如 ``{"id": str, "action": [...], "depends_on":
  [id, ...]}``。彼此獨立的分支會平行執行；失敗分支的後續依賴會被標記為
  ``skipped``（或在 ``fail_fast=False`` 下仍會執行）。循環 / 未知依賴 /
  重複 id 會在任何節點執行前被拒絕。

可靠性工具
----------

* :func:`automation_file.core.retry.retry_on_transient`——裝飾器，對
  ``ConnectionError`` / ``TimeoutError`` / ``OSError`` 進行有上限的指數退避
  重試，:func:`automation_file.download_file` 已套用。
* :class:`automation_file.core.quota.Quota`——資料類別，整合選用的
  ``max_bytes`` 大小上限與 ``max_seconds`` 時間預算。
* :func:`automation_file.core.checksum.file_checksum` 與
  :func:`automation_file.core.checksum.verify_checksum`——串流式檔案雜湊
  （支援 :mod:`hashlib` 的任何演算法），並以常數時間比較摘要。
  :func:`automation_file.download_file` 接受 ``expected_sha256=`` 參數，
  在 HTTP 傳輸結束後立即驗證目標檔案。
* 可續傳下載：:func:`automation_file.download_file` 接受 ``resume=True``，
  會寫入 ``<target>.part`` 並送出 ``Range: bytes=<n>-``，讓中斷的傳輸從
  既有位元組數接續，而不是從零重來。
* :func:`automation_file.utils.deduplicate.find_duplicates`——三階段
  size → partial-hash → full-hash 管線；大多數檔案根本不會被雜湊，因為
  大小唯一的群組在讀取任何摘要前就會被丟棄。
* :func:`automation_file.sync_dir`——使用 ``(size, mtime)`` 或基於雜湊的
  變更偵測執行增量目錄鏡像，可選擇刪除多餘檔案並支援 dry-run。
* :func:`automation_file.write_manifest` /
  :func:`automation_file.verify_manifest`——為根目錄下的每個檔案摘要
  建立 JSON 快照，可用於發行產物驗證與竄改偵測。
* :class:`automation_file.core.progress.CancellationToken` 與
  :class:`automation_file.core.progress.ProgressReporter`——傳輸的可選
  儀表化。HTTP 下載與 S3 上傳 / 下載接受 ``progress_name=`` 關鍵字參數，
  將兩個元件串接到傳輸迴圈；JSON 動作 ``FA_progress_list`` /
  ``FA_progress_cancel`` / ``FA_progress_clear`` 操作共享登錄表。

事件驅動的調度
--------------

兩個長時間執行的子系統共用主執行器，而不是自行分叉獨立的調度路徑：

* :mod:`automation_file.trigger` 包裝 ``watchdog`` 觀察者。每個
  :class:`~automation_file.trigger.FileWatcher` 會把相符的檔案系統事件
  轉送給共享登錄表調度的動作清單。
  :data:`~automation_file.trigger.trigger_manager` 擁有 name → watcher
  對應表，讓 GUI 與 JSON 動作共享同一個生命週期。
* :mod:`automation_file.scheduler` 執行一個背景執行緒，在分鐘邊界甦醒、
  走訪已登錄的 :class:`~automation_file.scheduler.ScheduledJob`，並在
  短生命週期的工作執行緒上調度每個相符的任務，避免慢動作拖累後續任務。

當動作清單拋出 :class:`~automation_file.exceptions.FileAutomationException`
時，兩個調度器都會呼叫
:func:`automation_file.notify.manager.notify_on_failure`。未登錄任何 sink 時
此輔助函式不做任何事，因此自動通知只是在登錄任何
:class:`~automation_file.NotificationSink` 後自然產生的副作用。

通知
----

:mod:`automation_file.notify` 內建三個具體 sink
（:class:`~automation_file.WebhookSink`、:class:`~automation_file.SlackSink`、
:class:`~automation_file.EmailSink`），共同藏於一個
:class:`~automation_file.NotificationManager` 扇出之後。管理器負責：

* 每個 sink 的錯誤隔離——一個故障的 sink 不會使其他 sink 失敗。
* 基於 ``(subject, body, level)`` 的滑動視窗去重，避免卡住的觸發器
  灌爆通道。
* 模組層單例 :data:`~automation_file.notification_manager`，讓 CLI、GUI、
  長時間執行的調度器全部透過同一份狀態發布。

每個 webhook / Slack URL 都會經由
:func:`~automation_file.remote.url_validator.validate_http_url` 阻擋 SSRF 目標。
Email sink 永遠不會在 ``repr()`` 中暴露密碼。

組態與密鑰
----------

:class:`automation_file.AutomationConfig` 會載入 ``automation_file.toml``
文件，並提供輔助方法以實體化 sink / 預設值。密鑰佔位符（``${env:NAME}`` /
``${file:NAME}``）在載入時透過
:class:`~automation_file.ChainedSecretProvider`（由
:class:`~automation_file.EnvSecretProvider` 與 / 或
:class:`~automation_file.FileSecretProvider` 組成）解析。未解析的引用會
拋出 :class:`~automation_file.SecretNotFoundException`，拼錯的名稱不會
默默變成空字串。

安全邊界
--------

* **SSRF 防護**：所有外送 HTTP URL 皆經由
  :func:`automation_file.remote.url_validator.validate_http_url` 驗證。
* **路徑穿越**：
  :func:`automation_file.local.safe_paths.safe_join` 將使用者提供的路徑
  解析於指定根目錄之下，並拒絕 ``..``、位於根目錄外的絕對路徑，以及
  指向根目錄外的符號連結。
* **TCP / HTTP 驗證**：兩個伺服器都接受可選的 ``shared_secret``。設定後，
  TCP 伺服器要求 payload 前綴 ``AUTH <secret>\\n``，HTTP 伺服器要求
  ``Authorization: Bearer <secret>``。兩者預設綁定 loopback，除非明確
  傳入 ``allow_non_loopback=True``，否則拒絕非 loopback 綁定。
* **SFTP 主機驗證**：SFTP client 使用 :class:`paramiko.RejectPolicy`，
  絕不自動加入未知的主機金鑰。
* **外掛載入**：:class:`automation_file.core.package_loader.PackageLoader`
  可登錄任意模組成員；切勿將其暴露給不受信任的輸入。Entry-point 的
  探索路徑（:func:`automation_file.core.plugins.load_entry_point_plugins`）
  較為安全——只有使用者自行安裝的套件才能貢獻命令；但每個外掛仍以
  函式庫的完整權限執行，安裝第三方外掛前請務必審視。

Entry-point 外掛
----------------

第三方套件可在不需要 ``automation_file`` 匯入它們的情況下，提供額外
動作。外掛在自己的 ``pyproject.toml`` 中宣告::

   [project.entry-points."automation_file.actions"]
   my_plugin = "my_plugin:register"

其中 ``register`` 是零參數的可呼叫物件，回傳
``Mapping[str, Callable]``——與傳入
:func:`automation_file.add_command_to_executor` 的資料形狀相同。
:func:`automation_file.core.action_registry.build_default_registry`
會在內建命令連結完成後呼叫
:func:`automation_file.core.plugins.load_entry_point_plugins`，
因此每個新建立的登錄表都會自動填入已安裝的外掛。外掛失敗（匯入
錯誤、factory 例外、回傳形狀錯誤、登錄表拒絕）會被記錄並吞下，
一個壞外掛不會破壞整個函式庫。

共享單例
--------

``automation_file/__init__.py`` 建立下列行程層級單例：

* ``executor``——:func:`execute_action` 使用的 :class:`ActionExecutor`。
* ``callback_executor``——與 ``executor.registry`` 綁定的
  :class:`CallbackExecutor`。
* ``package_manager``——同一個登錄表的 :class:`PackageLoader`。
* ``driver_instance``、``s3_instance``、``azure_blob_instance``、
  ``dropbox_instance``、``sftp_instance``——各個雲端後端的延遲初始化
  client。

所有 executor 共享同一個 :class:`ActionRegistry`，因此呼叫
:func:`add_command_to_executor`（或任一 ``register_*_ops`` 輔助函式）
會讓新命令立即對所有調度器可見。
