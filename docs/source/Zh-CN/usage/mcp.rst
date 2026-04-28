MCP 服务器（Claude Desktop / Claude Code）
==========================================

``automation_file`` 自带一个 Model Context Protocol（MCP）服务器，
将共享的 :class:`~automation_file.core.action_registry.ActionRegistry`
中的每一项暴露为 MCP 工具。**Claude Desktop**、**Claude Code**
以及其他 MCP 宿主，可以像调用普通 MCP 工具一样调用 ``FA_*`` 动作——
无需自写插件，无需额外打包。

传输方式为 **stdio**（``stdin`` / ``stdout`` 上每行一条 JSON-RPC 2.0 消息），
与目前 MCP 宿主使用的协议一致。

提供的能力
----------

* ``initialize`` 握手，返回协议版本 ``2024-11-05``、
  ``serverInfo.name`` 与 ``serverInfo.version``。
* ``tools/list`` 为每个已注册的 ``FA_*`` 动作返回一个 MCP 工具描述，
  其参数 JSON Schema 由 Python 函数签名自动派生
  （``str → "string"``、``int → "integer"`` 等）。
* ``tools/call`` 通过注册表派发，并以 JSON 编码后的文本内容块返回结果。
* ``--allowed-actions`` 允许列表参数，让你只把注册表的子集暴露给宿主。
* 所有内部错误都会以 JSON-RPC 错误对象形式返回——
  宿主无需解析异常字符串即可呈现错误。

启动服务器
----------

CLI::

   python -m automation_file mcp
   python -m automation_file mcp --name automation_file --version 1.0.0
   python -m automation_file mcp --allowed-actions FA_list_dir,FA_file_checksum

进程在前台运行，从 ``stdin`` 读取分行 JSON 并把响应写到 ``stdout``。
通常宿主会替你启动该进程，不需要手工运行。

从 Python 启动（例如嵌入到自家 stdio 桥接器里）：

.. code-block:: python

   from automation_file import MCPServer

   server = MCPServer(name="automation_file", version="1.0.0")
   server.serve_stdio()        # stdin 关闭前阻塞

通过自定义注册表把可调用动作面缩小：

.. code-block:: python

   from automation_file import MCPServer
   from automation_file.core.action_registry import ActionRegistry
   from automation_file import executor

   safe = ActionRegistry()
   for name in ("FA_list_dir", "FA_file_checksum", "FA_fast_find"):
       safe.register(name, executor.registry.resolve(name))

   MCPServer(safe).serve_stdio()

Claude Desktop 配置
-------------------

在 ``~/Library/Application Support/Claude/claude_desktop_config.json``
（macOS）或 ``%APPDATA%\Claude\claude_desktop_config.json``
（Windows）的 ``mcpServers`` 下添加条目：

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "python",
         "args": ["-m", "automation_file", "mcp"]
       }
     }
   }

重启 Claude Desktop。``automation_file`` 服务器会出现在工具面板中，
所有 ``FA_*`` 动作都可被调用。

对于操作敏感路径的宿主，建议把可用动作锁死为白名单：

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "python",
         "args": [
           "-m", "automation_file", "mcp",
           "--allowed-actions",
           "FA_list_dir,FA_fast_find,FA_file_checksum,FA_verify_checksum"
         ]
       }
     }
   }

显式指定虚拟环境的解释器（避免误用系统 Python）：

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "C:\\envs\\fa\\Scripts\\python.exe",
         "args": ["-m", "automation_file", "mcp"]
       }
     }
   }

Claude Code 配置
----------------

Claude Code 使用同一份 MCP 定义。可通过 ``claude mcp add`` CLI 注册::

   claude mcp add automation_file -- python -m automation_file mcp

或在仓库根目录提交 ``.mcp.json``：

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "python",
         "args": ["-m", "automation_file", "mcp"]
       }
     }
   }

加载完成后，要求 Claude Code 使用 ``mcp__automation_file__FA_*`` 工具——
例如「使用 FA_fast_find 找出 ./var 下所有 *.log」。

查看工具目录
------------

可渲染与宿主完全一致的描述符——便于测试、GUI 调试或生成文档：

.. code-block:: python

   from automation_file import tools_from_registry, executor

   for tool in tools_from_registry(executor.registry):
       print(tool["name"], "->", tool["description"])

每个描述符的形状如下::

   {
     "name": "FA_fast_find",
     "description": "底层可调用对象的第一行 docstring。",
     "inputSchema": {
       "type": "object",
       "properties": {"root": {"type": "string"}, "pattern": {"type": "string"}},
       "required": ["root", "pattern"],
       "additionalProperties": true,
     },
   }

手工烟雾测试
------------

直接把 JSON-RPC 帧喂给服务器以确认其能正常加载::

   printf '%s\n%s\n%s\n' \
     '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
     '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
     '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"FA_fast_find","arguments":{"root":".","pattern":"*.py","limit":3}}}' \
     | python -m automation_file mcp

每行输入在 stdout 上恰得到一条 JSON-RPC 响应（通知没有响应）。

安全注意事项
------------

* MCP 服务器以 **启动它的 Python 进程的权限** 运行。
  每次工具调用都落在你 shell 用户账户里。
* 默认情况下，服务器暴露 **全部** 已注册的 ``FA_*`` 动作，
  其中包含会删除文件、写文件系统、上传到远程后端的动作。
  对任何不完全可信的宿主，请用 ``--allowed-actions`` 只白名单暴露
  必要的动作。
* 在打算给第三方宿主使用的 MCP 服务器启动前，**不要** 调用
  :func:`~automation_file.PackageLoader.add_package_to_executor`
  （或暴露其动作）。该助手会注册任意包的全部顶层函数 / 类 / 内置，
  权限相当于 ``eval``。
* 服务器启动时会通过 ``file_automation_logger`` 以 ``INFO`` 级别记录
  暴露的工具数量与配置的服务器名称。工具调用负载从不被记录。
* 涉及对外 HTTP 的动作（``FA_download_file``、各云后端）仍会通过
  SSRF 校验；MCP 层不会放宽任何单动作检查。
