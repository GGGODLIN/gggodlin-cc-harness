#!/usr/bin/env bash
# Threat model: 安全型 gate 只防 agent 忘記在 Figma MCP call 前 invoke skill；判不出來一律 deny。它不承諾 skill 內容已被讀取，也不承諾非 MCP 路徑（REST、curl 等）受到保護。
# Surface：Locked＝本 gate 與 fixture；Editable＝無；Append-only＝無；Human-controlled＝$DISABLED（存在時停用並提示）。
# Locked lifecycle：bootstrap 由一般 commit 與 settings.json 掛載；update 先改檔再跑 fixture；recovery 建立 disabled sentinel；三條路徑都留下 git diff 或 fixture 輸出稽核痕跡。
# Bypass table：改走非 MCP Figma 路徑→不攔；invoke skill 後忽略內容→sentinel 不證明內容；破壞 state/helper→安全型分支 deny。

set -u

INPUT=$(cat)
STATE_DIR=${FIGMA_GATE_STATE_DIR:-$HOME/.claude/hooks/state}
DISABLED=${FIGMA_GATE_DISABLED_SENTINEL:-$STATE_DIR/figma-gate.disabled}
PYTHON=${FIGMA_GATE_PYTHON:-$(command -v python3 2>/dev/null || true)}

json_output() {
  local decision=$1 reason=$2
  if [ -n "$PYTHON" ] && [ -x "$PYTHON" ]; then
    if "$PYTHON" -c 'import json,sys
print(json.dumps({"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":sys.argv[1],"permissionDecisionReason":sys.argv[2]}},separators=(",",":")))' "$decision" "$reason"; then
      return 0
    fi
    printf '%s\n' '[figma-context-budget-gate] could not render hook decision JSON.' >&2
    return 1
  fi
  if [ "$decision" = "allow" ]; then
    printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow","permissionDecisionReason":"[figma-context-budget-gate] gate is disabled or state is already trusted."}}'
  else
    printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"[figma-context-budget-gate] hook runtime unavailable."}}'
  fi
}

pretool_deny() {
  if ! json_output deny "[figma-context-budget-gate] $1"; then
    exit 2
  fi
  exit 0
}

pretool_allow() {
  if ! json_output allow "[figma-context-budget-gate] $1"; then
    exit 2
  fi
  exit 0
}

posttool_fail() {
  printf '%s\n' "[figma-context-budget-gate] $1" >&2
  exit 2
}

safe_id() {
  local value=$1
  [ -n "$value" ] || return 1
  case "$value" in
    .|..|*[!A-Za-z0-9._-]*) return 1 ;;
  esac
}

is_regular_file() {
  local path=$1
  [ ! -L "$path" ] && [ -f "$path" ]
}

state_dir_is_invalid() {
  [ ! -L "$STATE_DIR" ] && [ -d "$STATE_DIR" ] && [ -w "$STATE_DIR" ] || return 0
  return 1
}

prepare_state_dir() {
  umask 077
  if [ ! -e "$STATE_DIR" ] && [ ! -L "$STATE_DIR" ]; then
    mkdir -p "$STATE_DIR" || return 1
  fi
  [ ! -L "$STATE_DIR" ] && [ -d "$STATE_DIR" ] && [ -w "$STATE_DIR" ]
}

json_fields() {
  [ -n "$PYTHON" ] && [ -x "$PYTHON" ] || return 1
  "$PYTHON" -c 'import json,sys
try:
  value=json.loads(sys.stdin.read())
  if not isinstance(value,dict): raise ValueError()
  tool_input=value.get("tool_input",{})
  skill=tool_input.get("skill","") if isinstance(tool_input,dict) else ""
  fields=[value.get("hook_event_name",""),value.get("tool_name",""),skill,value.get("session_id","")]
  if not all(isinstance(field,str) for field in fields): raise ValueError()
  if any("\x1f" in field for field in fields): raise ValueError()
  print("\x1f".join(fields))
except Exception:
  raise SystemExit(1)'
}

state_json_is_valid() {
  local path=$1 session=$2
  [ -n "$PYTHON" ] && [ -x "$PYTHON" ] || return 1
  "$PYTHON" - "$path" "$session" <<'PY'
import json
import sys

path, session = sys.argv[1:3]
try:
  with open(path, encoding="utf-8") as source:
    value = json.load(source)
  if not isinstance(value, dict):
    raise ValueError()
  if value.get("contract") != "FIGMA_CONTEXT_BUDGET v1":
    raise ValueError()
  if value.get("session_id") != session:
    raise ValueError()
  if value.get("skill") != "figma-context-budget":
    raise ValueError()
except Exception:
  raise SystemExit(1)
PY
}

write_state() {
  local session=$1 path temp
  prepare_state_dir || return 1
  path="$STATE_DIR/figma-budget-$session"
  if [ -e "$path" ] || [ -L "$path" ]; then
    is_regular_file "$path" || return 1
  fi
  temp=$(mktemp "$STATE_DIR/.figma-budget.XXXXXX") || return 1
  if [ -z "$PYTHON" ] || [ ! -x "$PYTHON" ]; then
    unlink "$temp" 2>/dev/null || true
    return 1
  fi
  if ! "$PYTHON" - "$temp" "$session" <<'PY'
import json
import sys

path, session = sys.argv[1:3]
with open(path, "w", encoding="utf-8") as target:
  json.dump({"contract": "FIGMA_CONTEXT_BUDGET v1", "session_id": session, "skill": "figma-context-budget"}, target, separators=(",", ":"))
  target.write("\n")
PY
  then
    unlink "$temp" 2>/dev/null || true
    return 1
  fi
  chmod 600 "$temp" || {
    unlink "$temp" 2>/dev/null || true
    return 1
  }
  if ! mv -f "$temp" "$path"; then
    unlink "$temp" 2>/dev/null || true
    return 1
  fi
}

FIELDS=$(printf '%s' "$INPUT" | json_fields 2>/dev/null) || {
  if [ -e "$DISABLED" ] || [ -L "$DISABLED" ]; then
    printf '%s\n' "[figma-context-budget-gate] disabled by $DISABLED" >&2
    exit 0
  fi
  pretool_deny 'hook payload is invalid.'
}
IFS=$'\x1f' read -r EVENT TOOL SKILL SESSION <<< "$FIELDS"

if [ -e "$DISABLED" ] || [ -L "$DISABLED" ]; then
  printf '%s\n' "[figma-context-budget-gate] disabled by $DISABLED" >&2
  if [ "$EVENT" = "PreToolUse" ]; then
    pretool_allow "gate disabled by $DISABLED"
  fi
  exit 0
fi

case "$EVENT" in
  PostToolUse)
    [ "$TOOL" = "Skill" ] || exit 0
    [ "$SKILL" = "figma-context-budget" ] || exit 0
    safe_id "$SESSION" || posttool_fail 'skill payload session id is invalid.'
    write_state "$SESSION" || posttool_fail 'could not write the session budget sentinel.'
    exit 0
    ;;
  PreToolUse)
    case "$TOOL" in
      mcp__figma*__use_figma) exit 0 ;;
      mcp__claude_ai_Figma__use_figma) exit 0 ;;
      mcp__figma*) ;;
      mcp__claude_ai_Figma__*) ;;
      *) exit 0 ;;
    esac
    safe_id "$SESSION" || pretool_deny 'session id is invalid.'
    state_dir_is_invalid && pretool_deny 'state directory is invalid.'
    STATE="$STATE_DIR/figma-budget-$SESSION"
    if [ ! -e "$STATE" ] && [ ! -L "$STATE" ]; then
      pretool_deny 'no session sentinel; invoke Skill(figma-context-budget) before retrying the Figma MCP call.'
    fi
    is_regular_file "$STATE" || pretool_deny 'session state cannot be read safely.'
    state_json_is_valid "$STATE" "$SESSION" || pretool_deny 'session state is missing, unreadable, or malformed JSON.'
    pretool_allow 'session sentinel is present.'
    ;;
  *)
    exit 0
    ;;
esac
