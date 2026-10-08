# progress.md: FileAutomation

Outstanding work only. When an item is done, delete it in the same commit and add a `#done` entry to `docs/updates/` (format and query commands: `docs/updates/README.md`). No finished items, no history, no rules (rules live in `CLAUDE.md`).
Item numbers (`#n`) are never reused. Tags: [DECIDE] needs the owner's decision, [BLOCKED] waits on something else, [UNVERIFIED] observed but not confirmed.
Cross-repo and workspace items live in `D:\Codes\progress.md` (relevant here: X-12, X-13).

## Open

Items #10 to #26 are what is left of the 1.0 roadmap (`docs/FILEAUTOMATION-1.0-ROADMAP.md`, PR #107, not on `dev` yet), in the order its §20 recommends. The storage core is done (U-20261008-01).

### Architecture and packaging (roadmap M1)


### Universal storage layer (roadmap M2)

- **#17** Native streams and checksums for the remote backends. `open_read` / `open_write`, `copy_tree` and `sync_tree` exist (U-20261008-04), but outside `LocalStorage` a stream is a staged local copy and the default `checksum` downloads the file: S3 could read `get_object()["Body"]`, and a backend with a server-side digest could answer `checksum` from it.
- **#31** `FsspecStorage(directories=False)`: a `<dir>/` placeholder key that another tool wrote survives `delete(dir, recursive=True)`, so the directory still exists afterwards, and an empty directory that only a placeholder holds cannot be deleted at all. `ObjectStorage` removes placeholders because it lists raw keys; through fsspec the key has to be addressed with the filesystem's own call, and `_strip_protocol` of s3fs / gcsfs removes a trailing slash, so `rm_file(path + "/")` is probably wrong. Needs a real s3fs or gcsfs (MinIO under #19) before it is written.
- **#32** [UNVERIFIED] No storage adapter has met a real service: FTP ran against an in-memory model of RFC 959 / 3659 and FTPS data channels did not run at all; SFTP met paramiko's own server, not OpenSSH; Microsoft Graph (`OneDriveClient.graph_send`), Drive (the discovery document as a transport), Dropbox, WebDAV and SMB met stand-ins, and the `smbprotocol` error shapes were written from its documentation. The hand-written redirect handling of `WebDAVClient` (U-20261008-14) has not met a server that redirects. Run each against the service (#19) and fix what differs.
- **#18** [UNVERIFIED] The five symbolic-link tests of `tests/test_storage_local.py` have not run anywhere: the development machine may not create links (they skip there). The Linux and macOS jobs of `integration.yml` can; read their first run and fix `LocalStorage` if one fails.

### Backend integration tests (roadmap M3)

- **#19** [UNVERIFIED] `.github/workflows/integration.yml` and `tests/integration/` (U-20261008-23) have never run: there is no Docker on the development machine. The first run of the workflow decides whether each of the six service jobs (`s3`, `azure`, `sftp`, `ftp`, `webdav`, `smb`) and the two platform jobs (Linux, macOS) work. Expect to adjust the container options in `tests/integration/start_service.sh` (image tags are floating; pin them to digests once a run is green; the Samba share options and the FTP passive ports are the least certain) and to fix what a real service or another platform shows (#32, #18). Still missing: credential-gated jobs for Google Drive, OneDrive and Dropbox, which have no emulator, and FTPS.
- **#20** Metadata cases in the contract suite: user metadata and content type kept across an upload and a copy where `capabilities` says the backend supports them. The failure cases exist (U-20261008-10): a backend's contract class gets them by providing the `break_storage` fixture, as the local, S3 and Azure classes do.

### Later milestones

- **#23** Scheduler v2 (roadmap §8, the open half of M6): one scheduler with cron (time-zone aware), manual, file-event, webhook and pipeline-dependency triggers, run states and overlap protection, reading a pipeline's `schedule`. The event model, the `NotificationRouter` and audit schema v2 are done (U-20261008-05, U-20261008-17); the scheduler in `scheduler/` still dispatches action lists on its own cron loop.
- **#24** UI 2.0 (roadmap §11, M7). Not before the APIs of #13 to #23 are stable (roadmap §20).
- **#25** Semantic MCP tools (roadmap §12, M8): `file_*`, `storage_*`, `pipeline_*`, `integrity_status`, `audit_search`, with a permission model and dry run, next to the existing `FA_*` bridge.
- **#26** Release engineering and 1.0 (roadmap §13, M9). Done: semantic versioning with a way to release a MINOR or MAJOR (U-20261008-24), the public API policy (U-20261008-22), a package-build check and the integration workflow next to the PR checks. Open: the migration guide and the final documentation audit (after the scheduler, MCP and GUI work lands); making the integration jobs required once they are green (#19); the 1.0.0 release itself, which is the owner's call: write `1.0.0` in both TOMLs in the release pull request.
- **#35** [UNVERIFIED] One full run of the suite on 2026-10-08 reported `1 failed, 4882 passed` and four runs around it passed. The machine was running three other test suites at the time, and the run was not started with `-rf`, so the test is not known. A test that depends on timing is the likely cause (the pipeline timeout and cancellation cases, the integrity watchers, the SFTP loopback, the scheduler). Run the suite with `-rf` under load, or read the first CI runs, to find it.
- **#34** [BLOCKED] PyPI Trusted Publishing (roadmap §13). `publish.yml` and `publish-dev` still upload with the `PYPI_API_TOKEN` secret. Switching needs the owner to add a trusted publisher for each project on PyPI (`automation_file`: workflow `publish.yml`; `automation_file_dev`: workflow `ci-dev.yml`; an environment name if one is wanted) before the workflows can drop the token for `id-token: write` and `pypa/gh-action-pypi-publish`. Changing the workflows first would break both channels.

### Packaging follow-ups

- **#29** [BLOCKED] PyBreeze has to declare `automation-file[all]` before the stable release that splits the extras reaches users, or it installs without the SDKs it relied on. The change exists on PyBreeze's local branch `deps/automation-file-all-extra` (one commit on its `origin/dev`: `dev.toml`, `pyproject.toml`, `requirements.txt`), not pushed: it waits for someone to open the PR there and for PyBreeze's own update log. PyBreeze's checkout was on `docs/tutorials` with other work, so nothing else was touched.
