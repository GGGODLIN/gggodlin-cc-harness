#!/bin/bash
set -u

# 檢查項搬到審查標準正本後，斷言改到正本找；根目錄可用 REVIEW_STANDARDS_ROOT 指定（測 worktree 或隔離副本）
ROOT="${REVIEW_STANDARDS_ROOT:-$HOME/.claude}"
AGENT="$ROOT/review-standards/code-review-quality.md"
DEFINITION="$ROOT/agents/code-reviewer.md"
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

# 正本不存在時不能因為「找不到字」而過
if [ ! -f "$AGENT" ] || grep -Fq 'Every failure path must log' "$AGENT" "$DEFINITION"; then
  printf 'FAIL: mandatory logging was not copied\n'
  FAIL=$((FAIL + 1))
else
  printf 'PASS: mandatory logging was not copied\n'
  PASS=$((PASS + 1))
fi

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
test "$FAIL" -eq 0
