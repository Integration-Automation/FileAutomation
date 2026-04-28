动作服务器
==========

TCP 动作服务器
--------------

.. code-block:: python

   from automation_file import start_autocontrol_socket_server

   server = start_autocontrol_socket_server(
       host="localhost", port=9943, shared_secret="optional-secret",
   )
   # 稍后：
   server.shutdown()
   server.server_close()

设置 ``shared_secret`` 后，客户端必须在 JSON 动作列表之前加上
``AUTH <secret>\n`` 前缀。服务器默认仍绑定 loopback，除非显式传入
``allow_non_loopback=True``，否则拒绝非 loopback 绑定。

每个连接只接受一份 JSON 负载（``recv(8192)``）。
若要提高该上限，必须同时改为带长度前缀的协议。

HTTP 动作服务器
---------------

.. code-block:: python

   from automation_file import start_http_action_server

   server = start_http_action_server(
       host="127.0.0.1", port=9944, shared_secret="optional-secret",
   )

   # 客户端：
   # curl -H 'Authorization: Bearer optional-secret' \
   #      -d '[["FA_create_dir",{"dir_path":"x"}]]' \
   #      http://127.0.0.1:9944/actions

HTTP 响应均为 JSON。鉴权失败返回 ``401``；非法 JSON 返回 ``400``；
未知路径返回 ``404``。请求体上限 1 MB。默认仅绑定 loopback；
若要绑定其他地址须传 ``allow_non_loopback=True``。

共享密钥比较使用 :func:`hmac.compare_digest`（常数时间）。
切勿记录密钥或原始负载。
