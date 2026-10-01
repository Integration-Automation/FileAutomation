# progress.md: FileAutomation

Outstanding work only. When an item is done, delete it in the same commit and add a `#done` entry to `docs/updates/` (format and query commands: `docs/updates/README.md`). No finished items, no history, no rules (rules live in `CLAUDE.md`).
Item numbers (`#n`) are never reused. Tags: [DECIDE] needs the owner's decision, [BLOCKED] waits on something else, [UNVERIFIED] observed but not confirmed.
Cross-repo and workspace items live in `D:\Codes\progress.md` (relevant here: X-12, X-13).

## Open

- **#9** [DECIDE] The publish jobs still fetch the build backend unpinned. `python -m build` (`.github/workflows/ci-dev.yml:98`, `.github/workflows/publish.yml:74`) creates an isolated environment and installs `setuptools>=77` from `[build-system] requires` (`stable.toml:3`, `dev.toml:5`) at whatever version is newest, outside `.github/requirements/publish.txt`. Closing it means adding `setuptools` to `publish.in` and building with `python -m build --no-isolation`, or pointing the isolated install at a hash-locked constraints file. The other repositories locked under workspace X-13 build the same way.
