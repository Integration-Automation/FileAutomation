伺服器
======

.. automodule:: automation_file.server.tcp_server
   :members:

.. automodule:: automation_file.server.http_server
   :members:

HTTP 伺服器另外提供 ``GET /healthz``（liveness）、``GET /readyz``
（readiness——登錄表為空時回傳 503）、``GET /openapi.json``（OpenAPI 3.0
規格），以及 ``GET /progress``（以 WebSocket 推送
:class:`automation_file.core.progress.progress_registry` 快照）。

.. automodule:: automation_file.server.web_ui
   :members:

.. automodule:: automation_file.server.mcp_server
   :members:

.. automodule:: automation_file.server.metrics_server
   :members:

.. automodule:: automation_file.server.action_acl
   :members:

.. automodule:: automation_file.server.network_guards
   :members:
