# automation_file MCP server

Three ways to launch the MCP stdio server, in order of preference:

```bash
automation_file_mcp                                # installed console script
python -m automation_file mcp                      # CLI subcommand
python examples/mcp/run_mcp.py                     # standalone launcher
```

The server offers the fourteen **semantic tools** (`file_read`, `file_copy`,
`pipeline_run`, ...), which are bound to a permission policy, and the **bridge**
that exposes every registered `FA_*` action. For an AI client, give the semantic
tools a root and switch the bridge off:

```bash
automation_file_mcp --root /srv/reports --no-bridge                 # read-only
automation_file_mcp --root /srv/reports --allow-write --no-bridge   # may create files
```

All three launch styles accept the same flags:

| Flag                  | Default            | Description                                    |
|-----------------------|--------------------|------------------------------------------------|
| `--name`              | `automation_file`  | `serverInfo.name` returned at handshake        |
| `--version`           | `1.0.0`            | `serverInfo.version` returned at handshake     |
| `--allowed-actions`   | *(all)*            | Comma-separated allow list for the bridge (e.g. `FA_file_checksum,FA_fast_find`) |
| `--no-bridge`         | *(bridge on)*      | Offer only the semantic tools                  |
| `--root`              | *(none)*           | A location the semantic tools may work in: a storage URI or a local directory; repeatable |
| `--allow-write`       | off                | Let the semantic tools create files            |
| `--allow-overwrite`   | off                | Let them replace an existing file (needs `--allow-write`) |
| `--allow-delete`      | off                | Let them delete; a move deletes its source (needs `--allow-write`) |
| `--max-read-bytes`    | `262144`           | Most bytes `file_read` returns in one call     |
| `--max-write-bytes`   | `1048576`          | Largest content `file_write` accepts           |
| `--max-results`       | `200`              | Most entries a listing or a search returns     |
| `--max-search-bytes`  | `8388608`          | Most bytes one content search reads            |
| `--pipeline-dir`      | *(memory)*         | Where `pipeline_create` keeps definitions      |
| `--pipeline-actions`  | *(by permission)*  | Comma-separated actions a pipeline run through MCP may call |
| `--tools`             | *(all fourteen)*   | Comma-separated semantic tools to offer, or `none` |

## Claude Desktop

Edit `claude_desktop_config.json`:

- **Windows** — `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**  — `~/Library/Application Support/Claude/claude_desktop_config.json`

`claude_desktop_config.json` in this directory is a ready-to-copy sample: the
semantic tools on one directory, the bridge narrowed to an allow list, the full
bridge, and the standalone launcher. Pick the one that matches your install.

## Manual smoke test

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' | automation_file_mcp
```

A single line reply containing `serverInfo` means the server is healthy.

## Security

Use `--no-bridge` for an AI client. The semantic tools stay inside `--root` and
are read-only until `--allow-write`; the bridge is not bound by either. The
default registry includes `FA_run_shell`, `FA_encrypt_file`, and other
high-privilege actions that an MCP host may invoke without prompting, so when
the bridge stays on, narrow it with `--allowed-actions`.

The full manual, with the permission model and an example workflow, is
`docs/source/Eng/usage/mcp.rst`.
