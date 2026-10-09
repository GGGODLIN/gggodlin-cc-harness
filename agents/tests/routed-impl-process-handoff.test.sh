#!/bin/bash
set -u

AGENT="$HOME/.claude/agents/routed-impl.md"
IMPLEMENT="$HOME/.claude/skills/implement/SKILL.md"
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

check_file_contains() {
  local file="$1"
  local text="$2"
  local label="$3"
  if grep -Fq "$text" "$file"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

check_contains '流程由 caller 決定' 'caller owns the process decision'
check_contains 'local pipeline（`brainstorm` → `to-spec` → `to-tickets` → `implement`）' 'contract names the local pipeline'
check_contains '續作不得再次詢問' 'continuation does not reopen the decision'
check_contains '不得直接向使用者詢問流程或自行換流程' 'subagent cannot ask the user again'
check_contains 'BLOCKED: missing selected process' 'missing context returns a caller-facing blocker'
check_file_contains "$IMPLEMENT" '既有流程續作狀態：implement' 'implement workers carry process continuation'

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
test "$FAIL" -eq 0
