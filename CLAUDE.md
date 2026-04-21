# FileAutomation

Automation-first Python library for local file / directory / zip operations, HTTP downloads, and Google Drive integration. Actions are defined as JSON and dispatched through a central registry so they can be executed in-process, from disk, or over a TCP socket.

## Architecture

**Layered architecture with Facade + Registry + Command + Strategy patterns:**

```
automation_file/
├── __init__.py                 # Public API facade (every name users import)
├── __main__.py                 # CLI entry (argparse dispatcher)
├── exceptions.py               # Exception hierarchy (FileAutomationException base)
├── logging_config.py           # file_automation_logger (file + stderr handlers)
├── core/
│   ├── action_registry.py      # ActionRegistry — name -> callable (Registry + Command)
│   ├── action_executor.py      # ActionExecutor — runs JSON action lists (Facade + Template Method)
│   ├── callback_executor.py    # CallbackExecutor — trigger then callback composition
│   ├── package_loader.py       # PackageLoader — dynamically registers package members
│   └── json_store.py           # Thread-safe read/write of JSON action files
├── local/                      # Strategy modules — each file is a batch of pure operations
│   ├── file_ops.py
│   ├── dir_ops.py
│   └── zip_ops.py
├── remote/
│   ├── url_validator.py        # SSRF guard for outbound URLs
│   ├── http_download.py        # SSRF-validated HTTP download with size/timeout caps
│   └── google_drive/
│       ├── client.py           # GoogleDriveClient (Singleton Facade)
│       ├── delete_ops.py
│       ├── download_ops.py
│       ├── folder_ops.py
│       ├── search_ops.py
│       ├── share_ops.py
│       └── upload_ops.py
├── server/
│   └── tcp_server.py           # Loopback-only TCP server executing JSON actions
├── project/
│   ├── project_builder.py      # ProjectBuilder (Builder pattern)
│   └── templates.py            # Scaffolding templates
└── utils/
    └── file_discovery.py       # Recursive file listing by extension
```

**Key design patterns in use:**
- **Facade**: `automation_file/__init__.py` re-exports every supported name (`execute_action`, `driver_instance`, `start_autocontrol_socket_server`, …).
- **Registry + Command**: `ActionRegistry` maps action name → callable. JSON action lists are command objects (`[name, kwargs]` / `[name, [args]]` / `[name]`) dispatched through the registry.
- **Template Method**: `ActionExecutor._execute_event` defines the single-action lifecycle (resolve → call → wrap result); `execute_action` is the outer iteration template.
- **Strategy**: Each `local/*_ops.py` and `remote/google_drive/*_ops.py` module is an independent strategy that plugs into the registry.
- **Singleton (module-level)**: `driver_instance`, `executor`, `callback_executor`, `package_manager` are shared instances wired in `__init__.py` so `callback_executor.registry is executor.registry`.
- **Builder**: `ProjectBuilder` assembles the `keyword/` + `executor/` skeleton.

## Key types

- `ActionRegistry` — mutable name → callable mapping. `register`, `register_many`, `resolve`, `unregister`, `event_dict` (live view for legacy callers).
- `ActionExecutor` — holds a registry and runs JSON action lists. `execute_action(list|dict)`, `execute_files(paths)`, `add_command_to_executor(mapping)`.
- `CallbackExecutor` — runs a registered trigger, then a user callback, sharing the executor's registry.
- `PackageLoader` — imports a package by name and registers its top-level functions / classes / builtins as `<package>_<member>`.
- `GoogleDriveClient` — wraps OAuth2 credential loading; exposes `service` lazily. `later_init(token_path, credentials_path)` bootstraps; `require_service()` raises if not initialised.
- `TCPActionServer` — threaded TCP server that deserialises a JSON action list per connection. Defaults to loopback.

## Branching & CI

- `main` branch: stable releases, publishes `automation_file` to PyPI (version in `stable.toml`).
- `dev` branch: development, publishes `automation_file_dev` to PyPI (version in `dev.toml`).
- Keep both TOMLs in sync when bumping.
- CI: GitHub Actions (Windows, Python 3.10 / 3.11 / 3.12) — one matrix workflow per branch: `.github/workflows/ci-dev.yml`, `.github/workflows/ci-stable.yml`.
- CI steps: install deps → `pytest tests/ -v`.

## Development

```bash
python -m pip install -r dev_requirements.txt pytest
python -m pytest tests/ -v --tb=short
python -m automation_file --help
```

**Testing:**
- Unit tests live under `tests/` (pytest). Fixtures in `tests/conftest.py` (`sample_file`, `sample_dir`).
- Tests cover every module in `core/`, `local/`, `remote/url_validator`, `project/`, `server/`, `utils/`, plus a facade smoke test.
- Google Drive / HTTP-download code paths that require real credentials or network access are **not** exercised in CI — only their URL-validation / input-validation guards are.
- Run all tests before submitting changes: `python -m pytest tests/ -v`.

## Conventions

- Python 3.10+ — use `X | Y` union syntax, not `Union[X, Y]`.
- Use `from __future__ import annotations` at the top of every module for deferred type evaluation.
- Exception hierarchy: all custom exceptions inherit from `FileAutomationException`; never `raise Exception(...)` directly.
- Logging: use `file_automation_logger` from `automation_file.logging_config`. Never `print()` for diagnostics.
- Action-list shape: `[name]`, `[name, {kwargs}]`, or `[name, [args]]` — nothing else.
- Delete all unused code — no dead imports, commented-out blocks, unreachable branches, or `_old_`-prefixed names. Git history is the archive.
- Prefer updating the registry over extending the executor class. Plugins register via `add_command_to_executor({name: callable})`.

## Security

All code must follow secure-by-default principles. Review every change against the checklist below.

### General rules
- Never use `eval()`, `exec()`, or `pickle.loads()` on untrusted data.
- Never use `subprocess.Popen(..., shell=True)` — always pass argument lists.
- Never log or display secrets, tokens, passwords, or API keys. OAuth2 tokens handled by `GoogleDriveClient` are kept on disk only at the caller-supplied `token_path`.
- Use `json.loads()` / `json.dumps()` for serialisation — never pickle.
- Validate all user input at system boundaries (CLI args, URL inputs, TCP payloads).

### Network requests (SSRF prevention)
- **All** outbound HTTP requests to user-specified URLs must validate the target first via `automation_file.remote.url_validator.validate_http_url`:
  1. Only `http://` and `https://` schemes — rejects `file://`, `ftp://`, `data:`, `gopher://`.
  2. Resolve the hostname and reject IPs in private / loopback / link-local / reserved / multicast / unspecified ranges.
- `http_download.download_file` calls the validator, uses `allow_redirects=False`, enforces a default 20 MB response cap and 15 s connection timeout, and never downgrades TLS verification.
- Never pass user-supplied URLs directly to `urlopen()` / `requests.*` without the validator.

### Network requests (TLS)
- All HTTPS requests must use default TLS verification — never set `verify=False`.
- No bespoke SSH logic in this project; if added, match PyBreeze's `InteractiveHostKeyPolicy` pattern.

### Subprocess execution
- This library does not spawn subprocesses on the hot path. If you add one, pass argument lists (never `shell=True`), set an explicit `timeout`, and never interpolate user input into a command string.

### TCP server
- `TCPActionServer` binds to `localhost` by default. `start_autocontrol_socket_server(host=…)` raises `ValueError` if the resolved address is not loopback unless `allow_non_loopback=True` is passed explicitly.
- Do not remove the loopback guard to "make it easier to test remotely". The server dispatches arbitrary registry commands; exposing it to the network is equivalent to exposing a Python REPL.
- The server accepts a single JSON payload per connection (`recv(8192)`). Do not raise that limit without also adding a length-framed protocol.
- `quit_server` triggers an orderly shutdown; do not add an administrative bypass that skips the loopback check.

### Google Drive
- Credentials are stored at the caller-supplied `token_path` with `encoding="utf-8"`. Never log or print the token contents.
- `GoogleDriveClient.require_service()` raises rather than silently operating with a `None` service — do not paper over it by catching `RuntimeError` at the call site.

### File I/O
- Always use `pathlib.Path` for path manipulation; never string-concatenate paths with user input.
- Use `with open(...) as f:` for every file operation; close via context manager.
- Always pass `encoding="utf-8"` when reading or writing text.
- Never follow symlinks from untrusted sources — resolve and re-check the parent.
- JSON writes go through `automation_file.core.json_store.write_action_json` which holds a module-level lock.

### Plugin / package loading
- `PackageLoader.add_package_to_executor(package)` registers every function / class / builtin of a package under `<package>_<member>`. Treat it as eval-grade power: never expose it to arbitrary clients (e.g. via the TCP server). If you add a remote plugin-load command, gate it behind an explicit admin flag and authenticated transport.

### Secrets and credentials
- Google OAuth tokens live on disk at the user-supplied path; keep the path out of logs.
- API keys / credentials must come from env vars or caller-supplied paths; never hardcode.

### Dependency security
- Pin dependencies in `requirements.txt` / `dev_requirements.txt`.
- Do not add new dependencies without reviewing their security posture.
- Avoid transitive bloat — prefer stdlib when the alternative is a single-function dependency.

## Code quality (SonarQube / Codacy compliance)

All code must satisfy common static-analysis rules. Review every change against the checklist below.

### Complexity & size
- Cyclomatic complexity per function: ≤ 15 (hard cap 20). Break large branches into helpers.
- Cognitive complexity per function: ≤ 15. Flatten nested `if`/`for`/`try` chains with early returns.
- Function length: ≤ 75 lines of code (excluding docstring / blank lines). Extract helpers past that.
- Parameter count: ≤ 7 per function/method. Use a dataclass when more are needed.
- Nesting depth: ≤ 4 levels. Refactor with early returns instead of pyramids.
- File length: ≤ 1000 lines.

### Exception handling
- Never use bare `except:` — always specify exception types.
- Avoid catching `Exception` / `BaseException` unless immediately logging and re-raising, or running at a top-level dispatcher boundary (the `ActionExecutor.execute_action` loop is one of these — it intentionally records per-action failures without aborting the batch).
- Never `pass` silently inside `except` — log via `file_automation_logger` at minimum.
- Do not `return` / `break` / `continue` inside a `finally` block — it swallows exceptions.
- Custom exceptions must inherit from `FileAutomationException`.
- Use `raise ... from err` (or `raise ... from None`) when re-raising to preserve / suppress the chain explicitly.

### Pythonic correctness
- Compare with `None` using `is` / `is not`, never `==` / `!=`.
- Type checks use `isinstance(obj, T)`, never `type(obj) == T`.
- Never use mutable default arguments — use `None` and initialise inside.
- Prefer f-strings over `%` formatting or `str.format()` (except inside lazy log calls: `logger.info("x=%s", x)`).
- Use context managers for every file / socket / lock.
- Use `enumerate()` instead of `range(len(...))` when the index is needed.
- Use `dict.get(key, default)` over `key in dict and dict[key]`.

### Naming & style (PEP 8)
- `snake_case` for functions, methods, variables, module names.
- `PascalCase` for classes.
- `UPPER_SNAKE_CASE` for module-level constants.
- `_leading_underscore` for protected / internal members.
- Do not shadow built-ins (`id`, `type`, `list`, `dict`, `input`, `file`, `open`, etc.).

### Duplication & dead code
- String literal used 3+ times in the same module → extract a module-level constant.
- Identical 6+ line blocks in 2+ places → extract a helper.
- Remove unused imports, unused parameters, unused local variables, unreachable code after `return` / `raise`.
- No commented-out code blocks — delete them.
- No `TODO` / `FIXME` / `XXX` without an issue reference (`# TODO(#123): …`).

### Logging, printing, assertions
- Never use `print()` for diagnostics in library code — use `file_automation_logger`.
- Use lazy logging (`logger.debug("x=%s", x)`) to avoid eager f-string formatting on hot paths.
- Never use `assert` for runtime validation; `assert` is for tests only.

### Hardcoded values & secrets
- No hardcoded passwords, tokens, API keys, or secrets.
- No hardcoded IPs / hostnames outside of documented `localhost` / loopback defaults.
- Magic numbers (except 0, 1, -1) should be named constants when repeated or non-obvious.

### Boolean & return hygiene
- `return bool(cond)` or `return cond`, not `if cond: return True else: return False`.
- `if x` / `if not x`, not `if x == True` / `if x == False`.
- A function should have a consistent return type.

### Imports
- One import per line; grouped `from x import a, b` is fine.
- Order: stdlib → third-party → first-party (`automation_file.*`) — separated by blank lines.
- No wildcard imports outside `__init__.py` re-exports.
- Max one level of relative import.

### Running the linter
- Before committing any non-trivial change, run `ruff check automation_file/ tests/` locally.
- When adding a `# noqa: RULE`, justify it in the comment — never blanket-disable.

## Commit & PR rules

- Commit messages: short imperative sentence (e.g., "Fix rename_file overwrite bug", "Update stable version").
- Do not mention any AI tools, assistants, or co-authors in commit messages or PR descriptions.
- Do not add `Co-Authored-By` headers referencing any AI.
- PR target: `dev` for development work, `main` for stable releases.
