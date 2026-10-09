#!/bin/bash

set -u

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
FABLE_GATE=${FABLE_GATE_PATH:-$SCRIPT_DIR/fable-gate.sh}
T2_HOOK=${T2_ROUTING_GATE_HOOK:-$SCRIPT_DIR/T2-routing-gate.sh}
TMP=$(mktemp -d)
BYPASS_AUDIT="$TMP/bypass-audit.jsonl"
T2_AUDIT="$TMP/t2-audit.jsonl"
T2_TRACE="$TMP/t2-trace.log"
T2_COPY="$TMP/T2-routing-gate.sh"
LEGACY_SENTINEL="$TMP/routed-enforce-off"
ENFORCE_SENTINEL="$TMP/routed-enforce-on"
FABLE_TRANSCRIPT="$TMP/fable.jsonl"
SONNET_TRANSCRIPT="$TMP/sonnet.jsonl"
WORKFLOW_DIR="$TMP/workflows/wf_test"
WORKFLOW_TRANSCRIPT="$WORKFLOW_DIR/transcript.jsonl"
UNWRITABLE="$TMP/unwritable"
CONCURRENT_AUDIT="$TMP/concurrent-audit.jsonl"
CONCURRENT_TRACE="$TMP/concurrent-trace.log"
CACHE_DIR=/tmp/cc-widget-cache
CACHE_SONNET_SID="t2-test-$$-cache-sonnet"
CACHE_FABLE_SID="t2-test-$$-cache-fable"
CACHE_SONNET="$CACHE_DIR/model-${CACHE_SONNET_SID}.txt"
CACHE_FABLE="$CACHE_DIR/model-${CACHE_FABLE_SID}.txt"
FAILURES=0
PASSES=0

cleanup() {
  rm -f "$CACHE_SONNET" "$CACHE_FABLE"
  rm -f "$WORKFLOW_TRANSCRIPT"
  rmdir "$WORKFLOW_DIR" 2>/dev/null
  rmdir "$TMP/workflows" 2>/dev/null
  rmdir "$UNWRITABLE" 2>/dev/null
  rm -f "$TMP"/* 2>/dev/null
  rmdir "$TMP" 2>/dev/null
}

trap cleanup EXIT

pass() {
  PASSES=$((PASSES + 1))
  printf 'PASS %s\n' "$1"
}

fail() {
  printf 'FAIL %s: %s\n' "$1" "$2"
  FAILURES=$((FAILURES + 1))
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
  if "$@"; then
    pass "$name"
  else
    fail "$name" "command failed"
  fi
}

make_input() {
  local session=$1 transcript=$2 prompt=$3 description=$4 subagent_type=$5
  jq -nc \
    --arg session "$session" --arg transcript "$transcript" --arg prompt "$prompt" \
    --arg description "$description" --arg subagent_type "$subagent_type" \
    '{session_id: $session, transcript_path: $transcript, tool_name: "Agent",
      tool_use_id: ("tool-" + $session),
      tool_input: {prompt: $prompt, description: $description, subagent_type: $subagent_type}}'
}

make_input_model() {
  local session=$1 transcript=$2 prompt=$3 description=$4 subagent_type=$5 model=$6
  jq -nc \
    --arg session "$session" --arg transcript "$transcript" --arg prompt "$prompt" \
    --arg description "$description" --arg subagent_type "$subagent_type" --arg model "$model" \
    '{session_id: $session, transcript_path: $transcript, tool_name: "Agent",
      tool_use_id: ("tool-" + $session),
      tool_input: {prompt: $prompt, description: $description, subagent_type: $subagent_type, model: $model}}'
}

run_gate() {
  local input=$1 hook=$2 audit=$3 output=$4 error=$5
  printf '%s' "$input" | T2_ROUTED_SENTINEL="$LEGACY_SENTINEL" FABLE_GATE_T2_AUDIT_PATH="$audit" "$FABLE_GATE" "$hook" > "$output" 2> "$error"
}

run_gate_enforced() {
  local input=$1 hook=$2 audit=$3 output=$4 error=$5
  printf '%s' "$input" | T2_ROUTED_SENTINEL="$ENFORCE_SENTINEL" FABLE_GATE_T2_AUDIT_PATH="$audit" "$FABLE_GATE" "$hook" > "$output" 2> "$error"
}

make_t2_copy() {
  local audit=$1 trace=$2
  while IFS= read -r line; do
    case "$line" in
      LOG=*) printf 'LOG=%s\n' "$trace" ;;
      AUDIT=*) printf 'AUDIT=%s\n' "$audit" ;;
      *) printf '%s\n' "$line" ;;
    esac
  done < "$T2_HOOK" > "$T2_COPY"
  chmod +x "$T2_COPY"
}

printf '{"message":{"model":"claude-fable-5"}}\n' > "$FABLE_TRANSCRIPT"
printf '{"message":{"model":"claude-sonnet-5"}}\n' > "$SONNET_TRANSCRIPT"
mkdir -p "$WORKFLOW_DIR"
printf '{"message":{"model":"claude-sonnet-5"}}\n' > "$WORKFLOW_TRANSCRIPT"
printf '' > "$ENFORCE_SENTINEL"

make_t2_copy "$T2_AUDIT" "$T2_TRACE"
export FABLE_GATE_T2_HOOK_PATH="$T2_COPY"

# fable main + 無 token → 原 no-token deny（T2 在 fable 下不再 bypass、照常執行）
INPUT=$(make_input "t2-test-$$-f1" "$FABLE_TRANSCRIPT" "inspect" "no token" "general-purpose")
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/f1.out" "$TMP/f1.err"
assert_eq "fable-no-token-exit" "$?" "0"
assert_eq "fable-no-token-decision" "$(jq -r '.hookSpecificOutput.permissionDecision' "$TMP/f1.out")" "deny"

# known-bad：fable main + token + 未指定 model → 新 deny（默默繼承 Fable 被攔）
INPUT=$(make_input "t2-test-$$-f2" "$FABLE_TRANSCRIPT" "<routed:判斷> inspect" "with token" "general-purpose")
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/f2.out" "$TMP/f2.err"
assert_eq "fable-inherit-exit" "$?" "0"
assert_eq "fable-inherit-decision" "$(jq -r '.hookSpecificOutput.permissionDecision' "$TMP/f2.out")" "deny"
assert_eq "fable-inherit-audit-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "fable_inherit_no_model"

# known-good：fable main + token + model 顯式指定 → allow
INPUT=$(make_input_model "t2-test-$$-f3" "$FABLE_TRANSCRIPT" "<routed:判斷> inspect" "with model" "general-purpose" "opus")
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/f3.out" "$TMP/f3.err"
assert_eq "fable-model-exit" "$?" "0"
assert_eq "fable-model-output" "$(stat -f %z "$TMP/f3.out")" "0"
assert_eq "fable-model-audit-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "model:opus"

# 邊界：fable main + token + 無 model + description <fable-ok> 顯式標記 → allow
INPUT=$(make_input "t2-test-$$-f4" "$FABLE_TRANSCRIPT" "<routed:判斷> escalation retry" "<fable-ok> 完整失敗軌跡" "general-purpose")
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/f4.out" "$TMP/f4.err"
assert_eq "fable-ok-exit" "$?" "0"
assert_eq "fable-ok-output" "$(stat -f %z "$TMP/f4.out")" "0"
assert_eq "fable-ok-audit-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "fable_ok_marker"

INPUT=$(make_input "t2-test-$$-f4b" "$FABLE_TRANSCRIPT" "<routed:判斷> <fable-ok> untrusted prompt" "terminal escalation" "general-purpose")
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/f4b.out" "$TMP/f4b.err"
assert_eq "fable-ok-prompt-only-exit" "$?" "0"
assert_eq "fable-ok-prompt-only-decision" "$(jq -r '.hookSpecificOutput.permissionDecision' "$TMP/f4b.out")" "deny"
assert_eq "fable-ok-prompt-only-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "fable_inherit_no_model"

INPUT=$(make_input "t2-test-$$-s1" "$SONNET_TRANSCRIPT" "inspect" "no token" "general-purpose")
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/s1.out" "$TMP/s1.err"
assert_eq "sonnet-no-token-exit" "$?" "0"
assert_eq "sonnet-no-token-decision" "$(jq -r '.hookSpecificOutput.permissionDecision' "$TMP/s1.out")" "deny"

INPUT=$(make_input "t2-test-$$-s2" "$SONNET_TRANSCRIPT" "<routed:實作> inspect" "with token" "general-purpose")
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/s2.out" "$TMP/s2.err"
assert_eq "sonnet-token-exit" "$?" "0"
assert_eq "sonnet-token-output" "$(stat -f %z "$TMP/s2.out")" "0"

INPUT=$(make_input "t2-test-$$-e1" "$SONNET_TRANSCRIPT" "inspect" "specialized" "code-reviewer")
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/e1.out" "$TMP/e1.err"
assert_eq "specialized-exit" "$?" "0"

INPUT=$(make_input "t2-test-$$-e2" "$WORKFLOW_TRANSCRIPT" "inspect" "workflow" "general-purpose")
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/e2.out" "$TMP/e2.err"
assert_eq "workflow-exit" "$?" "0"
assert_eq "t2-audit-actions" "$(jq -s -r 'map(.action) | join(",")' "$T2_AUDIT")" "deny,deny,allow,allow,deny,deny,allow,pass-e1,pass-e2"

INPUT=$(make_input "t2-test-$$-enforce-good" "$FABLE_TRANSCRIPT" "inspect" "enforce good" "routed-judge")
run_gate_enforced "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/enforce-good.out" "$TMP/enforce-good.err"
assert_eq "enforce-good-exit" "$?" "0"
assert_eq "enforce-good-output" "$(stat -f %z "$TMP/enforce-good.out")" "0"
assert_eq "enforce-good-audit-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "enforce_allowed:routed-judge"

INPUT=$(make_input_model "t2-test-$$-enforce-bad" "$FABLE_TRANSCRIPT" "<routed:判斷> inspect" "enforce bad" "general-purpose" "opus")
run_gate_enforced "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/enforce-bad.out" "$TMP/enforce-bad.err"
assert_eq "enforce-bad-exit" "$?" "0"
assert_eq "enforce-bad-decision" "$(jq -r '.hookSpecificOutput.permissionDecision' "$TMP/enforce-bad.out")" "deny"
assert_eq "enforce-bad-audit-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "enforce_routed_required:general-purpose"

INPUT=$(make_input_model "t2-test-$$-enforce-edge" "$FABLE_TRANSCRIPT" "inspect" "enforce edge" "routed-impl" "fable")
run_gate_enforced "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/enforce-edge.out" "$TMP/enforce-edge.err"
assert_eq "enforce-edge-exit" "$?" "0"
assert_eq "enforce-edge-decision" "$(jq -r '.hookSpecificOutput.permissionDecision' "$TMP/enforce-edge.out")" "deny"
assert_eq "enforce-edge-audit-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "fable_no_marker:routed-impl"

INPUT=$(make_input "t2-test-$$-mech-good-on" "$SONNET_TRANSCRIPT" "transform" "<mech-ok> fixed transform" "routed-mech")
run_gate_enforced "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/mech-good-on.out" "$TMP/mech-good-on.err"
assert_eq "mech-good-on-exit" "$?" "0"
assert_eq "mech-good-on-output" "$(stat -f %z "$TMP/mech-good-on.out")" "0"
assert_eq "mech-good-on-action" "$(jq -s -r '.[-1].action' "$T2_AUDIT")" "pass-e1"
assert_eq "mech-good-on-token" "$(jq -s -r '.[-1].token' "$T2_AUDIT")" "<mech-ok>"
assert_eq "mech-good-on-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "mech_opt_in_ok"

INPUT=$(make_input "t2-test-$$-mech-bad-on" "$SONNET_TRANSCRIPT" "transform" "fixed transform" "routed-mech")
run_gate_enforced "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/mech-bad-on.out" "$TMP/mech-bad-on.err"
assert_eq "mech-bad-on-exit" "$?" "0"
assert_eq "mech-bad-on-decision" "$(jq -r '.hookSpecificOutput.permissionDecision' "$TMP/mech-bad-on.out")" "deny"
assert_eq "mech-bad-on-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "mech_opt_in_required"
assert_true "mech-bad-on-guidance-input" grep -q '輸入完整' "$TMP/mech-bad-on.out"
assert_true "mech-bad-on-guidance-output" grep -q '輸出固定' "$TMP/mech-bad-on.out"
assert_true "mech-bad-on-guidance-boundary" grep -q '不需搜尋／驗證／取捨' "$TMP/mech-bad-on.out"
assert_true "mech-bad-on-guidance-marker" grep -q '<mech-ok>' "$TMP/mech-bad-on.out"
assert_true "mech-bad-on-guidance-route" grep -q 'routed-judge' "$TMP/mech-bad-on.out"
assert_true "mech-bad-on-guidance-warning" grep -q '不要猜填' "$TMP/mech-bad-on.out"

INPUT=$(make_input "t2-test-$$-mech-prompt-only" "$SONNET_TRANSCRIPT" "<mech-ok> transform" "fixed transform" "routed-mech")
run_gate_enforced "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/mech-prompt-only.out" "$TMP/mech-prompt-only.err"
assert_eq "mech-prompt-only-decision" "$(jq -r '.hookSpecificOutput.permissionDecision' "$TMP/mech-prompt-only.out")" "deny"
assert_eq "mech-prompt-only-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "mech_opt_in_required"

INPUT=$(make_input "t2-test-$$-mech-good-off" "$SONNET_TRANSCRIPT" "transform" "<mech-ok> fixed transform" "routed-mech")
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/mech-good-off.out" "$TMP/mech-good-off.err"
assert_eq "mech-good-off-output" "$(stat -f %z "$TMP/mech-good-off.out")" "0"
assert_eq "mech-good-off-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "mech_opt_in_ok"

INPUT=$(make_input "t2-test-$$-mech-bad-off" "$SONNET_TRANSCRIPT" "transform" "fixed transform" "routed-mech")
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/mech-bad-off.out" "$TMP/mech-bad-off.err"
assert_eq "mech-bad-off-decision" "$(jq -r '.hookSpecificOutput.permissionDecision' "$TMP/mech-bad-off.out")" "deny"
assert_eq "mech-bad-off-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "mech_opt_in_required"

INPUT=$(make_input_model "t2-test-$$-mech-fable-priority" "$FABLE_TRANSCRIPT" "transform" "<mech-ok> fixed transform" "routed-mech" "fable")
run_gate_enforced "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/mech-fable-priority.out" "$TMP/mech-fable-priority.err"
assert_eq "mech-fable-priority-decision" "$(jq -r '.hookSpecificOutput.permissionDecision' "$TMP/mech-fable-priority.out")" "deny"
assert_eq "mech-fable-priority-reason" "$(jq -s -r '.[-1].reason' "$T2_AUDIT")" "fable_no_marker:routed-mech"

INPUT=$(jq -nc --arg transcript "$FABLE_TRANSCRIPT" \
  '{transcript_path: $transcript, tool_name: "Agent", tool_use_id: "tool-missing-session",
    tool_input: {prompt: "inspect", description: "missing session", subagent_type: "general-purpose"}}')
run_gate "$INPUT" "$T2_COPY" "$BYPASS_AUDIT" "$TMP/missing.out" "$TMP/missing.err"
assert_eq "missing-session-exit" "$?" "0"
assert_true "missing-session-row" jq -s -e '.[-1].session_id == ""' "$T2_AUDIT"

run_gate '{bad' "$T2_COPY" "$BYPASS_AUDIT" "$TMP/bad.out" "$TMP/bad.err"
assert_eq "bad-json-exit" "$?" "0"
assert_eq "bad-json-output" "$(stat -f %z "$TMP/bad.out")" "0"

# fable main + 非 T2 hook → 維持 bypass（policy 不變、只有 T2 例外）
INPUT=$(make_input "t2-test-$$-other" "$FABLE_TRANSCRIPT" "inspect" "other hook" "general-purpose")
run_gate "$INPUT" /usr/bin/false "$BYPASS_AUDIT" "$TMP/other.out" "$TMP/other.err"
assert_eq "other-hook-fable-bypass" "$?" "0"
assert_eq "other-hook-output" "$(stat -f %z "$TMP/other.out")" "0"

mkdir -p "$CACHE_DIR"
printf 'claude-sonnet-5\n' > "$CACHE_SONNET"
printf 'claude-fable-5\n' > "$CACHE_FABLE"
INPUT=$(make_input "$CACHE_SONNET_SID" "$FABLE_TRANSCRIPT" "inspect" "cache wins" "general-purpose")
run_gate "$INPUT" /usr/bin/false "$BYPASS_AUDIT" "$TMP/cache-sonnet.out" "$TMP/cache-sonnet.err"
assert_eq "sonnet-cache-over-fable-transcript" "$?" "1"
INPUT=$(make_input "$CACHE_FABLE_SID" "$SONNET_TRANSCRIPT" "inspect" "cache wins" "general-purpose")
run_gate "$INPUT" /usr/bin/false "$BYPASS_AUDIT" "$TMP/cache-fable.out" "$TMP/cache-fable.err"
assert_eq "fable-cache-over-sonnet-transcript" "$?" "0"

make_t2_copy "$CONCURRENT_AUDIT" "$CONCURRENT_TRACE"
LONG_DESC=$(printf '%0100000d' 0 | tr '0' x)
PIDS=""
for i in $(seq 1 16); do
  INPUT=$(make_input "t2-test-$$-cf-$i" "$FABLE_TRANSCRIPT" "<routed:判斷> inspect" "$LONG_DESC" "general-purpose")
  run_gate "$INPUT" "$T2_COPY" "$CONCURRENT_AUDIT" "$TMP/cf-$i.out" "$TMP/cf-$i.err" &
  PIDS="$PIDS $!"
  INPUT=$(make_input "t2-test-$$-cs-$i" "$SONNET_TRANSCRIPT" "<routed:判斷> inspect" "$LONG_DESC" "general-purpose")
  run_gate "$INPUT" "$T2_COPY" "$CONCURRENT_AUDIT" "$TMP/cs-$i.out" "$TMP/cs-$i.err" &
  PIDS="$PIDS $!"
done
CONCURRENT_FAILURES=0
for pid in $PIDS; do
  wait "$pid" || CONCURRENT_FAILURES=$((CONCURRENT_FAILURES + 1))
done
assert_eq "concurrent-exits" "$CONCURRENT_FAILURES" "0"
assert_eq "concurrent-line-count" "$(wc -l < "$CONCURRENT_AUDIT" | tr -d ' ')" "32"
assert_true "concurrent-json-valid" jq -s -e 'length == 32' "$CONCURRENT_AUDIT"
assert_eq "concurrent-unique-tool-use" "$(jq -s '[.[].tool_use_id] | unique | length' "$CONCURRENT_AUDIT")" "32"
assert_true "concurrent-action-counts" jq -s -e \
  '([.[] | select(.action == "deny" and .reason == "fable_inherit_no_model")] | length) == 16 and
   ([.[] | select(.action == "allow")] | length) == 16' "$CONCURRENT_AUDIT"

if [ "$FAILURES" -eq 0 ]; then
  printf 'RESULT PASS %s/%s\n' "$PASSES" "$PASSES"
  exit 0
fi

printf 'RESULT FAIL %s\n' "$FAILURES"
exit 1
