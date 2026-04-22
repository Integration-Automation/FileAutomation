"""Minimal MCP stdio launcher.

Point an MCP host at this file with::

    {
      "mcpServers": {
        "automation_file": {
          "command": "python",
          "args": ["/absolute/path/to/examples/mcp/run_mcp.py"]
        }
      }
    }

For a whitelisted registry prefer the installed console script
``automation_file_mcp --allowed-actions FA_list_dir,FA_file_checksum`` or
``python -m automation_file mcp --allowed-actions ...``.
"""

from __future__ import annotations

import sys

from automation_file.server.mcp_server import _cli


if __name__ == "__main__":
    sys.exit(_cli())
