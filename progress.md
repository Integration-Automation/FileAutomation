# progress.md: FileAutomation

Outstanding work only. When an item is done, delete it in the same commit and add a `#done` entry to `docs/updates/` (format and query commands: `docs/updates/README.md`). No finished items, no history, no rules (rules live in `CLAUDE.md`).
Item numbers (`#n`) are never reused. Tags: [DECIDE] needs the owner's decision, [BLOCKED] waits on something else, [UNVERIFIED] observed but not confirmed.
Cross-repo and workspace items live in `D:\Codes\progress.md` (relevant here: X-12, X-13).

## Open

Items #10 to #26 are what is left of the 1.0 roadmap (`docs/FILEAUTOMATION-1.0-ROADMAP.md`, PR #107, not on `dev` yet), in the order its §20 recommends. The storage core is done (U-20261008-01).

### Architecture and packaging (roadmap M1)

- **#10** [DECIDE] Optional extras. Roadmap §3 wants a light base install with the SDKs and the GUI under `[s3]`, `[gdrive]`, `[azure]`, `[dropbox]`, `[sftp]`, `[ftp]`, `[webdav]`, `[smb]`, `[fsspec]`, `[gui]`, `[all]`, `[test]`. `CLAUDE.md` › Branching & CI and `architecture.md` §7 say the opposite: the backends and PySide6 are first-class runtime dependencies and must not move under extras. PyBreeze declares `automation-file` and gets the GUI and the SDKs through it (`architecture.md` §6), so moving them breaks it unless it asks for `[all]` in the same round. Decide which rule wins and whether `automation_file_dev` follows.
- **#11** [DECIDE] Public API policy and deprecation policy (roadmap M1, M9): which names are frozen at 1.0 and how a name is retired. The storage layer is documented as provisional until then.
- **#12** `import automation_file` loads `requests`, `cryptography`, `watchdog`, `googleapiclient`, `google.auth`, `google_auth_oauthlib`, `prometheus_client`, `opentelemetry`, `tqdm` and `defusedxml` at module level, because the facade imports every module. Roadmap §3 requires that the base package imports no optional SDK at import time. `boto3`, `azure`, `dropbox`, `paramiko`, `PySide6`, `pyarrow`, `msal` and `boxsdk` are already lazy. What counts as optional depends on #10.

### Universal storage layer (roadmap M2)

- **#13** Storage adapters over the existing clients, each in `storage/<name>_storage.py` with a `StorageContract` class against a fake client: S3 (`s3://bucket/key`), Azure Blob (`azure://container/blob`), Dropbox (`dropbox:///path`), SFTP (`sftp://host/path`), FTP and FTPS, WebDAV, SMB (`smb://server/share/path`), fsspec. The object stores set `capabilities.directories=False` and override `_walk` with one flat listing. A session backend must refuse a URI whose host is not the one it is connected to; `SFTPClient` does not keep its host today. `tests/test_storage_imports.py` then needs the client modules on its allowlist.
- **#14** Google Drive adapter (`gdrive://`). Drive addresses files by ID and allows two files of one name in a folder, so the path-to-ID lookup and the duplicate-name rule have to be designed first.
- **#15** [DECIDE] The eleventh backend slot, and whether OneDrive and Box are promoted to the storage contract or documented as action-only (roadmap §4).
- **#16** Cross-backend operations through the layer: `copy_between` / `FA_copy_between` on `File.copy_to`, and `FA_storage_*` actions. `copy_between` accepts `local:<path>`, `sftp:/path`, `s3:bucket/key` and http(s) sources today; `parse_storage_uri` rejects the first three as ambiguous, so the action needs a translation step to stay compatible.
- **#17** Streams and directory trees: `open()` or chunked reads and writes (`read_bytes` holds the whole file in memory, and the default `checksum` stages a full local copy of a remote file), directory copy and sync through the layer, and a backend's native checksum where it has one.
- **#18** [UNVERIFIED] The five symbolic-link tests of `tests/test_storage_local.py` have not run anywhere: the development machine may not create links (they skip there), CI's Windows runners may. Read the first CI run of the branch and fix `LocalStorage` if one fails.

### Backend integration tests (roadmap M3)

- **#19** Integration environments for the contract suite in CI: MinIO, Azurite, SFTP, FTP/FTPS, WebDAV and Samba, plus credential-gated jobs for the cloud adapters, and Linux and macOS legs (`ci-dev.yml` runs pytest on Windows only). Needs #13.
- **#20** Failure cases in the contract suite: access denied, transient failures mapped to `StorageTransientException` and retried, metadata kept where the backend supports it. Only `LocalStorage` has permission-error tests today (`tests/test_storage_local.py`).

### Later milestones

- **#21** IntegrityMonitor 2.0 (roadmap §6, M4): snapshot and manifest schema with a version, baseline management, change detection over `FileInfo`, watch and continuous modes, alert and audit hooks, opt-in remediation. `core/fim.py` and `core/manifest.py` are the starting point; build it on the storage layer.
- **#22** Pipeline runtime (roadmap §7, M5): `Pipeline` domain model, DAG runtime v2 with retry, timeout, cancellation, conditions, idempotency, checkpoint and resume, dry run, execution history, and versioned YAML/JSON definitions with schema validation. `core/dag_executor.py` is the starting point.
- **#23** Scheduler, events, notifications and audit (roadmap §8 to §10, M6): one scheduler with cron (time-zone aware), manual, file-event, webhook and pipeline-dependency triggers; an event model that drives a `NotificationRouter`; audit schema v2 with correlation IDs behind a storage interface.
- **#24** UI 2.0 (roadmap §11, M7). Not before the APIs of #13 to #23 are stable (roadmap §20).
- **#25** Semantic MCP tools (roadmap §12, M8): `file_*`, `storage_*`, `pipeline_*`, `integrity_status`, `audit_search`, with a permission model and dry run, next to the existing `FA_*` bridge.
- **#26** Release engineering and 1.0 (roadmap §13, M9): contract and integration tests in the PR gate, PyPI Trusted Publishing, SemVer, migration guide, API freeze.

### Found on the way

- **#27** The three `usage/cloud.rst` pages (`docs/source/Eng`, `Zh-TW`, `Zh-CN`) show a `FA_cross_copy` action with `src` / `dst` and a `drive://` prefix. Neither exists: the action is `FA_copy_between(source, target)` and `remote/cross_backend.py` has no `drive` scheme. The READMEs were corrected in `bc13101`; these pages were not. Fix them with #16, which rewrites that section anyway.
- **#28** Five tests of `tests/test_versioning.py` fail on a machine with a long temp directory (`FileNotFoundError: [WinError 206]`, the file name or extension is too long): `FileVersioner` names a version directory after the whole source path (`C__sep__Users__sep__...`), so the path roughly doubles and passes Windows' 260-character limit. Seen on `a0dd11f` before any change of this branch; the suite passes where the temp path is shorter (U-20261001-11). A real source file with a long path fails the same way.
