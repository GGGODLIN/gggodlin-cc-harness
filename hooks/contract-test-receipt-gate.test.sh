#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/hooks/contract-test-receipt-gate.test.sh
# Threat model: this提示型 gate protects honest agents that forget to rerun a contract test after an edit. It does not prevent deliberate bypasses through an uncovered tool, a direct filesystem write, or a fabricated receipt.
# Surface table: Locked = this gate, its wrapper, and fixtures; Editable = command/SKILL.md targets; Append-only = session receipt JSONL; Human-controlled = the disabled sentinel.
# Bypass table: a bare test command does not create a receipt; a changed target mtime or size invalidates an older receipt; a broken receipt path is rejected without blocking on FIFO I/O; same>3 or total>6 releases the提示型偏安全 Stop gate.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$ROOT/hooks/contract-test-receipt-gate.sh"
HELPER="$ROOT/scripts/contract-test-helper.sh"
WRAPPER="$ROOT/scripts/contract-test-run"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASS=0
FAIL=0

check() {
  local label=$1 ok=$2 detail=${3:-}
  if [ "$ok" -eq 0 ]; then
    printf 'PASS %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL %s%s\n' "$label" "${detail:+ — $detail}"
    FAIL=$((FAIL + 1))
  fi
}

make_payload() {
  local event=$1 session=$2 path=$3 cwd=$4 tool=${5:-Edit}
  jq -nc --arg event "$event" --arg session "$session" --arg path "$path" --arg cwd "$cwd" --arg tool "$tool" \
    '{hook_event_name:$event,session_id:$session,cwd:$cwd,tool_name:$tool,tool_input:{file_path:$path}}'
}

run_post() {
  local session=$1 path=$2 runs=$3 pending=$4 state=$5 disabled=$6 timeout=${7:-30} total=${8:-} runner=${9:-$WRAPPER}
  make_payload PostToolUse "$session" "$path" "$(dirname "$path")" \
    | env CONTRACT_TEST_RUNS_DIR="$runs" CONTRACT_TEST_PENDING_DIR="$pending" \
      CONTRACT_TEST_STATE_DIR="$state" CONTRACT_TEST_DISABLED_SENTINEL="$disabled" \
      CONTRACT_TEST_TIMEOUT_SECONDS="$timeout" CONTRACT_TEST_TOTAL_TIMEOUT_SECONDS="$total" \
      CONTRACT_TEST_HELPER="$HELPER" CONTRACT_TEST_RUNNER="$runner" bash "$HOOK"
}

run_stop() {
  local session=$1 runs=$2 pending=$3 state=$4 disabled=$5 same=${6:-3} total=${7:-6} runner=${8:-$WRAPPER}
  make_payload Stop "$session" "" "$TMP" \
    | env CONTRACT_TEST_RUNS_DIR="$runs" CONTRACT_TEST_PENDING_DIR="$pending" \
      CONTRACT_TEST_STATE_DIR="$state" CONTRACT_TEST_DISABLED_SENTINEL="$disabled" \
      CONTRACT_TEST_HELPER="$HELPER" CONTRACT_TEST_RUNNER="$runner" \
      CONTRACT_TEST_LOOPGUARD_SAME="$same" CONTRACT_TEST_LOOPGUARD_TOTAL="$total" \
      bash "$HOOK"
}

fixture_root="$TMP/known-good/.claude"
mkdir -p "$fixture_root/commands/tests" "$TMP/runs" "$TMP/pending" "$TMP/state"
target="$fixture_root/commands/known-good.md"
test="$fixture_root/commands/tests/known-good-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' "grep -Fq known-good '$target'" > "$test"
chmod +x "$test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $test -->" '# known-good' > "$target"
disabled="$TMP/state/contract-test-gate.disabled"
session=known-good-session

post_output="$TMP/known-good-post.out"
post_error="$TMP/known-good-post.err"
run_post "$session" "$target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$post_output" 2>"$post_error"
post_rc=$?
check 'known-good: PostToolUse exits zero' "$([ "$post_rc" -eq 0 ] && printf 0 || printf 1)" "actual exit=$post_rc"
check 'known-good: hook stdout is empty' "$([ ! -s "$post_output" ] && printf 0 || printf 1)" "unexpected stdout=$(cat "$post_output")"
check 'known-good: hook stderr is empty' "$([ ! -s "$post_error" ] && printf 0 || printf 1)" "unexpected stderr=$(cat "$post_error")"
receipt="$TMP/runs/$session.jsonl"
check 'known-good: receipt exists' "$([ -f "$receipt" ] && printf 0 || printf 1)"
expected_mtime_ns="$(python3 -c 'import os,sys; print(os.stat(sys.argv[1]).st_mtime_ns)' "$target")"
expected_size="$(python3 -c 'import os,sys; print(os.stat(sys.argv[1]).st_size)' "$target")"
canonical_test="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$test")"
check 'known-good: receipt has passing test and target stamp' "$(jq -e --arg test "$canonical_test" --argjson mtime "$expected_mtime_ns" --argjson size "$expected_size" 'select(.test_path == $test and .target_mtime_ns == $mtime and .target_size == $size and .exit == 0 and .exit_code == 0 and (.seconds | type == "number"))' "$receipt" >/dev/null 2>&1; printf "$?")" "receipt=$(cat "$receipt" 2>/dev/null)"
check 'known-good: receipt carries no digest field' "$(jq -e -s 'all(.[]; (keys | map(test("sha|hash|digest|checksum"; "i")) | any | not) and ([.. | strings | select(test("^[0-9a-f]{64}$"))] | length == 0))' "$receipt" >/dev/null 2>&1; printf "$?")" "receipt=$(cat "$receipt" 2>/dev/null)"
check 'known-good: pending carries no digest field' "$(jq -e -s 'all(.[]; (keys | map(test("sha|hash|digest|checksum"; "i")) | any | not) and ([.. | strings | select(test("^[0-9a-f]{64}$"))] | length == 0))' "$TMP/pending/$session.jsonl" >/dev/null 2>&1; printf "$?")" "pending=$(cat "$TMP/pending/$session.jsonl" 2>/dev/null)"
stop_output="$TMP/known-good-stop.out"
stop_error="$TMP/known-good-stop.err"
run_stop "$session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$stop_output" 2>"$stop_error"
stop_rc=$?
check 'known-good: Stop exits zero' "$([ "$stop_rc" -eq 0 ] && printf 0 || printf 1)" "actual exit=$stop_rc"
check 'known-good: Stop allows with matching receipt' "$([ ! -s "$stop_output" ] && printf 0 || printf 1)" "unexpected output=$(cat "$stop_output")"
check 'known-good: pending is cleared after Stop' "$([ ! -e "$TMP/pending/$session.jsonl" ] && printf 0 || printf 1)"

bad_root="$TMP/known-bad/.claude"
mkdir -p "$bad_root/commands/tests"
bad_target="$bad_root/commands/known-bad.md"
bad_test="$bad_root/commands/tests/known-bad-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'for i in $(seq 1 45); do printf "bad-output-%s\\n" "$i"; done' 'exit 7' > "$bad_test"
chmod +x "$bad_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $bad_test -->" '# known-bad' > "$bad_target"
bad_session=known-bad-session
bad_output="$TMP/known-bad-post.out"
bad_error="$TMP/known-bad-post.err"
run_post "$bad_session" "$bad_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$bad_output" 2>"$bad_error"
bad_post_rc=$?
check 'known-bad: PostToolUse remains non-blocking' "$([ "$bad_post_rc" -eq 0 ] && printf 0 || printf 1)"
# 自動測試失敗時不額外塞 additionalContext 提醒（避免干擾），失敗僅留收據與 Stop 檢查。
check 'known-bad: PostToolUse emits no additionalContext reminder' "$(! grep -q additionalContext "$bad_output"; printf "$?")" "stdout=$(cat "$bad_output")"
reminder_control="$TMP/reminder-control.out"
printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"x"}}' > "$reminder_control"
check 'control: the reminder matcher detects additionalContext' "$(grep -q additionalContext "$reminder_control"; printf "$?")"
check 'known-bad: stderr includes output tail' "$(grep -Fxq bad-output-45 "$bad_error" && ! grep -Fxq bad-output-1 "$bad_error"; printf "$?")" "stderr=$(cat "$bad_error")"
bad_receipt="$TMP/runs/$bad_session.jsonl"
check 'known-bad: receipt records nonzero exit' "$(jq -e 'select(.exit == 7 and .exit_code == 7 and .status == "failed" and .timeout == false)' "$bad_receipt" >/dev/null 2>&1; printf "$?")" "receipt=$(cat "$bad_receipt" 2>/dev/null)"
bad_stop="$TMP/known-bad-stop.out"
run_stop "$bad_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$bad_stop" 2>/dev/null
check 'known-bad: Stop blocks' "$(jq -e 'select(.decision == "block")' "$bad_stop" >/dev/null 2>&1; printf "$?")" "output=$(cat "$bad_stop")"
check 'known-bad: Stop lists wrapper command' "$(grep -Fq "$WRAPPER" "$bad_stop" && printf 0 || printf 1)"

boundary_root="$TMP/hash-boundary/.claude"
mkdir -p "$boundary_root/commands/tests"
boundary_target="$boundary_root/commands/hash-boundary.md"
boundary_test="$boundary_root/commands/tests/hash-boundary-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' "grep -Fq hash-boundary '$boundary_target'" > "$boundary_test"
chmod +x "$boundary_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $boundary_test -->" '# hash-boundary' > "$boundary_target"
boundary_session=hash-boundary-session
run_post "$boundary_session" "$boundary_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
printf '%s\n' '# changed-after-receipt' > "$boundary_target"
boundary_stop="$TMP/hash-boundary-stop.out"
run_stop "$boundary_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$boundary_stop" 2>/dev/null
check 'boundary: changed target size blocks Stop' "$(jq -e 'select(.decision == "block")' "$boundary_stop" >/dev/null 2>&1; printf "$?")" "output=$(cat "$boundary_stop")"
check 'boundary: changed target remains pending' "$([ -f "$TMP/pending/$boundary_session.jsonl" ] && printf 0 || printf 1)"

 timeout_root="$TMP/timeout/.claude"
mkdir -p "$timeout_root/commands/tests"
timeout_target="$timeout_root/commands/timeout.md"
timeout_test="$timeout_root/commands/tests/timeout-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'sleep 1' "grep -Fq timeout '$timeout_target'" > "$timeout_test"
chmod +x "$timeout_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $timeout_test -->" '# timeout' > "$timeout_target"
timeout_session=timeout-session
timeout_error="$TMP/timeout-post.err"
run_post "$timeout_session" "$timeout_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" 0.1 >/dev/null 2>"$timeout_error"
timeout_post_rc=$?
timeout_receipt="$TMP/runs/$timeout_session.jsonl"
check 'boundary: timeout is non-blocking' "$([ "$timeout_post_rc" -eq 0 ] && printf 0 || printf 1)"
check 'boundary: timeout receipt is recorded' "$(jq -e 'select(.exit == "timeout" and .timeout == true and .status == "timeout")' "$timeout_receipt" >/dev/null 2>&1; printf "$?")" "receipt=$(cat "$timeout_receipt" 2>/dev/null)"
check 'boundary: timeout names wrapper command' "$(grep -Fq "$WRAPPER" "$timeout_error" && printf 0 || printf 1)"
env -u CONTRACT_TEST_TIMEOUT_SECONDS CONTRACT_TEST_SESSION_ID="$timeout_session" \
  CONTRACT_TEST_CWD="$(dirname "$timeout_target")" CONTRACT_TEST_RUNS_DIR="$TMP/runs" \
  CONTRACT_TEST_PENDING_DIR="$TMP/pending" CONTRACT_TEST_STATE_DIR="$TMP/state" \
  CONTRACT_TEST_DISABLED_SENTINEL="$disabled" CONTRACT_TEST_HELPER="$HELPER" \
  "$WRAPPER" "$timeout_test" >/dev/null 2>"$TMP/timeout-wrapper.err"
wrapper_rc=$?
check 'boundary: wrapper rerun exits zero from test path' "$([ "$wrapper_rc" -eq 0 ] && printf 0 || printf 1)"
check 'boundary: wrapper adds passing receipt' "$(jq -e 'select(.exit == 0 and .exit_code == 0 and .status == "passed" and .timeout == false)' "$timeout_receipt" >/dev/null 2>&1; printf "$?")" "receipt=$(cat "$timeout_receipt" 2>/dev/null)"
timeout_stop="$TMP/timeout-stop.out"
run_stop "$timeout_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$timeout_stop" 2>/dev/null
check 'boundary: wrapper receipt lets Stop pass' "$([ ! -s "$timeout_stop" ] && printf 0 || printf 1)" "output=$(cat "$timeout_stop")"

latest_root="$TMP/latest-receipt/.claude"
mkdir -p "$latest_root/commands/tests"
latest_target="$latest_root/commands/latest.md"
latest_test="$latest_root/commands/tests/latest-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' "grep -Fq latest '$latest_target'" > "$latest_test"
chmod +x "$latest_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $latest_test -->" '# latest' > "$latest_target"
latest_session=latest-receipt-session
run_post "$latest_session" "$latest_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
printf '%s\n' '#!/usr/bin/env bash' 'printf latest-failure' 'exit 9' > "$latest_test"
env -u CONTRACT_TEST_TIMEOUT_SECONDS CONTRACT_TEST_SESSION_ID="$latest_session" \
  CONTRACT_TEST_CWD="$(dirname "$latest_target")" CONTRACT_TEST_RUNS_DIR="$TMP/runs" \
  CONTRACT_TEST_PENDING_DIR="$TMP/pending" CONTRACT_TEST_STATE_DIR="$TMP/state" \
  CONTRACT_TEST_DISABLED_SENTINEL="$disabled" CONTRACT_TEST_TARGET_PATH="$latest_target" \
  "$WRAPPER" "$latest_test" >/dev/null 2>"$TMP/latest-wrapper.err"
latest_stop="$TMP/latest-stop.out"
run_stop "$latest_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$latest_stop" 2>/dev/null
check 'boundary: latest failed receipt overrides earlier success' "$(jq -e 'select(.decision == "block")' "$latest_stop" >/dev/null 2>&1; printf "$?")" "output=$(cat "$latest_stop")"

twin_root="$TMP/target-identity/.claude"
mkdir -p "$twin_root/commands/tests"
twin_a="$twin_root/commands/twin-a.md"
twin_b="$twin_root/commands/twin-b.md"
twin_test="$twin_root/commands/tests/twin-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' "grep -Fq same-target '$twin_a'" > "$twin_test"
chmod +x "$twin_test"
marker="<!-- 本檔在契約測試底下：bash $twin_test -->"
printf '%s\n' "$marker" '# same-target' > "$twin_a"
printf '%s\n' "$marker" '# same-target' > "$twin_b"
twin_session=target-identity-session
run_post "$twin_session" "$twin_a" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
run_post "$twin_session" "$twin_b" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
twin_receipt="$TMP/runs/$twin_session.jsonl"
canonical_twin_b="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$twin_b")"
python3 - "$twin_receipt" "$canonical_twin_b" <<'PY'
import json
import sys
from pathlib import Path
receipt, target = sys.argv[1:3]
rows = [json.loads(line) for line in Path(receipt).read_text().splitlines() if line.strip()]
Path(receipt).write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows if row.get("target_path") != target))
PY
twin_stop="$TMP/target-identity-stop.out"
run_stop "$twin_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$twin_stop" 2>/dev/null
check 'boundary: receipt target identity cannot cross-release equal stamps' "$(jq -e 'select(.decision == "block")' "$twin_stop" >/dev/null 2>&1; printf "$?")" "output=$(cat "$twin_stop")"

aggregate_root="$TMP/aggregate-timeout/.claude"
mkdir -p "$aggregate_root/commands/tests"
aggregate_target="$aggregate_root/commands/aggregate.md"
aggregate_test_a="$aggregate_root/commands/tests/aggregate-a-contract.test.sh"
aggregate_test_b="$aggregate_root/commands/tests/aggregate-b-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'sleep 1' > "$aggregate_test_a"
printf '%s\n' '#!/usr/bin/env bash' 'sleep 1' > "$aggregate_test_b"
chmod +x "$aggregate_test_a" "$aggregate_test_b"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $aggregate_test_a -->" "<!-- 本檔在契約測試底下：bash $aggregate_test_b -->" '# aggregate' > "$aggregate_target"
aggregate_session=aggregate-timeout-session
run_post "$aggregate_session" "$aggregate_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" 0.2 0.25 >/dev/null 2>"$TMP/aggregate-post.err"
aggregate_receipt="$TMP/runs/$aggregate_session.jsonl"
check 'boundary: aggregate timeout records both tests' "$(jq -s 'length == 2 and all(.timeout == true)' "$aggregate_receipt" >/dev/null 2>&1; printf "$?")" "receipt=$(cat "$aggregate_receipt" 2>/dev/null)"
check 'boundary: aggregate timeout stays within total budget' "$(jq -e -s '([.[].seconds] | add) < 0.35' "$aggregate_receipt" >/dev/null 2>&1; printf "$?")" "receipt=$(cat "$aggregate_receipt" 2>/dev/null)"

ambiguous_root="$TMP/ambiguous-session/.claude"
mkdir -p "$ambiguous_root/commands/tests"
ambiguous_target="$ambiguous_root/commands/ambiguous.md"
ambiguous_test="$ambiguous_root/commands/tests/ambiguous-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'exit 7' > "$ambiguous_test"
chmod +x "$ambiguous_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $ambiguous_test -->" '# ambiguous' > "$ambiguous_target"
ambiguous_session_a=ambiguous-session-a
ambiguous_session_b=ambiguous-session-b
run_post "$ambiguous_session_a" "$ambiguous_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
run_post "$ambiguous_session_b" "$ambiguous_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
ambiguous_receipt_a="$TMP/runs/$ambiguous_session_a.jsonl"
ambiguous_receipt_b="$TMP/runs/$ambiguous_session_b.jsonl"
ambiguous_before_a="$(wc -l < "$ambiguous_receipt_a" | tr -d ' ')"
ambiguous_before_b="$(wc -l < "$ambiguous_receipt_b" | tr -d ' ')"
env -u CONTRACT_TEST_SESSION_ID -u CONTRACT_TEST_SESSION -u CLAUDE_CODE_SESSION_ID -u CLAUDE_SESSION_ID \
  CONTRACT_TEST_CWD="$(dirname "$ambiguous_target")" CONTRACT_TEST_RUNS_DIR="$TMP/runs" \
  CONTRACT_TEST_PENDING_DIR="$TMP/pending" CONTRACT_TEST_STATE_DIR="$TMP/state" \
  CONTRACT_TEST_DISABLED_SENTINEL="$disabled" CONTRACT_TEST_HELPER="$HELPER" \
  "$WRAPPER" "$ambiguous_target" >/dev/null 2>"$TMP/ambiguous-wrapper.err"
ambiguous_wrapper_rc=$?
ambiguous_after_a="$(wc -l < "$ambiguous_receipt_a" | tr -d ' ')"
ambiguous_after_b="$(wc -l < "$ambiguous_receipt_b" | tr -d ' ')"
check 'boundary: ambiguous target wrapper does not guess a session' "$([ "$ambiguous_after_a" = "$ambiguous_before_a" ] && [ "$ambiguous_after_b" = "$ambiguous_before_b" ] && printf 0 || printf 1)"
check 'boundary: ambiguous target wrapper requests explicit session' "$(grep -Fq 'CONTRACT_TEST_SESSION_ID' "$TMP/ambiguous-wrapper.err" && printf 0 || printf 1)"

symlink_root="$TMP/symlink-receipt/.claude"
mkdir -p "$symlink_root/commands/tests"
symlink_target="$symlink_root/commands/symlink.md"
symlink_test="$symlink_root/commands/tests/symlink-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' "grep -Fq symlink '$symlink_target'" > "$symlink_test"
chmod +x "$symlink_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $symlink_test -->" '# symlink' > "$symlink_target"
symlink_session=symlink-receipt-session
symlink_receipt="$TMP/runs/$symlink_session.jsonl"
symlink_outside="$TMP/symlink-outside.jsonl"
: > "$symlink_outside"
ln -s "$symlink_outside" "$symlink_receipt"
symlink_error="$TMP/symlink-post.err"
run_post "$symlink_session" "$symlink_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>"$symlink_error"
check '病態: symlink receipt PostToolUse returns' "$([ "$?" -eq 0 ] && printf 0 || printf 1)"
check '病態: symlink receipt target stays untouched' "$([ ! -s "$symlink_outside" ] && printf 0 || printf 1)"
check '病態: symlink receipt reports rejected write' "$(grep -Fq 'receipt write rejected' "$symlink_error" && printf 0 || printf 1)"
symlink_stop_1="$TMP/symlink-stop-1.out"
symlink_stop_2="$TMP/symlink-stop-2.out"
symlink_stop_3="$TMP/symlink-stop-3.out"
symlink_stop_4="$TMP/symlink-stop-4.out"
run_stop "$symlink_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$symlink_stop_1" 2>/dev/null
run_stop "$symlink_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$symlink_stop_2" 2>/dev/null
run_stop "$symlink_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$symlink_stop_3" 2>/dev/null
run_stop "$symlink_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$symlink_stop_4" 2>/dev/null
check '病態: symlink receipt first three Stop calls block' "$(jq -e -s 'length == 3 and all(.decision == "block")' "$symlink_stop_1" "$symlink_stop_2" "$symlink_stop_3" >/dev/null 2>&1; printf "$?")"
check '病態: symlink receipt fourth Stop call releases' "$([ ! -s "$symlink_stop_4" ] && printf 0 || printf 1)"
check '病態: loop guard release is audited' "$(grep -Fq 'ESCAPED' "$TMP/state/contract-test-loopguard/audit.jsonl" && printf 0 || printf 1)"

fifo_root="$TMP/fifo-receipt/.claude"
mkdir -p "$fifo_root/commands/tests"
fifo_target="$fifo_root/commands/fifo.md"
fifo_test="$fifo_root/commands/tests/fifo-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' "grep -Fq fifo '$fifo_target'" > "$fifo_test"
chmod +x "$fifo_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $fifo_test -->" '# fifo' > "$fifo_target"
fifo_session=fifo-receipt-session
fifo_receipt="$TMP/runs/$fifo_session.jsonl"
mkfifo "$fifo_receipt"
fifo_started="$(date +%s)"
run_post "$fifo_session" "$fifo_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>"$TMP/fifo-post.err"
fifo_post_rc=$?
fifo_elapsed=$(( $(date +%s) - fifo_started ))
check '病態: FIFO receipt PostToolUse returns' "$([ "$fifo_post_rc" -eq 0 ] && printf 0 || printf 1)"
check '病態: FIFO receipt does not block' "$([ "$fifo_elapsed" -lt 5 ] && printf 0 || printf 1)" "elapsed=$fifo_elapsed"
for i in 1 2 3 4; do
  run_stop "$fifo_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$TMP/fifo-stop-$i.out" 2>/dev/null
done
check '病態: FIFO receipt first three Stop calls block' "$(jq -e -s 'length == 3 and all(.decision == "block")' "$TMP/fifo-stop-1.out" "$TMP/fifo-stop-2.out" "$TMP/fifo-stop-3.out" >/dev/null 2>&1; printf "$?")"
check '病態: FIFO receipt fourth Stop call releases' "$([ ! -s "$TMP/fifo-stop-4.out" ] && printf 0 || printf 1)"

total_root="$TMP/total-limit/.claude"
mkdir -p "$total_root/commands/tests"
total_target="$total_root/commands/total.md"
total_test="$total_root/commands/tests/total-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' "grep -Fq total '$total_target'" > "$total_test"
chmod +x "$total_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $total_test -->" '# total' > "$total_target"
total_session=total-limit-session
run_post "$total_session" "$total_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
for i in 1 2 3 4 5 6 7; do
  printf '# total-%s\n' "$i" > "$total_target"
  run_stop "$total_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$TMP/total-stop-$i.out" 2>/dev/null
done
check 'loop guard: changing fingerprint blocks first six total calls' "$(jq -e -s 'length == 6 and all(.decision == "block")' "$TMP/total-stop-1.out" "$TMP/total-stop-2.out" "$TMP/total-stop-3.out" "$TMP/total-stop-4.out" "$TMP/total-stop-5.out" "$TMP/total-stop-6.out" >/dev/null 2>&1; printf "$?")"
check 'loop guard: changing fingerprint releases on seventh total call' "$([ ! -s "$TMP/total-stop-7.out" ] && printf 0 || printf 1)"

no_exam_root="$TMP/no-exam/.claude"
mkdir -p "$no_exam_root/commands"
no_exam_target="$no_exam_root/commands/no-exam.md"
printf '%s\n' '# no contract test' > "$no_exam_target"
no_exam_session=no-exam-session
run_post "$no_exam_session" "$no_exam_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
check '旁路: no exam does not create receipt' "$([ ! -e "$TMP/runs/$no_exam_session.jsonl" ] && printf 0 || printf 1)"
check '旁路: no exam does not create pending state' "$([ ! -e "$TMP/pending/$no_exam_session.jsonl" ] && printf 0 || printf 1)"

eval_root="$TMP/eval-only/.claude"
mkdir -p "$eval_root/skills/eval-only/evals"
printf '%s\n' 'name: eval-only' > "$eval_root/skills/eval-only/evals/eval.yaml"
eval_target="$eval_root/skills/eval-only/SKILL.md"
printf '%s\n' '# eval only' > "$eval_target"
eval_session=eval-only-session
run_post "$eval_session" "$eval_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
check '旁路: eval.yaml-only skill does not create contract receipt' "$([ ! -e "$TMP/runs/$eval_session.jsonl" ] && printf 0 || printf 1)"

self_session=self-test-session
run_post "$self_session" "$HOOK" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
check '生命週期: changing gate itself does not recurse' "$([ ! -e "$TMP/runs/$self_session.jsonl" ] && printf 0 || printf 1)"

disabled_session=disabled-session
: > "$disabled"
disabled_output="$TMP/disabled.out"
disabled_error="$TMP/disabled.err"
run_post "$disabled_session" "$target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$disabled_output" 2>"$disabled_error"
check '生命週期: disabled skips PostToolUse' "$([ ! -e "$TMP/runs/$disabled_session.jsonl" ] && [ ! -e "$TMP/pending/$disabled_session.jsonl" ] && printf 0 || printf 1)"
check '生命週期: disabled leaves trace' "$(grep -Fq disabled "$disabled_error" && printf 0 || printf 1)"
rm -f "$disabled"

external_exec_root="$TMP/external-exec/.claude"
mkdir -p "$external_exec_root/commands"
external_exec_target="$external_exec_root/commands/external-exec.md"
external_exec_test="$TMP/external-exec/outside-contract.test.sh"
external_exec_side_effect="$TMP/external-exec/ran"
mkdir -p "$(dirname "$external_exec_test")"
printf '%s\n' '#!/usr/bin/env bash' "printf executed > '$external_exec_side_effect'" >"$external_exec_test"
chmod +x "$external_exec_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $external_exec_test -->" '# external execution' >"$external_exec_target"
external_exec_session=external-exec-session
run_post "$external_exec_session" "$external_exec_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
check 'security: external marker test is not executed' "$([ ! -e "$external_exec_side_effect" ] && printf 0 || printf 1)"
check 'security: external marker does not create pending state' "$([ ! -e "$TMP/pending/$external_exec_session.jsonl" ] && printf 0 || printf 1)"

language_root="$TMP/language-support/.claude"
mkdir -p "$language_root/commands/tests" "$language_root/commands"
language_target="$language_root/commands/language.md"
language_python="$language_root/commands/tests/language-contract.test.py"
language_mjs="$language_root/commands/tests/language-contract.test.mjs"
language_js="$language_root/commands/tests/language-contract.test.js"
printf '%s\n' 'import sys' 'sys.exit(0)' >"$language_python"
printf '%s\n' 'import test from "node:test"' 'test("language", () => {})' >"$language_mjs"
printf '%s\n' 'const test = require("node:test")' 'test("language", () => {})' >"$language_js"
chmod +x "$language_python" "$language_mjs" "$language_js"
printf '%s\n' '<!-- 本檔在契約測試底下：python3 commands/tests/language-contract.test.py && node --test commands/tests/language-contract.test.mjs -->' '<!-- 本檔在契約測試底下：node commands/tests/language-contract.test.js -->' '# language' >"$language_target"
language_session=language-support-session
run_post "$language_session" "$language_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>"$TMP/language.err"
language_receipt="$TMP/runs/$language_session.jsonl"
check 'security: supported language markers execute' "$(jq -s 'length == 3 and all(.status == "passed")' "$language_receipt" >/dev/null 2>&1; printf "$?")" "stderr=$(cat "$TMP/language.err")"

python_shape_root="$TMP/python-shape/.claude"
mkdir -p "$python_shape_root/commands/tests" "$python_shape_root/commands"
python_shape_target="$python_shape_root/commands/python-shape.md"
python_shape_test="$python_shape_root/commands/tests/test_python_shape.py"
printf '%s\n' 'from pathlib import Path' "assert Path('$python_shape_target').name == 'python-shape.md'" >"$python_shape_test"
printf '%s\n' '# python-shape' >"$python_shape_target"
python_shape_session=python-shape-session
run_post "$python_shape_session" "$python_shape_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>"$TMP/python-shape.err"
python_shape_receipt="$TMP/runs/$python_shape_session.jsonl"
canonical_python_shape="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$python_shape_test")"
check 'regression: commands/tests/test_*.py writes a receipt' "$([ -f "$python_shape_receipt" ] && jq -e --arg test "$canonical_python_shape" 'select(.test_path == $test and .status == "passed")' "$python_shape_receipt" >/dev/null 2>&1; printf "$?")" "stderr=$(cat "$TMP/python-shape.err")"

hash_test_root="$TMP/test-hash/.claude"
mkdir -p "$hash_test_root/commands/tests" "$hash_test_root/commands"
hash_test_target="$hash_test_root/commands/test-hash.md"
hash_test="$hash_test_root/commands/tests/test-hash-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$hash_test"
chmod +x "$hash_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $hash_test -->" '# test hash' >"$hash_test_target"
hash_test_session=test-hash-session
run_post "$hash_test_session" "$hash_test_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
hash_test_receipt="$TMP/runs/$hash_test_session.jsonl"
check 'security: receipt stores test stamp' "$(jq -e 'select((.test_mtime_ns | type == "number") and (.test_size | type == "number"))' "$hash_test_receipt" >/dev/null 2>&1; printf "$?")"
printf '%s\n' '#!/usr/bin/env bash' 'exit 7' >"$hash_test"
hash_test_stop="$TMP/test-hash-stop.out"
run_stop "$hash_test_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$hash_test_stop" 2>/dev/null
check 'security: changed test mtime blocks Stop' "$(jq -e 'select(.decision == "block")' "$hash_test_stop" >/dev/null 2>&1; printf "$?")"

same_size_root="$TMP/same-size/.claude"
mkdir -p "$same_size_root/commands/tests"
same_size_target="$same_size_root/commands/same-size.md"
same_size_test="$same_size_root/commands/tests/same-size-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$same_size_test"
chmod +x "$same_size_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $same_size_test -->" '# aaaa' >"$same_size_target"
same_size_session=same-size-session
run_post "$same_size_session" "$same_size_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
same_size_clean="$TMP/same-size-clean.out"
run_stop "$same_size_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$same_size_clean" 2>/dev/null
check 'boundary: unchanged target is accepted' "$([ ! -s "$same_size_clean" ] && printf 0 || printf 1)" "output=$(cat "$same_size_clean")"
run_post "$same_size_session" "$same_size_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
python3 - "$same_size_target" <<'PY'
import os
import sys
path = sys.argv[1]
before = os.stat(path)
with open(path, "r+b") as handle:
  handle.seek(-5, os.SEEK_END)
  handle.write(b"bbbb\n")
os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
assert os.stat(path).st_size == before.st_size
PY
same_size_stop="$TMP/same-size-stop.out"
run_stop "$same_size_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$same_size_stop" 2>/dev/null
check 'boundary: same-size rewrite with newer mtime blocks Stop' "$(jq -e 'select(.decision == "block")' "$same_size_stop" >/dev/null 2>&1; printf "$?")" "output=$(cat "$same_size_stop")"

legacy_root="$TMP/legacy-digest/.claude"
mkdir -p "$legacy_root/commands/tests"
legacy_target="$legacy_root/commands/legacy.md"
legacy_test="$legacy_root/commands/tests/legacy-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$legacy_test"
chmod +x "$legacy_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $legacy_test -->" '# legacy' >"$legacy_target"
legacy_session=legacy-digest-session
canonical_legacy_target="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$legacy_target")"
canonical_legacy_test="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$legacy_test")"
jq -nc --arg target "$canonical_legacy_target" --arg test "$canonical_legacy_test" --arg runner "$WRAPPER" \
  '{schema:"contract-test-pending-v1",session_id:"legacy-digest-session",target_path:$target,file_path:$target,target_hash:("a"*64),hash:("a"*64),test_paths:[$test],commands:["bash " + $test],updated_at:"2026-01-01T00:00:00Z"}' >"$TMP/pending/$legacy_session.jsonl"
jq -nc --arg target "$canonical_legacy_target" --arg test "$canonical_legacy_test" \
  '{schema:"contract-test-receipt-v1",session_id:"legacy-digest-session",test_path:$test,target_path:$target,target_hash:("a"*64),test_hash:("b"*64),hash:("a"*64),exit:0,exit_code:0,timeout:false,status:"passed",seconds:0.1,duration_seconds:0.1,runner:"wrapper",recorded_at:"2026-01-01T00:00:00Z"}' >"$TMP/runs/$legacy_session.jsonl"
legacy_stop="$TMP/legacy-stop.out"
run_stop "$legacy_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$legacy_stop" 2>"$TMP/legacy-stop.err"
legacy_rc=$?
check 'legacy: old digest-only rows do not crash the Stop gate' "$([ "$legacy_rc" -eq 0 ] && jq -e 'select(.decision == "block")' "$legacy_stop" >/dev/null 2>&1; printf "$?")" "rc=$legacy_rc output=$(cat "$legacy_stop") err=$(cat "$TMP/legacy-stop.err")"
check 'legacy: old digest-only obligation stays pending for a rerun' "$([ -f "$TMP/pending/$legacy_session.jsonl" ] && printf 0 || printf 1)"

key_root="$TMP/session-key/.claude"
mkdir -p "$key_root/commands/tests"
key_target="$key_root/commands/session-key.md"
key_test="$key_root/commands/tests/session-key-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$key_test"
chmod +x "$key_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $key_test -->" '# session key' >"$key_target"
key_session='unsafe/session id'
key_expected="$(python3 -c 'import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:24])' "$key_session")"
run_post "$key_session" "$key_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
check 'identity key: unsafe session id keeps the sha256[:24] receipt filename' "$([ -f "$TMP/runs/$key_expected.jsonl" ] && [ -f "$TMP/pending/$key_expected.jsonl" ] && printf 0 || printf 1)" "expected key=$key_expected runs=$(ls "$TMP/runs" | tr '\n' ' ')"
key_stop="$TMP/session-key-stop.out"
run_stop "$key_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$key_stop" 2>/dev/null
check 'identity key: Stop finds the receipt under the same filename key' "$([ ! -s "$key_stop" ] && printf 0 || printf 1)" "output=$(cat "$key_stop")"

malformed_session=malformed-pending-session
printf '%s\n' 'not-json' >"$TMP/pending/$malformed_session.jsonl"
malformed_stop="$TMP/malformed-stop.out"
run_stop "$malformed_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$malformed_stop" 2>/dev/null
check 'security: malformed pending blocks Stop' "$(jq -e 'select(.decision == "block")' "$malformed_stop" >/dev/null 2>&1; printf "$?")"
check 'security: malformed pending remains present' "$([ -f "$TMP/pending/$malformed_session.jsonl" ] && printf 0 || printf 1)"

symlink_pending_session=symlink-pending-session
symlink_pending_target="$TMP/symlink-pending-outside.jsonl"
printf '%s\n' '{"unrelated":true}' >"$symlink_pending_target"
ln -s "$symlink_pending_target" "$TMP/pending/$symlink_pending_session.jsonl"
symlink_pending_stop="$TMP/symlink-pending-stop.out"
run_stop "$symlink_pending_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >"$symlink_pending_stop" 2>/dev/null
check 'security: symlink pending blocks Stop' "$(jq -e 'select(.decision == "block")' "$symlink_pending_stop" >/dev/null 2>&1; printf "$?")"
check 'security: symlink pending remains present' "$([ -L "$TMP/pending/$symlink_pending_session.jsonl" ] && printf 0 || printf 1)"
check 'security: symlink pending target stays untouched' "$(grep -Fq 'unrelated' "$symlink_pending_target" && printf 0 || printf 1)"

concurrency_root="$TMP/concurrency/.claude"
mkdir -p "$concurrency_root/commands/tests" "$concurrency_root/commands"
concurrency_session=concurrency-session
concurrency_pids=""
for i in 1 2 3 4 5 6 7 8; do
  concurrency_target="$concurrency_root/commands/concurrency-$i.md"
  concurrency_test="$concurrency_root/commands/tests/concurrency-$i-contract.test.sh"
  printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$concurrency_test"
  chmod +x "$concurrency_test"
  printf '%s\n' "<!-- 本檔在契約測試底下：bash $concurrency_test -->" "# concurrency-$i" >"$concurrency_target"
  run_post "$concurrency_session" "$concurrency_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null &
  concurrency_pids="$concurrency_pids $!"
done
for concurrency_pid in $concurrency_pids; do
  wait "$concurrency_pid"
done
concurrency_pending="$TMP/pending/$concurrency_session.jsonl"
concurrency_rows=0
[ -f "$concurrency_pending" ] && concurrency_rows=$(wc -l <"$concurrency_pending" | tr -d ' ')
check 'security: concurrent pending updates retain all rows' "$( [ "$concurrency_rows" = 8 ] && printf 0 || printf 1 )" "rows=$concurrency_rows"

escaped_root="$TMP/discovery-timeout/.claude"
mkdir -p "$escaped_root/commands/tests" "$escaped_root/commands"
escaped_target="$escaped_root/commands/discovery-timeout.md"
escaped_test="$escaped_root/commands/tests/discovery-timeout-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$escaped_test"
chmod +x "$escaped_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $escaped_test -->" '# discovery timeout' >"$escaped_target"
escaped_child="$TMP/discovery-child.py"
escaped_driver="$TMP/discovery-driver.py"
escaped_helper="$TMP/discovery-helper.sh"
printf '%s\n' 'import time' 'time.sleep(5)' >"$escaped_child"
printf '%s\n' 'import subprocess' 'import sys' 'import time' "subprocess.Popen([sys.executable, '$escaped_child'], start_new_session=True)" 'time.sleep(5)' >"$escaped_driver"
printf '%s\n' '#!/usr/bin/env bash' "exec python3 '$escaped_driver'" >"$escaped_helper"
chmod +x "$escaped_helper"
escaped_started=$(python3 -c 'import time; print(time.monotonic())')
env CONTRACT_TEST_TOTAL_TIMEOUT_SECONDS=0.1 CONTRACT_TEST_SESSION_ID=discovery-timeout-session \
  CONTRACT_TEST_CWD="$(dirname "$escaped_target")" CONTRACT_TEST_RUNS_DIR="$TMP/runs" \
  CONTRACT_TEST_PENDING_DIR="$TMP/pending" CONTRACT_TEST_STATE_DIR="$TMP/state" \
  CONTRACT_TEST_DISABLED_SENTINEL="$disabled" CONTRACT_TEST_HELPER="$escaped_helper" \
  "$WRAPPER" "$escaped_target" >"$TMP/discovery-timeout.out" 2>"$TMP/discovery-timeout.err"
escaped_rc=$?
escaped_finished=$(python3 -c 'import time; print(time.monotonic())')
escaped_elapsed=$(python3 -c 'import sys; print(float(sys.argv[2]) - float(sys.argv[1]))' "$escaped_started" "$escaped_finished")
check 'security: helper discovery honors total timeout' "$(python3 -c 'import sys; print(0 if float(sys.argv[1]) < 1.5 else 1)' "$escaped_elapsed")" "elapsed=$escaped_elapsed rc=$escaped_rc"
check 'security: timed out helper reports discovery timeout' "$(grep -Fq 'timed out' "$TMP/discovery-timeout.err" && printf 0 || printf 1)"

recovery_root="$TMP/recovery path/.claude"
mkdir -p "$recovery_root/commands/tests" "$recovery_root/commands"
recovery_target="$recovery_root/commands/recovery target.md"
recovery_test="$recovery_root/commands/tests/recovery test.test.sh"
recovery_runner="$TMP/runner with space"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$recovery_test"
chmod +x "$recovery_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash '$recovery_test' -->" '# recovery' >"$recovery_target"
cp "$WRAPPER" "$recovery_runner"
chmod +x "$recovery_runner"
recovery_session='recovery session'
run_post "$recovery_session" "$recovery_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" 30 30 "$recovery_runner" >/dev/null 2>/dev/null
printf '%s\n' '# changed recovery target' >"$recovery_target"
recovery_stop="$TMP/recovery-stop.out"
run_stop "$recovery_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" 3 6 "$recovery_runner" >"$recovery_stop" 2>/dev/null
recovery_canonical_target="$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$recovery_target")"
check 'security: recovery command uses configured runner' "$(grep -Fq "$(printf "'%s'" "$recovery_runner")" "$recovery_stop" && printf 0 || printf 1)" "output=$(cat "$recovery_stop")"
check 'security: recovery command quotes session and path' "$(grep -Fq "$(printf "'%s'" "$recovery_session")" "$recovery_stop" && grep -Fq "$(printf "'%s'" "$recovery_canonical_target")" "$recovery_stop" && printf 0 || printf 1)" "output=$(cat "$recovery_stop")"

nonpositive_root="$TMP/nonpositive-loopguard/.claude"
mkdir -p "$nonpositive_root/commands/tests" "$nonpositive_root/commands"
nonpositive_target="$nonpositive_root/commands/nonpositive.md"
nonpositive_test="$nonpositive_root/commands/tests/nonpositive-contract.test.sh"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$nonpositive_test"
chmod +x "$nonpositive_test"
printf '%s\n' "<!-- 本檔在契約測試底下：bash $nonpositive_test -->" '# nonpositive' >"$nonpositive_target"
nonpositive_session=nonpositive-loopguard-session
run_post "$nonpositive_session" "$nonpositive_target" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" >/dev/null 2>/dev/null
printf '%s\n' '# changed nonpositive target' >"$nonpositive_target"
nonpositive_stop="$TMP/nonpositive-stop.out"
run_stop "$nonpositive_session" "$TMP/runs" "$TMP/pending" "$TMP/state" "$disabled" 0 0 >"$nonpositive_stop" 2>/dev/null
check 'security: nonpositive loop limits do not release first call' "$(jq -e 'select(.decision == "block")' "$nonpositive_stop" >/dev/null 2>&1; printf "$?")"

if python3 - "$ROOT/settings.json" <<'PY'
import json
import sys
from pathlib import Path

settings = json.loads(Path(sys.argv[1]).read_text())
post_groups = settings.get("hooks", {}).get("PostToolUse", [])
stop_groups = settings.get("hooks", {}).get("Stop", [])
post = [
  hook.get("command", "")
  for group in post_groups
  if group.get("matcher") == "Edit|Write"
  for hook in group.get("hooks", [])
]
stop = [
  hook.get("command", "")
  for group in stop_groups
  for hook in group.get("hooks", [])
]
assert post.count("~/.claude/hooks/contract-test-receipt-gate.sh") == 1
assert stop.count("~/.claude/hooks/contract-test-receipt-gate.sh") == 1
assert sum("contract-test-receipt-gate.sh" in command for command in post + stop) == 2
print("PASS settings.json wires PostToolUse Edit|Write and Stop once each")
PY
then
  PASS=$((PASS + 1))
else
  printf '%s\n' 'FAIL settings.json wires PostToolUse Edit|Write and Stop once each'
  FAIL=$((FAIL + 1))
fi

printf '%s\n' '----'
printf 'pass=%s fail=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
