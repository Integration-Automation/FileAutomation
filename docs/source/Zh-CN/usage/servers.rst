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

Web UI
------

浏览器中的只读仪表板，以标准库与 HTMX 提供（从固定的 CDN URL 加载一个脚本，并附 SRI
哈希）。

.. code-block:: python

   from automation_file import start_web_ui

   server = start_web_ui(host="127.0.0.1", port=9955, shared_secret="optional-secret")
   # 浏览 http://127.0.0.1:9955/
   # 稍后：
   server.shutdown()
   server.server_close()

页面为每个区段轮询一个 HTML 片段。除了传输进度以外，每个片段都由应用层
（:doc:`app_layer`）渲染，也就是桌面窗口（:doc:`gui`）所调用的同一组服务，所以两者
显示相同的状态。

.. list-table::
   :header-rows: 1
   :widths: 22 14 64

   * - 片段
     - 轮询间隔
     - 显示内容
   * - ``GET /ui/health``
     - 5 秒
     - ``ok`` 或 ``attention`` 与其原因；已注册的动作、运行中的运行、调度作业、
       监控器、sink 与路由、审计轨迹。
   * - ``GET /ui/runs``
     - 3 秒
     - 运行中与最近的流水线运行，以及最新几次运行的结局。
   * - ``GET /ui/integrity``
     - 10 秒
     - 每个具名完整性监控器，以及它上次发现的漂移。
   * - ``GET /ui/events``
     - 5 秒
     - 总线上最新的事件，新的在前。
   * - ``GET /ui/storage``
     - 30 秒
     - 每个存储后端以及能不能用。
   * - ``GET /ui/audit``
     - 10 秒
     - 最新的审计记录；要先以 ``configure_audit`` 给审计轨迹一个 store。
   * - ``GET /ui/progress``
     - 2 秒
     - 进度注册表中进行中的传输。
   * - ``GET /ui/registry``
     - 30 秒
     - 每个已注册动作的名称。

``GET /`` 与 ``GET /index.html`` 提供页面；其他路径一律返回 ``404``。没有任何路由会
改变东西：要执行动作，请通过上面的动作服务器，并使用它们自己的鉴权机制。

* **默认仅绑定 loopback。** 要绑定其他地址必须传 ``allow_non_loopback=True``；这么做
  却没有 ``shared_secret`` 时会记录一条警告。
* **共享密钥。** 设置 ``shared_secret`` 后，每个请求都需要
  ``Authorization: Bearer <secret>``，否则返回 ``401``。页面把这个请求头放在
  ``hx-headers`` 中，让它自己的轮询得到授权；因此能读到页面的人就能读到密钥，请通过
  loopback 或在 TLS 之后提供它。
* **已转义且已屏蔽。** 片段显示的一切都经过 HTML 转义，而且应用层已经先屏蔽其中的
  token、密码与 webhook URL。
* **片段绝不会弄坏页面。** 某个服务无法响应时，它的片段会显示
  ``unavailable: <ExceptionType>``，其他片段照常工作。

``start_web_ui(services=...)`` 接受以 ``automation_file.app.build_services`` 构建的
一组服务，用来显示进程共用的那一组以外的 run store、事件总线或 resolver。
