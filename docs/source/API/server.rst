Server
======

.. automodule:: automation_file.server.tcp_server
   :members:

.. automodule:: automation_file.server.http_server
   :members:

The HTTP server also exposes ``GET /healthz`` (liveness), ``GET /readyz``
(readiness — returns 503 when the registry is empty), ``GET /openapi.json``
(OpenAPI 3.0 spec), and ``GET /progress`` (WebSocket stream of
:class:`automation_file.core.progress.progress_registry` snapshots).

.. automodule:: automation_file.server.web_ui
   :members:

.. automodule:: automation_file.server.mcp_server
   :members:

The semantic MCP tools: the policy, the toolkit, and the modules that hold the
tools.

.. automodule:: automation_file.server.mcp_policy
   :members:

.. automodule:: automation_file.server.mcp_tools
   :members:

.. automodule:: automation_file.server.mcp_tool_model
   :members:

.. automodule:: automation_file.server.mcp_file_tools
   :members:

.. automodule:: automation_file.server.mcp_storage_tools
   :members:

.. automodule:: automation_file.server.mcp_pipeline_tools
   :members:

.. automodule:: automation_file.server.mcp_pipeline_actions
   :members:

.. automodule:: automation_file.server.mcp_report_tools
   :members:

.. automodule:: automation_file.server.metrics_server
   :members:

.. automodule:: automation_file.server.action_acl
   :members:

.. automodule:: automation_file.server.network_guards
   :members:
