# Contributing to git timelog

Contributions are welcome: bug reports, ideas, docs and code.

## Getting started

```sh
git clone https://github.com/tmtony98/git-timelog.git
cd git-timelog
python3 -m unittest discover tests     # tests run the real CLI against throwaway repos
./git-timelog demo                     # with GIT_TIMELOG_HOME=/tmp/gtl-demo for fake data
GIT_TIMELOG_HOME=/tmp/gtl-demo ./git-timelog serve --port 7788
```

You can run `./git-timelog` straight from the checkout; it finds `web/` and `hooks/` next to itself.

## Principles

Please keep these in mind; PRs that break them are hard to merge:

- **Standard library only.** No `pip install` for users.
- **No always-on process.** Hooks are event-driven; the dashboard starts on demand.
- **Local and private.** Data never leaves the machine unless the user explicitly sends it.
- **Never break git.** Hooks must stay fast and always exit 0.

## Ideas we'd love help with

- VS Code / Cursor extension that sends editor "heartbeats", so uncommitted work is counted
- Ticket IDs detected from branch names (`feat/WEB-142-login` → `WEB-142`)
- CSV export and a weekly report
- Detect every PR merge brought in by `git pull`, not just the latest commit
- JetBrains plugin, Windows support, packaging (Homebrew, AUR, pipx)

Open an issue first for anything big, so we can agree on the approach.

## Pull requests

1. Fork and create a branch (git timelog will track it for you).
2. Add or update tests in `tests/` for behaviour changes.
3. Make sure `python3 -m unittest discover tests` passes.
4. Describe what changed and why in the PR.

By contributing you agree your work is released under the MIT license.
