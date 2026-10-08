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
- **#32** [UNVERIFIED] Adapters that have still not met their real service: Google Drive, OneDrive (Microsoft Graph, `OneDriveClient.graph_send`) and Dropbox met stand-ins only; S3 met S3Mock, not AWS; FTPS data channels have not run. SFTP (OpenSSH), FTP (vsftpd), WebDAV (Apache), SMB (Samba) and Azure Blob (Azurite) pass the contract in CI. `SMBClient` with a port other than 445 fails in listing and directory creation: smbprotocol drops the `port` argument in some of its calls, so the CI server listens on 445; confirm against smbprotocol and either pass the port another way or document that only 445 works.

### Backend integration tests (roadmap M3)

- **#19** Integration workflow, what is left after its first green run (U-20261008-33): pin the six container images to digests (they are pulled by floating tag); credential-gated jobs for Google Drive, OneDrive and Dropbox, which have no emulator; an FTPS run; and the real S3 API, since the S3 job runs against S3Mock (MinIO's image can no longer be pulled without an account).
- **#36** Writing metadata through the storage layer. `upload`, `write_bytes` and `open_write` take no user metadata and no content type, so `stat().metadata` can be read but a caller cannot set it, and the content type is always the one guessed from the name. The contract checks what is read (U-20261008-25). Adding it means a keyword on the write operations, a capability-conditional contract case, and deciding what a backend without metadata does with the argument (refuse, or ignore).

### Later milestones

- **#38** [UNVERIFIED] UI 2.0 (U-20261008-30) has only run on Qt's offscreen platform. Open it on a real display (`python -m automation_file ui`) and check: text fit and layout of the ten pages, dragging a node and adding a task on the pipeline canvas, selecting two tasks and connecting them, the file dialogs, the confirmation boxes, the keyboard shortcuts, and one page against a real backend. Dragging from node to node to connect two tasks is not built.
- **#39** The application layer reaches into two private places: `StorageService` reads `StorageResolver._mounts` / `_factories` (give the resolver a public listing of its mounts), and `app/` uses `pipeline.definition.retry_from_dict`, `graph.upstream_tasks`, `substitution.is_name` / `NAME_RULE` and `model.ON_SUCCESS` / `WHEN_CHOICES`, which are not in `automation_file.pipeline.__all__` (export them, or give the pipeline package the functions the editor needs).
- **#37** Storage-layer gaps the MCP work found (U-20261008-27) and did not change: (a) a `LocalStorage(root)` listing reports a link's name and its target's metadata without a containment check, although reading through the link is refused; (b) `StorageBackend` has no ranged read, so reading the head of a large remote file stages all of it; (c) `LocalStorage` on Windows opens device names (`CON`, `NUL`) and alternate data streams, which the MCP tools refuse themselves; (d) a link on an SFTP or FTP server leads outside a root that is only a path prefix.
- **#26** The 1.0.0 release (roadmap M9). Everything the roadmap lists is on the branch `feat/universal-storage-layer`; what is left is the owner's: review and merge the pull request to `dev`, read the first CI and integration runs (#19, #32, #18, #38), decide the 1.0 date, then write `1.0.0` in `stable.toml` and `dev.toml` in the release pull request to `main` and raise the `Development Status` classifier. Not written: a separate security page in the manual (the deployment chapter and `CLAUDE.md` § Security carry that guidance today).
- **#40** [DECIDE] SonarCloud fails pull request #109 on one condition, the security rating of new code: eight findings, all on the two `pip install` steps of the two jobs in `.github/workflows/integration.yml` (`S8541` no `--only-binary :all:`, `S8544` versions not locked). The `pytest`, `minimal` and `extras` jobs of `ci-dev.yml` install the same way and are not flagged only because their lines are not new. Either accept the findings in SonarCloud, or lock the test dependencies for every job: a `test.in` / `test.txt` pair next to `.github/requirements/publish.in`, generated with `uv pip compile` for the platforms the jobs run on, and `pip install --require-hashes --only-binary :all:` in each job. The lock could not be generated on the development machine (no `uv`, and a network too slow to resolve every extra).
- **#34** [BLOCKED] PyPI Trusted Publishing (roadmap §13). `publish.yml` and `publish-dev` still upload with the `PYPI_API_TOKEN` secret. Switching needs the owner to add a trusted publisher for each project on PyPI (`automation_file`: workflow `publish.yml`; `automation_file_dev`: workflow `ci-dev.yml`; an environment name if one is wanted) before the workflows can drop the token for `id-token: write` and `pypa/gh-action-pypi-publish`. Changing the workflows first would break both channels.

### Packaging follow-ups

- **#29** [BLOCKED] PyBreeze has to declare `automation-file[all]` before the stable release that splits the extras reaches users, or it installs without the SDKs it relied on. The change exists on PyBreeze's local branch `deps/automation-file-all-extra` (one commit on its `origin/dev`: `dev.toml`, `pyproject.toml`, `requirements.txt`), not pushed: it waits for someone to open the PR there and for PyBreeze's own update log. PyBreeze's checkout was on `docs/tutorials` with other work, so nothing else was touched.
