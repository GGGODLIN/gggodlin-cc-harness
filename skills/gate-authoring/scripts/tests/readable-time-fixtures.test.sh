#!/bin/bash
set -u

SKILL="$HOME/.claude/skills/gate-authoring/SKILL.md"
PASS=0
FAIL=0

check_contains() {
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

check_contains 'fixture 內含 epoch／Unix timestamp' 'rule targets opaque epoch fixtures'
check_contains '完整時間與時區的 ISO-8601' 'rule requires a complete readable source time'
check_contains '常數旁保留等價 ISO-8601' 'rule allows readable annotation beside constants'
check_contains '不要只用 `date -j -f "%Y-%m-%d"`' 'rule rejects date-only macOS conversion'
check_contains '會繼承執行當下的時分秒' 'rule explains the date-only failure mode'

check_contains '談論該指令的文字' 'threat model names talk-about-the-command false positives'
check_contains 'fixture 之外再做一次真實環境 known-bad 實測' 'rule requires a real-environment deny probe beyond fixtures'
check_contains '三項綁定缺一就是跨 session 授權外洩' 'rule names the cross-session permit leak'
check_contains '回合邊界' 'rule names per-turn gate boundaries'
check_contains 'origin／turnOrigin／promptSource' 'rule inventories real transcript origin fields'
check_contains 'task-notification／peer／tool result／meta' 'rule pairs reset and non-reset event classes'

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
test "$FAIL" -eq 0
