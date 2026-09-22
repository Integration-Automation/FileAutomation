# progress.md: FileAutomation

Outstanding work only. When an item is done, delete it in the same commit and add a `#done` entry to `docs/updates/` (format and query commands: `docs/updates/README.md`). No finished items, no history, no rules (rules live in `CLAUDE.md`).
Item numbers (`#n`) are never reused. Tags: [DECIDE] needs the owner's decision, [BLOCKED] waits on something else, [UNVERIFIED] observed but not confirmed.
Cross-repo and workspace items live in `D:\Codes\progress.md` (relevant here: X-6, X-16).

## Open

- **#1** Add `.codacy_tmp/` to `.gitignore` (five analysis scratch files sit untracked in the tree).
- **#2** `CLAUDE.md` is stale: ≈:99 says CI runs Python 3.10–3.12 (it runs 3.10–3.14), and the Architecture section does not mention WebDAV, SMB, the MCP server, the DAG runner or notify.
- **#3** Five dependabot branches are unmerged (boxsdk, cryptography, msal, opentelemetry-sdk, pyarrow; 2026-06-01..24), as is `origin/release/bump-v0.0.32` (workspace X-16).
- **#5** The HTTP action server's default port 9944 is also MailThunder's socket-server default. `CLAUDE.md` still says "nine tabs" and that the HTTP server handles only `POST /actions`; `architecture.md` describes the code as it is.
