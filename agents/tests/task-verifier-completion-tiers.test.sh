#!/bin/bash
set -u

AGENT="$HOME/.claude/agents/task-verifier.md"
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

check_contains 'Keep completion tiers separate' 'completion tiers are an explicit contract'
check_contains 'Implemented is not deployed; deployed is not externally verified.' 'earlier completion tiers cannot imply later tiers'
check_contains 'Evidence for an earlier tier cannot prove a later tier.' 'tier evidence is scoped'
check_contains 'at least one adjacent probe' 'behavior verification probes beside the claim'
check_contains 'state why no meaningful adjacent case exists' 'adjacent probe exception is explicit'

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
test "$FAIL" -eq 0
