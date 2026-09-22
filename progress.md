# progress.md: FileAutomation

Outstanding work only. When an item is done, delete it in the same commit and add a `#done` entry to `docs/updates/` (format and query commands: `docs/updates/README.md`). No finished items, no history, no rules (rules live in `CLAUDE.md`).
Item numbers (`#n`) are never reused. Tags: [DECIDE] needs the owner's decision, [BLOCKED] waits on something else, [UNVERIFIED] observed but not confirmed.
Cross-repo and workspace items live in `D:\Codes\progress.md` (relevant here: X-6, X-16).

## Open

- **#1** Add `.codacy_tmp/` to `.gitignore` (five analysis scratch files sit untracked in the tree).
- **#2** `CLAUDE.md` is stale: ≈:99 says CI runs Python 3.10–3.12 (it runs 3.10–3.14), and the Architecture section does not mention WebDAV, SMB, the MCP server, the DAG runner or notify.
- **#3** `origin/release/bump-v0.0.32` is still unmerged (workspace X-16). The five dependabot branches are settled: four floors applied on `dev` and boxsdk refused, see `docs/updates` U-20260923-01.
- **#5** The HTTP action server's default port 9944 is also MailThunder's socket-server default. `CLAUDE.md` still says "nine tabs" and that the HTTP server handles only `POST /actions`; `architecture.md` describes the code as it is.
- **#6** The Box backend (`automation_file/remote/box/client.py`) uses the legacy `boxsdk` 3.x API (`boxsdk.OAuth2`, `boxsdk.Client`), and the distribution's 10.x line ships the module `box_sdk_gen` with a different API, so the `>=3.14.0,<4` cap is load-bearing. Port the client to `box_sdk_gen` (and drop the cap), or write down that the Box backend stays on the 3.x SDK.
