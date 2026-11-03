#!/bin/bash
set -u

SKILL="${GATE_AUTHORING_SKILL:-$(cd "$(dirname "$0")/../.." && pwd)/SKILL.md}"
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
check_contains '跨 session 授權外洩不一定在單 session 測試裡現形' 'rule names the cross-session permit leak'
check_contains '不追加內容 hash 或沒有既有消費端的替代驗證' 'permit scope does not create content verification'
check_contains '當次 session、permit 身分、期限與單次消耗狀態' 'permit binding follows identity fields'
check_contains '需要確認內容相等時沿用已有的原文比對' 'content equality reuses the existing text comparison'
check_contains '不因記錄缺失或過期重做' 'bookkeeping alone does not replay correct results'
for stale in '要防就把被呼叫檔的 hash 也綁進 permit' 'session、內容 hash、單次消耗' '被驗檔案 hash'; do
  if command grep -Fq -- "$stale" "$SKILL"; then
    printf 'FAIL: stale content-hash instruction: %s\n' "$stale"
    FAIL=$((FAIL + 1))
  else
    printf 'PASS: no stale content-hash instruction: %s\n' "$stale"
    PASS=$((PASS + 1))
  fi
done
check_contains '回合邊界' 'rule names per-turn gate boundaries'
check_contains 'origin／turnOrigin／promptSource' 'rule inventories real transcript origin fields'
check_contains 'task-notification／peer／tool result／meta' 'rule pairs reset and non-reset event classes'

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
test "$FAIL" -eq 0
