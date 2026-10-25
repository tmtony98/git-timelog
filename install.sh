#!/usr/bin/env bash
# Install git-timelog for the current user. No root, no dependencies beyond python3 + git.
set -euo pipefail
cd "$(dirname "$0")"

BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
DATA="${GIT_TIMELOG_HOME:-$HOME/.local/share/git-timelog}"
PORT="${PORT:-7777}"
BIN="$BIN_DIR/git-timelog"

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }
command -v git >/dev/null || { echo "git is required" >&2; exit 1; }

mkdir -p "$BIN_DIR" "$DATA/web" "$DATA/hooks"
install -m 755 git-timelog "$BIN"
install -m 644 web/index.html "$DATA/web/index.html"
install -m 755 hooks/hook.sh "$DATA/hooks/hook.sh"
install -m 755 hooks/agent-hook.sh "$DATA/hooks/agent-hook.sh"
echo "installed $BIN"

if command -v systemctl >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then
  UNIT_DIR="$HOME/.config/systemd/user"
  mkdir -p "$UNIT_DIR"
  for f in systemd/*.in; do
    sed -e "s|@BIN@|$BIN|g" -e "s|@PORT@|$PORT|g" "$f" > "$UNIT_DIR/$(basename "${f%.in}")"
  done
  cp systemd/git-timelog-report.timer "$UNIT_DIR/"
  systemctl --user daemon-reload
  systemctl --user enable --now git-timelog.socket git-timelog-report.timer
  echo "dashboard: http://localhost:$PORT (starts on demand, stops when idle)"
  echo "standup note: weekdays 18:30"
else
  echo "systemd not found: run 'git timelog serve' to start the dashboard manually"
fi

case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "note: add $BIN_DIR to your PATH" ;; esac
echo
echo "next: cd into a repo and run 'git timelog init'"
