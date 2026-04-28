MCP server (Claude Desktop / Claude Code)
=========================================

``automation_file`` ships a Model Context Protocol (MCP) server that
exposes every entry of the shared
:class:`~automation_file.core.action_registry.ActionRegistry` as an MCP
tool. Hosts such as **Claude Desktop**, **Claude Code**, and other
MCP-aware clients can then call ``FA_*`` actions exactly like any other
MCP tool — no plugin code, no extra packaging.

Transport is **stdio** (one JSON-RPC 2.0 message per line on
``stdin`` / ``stdout``), matching the protocol that current MCP hosts
consume.

What you get
------------

* ``initialize`` handshake reporting protocol version ``2024-11-05`` and
  ``serverInfo.name`` / ``serverInfo.version``.
* ``tools/list`` returns one MCP tool per registered ``FA_*`` action,
  with an auto-derived JSON Schema for its arguments (built from the
  Python signature: ``str → "string"``, ``int → "integer"``, etc.).
* ``tools/call`` dispatches through the registry and returns the result
  as a JSON-encoded text content block.
* ``--allowed-actions`` allow-list flag to surface only a subset of the
  registry to the host.
* Every internal failure surfaces as a JSON-RPC error object — the host
  can render it without parsing exception strings.

Starting the server
-------------------

CLI::

   python -m automation_file mcp
   python -m automation_file mcp --name automation_file --version 1.0.0
   python -m automation_file mcp --allowed-actions FA_list_dir,FA_file_checksum

The process runs in the foreground, reading newline-delimited JSON from
``stdin`` and writing responses to ``stdout``. MCP hosts spawn this
process for you — you rarely run it by hand.

From Python (e.g. when embedding into another stdio bridge):

.. code-block:: python

   from automation_file import MCPServer

   server = MCPServer(name="automation_file", version="1.0.0")
   server.serve_stdio()        # blocks until stdin closes

Filter to a smaller surface area by passing your own registry:

.. code-block:: python

   from automation_file import MCPServer
   from automation_file.core.action_registry import ActionRegistry
   from automation_file import executor

   safe = ActionRegistry()
   for name in ("FA_list_dir", "FA_file_checksum", "FA_fast_find"):
       safe.register(name, executor.registry.resolve(name))

   MCPServer(safe).serve_stdio()

Claude Desktop configuration
----------------------------

Add an entry under ``mcpServers`` in
``~/Library/Application Support/Claude/claude_desktop_config.json`` (macOS) or
``%APPDATA%\Claude\claude_desktop_config.json`` (Windows):

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "python",
         "args": ["-m", "automation_file", "mcp"]
       }
     }
   }

Restart Claude Desktop. The ``automation_file`` server appears in the
tools panel; every ``FA_*`` action is callable.

Lock the surface area down to a curated allow-list — recommended for
hosts that operate on sensitive paths:

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

Use a virtualenv interpreter explicitly (avoids picking up the system
Python):

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "C:\\envs\\fa\\Scripts\\python.exe",
         "args": ["-m", "automation_file", "mcp"]
       }
     }
   }

Claude Code configuration
-------------------------

Claude Code consumes the same MCP definition. Register the server with
the ``claude mcp add`` CLI::

   claude mcp add automation_file -- python -m automation_file mcp

Or commit a ``.mcp.json`` to the repo root:

.. code-block:: json

   {
     "mcpServers": {
       "automation_file": {
         "command": "python",
         "args": ["-m", "automation_file", "mcp"]
       }
     }
   }

After it loads, ask Claude Code to use ``mcp__automation_file__FA_*``
tools — for example ``"use FA_fast_find to locate every *.log under
./var"``.

Inspecting the catalogue
------------------------

Render the same descriptors a host would see — useful for tests, GUI
debugging, or generating documentation:

.. code-block:: python

   from automation_file import tools_from_registry, executor

   for tool in tools_from_registry(executor.registry):
       print(tool["name"], "->", tool["description"])

Each descriptor is shaped as::

   {
     "name": "FA_fast_find",
     "description": "First docstring line of the underlying callable.",
     "inputSchema": {
       "type": "object",
       "properties": {"root": {"type": "string"}, "pattern": {"type": "string"}},
       "required": ["root", "pattern"],
       "additionalProperties": true,
     },
   }

Manual smoke test
-----------------

Pipe JSON-RPC frames straight at the server to confirm it loads::

   printf '%s\n%s\n%s\n' \
     '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
     '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
     '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"FA_fast_find","arguments":{"root":".","pattern":"*.py","limit":3}}}' \
     | python -m automation_file mcp

Each input line gets exactly one JSON-RPC reply on stdout (notifications
have no reply).

Security considerations
-----------------------

* The MCP server runs with **the same privileges as the Python process
  that starts it.** Every tool call lands in your shell's user account.
* By default the server exposes **every** registered ``FA_*`` action,
  including ones that delete files, write to the filesystem, or upload
  to remote backends. Use ``--allowed-actions`` to whitelist a tight
  surface for any host you don't fully trust.
* Do **not** call
  :func:`~automation_file.PackageLoader.add_package_to_executor` (or
  expose its action) before starting an MCP server intended for a
  third-party host. That helper registers every top-level function /
  class / builtin of an arbitrary package and is eval-grade power.
* The server logs at the ``INFO`` level via
  ``file_automation_logger`` when it starts, including the number of
  exposed tools and the configured server name. Tool-call payloads are
  never logged.
* Outbound HTTP-bearing actions (``FA_download_file``, the cloud
  backends) keep their SSRF guard; the MCP layer does not loosen any
  per-action check.
