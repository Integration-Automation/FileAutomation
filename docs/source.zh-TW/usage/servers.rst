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
