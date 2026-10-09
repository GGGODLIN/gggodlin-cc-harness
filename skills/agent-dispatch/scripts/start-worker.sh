#!/bin/bash
set -u
set -o pipefail
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
HERE="$(cd "$(dirname "$0")" && pwd)"
fail() {
  printf '%s\n' "$*" >&2
  exit 2
}
[ "$#" -ge 3 ] || fail "usage: start-worker.sh <worker name> <worktree path> <brief file> [--label L] [--model M] [--effort E] [--log-dir D] [--no-watch]"
NAME="$1"
CWD="$2"
BRIEF="$3"
shift 3
LABEL="$NAME"
MODEL="opus[1m]"
EFFORT="high"
LOGDIR=""
WATCH=1
while [ "$#" -gt 0 ]; do
  case "$1" in
    --label)
      [ "$#" -ge 2 ] || fail "missing value for --label"
      LABEL="$2"
      shift 2
      ;;
    --model)
      [ "$#" -ge 2 ] || fail "missing value for --model"
      MODEL="$2"
      shift 2
      ;;
    --effort)
      [ "$#" -ge 2 ] || fail "missing value for --effort"
      EFFORT="$2"
      shift 2
      ;;
    --log-dir)
      [ "$#" -ge 2 ] || fail "missing value for --log-dir"
      LOGDIR="$2"
      shift 2
      ;;
    --no-watch)
      WATCH=0
      shift
      ;;
    *)
      fail "unknown arg $1"
      ;;
  esac
done
[ -d "$CWD" ] || fail "worktree not found: $CWD"
[ -f "$BRIEF" ] || fail "brief not found: $BRIEF"
CWD="$(cd "$CWD" && pwd -P)"
LOGDIR="${LOGDIR:-$(dirname "$BRIEF")/watch-logs}"
mkdir -p "$LOGDIR" || fail "could not create log directory: $LOGDIR"

HERDR_ANY=0
if [ -n "${HERDR_PANE_ID:-}" ] || [ -n "${HERDR_WORKSPACE_ID:-}" ]; then
  HERDR_ANY=1
fi
[ "$HERDR_ANY" -eq 1 ] || fail "no supported parent terminal identity; use Herdr"
[ -n "${HERDR_PANE_ID:-}" ] && [ -n "${HERDR_WORKSPACE_ID:-}" ] || fail "incomplete Herdr parent identity"
BACKEND=herdr

check_json_ok() {
  printf '%s' "$1" | python3 -c 'import json,sys; s=sys.stdin.read().strip();
try:
 d=json.loads(s); raise SystemExit(1 if d.get("ok") is False else 0)
except json.JSONDecodeError:
 raise SystemExit(0)'
}

herdr_parent_is_live() {
  local result
  result=$(herdr pane get "$HERDR_PANE_ID" 2>&1) || return 1
  printf '%s' "$result" | python3 -c 'import json,sys; d=json.load(sys.stdin); p=d.get("result",{}).get("pane",{}); ok=p.get("pane_id")==sys.argv[1] and p.get("workspace_id")==sys.argv[2]; raise SystemExit(0 if ok else 1)' "$HERDR_PANE_ID" "$HERDR_WORKSPACE_ID"
}

herdr_parent_is_live || fail "Herdr parent target is not live: $HERDR_PANE_ID"

cleanup_herdr_tab() {
  [ -n "${1:-}" ] && herdr tab close "$1" >/dev/null 2>&1 || true
}

start_herdr() {
  local main main_identity main_session ws created created_info pane tab started agents session prompt log first_error
  main="$HERDR_PANE_ID"
  ws="$HERDR_WORKSPACE_ID"
  main_identity=$(herdr agent get "$main" 2>&1) || fail "Herdr main identity unavailable: $main_identity"
  main_session=$(printf '%s' "$main_identity" | python3 -c 'import json,sys; d=json.load(sys.stdin); a=d.get("result",{}).get("agent",{}); s=a.get("agent_session",{}).get("value",""); print(s) if a.get("pane_id")==sys.argv[1] and s else sys.exit(1)' "$main") || fail "Herdr main session unavailable: $main_identity"
  if [ -n "${CLAUDE_CODE_SESSION_ID:-}" ] && [ "$main_session" != "$CLAUDE_CODE_SESSION_ID" ]; then
    fail "Herdr main pane belongs to another session"
  fi
  tab=""
  created=$(herdr tab create --workspace "$ws" --cwd "$CWD" --label "$LABEL" --no-focus 2>&1) || fail "$created"
  created_info=$(printf '%s' "$created" | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d.get("result",{}); print(r["root_pane"]["pane_id"] + "\t" + r["tab"]["tab_id"])') || fail "invalid Herdr tab create response: $created"
  IFS=$'\t' read -r pane tab <<< "$created_info"
  [ -n "$pane" ] && [ -n "$tab" ] || fail "Herdr tab create returned no target"
  started=$(herdr agent start "$NAME" --kind claude --pane "$pane" -- --model "$MODEL" --effort "$EFFORT" 2>&1)
  if [ "$?" -ne 0 ]; then
    first_error="$started"
    if printf '%s' "$first_error" | command grep -Eq 'agent_pane_busy|not an available shell'; then
      herdr pane process-info --pane "$pane" >/dev/null 2>&1 || { cleanup_herdr_tab "$tab"; fail "Herdr pane was not ready: $first_error"; }
      started=$(herdr agent start "$NAME" --kind claude --pane "$pane" -- --model "$MODEL" --effort "$EFFORT" 2>&1) || { cleanup_herdr_tab "$tab"; fail "Herdr agent start failed after pane check: $started"; }
    else
      cleanup_herdr_tab "$tab"
      fail "$first_error"
    fi
  fi
  [ -z "$started" ] || check_json_ok "$started" || { cleanup_herdr_tab "$tab"; fail "Herdr agent start returned ok:false: $started"; }
  agents=$(herdr agent list 2>&1) || { cleanup_herdr_tab "$tab"; fail "$agents"; }
  session=$(printf '%s' "$agents" | python3 -c 'import json,sys; d=json.load(sys.stdin); name=sys.argv[1]; pane=sys.argv[2]; xs=[x for x in d.get("result",{}).get("agents",[]) if x.get("name")==name and x.get("pane_id")==pane]; r=xs[0].get("agent_session",{}).get("value","") if xs else ""; print(r) if r else sys.exit(1)' "$NAME" "$pane") || { cleanup_herdr_tab "$tab"; fail "Herdr agent list returned no session for $NAME"; }
  prompt="[main] Read $BRIEF and follow it. Ask your questions in plain text and stop; do not assume answers."
  started=$(herdr agent prompt "$NAME" "$prompt" --wait --until working 2>&1) || { cleanup_herdr_tab "$tab"; fail "prompt failed: $started"; }
  [ -z "$started" ] || check_json_ok "$started" || { cleanup_herdr_tab "$tab"; fail "Herdr prompt returned ok:false: $started"; }
  log="$LOGDIR/$NAME.log"
  if [ "$WATCH" -eq 1 ]; then
    nohup bash "$HERE/agent-watch.sh" herdr "$NAME" "$main" "$log" "$session" "$CWD" "$main_session" "$pane" >/dev/null 2>&1 &
    disown
  fi
  python3 -c 'import json,sys; print(json.dumps({"backend":sys.argv[1],"parent_backend":sys.argv[1],"worker_backend":sys.argv[1],"name":sys.argv[2],"worker_id":sys.argv[3],"parent_id":sys.argv[4],"parent_session_id":sys.argv[9],"pane_id":sys.argv[3],"tab_id":sys.argv[5],"session_id":sys.argv[6],"log":sys.argv[7],"cwd":sys.argv[8]}))' "$BACKEND" "$NAME" "$pane" "$main" "$tab" "$session" "$log" "$CWD" "$main_session"
}

start_herdr
