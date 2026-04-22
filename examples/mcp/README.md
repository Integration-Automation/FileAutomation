# automation_file MCP server

Three ways to launch the MCP stdio bridge, in order of preference:

```bash
automation_file_mcp                                # installed console script
python -m automation_file mcp                      # CLI subcommand
python examples/mcp/run_mcp.py                     # standalone launcher
```

All three accept the same flags:

| Flag                 | Default            | Description                                    |
|----------------------|--------------------|------------------------------------------------|
| `--name`             | `automation_file`  | `serverInfo.name` returned at handshake        |
| `--version`          | `1.0.0`            | `serverInfo.version` returned at handshake     |
| `--allowed-actions`  | *(all)*            | Comma-separated allow list (e.g. `FA_file_checksum,FA_fast_find`) |

## Claude Desktop

Edit `claude_desktop_config.json`:

- **Windows** — `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**  — `~/Library/Application Support/Claude/claude_desktop_config.json`

`claude_desktop_config.json` in this directory is a ready-to-copy sample
covering the three launch styles. Pick the one that matches your install.

## Manual smoke test

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | automation_file_mcp
```

A single line reply containing `serverInfo` means the server is healthy.

## Security

`--allowed-actions` is strongly recommended. The default registry includes
`FA_run_shell`, `FA_encrypt_file`, and other high-privilege actions that an
MCP host may invoke without prompting.
