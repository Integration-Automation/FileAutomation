# FileAutomation Architecture

> Short overview for people and agents.
> Last verified: 2026-09-22 against `2e6c0ec` on `dev`.

## 1. Purpose

FileAutomation (`automation_file`) is an automation-first library for local file, directory and
archive operations, SSRF-checked HTTP downloads, and remote storage (Google Drive, S3, Azure Blob,
Dropbox, SFTP, FTP, OneDrive, Box, plus SMB and WebDAV clients). Every operation is an `FA_*`
command in one `ActionRegistry`, so JSON action lists run the same way in-process, from files, from
the CLI, over loopback TCP or HTTP servers, as MCP tools, or from the PySide6 GUI.

## 2. Layers and directories

| Path | Responsibility |
| --- | --- |
| `automation_file/__init__.py` | Public facade (`__all__`). Wires the shared `executor`, `callback_executor` and `package_manager` over one registry. `launch_ui` is loaded lazily through `__getattr__` |
| `automation_file/__main__.py` | CLI: legacy flags plus subcommands |
| `automation_file/core/` | Engine: `action_registry.py` (`ActionRegistry`, `build_default_registry`), `action_executor.py` (`ActionExecutor`, shared `executor`), `callback_executor.py`, `package_loader.py`, `plugins.py`, `dag_executor.py`, `action_queue.py`, `json_store.py`, `substitution.py`. Also cross-cutting helpers: `retry`, `quota`, `rate_limit`, `circuit_breaker`, `file_lock`, `sqlite_lock`, `checksum`, `manifest`, `crypto`, `secrets`, `config`, `config_watcher`, `audit`, `metrics`, `tracing`, `progress`, `fim`, `content_store` |
| `automation_file/local/` | Local strategy modules: file, dir, zip, tar and archive ops, sync, diff, text/JSON/data edits, templates, versioning, trash, `shell_ops` (argv-only subprocess), conditional branches. `safe_paths.py` guards against path traversal |
| `automation_file/remote/` | `url_validator.py` (SSRF guard), `http_download.py`, `cross_backend.py`, `fsspec_bridge.py`. One subpackage per backend: `google_drive/`, `s3/`, `azure_blob/`, `dropbox_api/`, `sftp/`, `ftp/`, `onedrive/`, `box/`, each with `client.py`, `*_ops.py` and `register_<backend>_ops`. `smb/` and `webdav/` have a client only |
| `automation_file/server/` | `tcp_server.py`, `http_server.py`, `mcp_server.py`, `web_ui.py`, `metrics_server.py`, `action_acl.py` (`ActionACL`), `network_guards.py` (`ensure_loopback`) |
| `automation_file/client/` | `HTTPActionClient` for the HTTP action server |
| `automation_file/trigger/`, `scheduler/`, `notify/` | Watchdog file triggers, cron scheduler, notification sinks. Each registers its own `FA_*` ops |
| `automation_file/project/` | `ProjectBuilder`, `create_project_dir` |
| `automation_file/ui/` | PySide6 GUI: `launcher.launch_ui`, `main_window.MainWindow`, `worker.ActionWorker`, `log_widget.LogPanel`, `tabs/` (backend panels are grouped under `TransferTab`) |
| `automation_file/utils/` | File discovery, fast find, grep, duplicate finder, backup rotation |
| `automation_file/exceptions.py`, `logging_config.py` | `FileAutomationException` hierarchy; `file_automation_logger` (INFO+ to stderr, DEBUG+ to `$FILE_AUTOMATION_LOG_FILE` or `~/.automation_file/logs/FileAutomation.log`, opened on first use) |
| `stable.toml`, `dev.toml` | Packaging for `automation_file` and `automation_file_dev`. No `pyproject.toml` is committed; CI and publish copy one of these TOMLs into place |
| `main_ui.py` | Development shortcut for `launch_ui()` |
| `tests/`, `docs/`, `examples/mcp/` | pytest suite (fixtures in `tests/conftest.py`); Sphinx docs; MCP host configuration example |

## 3. Entry points and public interfaces

- **Python facade** (`import automation_file`): `execute_action`, `execute_files`,
  `execute_action_parallel`, `validate_action`, `execute_action_dag`, `add_command_to_executor`,
  `executor`, `callback_executor`, `package_manager`, `ActionRegistry`, `build_default_registry`,
  `driver_instance` (Google Drive), `start_autocontrol_socket_server`, `start_http_action_server`,
  `HTTPActionClient`, `MCPServer`, `create_project_dir`, `launch_ui` (lazy).
- **Action format**: an action is `[name]`, `[name, {kwargs}]` or `[name, [args]]`. A file holds a
  list of actions or `{"auto_control": [...]}`.
- **CLI** (`python -m automation_file`; no console script for it):
  - legacy flags `-e/--execute_file`, `-d/--execute_dir`, `-c/--create_project` and `--execute_str`.
    `_execute_str` decodes a second time when the first `json.loads` yields a string;
  - subcommands `zip`, `unzip`, `download`, `create-file`, `server`, `http-server`, `ui`, `mcp`, `drive-upload`.
- **MCP**: `automation_file_mcp` (`automation_file.server.mcp_server:_cli`) or
  `python -m automation_file mcp [--allowed-actions ...]`. It is a standard-library JSON-RPC stdio
  server whose tools come from the registry (`tools_from_registry`).
- **TCP server**: `start_autocontrol_socket_server(host="localhost", port=9943, allow_non_loopback=False, shared_secret=None, action_acl=None)`
  returns a `TCPActionServer`. With a secret, clients prefix the payload with `AUTH <secret>\n`.
  `quit_server` shuts it down. Replies end with `Return_Data_Over_JE\n`.
- **HTTP server**: `start_http_action_server` returns an `HTTPActionServer` (default `127.0.0.1:9944`)
  with `POST /actions` and `GET /healthz`, `/readyz`, `/openapi.json`, `/progress`. Auth is an
  optional `Bearer` token.
- **Other servers**: `start_web_ui` (default port 9955) and `start_metrics_server` (`/metrics`,
  default port 9945).
- **GUI**: `launch_ui()`, `python -m automation_file ui` or `python main_ui.py`.
- **Plugins**: third-party packages register actions through the entry-point group `automation_file.actions`.

## 4. Main flows

**Action list → result**

```
JSON file / --execute_str / Python → ActionExecutor.execute_action(list|dict, validate_first, dry_run, substitute)
  → _coerce (list or {"auto_control": [...]}) → _execute_event → registry.resolve(name)
  → FA_* callable in local/ | remote/ | utils/ | core/ (inside tracing.action_span)
  → {"execute: <action>": return value | repr(error)}   (one failure never aborts the batch)
```

**Remote transports**

```
start_autocontrol_socket_server / start_http_action_server → ensure_loopback (unless allow_non_loopback=True)
  → TCP (AUTH <secret> + JSON) | HTTP POST /actions (Bearer) → ActionACL check → shared executor
MCP host → automation_file_mcp (stdio JSON-RPC) → tools/call → MCPServer registry (optionally --allowed-actions)
```

**Registry construction**

```
ActionExecutor() → build_default_registry(): local + http + utils + drive commands
  → _register_cloud_backends (register_<backend>_ops) → trigger / scheduler / progress / notify ops
  → _load_plugins (entry points; may override built-ins)
  → executor adds FA_execute_action, FA_execute_files, FA_execute_action_parallel, FA_validate
```

## 5. Extension points

- **New local or utility action**: function in `local/<x>_ops.py` (or `utils/`, `core/`) using
  `from __future__ import annotations`, `FileAutomationException` subclasses and `file_automation_logger`
  → `"FA_<name>"` in `_local_commands()` or `_utils_commands()` (`core/action_registry.py`) → export
  from `automation_file/__init__.py` and `__all__` → `tests/test_<module>.py` (plus `tests/test_facade.py`
  when exported).
- **New remote backend**, in this order:
  1. `remote/<backend>/` with `client.py` (module singleton `<backend>_instance` with `later_init`,
     plus `close` where relevant), the `*_ops.py` modules, and `register_<backend>_ops(registry)` in `__init__.py`.
  2. Call it from `_register_cloud_backends`.
  3. Add the SDK to `dependencies` in both `stable.toml` and `dev.toml`, then add facade exports.
  4. Add `ui/tabs/<backend>_tab.py` and wire it into `ui/tabs/transfer_tab.py`.
  5. Add tests; paths that need the network are not exercised in CI.
- **Outbound HTTP**: always call `validate_http_url` (`remote/url_validator.py`) first.
- **Plugins**: an entry point in the group `automation_file.actions` (`core/plugins.py`), or
  `add_command_to_executor({...})` at runtime. `package_manager.add_package_to_executor` registers a
  package's members as `<package>_<member>`.
- **CLI subcommand**: `_cmd_<name>` registered in an `_add_*_commands` helper (`__main__.py`). Keep the
  legacy flags and the double decode.
- **New server surface**: reuse `ensure_loopback`, `shared_secret` with `hmac.compare_digest`, and `ActionACL`.

## 6. Cross-project boundaries

- **PyBreeze (subprocess)** runs `python -m automation_file --execute_str <json>` or `--execute_file <path>`
  (`PyBreeze/pybreeze/extend/process_executor/python_task_process_manager.py`; the package name is in
  `.../process_executor/file_automation/file_automation_process.py`). PyBreeze double-encodes the JSON
  on Windows, so `_execute_str`'s `isinstance`-guarded second decode and the legacy flag names are a
  contract, guarded by `tests/test_legacy_cli_contract.py`. PyBreeze also declares `automation-file` as
  a dependency.
- **TestPioneer** imports `download_file` and `unzip_all` from the facade in-process
  (`test_pioneer/executor/file/file_processing.py`). Its `parallel_run` does not spawn this package.
- **Names inherited from AutoControl**: the TCP starter is still called `start_autocontrol_socket_server`
  and the action-dict key is `auto_control`; MailThunder uses the same name and key. MailThunder's
  socket-server default port (9944) equals this package's HTTP-server default.
- **Wire format**: TCP replies end with the same `Return_Data_Over_JE` terminator as the sibling servers.
- **Builtins policy**: the default registry contains no Python builtins; only `PackageLoader` can add
  them. In the siblings, APITestka uses an explicit allowlist, LoadDensity a `_UNSAFE_BUILTINS`
  blacklist, and MailThunder registers every builtin (known gap).

## 7. Design constraints

- Only the three action shapes in §3. Extend through the registry, not by subclassing the executor.
  Python 3.10+, `X | Y` unions, `from __future__ import annotations` (CLAUDE.md § Conventions).
- Exceptions derive from `FileAutomationException`. Log through `file_automation_logger`; no
  `print()` diagnostics and no runtime `assert` (§ Conventions; § Code quality › Logging, printing, assertions).
- Every user-supplied URL goes through `validate_http_url`. Never `verify=False`. Downloads have size
  and time caps and do not follow redirects (§ Security › Network requests (SSRF prevention) / (TLS)).
- Servers bind loopback unless `allow_non_loopback=True`; secrets are compared with `hmac.compare_digest`;
  TCP reads one `recv(8192)` payload; HTTP bodies are capped at 1 MB (§ Security › TCP server; › HTTP server).
- Resolve user paths through `safe_join` / `is_within` (§ Security › Path traversal). SFTP keeps
  `paramiko.RejectPolicy()` (§ Security › SFTP host verification).
- `retry_on_transient` retries only the listed exception types (§ Security › Reliability (retry / quota)).
  `PackageLoader` is eval-grade; never expose it remotely (§ Security › Plugin / package loading).
- No `shell=True`; subprocesses use argument lists and a timeout (§ Security › General rules; › Subprocess execution).
- Backends and PySide6 are first-class runtime dependencies. Keep `stable.toml` and `dev.toml`
  dependencies in sync, and let the publish workflow bump versions (§ Branching & CI).
- Limits: cyclomatic complexity ≤ 15 (hard cap 20), cognitive complexity ≤ 15, functions ≤ 75 lines,
  ≤ 7 parameters, nesting ≤ 4, files ≤ 1000 lines (§ Code quality › Complexity & size).
- Run `ruff check`, `ruff format --check`, `mypy` and `pytest` before committing (§ Development).
  Development PRs target `dev`; stable PRs target `main` (§ Commit & PR rules).

## 8. When to update this file

- A top-level subpackage, backend or server module is added, removed or renamed.
- CLI flags, subcommands, `[project.scripts]` in the TOMLs, or the entry-point group change.
- The action format, the `auto_control` key, the registry build order, or plugin override semantics change.
- Server defaults (host, port, auth, ACL, terminator) or HTTP routes change.
- A §6 contract changes: PyBreeze invocation, the Windows double decode, the facade names TestPioneer uses.
- A CLAUDE.md section referenced in §7 is renamed or its rule changes.
- Refresh the "Last verified" line whenever this file is re-checked against HEAD.
