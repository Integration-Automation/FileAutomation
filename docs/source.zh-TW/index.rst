automation_file
===============

語言：`English <../html/index.html>`_ | **繁體中文** | `简体中文 <../html-zh-CN/index.html>`_

以自動化為核心的模組化框架，涵蓋本地檔案 / 目錄 / ZIP 操作、經 SSRF 驗證的
HTTP 下載、遠端儲存（Google Drive、S3、Azure Blob、Dropbox、SFTP、FTP、
WebDAV、SMB、fsspec），以及透過內建 TCP / HTTP 伺服器執行的 JSON 動作。
內建 PySide6 圖形介面，把每一項功能以分頁形式呈現；所有公開功能統一從
頂層 ``automation_file`` 外觀模組重新匯出。

功能亮點
--------

**核心原語**

* JSON 動作清單由共用的
  :class:`~automation_file.core.action_executor.ActionExecutor` 執行，支援
  驗證、dry-run、平行、DAG。
* 路徑穿越防護（:func:`~automation_file.local.safe_paths.safe_join`）、
  對外 URL 的 SSRF 驗證、預設僅綁定 loopback 的 TCP / HTTP 伺服器，
  可選共享金鑰驗證與每動作 ACL。
* 可靠性輔助：``retry_on_transient`` 裝飾器、``Quota`` 流量與時間上限、
  串流式 checksum、可續傳 HTTP 下載。

**後端整合**

* 本地檔案 / 目錄 / ZIP / tar 操作。
* HTTP 下載：SSRF 防護、大小 / 逾時上限、重試、續傳、可選 SHA-256 驗證。
* 第一方整合：Google Drive、S3、Azure Blob、Dropbox、SFTP、FTP / FTPS、
  WebDAV、SMB / CIFS、fsspec — 全部自動註冊。
* 跨後端複製，使用 URI 語法（``local://``、``s3://``、``drive://``、
  ``sftp://``、``azure://``、``dropbox://``、``ftp://`` …）。

**事件驅動**

* 檔案監看觸發器 ``FA_watch_*`` — 路徑變動時自動執行動作清單。
* Cron 排程（``FA_schedule_*``）採用純標準函式庫的 5 欄位解析器，
  提供重疊保護，失敗時自動通知。
* 傳輸進度與取消 Token，透過 ``progress_name`` 對外暴露。

**可觀測性與整合**

* 通知 Sink — webhook / Slack / SMTP / Telegram / Discord / Teams /
  PagerDuty，各 Sink 獨立隔離錯誤並採用滑動視窗去重。
* Prometheus 指標匯出器（``start_metrics_server``）、SQLite 稽核日誌、
  檔案完整性監視器。
* HTMX 網頁面板（``start_web_ui``）、MCP 伺服器將註冊表橋接到
  Claude Desktop / MCP CLI，走 JSON-RPC 2.0。
* PySide6 桌面 GUI（``python -m automation_file ui``）。

**供應鏈**

* 設定檔與機敏資訊 — 在 ``automation_file.toml`` 宣告 sink 與預設值；
  ``${env:…}`` / ``${file:…}`` 參考透過 Env / File / Chained provider
  解析，避免把金鑰寫死在檔案裡。
* 進入點外掛 — 第三方套件透過
  ``[project.entry-points."automation_file.actions"]``
  自行註冊 ``FA_*`` 動作。

架構鳥瞰
--------

.. code-block:: text

   使用者 / CLI / JSON batch
          │
          ▼
   ┌─────────────────────────────────────────┐
   │  automation_file（外觀）                │
   │  execute_action、driver_instance、      │
   │  start_autocontrol_socket_server、      │
   │  start_http_action_server、Quota …      │
   └─────────────────────────────────────────┘
          │
          ▼
   ┌──────────────┐     ┌────────────────────┐
   │  core        │────▶│ ActionRegistry     │
   │  executor、  │     │ （FA_* 指令）      │
   │  retry、     │     └────────────────────┘
   │  quota、     │              │
   │  progress    │              ▼
   └──────────────┘     ┌────────────────────┐
                        │ local / remote /   │
                        │ server / triggers /│
                        │ scheduler / ui     │
                        └────────────────────┘

完整的模組樹與設計模式請見 :doc:`architecture`。

安裝
----

.. code-block:: bash

   pip install automation_file

所有後端（S3、Azure Blob、Dropbox、SFTP、PySide6）皆為第一方執行期
依賴，常見使用情境不需要額外 extras。

快速開始
--------

用 CLI 執行 JSON 動作清單：

.. code-block:: bash

   python -m automation_file --execute_file my_actions.json

直接從 Python 呼叫：

.. code-block:: python

   from automation_file import execute_action

   execute_action([
       ["FA_create_dir", {"dir_path": "build"}],
       ["FA_create_file", {"file_path": "build/hello.txt", "content": "hi"}],
       ["FA_zip_dir", {"source": "build", "target": "build.zip"}],
   ])

執行前先驗證動作清單，或以平行方式執行：

.. code-block:: python

   from automation_file import executor

   problems = executor.validate(actions)
   if problems:
       raise SystemExit("\n".join(problems))
   executor.execute_action_parallel(actions, max_workers=4)

啟動 PySide6 圖形介面：

.. code-block:: bash

   python -m automation_file ui

以共享金鑰在 loopback 提供 HTTP 動作伺服器：

.. code-block:: python

   from automation_file import start_http_action_server

   server = start_http_action_server(port=8765, shared_secret="s3kret")

動作清單的格式
--------------

一個動作是三種 list 形式之一，依名稱透過註冊表調度：

.. code-block:: python

   ["FA_create_dir"]                                  # 無參數
   ["FA_create_dir", {"dir_path": "build"}]           # 關鍵字參數
   ["FA_copy_file", ["src.txt", "dst.txt"]]           # 位置參數

JSON 動作清單就是上述 list 的 list。

.. toctree::
   :maxdepth: 2
   :caption: 架構

   architecture

.. toctree::
   :maxdepth: 3
   :caption: 使用指南

   usage/index

.. toctree::
   :maxdepth: 2
   :caption: API 參考

   api/index

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
