#!/bin/bash
set -u

AGENT="$HOME/.claude/agents/code-reviewer.md"
PASS=0
FAIL=0

check_contains() {
  local text="$1"
  local label="$2"
  if grep -Fq "$text" "$AGENT"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

check_contains 'Bounded degraded modes' 'degraded modes are an explicit review check'
check_contains 'catch, fallback, retry, or skip-and-continue' 'rule has a narrow trigger'
check_contains 'degraded state is observable' 'degradation must be visible'
check_contains 'explicit threshold that escalates or aborts' 'degradation has a bound'
check_contains 'Do not require every layer to log' 'rule avoids duplicate logging'

if grep -Fq 'Every failure path must log' "$AGENT"; then
  printf 'FAIL: mandatory logging was not copied\n'
  FAIL=$((FAIL + 1))
else
  printf 'PASS: mandatory logging was not copied\n'
  PASS=$((PASS + 1))
fi

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
test "$FAIL" -eq 0
