============================
automation_file 繁體中文文件
============================

繁中手冊依典型讀者旅程拆分為章節：安裝 → 執行 JSON 動作 → 操作本地檔案
→ 串接遠端儲存 → 對外開伺服器 → 規模化自動化。可使用左側目錄，或直接
跳到下方任一章節。

.. contents:: 本頁目錄
   :local:
   :depth: 1

----

.. _zh-tw-getting-started:

第 1 章 — 入門
==============

安裝 ``automation_file``、執行第一份 JSON 動作清單，並理解註冊器與
執行器之間的分工。

.. toctree::
   :maxdepth: 2
   :caption: 入門

   usage/quickstart

.. _zh-tw-cli:

第 2 章 — CLI
=============

使用 ``python -m automation_file`` argparse 派發器驅動框架——子命令、
舊版旗標與 JSON 檔案執行。

.. toctree::
   :maxdepth: 2
   :caption: CLI

   usage/cli

.. _zh-tw-architecture:

第 3 章 — 架構
==============

分層架構、設計模式（Facade、Registry、Command、Strategy、Template
Method、Singleton、Builder），以及執行器與註冊器的互動方式。

.. toctree::
   :maxdepth: 2
   :caption: 架構

   architecture

.. _zh-tw-local:

第 4 章 — 本地操作
==================

由 ``local/`` 策略模組提供的檔案、目錄、ZIP、tar 與壓縮檔操作；
``safe_join`` 路徑穿越防護；感知 OS 索引的 ``fast_find``；串流式
``file_checksum`` 與 ``find_duplicates``；``sync_dir`` rsync 風格鏡像；
目錄差異比對與文字 patch；JSON / YAML / CSV / JSONL / Parquet 編輯；
MIME 偵測；樣板渲染；垃圾桶送回 / 還原；檔案版本控制；條件式執行；
變數替換；具逾時的 shell 子行程；以及 AES-256-GCM 檔案加密。

.. toctree::
   :maxdepth: 2
   :caption: 本地操作

   usage/local

.. _zh-tw-transfer:

第 5 章 — HTTP 傳輸
===================

經 SSRF 驗證的對外 HTTP 下載，並透過 ``http_download`` 設下大小、
逾時、重試與 ``expected_sha256`` 上限。可透過 ``Range:`` 續傳到
``<target>.part``，並提供即時進度快照。

.. toctree::
   :maxdepth: 2
   :caption: HTTP 傳輸

   usage/transfer

.. _zh-tw-cloud:

第 6 章 — 雲端與 SFTP 後端
==========================

Google Drive、S3、Azure Blob、Dropbox、OneDrive、Box、SFTP、FTP / FTPS、
WebDAV、SMB 與 fsspec——皆由 ``build_default_registry`` 自動註冊。
``copy_between`` 可依 URI 前綴在不同後端間搬資料。

.. toctree::
   :maxdepth: 2
   :caption: 雲端與 SFTP 後端

   usage/cloud

.. _zh-tw-servers:

第 7 章 — 動作伺服器
====================

預設僅綁定 loopback 的 TCP 與 HTTP 伺服器，接受 JSON 動作清單，並可
選擇啟用共享密鑰驗證、``ActionACL`` 白名單、``GET /healthz`` /
``GET /readyz`` 健康檢查、``GET /openapi.json``、``GET /progress``
WebSocket，以及帶型別的 ``HTTPActionClient`` SDK。

.. toctree::
   :maxdepth: 2
   :caption: 動作伺服器

   usage/servers

.. _zh-tw-mcp:

第 8 章 — MCP 伺服器
====================

``MCPServer`` 透過 stdio 上的換行分隔 JSON-RPC 2.0，把註冊器橋接到
任何 Model Context Protocol 主機（Claude Desktop、Claude Code、MCP
CLI）。

.. toctree::
   :maxdepth: 2
   :caption: MCP 伺服器

   usage/mcp

.. _zh-tw-gui:

第 9 章 — 圖形介面
==================

PySide6 桌面控制介面——分頁佈局、日誌面板，以及 ``ActionWorker`` 執行
緒池模型。

.. toctree::
   :maxdepth: 2
   :caption: 圖形介面

   usage/gui

.. _zh-tw-reliability:

第 10 章 — 可靠性
=================

帶上限的指數退避 ``retry_on_transient``、``Quota`` 大小與時間預算、
``CircuitBreaker``、``RateLimiter``、``FileLock`` / ``SQLiteLock``、
持久化的 ``ActionQueue``、SQLite ``AuditLog``、用於週期清單比對的
``IntegrityMonitor``，以及帶型別的 ``FileAutomationException`` 階層。

.. toctree::
   :maxdepth: 2
   :caption: 可靠性

   usage/reliability

.. _zh-tw-events:

第 11 章 — 觸發器與排程
=======================

檔案監控觸發器（``FA_watch_*``）會在檔案系統事件發生時執行動作清單；
cron 風格排程器（``FA_schedule_*``）會依排程定期執行動作清單，並具備
重疊保護。

.. toctree::
   :maxdepth: 2
   :caption: 觸發器與排程

   usage/events

.. _zh-tw-notifications:

第 12 章 — 通知
===============

Slack、Email（SMTP）、Discord、Telegram、Microsoft Teams、PagerDuty
與通用 Webhook 接收端，由 ``NotificationManager`` 組合，具備每接收端
錯誤隔離與滑動視窗去重。

.. toctree::
   :maxdepth: 2
   :caption: 通知

   usage/notifications

.. _zh-tw-config:

第 13 章 — 設定與機敏資訊
=========================

在 ``automation_file.toml`` 裡宣告接收端與預設值；``${env:…}`` /
``${file:…}`` 參照會透過鏈式 ``EnvSecretProvider`` /
``FileSecretProvider`` 解析；``ConfigWatcher`` 會輪詢並熱重載檔案，
無需重啟。

.. toctree::
   :maxdepth: 2
   :caption: 設定與機敏資訊

   usage/config

.. _zh-tw-dag:

第 14 章 — DAG 動作執行器
=========================

以 DAG 形式執行動作清單，可宣告依賴、進行拓撲式平行展開、依分支
略過失敗節點。

.. toctree::
   :maxdepth: 2
   :caption: DAG 動作執行器

   usage/dag

.. _zh-tw-plugins:

第 15 章 — 外掛
===============

第三方套件可透過 ``[project.entry-points."automation_file.actions"]``
註冊自家 ``FA_*`` 動作；``PackageLoader`` 會匯入一個 Python 套件，
並把其頂層成員以 ``<package>_<member>`` 名稱註冊進註冊器。

.. toctree::
   :maxdepth: 2
   :caption: 外掛

   usage/plugins
