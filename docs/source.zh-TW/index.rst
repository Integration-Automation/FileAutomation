###############
automation_file
###############

**以 JSON 動作清單為核心的模組化檔案自動化框架。**

``automation_file`` 把本地檔案 / 目錄 / ZIP / tar 操作、經 SSRF 驗證且
可續傳的 HTTP 下載、十一種遠端儲存後端（Google Drive、S3、Azure Blob、
Dropbox、OneDrive、Box、SFTP、FTP / FTPS、WebDAV、SMB、fsspec）、
透過內建 TCP / HTTP / MCP 伺服器執行的 JSON 動作清單、cron 排程器、
檔案監控觸發器、通知扇出、稽核紀錄、AES-256-GCM 檔案加密、Prometheus
指標，以及 PySide6 桌面圖形介面，全部統合為單一框架——一切透過共用的
``ActionRegistry`` 調度，並由單一 ``automation_file`` 門面對外呈現。

* **PyPI**：https://pypi.org/project/automation_file/
* **GitHub**：https://github.com/Integration-Automation/FileAutomation
* **Issue / 未來規劃**：https://github.com/Integration-Automation/FileAutomation/issues
* **授權**：MIT

語言：`English <../html/index.html>`_ | **繁體中文** | `简体中文 <../html-zh-CN/index.html>`_

.. contents:: 本頁目錄
   :local:
   :depth: 1

----

安裝
====

.. code-block:: bash

   pip install automation_file

每個後端（Google Drive、S3、Azure Blob、Dropbox、OneDrive、Box、SFTP、
FTP、WebDAV、SMB、fsspec）以及 PySide6 圖形介面皆為一級執行階段相依
套件——不需要記住任何選用 extra。

第一份動作
==========

一個動作是三種 JSON 形狀之一——``[name]``、``[name, {kwargs}]`` 或
``[name, [args]]``。動作清單是動作的陣列。共用的執行器會依序執行，並
回傳每筆動作的結果對應表。

.. code-block:: python

   from automation_file import execute_action

   results = execute_action([
       ["FA_create_dir",  {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
       ["FA_zip_dir",     {"dir_we_want_to_zip": "build", "zip_name": "build_snapshot"}],
   ])

同一份清單可從 CLI（``python -m automation_file run actions.json``）、
Loopback TCP / HTTP 伺服器、MCP 主機，以及圖形介面的 **JSON 動作** 分頁
直接執行——不需改寫。可參考 :doc:`usage/quickstart` 了解驗證、Dry-run
與平行執行；:doc:`usage/cli` 介紹 argparse 派發器；:doc:`architecture`
說明註冊器與執行器如何協作。

----

提供哪些功能
============

**本地操作**\ （:doc:`usage/local`）
   檔案 / 目錄 / ZIP / tar / 壓縮檔操作、``safe_join`` 路徑穿越防護、
   感知 OS 索引的 ``fast_find``、串流式 ``file_checksum`` 與
   ``find_duplicates``、``sync_dir`` rsync 風格鏡像、目錄差異比對、
   文字 patch、JSON / YAML / CSV / JSONL / Parquet 編輯、MIME 偵測、
   樣板渲染、垃圾桶送回 / 還原、檔案版本控制、條件式執行
   （``FA_if_exists`` / ``FA_if_newer`` / ``FA_if_size_gt``）、變數替換
   （``${env:…}`` / ``${date:%Y-%m-%d}`` / ``${uuid}``）、有逾時的 shell
   子行程，以及 AES-256-GCM 檔案加密。

**HTTP 傳輸**\ （:doc:`usage/transfer`）
   ``download_file`` 透過 ``validate_http_url`` 驗證每個 URL（拒絕
   ``file://`` / ``ftp://`` / 私有 / loopback / link-local / 保留位址），
   設下大小與逾時上限，支援透過 ``Range:`` 續傳到 ``<target>.part``，
   傳輸後比對 ``expected_sha256``，並可整合進度註冊器，提供即時傳輸
   快照與協作式取消。

**雲端與遠端儲存**\ （:doc:`usage/cloud`）
   Google Drive（OAuth2）、S3（boto3）、Azure Blob、Dropbox、OneDrive、
   Box、SFTP（paramiko + ``RejectPolicy``）、FTP / FTPS、WebDAV、SMB /
   CIFS 與 fsspec 橋接——皆由 ``build_default_registry()`` 自動註冊，
   並透過各自的共享單例存取。``copy_between`` 可依 URI 前綴在任兩個
   後端間搬資料。

**動作伺服器**\ （:doc:`usage/servers`）
   預設僅綁定 loopback 的 TCP 與 HTTP 伺服器，接受 JSON 動作清單，可
   選擇啟用共享密鑰驗證、伺服器端 ``ActionACL`` 白名單、
   ``GET /healthz`` / ``GET /readyz`` 健康檢查、``GET /openapi.json``、
   ``GET /progress`` WebSocket，以及帶型別的 ``HTTPActionClient`` SDK。

**MCP 伺服器**\ （:doc:`usage/mcp`）
   ``MCPServer`` 透過 stdio 上的換行分隔 JSON-RPC 2.0，把註冊器橋接到
   任何 Model Context Protocol 主機（Claude Desktop、Claude Code、MCP
   CLI）。每個 ``FA_*`` 動作會變成具自動產生輸入 schema 的 MCP 工具。

**桌面圖形介面**\ （:doc:`usage/gui`）
   PySide6 分頁控制介面——Home、Local、Transfer、Progress、JSON 動作、
   Triggers、Scheduler、Servers，加上每個雲端後端各一個分頁——共享
   相同的單例，並透過 ``ActionWorker`` 在全域執行緒池上派工。

**可靠性**\ （:doc:`usage/reliability`）
   ``retry_on_transient`` 帶有上限的指數退避、``Quota`` 大小與時間預算、
   ``CircuitBreaker``、``RateLimiter``、``FileLock`` / ``SQLiteLock``、
   持久化的 ``ActionQueue``、SQLite ``AuditLog``、用於週期清單比對的
   ``IntegrityMonitor``，以及帶型別的 ``FileAutomationException`` 階層。

**觸發器與排程**\ （:doc:`usage/events`）
   檔案監控觸發器（``FA_watch_*``）會在檔案系統事件發生時執行動作清單；
   cron 風格排程器（``FA_schedule_*``）依排程定期執行動作清單，並具備
   重疊保護——兩者皆會在失敗時回退到通知。

**通知**\ （:doc:`usage/notifications`）
   Slack、Email（SMTP）、Discord、Telegram、Microsoft Teams、PagerDuty
   與通用 Webhook 接收端，由 ``NotificationManager`` 組合，具備每接收端
   錯誤隔離與滑動視窗去重。

**設定與機敏資訊**\ （:doc:`usage/config`）
   在 ``automation_file.toml`` 裡宣告接收端與預設值；``${env:…}`` /
   ``${file:…}`` 參照透過鏈式 ``EnvSecretProvider`` / ``FileSecretProvider``
   解析；``ConfigWatcher`` 會輪詢並熱重載檔案，無需重啟。

**DAG 動作執行器**\ （:doc:`usage/dag`）
   以 DAG 形式執行動作清單，可宣告依賴、進行拓撲式平行展開、依分支
   略過失敗節點。

**可觀測性**
   ``start_metrics_server()`` 把每個動作以 Prometheus 計數器與直方圖
   對外曝光；``start_web_ui()`` 提供僅依賴標準函式庫的 HTMX 儀表板，
   呈現健康狀態、進度與註冊器。

**外掛**\ （:doc:`usage/plugins`）
   第三方套件可透過 ``[project.entry-points."automation_file.actions"]``
   註冊自家 ``FA_*`` 動作；``PackageLoader`` 會匯入一個 Python 套件，
   並把其頂層成員以 ``<package>_<member>`` 名稱註冊進註冊器。

----

閱讀順序
========

文件依語言與內容類型拆分。手冊依典型讀者旅程組織——安裝、操作本地、
串接遠端儲存、對外開伺服器、規模化自動化，最後深入可靠性、設定與
組合執行。API 參考則是每個公開模組的自動生成 Python 參考。

.. toctree::
   :maxdepth: 1
   :caption: 入門

   usage/quickstart
   usage/cli
   architecture

.. toctree::
   :maxdepth: 1
   :caption: 檔案與儲存操作

   usage/local
   usage/transfer
   usage/cloud

.. toctree::
   :maxdepth: 1
   :caption: 伺服器與介面

   usage/servers
   usage/mcp
   usage/gui

.. toctree::
   :maxdepth: 1
   :caption: 執行階段控制

   usage/reliability
   usage/events
   usage/notifications
   usage/config

.. toctree::
   :maxdepth: 1
   :caption: 組合與擴充

   usage/dag
   usage/plugins

.. toctree::
   :maxdepth: 1
   :caption: API 參考

   api/core
   api/local
   api/remote
   api/server
   api/client
   api/trigger
   api/scheduler
   api/notify
   api/progress
   api/project
   api/ui
   api/utils

----

索引
====

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
