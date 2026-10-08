MCP 伺服器
====================

``automation_file`` 內建一個 Model Context Protocol（MCP）伺服器，讓 **Claude Desktop**
或 **Claude Code** 這類 AI 用戶端可以透過它處理檔案。傳輸方式是 stdio：每行一則
JSON-RPC 2.0 訊息。

伺服器提供兩組工具：

* **語意工具**：十四個名稱穩定、以工作為單位的工具（``file_read``、``file_copy``、
  ``pipeline_run`` ……），操作對象是 :doc:`儲存 URI <storage>`，並受一份權限政策
  約束。這是為 AI 用戶端設計的介面；
* **橋接**：每個已註冊的 ``FA_*`` 動作各自成為一個工具，與先前的版本相同。為了相容，
  它預設開啟，而且 **不受** 政策約束。

語意工具的預設值是安全的：不允許任何位置、不能更動任何東西，每個回應的大小也都有
上限。

最小設定
----------------

給伺服器一個可以讀取的目錄。寫在 ``claude_desktop_config.json``\ （Claude Desktop）或
``.mcp.json``\ （Claude Code）裡：

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "python",
         "args": ["-m", "automation_file", "mcp", "--root", "/srv/reports", "--no-bridge"]
       }
     }
   }

用戶端現在會看到十四個語意工具。它可以列出、讀取、搜尋 ``/srv/reports`` 底下的
內容並計算校驗碼，除此之外什麼都不能做：寫入會被拒絕，該目錄以外的每個路徑也一樣。
在 Windows 上路徑要寫成 ``"C:\\data\\reports"``。如果 ``PATH`` 上的 ``python`` 不是
安裝本套件的那一個，請改用該環境的直譯器
（``"command": "C:\\envs\\fa\\Scripts\\python.exe"``）。

使用 Claude Code 時，同一個伺服器可以從 shell 加入::

   claude mcp add automation_file -- python -m automation_file mcp --root /srv/reports --no-bridge

正式環境設定
------------------------

列出每一個位置、只開啟工作需要的權限、把管線的定義存在磁碟上，並且關閉橋接：

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "/opt/fa/bin/python",
         "args": [
           "-m", "automation_file", "mcp",
           "--root", "/srv/reports/inbox",
           "--root", "/srv/reports/outbox",
           "--allow-write",
           "--max-read-bytes", "65536",
           "--max-results", "100",
           "--pipeline-dir", "/var/lib/automation_file/pipelines",
           "--tools", "file_read,file_write,file_copy,file_search,file_checksum,file_verify,storage_list,storage_copy",
           "--no-bridge"
         ]
       }
     }
   }

遠端後端必須先初始化用戶端，稽核軌跡與通知路由也要在伺服器啟動之前設定好。這需要
幾行 Python，所以請用一支啟動腳本來啟動伺服器，再把宿主的 ``command`` 指向它：

.. code-block:: python

   # /opt/fa/mcp_server.py
   import os

   from automation_file import (
       MCPServer, Route, Severity, SlackSink, configure_audit,
       notification_manager, notification_router, s3_instance, sftp_instance,
   )
   from automation_file.server.mcp_policy import MCPPolicy

   s3_instance.later_init(region_name="eu-west-1")              # 憑證：AWS 的預設來源鏈
   sftp_instance.later_init(host="sftp.example.com", username="reports",
                            key_filename="/etc/fa/id_ed25519",
                            known_hosts="/etc/fa/known_hosts")
   configure_audit("/var/lib/automation_file/audit.sqlite")     # audit_search 讀的就是這裡
   notification_manager.register(SlackSink(os.environ["SLACK_WEBHOOK"], name="ops"))
   notification_router.add_route(Route(
       "mcp-failures", sinks=("ops",),
       types=("mcp.tool.failed", "pipeline.failed", "storage.error"),
       min_severity=Severity.WARNING,
   ))
   notification_router.start()

   policy = MCPPolicy(
       roots=["s3://reports-export/daily", "sftp://sftp.example.com/inbound/reports"],
       allow_write=True,
       allow_delete=True,                # file_move 會刪除來源
       max_read_bytes=64 * 1024,
       pipeline_dir="/var/lib/automation_file/pipelines",
   )
   MCPServer(policy=policy, bridge=False).serve_stdio()

.. code-block:: json

   {"mcpServers": {"automation_file": {"command": "/opt/fa/bin/python",
                                       "args": ["/opt/fa/mcp_server.py"]}}}

``stdout`` 上除了協定之外什麼都不能寫：函式庫的日誌寫到 ``stderr`` 與它的日誌檔，
啟動腳本也不可以 ``print``。

語意工具
----------------

每個位置都是一個儲存 URI，``<scheme>://<authority>/<path>``
（``local:///srv/reports/a.csv``、``s3://bucket/2026/a.csv``、
``sftp://host/inbox/a.csv``），或是本機的絕對路徑。「需要」一欄列出：除了要有一個
涵蓋這次呼叫所有位置的根位置之外，政策還必須允許什麼。

.. list-table::
   :header-rows: 1
   :widths: 14 30 36 20

   * - 工具
     - 引數
     - 結果
     - 需要
   * - ``file_read``
     - ``uri``、``offset=0``、``max_bytes``、``encoding="utf-8"``\ （文字編碼，或
       ``base64``）
     - ``content``、``encoding``、``size``、``offset``、``bytes``、
       ``truncated``、``next_offset``
     - —
   * - ``file_write``
     - ``uri``、``content``、``encoding="utf-8"``、``overwrite=false``、
       ``dry_run=false``
     - ``size``、``sha256``、``overwrites``、``replaced_size``、``written``
     - 寫入；要取代檔案時還需要覆寫
   * - ``file_copy``
     - ``source``、``target``、``overwrite=false``、``verify=false``、
       ``dry_run=false``
     - ``source``、``target``、``size``、``overwrites``、``replaced_size``、
       ``deletes_source``、``done``；使用 ``verify`` 時另有 ``sha256``、
       ``verified``
     - 寫入；要取代檔案時還需要覆寫
   * - ``file_move``
     - 與 ``file_copy`` 相同
     - 與 ``file_copy`` 相同；``deletes_source`` 為 true
     - 寫入與刪除；要取代檔案時還需要覆寫
   * - ``file_search``
     - ``uri``、``pattern="*"``、``content``、``recursive=true``、
       ``case_sensitive=false``、``max_results``
     - ``matches``\ （``uri``、``path``、``name``、``size``、``modified_at``；
       內容搜尋另有 ``line``、``snippet``、``matching_lines``）、``count``、
       ``candidates``、``truncated``；內容搜尋另有 ``searched_files``、
       ``searched_bytes``、``skipped``、``complete``
     - —
   * - ``file_checksum``
     - ``uri``、``algorithm="sha256"``
     - ``algorithm``、``value``、``size``
     - —
   * - ``file_verify``
     - ``uri``、``expected``\ （十六進位，或 ``sha256:<hex>``）、
       ``algorithm="sha256"``
     - ``match``、``expected``、``actual``、``algorithm``
     - —
   * - ``storage_list``
     - ``uri``、``recursive=false``、``max_results``
     - ``entries``\ （``uri``、``path``、``name``、``is_dir``、``size``、
       ``modified_at``）、``count``、``total``、``truncated``
     - —
   * - ``storage_copy``
     - ``source``、``target``、``overwrite=false``、``verify=false``、
       ``dry_run=false``
     - 檔案：``kind="file"`` 加上 ``file_copy`` 的結果。目錄：``kind="tree"``、
       ``planned``\ （``copy``、``overwrite``、``skip``、``bytes``）、``paths``、
       ``existing``、``truncated``、``done``，複製之後另有 ``copied``、
       ``skipped``、``failed``、``errors``、``ok``
     - 寫入；要取代檔案時還需要覆寫
   * - ``pipeline_create``
     - ``name``、``definition``、``overwrite=false``、``dry_run=false``
     - ``name``、``location``、``persistent``、``tasks``、``actions``、
       ``overwrites``、``stored``
     - 寫入；要取代定義時還需要覆寫
   * - ``pipeline_run``
     - ``name``、``params``、``dry_run=false``、``background=false``
     - ``run_id``、``status``、``ok``、``run``\ （這次執行與它的每個任務）
     - 寫入；每個任務需要它的動作所需要的權限
   * - ``pipeline_status``
     - ``run_id``，或 ``name`` 與 ``limit=5``
     - ``runs``、``count``
     - 不需要根位置
   * - ``integrity_status``
     - ``name``
     - ``monitors``\ （``name``、``target``、``running``、``last_run``、
       ``last_error``、``last_report``）、``count``
     - 不需要根位置
   * - ``audit_search``
     - ``actor``、``source``、``pipeline``、``task``、``action``、``backend``、
       ``status``、``correlation_id``、``resource_prefix``、``text``、``since``、
       ``until``、``limit=50``、``offset=0``
     - ``records``、``count``、``total``、``limit``、``offset``、``truncated``
     - 不需要根位置；需要已設定的稽核軌跡

個別工具的說明：

``file_read``
    每次呼叫最多回傳 ``--max-read-bytes`` 個位元組。``truncated`` 為 true 時，把
    ``offset`` 設成 ``next_offset`` 再呼叫一次；字元絕不會被切成兩半。內容不是所選
    編碼的文字時會回報錯誤，並要求改用 ``encoding="base64"``。

``file_copy``、``file_move`` 與 ``verify``
    ``verify=true`` 時會比對來源與副本的 SHA-256。此時搬移會先複製、再比對，只有在
    兩個摘要相符時才刪除來源；不相符時來源保留，呼叫以 ``checksum_mismatch`` 失敗。

``file_verify``
    不相符是一個結果（``match`` 為 false），不是錯誤。

``file_search``
    ``pattern`` 是比對檔名的 shell 樣式（``*.csv``）；樣式裡有 ``/`` 時，比對的是
    ``uri`` 底下的相對路徑（``2026/*/*.csv``）。``content`` 是單純的子字串，不是正規
    表示式。一次內容搜尋最多讀取 ``--max-search-bytes`` 個位元組。超過剩餘額度的
    檔案不會被開啟，而是列在 ``skipped`` 裡；二進位檔與讀不到的檔案也一樣。只有在
    每個候選檔案都搜尋過時，``complete`` 才是 true。

``storage_copy``
    像 ``file_copy`` 一樣複製一個檔案，或複製某個目錄底下的所有檔案。對目錄而言，
    除非 ``overwrite`` 為 true，否則目標已有的檔案會被略過。失敗的檔案記在
    ``errors`` 裡，其他檔案照樣複製；這時呼叫是一個錯誤，但結果裡仍有各項數量。

``pipeline_run``
    在這次請求裡執行，並回傳已結束的執行。``background=true`` 時立刻回傳
    ``status="running"``；請用 ``run_id`` 輪詢 ``pipeline_status``。失敗的執行是
    一個錯誤，但結果裡仍帶有這次執行。

結果與錯誤
~~~~~~~~~~~~~~~~~~~~

語意工具以一份 JSON 文件作為結果的文字回應。其中一定有 ``tool`` 與
``correlation_id``。呼叫被拒絕或失敗時，``isError`` 為 true，文件裡會有 ``error``：

.. code-block:: json

   {
     "tool": "file_write",
     "correlation_id": "27acff55529c4317b74de6ea98759f42",
     "error": {
       "type": "permission_denied",
       "code": "read_only",
       "message": "file_write changes something and this server is read-only: start it with --allow-write, or pass MCPPolicy(allow_write=True)"
     }
   }

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - ``error.type``
     - 意義
   * - ``permission_denied``
     - 政策拒絕了這次呼叫。``code`` 指出是哪一條規則：``no_root``、
       ``outside_root``、``read_only``、``overwrite_not_allowed``、
       ``delete_not_allowed``、``tool_disabled``、``action_not_allowed`` 或
       ``limit_exceeded``。
   * - ``invalid_arguments``
     - 引數缺少、未知、型別錯誤或超出範圍。每個問題都會列出。
   * - ``invalid_uri``
     - 位置不是儲存 URI，或它的路徑含有 ``..`` 區段。
   * - ``not_found``、``already_exists``
     - 沒有這個檔案、管線、執行或監控器；或目標已存在而沒有給 ``overwrite``。
   * - ``checksum_mismatch``
     - ``verify`` 發現兩邊的摘要不同。
   * - ``invalid_definition``
     - 管線定義有誤；``problems`` 列出每一項發現與它的路徑。
   * - ``not_configured``
     - 伺服器沒有保存稽核軌跡。
   * - ``failed``
     - 函式庫回報的其他錯誤；``exception`` 是例外類別的名稱。
   * - ``internal_error``
     - 非預期的例外。請回報。

權限模型
----------------

:class:`~automation_file.server.mcp_policy.MCPPolicy` 在伺服器啟動時建立，之後無法
更改。它的文字描述會放在握手回應的 ``instructions`` 裡送給用戶端，所以模型在第一次
呼叫之前就知道界線在哪裡。

.. list-table::
   :header-rows: 1
   :widths: 24 24 14 38

   * - 欄位
     - 旗標
     - 預設值
     - 意義
   * - ``roots``
     - ``--root``\ （可重複）
     - 無
     - 工具可以作業的位置：儲存 URI 或本機目錄。一個都沒有時，每個會碰到儲存的
       工具都會拒絕，並說明如何加入根位置。
   * - ``allow_write``
     - ``--allow-write``
     - 關閉
     - 沒有它，``file_write``、``file_copy``、``file_move``、``storage_copy``、
       ``pipeline_create`` 與 ``pipeline_run`` 都會被拒絕，試跑也一樣。
   * - ``allow_overwrite``
     - ``--allow-overwrite``
     - 關閉
     - 取代既有的檔案或定義。呼叫本身也必須提出要求（``overwrite=true``）。需要
       ``allow_write``。
   * - ``allow_delete``
     - ``--allow-delete``
     - 關閉
     - 刪除。``file_move`` 會刪除來源，所以需要它。需要 ``allow_write``。
   * - ``max_read_bytes``
     - ``--max-read-bytes``
     - 262144
     - ``file_read`` 一次呼叫最多回傳的位元組數，也是管線工具回傳的任務結果的
       大小上限。
   * - ``max_write_bytes``
     - ``--max-write-bytes``
     - 1048576
     - ``file_write`` 接受的內容大小上限，以及 ``pipeline_create`` 儲存的定義大小
       上限。
   * - ``max_results``
     - ``--max-results``
     - 200
     - 列表、搜尋、目錄複製計畫或 ``audit_search`` 最多回傳的項目數。呼叫裡較大的
       ``max_results`` 或 ``limit`` 會被降到這個值。
   * - ``max_search_bytes``
     - ``--max-search-bytes``
     - 8388608
     - 一次內容搜尋最多讀取的位元組數。
   * - ``pipeline_dir``
     - ``--pipeline-dir``
     - 記憶體
     - ``pipeline_create`` 存放定義的地方：儲存 URI 或本機目錄，每條管線一個
       ``<name>.json``。沒有設定時定義保存在記憶體裡，伺服器停止就消失。
   * - ``pipeline_actions``
     - ``--pipeline-actions``
     - 依權限而定
     - 透過 MCP 建立或執行的管線可以呼叫的動作。見 `管線`_。
   * - ``tools``
     - ``--tools``
     - 全部十四個
     - 要提供的語意工具。沒有列入的工具不會出現在清單裡，呼叫它也會被拒絕。
       ``--tools none`` 一個都不提供。
   * - ``actor``
     - （僅限 Python）
     - ``mcp``
     - 事件與稽核紀錄裡每次呼叫的 actor。握手時用戶端回報的名稱會接在後面：
       ``mcp:claude-desktop``。

位置
~~~~~~~~

呼叫裡提到的每個位置都在某個根位置之內（或就是根位置本身）時，呼叫才被允許。

* **本機根位置** 由儲存層自己把關。該位置由一個限制在根位置內的 ``LocalStorage``
  提供服務，所以每個操作都會通過 ``safe_join``：指向根位置之外的符號連結（或
  Windows 的 junction），以及偷渡到根位置底下的絕對路徑，都會以 ``outside_root``
  被拒絕。留在根位置之內的連結則會被跟隨。在 Windows 上比對不分大小寫，也接受
  反斜線；名稱是裝置（``CON``、``NUL``、``COM1``）或替代資料流
  （``a.txt:stream``）的路徑同樣會被拒絕。
* **其他後端** 以 scheme、authority 與完整的路徑區段比對。``s3://bucket/team`` 允許
  ``s3://bucket/team/2026/a.csv``，並拒絕 ``s3://bucket/team-b/a.csv`` 與
  ``s3://other/team/a.csv``。authority 必須完全相同，包含大小寫。根位置只是路徑的
  前綴，僅此而已：伺服器上既有的連結（例如 SFTP 的符號連結）會由伺服器跟隨。請給
  後端一個無法離開該目錄樹的帳號。
* 含有 ``..`` 區段的路徑根本不是儲存 URI（``invalid_uri``）。
* 以 ``Storage.mount`` 掛載的後端要透過它的掛載 URI 來指定；位於已掛載的
  ``LocalStorage`` 之下的根位置，會被限制在該根位置之內。

位置的寫法要和根位置的寫法一致。以 ``/srv/reports`` 給定的根位置不會符合
``local:///mnt/disk2/reports``，即使兩者是同一個目錄。

管線
~~~~~~~~

``pipeline_create`` 儲存一份定義（:doc:`pipeline`，``schema_version: 1``），
``pipeline_run`` 則執行它。兩者都需要 ``allow_write``。

定義可以呼叫什麼，在建立時檢查一次，執行時再檢查一次，因為這段期間檔案可能被別的
東西改寫。預設情況下，管線可以呼叫權限所涵蓋的 ``FA_storage_*`` 動作：

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - 權限
     - 動作
   * - 一律可用
     - ``FA_storage_exists``、``FA_storage_stat``、``FA_storage_list``、
       ``FA_storage_checksum``、``FA_storage_verify``、``FA_storage_read_text``、
       ``FA_storage_schemes``
   * - ``allow_write``
     - ``FA_storage_mkdir``、``FA_storage_write_text``、``FA_storage_copy``、
       ``FA_storage_copy_tree``
   * - ``allow_overwrite``
     - ``FA_storage_sync``\ （它會取代有變動的檔案）
   * - ``allow_delete``
     - ``FA_storage_move``、``FA_storage_delete``

在這樣的管線裡，這些名稱執行的不是原本的動作，而是受防護的版本：它們在任務執行的
當下檢查根位置與權限，也就是在 ``${params.<name>}`` 與 ``${tasks.<id>.result}``
填入之後，所以參數無法把任務帶到根位置之外。它們的行為與原本的動作相同，差別如下：

* ``overwrite`` 的預設值是政策所允許的，而不是 ``true``；在不允許覆寫的地方，明確
  寫出的 ``overwrite: true`` 會被拒絕；
* ``FA_storage_verify`` 的 ``expected`` 也接受 ``FA_storage_checksum`` 的結果，所以
  ``"${tasks.<id>.result}"`` 可以用來比對兩個檔案；
* ``FA_storage_read_text`` 與 ``FA_storage_write_text`` 遵守讀取與寫入的上限；
* ``FA_storage_sync`` 需要 ``allow_overwrite``，``delete: true`` 還需要
  ``allow_delete``；
* ``FA_storage_delete`` 絕不會移除根位置本身；
* 沒有 ``FA_storage_upload`` 與 ``FA_storage_download``：它們接受的是檔案系統路徑，
  不是儲存 URI。請改為複製到 ``local://`` URI，或從它複製出來。

``--pipeline-actions a,b,c`` 會取代預設的清單。上面的 ``FA_storage_*`` 動作被列入時
仍然受到防護。**其他動作則照原樣執行，不受根位置與權限約束**：只列出你本來就願意
讓用戶端直接呼叫的動作，而且絕不要列出會執行其他動作的動作
（``FA_execute_action``、``FA_pipeline_run``、``FA_run_shell``）。每個名稱都必須是
伺服器有提供的動作，否則伺服器不會啟動。出現在另一個動作的引數或參數裡的動作會被
拒絕，除非清單裡有它；儲存動作在那裡則一律被拒絕，因為巢狀執行時它不受防護。

透過 MCP 建立的定義不能帶有 ``schedule``：管線何時自行執行，由維運伺服器的人決定。
定義的 ``name`` 就是它儲存時使用的名稱；省略時會自動填入。

執行紀錄存在預設的執行紀錄儲存裡，``pipeline_status`` 與 ``FA_pipeline_status`` 都
從那裡查找。除非啟動腳本呼叫 ``set_default_run_store(SQLiteRunStore(path))``，否則
它只存在記憶體裡。

試跑
--------

每個會更動東西的工具都接受 ``dry_run``。這時它會做完真正呼叫要做的每一項檢查，
不更動任何東西，並回傳計畫：

.. code-block:: json

   {
     "tool": "file_move",
     "correlation_id": "bb62a807d4f64bf3b666d00d3b4f410f",
     "source": "s3://reports-export/daily/2026-10-07.csv",
     "target": "sftp://sftp.example.com/inbound/reports/2026-10-07.csv",
     "size": 48211,
     "overwrites": false,
     "replaced_size": null,
     "deletes_source": true,
     "dry_run": true,
     "done": false
   }

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - 工具
     - 試跑回報的內容
   * - ``file_write``
     - 內容的大小與 SHA-256、是否會取代某個檔案，以及該檔案的大小。
   * - ``file_copy``、``file_move``
     - 來源、目標、大小、目標是否會被取代、來源是否會被刪除。
   * - ``storage_copy``
     - 對目錄：會複製、取代與略過多少檔案與位元組，以及路徑（受 ``max_results``
       限制）。
   * - ``pipeline_create``
     - 定義是否有效且被允許、它的任務與動作，以及是否會取代已儲存的定義。
   * - ``pipeline_run``
     - 依相依順序排列、狀態為 ``planned`` 的任務；若任務指定了未知的動作，或用到
       這次執行沒有給的參數，會在該任務上附 ``error``。不會執行也不會記錄任何
       東西。

試跑需要的權限與真正的呼叫相同：唯讀的伺服器同樣會拒絕它，所以伺服器不會做的事，
也不會給出計畫。

可追溯性
----------------

每次語意呼叫都在 ``correlation_scope()`` 與 ``actor_scope(...)`` 之內執行。結果帶有
``correlation_id``，這次呼叫所做的一切也都帶有它：儲存操作，以及每次呼叫一則的
事件：``mcp.tool.completed`` 或 ``mcp.tool.failed``\ （source 為 ``mcp``）。

.. list-table::
   :header-rows: 1
   :widths: 26 14 60

   * - 結果
     - 嚴重度
     - 事件
   * - 完成
     - info
     - ``mcp.tool.completed``，``status="ok"``
   * - 被政策拒絕
     - warning
     - ``mcp.tool.failed``，``status="refused"``，``code`` 指出規則
   * - 請求本身有誤：檔案不存在、目標已存在、引數錯誤、定義無效
     - info
     - ``mcp.tool.failed``，``status="error"``，``code`` 就是 ``error.type``
   * - 失敗：後端錯誤、目錄複製中有檔案失敗、管線執行失敗
     - warning
     - ``mcp.tool.failed``，``status="error"``。失敗的後端另外以
       ``storage.error`` 回報，失敗的執行則以 ``pipeline.failed`` 回報。
   * - ``verify`` 發現摘要不同
     - error
     - ``mcp.tool.failed``，``status="error"``，``code="checksum_mismatch"``
   * - 非預期的例外
     - error
     - ``mcp.tool.failed``，``status="error"``，``code="internal_error"``

因此，一條針對 ``mcp.tool.failed``、``min_severity=Severity.WARNING`` 的通知路由會
收到拒絕與真正的失敗，而不會收到「模型要了一個不存在的檔案」這種事。

事件的 payload 記有工具名稱（``action``）、這次呼叫涉及的儲存 URI（``resource``、
``source_uri``）、``duration_ms``，管線工具另有 ``pipeline`` 與 ``run_id``。它絕不
包含內容、參數或摘要。被拒絕的呼叫也會以 warning 寫進日誌，內容是工具、規則與關聯
ID，不含任何引數值。

設定了 :doc:`稽核軌跡 <audit>` 之後，一次搜尋就能看到某次呼叫做了什麼：

.. code-block:: python

   audit_search(correlation_id="7dc51e94bd3b494eae8e6b6f3f3b150b")
   # [{"source": "mcp", "action": "mcp.tool.completed", "actor": "mcp:claude-desktop", ...},
   #  {"source": "storage", "action": "copy", "resource": "sftp://...", "status": "ok", ...}]

管線的一次執行有它自己的關聯 ID，也就是它的 ``run_id``。``pipeline_run`` 那次呼叫的
事件裡記有這個 ``run_id``，兩者由此連結起來。

範例：從 S3 到 SFTP，經過驗證與稽核，失敗時發出警示
------------------------------------------------------------------------

工作內容：*把昨天的 CSV 從 S3 搬到公司的 SFTP 伺服器，驗證它的 SHA-256，稽核這次
傳輸，失敗時通知 Slack*。`正式環境設定`_ 的啟動腳本已經準備好所需的一切：兩個後端都
已初始化、兩個根位置、允許寫入與刪除、一份稽核軌跡，以及一條把失敗送到 Slack 的
路由。接著用戶端進行這些呼叫：

.. code-block:: text

   1. storage_list   {"uri": "s3://reports-export/daily"}
        -> 項目清單；用戶端選出 2026-10-07.csv

   2. file_move      {"source": "s3://reports-export/daily/2026-10-07.csv",
                      "target": "sftp://sftp.example.com/inbound/reports/2026-10-07.csv",
                      "verify": true, "dry_run": true}
        -> 計畫：size、overwrites=false、deletes_source=true

   3. file_move      同樣的引數，去掉 dry_run
        -> done=true、verified=true、sha256="9f86d0..."、correlation_id="7dc5..."
           兩個 SHA-256 摘要相符之後，來源才被刪除。

   4. file_verify    {"uri": "sftp://sftp.example.com/inbound/reports/2026-10-07.csv",
                      "expected": "sha256:9f86d0..."}
        -> match=true（獨立的檢查，留作紀錄）

   5. audit_search   {"correlation_id": "7dc5..."}
        -> 第 3 步的 mcp.tool.completed 紀錄，以及儲存紀錄（copy、delete），
           附有資源、耗時與狀態

**失敗時。** 第 3 步失敗時，用戶端會收到 ``error``，來源仍然在 S3 裡。伺服器會發布
``mcp.tool.failed``\ （摘要不同時是 error，傳輸失敗時是 warning），後端失敗時另外
發布 ``storage.error``，啟動腳本設定的路由再把它們送到 Slack。通知不是由任何工具
送出的，所以用戶端無法略過它。

同一件工作也可以寫成管線，建立一次、每天執行：

.. code-block:: text

   pipeline_create {
     "name": "export-daily",
     "definition": {
       "schema_version": 1,
       "description": "Move the daily export from S3 to SFTP and verify it",
       "tasks": {
         "digest": {"action": ["FA_storage_checksum",
                               {"uri": "s3://reports-export/daily/${params.date}.csv"}]},
         "copy":   {"action": ["FA_storage_copy",
                               {"source": "s3://reports-export/daily/${params.date}.csv",
                                "target": "sftp://sftp.example.com/inbound/reports/${params.date}.csv"}],
                    "depends_on": ["digest"],
                    "retry": {"max_attempts": 3, "backoff": 5}, "timeout": 600},
         "verify": {"action": ["FA_storage_verify",
                               {"uri": "sftp://sftp.example.com/inbound/reports/${params.date}.csv",
                                "expected": "${tasks.digest.result}", "strict": true}],
                    "depends_on": ["copy"]},
         "remove": {"action": ["FA_storage_delete",
                               {"uri": "s3://reports-export/daily/${params.date}.csv"}],
                    "depends_on": ["verify"]}
       }
     }
   }
   pipeline_run    {"name": "export-daily", "params": {"date": "2026-10-07"}, "dry_run": true}
   pipeline_run    {"name": "export-daily", "params": {"date": "2026-10-07"}}
   audit_search    {"correlation_id": "<the run_id>"}

``"${tasks.digest.result}"`` 把來源的校驗碼交給 ``FA_storage_verify``。加上
``strict: true`` 之後，不相符會讓任務失敗，於是 ``remove`` 被略過，來源保留。失敗的
執行會發布 ``pipeline.failed``，同一條路由會把它送到 Slack。

``FA_*`` 橋接
--------------------

橋接開啟時，``tools/list`` 先回傳語意工具，接著是每個已註冊的動作各一個工具，依名稱
排序，其 JSON Schema 由 Python 簽名推導而來。對這類工具呼叫 ``tools/call`` 會透過
註冊表派送，並以 JSON 編碼的回傳值回應；失敗則是 JSON-RPC 錯誤。先前的版本就是這樣
運作的，既有的設定可以繼續使用。

.. code-block:: text

   python -m automation_file mcp                                    # 語意工具 + 每個 FA_* 動作
   python -m automation_file mcp --allowed-actions FA_list_dir,FA_file_checksum
   python -m automation_file mcp --root /srv/reports --no-bridge    # 只有語意工具

``--allowed-actions`` 把橋接縮小到指定的動作。引數裡提到清單以外動作的呼叫會被拒絕
（無法用 ``FA_execute_action`` 繞過去）。``--no-bridge`` 或
``MCPServer(bridge=False)`` 會關閉橋接；此時 ``FA_*`` 名稱是未知的工具。

**政策不約束橋接。** 透過橋接呼叫的 ``FA_storage_copy`` 可以到達行程能到的任何
位置，不管 ``--root`` 怎麼設定。面對 AI 用戶端請使用 ``--no-bridge``；橋接只留給
那些即使沒有政策你也願意讓用戶端呼叫的工具。

從 Python 使用：

.. code-block:: python

   from automation_file import MCPServer, executor, tools_from_registry
   from automation_file.server.mcp_policy import MCPPolicy
   from automation_file.server.mcp_tools import SemanticToolkit

   MCPServer().serve_stdio()                                  # 和以前一樣：橋接開啟
   MCPServer(policy=MCPPolicy(roots=["/srv/reports"]), bridge=False).serve_stdio()

   for tool in tools_from_registry(executor.registry):        # 橋接的工具目錄
       print(tool["name"], "->", tool["description"])

   toolkit = SemanticToolkit(MCPPolicy(roots=["/srv/reports"]))   # 不經 JSON-RPC 使用工具
   outcome = toolkit.call("file_checksum", {"uri": "/srv/reports/a.csv"})
   outcome.is_error, outcome.payload["value"], outcome.correlation_id

旗標
--------

``python -m automation_file mcp`` 與 ``automation_file_mcp`` 主控台指令接受相同的
旗標。

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - 旗標
     - 意義
   * - ``--name``、``--version``
     - 握手時的 ``serverInfo``。預設值：``automation_file``、``1.0.0``。
   * - ``--allowed-actions a,b``
     - 橋接提供的已註冊動作。預設：全部。
   * - ``--no-bridge``
     - 只提供語意工具。
   * - ``--root URI``
     - 一個允許的位置；可重複。
   * - ``--allow-write``、``--allow-overwrite``、``--allow-delete``
     - 三項權限。後兩項需要第一項。
   * - ``--max-read-bytes N``、``--max-write-bytes N``、``--max-results N``、
       ``--max-search-bytes N``
     - 各項上限。
   * - ``--pipeline-dir URI``
     - 管線定義存放的地方。
   * - ``--pipeline-actions a,b``
     - 透過 MCP 執行的管線可以呼叫的動作。
   * - ``--tools a,b``
     - 要提供的語意工具，或 ``none``。

錯誤的旗標（未知的工具名稱、沒有 ``--allow-write`` 的 ``--allow-overwrite``、帶有
憑證的根位置）會讓指令在開始服務之前就以用法錯誤結束。

安全指引
----------------

* **行程的權限就是外部界線。** 伺服器以啟動它的使用者身分執行，使用後端被給予的
  憑證。政策為語意工具縮小這個範圍；它不能取代帳號、bucket policy 或 SFTP 使用者
  上的最小權限。
* **面對 AI 用戶端請關閉橋接**\ （``--no-bridge``）。橋接提供每個已註冊的動作，
  包含 ``FA_run_shell`` 與 ``FA_storage_delete``，而政策對它不適用。
* **根位置要盡量小。** 根位置是對其下所有內容的授權。不要使用 ``local:///`` 或家
  目錄。用戶端可以寫入的東西，請放在它專屬的目錄裡。
* **從唯讀開始。** 工作需要時才加上 ``--allow-write``，真的需要時才加上
  ``--allow-overwrite`` 與 ``--allow-delete``。能寫入但不能覆寫或刪除的用戶端，
  無法破壞原本就在那裡的東西。
* **檔案的內容不是指令。** 模型透過 ``file_read`` 與 ``file_search`` 讀到檔案內容，
  並可能依照讀到的東西行動。政策限制了這樣被挾持的工作階段能做的事；宿主的確認
  提示也是。對重要的操作，先要求一次 ``dry_run``。
* **管線。** 預設的動作留在根位置之內。你用 ``--pipeline-actions`` 加入的每個動作
  都不受限制地執行。管線目錄裡放的是 AI 用戶端寫下的定義：只有 ``pipeline_run``
  會對它們套用政策，所以不要用 ``FA_pipeline_run`` 或 ``Pipeline.from_file`` 執行
  它們，也不要讓排程器指向那個目錄。
* **回報類工具不受根位置約束。** ``audit_search``、``integrity_status`` 與
  ``pipeline_status`` 會顯示整個行程裡的資源名稱、錯誤與執行參數。對於不該看到這些
  的用戶端，請不要把它們列入 ``--tools``。
* **用戶端的名稱不能證明任何事。** 它只是稽核軌跡裡 actor 的標籤，而且由用戶端
  自己提供。stdio 沒有驗證機制：能啟動這個行程的人，就擁有它的能力。
* **機密。** 憑證絕不該放在儲存 URI 裡（帶有憑證的 URI 會被拒絕），也不該放在管線
  參數裡，因為參數會隨執行一起被記錄。日誌不含引數值，也不含檔案內容。
* **網路。** 語意工具本身不發出任何 HTTP 請求。儲存後端保有各自的檢查：TLS 驗證、
  SFTP 主機金鑰，以及會抓取 URL 的動作所用的 SSRF 防護。
* 不要在提供橋接的行程裡呼叫 ``PackageLoader.add_package_to_executor``：它會把套件
  的每個成員註冊成動作。

出問題時
----------------

``no storage location is allowed on this server``
    沒有設定任何根位置。加上 ``--root <儲存 URI 或目錄>``，或傳入
    ``MCPPolicy(roots=[...])``。

``... is outside the allowed locations (...)``
    位置不在任何根位置之內；訊息裡會列出根位置。請對照根位置檢查寫法：另一個
    bucket 或主機、相鄰的目錄（``reports`` 旁邊的 ``reports-old``）、authority 的
    大小寫不同，或通往同一個目錄的另一條路徑。

``... leaves the allowed location through a link or an absolute path``
    本機根位置底下的符號連結或 junction 指向根位置之外。如果用戶端應該能到達那裡，
    請把連結的目標加為根位置。

``this server is read-only``、``does not allow it``
    權限沒有開啟：``--allow-write``、``--allow-overwrite`` 或 ``--allow-delete``。
    ``file_move`` 需要寫入與刪除。

``already exists``
    傳入 ``overwrite=true``；伺服器也必須允許覆寫。

``file_read`` 只回傳檔案的一部分
    ``truncated`` 為 true：以 ``offset=next_offset`` 再呼叫一次，或調高
    ``--max-read-bytes``。對於不支援範圍讀取的後端，每次呼叫都會把整個檔案暫存到
    本機，所以翻閱很大的遠端檔案時請節制。

``file_search`` 漏掉某個檔案
    檢查 ``complete`` 與 ``skipped``。超過 ``--max-search-bytes`` 剩餘額度的檔案
    不會被搜尋；請縮小 ``pattern`` 或調高額度。內容是以 UTF-8 文字比對的。

``... is not allowed in a pipeline``
    定義提到了允許範圍以外的動作；訊息裡會列出允許的動作。請使用儲存動作，或用
    ``--pipeline-actions`` 加入該動作。

管線任務以 ``MCPLocationException`` 或 ``MCPPermissionException`` 失敗
    任務在執行時到達了根位置以外的位置，或需要一項沒有開啟的權限。定義之所以被
    接受，是因為位置來自參數。

``no pipeline named ... is stored``
    訊息裡會列出已儲存的名稱。沒有 ``--pipeline-dir`` 時，伺服器重新啟動後定義就
    不在了。

``pipeline_status`` 找不到某次執行
    執行紀錄預設存在記憶體裡。請在啟動腳本裡呼叫
    ``set_default_run_store(SQLiteRunStore(path))``。

``this server keeps no audit trail``
    請在啟動腳本裡於 ``serve_stdio()`` 之前呼叫 ``configure_audit(path)``。

``sftp://`` 或 ``s3://`` 位置明明在根位置之內卻失敗
    這個行程裡的後端沒有初始化。請在啟動腳本裡呼叫它的 ``later_init``；見
    `正式環境設定`_ 與 :doc:`storage`。

宿主列出數百個工具，或完全沒有語意工具
    前者是橋接：加上 ``--no-bridge`` 或 ``--allowed-actions``。後者是
    ``--tools none``，或套件的版本早於語意工具。

宿主在啟動時回報連線中斷
    有東西寫到了 ``stdout``，或指令以用法錯誤結束。請在終端機裡執行同一道指令：
    錯誤會寫到 ``stderr``。手動檢查伺服器的方法::

       printf '%s\n%s\n' \
         '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
         '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
         | python -m automation_file mcp --root /srv/reports --no-bridge

語意工具的每個例外都衍生自 ``MCPServerException``，因此也衍生自
``FileAutomationException``：``MCPPermissionException``\ （帶有 ``code``）、它的子類別
``MCPLocationException``，以及 ``MCPToolException``\ （帶有 ``kind``）。
