服务器
======

.. automodule:: automation_file.server.tcp_server
   :members:

.. automodule:: automation_file.server.http_server
   :members:

HTTP 服务器还提供 ``GET /healthz``（liveness）、``GET /readyz``
（readiness——注册表为空时返回 503）、``GET /openapi.json``（OpenAPI 3.0
规格），以及 ``GET /progress``（通过 WebSocket 推送
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
