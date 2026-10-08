動作伺服器
==========

TCP 動作伺服器
--------------

.. code-block:: python

   from automation_file import start_autocontrol_socket_server

   server = start_autocontrol_socket_server(
       host="localhost", port=9943, shared_secret="optional-secret",
   )
   # 稍後：
   server.shutdown()
   server.server_close()

設定 ``shared_secret`` 後，用戶端必須在 JSON 動作清單之前加上
``AUTH <secret>\n`` 前綴。伺服器預設仍綁定 loopback，除非顯式傳入
``allow_non_loopback=True``，否則拒絕非 loopback 綁定。

每條連線只接受一份 JSON 負載（``recv(8192)``）。
若要提高該上限，必須同時改採帶長度前綴的協定。

HTTP 動作伺服器
---------------

.. code-block:: python

   from automation_file import start_http_action_server

   server = start_http_action_server(
       host="127.0.0.1", port=9944, shared_secret="optional-secret",
   )

   # 用戶端：
   # curl -H 'Authorization: Bearer optional-secret' \
   #      -d '[["FA_create_dir",{"dir_path":"x"}]]' \
   #      http://127.0.0.1:9944/actions

HTTP 回應皆為 JSON。授權失敗回 ``401``；JSON 異常回 ``400``；
未知路徑回 ``404``。請求主體上限 1 MB。預設只綁定 loopback；
若要綁定其他地址需傳 ``allow_non_loopback=True``。

共享密鑰比較使用 :func:`hmac.compare_digest`（常數時間）。
切勿記錄密鑰或原始負載。

Web UI
------

瀏覽器中的唯讀儀表板，以標準函式庫與 HTMX 提供（從固定的 CDN URL 載入一支腳本，並
附 SRI 雜湊）。

.. code-block:: python

   from automation_file import start_web_ui

   server = start_web_ui(host="127.0.0.1", port=9955, shared_secret="optional-secret")
   # 瀏覽 http://127.0.0.1:9955/
   # 稍後：
   server.shutdown()
   server.server_close()

頁面為每個區段輪詢一個 HTML 片段。除了傳輸進度以外，每個片段都由應用層
（:doc:`app_layer`）繪製，也就是桌面視窗（:doc:`gui`）所呼叫的同一組服務，所以兩者
顯示相同的狀態。

.. list-table::
   :header-rows: 1
   :widths: 22 14 64

   * - 片段
     - 輪詢間隔
     - 顯示內容
   * - ``GET /ui/health``
     - 5 秒
     - ``ok`` 或 ``attention`` 與其原因；已註冊的動作、執行中的執行、排程工作、
       監控器、sink 與路由、稽核軌跡。
   * - ``GET /ui/runs``
     - 3 秒
     - 執行中與最近的管線執行，以及最新幾次執行的結局。
   * - ``GET /ui/integrity``
     - 10 秒
     - 每個具名完整性監控器，以及它上次發現的漂移。
   * - ``GET /ui/events``
     - 5 秒
     - 匯流排上最新的事件，新的在前。
   * - ``GET /ui/storage``
     - 30 秒
     - 每個儲存後端以及能不能用。
   * - ``GET /ui/audit``
     - 10 秒
     - 最新的稽核紀錄；要先以 ``configure_audit`` 給稽核軌跡一個 store。
   * - ``GET /ui/progress``
     - 2 秒
     - 進度註冊表中進行中的傳輸。
   * - ``GET /ui/registry``
     - 30 秒
     - 每個已註冊動作的名稱。

``GET /`` 與 ``GET /index.html`` 提供頁面；其他路徑一律回 ``404``。沒有任何路由會
改變東西：要執行動作，請透過上面的動作伺服器，並使用它們自己的驗證機制。

* **預設只綁定 loopback。** 要綁定其他位址必須傳 ``allow_non_loopback=True``；這麼做
  卻沒有 ``shared_secret`` 時會記錄一則警告。
* **共享密鑰。** 設定 ``shared_secret`` 後，每個請求都需要
  ``Authorization: Bearer <secret>``，否則回 ``401``。頁面把這個標頭放在
  ``hx-headers`` 中，讓它自己的輪詢得到授權；因此能讀到頁面的人就能讀到密鑰，請透過
  loopback 或在 TLS 之後提供它。
* **已跳脫且已遮蔽。** 片段顯示的一切都經過 HTML 跳脫，而且應用層已經先遮蔽其中的
  token、密碼與 webhook URL。
* **片段絕不會弄壞頁面。** 某個服務無法回應時，它的片段會顯示
  ``unavailable: <ExceptionType>``，其他片段照常運作。

``start_web_ui(services=...)`` 接受以 ``automation_file.app.build_services`` 建立的
一組服務，用來顯示行程共用的那一組以外的 run store、事件匯流排或 resolver。
