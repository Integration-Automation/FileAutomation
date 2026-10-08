遷移到 1.0
==========

為 0.0.x 寫的程式仍然可以執行：沒有任何 ``FA_*`` 動作、facade 名稱或命令列旗標被移除。
本頁列出少數行為有所不同之處，並針對每一個舊介面，說明對應的新介面以及何時該優先採用。

你必須做的事
------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - 如果你
     - 那麼
   * - 安裝本套件並使用雲端後端、Parquet 或 GUI
     - 請寫明 extra。基本安裝不再附帶各家 SDK：
       ``pip install "automation_file[s3,sftp]"``，或用 ``[all]`` 取得 0.0.x 所安裝的
       全部內容。缺少 SDK 時，會在第一次呼叫時失敗並指出要執行的指令。
   * - 在 Windows 上的排程使用時區
     - 不必做任何事：在 Windows 上 ``tzdata`` 會隨套件一併安裝。
   * - 以 ``sftp://host/path`` 或 ``ftp://host/path`` 呼叫 ``copy_between``
     - 兩個斜線現在代表主機與絕對路徑，而且主機必須是工作階段實際連線的那一台。
       文件記載的單斜線寫法（``sftp:/path``，相對於登入目錄）沒有改變。
   * - 依賴 ``copy_between`` 在後端尚未初始化時拋出 ``RuntimeError``
     - 請改為攔截 ``StorageUnavailableException``（屬於 ``FileAutomationException``）。
   * - 把指向其他主機的完整 URL 當成路徑傳給 ``WebDAVClient``，或依賴它跟隨轉址到
       其他主機
     - 現在會被拒絕。請為那台主機另外建立用戶端。
   * - 讀取或指定排程工作的 ``job.cron``
     - 讀取仍然可行。指定不再會重新排程：請先移除工作，再重新加入。
   * - 依賴排程的動作清單在其中一個動作拋出例外時仍被記為已執行
     - 該次執行現在是 ``failed``，並發布 ``scheduler.error``。清單的其餘部分仍會執行。
   * - 為動作伺服器設定了 ``ActionACL``
     - 請檢查你的允許清單：巢狀在另一個動作引數中的動作（``FA_execute_action``、
       管線定義、排程的清單）現在也會被檢查，因此同樣必須被允許。
   * - 以 ``--allowed-actions`` 限縮了 MCP 伺服器
     - 同樣適用：工具不能再執行伺服器沒有開放的動作。
   * - 比對通知 sink 的錯誤文字
     - 其中的 URL 現在只保留主機部分，路徑中的權杖不會顯示出來。
   * - 匯入 ``HomeTab`` 或 ``SchedulerTab`` 來嵌入它們
     - 它們仍然可以匯入，但視窗不再掛載它們；Dashboard 與 Scheduler 頁面取代了它們。

本次發行的其餘內容都是新增的功能。

舊介面與新介面
--------------

兩欄都受到支援。左欄沒有任何東西被棄用。

.. list-table::
   :header-rows: 1
   :widths: 30 34 36

   * - 舊介面
     - 新介面
     - 何時優先採用新介面
   * - ``FA_s3_upload_file``、``FA_sftp_download_file`` 以及其他各後端專屬的動作
     - ``File`` / ``Storage`` 與 ``FA_storage_*``（:doc:`storage`）
     - 同一份程式要能用在不只一種後端，或者你想要有型別的錯誤、稽核軌跡與事件
   * - ``copy_between`` / ``FA_copy_between``
     - ``File(source).copy_to(target)``、``FA_storage_copy``
     - 你想要的是例外而不是 ``False``，並且想取得結果的描述
   * - ``write_manifest`` / ``verify_manifest``
     - ``IntegrityMonitor``（:doc:`integrity`）
     - 目錄樹不在本機，或者你需要偵測重新命名、中繼資料變更、監看，或經過核可的基準
   * - ``IntegrityMonitor(root, manifest_path, …)`` 與 ``check_once()``
     - ``IntegrityMonitor(target, baseline=…)`` 搭配 ``verify()``、``accept()``
     - 你想要 ``DriftReport`` 而不是摘要字典。由 ``accept()`` 或 ``create_baseline()``
       寫出的基準，``verify_manifest`` 無法再讀取
   * - ``execute_action_dag``
     - ``Pipeline``（:doc:`pipeline`）
     - 你需要重試、逾時、當機後續跑，或執行歷史
   * - ``AuditLog``
     - ``configure_audit`` 與 ``audit_search``（:doc:`audit`）
     - 你希望每個事件與每次儲存操作都被記錄，而不必自己呼叫 ``record``。
       ``SQLiteAuditStore.import_v1()`` 可以複製舊的資料列
   * - ``notification_manager.notify`` 與 ``notify_on_failure``
     - 通知路由（:doc:`notifications`）
     - 不同的事件要送到不同的 sink，並各有自己的去重與限流
   * - 以 cron 運算式呼叫 ``FA_schedule_add``
     - ``FA_schedule_job``、``FA_schedule_pipeline`` 與各種觸發條件（:doc:`scheduler`）
     - 工作要依某個時區執行、由事件觸發、接在另一條管線之後，或要執行管線
   * - MCP 伺服器的 ``FA_*`` 工具
     - 語意化工具（:doc:`mcp`）
     - AI 宿主應該被限制在指定的位置之內，並從唯讀開始
   * - GUI 中各後端專屬的分頁
     - 依工作流程安排的頁面；原本的分頁放在 Advanced 底下（:doc:`gui`）
     - 一律優先，除非你需要某個後端專屬的操作

原本會收到的通知
----------------

有兩個元件過去會直接通知整個行程共用的 ``notification_manager``，現在仍然如此：完整性
監控在偵測到偏移時，以及 ``notify_on_failure`` 在觸發或排程失敗時。一旦你啟動了通知
路由器，這些事件就改由它的路由送達，直接通知隨之停止，因此同一件事不會被通知兩次。
如果你啟動了路由器，請為你原本會被告知的事件（``integrity.violation``、
``scheduler.error``、``system.error``）加上路由；否則它們會被發布，卻送不到任何 sink。

升級正式環境之前
----------------

1. 在全新的環境中安裝新版本以及你需要的 extra。
2. 以 ``-W error::DeprecationWarning`` 執行你的測試。
3. 執行 ``python -m automation_file storage schemes``，並對你使用的每一種後端做一次真實的
   傳輸。
4. 如果動作伺服器設有 ``ActionACL``，請把你的用戶端會送出的每一種請求各送一次。
5. 依照 :doc:`deployment` 安排現在應該保存在檔案中的狀態（稽核軌跡、管線執行紀錄）。
