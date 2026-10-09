#!/usr/bin/env bash
set -uo pipefail
HOOK="$HOME/.claude/hooks/repeat-verify-reminder.sh"
SID="test-repeat-verify-$$"
ESCAPED_SID="../escaped-repeat-verify-$$"
STATE_DIR="${TMPDIR:-/tmp}/cc-repeat-verify"
ESCAPED_PATH="${TMPDIR:-/tmp}/escaped-repeat-verify-$$.json"

hashed_state_path() {
  python3 - "$1" "$STATE_DIR" <<'PYEOF'
import hashlib, os, sys
print(os.path.join(sys.argv[2], hashlib.sha256(sys.argv[1].encode()).hexdigest() + ".json"))
PYEOF
}

cleanup() {
  rm -f "$STATE_DIR/$SID.json" "$(hashed_state_path "$SID")"
  rm -f "$ESCAPED_PATH" "$(hashed_state_path "$ESCAPED_SID")"
}
trap cleanup EXIT

call() {
  local tool="$1" cmd="${2:-}" sid="${3:-$SID}"
  python3 - "$tool" "$cmd" "$sid" <<'PYEOF' | python3 "$HOOK"
import json, sys
tool, cmd, sid = sys.argv[1], sys.argv[2], sys.argv[3]
payload = {"session_id": sid, "tool_name": tool, "hook_event_name": "PostToolUse"}
if tool == "Bash":
  payload["tool_input"] = {"command": cmd}
print(json.dumps(payload))
PYEOF
}

fail=0
check() {
  local name="$1" got="$2" want_advisory="$3"
  local has="no"
  [[ "$got" == *additionalContext* ]] && has="yes"
  if [[ "$has" == "$want_advisory" ]]; then
    echo "PASS  $name"
  else
    echo "FAIL  $name (advisory=$has, want=$want_advisory)"
    fail=1
  fi
}

cleanup
out1=$(call Bash "npm run test:unit -- --run")
out2=$(call Bash "git status --short --branch")
check "known-good: 兩條不同指令不觸發" "$out1$out2" "no"

cleanup
call Bash "npm run test:unit -- --run" >/dev/null
out=$(call Bash "npm run test:unit -- --run")
check "known-bad: 同指令重跑且無 mutation → 觸發" "$out" "yes"

cleanup
call Bash "sleep 30" >/dev/null
out=$(call Bash "sleep 30")
check "known-good: 純 sleep 重跑不觸發" "$out" "no"

cleanup
call Bash "sleep 30; echo waited" >/dev/null
out=$(call Bash "sleep 30; echo waited")
check "boundary: sleep 後還有其他 command 仍觸發" "$out" "yes"

cleanup
call Bash $'sleep\n30d' >/dev/null
out=$(call Bash $'sleep\n30d')
check "boundary: multiline command 不得冒充純 sleep" "$out" "yes"

cleanup
call Bash "npm run test:unit -- --run" >/dev/null
out1=$(call Bash "npm run test:unit -- --run")
out2=$(call Bash "npm run test:unit -- --run")
check "known-bad: 同 generation 首次重跑會提醒" "$out1" "yes"
check "known-good: 同 generation 只提醒一次" "$out2" "no"

call Edit >/dev/null
call Bash "npm run test:unit -- --run" >/dev/null
out=$(call Bash "npm run test:unit -- --run")
check "boundary: 新 generation 可再提醒一次" "$out" "yes"

cleanup
parallel_dir=$(mktemp -d "${TMPDIR:-/tmp}/repeat-verify-parallel.XXXXXX")
call Bash "npm run test:parallel -- --run" >/dev/null
for i in $(seq 1 100); do
  call Bash "npm run test:parallel -- --run" > "$parallel_dir/$i" &
done
wait
warnings=$(grep -l additionalContext "$parallel_dir"/* 2>/dev/null | wc -l | tr -d ' ')
if [[ "$warnings" == "1" ]]; then
  echo "PASS  boundary: 並行同 generation 只提醒一次"
else
  echo "FAIL  boundary: 並行同 generation 提醒 $warnings 次 (want=1)"
  fail=1
fi
find "$parallel_dir" -type f -delete
rmdir "$parallel_dir"

cleanup
call Bash "npm run test:unit -- --run" >/dev/null
call Edit >/dev/null
out=$(call Bash "npm run test:unit -- --run")
check "boundary: 同指令但中間有 Edit → 不觸發" "$out" "no"

cleanup
out1=$(call Bash "ls -la")
call Bash "ls -la" >/dev/null
out2=$(call Bash "ls -la")
check "boundary: 短指令(<8字元)豁免" "$out1$out2" "no"

cleanup
call Bash "git status --short --branch" "$ESCAPED_SID" >/dev/null
if [[ -e "$ESCAPED_PATH" ]]; then
  echo "FAIL  security: session_id 不得穿越 STATE_DIR"
  fail=1
else
  echo "PASS  security: session_id 不得穿越 STATE_DIR"
fi

exit $fail
