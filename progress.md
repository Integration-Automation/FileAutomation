# progress.md: FileAutomation

Outstanding work only. When an item is done, delete it in the same commit and add a `#done` entry to `docs/updates/` (format and query commands: `docs/updates/README.md`). No finished items, no history, no rules (rules live in `CLAUDE.md`).
Item numbers (`#n`) are never reused. Tags: [DECIDE] needs the owner's decision, [BLOCKED] waits on something else, [UNVERIFIED] observed but not confirmed.
Cross-repo and workspace items live in `D:\Codes\progress.md` (relevant here: X-12, X-13).

## Open

Items #10 to #26 are what is left of the 1.0 roadmap (`docs/FILEAUTOMATION-1.0-ROADMAP.md`, PR #107, not on `dev` yet), in the order its §20 recommends. The storage core is done (U-20261008-01).

### Architecture and packaging (roadmap M1)

- **#11** [DECIDE] Public API policy and deprecation policy (roadmap M1, M9): which names are frozen at 1.0 and how a name is retired. The storage layer is documented as provisional until then.

### Universal storage layer (roadmap M2)

- **#16** `copy_between` / `FA_copy_between` on `File.copy_to`. The `FA_storage_*` actions exist (U-20261008-03), so the layer is reachable from action lists; the older action still has its own dispatcher in `remote/cross_backend.py`. `copy_between` accepts `local:<path>`, `sftp:/path`, `s3:bucket/key` and http(s) sources today; `parse_storage_uri` rejects the first three as ambiguous, so the action needs a translation step to stay compatible.
- **#17** Native streams and checksums for the remote backends. `open_read` / `open_write`, `copy_tree` and `sync_tree` exist (U-20261008-04), but outside `LocalStorage` a stream is a staged local copy and the default `checksum` downloads the file: S3 could read `get_object()["Body"]`, and a backend with a server-side digest could answer `checksum` from it.
- **#31** `FsspecStorage(directories=False)`: a `<dir>/` placeholder key that another tool wrote survives `delete(dir, recursive=True)`, so the directory still exists afterwards, and an empty directory that only a placeholder holds cannot be deleted at all. `ObjectStorage` removes placeholders because it lists raw keys; through fsspec the key has to be addressed with the filesystem's own call, and `_strip_protocol` of s3fs / gcsfs removes a trailing slash, so `rm_file(path + "/")` is probably wrong. Needs a real s3fs or gcsfs (MinIO under #19) before it is written.
- **#32** [UNVERIFIED] No storage adapter has met a real service: FTP ran against an in-memory model of RFC 959 / 3659 and FTPS data channels did not run at all; SFTP met paramiko's own server, not OpenSSH; Microsoft Graph (`OneDriveClient.graph_send`), Drive (the discovery document as a transport), Dropbox, WebDAV and SMB met stand-ins, and the `smbprotocol` error shapes were written from its documentation. The hand-written redirect handling of `WebDAVClient` (U-20261008-14) has not met a server that redirects. Run each against the service (#19) and fix what differs.
- **#18** [UNVERIFIED] The five symbolic-link tests of `tests/test_storage_local.py` have not run anywhere: the development machine may not create links (they skip there), CI's Windows runners may. Read the first CI run of the branch and fix `LocalStorage` if one fails.

### Backend integration tests (roadmap M3)

- **#19** Integration environments for the contract suite in CI: MinIO and Azurite (`S3Storage` and `AzureStorage` have only met stand-in clients and, for S3, botocore's Stubber; no request has reached a real service), SFTP, FTP/FTPS, WebDAV and Samba, plus credential-gated jobs for the cloud adapters, and Linux and macOS legs (`ci-dev.yml` runs pytest on Windows only). The adapters exist (U-20261008-12); what each has not met is listed in #32.
- **#20** Metadata cases in the contract suite: user metadata and content type kept across an upload and a copy where `capabilities` says the backend supports them. The failure cases exist (U-20261008-10): a backend's contract class gets them by providing the `break_storage` fixture, as the local, S3 and Azure classes do.

### Later milestones

- **#21** IntegrityMonitor 2.0 (roadmap §6, M4): snapshot and manifest schema with a version, baseline management, change detection over `FileInfo`, watch and continuous modes, alert and audit hooks, opt-in remediation. `core/fim.py` and `core/manifest.py` are the starting point; build it on the storage layer.
- **#22** Pipeline runtime (roadmap §7, M5): `Pipeline` domain model, DAG runtime v2 with retry, timeout, cancellation, conditions, idempotency, checkpoint and resume, dry run, execution history, and versioned YAML/JSON definitions with schema validation. `core/dag_executor.py` is the starting point.
- **#23** Scheduler, events, notifications and audit (roadmap §8 to §10, M6): one scheduler with cron (time-zone aware), manual, file-event, webhook and pipeline-dependency triggers; an event model that drives a `NotificationRouter`; audit schema v2 with correlation IDs behind a storage interface.
- **#24** UI 2.0 (roadmap §11, M7). Not before the APIs of #13 to #23 are stable (roadmap §20).
- **#25** Semantic MCP tools (roadmap §12, M8): `file_*`, `storage_*`, `pipeline_*`, `integrity_status`, `audit_search`, with a permission model and dry run, next to the existing `FA_*` bridge.
- **#26** Release engineering and 1.0 (roadmap §13, M9): contract and integration tests in the PR gate, PyPI Trusted Publishing, SemVer, migration guide, API freeze.

### Packaging follow-ups

- **#29** [BLOCKED] PyBreeze has to declare `automation-file[all]` before the stable release that splits the extras reaches users, or it installs without the SDKs it relied on. The change exists on PyBreeze's local branch `deps/automation-file-all-extra` (one commit on its `origin/dev`: `dev.toml`, `pyproject.toml`, `requirements.txt`), not pushed: it waits for someone to open the PR there and for PyBreeze's own update log. PyBreeze's checkout was on `docs/tutorials` with other work, so nothing else was touched.
