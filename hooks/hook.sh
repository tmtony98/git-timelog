#!/usr/bin/env bash
# git-timelog hook: append one tab-separated event line. Never fails git.
# Called from .git/hooks/<name> as: hook.sh <hook-name> <git hook args...>
{
  log="${GIT_TIMELOG_HOME:-$HOME/.local/share/git-timelog}/events.log"
  mkdir -p "$(dirname "$log")"
  name=$1; shift
  repo=$(basename "$(git rev-parse --show-toplevel)")
  branch=$(git rev-parse --abbrev-ref HEAD)
  sha=$(git rev-parse --short HEAD)
  case "$name" in
    post-checkout)
      [ "$3" = "1" ] || exit 0            # file checkout, not a branch switch
      prev=$(git rev-parse --abbrev-ref @{-1} 2>/dev/null)
      [ "$prev" = "$branch" ] && exit 0
      kind=checkout; subject="from:$prev" ;;
    post-commit) kind=commit; subject=$(git log -1 --format=%s) ;;
    post-merge)  kind=merge;  subject=$(git log -1 --format=%s) ;;
    *) exit 0 ;;
  esac
  subject=${subject//$'\t'/ }
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date +%s)" "$kind" "$repo" "$branch" "$sha" "$subject" >> "$log"
} 2>/dev/null || true
exit 0
