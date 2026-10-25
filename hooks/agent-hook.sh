#!/usr/bin/env bash
# git-timelog coding-agent hook: log session activity (start, prompt, stop, end).
# Works with Claude Code, Codex, Gemini CLI and Cursor: reads the hook JSON on stdin
# and appends one line to the event log. Never blocks the agent.
{
  data="${GIT_TIMELOG_HOME:-$HOME/.local/share/git-timelog}"
  in=$(cat)
  ev=$(jq -r '.hook_event_name // empty' <<<"$in")
  sid=$(jq -r '.session_id // .conversation_id // empty' <<<"$in")
  cwd=$(jq -r '.cwd // .workspace_roots[0] // empty' <<<"$in")
  case "$ev" in
    SessionStart|sessionStart) what=start ;;
    UserPromptSubmit|BeforeAgent|beforeSubmitPrompt) what=prompt ;;
    Stop|AfterAgent|stop) what=stop ;;
    SessionEnd|sessionEnd) what=end ;;
    *) what="" ;;
  esac
  if [ -n "$what" ] && [ -n "$sid" ] && [ -n "$cwd" ]; then
    # main checkout's name (shared by worktrees); the folder name when not inside a repo
    common=$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
    if [ -n "$common" ]; then
      repo=$(basename "$(dirname "$common")"); branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
    else
      repo=$(basename "$cwd"); branch=""
    fi
    if [ "$what" = prompt ] && [ ! -e "$data/sessions/$sid" ]; then  # the first prompt names the task
      mkdir -p "$data/sessions" && : > "$data/sessions/$sid"
      title=$(jq -r '.prompt // ""' <<<"$in" | tr '\t\r\n' '   ' | sed 's/  */ /g; s/^ //; s/ $//' | cut -c1-80)
      what="prompt|$title"
    fi
    mkdir -p "$data"
    printf '%s\tagent\t%s\t%s\t%s\t%s\n' "$(date +%s)" "$repo" "$branch" "$sid" "$what" >> "$data/events.log"
  fi
} 2>/dev/null
# Cursor waits for a JSON answer on prompt submission; the others ignore an empty reply.
[ "$ev" = beforeSubmitPrompt ] && echo '{"continue": true}'
exit 0
