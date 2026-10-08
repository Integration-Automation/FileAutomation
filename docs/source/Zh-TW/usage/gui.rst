GUI（PySide6）
==============

桌面視窗依「你想完成什麼事」來安排，而不是依後端：側邊欄有九個工作流程頁面，另有一個
**Advanced** 項目，保留那些直接操作單一動作或單一後端的工具。

每個頁面都只是應用層（:doc:`app_layer`）某一個服務的薄薄一層檢視。視窗本身不帶任何
邏輯，所以它顯示的內容，就是 Web UI（:doc:`servers`）、CLI 與你自己的 Python 程式
看到的內容。

.. code-block:: bash

   pip install "automation_file[gui]"      # PySide6 是 extra，不是基礎相依套件
   python -m automation_file ui
   # 或在儲存庫根目錄開發時：
   python main_ui.py

.. code-block:: python

   from automation_file import launch_ui

   launch_ui()

沒有安裝 PySide6 時，``launch_ui`` 會拋出 ``OptionalDependencyException``，訊息中
帶有上面那行 ``pip install`` 指令。

導覽
--------

.. list-table::
   :header-rows: 1
   :widths: 18 12 70

   * - 項目
     - 快速鍵
     - 用途
   * - Dashboard
     - ``Ctrl+1``
     - 一眼看完健康狀態、執行中與最近的管線執行、完整性漂移、最近的事件與儲存狀態。
   * - Files
     - ``Ctrl+2``
     - 瀏覽儲存 URI、預覽檔案、複製、搬移、刪除、建立目錄。
   * - Storage
     - ``Ctrl+3``
     - 有哪些後端、每個後端能不能用，以及掛載點。
   * - Pipelines
     - ``Ctrl+4``
     - 視覺化管線編輯器：建立、驗證、試跑、測試、執行、續跑。
   * - Scheduler
     - ``Ctrl+5``
     - Cron 工作：列出、新增、移除。
   * - Integrity
     - ``Ctrl+6``
     - 為目錄樹建立基準、驗證與接受；啟動與停止監控器。
   * - Audit
     - ``Ctrl+7``
     - 把稽核軌跡指向資料庫，搜尋並計算其中的紀錄。
   * - Notifications
     - ``Ctrl+8``
     - 已註冊的 sink、路由，以及測試訊息。
   * - Settings
     - ``Ctrl+9``
     - 設定檔、選用的 extra、執行環境。
   * - Advanced
     - ``Ctrl+0``
     - Local、Transfer、Progress、JSON actions、Triggers 與 Servers：舊版視窗的
       分頁。見 `舊分頁去了哪裡`_。

視窗
--------

側邊欄在左，選取的頁面在右。兩者下方是所有頁面共用的 **活動日誌**：每個動作開始時寫
一行、得到結果時再寫一行，並以頁面名稱開頭。最新的一行也會在狀態列顯示幾秒鐘。

每個頁面的底部都有一行 **狀態列文字**，顯示你在這個頁面上最後做的那件事的結果：成功
是綠色，失敗是紅色。

沒有任何操作會卡住視窗。頁面把每一次呼叫交給執行緒池（``QThreadPool`` 上的
``ActionWorker``），結果回來時才顯示。頁面在你開啟它時讀取資料，按下它的 **Refresh**
按鈕時再讀一次。有兩個檢視會自己更新：Dashboard 在可見時每五秒更新一次；被追蹤的管線
執行每秒更新兩次，直到它結束。

視窗與函式庫其餘部分共用行程內的單例。從 Python 註冊的 sink、透過 HTTP 動作伺服器
啟動的管線，或由 JSON 動作啟動的監控器，都會在下一次更新後出現。

Dashboard
---------

**All clear** 或 **Needs attention**，旁邊列出原因。只要最新的五十次執行中有一次
失敗、某個監控器發現漂移或無法驗證，或事件匯流排上有嚴重程度為 ``error`` 以上的近期
事件，儀表板就會要求注意。

* **Health**：已註冊的動作、執行中的執行、排程工作、完整性監控器、通知 sink 與路由、
  路由器是否啟用，以及稽核軌跡是否正在記錄。
* **Pipeline runs**：最新幾次執行的結局、仍在進行的執行，以及最近的結果與錯誤。
* **Integrity drift**：每個具名監控器、它的目標，以及它上次發現了什麼。
* **Storage status**：每個後端以及能不能用。
* **Recent events**：匯流排上最新的二十個事件，新的在前。

**Refresh every 5 s** 開關計時器；**Refresh** 立即讀取。儀表板只讀取：不啟動任何
東西，也不改變任何東西。

Files
-----

輸入儲存 URI 或本機路徑（``s3://reports/2026``、``local:///data``、``C:\data``、
``memory://demo``）後按 **Open**。**Up** 回到上一層，**Browse local…** 選取目錄。
在目錄上按兩下會進入該目錄，在檔案上按兩下會預覽它。

預覽是有上限的：最多顯示 64 KiB，而遠端後端上超過 16 MiB 的檔案根本不會被抓取（狀態
列文字會說明）。二進位內容以前 256 個位元組的十六進位傾印顯示。

各項操作都作用在選取的項目上：

* **Copy** / **Move** 到目標 URI，可以在同一個後端或另一個後端。目標若是既有的目錄，
  檔案會以原本的名稱放進去。目錄會連同底下的一切一起複製；目錄不能搬移（請先複製、
  檢查副本，再刪除原本的）。
* **Create directory** 在目前位置底下建立目錄。
* **Delete selected** 會先詢問。有內容的目錄需要勾選 **Delete a directory with its
  contents**。

每個路徑都經過儲存層（:doc:`storage`）：``..`` 會被拒絕，URI 中的憑證會被拒絕，掛載
的目錄無法被跳出。

Storage
-------

每個後端一列：

.. list-table::
   :header-rows: 1
   :widths: 14 86

   * - Kind
     - 意義
   * - ``scheme``
     - 有工廠函式的 URI scheme：``local``、``memory``、``s3``、``azure``、
       ``gdrive``、``dropbox``、``onedrive``、``sftp``、``ftp``、``ftps``。
   * - ``mount``
     - 掛載在某個 URI 上的後端。它的名稱就是那個 URI。
   * - ``client``
     - 有 ``FA_*`` 動作但沒有儲存 scheme 的共用 client（Box）。

本機與記憶體後端、掛載點，以及 client 已初始化的雲端後端，**Usable** 為 ``yes``。
**Detail** 說明缺了什麼：如何初始化 client；若該 extra 的套件沒有安裝，則是
``pip install`` 指令。

**Mount a local directory** 以你選的 URI 提供某個目錄，並把它限制在那個目錄內
（把 ``sandbox://jobs`` 掛在 ``/srv/jobs``）。來自行程外部的路徑請用這個方式處理。
**Unmount selected** 移除掛載點。選取掛載點、``local`` 或 ``memory`` 時，會顯示該
後端提供哪些能力（目錄、修改時間、ETag……）。

Pipelines
---------

這個頁面是管線定義（:doc:`pipeline`）的編輯器，也是它的執行主控台。

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - 區域
     - 內容
   * - 最上面一列
     - **New**、**Open…**、**Save**、**Save as…**、**Auto layout**，以及檔案名稱
       （有未儲存的變更時會加上 ``(modified)``）。
   * - 第二列
     - 管線名稱、**Max workers**、描述、預設參數（JSON）與排程（cron 運算式，留給
       排程器使用）。
   * - Actions（左）
     - 所有已註冊的動作，附篩選欄。
   * - 畫布（中）
     - 每個任務一個節點、每個相依一條箭頭，上方有 **Connect**、**Disconnect** 與
       **Remove selected**。
   * - Selected task（右）
     - 畫布上選取的任務的表單。
   * - 執行列
     - 執行參數（JSON）以及 **Validate**、**Dry run**、**Test task**、**Run**、
       **Resume**、**Retry**、**Cancel**、**Refresh history**、
       **Follow selected run**。
   * - 底部的分頁
     - **Problems**、**Tasks**、**Log**、**History**。

管線編輯器逐步說明
------------------------------------

1. **開始。** 按 **New** 建立空白定義，或按 **Open…** 開啟 ``.yaml`` / ``.yml`` /
   ``.json`` 檔案。不是有效定義的檔案仍然打得開：形狀正確的部分會顯示出來，
   **Problems** 分頁則列出它哪裡有問題。

2. **命名。** 填入名稱、worker 數量，需要的話再填描述、JSON 物件形式的預設參數與
   排程。

3. **新增任務。** 把 **Actions** 清單中的動作拖到畫布上：任務會出現在你放開的位置。
   在動作上按兩下，或選取它再按 **Add task**，會把它加在最下面的任務之下。篩選欄可以
   縮小清單（輸入 ``storage`` 會顯示 ``FA_storage_*`` 動作）。任務的 ID 由動作名稱
   推導而來；可以在表單中修改。

4. **排列。** 把節點拖到你想要的位置。**Auto layout** 依相依深度把每個任務放進對應的
   欄。位置是編輯器的中繼資料：它存在定義旁邊，絕不會存進定義裡。

5. **連接。** 先點上游任務，再按住 ``Ctrl`` 點相依於它的任務，然後按 **Connect**。
   按鈕會顯示它將採用的方向（``Connect download -> publish``）：你選取這兩個任務的
   順序，就是箭頭的方向。會形成相依循環的箭頭會被拒絕。你也可以在任務表單的
   **Depends on** 中勾選上游任務。

   要移除相依，請點它的箭頭（或選取它兩端的任務），再按 **Disconnect**。
   **Remove selected** 會移除選取的箭頭；沒有選取箭頭時，則移除選取的任務與它們的
   箭頭。

6. **編輯選取的任務。** 表單顯示最後選取的任務：

   .. list-table::
      :header-rows: 1
      :widths: 24 76

      * - 欄位
        - 意義
      * - Task ID
        - 在管線中唯一。改名會保留箭頭，並改寫指向該任務的
          ``${tasks.<id>.result}`` 占位符。
      * - Action
        - 已註冊的動作。它的簽章與摘要顯示在下方。
      * - Arguments
        - 動作的每個參數一列，並附上預設值。值若能解析成 JSON 就是 JSON
          （``12``、``true``、``["a", "b"]``、``"12"``），否則就是文字，所以 URI 或
          ``${params.date}`` 不需要加引號。留空的列不會被傳入，因此套用預設值。
          **Add argument** 為接受 ``**kwargs`` 的動作新增一列。**Edit as JSON**
          把引數顯示成一份 JSON 文件；位置引數（JSON 陣列）只能用這種方式編輯。
      * - Depends on
        - 勾選必須先結束的任務。
      * - Attempts、Back-off、Back-off cap、Retry on
        - 總嘗試次數、第一次退避時間與其上限，以及值得再試一次的例外名稱（留空：
          暫時性的那幾種）。
      * - Timeout
        - 整個任務的秒數；留空表示不限。
      * - Run when
        - ``on_success``、``on_failure`` 或 ``always``。
      * - Idempotency key
        - 帶有 ``${params.<name>}`` 占位符的文字；留空表示沒有。

   在你按下 **Apply changes** 之前，什麼都不會改變。**Revert** 會丟掉你輸入的內容，
   選取另一個任務也一樣。草稿拒絕某個值時，表單會說明原因，並保留你輸入的內容。

7. **驗證。** **Problems** 分頁列出每一項發現，並附上所指項目的路徑
   （``tasks.publish.depends_on[0]: unknown task 'x'``），包含註冊表不認得的動作
   名稱。點某個問題會選取它的任務。**Dry run**、**Test task**、**Run**、**Resume**
   與 **Retry** 都會先驗證，有問題就停下來。

8. **試跑。** 以 JSON 物件輸入執行參數，然後按 **Dry run**。不會執行也不會記錄任何
   東西。**Tasks** 分頁把每個任務顯示為 ``planned`` 並附上層級；無法照計畫執行的任務
   會說明原因（例如這次執行沒有提供某個參數）。

9. **測試單一任務。** 選取一個任務再按 **Test task**。它的動作會真的執行，並套用它的
   重試策略與逾時。它的上游任務則不會執行：每一個都換成不回傳任何東西的替身，所以
   ``${tasks.<id>.result}`` 占位符會得到 ``null``。測試不會記錄到任何 run store，
   也不會發布到共用的事件匯流排。

10. **執行。** **Run** 在背景啟動管線並追蹤它：**Tasks** 分頁顯示每個任務的狀態、
    嘗試次數、耗時與錯誤，**Log** 分頁顯示這次執行的事件，每個節點則換成它的狀態
    顏色（灰色 pending、藍色 running、綠色 succeeded、紅色 failed 或逾時、橘色
    cancelled、黃色 skipped）。**Cancel** 要求這次執行停下來。

11. **續跑或重試。** 失敗之後，先排除原因。**Resume** 接續同一次執行：已成功的任務
    會保留，其餘的重新執行，執行 ID 與參數都不變。**Retry** 以被追蹤的那次執行的
    參數啟動一次新的執行。

12. **回顧。** **History** 分頁列出已記錄的執行，新的在前。在某一筆上按兩下，或選取
    它再按 **Follow selected run**，就能再看到它的任務與事件；之後 **Resume** 與
    **Retry** 會作用在它身上。

13. **儲存。** **Save as…** 把定義寫成 ``.yaml``、``.yml`` 或 ``.json``，並把畫布
    配置寫進旁邊的 ``<file>.layout.json``。定義檔正是 ``Pipeline.from_file`` 與
    ``FA_pipeline_run`` 所接受的檔案。

Scheduler
---------

**Schedule a job** 需要唯一的名稱、五個欄位的 cron 運算式，以及 JSON 形式的動作
清單，按 **Add job** 註冊。勾選核取方塊可以讓新的一次執行在前一次還沒結束時啟動；否則
那次觸發會被略過，並計入 **Skipped**。表格顯示每個工作的執行次數與上次執行時間；
**Remove selected** 與 **Remove all** 移除工作。要讓管線依排程執行，請排程
``FA_pipeline_run`` 並給它定義檔的路徑。

視窗關閉時，這些工作會被移除。

Integrity
---------

輸入 **Target**（要檢查的目錄樹）與 **Baseline**（已核可狀態存放的位置），兩者都是
儲存 URI 或本機路徑。

* **Create baseline** 核可目前的內容。
* **Verify** 把目錄樹與基準比較，並列出每一項變更的種類與路徑。關閉 **Deep** 時，只有
  大小或時間改變的檔案會被雜湊，摘要會註明這是快速檢查。
* **Accept current state** 會先詢問，然後把目前的目錄樹存成新的基準。

在 **Monitors** 底下，給一個名稱與間隔，按 **Start monitor** 就會在執行緒上持續驗證
目標；表格顯示每個監控器上次發現了什麼。從視窗啟動的監控器會在視窗關閉時停止。見
:doc:`integrity`。

Audit
-----

稽核軌跡在取得 store 之前什麼都不記錄。輸入 SQLite 資料庫的路徑（不存在時會建立），
按 **Configure**；之後 **State** 會顯示紀錄寫到哪裡。

填入任何篩選條件，按 **Search**（新的在前，最多 **Limit** 筆）或 **Count**。留空的
篩選條件不會限制搜尋。**Since** 與 **Until** 接受帶時區偏移的 ISO 8601 時間。選取
一筆紀錄可以看到它的全部內容（JSON）。見 :doc:`audit`。

Notifications
-------------

**Sinks** 依名稱、型別與送達位置列出已註冊的 sink。Sink 是在程式中或從設定檔
（Settings）註冊的；這個頁面不會建立它們。選一個 sink（或 **All sinks**），需要的話
填入主旨，按 **Send test message**；狀態列文字會顯示每個 sink 的結果。

**Routes** 列出哪些事件送到哪些 sink。**Add or replace a route** 需要名稱、sink
名稱、事件類型（``pipeline.*``、``task.failed``）、來源、最低嚴重程度與節流數值；清單
以逗號分隔。路由若指名未註冊的 sink 會被拒絕。路由器隨第一條路由啟動，最後一條路由
被移除時停止。見 :doc:`notifications`。

Settings
--------

輸入 ``automation_file.toml`` 的路徑（:doc:`config`）。

* **Preview** 讀取檔案並顯示摘要。不會改變任何東西。
* **Apply** 註冊它的通知 sink 與路由。

**Optional extras** 列出每個 extra、它啟用的功能、是否已安裝，以及未安裝時的
``pip install`` 指令。**Environment** 顯示套件與 Python 版本、平台、日誌檔，以及
最後套用的設定檔。

舊分頁去了哪裡
----------------------------

什麼都沒有移除。**Advanced** 項目保留了舊的分頁，原封不動：

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - 舊分頁
     - 現在
   * - Home
     - **Dashboard**（後端是否就緒在 *Storage status* 底下，也在 **Storage** 頁面）。
   * - Local
     - **Advanced** → *Local*。瀏覽與複製也可以在 **Files** 進行。
   * - Transfer（HTTP、Google Drive、S3、Azure Blob、Dropbox、SFTP、OneDrive、
       Box）
     - **Advanced** → *Transfer*。雲端 client 的憑證就是在這裡提供。
   * - Progress
     - **Advanced** → *Progress*。
   * - JSON actions
     - **Advanced** → *JSON actions*。
   * - Triggers
     - **Advanced** → *Triggers*。
   * - Scheduler
     - **Scheduler**。
   * - Servers
     - **Advanced** → *Servers*。

機敏資訊
----------------

沒有任何頁面會顯示機敏資訊。Sink 以名稱、型別與送達位置描述；設定檔摘要中的密碼與
token 會換成 ``********``，webhook URL 只留下主機；事件、稽核紀錄與執行參數在顯示前
也以同樣方式遮蔽；URL 中的憑證與 bearer token 會從頁面顯示的訊息中移除。

值是否被遮蔽，取決於存放它的 *名稱* 是否表明它是機敏資訊（``password``、``token``、
``api_key``、``authorization``……）。任務的結果則照任務回傳的樣子顯示。所以請給機敏
參數取這樣的名稱，並且不要把機敏資訊放進結果裡。

在沒有顯示器的環境執行
------------------------------------------

Qt 需要顯示器才能開啟視窗。在沒有顯示器的伺服器上：

* 唯讀檢視請用 Web UI（:doc:`servers`）；它由同一個應用層繪製。
* 從 Python 直接使用應用層（:doc:`app_layer`），或透過 CLI 與動作伺服器使用
  ``FA_*`` 動作。視窗做的每一件事，都是對其中之一的呼叫。
* 要建構視窗但不顯示它（測試、CI 中的螢幕截圖），請在匯入 Qt 之前設定
  ``QT_QPA_PLATFORM=offscreen``：

  .. code-block:: python

     import os
     os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

     from PySide6.QtWidgets import QApplication
     from automation_file.app import build_services
     from automation_file.ui.main_window import MainWindow

     app = QApplication([])
     window = MainWindow(build_services())     # 或以 MainWindow() 使用共用的服務
     window.navigate("Pipelines")
     window.close()

``import automation_file`` 與 ``import automation_file.app`` 絕不會匯入 PySide6；
只有 ``automation_file.ui`` 會。

出問題時
----------------

按鈕好像沒有反應
    請看頁面底部的狀態列文字與活動日誌。每一次拒絕與每一次失敗都會在那裡回報，並附上
    原因。

``launch_ui`` 拋出 ``OptionalDependencyException``
    沒有安裝 PySide6：``pip install "automation_file[gui]"``。

視窗打不開：「could not load the Qt platform plugin」
    沒有顯示器。見 `在沒有顯示器的環境執行`_。

雲端後端顯示「not initialised」
    它的共用 client 還沒有憑證。開啟 **Advanced** → *Transfer*，選擇該後端並填寫
    *Credentials*，或執行它的 ``FA_*_later_init`` 動作。

Detail 說某個套件「is not installed」
    安裝該列指名的 extra；**Settings** 列出每個 extra 與它的指令。

**Connect** 被拒絕
    這條箭頭會形成相依循環，或是選取的任務不是剛好兩個。

**Run** 停在「problem(s): see the Problems tab」
    定義無效。每個問題都以所指項目的路徑開頭；點它就會選取該任務。

按了 **Cancel** 之後執行仍是 ``running``
    執行中的動作無法被中斷。尚未開始的任務會立刻被取消；執行中的任務回傳後，這次執行
    才會結束。

**Resume** 被拒絕
    這次執行仍在進行、屬於另一個名稱的管線，或是定義現在需要已儲存的執行所沒有的
    參數。

重新啟動後歷史是空的
    執行紀錄預設保存在記憶體中。在 ``launch_ui()`` 之前呼叫
    ``set_default_run_store(SQLiteRunStore(path))``，就能把它們保存在檔案裡。

**Search** 說 audit is not configured
    請先在同一個頁面為稽核軌跡指定資料庫。

測試訊息失敗
    狀態列文字會顯示每個 sink 的錯誤，URL 只留下主機。Sink 本身的說明見
    :doc:`notifications`。

頁面顯示的是舊資料
    按 **Refresh**。只有 Dashboard 與被追蹤的執行會自己更新。

視窗關閉後還有東西在執行
    關閉視窗會移除排程工作，並停止它啟動的監控器、動作伺服器與觸發器，但不會動管線
    執行：已啟動的執行會跑到結束，行程在那之前不會結束。
