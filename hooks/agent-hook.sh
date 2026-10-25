#!/usr/bin/env bash
# git-timelog coding-agent hook: log session activity (start, prompt, stop, end).
# Works with Claude Code, Codex, Gemini CLI and Cursor: reads the hook JSON on stdin
# and appends one line to the event log. Never blocks the agent. Needs jq.
data="${GIT_TIMELOG_HOME:-$HOME/.local/share/git-timelog}"
{
  # one jq call reads everything we need (tabs/newlines in the prompt become spaces)
  IFS=$'\t' read -r ev sid cwd title < <(jq -r '[
      .hook_event_name // "",
      (.session_id // .conversation_id // ""),
      (.cwd // .workspace_roots[0] // ""),
      ((.prompt // "") | gsub("[\t\r\n ]+"; " ") | ltrimstr(" ") | .[0:80] | rtrimstr(" "))
    ] | @tsv')
  case "$ev" in
    SessionStart|sessionStart) what=start ;;
    UserPromptSubmit|BeforeAgent|beforeSubmitPrompt) what=prompt ;;
    Stop|AfterAgent|stop) what=stop ;;
    SessionEnd|sessionEnd) what=end ;;
    *) what="" ;;
  esac
  if [ -n "$what" ] && [ -n "$sid" ] && [ -n "$cwd" ]; then
    # one git call: main checkout (shared by worktrees) and current branch
    { read -r common; read -r branch; } < <(git -C "$cwd" rev-parse --path-format=absolute \
        --git-common-dir --abbrev-ref HEAD 2>/dev/null)
    if [ -n "$common" ]; then
      repo=$(basename "$(dirname "$common")"); [ "$branch" = HEAD ] && branch=""
    else
      repo=$(basename "$cwd"); branch=""
    fi
    # Only folders git-timelog tracks are written down (list kept up to date by git-timelog).
    if [ ! -f "$data/tracked-repos" ] || grep -qxF "$repo" "$data/tracked-repos"; then
      if [ "$what" = prompt ] && [ ! -e "$data/sessions/$sid" ]; then  # the first prompt names the task
        mkdir -p "$data/sessions" && : > "$data/sessions/$sid"
        [ -e "$data/no-titles" ] && title=""
        what="prompt|$title"
      fi
      mkdir -p "$data"
      printf '%s\tagent\t%s\t%s\t%s\t%s\n' "$(date +%s)" "$repo" "$branch" "$sid" "$what" >> "$data/events.log"
    fi
  fi
} < <(cat) 2>/dev/null
# Cursor waits for a JSON answer on prompt submission; the others ignore an empty reply.
[ "$ev" = beforeSubmitPrompt ] && echo '{"continue": true}'
exit 0
