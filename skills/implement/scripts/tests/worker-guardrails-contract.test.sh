#!/usr/bin/env bash
set -u

SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/SKILL.md"
PASS=0
FAIL=0

assert_grep() {
  local label=$1 pattern=$2
  if grep -qE "$pattern" "$SKILL"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

assert_grep "skill marks worker guardrails contract" '本檔在契約測試底下.*worker-guardrails-contract\.test\.sh'
assert_grep "worker cannot dispatch child Agent" 'Do not call Agent|worker never creates its own child Agent'
assert_grep "worker returns delegation request" 'NEEDS_DELEGATION'
assert_grep "controller owns delegated Agent calls" 'controller owns every delegated Agent call'
assert_grep "delegation resume rearms watchdog" 'resumed turn.*new background dispatch.*return to step 2.*fresh.*reminderTaskId'
assert_grep "tool denial returns blocked" 'tool call is denied.*BLOCKED:'
assert_grep "tool denial permits safe fallback" 'safe path that does not use that tool'
assert_grep "controller launches executable reminder" 'Bash\(run_in_background=true\): sleep 1200'
assert_grep "controller records separate task handles" 'workerTaskId.*reminderTaskId'
assert_grep "controller creates rearmed twenty-minute check" '20-minute progress check that is re-armed|re-armed on every continue decision'
assert_grep "watchdog rearms after verified progress" 'let the worker continue and immediately arm a fresh .reminderTaskId'
assert_grep "watchdog never leaves a live worker unobserved" 'no live worker is ever left without a scheduled next look|no other scheduled observer'
assert_grep "controller cancels reminder by handle" 'TaskStop.*reminderTaskId'
assert_grep "watchdog uses exact non-blocking retrieval" 'TaskOutput.*workerTaskId.*block: false.*timeout: 1000'
assert_grep "watchdog stops only the worker handle" 'TaskStop.*workerTaskId'
assert_grep "watchdog never stops automatically" 'must not automatically stop'
assert_grep "guardrails are wired before dispatch" 'Before dispatching each worker|派出每支 worker 前'

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
