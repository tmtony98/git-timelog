# git timelog

**Your git history is already a timesheet.**

`git timelog` is a time tracker you never have to start. Every branch becomes a task,
every checkout and commit becomes a data point, and a local dashboard shows where your
hours went. No account, no cloud, no browser extension, no Electron app.

![Dashboard: task board with hours per branch](docs/dashboard.jpg)

![Hours per day and activity feed](docs/chart.jpg)

## Why

Time trackers like Clockify or Toggl only work if you remember to press start.
Developers already leave a precise trail of what they worked on and when: it's called git.
`git timelog` reads that trail.

- **Zero effort.** Git hooks record branch switches, commits and merges as they happen.
- **Branches are tasks.** `feat/login` shows up on the board the first time you touch it.
  When a PR is merged (GitHub, GitLab or Bitbucket merge commits), the task moves to *done*.
- **Private.** Everything stays in a SQLite file on your machine.
- **Tiny.** One Python file, standard library only. Nothing to `pip install`.
- **No background process.** On Linux, systemd holds the port and starts the dashboard
  only when you open it; it exits after 10 idle minutes. Hooks add ~1 ms to a git command.
- **Daily standup notes.** A Markdown note per day (Obsidian-friendly) with what you committed,
  hours per task and what's in progress.

## Install

Requires `git` and `python3` (3.8+). Linux with systemd gets the on-demand dashboard and the
scheduled standup note; macOS and others run the dashboard with `git timelog serve`.

```sh
git clone https://github.com/tmtony98/git-timelog.git
cd git-timelog
./install.sh
```

Then, in each repository you want to track:

```sh
cd ~/code/my-app
git timelog init          # installs hooks and imports the last 30 days
git timelog open          # http://localhost:7777
```

Because the command is named `git-timelog`, git exposes it as a subcommand: `git timelog`.

## Usage

```sh
git timelog ls                         # open tasks with hours (--all for done)
git timelog log 45m "code review"      # add time to the current branch
git timelog log "Sprint planning" 1h   # add time to a named task
git timelog add "Design review"        # a task that isn't a branch
git timelog start / stop               # manual timer (current branch by default)
git timelog status feat/login review   # todo | doing | review | done
git timelog set feat/login ticket WEB-142
git timelog report                     # write today's standup note
git timelog repos | remove             # list or stop tracking repos
```

On the dashboard you can drag cards between columns, start timers, log time and attach a
ticket or PR link.

## How time is estimated

Events are walked in time order. The gap between two events is credited to the branch that
was checked out during it, as long as the gap is under 2 hours. After a longer gap a new
session starts, and its first commit gets a 30 minute lead-in. This is the same idea as
[git-hours](https://github.com/kimmobrunfeldt/git-hours), applied to checkouts as well as
commits.

It's an estimate: long stretches of uncommitted work are undercounted. Use `git timelog log`
or the timer to correct it. Manual time is added on top of git time.

## Configuration

`~/.config/git-timelog/config.ini` (all optional):

```ini
[git-timelog]
author =                       ; default: each repo's user.email
base_branches = main,master,develop,dev,staging,prod,release/*
session_gap_min = 120
lead_in_min = 30
stale_days = 7                 ; idle branches are marked done after backfill
idle_exit_min = 10
port = 7777                    ; re-run install.sh with PORT=... to change the socket
standup_dir = ~/Documents/git-timelog/standups
title = git timelog
```

Point `standup_dir` into your Obsidian vault to get notes there.

## Where things live

| What | Path |
|---|---|
| Command | `~/.local/bin/git-timelog` |
| Data (SQLite + hook event log) | `~/.local/share/git-timelog/` |
| Config | `~/.config/git-timelog/config.ini` |
| systemd units | `~/.config/systemd/user/git-timelog*` |
| Hooks | one line appended to `post-checkout`, `post-commit`, `post-merge` in each tracked repo |

Existing hooks are kept; `git timelog` adds a single marked line and `git timelog remove`
takes it out again. If a repo sets `core.hooksPath` to a folder inside the project
(Husky and similar), `init` doesn't touch those files and prints the one line to add yourself.

## Try it without your own data

```sh
GIT_TIMELOG_HOME=/tmp/gtl-demo git timelog demo
GIT_TIMELOG_HOME=/tmp/gtl-demo git timelog serve --port 7788
```

## Uninstall

```sh
./uninstall.sh            # removes command, hooks and services; keeps your data
./uninstall.sh --purge    # also deletes data and config
```

## Development

```sh
python3 -m unittest discover tests
```

The tests run the real CLI against throwaway git repositories.

## License

MIT
