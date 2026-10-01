# progress.md: FileAutomation

Outstanding work only. When an item is done, delete it in the same commit and add a `#done` entry to `docs/updates/` (format and query commands: `docs/updates/README.md`). No finished items, no history, no rules (rules live in `CLAUDE.md`).
Item numbers (`#n`) are never reused. Tags: [DECIDE] needs the owner's decision, [BLOCKED] waits on something else, [UNVERIFIED] observed but not confirmed.
Cross-repo and workspace items live in `D:\Codes\progress.md` (relevant here: X-12, X-13).

## Open

- **#8** Both wheels install the test suite as a top-level `tests` package next to `automation_file`: `find = { namespaces = false }` (`stable.toml:71`, `dev.toml:73`) has no `include`, and `tests/__init__.py` makes `tests` a package (the `automation_file` 0.0.51 wheel on PyPI lists both in `top_level.txt`). Limit discovery to `automation_file*` in both TOMLs together (`tests/test_dev_toml_parity.py` compares the table) and check the built wheel.
