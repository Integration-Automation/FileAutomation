# FileAutomation Architecture

> Short overview for people and agents.
> Last verified: 2026-09-22 against `2e6c0ec` on `dev`.

## 1. Purpose

FileAutomation (`automation_file`) is an automation-first library for local file, directory and
archive operations, SSRF-checked HTTP downloads, and remote storage (Google Drive, S3, Azure Blob,
Dropbox, SFTP, FTP, OneDrive, Box, plus SMB and WebDAV clients). Every operation is an `FA_*`
command in one `ActionRegistry`, so JSON action lists run the same way in-process, from files, from
the CLI, over loopback TCP or HTTP servers, as MCP tools, or from the PySide6 GUI.

Next to the actions, `automation_file.storage` is the universal storage layer: one URI syntax, one
`StorageBackend` contract and one error hierarchy, used through `File` and `Storage`. It is the first
piece of the 1.0 roadmap (`docs/FILEAUTOMATION-1.0-ROADMAP.md`, PR #107); what is still open is in `progress.md`.

## 2. Layers and directories

| Path | Responsibility |
| --- | --- |
| `automation_file/__init__.py` | Public facade (`__all__`). Wires the shared `executor`, `callback_executor` and `package_manager` over one registry. `launch_ui` is loaded lazily through `__getattr__` |
| `automation_file/__main__.py`, `cli_storage.py` | CLI: legacy flags plus subcommands; `cli_storage.py` holds the `storage` subcommand |
| `automation_file/core/` | Engine, on je_action_core: `action_registry.py` (`ActionRegistry`, a `CommandRegistry`; `build_default_registry`), `action_executor.py` (`ActionExecutor`, an `ActionExecutor` with strict actions, indexed records and the dry-run, validate, substitute and parallel extras; shared `executor`), `callback_executor.py`, `package_loader.py`, `plugins.py`, `dag_executor.py`, `action_queue.py`, `json_store.py`, `substitution.py`. Also cross-cutting helpers: `optional` (`require_module`, the extras table), `retry`, `quota`, `rate_limit`, `circuit_breaker`, `file_lock`, `sqlite_lock`, `checksum`, `manifest`, `crypto`, `secrets`, `config`, `config_watcher`, `audit`, `metrics`, `tracing`, `progress`, `fim`, `content_store` |
| `automation_file/local/` | Local strategy modules: file, dir, zip, tar and archive ops, sync, diff, text/JSON/data edits, templates, versioning, trash, `shell_ops` (argv-only subprocess), conditional branches. `safe_paths.py` guards against path traversal |
| `automation_file/remote/` | `url_validator.py` (SSRF guard), `http_download.py`, `cross_backend.py`, `fsspec_bridge.py`. One subpackage per backend: `google_drive/`, `s3/`, `azure_blob/`, `dropbox_api/`, `sftp/`, `ftp/`, `onedrive/`, `box/`, each with `client.py`, `*_ops.py` and `register_<backend>_ops`. `smb/` and `webdav/` have a client only |
| `automation_file/storage/` | Universal storage layer. `uri.py` (`StorageURI`, `parse_storage_uri`, `normalize_path`), `types.py` (`FileInfo`, `Checksum`, `StorageCapabilities`), `backend.py` (`StorageBackend`: the public operations are template methods over the `_`-prefixed primitives a backend supplies), `local_storage.py` (`LocalStorage`, confined through `safe_join` when given a root), `memory_storage.py` (`MemoryStorage`), `object_storage.py` (`ObjectStorage`: directories as key prefixes over `_head`, `_scan`, `_put`, `_get`, `_remove`), `s3_storage.py` (`S3Storage`, over `s3_instance` or a given boto3 client), `azure_storage.py` (`AzureStorage`, over `azure_blob_instance` or a given `BlobServiceClient`), `resolver.py` (`StorageResolver`, `default_resolver`: mounts first, then scheme factories), `file.py` (`File`), `storage.py` (`Storage`), `observe.py` (listeners for `upload`, `download`, `read`, `delete`, `mkdir`, `copy`, `move`), `streams.py` (staged file objects behind `open_read` / `open_write`), `tree.py` (`copy_tree`, `sync_tree`, `TreeResult`), `actions.py` (the `FA_storage_*` functions and `register_storage_ops`). At module level it imports only `exceptions`, `logging_config`, `core.checksum` and `local.safe_paths`: no registry, no GUI, no backend SDK. The adapters import their SDK's exceptions and the shared client inside the functions that use them |
| `automation_file/events/` | The event model every component reports through. `model.py` (`Event`, `Severity`, the ten core events), `bus.py` (`EventBus`, the process-wide `event_bus`, `emit`), `context.py` (`correlation_scope`, `actor_scope`), `storage_bridge.py` (failed storage operations become `StorageError` events; installed when the package is imported). It imports only the standard library, `logging_config` and `storage.observe` |
| `automation_file/server/` | `tcp_server.py`, `http_server.py`, `mcp_server.py`, `web_ui.py`, `metrics_server.py`, `action_acl.py` (`ActionACL`), `network_guards.py` (`ensure_loopback`) |
| `automation_file/client/` | `HTTPActionClient` for the HTTP action server |
| `automation_file/trigger/`, `scheduler/`, `notify/` | Watchdog file triggers, cron scheduler, notification sinks. Each registers its own `FA_*` ops |
| `automation_file/project/` | `ProjectBuilder`, `create_project_dir` |
| `automation_file/ui/` | PySide6 GUI: `launcher.launch_ui`, `main_window.MainWindow`, `worker.ActionWorker`, `log_widget.LogPanel`, `tabs/` (backend panels are grouped under `TransferTab`) |
| `automation_file/utils/` | File discovery, fast find, grep, duplicate finder, backup rotation |
| `automation_file/exceptions.py`, `logging_config.py` | `FileAutomationException` hierarchy; `file_automation_logger` (INFO+ to stderr, DEBUG+ to `$FILE_AUTOMATION_LOG_FILE` or `~/.automation_file/logs/FileAutomation.log`, opened on first use) |
| `stable.toml`, `dev.toml` | Packaging for `automation_file` and `automation_file_dev`. No `pyproject.toml` is committed; CI and the publish jobs write one of these TOMLs into place. Apart from the name, version and description they say the same thing (`tests/test_dev_toml_parity.py`) |
| `MANIFEST.in` | Keeps `tests/` out of both source distributions (`tests/test_sdist_manifest.py`); package discovery in the TOMLs already keeps it out of the wheels |
| `scripts/dev_release.py` | Release helper for the dev channel (standard library only): picks the next `automation_file_dev` version from PyPI and tells whether the built wheel differs from the newest published one |
| `.github/requirements/publish.in`, `publish.txt` | The tools of the two publish jobs (`build`, `twine`, and the build backend `setuptools`) and their hash-locked resolution for Python 3.12 on Linux. `publish.in` holds the `uv pip compile` command that regenerates `publish.txt`; Dependabot reads the directory |
| `main_ui.py` | Development shortcut for `launch_ui()` |
| `tests/`, `docs/`, `examples/mcp/` | pytest suite (fixtures in `tests/conftest.py`); Sphinx docs; MCP host configuration example |

## 3. Entry points and public interfaces

- **Python facade** (`import automation_file`): `execute_action`, `execute_files`,
  `execute_action_parallel`, `validate_action`, `execute_action_dag`, `add_command_to_executor`,
  `executor`, `callback_executor`, `package_manager`, `ActionRegistry`, `build_default_registry`,
  `driver_instance` (Google Drive), `start_autocontrol_socket_server`, `start_http_action_server`,
  `HTTPActionClient`, `MCPServer`, `create_project_dir`, `launch_ui` (lazy).
- **Storage layer** (same facade): `File`, `Storage`, `StorageBackend`, `StorageResolver`, `StorageURI`,
  `parse_storage_uri`, `FileInfo`, `Checksum`, `StorageCapabilities`, `LocalStorage`, `MemoryStorage`,
  `ObjectStorage`, `S3Storage`, `AzureStorage`, and
  `StorageException` with its nine subclasses. Storage URIs are `<scheme>://<authority>/<path>`; the built-in
  schemes are `local` (alias `file`), `memory`, `s3` and `azure` (alias `az`), and text without `://` is a local path. `s3://` and `azure://` use the shared `s3_instance` / `azure_blob_instance`. The API is
  provisional until 1.0. Sixteen `FA_storage_*` actions (`exists`, `stat`, `list`, `mkdir`, `upload`,
  `download`, `delete`, `checksum`, `verify`, `copy`, `move`, `read_text`, `write_text`, `copy_tree`,
  `sync`, `schemes`) put
  it in the default registry; `register_storage_ops` adds them to another one.
- **Events** (same facade): `Event`, `Severity`, `EventBus`, `event_bus`, `emit`, `correlation_scope`,
  `actor_scope`, and the core events `PipelineStarted`, `PipelineCompleted`, `PipelineFailed`,
  `TaskStarted`, `TaskCompleted`, `TaskFailed`, `IntegrityViolation`, `StorageError`, `SchedulerError`,
  `SystemErrorEvent`. Event `type` names (`pipeline.failed`, ...) and the payload keys in
  `events.model.PAYLOAD_KEYS` are what consumers match on.
- **Action format**: an action is `[name]`, `[name, {kwargs}]` or `[name, [args]]`. A file holds a
  list of actions or `{"auto_control": [...]}`.
- **CLI** (`python -m automation_file`; no console script for it):
  - legacy flags `-e/--execute_file`, `-d/--execute_dir`, `-c/--create_project` and `--execute_str`.
    `_execute_str` decodes a second time when the first `json.loads` yields a string;
  - subcommands `zip`, `unzip`, `download`, `create-file`, `server`, `http-server`, `ui`, `mcp`, `drive-upload`;
  - `storage` with its own subcommands `ls`, `stat`, `cat`, `cp`, `mv`, `rm`, `mkdir`, `sync`, `checksum`,
    `verify`, `schemes` (`cli_storage.py`): one JSON document per call, and `--init <action list>` to
    initialise a backend's client first.
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
- **PyPI packages**: `automation_file` (stable) and `automation_file_dev` (dev channel), both the same
  import package.
  - Stable: a push to `main` runs `publish.yml`, which bumps both TOMLs, builds from `stable.toml`,
    uploads, and commits and tags the bump.
  - Dev: the `publish-dev` job of `ci-dev.yml` runs after `lint` and `pytest` on a push to `dev`. It
    builds from `dev.toml` and uploads when the commit is still the tip of `dev` and the wheel differs
    from the newest published one. `scripts/dev_release.py` takes the version from PyPI (newest release
    plus one patch, never below the version in `dev.toml`), so nothing is committed back.
  - Both jobs hold the PyPI token and install only the wheels pinned by hash in
    `.github/requirements/publish.txt` (`pip install --require-hashes --only-binary :all:`);
    `tests/test_workflow_actions.py` fails on any other `pip install` in them.
  - Both jobs build with `python -m build --no-isolation`, so the build backend is the locked
    `setuptools` and not a download made at build time. The same test file fails on a build without
    the flag and when the lock does not satisfy `[build-system] requires` of `stable.toml` or `dev.toml`.

## 4. Main flows

**Action list → result**

```
JSON file / --execute_str / Python → ActionExecutor.execute_action(list|dict, validate_first, dry_run, substitute)
  → _coerce (list or {"auto_control": [...]}) → _execute_event → registry.resolve(name)
  → FA_* callable in local/ | remote/ | utils/ | core/ (inside tracing.action_span)
  → {"execute[<index>]: <action>": return value | repr(error)}   (one failure never aborts the batch)
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
  → storage ops (FA_storage_*)
  → _load_plugins (entry points; may override built-ins)
  → executor adds FA_execute_action, FA_execute_files, FA_execute_action_parallel, FA_validate
```

**Storage URI → backend**

```
File(uri) / Storage(uri) → parse_storage_uri (scheme alias, authority check, path normalised, ".." refused)
  → StorageResolver.resolve: longest mount at or above the URI, else the scheme's factory → (backend, path)
  → StorageBackend public method: normalise, check what exists, make parents → _primitive of the backend
  → FileInfo / Checksum / bytes, or a StorageException subclass
copy_to / move_to → target_backend.copy_from(source_backend, ...) → native (_copy_from / _move_from) or a local staging file
every upload / download / read / delete / mkdir / copy / move → storage.observe listeners (StorageOperation)
```

**Event → consumers**

```
component → Event (type, severity, source, subject, payload, correlation_id, actor) → event_bus.publish
  → each matching subscriber, in the publisher's thread; one that raises is logged and skipped
storage.observe → events.storage_bridge → StorageError (only for a failing backend, not a caller mistake)
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
  3. Add the SDK as an extra in both `stable.toml` and `dev.toml` (and to `all`), name it in
     `core.optional.EXTRAS`, import it with `require_module` where it is used, then add facade exports.
  4. Add `ui/tabs/<backend>_tab.py` and wire it into `ui/tabs/transfer_tab.py`.
  5. Add tests; paths that need the network are not exercised in CI.
- **New storage backend** (the universal layer; separate from the `FA_*` backend above):
  1. Subclass `StorageBackend` in `storage/<name>_storage.py`: set `scheme` and `capabilities`, implement
     `_stat`, `_list_dir`, `_upload`, `_download`, `_delete_file`, plus `_mkdir` and `_rmdir` when
     `capabilities.directories` is true. Map the SDK's errors to the `StorageException` subclasses and
     import the SDK lazily. An object store subclasses `ObjectStorage` and implements `_head`, `_scan`,
     `_put`, `_get`, `_remove` instead.
  2. Register its factory in `register_default_schemes` (`storage/resolver.py`), or leave it to callers
     to `Storage.mount(...)` when it needs connection arguments.
  3. Add `tests/test_storage_<name>.py` with a `StorageContract` subclass (`tests/storage_contract.py`);
     every backend passes the same suite.
  4. Export it from `storage/__init__.py` and the facade, and document its URI form in the three
     `usage/storage.rst` pages and the READMEs.
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
  contract, guarded by `tests/test_legacy_cli_contract.py`. PyBreeze declares `automation-file` and, now that the SDKs and the GUI are extras, needs `automation-file[all]` to keep what it had (`progress.md` #29); it lists the package as
  a dependency.
- **TestPioneer** imports `download_file` and `unzip_all` from the facade in-process
  (`test_pioneer/executor/file/file_processing.py`). Its `parallel_run` does not spawn this package.
- **Names inherited from AutoControl**: the TCP starter is still called `start_autocontrol_socket_server`
  and the action-dict key is `auto_control`. MailThunder has renamed both (`start_mail_thunder_socket_server`, `mail_thunder` key) and keeps the old names as deprecated aliases. MailThunder's
  socket-server default is 9942, so it runs next to this package's servers (TCP 9943, HTTP 9944,
  metrics 9945) on their defaults.
- **Wire format**: TCP replies end with the same `Return_Data_Over_JE` terminator as the sibling servers.
- **Builtins policy**: the default registry contains no Python builtins; only `PackageLoader` can add
  them. In the siblings, APITestka registers none, and LoadDensity, MailThunder and WebRunner register the
  same `SAFE_BUILTINS` allowlist.
- **ActionCore (this repo depends on it)**: `je_action_core` (Integration-Automation/ActionCore) holds the registry,
  executor pipeline, package loader, callback executor and JSON files. FileAutomation configures them as follows:
  - **registry**: accepts any callable; a refused one raises `AddCommandException("<name> is not callable")`;
  - **executor**: `StrictActionParser` (its messages are this repo's), `execute[<index>]: <action>` record keys,
    document key `auto_control`, its list messages, and the tracing span through `invoke`;
  - **package loader**: `<package>_<member>` names, import errors logged, gate off, the count returned through
    `check_and_add`;
  - **callback executor**: strict checks, errors raised;
  - **JSON files**: `JSONDecodeError` / `OSError` wrapped on read, `OSError` / `TypeError` on write.

  - **TCP server**: `SecretHeaderRequestHandler` (`AUTH <secret>` first line) on a `TCPActionServer`
    (`ActionTCPServer` with daemon threads and address reuse), the ACL as its `validate` hook, and
    `ReplyMessages` for `<key> -> <value>` lines and the `json error` / `forbidden` / `execution error` /
    `decode error` / `auth error` replies; `ensure_loopback` runs before it starts.

  The extras (dry run, validate, substitute, parallel, metrics) and the HTTP server stay here. It is a PyPI
  dependency (`je_action_core>=0.0.2`); the CI lint job installs it too, so mypy reads its types. ActionCore lists
  FileAutomation in its own §6.

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
- The storage layer does not import the registry, the GUI or a backend SDK at import time. Storage paths
  never contain `..`, storage URIs never carry credentials, `delete` never removes a storage root and
  never follows a symbolic link, and every backend passes `tests/storage_contract.py`.
- `retry_on_transient` retries only the listed exception types (§ Security › Reliability (retry / quota)).
  `PackageLoader` is eval-grade; never expose it remotely (§ Security › Plugin / package loading). No `FA_*`
  command reaches it, so je_action_core's package gate is off here (`tests/test_package_loader.py` fails if one
  is added; workspace X-12).
- No `shell=True`; subprocesses use argument lists and a timeout (§ Security › General rules; › Subprocess execution).
- The base install has no cloud SDK and no GUI toolkit: each lives in an extra and is imported at the
  moment of use through `core.optional.require_module` (`tests/test_optional_dependencies.py`). Keep
  `stable.toml` and `dev.toml` in sync (`tests/test_dev_toml_parity.py`), and let CI number both
  channels: never bump a version by hand (§ Branching & CI).
- Limits: cyclomatic complexity ≤ 15 (hard cap 20), cognitive complexity ≤ 15, functions ≤ 75 lines,
  ≤ 7 parameters, nesting ≤ 4, files ≤ 1000 lines (§ Code quality › Complexity & size).
- Run `ruff check`, `ruff format --check`, `mypy` and `pytest` before committing (§ Development).
  Development PRs target `dev`; stable PRs target `main` (§ Commit & PR rules).

## 8. When to update this file

- A top-level subpackage, backend or server module is added, removed or renamed.
- CLI flags, subcommands, `[project.scripts]` in the TOMLs, or the entry-point group change.
- How either PyPI package is built or published changes.
- The action format, the `auto_control` key, the registry build order, or plugin override semantics change.
- Server defaults (host, port, auth, ACL, terminator) or HTTP routes change.
- The storage URI syntax, the `StorageBackend` contract, the built-in schemes or the resolver order change.
- A §6 contract changes: PyBreeze invocation, the Windows double decode, the facade names TestPioneer uses.
- A CLAUDE.md section referenced in §7 is renamed or its rule changes.
- Refresh the "Last verified" line whenever this file is re-checked against HEAD.
