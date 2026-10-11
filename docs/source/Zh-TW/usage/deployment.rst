部署到正式環境
==============

本頁說明如何讓 FileAutomation 在無人看管的情況下運作：要安裝什麼、它的狀態存放在哪裡、
如何把它當成一個長時間執行的行程啟動、在網路上要開放什麼，以及該監看什麼。其中每個
部分都是一般的 Python；沒有另外需要維運的伺服器產品。

安裝
----

請固定版本，並寫明你用到的 extra。基本套件不含任何雲端 SDK 與 GUI 工具組：

.. code-block:: bash

   python -m venv /opt/fileautomation/venv
   /opt/fileautomation/venv/bin/pip install "automation_file[s3,sftp]==1.0.0"

在任何東西依賴它之前，先確認這份安裝能連到哪些儲存::

   /opt/fileautomation/venv/bin/python -m automation_file storage schemes

缺少 extra 的後端會在第一次呼叫時失敗，並指出安裝它的指令
（``pip install "automation_file[azure]"``），而不是在匯入時失敗。

請用專屬的帳號執行。那個帳號在檔案系統上的權限，加上你交給它的憑證，就是一個動作
所能做到的範圍。

設定與機密
----------

把設定放在 ``automation_file.toml``，並把機密留在檔案之外：

.. code-block:: toml

   [secrets]
   file_root = "/run/secrets"

   [[notify.sinks]]
   type = "slack"
   name = "team-alerts"
   webhook_url = "${env:SLACK_WEBHOOK}"

   [[notify.routes]]
   name = "failures"
   sinks = ["team-alerts"]
   types = ["pipeline.failed", "task.failed", "integrity.violation", "scheduler.error"]
   min_severity = "error"
   dedup_seconds = 600

``${env:NAME}`` 與 ``${file:name}`` 會在載入檔案時解析，無法解析的參考會拋出例外，
而不是變成空字串（:doc:`config`）。各後端的憑證來自環境變數，或來自該帳號讀得到的
檔案，再傳給各用戶端的 ``later_init``。不要把機密寫進動作清單、管線定義或命令列：
這三者都會被記錄、被儲存，或被同一台機器上的其他使用者看到。

單一行程
--------

排程器、完整性監控、通知路由器、稽核軌跡與各個伺服器，都是啟動它們的那個行程中的
執行緒。因此正式環境的部署就是一支腳本：啟動需要的東西，然後等待：

.. code-block:: python

   # /opt/fileautomation/service.py
   import os
   import signal
   import threading

   from automation_file import (
       ActionACL, AutomationConfig, IntegrityMonitor, SQLiteRunStore, configure_audit,
       install_operational_metrics, notification_manager, notification_router,
       s3_instance, start_http_action_server, start_metrics_server,
   )
   from automation_file.pipeline import set_default_run_store

   STATE = "/var/lib/fileautomation"

   # 1. 設定、sink 與通知路由。
   AutomationConfig.load("/etc/fileautomation/automation_file.toml").apply_to(
       notification_manager, notification_router
   )

   # 2. 重新啟動後必須還在的狀態。
   configure_audit(f"{STATE}/audit.sqlite")
   set_default_run_store(SQLiteRunStore(f"{STATE}/runs.sqlite"))

   # 3. 後端。
   s3_instance.later_init(region_name=os.environ["AWS_REGION"])

   # 4. 會自行運作的部分。
   monitor = IntegrityMonitor("s3://reports/2026", baseline=f"{STATE}/reports.baseline.json")
   monitor.start()

   # 5. 對外監聽的部分：只綁定 loopback、需要密鑰，而且只開放用戶端需要的動作。
   install_operational_metrics()
   start_metrics_server(port=9945)
   start_http_action_server(
       port=9944,
       shared_secret=os.environ["FA_SHARED_SECRET"],
       action_acl=ActionACL.build(allowed=["FA_pipeline_run", "FA_storage_copy", "FA_storage_list"]),
   )

   # 6. 持續存活，直到被要求停止。
   stop = threading.Event()
   signal.signal(signal.SIGTERM, lambda *_: stop.set())
   signal.signal(signal.SIGINT, lambda *_: stop.set())
   stop.wait()
   monitor.stop()

請用你的服務管理員來執行它。以 systemd 為例：

.. code-block:: ini

   [Unit]
   Description=FileAutomation
   After=network-online.target

   [Service]
   User=fileautomation
   EnvironmentFile=/etc/fileautomation/environment
   Environment=FILE_AUTOMATION_LOG_FILE=/var/log/fileautomation/FileAutomation.log
   ExecStart=/opt/fileautomation/venv/bin/python /opt/fileautomation/service.py
   Restart=on-failure
   StateDirectory=fileautomation
   LogsDirectory=fileautomation

   [Install]
   WantedBy=multi-user.target

在 Windows 上，同一支腳本可以透過 NSSM 之類的包裝程式當成服務執行，或由工作排程器以
「不論使用者是否登入都執行」的方式啟動。

只需要執行一次的工作（由系統本身的 cron 啟動的夜間管線、CI 步驟中的一次驗證）不需要
這個服務：命令列就能完成，並以你可以據以處理的結束碼結束（:doc:`cli`）::

   python -m automation_file pipeline --audit /var/lib/fileautomation/audit.sqlite \
       run /etc/fileautomation/daily.yaml --store /var/lib/fileautomation/runs.sqlite

磁碟上的狀態
------------

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - 項目
     - 位置與處理方式
   * - 稽核軌跡
     - 你交給 ``configure_audit`` 的 SQLite 檔案。它採用 WAL 模式，行程執行期間請用
       ``sqlite3 audit.sqlite ".backup …"`` 複製，不要用 ``cp``。依你的政策保留足夠久，
       再執行 ``python -m automation_file audit purge --db … --older-than-days 365``。
   * - 管線執行紀錄
     - ``SQLiteRunStore`` 的 SQLite 檔案。當機之後 ``resume`` 讀的就是它；沒有它，行程
       結束時執行紀錄就被遺忘了。
   * - 完整性基準
     - 每棵受監控的目錄樹一個 JSON 檔。請把它放在它所描述的目錄樹之外，最好放在能
       修改該目錄樹的帳號寫不到的地方：誰能改寫基準，誰就能掩蓋變更。
   * - OAuth 權杖
     - 你交給 Google Drive 用戶端的 ``token_path``。只允許服務帳號讀取。
   * - 日誌
     - ``~/.automation_file/logs/FileAutomation.log``，除非 ``FILE_AUTOMATION_LOG_FILE``
       指定了其他路徑。超過 10 MB 的檔案會在行程開啟它時被移到 ``.1``；需要更多輪替
       時請自行處理。
   * - 版本快照、資源回收筒、內容儲存庫
     - 你交給這些功能的目錄。在你清理之前，它們會持續成長。

網路暴露面
----------

每個伺服器都只綁定 loopback 介面，除非你傳入 ``allow_non_loopback=True``；這個預設值
也就是建議做法：動作伺服器會執行任何已註冊的東西，所以連得到它，就等於連得到服務
帳號的 Python 提示字元。

* 同一台機器上的用戶端使用 loopback 位址與共享密鑰。
* 其他地方的用戶端要經過某個負責終結 TLS 並驗證身分的元件（反向代理、SSH 通道、
  service mesh）。伺服器本身使用的是明文 HTTP 與明文 TCP。
* 為每個伺服器設定帶有允許清單的 ``ActionACL``。ACL 也會檢查巢狀在另一個動作引數中
  的動作。它看不到某個動作被指示去執行的檔案內容，所以對必須留在清單之內的用戶端，
  不要開放 ``FA_execute_files``，也不要開放以路徑指定的管線。
* MCP 伺服器透過啟動它的行程的標準串流通訊，不需要任何連接埠；它的允許清單請見
  :doc:`mcp`。

對外連往呼叫端提供的 URL 的請求，會經過 SSRF 防護：只允許 ``http`` 與 ``https``，
而且不允許私有、loopback 或 link-local 位址。有了這道防護，才能安全地接受用戶端提供
的 URL；請不要繞過它。

該監看什麼
----------

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - 訊號
     - 位置
   * - 健康狀態
     - HTTP 動作伺服器的 ``GET /healthz`` 與 ``GET /readyz``。
   * - 指標
     - ``start_metrics_server()`` 提供 Prometheus 文字格式。``automation_file_actions_total``
       及其耗時直方圖一直都有；``install_operational_metrics()`` 會加上事件、通知與
       儲存操作的計數器。
   * - 失敗
     - 事件：``pipeline.failed``、``task.failed``、``integrity.violation``、
       ``storage.error``、``scheduler.error``、``system.error``。把你想被告知的事件
       路由到某個 sink（:doc:`notifications`）。
   * - 歷史
     - 稽核軌跡：``python -m automation_file audit search --db … --status error``，或用
       ``--correlation-id <run id>`` 查看一次執行所做的一切。
   * - 日誌
     - INFO 以上的訊息也會寫到標準錯誤輸出，由服務管理員收集。

承受失敗
--------

* 為管線任務設定 ``RetryPolicy`` 來應付會自行消失的錯誤（連線中斷、被限流），並設定
  ``timeout`` 來應付永遠不回傳的情況。
* 為不可以發生兩次的任務設定 ``idempotency_key``，並把執行紀錄保存在
  ``SQLiteRunStore``：重新啟動之後，``pipeline resume <run id>`` 只會重做沒有成功的
  部分。
* 排程工作在前一次執行尚未結束時不會啟動，除非你允許重疊。
* 完整性監控的修復功能預設是關閉的，除非你設定了它。請先從警示開始，等你信任基準
  之後，再加上隔離或還原。

升級
----

1. 閱讀版本說明。修訂版只做修正；次版本可能會把東西標為棄用；只有主版本才會移除
   （:doc:`api_policy`）。
2. 在新版本進入正式環境之前，先用 ``-W error::DeprecationWarning`` 對它執行你自己的
   測試。
3. 備份那兩個 SQLite 檔案。會改變儲存格式的版本仍然讀得懂前一種格式，並說明如何轉換。
4. 安裝到舊環境旁邊的一個全新虛擬環境，再把服務切換過去；這樣要回復時，再切換一次
   即可。

檢查清單
--------

* 服務以專屬帳號執行，而且只有那個帳號能讀取機密與權杖檔案。
* 版本與 extra 都已固定。
* 稽核軌跡與執行紀錄儲存庫都是位於有備份的磁碟上的檔案。
* 每個伺服器都綁定在 loopback 介面、設有共享密鑰與允許清單；任何遠端連線都經過 TLS。
* 失敗會傳達給人：至少有一條針對錯誤的通知路由。
* 基準存放在受監控目錄樹的寫入者無法修改的位置。
* 日誌與持續成長的目錄都有你自己決定的保留期限。
