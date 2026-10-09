#!/bin/bash
set -u

SKILL="$HOME/.claude/skills/debugging/SKILL.md"
PASS=0
FAIL=0

check() {
  local text="$1"
  local label="$2"
  if grep -Fq "$text" "$SKILL"; then
    printf 'PASS: %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL: %s\n' "$label"
    FAIL=$((FAIL + 1))
  fi
}

check '本檔在契約測試底下：bash ~/.claude/skills/debugging/scripts/tests/presentation-shape.test.sh' 'skill declares its contract test'
check '觀察到什麼 → 哪一步首次由正確變錯誤 → 根因 → 下一步' 'root-cause report has a fixed shape'
check 'call tree／狀態流' 'multi-layer failures show one shape line'
check '先輸出問題形狀，再附假設表與證據表' 'evidence follows the failure shape'
check 'shape-first report' 'quick reference exposes the reporting criterion'

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
test "$FAIL" -eq 0
