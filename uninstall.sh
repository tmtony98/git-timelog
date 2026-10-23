#!/usr/bin/env bash
# Remove git-timelog. Your data is kept unless you pass --purge.
set -euo pipefail
BIN="${BIN_DIR:-$HOME/.local/bin}/git-timelog"
DATA="${GIT_TIMELOG_HOME:-$HOME/.local/share/git-timelog}"

if [ -x "$BIN" ]; then
  while read -r repo; do
    [ -d "$repo" ] && "$BIN" remove "$repo" || true
  done < <("$BIN" repos | grep '^/' || true)
fi
if command -v systemctl >/dev/null; then
  systemctl --user disable --now git-timelog.socket git-timelog-report.timer 2>/dev/null || true
  systemctl --user stop git-timelog.service 2>/dev/null || true
  rm -f "$HOME"/.config/systemd/user/git-timelog*
  systemctl --user daemon-reload 2>/dev/null || true
fi
rm -f "$BIN"
if [ "${1:-}" = "--purge" ]; then
  rm -rf "$DATA" "$HOME/.config/git-timelog"
  echo "removed git-timelog and its data"
else
  rm -rf "$DATA/web" "$DATA/hooks"
  echo "removed git-timelog (data kept in $DATA; use --purge to delete)"
fi
