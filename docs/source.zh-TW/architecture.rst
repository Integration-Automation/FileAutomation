架構
====

``automation_file`` 採用分層架構，核心由五種設計模式組成：

系統總覽
--------

下圖展示完整的派送表面：任何呼叫端——CLI、GUI、HTTP/MCP 客戶端、進入點外掛
——最終都會落到由 ``build_default_registry()`` 填充的共用 ``ActionRegistry``，
再從 registry 向本地 ops、遠端後端、可靠性 / 安全 / 可觀測性輔助工具、通知、
以及事件驅動的觸發器與 cron 排程器扇出。

.. mermaid::

   flowchart TD
       CLI["<b>CLI / JSON 批次</b><br/>python -m automation_file"]
       GUIUser["<b>PySide6 GUI</b><br/>launch_ui"]
       ClientSDK["<b>HTTPActionClient SDK</b>"]
       MCPHost["<b>MCP 主機</b><br/>Claude Desktop · MCP CLIs"]
       Plugins["<b>進入點外掛</b><br/>automation_file.actions"]

       subgraph Facade["<b>automation_file &mdash; 門面 (__init__.py)</b>"]
           PublicAPI["<b>Public API</b><br/>execute_action · execute_action_parallel · execute_action_dag<br/>validate_action · driver_instance · s3_instance · azure_blob_instance<br/>dropbox_instance · sftp_instance · ftp_instance · onedrive_instance · box_instance<br/>start_autocontrol_socket_server · start_http_action_server<br/>start_metrics_server · start_web_ui · MCPServer<br/>notification_manager · scheduler · trigger_manager<br/>AutomationConfig · progress_registry · Quota · retry_on_transient"]
       end

       subgraph Core["<b>core 核心</b>"]
           Registry[("<b>ActionRegistry</b><br/>FA_* 指令")]
           Executor["<b>ActionExecutor</b><br/>序列 · 並行 · dry-run · validate-first"]
           DAG["<b>dag_executor</b><br/>拓樸排程 fan-out"]
           Callback["<b>CallbackExecutor</b>"]
           Loader["<b>PackageLoader</b><br/>+ 進入點外掛"]
           Queue["<b>ActionQueue</b>"]
           Json["<b>json_store</b>"]
           Sub["<b>substitution</b><br/>${env:} ${date:} ${uuid}"]
       end

       subgraph Reliability["<b>可靠性</b>"]
           Retry["<b>retry</b><br/>@retry_on_transient"]
           QuotaMod["<b>Quota</b><br/>位元組 + 時間配額"]
           Breaker["<b>CircuitBreaker</b>"]
           RL["<b>RateLimiter</b>"]
           Locks["<b>FileLock</b> · <b>SQLiteLock</b>"]
       end

       subgraph Observability["<b>可觀測性</b>"]
           Progress["<b>progress</b><br/>CancellationToken · Reporter"]
           Metrics["<b>metrics</b><br/>Prometheus counters + histograms"]
           Audit["<b>AuditLog</b><br/>SQLite 稽核紀錄"]
           Tracing["<b>tracing</b><br/>OpenTelemetry spans"]
           FIM["<b>IntegrityMonitor</b>"]
       end

       subgraph Security["<b>安全 &amp; 設定</b>"]
           Secrets["<b>Secret providers</b><br/>Env · File · Chained"]
           Config["<b>AutomationConfig</b><br/>TOML 載入器"]
           ConfW["<b>ConfigWatcher</b><br/>熱重載"]
           Crypto["<b>crypto</b><br/>AES-256-GCM"]
           Check["<b>checksum</b> / <b>manifest</b>"]
           SafeP["<b>safe_paths</b><br/>safe_join · is_within"]
           ACL["<b>ActionACL</b>"]
       end

       subgraph Events["<b>事件驅動</b>"]
           Trigger["<b>TriggerManager</b><br/>watchdog 檔案監聽"]
           Sched["<b>Scheduler</b><br/>5-field cron + overlap guard"]
       end

       subgraph Servers["<b>伺服器</b>"]
           TCP["<b>TCPActionServer</b><br/>loopback · AUTH secret"]
           HTTPS["<b>HTTPActionServer</b><br/>POST /actions · Bearer<br/>/healthz /readyz /progress /openapi.json"]
           MCP["<b>MCPServer</b><br/>JSON-RPC 2.0 (stdio)"]
           MetSrv["<b>MetricsServer</b><br/>/metrics"]
           WebUI["<b>WebUIServer</b><br/>HTMX dashboard"]
       end

       subgraph UI["<b>ui (PySide6)</b>"]
           MainWin["<b>MainWindow</b><br/>Home · Local · HTTP · Drive · S3 · Azure · Dropbox<br/>SFTP · OneDrive · Box · JSON · Triggers · Scheduler<br/>Progress · Transfer · Servers"]
           Worker["<b>ActionWorker</b><br/>QRunnable on QThreadPool"]
       end

       subgraph Local["<b>本地 ops</b>"]
           FileOps["<b>file_ops</b> · <b>dir_ops</b>"]
           Archives["<b>zip_ops</b> · <b>tar_ops</b> · <b>archive_ops</b>"]
           DataOps["<b>data_ops</b><br/>csv · jsonl · parquet · yaml"]
           TextOps["<b>text_ops</b> · <b>diff_ops</b><br/><b>json_edit</b> · <b>templates</b>"]
           Misc["<b>shell_ops</b> · <b>sync_ops</b> · <b>trash</b><br/><b>versioning</b> · <b>conditional</b> · <b>mime</b>"]
       end

       subgraph Remote["<b>遠端後端</b>"]
           UrlVal["<b>url_validator</b><br/>SSRF 防護"]
           Http["<b>http_download</b><br/>retry · resume · SHA-256"]
           Drive["<b>google_drive</b>"]
           S3M["<b>s3</b>"]
           Azure["<b>azure_blob</b>"]
           Dropbox["<b>dropbox_api</b>"]
           SFTP["<b>sftp</b> (RejectPolicy)"]
           FTP["<b>ftp / FTPS</b>"]
           OneD["<b>onedrive</b>"]
           Box["<b>box</b>"]
           WebDAV["<b>webdav</b>"]
           SMB["<b>smb / cifs</b>"]
           Fsspec["<b>fsspec_bridge</b>"]
           Cross["<b>cross_backend</b><br/>local:// s3:// drive:// azure://<br/>dropbox:// sftp:// ftp://"]
       end

       subgraph Notify["<b>通知</b>"]
           NM["<b>NotificationManager</b><br/>fanout · dedup · SSRF guard"]
           Sinks["<b>Sinks</b><br/>Webhook · Slack · Email<br/>Telegram · Discord · Teams · PagerDuty"]
       end

       subgraph Utils["<b>工具 / 專案</b>"]
           Fast["<b>fast_find</b><br/>mdfind / locate / es.exe"]
           Dedup["<b>find_duplicates</b>"]
           Grep["<b>grep_files</b>"]
           Rotate["<b>rotate_backups</b>"]
           Discovery["<b>file_discovery</b>"]
           Builder["<b>ProjectBuilder</b> + templates"]
       end

       CLI ==> PublicAPI
       GUIUser ==> MainWin
       ClientSDK ==> HTTPS
       MCPHost ==> MCP
       Plugins ==> Loader

       MainWin ==> Worker
       Worker ==> PublicAPI

       PublicAPI ==> Executor
       PublicAPI ==> DAG
       PublicAPI ==> Callback
       PublicAPI ==> Queue
       PublicAPI ==> Config
       PublicAPI ==> NM
       PublicAPI ==> Trigger
       PublicAPI ==> Sched

       TCP ==> Executor
       HTTPS ==> Executor
       MCP ==> Registry
       MetSrv ==> Metrics
       WebUI ==> Registry
       ACL ==> TCP
       ACL ==> HTTPS

       Executor ==> Registry
       Executor ==> Sub
       Executor ==> Retry
       Executor ==> QuotaMod
       Executor ==> Metrics
       Executor ==> Audit
       Executor ==> Tracing
       Executor ==> Json
       DAG ==> Executor
       Callback ==> Registry
       Loader ==> Registry

       Trigger ==> Executor
       Sched ==> Executor
       Trigger -. 失敗時 .-> NM
       Sched -. 失敗時 .-> NM
       FIM -. 偵測到異動 .-> NM
       ConfW ==> Config
       Config ==> Secrets
       Config ==> NM

       Registry ==> FileOps
       Registry ==> Archives
       Registry ==> DataOps
       Registry ==> TextOps
       Registry ==> Misc
       Registry ==> Http
       Registry ==> Drive
       Registry ==> S3M
       Registry ==> Azure
       Registry ==> Dropbox
       Registry ==> SFTP
       Registry ==> FTP
       Registry ==> OneD
       Registry ==> Box
       Registry ==> WebDAV
       Registry ==> SMB
       Registry ==> Fsspec
       Registry ==> Cross
       Registry ==> Crypto
       Registry ==> Check
       Registry ==> Fast
       Registry ==> Dedup
       Registry ==> Grep
       Registry ==> Rotate
       Registry ==> Discovery
       Registry ==> Builder
       Registry ==> Progress

       FileOps ==> SafeP
       Archives ==> SafeP
       Misc ==> SafeP

       Http ==> UrlVal
       Http ==> Retry
       Http ==> Progress
       Http ==> Check
       S3M ==> Progress
       WebDAV ==> UrlVal
       NM ==> UrlVal
       NM ==> Sinks

       Cross ==> Drive
       Cross ==> S3M
       Cross ==> Azure
       Cross ==> Dropbox
       Cross ==> SFTP
       Cross ==> FTP

       classDef entry fill:#FDEDEC,stroke:#641E16,stroke-width:3px,color:#000,font-weight:bold;
       classDef facade fill:#D6EAF8,stroke:#154360,stroke-width:4px,color:#000,font-weight:bold;
       classDef core fill:#FEF9E7,stroke:#1F3A93,stroke-width:3px,color:#000,font-weight:bold;
       classDef rel fill:#D1F2EB,stroke:#0B5345,stroke-width:3px,color:#000,font-weight:bold;
       classDef obs fill:#FDEBD0,stroke:#9C640C,stroke-width:3px,color:#000,font-weight:bold;
       classDef sec fill:#F5B7B1,stroke:#78281F,stroke-width:3px,color:#000,font-weight:bold;
       classDef event fill:#FCF3CF,stroke:#7D6608,stroke-width:3px,color:#000,font-weight:bold;
       classDef server fill:#FADBD8,stroke:#922B21,stroke-width:3px,color:#000,font-weight:bold;
       classDef ui fill:#AED6F1,stroke:#1B4F72,stroke-width:3px,color:#000,font-weight:bold;
       classDef localOps fill:#E8DAEF,stroke:#512E5F,stroke-width:3px,color:#000,font-weight:bold;
       classDef remote fill:#D5F5E3,stroke:#196F3D,stroke-width:3px,color:#000,font-weight:bold;
       classDef notify fill:#F9E79F,stroke:#7D6608,stroke-width:3px,color:#000,font-weight:bold;
       classDef utils fill:#EAEDED,stroke:#212F3C,stroke-width:3px,color:#000,font-weight:bold;

       class CLI,GUIUser,ClientSDK,MCPHost,Plugins entry;
       class PublicAPI facade;
       class Registry,Executor,DAG,Callback,Loader,Queue,Json,Sub core;
       class Retry,QuotaMod,Breaker,RL,Locks rel;
       class Progress,Metrics,Audit,Tracing,FIM obs;
       class Secrets,Config,ConfW,Crypto,Check,SafeP,ACL sec;
       class Trigger,Sched event;
       class TCP,HTTPS,MCP,MetSrv,WebUI server;
       class MainWin,Worker ui;
       class FileOps,Archives,DataOps,TextOps,Misc localOps;
       class UrlVal,Http,Drive,S3M,Azure,Dropbox,SFTP,FTP,OneD,Box,WebDAV,SMB,Fsspec,Cross remote;
       class NM,Sinks notify;
       class Fast,Dedup,Grep,Rotate,Discovery,Builder utils;

       linkStyle default stroke:#1F2A44,stroke-width:2.5px;

設計模式
--------

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
