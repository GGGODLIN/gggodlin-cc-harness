#!/usr/bin/env bash
set -euo pipefail
HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/repeat-verify-reminder.sh"
[ -f "$HOOK" ] || { echo "FAIL: $HOOK not found"; exit 1; }
SID="test-repeat-verify-$$"
ESCAPED_SID="../escaped-repeat-verify-$$"
FIXTURE=$(mktemp -d "${TMPDIR:-/tmp}/repeat-verify-home.XXXXXX")
export HOME="$FIXTURE/home"
export TMPDIR="$FIXTURE/tmp"
mkdir -p "$HOME" "$TMPDIR"
STATE_DIR="$TMPDIR/cc-repeat-verify"
ESCAPED_PATH="$TMPDIR/escaped-repeat-verify-$$.json"

hashed_state_path() {
  python3 - "$1" "$STATE_DIR" <<'PYEOF'
import hashlib, os, sys
print(os.path.join(sys.argv[2], hashlib.sha256(sys.argv[1].encode()).hexdigest() + ".json"))
PYEOF
}

cleanup() {
  rm -rf "$FIXTURE"
}

reset_state() {
  rm -rf "$STATE_DIR"
  mkdir -p "$HOME" "$TMPDIR"
}

trap cleanup EXIT

call() {
  local tool="$1" cmd="${2:-}" sid="${3:-$SID}" outcome="${4:-completed}" stdout="${5:-}"
  local payload out errors rc=0
  payload=$(python3 - "$tool" "$cmd" "$sid" "$outcome" "$stdout" <<'PYEOF'
import json, os, sys
tool, cmd, sid, outcome, stdout = sys.argv[1:]
payload = {"session_id": sid, "tool_name": tool, "hook_event_name": "PostToolUse",
           "cwd": os.environ.get("TEST_CWD", ""),
           "transcript_path": os.environ.get("TEST_TRANSCRIPT", "")}
if tool == "Bash":
  payload["tool_input"] = {"command": cmd}
  # 本 session JSONL:55 的 Bash 回件形狀，沒有 exit_code。
  response = {"stdout": stdout, "stderr": "", "interrupted": False,
              "isImage": False, "noOutputExpected": False}
  if outcome == "failed":
    payload["hook_event_name"] = "PostToolUseFailure"
    payload["error"] = "Exit code 1"
  elif outcome == "unknown":
    response = {}
  elif outcome == "interrupted":
    response["interrupted"] = True
  elif outcome == "exit-failure":
    response["exit_code"] = 1
  elif outcome == "non-event":
    payload.pop("hook_event_name")
  elif outcome == "timedOutAfterMs":
    response[outcome] = 30000
  elif outcome != "completed":
    response[outcome] = "task-123" if outcome == "backgroundTaskId" else True
  payload["tool_response"] = response
print(json.dumps(payload))
PYEOF
  )
  errors=$(mktemp "$TMPDIR/repeat-stderr.XXXXXX")
  out=$(python3 "$HOOK" <<< "$payload" 2>"$errors") || rc=$?
  if [[ "$rc" != 0 || -s "$errors" ]]; then
    printf 'FAIL hook runtime (exit=%s, stderr bytes=%s)\n' "$rc" "$(wc -c < "$errors")" >&2
    rm -f "$errors"
    return 1
  fi
  rm -f "$errors"
  printf '%s' "$out"
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

reset_state
out1=$(call Bash "npm run test:unit -- --run")
out2=$(call Bash "git status --short --branch")
check "known-good: 兩條不同指令不觸發" "$out1$out2" "no"

reset_state
call Bash "npm run test:unit -- --run" >/dev/null
out=$(call Bash "npm run test:unit -- --run")
check "known-bad: 同指令重跑且無 mutation → 觸發" "$out" "yes"

reset_state
call Bash "sleep 30" >/dev/null
out=$(call Bash "sleep 30")
check "known-good: 純 sleep 重跑不觸發" "$out" "no"

reset_state
call Bash "sleep 30; echo waited" >/dev/null
out=$(call Bash "sleep 30; echo waited")
check "boundary: sleep 後還有其他 command 仍觸發" "$out" "yes"

reset_state
call Bash $'sleep\n30d' >/dev/null
out=$(call Bash $'sleep\n30d')
check "boundary: multiline command 不得冒充純 sleep" "$out" "yes"

reset_state
call Bash "npm run test:unit -- --run" >/dev/null
out1=$(call Bash "npm run test:unit -- --run")
out2=$(call Bash "npm run test:unit -- --run")
check "known-bad: 同 generation 首次重跑會提醒" "$out1" "yes"
check "known-good: 同 generation 只提醒一次" "$out2" "no"

call Edit >/dev/null
call Bash "npm run test:unit -- --run" >/dev/null
out=$(call Bash "npm run test:unit -- --run")
check "boundary: 新 generation 可再提醒一次" "$out" "yes"

reset_state
parallel_dir=$(mktemp -d "$TMPDIR/repeat-verify-parallel.XXXXXX")
call Bash "npm run test:parallel -- --run" >/dev/null
pids=()
for i in $(seq 1 100); do
  call Bash "npm run test:parallel -- --run" > "$parallel_dir/$i" &
  pids+=("$!")
done
for pid in "${pids[@]}"; do
  wait "$pid" || fail=1
done
warnings=$(command grep -l additionalContext "$parallel_dir"/* 2>/dev/null | wc -l | tr -d ' ')
if [[ "$warnings" == "1" ]]; then
  echo "PASS  boundary: 並行同 generation 只提醒一次"
else
  echo "FAIL  boundary: 並行同 generation 提醒 $warnings 次 (want=1)"
  fail=1
fi
find "$parallel_dir" -type f -delete
rmdir "$parallel_dir"

reset_state
call Bash "npm run test:unit -- --run" >/dev/null
call Edit >/dev/null
out=$(call Bash "npm run test:unit -- --run")
check "boundary: 同指令但中間有 Edit → 不觸發" "$out" "no"

reset_state
out1=$(call Bash "ls -la")
call Bash "ls -la" >/dev/null
out2=$(call Bash "ls -la")
check "boundary: 短指令(<8字元)豁免" "$out1$out2" "no"

reset_state
call Bash 'open -a "iPhone Mirroring"' >/dev/null
out=$(call Bash 'open -a "iPhone Mirroring"')
check "known-good: 純聚焦 open -a 重跑不提醒" "$out" "no"

reset_state
call Bash 'open -g -a "iPhone Mirroring"' >/dev/null
out=$(call Bash 'open -g -a "iPhone Mirroring"')
check "known-good: open -g -a 重跑不提醒" "$out" "no"

reset_state
call Bash 'open -a "iPhone Mirroring" && echo focused' >/dev/null
out=$(call Bash 'open -a "iPhone Mirroring" && echo focused')
check "boundary: open 後還有其他 command 仍提醒" "$out" "yes"

reset_state
call Bash "git status" >/dev/null
out=$(call Bash "git status")
check "known-good: git status 重跑不提醒" "$out" "no"

reset_state
call Bash "git status --short --branch" >/dev/null
out=$(call Bash "git status --short --branch")
check "known-good: git status 帶參數重跑不提醒" "$out" "no"

reset_state
call Bash "gh run view 123" >/dev/null
out=$(call Bash "gh run view 123")
check "known-good: gh run view 重跑不提醒" "$out" "no"

reset_state
call Bash "git status --short; npm test" >/dev/null
out=$(call Bash "git status --short; npm test")
check "boundary: 狀態查詢接測試仍提醒" "$out" "yes"

reset_state
call Bash "pytest tests/test_app.py" >/dev/null
out=$(call Bash "pytest tests/test_app.py")
check "known-bad: pytest 重跑仍提醒" "$out" "yes"

reset_state
call Bash "npm test" >/dev/null
call Bash "git push origin main" >/dev/null
out=$(call Bash "npm test")
check "known-good: 成功 git push 後同一驗證可再跑一次" "$out" "no"

reset_state
call Bash "npm test" >/dev/null
call Bash "git push origin main" "" failed >/dev/null
out=$(call Bash "npm test")
check "known-bad: git push 失敗不得重置" "$out" "yes"

reset_state
call Bash "npm test" >/dev/null
call Bash "git push --delete origin stale" "" completed >/dev/null
out=$(call Bash "npm test")
check "boundary: git push --delete 不得重置" "$out" "yes"

reset_state
call Bash "npm test" >/dev/null
call Bash "echo about to push origin main" "" completed >/dev/null
out=$(call Bash "npm test")
check "boundary: 含 push 文字但不是 git push 不得重置" "$out" "yes"

reset_state
call Bash "npm test" >/dev/null
call Bash "git push origin main && npm test" "" completed >/dev/null
out=$(call Bash "npm test")
check "boundary: git push 串其他 command 不得重置" "$out" "yes"

for cmd in \
  'git -C /absolute/repo status --short' \
  'git -C /absolute/repo diff --stat' \
  'git -C "/absolute path/repo" status --short' \
  "git -C '/absolute path/repo' diff --stat" \
  'git ls-remote origin refs/heads/main' \
  'git -C /absolute/repo ls-remote origin refs/heads/main' \
  'git -C "/absolute path/repo" ls-remote origin refs/heads/main' \
  'gh pr checks 123'; do
  reset_state
  call Bash "$cmd" >/dev/null
  out=$(call Bash "$cmd")
  check "regression: 純查詢 $cmd 不提醒" "$out" no
done

for cmd in \
  'git -C /absolute/repo push origin main' \
  'git -C "/absolute path/repo" push origin main' \
  "git -C '/absolute path/repo' push origin main"; do
  reset_state
  call Bash 'npm test' >/dev/null
  call Bash "$cmd" >/dev/null
  out=$(call Bash 'npm test')
  check "regression: 成功 $cmd 重置" "$out" no
  out=$(call Bash 'npm test')
  check "boundary: push 後再重跑測試仍提醒" "$out" yes
done

for outcome in failed exit-failure interrupted backgroundTaskId backgroundedByUser \
  backgroundedByTurnAbort backgroundedToDeliverMessage timedOutAfterMs \
  backgroundEndsWithFinalResponse unknown non-event; do
  reset_state
  call Bash 'npm test' >/dev/null
  call Bash 'git -C /absolute/repo push origin main' '' "$outcome" >/dev/null
  out=$(call Bash 'npm test')
  check "boundary: push $outcome 不重置" "$out" yes
done

for cmd in \
  'echo git -C /absolute/repo push origin main' \
  'git -C /absolute/repo push origin main; npm test' \
  'git -C relative/repo push origin main' \
  'git -C /absolute/repo status && npm test' \
  'echo git status' \
  'git -C /absolute/repo status --output=/some/file'; do
  reset_state
  call Bash 'npm test' >/dev/null
  call Bash "$cmd" >/dev/null
  out=$(call Bash 'npm test')
  check "boundary: $cmd 不重置" "$out" yes
  out=$(call Bash "$cmd")
  check "boundary: 非純查詢 $cmd 重跑仍提醒" "$out" yes
done

# 1e862710 原始 JSONL:6546、7659：同一服務在部署前後回報不同版本。
health='curl -fsS http://127.0.0.1:8787/api/health'
old_health='{"ok":true,"version":"1.12.0-dev+b9a6182a","deposed":false,"mode":"solo"}'
new_health='{"ok":true,"version":"1.12.0-dev+bad8ce1e","deposed":false,"mode":"solo"}'
restart='herdr plugin action invoke restart --plugin herdr.collie'
started='{"result":{"type":"plugin_action_invoked","log":{"status":"running"}}}'

reset_state
call Bash "$health" '' completed "$old_health" >/dev/null
call Bash 'npm test' >/dev/null
call Bash "$restart" '' completed "$started" >/dev/null
call Bash "$health" '' completed "$new_health" >/dev/null
out=$(call Bash 'npm test')
check "deploy: 健康回件確認運行版本改變後可重驗" "$out" no
out=$(call Bash 'npm test')
check "deploy: 完成後再重跑仍提醒" "$out" yes

reset_state
call Bash "$health" '' completed "$old_health" >/dev/null
call Bash 'npm test' >/dev/null
call Bash "$restart" '' completed "$started" >/dev/null
out=$(call Bash 'npm test')
check "deploy: restart 只有 running 不得重置" "$out" yes

reset_state
call Bash "$health" '' completed "$old_health" >/dev/null
call Bash 'npm test' >/dev/null
call Bash "$health" '' completed "$old_health" >/dev/null
out=$(call Bash 'npm test')
check "deploy: 相同健康版本輪詢不得重置" "$out" yes

reset_state
call Bash 'npm test' >/dev/null
call Bash "$health" '' completed "$new_health" >/dev/null
out=$(call Bash 'npm test')
check "deploy: 首次健康回件只建立基準" "$out" yes

for result in \
  '{"ok":false,"version":"new","deposed":false}' \
  '{"ok":true,"version":"new","deposed":true}' \
  '{"ok":true,"version":"new"}' \
  '{"ok":true,"version":"","deposed":false}' \
  '{"ok":true,"version":123,"deposed":false}' \
  'not-json'; do
  reset_state
  call Bash "$health" '' completed "$old_health" >/dev/null
  call Bash 'npm test' >/dev/null
  call Bash "$health" '' completed "$result" >/dev/null
  out=$(call Bash 'npm test')
  check "deploy: 無效或非健康版本不得重置 $result" "$out" yes
  call Bash "$health" '' completed "$new_health" >/dev/null
  out=$(call Bash 'npm test')
  check "deploy: 壞回件不污染最後健康版本 $result" "$out" no
 done

for outcome in failed exit-failure interrupted backgroundTaskId unknown; do
  reset_state
  call Bash "$health" '' completed "$old_health" >/dev/null
  call Bash 'npm test' >/dev/null
  call Bash "$health" '' "$outcome" "$new_health" >/dev/null
  out=$(call Bash 'npm test')
  check "deploy: $outcome 回件不得確認部署" "$out" yes
 done

reset_state
call Bash "$health" '' completed "$old_health" >/dev/null
call Bash 'npm test' >/dev/null
call Bash 'curl -fsS http://127.0.0.1:8790/api/health' '' completed "$new_health" >/dev/null
out=$(call Bash 'npm test')
check "deploy: 不同服務不能互當部署前後版本" "$out" yes

reset_state
call Bash "$health" '' completed "$old_health" >/dev/null
call Bash 'npm test' >/dev/null
call Bash 'printf about-deploy' '' completed "$new_health" >/dev/null
out=$(call Bash 'npm test')
check "deploy: 其他命令輸出健康JSON不重置" "$out" yes

lane="bash $HOME/Desktop/projects/collie-example-owner/docs/owner/dev-lane.sh"
lane_done='next is on 2.3.3-dev+bad8ce1e (dev HEAD bad8ce1e)'
reset_state
call Bash 'npm test' >/dev/null
call Bash "$lane" '' completed "$lane_done" >/dev/null
out=$(call Bash 'npm test')
check "deploy: 現用dev-lane完成後可重驗" "$out" no
out=$(call Bash 'npm test')
check "deploy: dev-lane完成後再次重跑仍提醒" "$out" yes

for outcome in failed interrupted backgroundTaskId; do
  reset_state
  call Bash 'npm test' >/dev/null
  call Bash "$lane" '' "$outcome" "$lane_done" >/dev/null
  out=$(call Bash 'npm test')
  check "deploy: dev-lane $outcome 不重置" "$out" yes
 done

for result in '' 'building' 'next is on old (dev HEAD bad8ce1e)'; do
  reset_state
  call Bash 'npm test' >/dev/null
  call Bash "$lane" '' completed "$result" >/dev/null
  out=$(call Bash 'npm test')
  check "deploy: dev-lane缺完成版本證據不重置 $result" "$out" yes
 done

reset_state
call Bash 'npm test' >/dev/null
call Bash "printf '%s' '$lane'" '' completed "$lane_done" >/dev/null
out=$(call Bash 'npm test')
check "deploy: 文字提及dev-lane不重置" "$out" yes

export TEST_CWD="$HOME/Desktop/projects/collie-example-owner"
export TEST_TRANSCRIPT="$FIXTURE/session.jsonl"
output_file="$FIXTURE/tasks/task-123.output"
mkdir -p "$FIXTURE/tasks"

background_notice() {
  python3 - "$TEST_TRANSCRIPT" "$SID" "$output_file" "$1" <<'PYEOF'
import json, sys
path, session, output, variant = sys.argv[1:]
status = "failed" if variant == "failed" else "completed"
exit_code = 1 if variant == "failed" else 0
task = "other-task" if variant == "other-task" else "task-123"
text = f'<task-notification>\n<task-id>{task}</task-id>\n<output-file>{output}</output-file>\n<status>{status}</status>\n<summary>Background command "Rebuild dev lane" completed (exit code {exit_code})</summary>\n</task-notification>'
row = {"type": "user", "sessionId": session,
       "origin": {"kind": "task-notification", "producer": "session-task"},
       "promptSource": "system", "turnOrigin": "task_notification",
       "message": {"role": "user", "content": text}}
if variant == "quoted":
  row.pop("origin")
  row["promptSource"] = "human"
if variant == "other-session":
  row["sessionId"] = "other-session"
with open(path, "a") as f:
  f.write(json.dumps(row) + "\n")
PYEOF
}

reset_state
: > "$TEST_TRANSCRIPT"
printf '%s\n' 'next is on 2.3.1-dev+05818122-dirty (dev HEAD 05818122)' > "$output_file"
call Bash 'npm test' >/dev/null
call Bash 'bash docs/owner/dev-lane.sh 2>&1 | tail -15' '' backgroundTaskId >/dev/null
background_notice completed
out=$(call Bash 'npm test')
check "deploy: 真實背景管線完成通知後可重驗" "$out" no
out=$(call Bash 'npm test')
check "deploy: 同一完成通知只重置一次" "$out" yes

for variant in failed quoted other-task other-session; do
  reset_state
  : > "$TEST_TRANSCRIPT"
  call Bash 'npm test' >/dev/null
  call Bash 'bash docs/owner/dev-lane.sh 2>&1 | tail -15' '' backgroundTaskId >/dev/null
  background_notice "$variant"
  out=$(call Bash 'npm test')
  check "deploy: $variant 通知不得確認部署" "$out" yes
 done

reset_state
: > "$TEST_TRANSCRIPT"
printf '%s\n' 'dev-lane: next did not come up' > "$output_file"
call Bash 'npm test' >/dev/null
call Bash 'bash docs/owner/dev-lane.sh 2>&1 | tail -15' '' backgroundTaskId >/dev/null
background_notice completed
out=$(call Bash 'npm test')
check "deploy: 管線exit0但缺部署成功輸出不重置" "$out" yes

reset_state
: > "$TEST_TRANSCRIPT"
printf '%s\n' 'next is on 2.3.1-dev+05818122-dirty (dev HEAD 05818122)' > "$output_file"
call Bash 'npm test' >/dev/null
call Bash 'printf about-dev-lane' '' backgroundTaskId >/dev/null
background_notice completed
out=$(call Bash 'npm test')
check "deploy: 非部署背景工作不能借通知重置" "$out" yes
unset TEST_CWD TEST_TRANSCRIPT

reset_state
call Bash "npm test" "$ESCAPED_SID" >/dev/null
if [[ -e "$ESCAPED_PATH" ]]; then
  echo "FAIL  security: session_id 不得穿越 STATE_DIR"
  fail=1
else
  echo "PASS  security: session_id 不得穿越 STATE_DIR"
fi

state_path=$(hashed_state_path "$ESCAPED_SID")
if [[ -f "$state_path" ]] && python3 - "$state_path" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as f:
  state = json.load(f)
assert state["mut"] == 0 and len(state["cmds"]) == 1
assert next(iter(state["cmds"].values()))["n"] == 1
PYEOF
then
  echo "PASS  security: traversal session 真正寫入隔離 JSON state"
else
  echo "FAIL  security: traversal session 未寫入有效 JSON state"
  fail=1
fi

[[ "$fail" == 0 ]] || exit "$fail"
printf '%s\n' REPEAT_VERIFY_CONTRACT_PASS
