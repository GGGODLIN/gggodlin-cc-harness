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

assert_grep "skill marks this contract test" '本檔在契約測試底下.*preflight-contract\.test\.sh'
assert_grep "listening port is discovery only" 'listening port.*discovery only'
assert_grep "shared daemon checks owner PID" 'owner PID'
assert_grep "shared daemon checks process cwd" 'process cwd'
assert_grep "shared daemon checks build identity" 'build identity'
assert_grep "shared daemon runs real runtime probe" 'real runtime probe'
assert_grep "done requires intended worktree identity" 'shared daemon.*intended worktree.*before dispatch'
assert_grep "browser E2E branch requires explicit acceptance" "ticket's acceptance explicitly requires browser E2E"
assert_grep "browser E2E state belongs to implementation owner" 'implementation owner makes that checkpoint reproducible'
assert_grep "browser E2E state covers required surfaces" 'test data, account state, feature flags, permissions, integrations, and service state'
assert_grep "browser runner does not improvise setup" 'browser runner.*unrelated UI flows'
assert_grep "test setup is inaccessible in production" 'inaccessible in production'
assert_grep "test setup is gated and authenticated" 'approved test environments, authenticated where appropriate'
assert_grep "test setup is narrow and repeatable" 'narrowly scoped, and safe to call repeatedly'
assert_grep "test setup forbids backdoors and encoded behavior" 'production backdoor.*weaken production authorization.*encode the behavior under test'
assert_grep "non-browser tickets skip E2E branch" 'Tickets without browser E2E acceptance skip this branch'

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
