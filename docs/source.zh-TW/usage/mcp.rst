MCP 伺服器（Claude Desktop / Claude Code）
==========================================

``automation_file`` 內建一個 Model Context Protocol（MCP）伺服器，
把共用的 :class:`~automation_file.core.action_registry.ActionRegistry`
中每一項暴露為 MCP 工具。**Claude Desktop**、**Claude Code**
以及其他 MCP 宿主，可以像呼叫一般 MCP 工具一樣呼叫 ``FA_*`` 動作——
無需自寫外掛、無需額外打包。

傳輸方式為 **stdio**（``stdin`` / ``stdout`` 上每行一條 JSON-RPC 2.0 訊息），
與目前 MCP 宿主使用的協定一致。

提供的能力
----------

* ``initialize`` 握手，回傳協定版本 ``2024-11-05``、
  ``serverInfo.name`` 與 ``serverInfo.version``。
* ``tools/list`` 為每個已註冊的 ``FA_*`` 動作回傳一個 MCP 工具描述，
  其參數 JSON Schema 由 Python 函式簽名自動推導
  （``str → "string"``、``int → "integer"`` 等）。
* ``tools/call`` 透過註冊表派送，並以 JSON 編碼的文字內容區塊回傳結果。
* ``--allowed-actions`` 允許清單參數，讓你只把註冊表的子集暴露給宿主。
* 所有內部錯誤都會以 JSON-RPC 錯誤物件形式回傳——
  宿主不必解析例外字串即可呈現錯誤。

啟動伺服器
----------

CLI::

   python -m automation_file mcp
   python -m automation_file mcp --name automation_file --version 1.0.0
   python -m automation_file mcp --allowed-actions FA_list_dir,FA_file_checksum

行程在前景執行，從 ``stdin`` 讀取分行 JSON 並把回應寫到 ``stdout``。
通常宿主會替你啟動該行程，不需要手動執行。

從 Python 啟動（例如嵌入到自家 stdio 橋接器中）：

.. code-block:: python

   from automation_file import MCPServer

   server = MCPServer(name="automation_file", version="1.0.0")
   server.serve_stdio()        # stdin 關閉前阻塞

以自訂註冊表把可呼叫動作面縮小：

.. code-block:: python

   from automation_file import MCPServer
   from automation_file.core.action_registry import ActionRegistry
   from automation_file import executor

   safe = ActionRegistry()
   for name in ("FA_list_dir", "FA_file_checksum", "FA_fast_find"):
       safe.register(name, executor.registry.resolve(name))

   MCPServer(safe).serve_stdio()

Claude Desktop 設定
-------------------

在 ``~/Library/Application Support/Claude/claude_desktop_config.json``
（macOS）或 ``%APPDATA%\Claude\claude_desktop_config.json``
（Windows）的 ``mcpServers`` 下新增條目：

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "python",
         "args": ["-m", "automation_file", "mcp"]
       }
     }
   }

重新啟動 Claude Desktop。``automation_file`` 伺服器會出現在工具面板，
所有 ``FA_*`` 動作皆可呼叫。

對於會操作敏感路徑的宿主，建議把可用動作鎖死為白名單：

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

顯式指定虛擬環境的直譯器（避免誤用系統 Python）：

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "C:\\envs\\fa\\Scripts\\python.exe",
         "args": ["-m", "automation_file", "mcp"]
       }
     }
   }

Claude Code 設定
----------------

Claude Code 使用相同的 MCP 定義。可透過 ``claude mcp add`` CLI 註冊::

   claude mcp add automation_file -- python -m automation_file mcp

或在儲存庫根目錄提交 ``.mcp.json``：

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "python",
         "args": ["-m", "automation_file", "mcp"]
       }
     }
   }

載入完成後，請 Claude Code 使用 ``mcp__automation_file__FA_*`` 工具——
例如「使用 FA_fast_find 找出 ./var 下所有 *.log」。

檢視工具目錄
------------

可呈現與宿主完全一致的描述符——便於測試、GUI 除錯或產生文件：

.. code-block:: python

   from automation_file import tools_from_registry, executor

   for tool in tools_from_registry(executor.registry):
       print(tool["name"], "->", tool["description"])

每個描述符的形狀如下::

   {
     "name": "FA_fast_find",
     "description": "底層可呼叫物件的第一行 docstring。",
     "inputSchema": {
       "type": "object",
       "properties": {"root": {"type": "string"}, "pattern": {"type": "string"}},
       "required": ["root", "pattern"],
       "additionalProperties": true,
     },
   }

手動煙霧測試
------------

直接把 JSON-RPC frame 餵給伺服器以確認其能正常載入::

   printf '%s\n%s\n%s\n' \
     '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
     '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
     '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"FA_fast_find","arguments":{"root":".","pattern":"*.py","limit":3}}}' \
     | python -m automation_file mcp

每行輸入在 stdout 上恰得到一條 JSON-RPC 回應（通知沒有回應）。

安全注意事項
------------

* MCP 伺服器以 **啟動它的 Python 行程的權限** 執行。
  每次工具呼叫都落在你 shell 使用者帳號中。
* 預設情況下，伺服器暴露 **全部** 已註冊的 ``FA_*`` 動作，
  其中包含會刪除檔案、寫檔案系統、上傳到遠端後端的動作。
  對任何你並非完全信任的宿主，請用 ``--allowed-actions`` 只白名單暴露
  必要動作。
* 在打算給第三方宿主使用的 MCP 伺服器啟動前，**不要** 呼叫
  :func:`~automation_file.PackageLoader.add_package_to_executor`
  （或暴露其動作）。該輔助函式會註冊任意套件的所有頂層函式 / 類別 / 內建，
  威力相當於 ``eval``。
* 伺服器啟動時會透過 ``file_automation_logger`` 以 ``INFO`` 等級記錄
  暴露的工具數量與設定的伺服器名稱。工具呼叫負載從不被記錄。
* 涉及對外 HTTP 的動作（``FA_download_file``、各雲端後端）仍會通過
  SSRF 檢查；MCP 層不會放鬆任何單一動作的檢查。
