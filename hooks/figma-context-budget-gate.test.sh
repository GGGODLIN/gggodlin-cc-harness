#!/usr/bin/env bash
# 本檔在契約測試底下；bash ~/.claude/hooks/figma-context-budget-gate.test.sh
# Figma gate 行為 fixture：known-good、known-bad、邊界、一般 Agent/fork 共用 session、disabled recovery。

set -u

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
HOOK="$ROOT/hooks/figma-context-budget-gate.sh"
SETTINGS="$ROOT/settings.json"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/figma-context-budget-gate.XXXXXX")
STATE_DIR="$TMP/state"
DISABLED="$STATE_DIR/figma-gate.disabled"
PASS_COUNT=0
FAIL_COUNT=0

cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  printf 'PASS %s\n' "$1"
}

fail() {
  FAIL_COUNT=$((FAIL_COUNT + 1))
  printf 'FAIL %s: %s\n' "$1" "$2"
}

assert_eq() {
  local name=$1 actual=$2 expected=$3
  if [ "$actual" = "$expected" ]; then
    pass "$name"
  else
    fail "$name" "expected=$expected actual=$actual"
  fi
}

assert_true() {
  local name=$1
  shift
  if "$@" >/dev/null 2>&1; then
    pass "$name"
  else
    fail "$name" "command failed"
  fi
}

assert_file_exists() {
  local name=$1 path=$2
  if [ -f "$path" ]; then
    pass "$name"
  else
    fail "$name" "missing=$path"
  fi
}

assert_file_absent() {
  local name=$1 path=$2
  if [ ! -e "$path" ] && [ ! -L "$path" ]; then
    pass "$name"
  else
    fail "$name" "unexpected=$path"
  fi
}

payload_pre() {
  local session=$1 tool=$2 tool_use=$3
  jq -cn \
    --arg session "$session" --arg tool "$tool" --arg tool_use "$tool_use" \
    '{hook_event_name:"PreToolUse",session_id:$session,tool_name:$tool,tool_use_id:$tool_use,tool_input:{}}'
}

payload_pre_agent() {
  local session=$1 tool=$2 tool_use=$3 agent=$4
  jq -cn \
    --arg session "$session" --arg tool "$tool" --arg tool_use "$tool_use" --arg agent "$agent" \
    '{hook_event_name:"PreToolUse",session_id:$session,agent_id:$agent,tool_name:$tool,tool_use_id:$tool_use,tool_input:{}}'
}

payload_post_skill() {
  local session=$1 skill=$2 tool_use=$3
  jq -cn \
    --arg session "$session" --arg skill "$skill" --arg tool_use "$tool_use" \
    '{hook_event_name:"PostToolUse",session_id:$session,tool_name:"Skill",tool_use_id:$tool_use,tool_input:{skill:$skill}}'
}

run_payload() {
  local payload=$1 output=$2 error=$3
  printf '%s' "$payload" | \
    FIGMA_GATE_STATE_DIR="$STATE_DIR" \
    FIGMA_GATE_DISABLED_SENTINEL="$DISABLED" \
    bash "$HOOK" > "$output" 2> "$error"
}

run_payload_with_python() {
  local payload=$1 output=$2 error=$3 python=$4
  printf '%s' "$payload" | \
    FIGMA_GATE_STATE_DIR="$STATE_DIR" \
    FIGMA_GATE_DISABLED_SENTINEL="$DISABLED" \
    FIGMA_GATE_PYTHON="$python" \
    bash "$HOOK" > "$output" 2> "$error"
}

run_payload_timeout() {
  local payload=$1 output=$2 error=$3 pid loops
  run_payload "$payload" "$output" "$error" &
  pid=$!
  loops=0
  while kill -0 "$pid" 2>/dev/null; do
    if [ "$loops" -ge 20 ]; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
      return 124
    fi
    sleep 0.1
    loops=$((loops + 1))
  done
  wait "$pid"
}

assert_decision() {
  local name=$1 output=$2 expected=$3 actual
  actual=$(jq -r '.hookSpecificOutput.permissionDecision // empty' "$output" 2>/dev/null || true)
  assert_eq "$name" "$actual" "$expected"
}

assert_reason_contains() {
  local name=$1 output=$2 text=$3
  if jq -r '.hookSpecificOutput.permissionDecisionReason // empty' "$output" 2>/dev/null | grep -qF "$text"; then
    pass "$name"
  else
    fail "$name" "missing=$text"
  fi
}

mkdir -p "$STATE_DIR"

assert_true "hook exists" test -f "$HOOK"
assert_true "hook executable" test -x "$HOOK"

GOOD_SESSION="figma-test-good-$$"
GOOD_STATE="$STATE_DIR/figma-budget-$GOOD_SESSION"
printf '%s\n' "$(jq -nc --arg session "$GOOD_SESSION" '{contract:"FIGMA_CONTEXT_BUDGET v1",session_id:$session,skill:"figma-context-budget"}')" > "$GOOD_STATE"
chmod 600 "$GOOD_STATE"
run_payload "$(payload_pre "$GOOD_SESSION" "mcp__figma-desktop__get_metadata" "tool-good")" "$TMP/good.out" "$TMP/good.err"
assert_eq "known-good exit" "$?" "0"
assert_decision "known-good allows sentinel" "$TMP/good.out" "allow"
assert_true "known-good stderr is empty" test ! -s "$TMP/good.err"

BAD_SESSION="figma-test-bad-$$"
run_payload "$(payload_pre "$BAD_SESSION" "mcp__figma-desktop__get_design_context" "tool-bad")" "$TMP/bad.out" "$TMP/bad.err"
assert_eq "known-bad exit" "$?" "0"
assert_decision "known-bad denies missing sentinel" "$TMP/bad.out" "deny"
assert_reason_contains "known-bad names required skill" "$TMP/bad.out" "figma-context-budget"

REMOTE_SESSION="figma-test-remote-$$"
run_payload "$(payload_pre "$REMOTE_SESSION" "mcp__claude_ai_Figma__get_metadata" "tool-remote")" "$TMP/remote.out" "$TMP/remote.err"
assert_eq "remote connector gate exit" "$?" "0"
assert_decision "remote connector denies missing sentinel" "$TMP/remote.out" "deny"
assert_reason_contains "remote connector names required skill" "$TMP/remote.out" "figma-context-budget"

WRITEBACK_SESSION="figma-test-writeback-$$"
run_payload "$(payload_pre "$WRITEBACK_SESSION" "mcp__figma-desktop__use_figma" "tool-writeback")" "$TMP/writeback.out" "$TMP/writeback.err"
WRITEBACK_EXIT=$?
REMOTE_WRITEBACK_SESSION="figma-test-remote-writeback-$$"
run_payload "$(payload_pre "$REMOTE_WRITEBACK_SESSION" "mcp__claude_ai_Figma__use_figma" "tool-remote-writeback")" "$TMP/remote-writeback.out" "$TMP/remote-writeback.err"
REMOTE_WRITEBACK_EXIT=$?
assert_eq "both use_figma writeback bypass exits" "$WRITEBACK_EXIT/$REMOTE_WRITEBACK_EXIT" "0/0"
assert_true "both use_figma writeback stdout is empty" sh -c 'test ! -s "$1" && test ! -s "$2"' _ "$TMP/writeback.out" "$TMP/remote-writeback.out"
assert_true "both use_figma writeback stderr is empty" sh -c 'test ! -s "$1" && test ! -s "$2"' _ "$TMP/writeback.err" "$TMP/remote-writeback.err"

BROKEN_RENDERER="$TMP/broken-renderer"
printf '%s\n' '#!/bin/sh' 'exit 1' > "$BROKEN_RENDERER"
chmod +x "$BROKEN_RENDERER"
RENDER_SESSION="figma-test-renderer-$$"
run_payload_with_python "$(payload_pre "$RENDER_SESSION" "mcp__figma-desktop__get_metadata" "tool-renderer")" "$TMP/renderer.out" "$TMP/renderer.err" "$BROKEN_RENDERER"
assert_eq "broken JSON renderer fails closed" "$?" "2"
assert_true "broken JSON renderer stdout is empty" test ! -s "$TMP/renderer.out"
assert_true "broken JSON renderer reports stderr" grep -qF "could not render" "$TMP/renderer.err"

PREFIX_SESSION="figma-test-prefix-$$"
PREFIX_STATE="$STATE_DIR/figma-budget-$PREFIX_SESSION"
run_payload "$(payload_post_skill "$PREFIX_SESSION" "figma-context-budget-x" "tool-prefix")" "$TMP/prefix.out" "$TMP/prefix.err"
assert_eq "boundary prefix post exit" "$?" "0"
assert_file_absent "boundary prefix does not write sentinel" "$PREFIX_STATE"
assert_true "boundary prefix stdout is empty" test ! -s "$TMP/prefix.out"

MALFORMED_SESSION="figma-test-malformed-$$"
MALFORMED_STATE="$STATE_DIR/figma-budget-$MALFORMED_SESSION"
printf '{bad\n' > "$MALFORMED_STATE"
run_payload "$(payload_pre "$MALFORMED_SESSION" "mcp__figma-desktop__get_screenshot" "tool-malformed")" "$TMP/malformed.out" "$TMP/malformed.err"
assert_eq "boundary malformed state exit" "$?" "0"
assert_decision "boundary malformed state denies" "$TMP/malformed.out" "deny"
assert_reason_contains "boundary malformed state explains failure" "$TMP/malformed.out" "state"

WRITER_SESSION="figma-test-writer-$$"
WRITER_STATE="$STATE_DIR/figma-budget-$WRITER_SESSION"
run_payload "$(payload_post_skill "$WRITER_SESSION" "figma-context-budget" "tool-writer")" "$TMP/writer.out" "$TMP/writer.err"
assert_eq "post exact skill exit" "$?" "0"
assert_file_exists "post exact skill writes sentinel" "$WRITER_STATE"
assert_true "post sentinel is valid JSON" sh -c 'jq -e --arg session "$1" '\'' .contract == "FIGMA_CONTEXT_BUDGET v1" and .session_id == $session and .skill == "figma-context-budget" '\'' "$2" >/dev/null' _ "$WRITER_SESSION" "$WRITER_STATE"
run_payload "$(payload_pre "$WRITER_SESSION" "mcp__figma-desktop__get_metadata" "tool-writer-pre")" "$TMP/writer-pre.out" "$TMP/writer-pre.err"
assert_decision "post sentinel permits next Figma call" "$TMP/writer-pre.out" "allow"

HARDLINK_SESSION="figma-test-hardlink-$$"
HARDLINK_STATE="$STATE_DIR/figma-budget-$HARDLINK_SESSION"
HARDLINK_TARGET="$TMP/hardlink-target"
printf '%s\n' "$(jq -nc --arg session "$HARDLINK_SESSION" '{contract:"FIGMA_CONTEXT_BUDGET v1",session_id:$session,skill:"figma-context-budget"}')" > "$HARDLINK_TARGET"
cp "$HARDLINK_TARGET" "$TMP/hardlink-before"
ln "$HARDLINK_TARGET" "$HARDLINK_STATE"
run_payload "$(payload_pre "$HARDLINK_SESSION" "mcp__figma-desktop__get_metadata" "tool-hardlink")" "$TMP/hardlink.out" "$TMP/hardlink.err"
assert_eq "regular hard link state exits" "$?" "0"
assert_decision "regular hard link state allows" "$TMP/hardlink.out" "allow"
assert_true "regular hard link target is untouched" cmp -s "$HARDLINK_TARGET" "$TMP/hardlink-before"

NON_REGULAR_SESSION="figma-test-non-regular-$$"
NON_REGULAR_STATE="$STATE_DIR/figma-budget-$NON_REGULAR_SESSION"
mkfifo "$NON_REGULAR_STATE"
run_payload_timeout "$(payload_pre "$NON_REGULAR_SESSION" "mcp__figma-desktop__get_metadata" "tool-non-regular")" "$TMP/non-regular.out" "$TMP/non-regular.err"
assert_eq "non-regular state pre exits without blocking" "$?" "0"
assert_decision "non-regular state denies" "$TMP/non-regular.out" "deny"
assert_reason_contains "non-regular state explains failure" "$TMP/non-regular.out" "state"
assert_true "non-regular state remains" test -p "$NON_REGULAR_STATE"

SHARED_SESSION="figma-test-shared-$$"
SHARED_STATE="$STATE_DIR/figma-budget-$SHARED_SESSION"
printf '%s\n' "$(jq -nc --arg session "$SHARED_SESSION" '{contract:"FIGMA_CONTEXT_BUDGET v1",session_id:$session,skill:"figma-context-budget"}')" > "$SHARED_STATE"
chmod 600 "$SHARED_STATE"
run_payload "$(payload_pre_agent "$SHARED_SESSION" "mcp__figma-desktop__get_metadata" "tool-agent" "agent-a")" "$TMP/agent.out" "$TMP/agent.err"
assert_decision "subagent Agent shares session sentinel" "$TMP/agent.out" "allow"
run_payload "$(payload_pre_agent "$SHARED_SESSION" "mcp__figma-desktop__get_screenshot" "tool-fork" "fork-a")" "$TMP/fork.out" "$TMP/fork.err"
assert_decision "subagent fork shares session sentinel" "$TMP/fork.out" "allow"

DISABLED_SESSION="figma-test-disabled-$$"
: > "$DISABLED"
run_payload "$(payload_pre "$DISABLED_SESSION" "mcp__figma-desktop__get_metadata" "tool-disabled")" "$TMP/disabled.out" "$TMP/disabled.err"
assert_eq "disabled exit" "$?" "0"
assert_decision "disabled allows without sentinel" "$TMP/disabled.out" "allow"
assert_true "disabled stderr explains override" grep -qF "disabled" "$TMP/disabled.err"
DISABLED_POST_SESSION="figma-test-disabled-post-$$"
run_payload "$(payload_post_skill "$DISABLED_POST_SESSION" "figma-context-budget" "tool-disabled-post")" "$TMP/disabled-post.out" "$TMP/disabled-post.err"
assert_eq "disabled PostToolUse exit" "$?" "0"
assert_true "disabled PostToolUse stays silent" test ! -s "$TMP/disabled-post.out"
assert_file_absent "disabled PostToolUse does not write sentinel" "$STATE_DIR/figma-budget-$DISABLED_POST_SESSION"
rm -f "$DISABLED"

assert_true "settings is valid JSON" jq -e 'type == "object"' "$SETTINGS"
assert_true "settings PreToolUse matcher wired" jq -e --arg command "~/.claude/hooks/figma-context-budget-gate.sh" '[.hooks.PreToolUse[] | select(.matcher == "mcp__figma*|mcp__claude_ai_Figma__*") | .hooks[]?.command] | map(select(. == $command)) | length == 1' "$SETTINGS"
assert_true "settings PostToolUse Skill wired" jq -e --arg command "~/.claude/hooks/figma-context-budget-gate.sh" '[.hooks.PostToolUse[] | select(.matcher == "Skill") | .hooks[]?.command] | map(select(. == $command)) | length == 1' "$SETTINGS"

TOTAL=$((PASS_COUNT + FAIL_COUNT))
if [ "$FAIL_COUNT" -eq 0 ]; then
  printf 'RESULT PASS %s/%s\n' "$PASS_COUNT" "$TOTAL"
  exit 0
fi
printf 'RESULT FAIL %s/%s\n' "$FAIL_COUNT" "$TOTAL"
exit 1
