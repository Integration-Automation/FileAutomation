# docs/updates: update log index

`progress.md` holds only work that is **not done yet**. Everything that *was* done (what changed, measured numbers, decisions, snapshots) is recorded here: **one batch file per month**, one entry per piece of work, each entry with a fixed-format ID and tags, and one row per entry in the index below.

> No TODOs here. If an entry mentions something still open, it only points to it (e.g. "open item: `progress.md` #3"); the item itself lives in `progress.md`.

## How to query

Run from the repository root:

| To find | Command |
|---|---|
| every entry, one line each | `rg -n "^## U-2" docs/updates` |
| entries of one type | `rg -n "^## U-2.*#done" docs/updates` |
| entries with a topic tag | `rg -n "^## U-2.*#<tag>" docs/updates` |
| one day or one month | `rg -n "^## U-202609" docs/updates` |
| the full text of one entry | `rg -n -A 60 "^## U-20260922-01" docs/updates` |
| any keyword | `rg -n "keyword" docs/updates` |

Without `rg`: `git grep -n "^## U-2" -- docs/updates`, or in PowerShell `Select-String -Path docs/updates/*.md -Pattern '^## U-2'`.

## Entry format

```markdown
## U-YYYYMMDD-NN · YYYY-MM-DD · one-line title · #type #topic

- **What**: ...
- **Result / numbers**: ...
- **Files**: `path` ...
- **Evidence**: commit, file:line, link ...
- **Open items**: none / see `progress.md` ...
```

- **ID**: `U-` + date + two-digit sequence for that day. IDs are never renumbered or reused, so code comments and other documents can cite them.
- **Type tag** (exactly one): `#done` finished `progress.md` item, `#snapshot` measurement or inventory, `#decision`, `#incident`, `#migration`, `#docs`, `#release`.
- Topic tags are free-form (`#mcp`, `#wayland`, ...).
- Keep conclusions, numbers, files and evidence; drop the reasoning trail and dead ends.

## Batch rules

1. One file per month: `docs/updates/YYYY-MM.md`. Append new entries at the end.
2. Over about 800 lines, continue in `YYYY-MM-b.md` (then `-c`) and list it in the batch table below.
3. **Claim the ID under a lock.** Several sessions may write this log at the same time (for example parallel autonomous runs), and without a lock two of them pick the same number:
   1. `mkdir docs/updates/.id-lock`. Creating a directory is atomic, so only one writer succeeds. If it already exists, someone else is claiming: wait a few seconds and retry. A lock older than 10 minutes is stale and may be removed.
   2. Find the day's last number with `rg -n "^## U-YYYYMMDD" docs/updates` and write the heading line and the index row.
   3. `rmdir docs/updates/.id-lock`, then fill in the body. Git never tracks the empty lock directory.
   4. Before committing, `rg -c "^## U-<your ID>" docs/updates` must report one match in total. If not, renumber your entry under the lock and fix its index row. Whoever merges a branch renumbers entries that reuse an ID.
4. **One line per index row**: title only (about 60 characters), no summary.
5. Never rewrite a recorded entry. Correct it with a new `#decision` or `#incident` entry and add "→ corrected in U-..." to the old one.

## When a `progress.md` item is done

In the same commit: delete the item from `progress.md`, add a `#done` entry here that names it, and add its index row.

---

## Index (newest first)

| ID | Date | Title | Tags | Batch |
|---|---|---|---|---|
| U-20261008-32 | 2026-10-08 | An intermittent test failure, and its wrong first diagnosis | #tests #incident | [2026-10](2026-10.md) |
| U-20261008-31 | 2026-10-08 | Migration guide | #docs #migration #roadmap | [2026-10](2026-10.md) |
| U-20261008-30 | 2026-10-08 | UI 2.0 and the application layer | #ui #roadmap #done | [2026-10](2026-10.md) |
| U-20261008-29 | 2026-10-08 | Scheduler v2 | #scheduler #roadmap #done | [2026-10](2026-10.md) |
| U-20261008-28 | 2026-10-08 | One positioning in the READMEs, the manuals and the metadata | #docs #packaging #roadmap | [2026-10](2026-10.md) |
| U-20261008-27 | 2026-10-08 | Semantic MCP tools | #mcp #security #roadmap #done | [2026-10](2026-10.md) |
| U-20261008-26 | 2026-10-08 | Production deployment guide | #docs #roadmap | [2026-10](2026-10.md) |
| U-20261008-25 | 2026-10-08 | Metadata cases in the storage contract | #storage #tests #done | [2026-10](2026-10.md) |
| U-20261008-24 | 2026-10-08 | A release can raise MINOR or MAJOR | #release #ci #roadmap | [2026-10](2026-10.md) |
| U-20261008-23 | 2026-10-08 | Integration tests and their workflow | #ci #tests #roadmap | [2026-10](2026-10.md) |
| U-20261008-22 | 2026-10-08 | Public API and deprecation policy | #decision #docs #roadmap #done | [2026-10](2026-10.md) |
| U-20261008-21 | 2026-10-08 | copy_between runs on the storage layer | #storage #roadmap #done | [2026-10](2026-10.md) |
| U-20261008-20 | 2026-10-08 | CLI subcommands for integrity, pipelines and the audit trail | #cli #roadmap #done | [2026-10](2026-10.md) |
| U-20261008-19 | 2026-10-08 | The action ACL and the MCP server check nested action names | #security #incident | [2026-10](2026-10.md) |
| U-20261008-18 | 2026-10-08 | Pipeline runtime | #pipeline #roadmap #done | [2026-10](2026-10.md) |
| U-20261008-17 | 2026-10-08 | Notification router and audit schema v2 | #notify #audit #roadmap | [2026-10](2026-10.md) |
| U-20261008-16 | 2026-10-08 | IntegrityMonitor 2.0 | #integrity #roadmap #done | [2026-10](2026-10.md) |
| U-20261008-15 | 2026-10-08 | The SFTP, OneDrive and SMB clients name the extra to install | #packaging #done | [2026-10](2026-10.md) |
| U-20261008-14 | 2026-10-08 | The WebDAV client only talks to its own server | #security #incident | [2026-10](2026-10.md) |
| U-20261008-13 | 2026-10-08 | A move between two views of one store could delete the file | #storage #incident | [2026-10](2026-10.md) |
| U-20261008-12 | 2026-10-08 | Storage adapters for eight more backends | #storage #roadmap #done | [2026-10](2026-10.md) |
| U-20261008-11 | 2026-10-08 | A storage subcommand for the CLI | #storage #cli #roadmap | [2026-10](2026-10.md) |
| U-20261008-10 | 2026-10-08 | Failure cases join the storage contract | #storage #roadmap #tests | [2026-10](2026-10.md) |
| U-20261008-09 | 2026-10-08 | Backend SDKs and the GUI toolkit become extras | #done #packaging #roadmap #decision | [2026-10](2026-10.md) |
| U-20261008-08 | 2026-10-08 | Three architecture diagrams still listed drive:// | #incident #docs | [2026-10](2026-10.md) |
| U-20261008-07 | 2026-10-08 | The cloud pages describe FA_copy_between, not FA_cross_copy | #done #docs | [2026-10](2026-10.md) |
| U-20261008-06 | 2026-10-08 | Event model, event bus and storage observers | #events #roadmap #storage | [2026-10](2026-10.md) |
| U-20261008-05 | 2026-10-08 | Streams and directory trees in the storage layer | #storage #roadmap #streams | [2026-10](2026-10.md) |
| U-20261008-04 | 2026-10-08 | Version directories stay short for long source paths | #done #versioning #windows | [2026-10](2026-10.md) |
| U-20261008-03 | 2026-10-08 | FA_storage_* actions put the storage layer in the registry | #storage #roadmap #actions #mcp | [2026-10](2026-10.md) |
| U-20261008-02 | 2026-10-08 | S3 and Azure Blob behind the storage layer | #storage #roadmap #s3 #azure | [2026-10](2026-10.md) |
| U-20261008-01 | 2026-10-08 | Universal storage layer: contract, URIs, local and memory | #storage #roadmap #tests | [2026-10](2026-10.md) |
| U-20261001-11 | 2026-10-01 | The publish jobs build with the locked setuptools | #done #ci #security #X-13 | [2026-10](2026-10.md) |
| U-20261001-10 | 2026-10-01 | The publish jobs install hash-locked build tools | #done #ci #security #deps | [2026-10](2026-10.md) |
| U-20261001-09 | 2026-10-01 | The source distributions stop carrying the tests | #done #packaging #tests | [2026-10](2026-10.md) |
| U-20261001-08 | 2026-10-01 | The wheels stop installing the test suite | #done #packaging #tests | [2026-10](2026-10.md) |
| U-20261001-07 | 2026-10-01 | CI publishes automation_file_dev from the dev branch | #release #ci #X-13 | [2026-10](2026-10.md) |
| U-20261001-06 | 2026-10-01 | The TCP server moves to je_action_core | #migration #socket-server #L-6 | [2026-10](2026-10.md) |
| U-20261001-05 | 2026-10-01 | X-12: no action command loads packages, so the gate stays off | #decision #security #X-12 | [2026-10](2026-10.md) |
| U-20261001-04 | 2026-10-01 | je_action_core comes from PyPI | #done #build #L-6 | [2026-10](2026-10.md) |
| U-20261001-03 | 2026-10-01 | Registry, executor pipeline and helpers move to je_action_core | #migration #executor #L-6 | [2026-10](2026-10.md) |
| U-20261001-02 | 2026-10-01 | Workflow-timeout test failed CI lint (ruff B905) | #incident #ci | [2026-10](2026-10.md) |
| U-20261001-01 | 2026-10-01 | Every workflow job has a timeout | #ci #tests | [2026-10](2026-10.md) |
| U-20260925-03 | 2026-09-25 | Python classifiers list every version CI tests | #packaging #tests | [2026-09](2026-09.md) |
| U-20260925-02 | 2026-09-25 | License metadata uses the SPDX expression in both channels | #packaging | [2026-09](2026-09.md) |
| U-20260925-01 | 2026-09-25 | Dependabot waits 7 days before proposing a new release | #ci #security #deps | [2026-09](2026-09.md) |
| U-20260924-02 | 2026-09-24 | Keep checkout credentials only in the job that pushes | #ci #security | [2026-09](2026-09.md) |
| U-20260924-01 | 2026-09-24 | Move CI to Node 24 actions pinned by commit | #ci #security #deps | [2026-09](2026-09.md) |
| U-20260923-11 | 2026-09-23 | cryptography and sphinx floors from Dependabot | #done #deps | [2026-09](2026-09.md) |
| U-20260923-10 | 2026-09-23 | Release 0.0.48 after Codacy's six findings | #done #release #ci | [2026-09](2026-09.md) |
| U-20260923-09 | 2026-09-23 | Five floors from the Dependabot PRs on main; the PRs closed | #done #deps | [2026-09](2026-09.md) |
| U-20260923-08 | 2026-09-23 | dev CI green again: format check and mypy | #done #ci | [2026-09](2026-09.md) |
| U-20260923-07 | 2026-09-23 | Stale release/bump-v0.0.32 branch deleted | #done #housekeeping | [2026-09](2026-09.md) |
| U-20260923-06 | 2026-09-23 | cryptography floor 50 and msal 1.39 | #done #deps #security | [2026-09](2026-09.md) |
| U-20260923-05 | 2026-09-23 | Box backend moves to box_sdk_gen (boxsdk 10) | #done #deps #box | [2026-09](2026-09.md) |
| U-20260923-04 | 2026-09-23 | Port clash with MailThunder resolved on MailThunder's side | #done #docs | [2026-09](2026-09.md) |
| U-20260923-03 | 2026-09-23 | FileAutomation.log moves out of the working directory | #done #logging | [2026-09](2026-09.md) |
| U-20260923-02 | 2026-09-23 | CLAUDE.md matches the code again | #done #docs | [2026-09](2026-09.md) |
| U-20260923-01 | 2026-09-23 | Dependency floors raised; Dependabot on dev; boxsdk 10 refused | #done #deps #ci | [2026-09](2026-09.md) |
| U-20260922-05 | 2026-09-22 | Contract test for the legacy CLI flags | #done #tests | [2026-09](2026-09.md) |
| U-20260922-04 | 2026-09-22 | Point project URLs at the current repository | #done #metadata | [2026-09](2026-09.md) |
| U-20260922-03 | 2026-09-22 | Delete four merged local branches and fast-forward main | #done #housekeeping | [2026-09](2026-09.md) |
| U-20260922-02 | 2026-09-22 | Stop tracking .idea/ | #done #housekeeping | [2026-09](2026-09.md) |
| U-20260922-01 | 2026-09-22 | Adopt progress/architecture/docs-updates rules | #docs #migration | [2026-09](2026-09.md) |

## Batches

| File | Period | Entries |
|---|---|---:|
| [2026-10.md](2026-10.md) | 2026-10 | 43 |
| [2026-09.md](2026-09.md) | 2026-09 | 21 |
