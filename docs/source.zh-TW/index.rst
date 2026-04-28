automation_file
===============

語言：`English <../html/index.html>`_ | **繁體中文** | `简体中文 <../html-zh-CN/index.html>`_

以 JSON 動作清單為核心的模組化檔案自動化框架。

``automation_file`` 把本地檔案 / 目錄 / ZIP 操作、經 SSRF 驗證的 HTTP 下載、
遠端儲存後端（Google Drive、S3、Azure Blob、Dropbox、OneDrive、Box、SFTP、
FTP、WebDAV、SMB、fsspec）以及透過內建 TCP / HTTP / MCP 伺服器執行的 JSON
動作清單統合為單一框架——全部透過共用的 ``ActionRegistry`` 調度，並由
PySide6 桌面圖形介面對外呈現。

文件依語言與內容類型拆分。每個語言手冊以章節組織：入門、CLI、架構、
本地操作、HTTP 傳輸、雲端與 SFTP 後端、動作伺服器、MCP 伺服器、圖形介面、
可靠性、觸發器與排程、通知、設定、DAG、外掛。API 參考則是自動生成的
Python 參考資料。

未來規劃
--------

專案追蹤：https://github.com/Integration-Automation/FileAutomation/issues

.. toctree::
   :maxdepth: 2
   :caption: 手冊

   第 1 章 — 入門 <usage/quickstart>
   第 2 章 — CLI <usage/cli>
   第 3 章 — 架構 <architecture>
   第 4 章 — 本地操作 <usage/local>
   第 5 章 — HTTP 傳輸 <usage/transfer>
   第 6 章 — 雲端與 SFTP 後端 <usage/cloud>
   第 7 章 — 動作伺服器 <usage/servers>
   第 8 章 — MCP 伺服器 <usage/mcp>
   第 9 章 — 圖形介面 <usage/gui>
   第 10 章 — 可靠性 <usage/reliability>
   第 11 章 — 觸發器與排程 <usage/events>
   第 12 章 — 通知 <usage/notifications>
   第 13 章 — 設定與機敏資訊 <usage/config>
   第 14 章 — DAG 動作執行器 <usage/dag>
   第 15 章 — 外掛 <usage/plugins>

.. toctree::
   :maxdepth: 2
   :caption: API 參考

   第 A 章 — 核心 <api/core>
   第 B 章 — 本地操作 <api/local>
   第 C 章 — 遠端操作 <api/remote>
   第 D 章 — 伺服器 <api/server>
   第 E 章 — 客戶端 SDK <api/client>
   第 F 章 — 觸發器 <api/trigger>
   第 G 章 — 排程器 <api/scheduler>
   第 H 章 — 通知 <api/notify>
   第 I 章 — 進度與取消 <api/progress>
   第 J 章 — 專案腳手架 <api/project>
   第 K 章 — 圖形介面 <api/ui>
   第 L 章 — 工具 <api/utils>

索引
----

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
