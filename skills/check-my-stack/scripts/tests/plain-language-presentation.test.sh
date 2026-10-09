#!/bin/bash
set -u

SKILL="$HOME/.claude/skills/check-my-stack/SKILL.md"
TEMPLATE="$HOME/.claude/skills/check-my-stack/references/output-template.md"
PASS=0
FAIL=0

check_contains() {
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

check_contains "$TEMPLATE" '## 先用白話回答' 'template starts with a plain-language answer section'
check_contains "$TEMPLATE" '直接回答使用者原問句' 'opening answers the original question'
for item in '**結論**' '**它是什麼**' '**跟你現有的差在哪**' '**用了會得到什麼**' '**代價**' '**依結論二選一**'; do
  check_contains "$TEMPLATE" "$item" "opening fixes six-item slot $item"
done
check_contains "$TEMPLATE" '不為它多跑任何步驟' 'six items summarize existing blocks without extra steps'
check_contains "$TEMPLATE" 'extract／frame／Gate Ledger／商數／maturity／reconcile' 'opening names internal jargon to keep out'
check_contains "$TEMPLATE" '先用白話回答 → Block 1 → Block 2 → Block 3 → Block 4 → Gate Ledger → Verdict' 'template defines user-first order'
check_contains "$SKILL" '先依 output-template「先用白話回答」段的六項依序作答' 'presentation step requires the six-item plain-language opening'
check_contains "$SKILL" '白話開頭是否依序含六項' 'self-verify checks the six-item opening'
check_contains "$SKILL" '先用白話回答 → Block 1 → Block 2 → Block 3 → Block 4 → Gate Ledger → Verdict' 'self-verify checks the user-first order'
check_contains "$SKILL" '退役／缺口盤點路徑' 'skill defines the retirement gap route'
check_contains "$SKILL" '缺什麼／哪些已對應／退役前做哪三件' 'retirement route fixes the chat report shape'
check_contains "$SKILL" '完整 Blocks 1–4 與 Gate Ledger 寫入證據副檔' 'retirement route keeps the full audit in a sidecar'
check_contains "$SKILL" '退役／缺口盤點路徑的 self-verify 狀態只寫進證據副檔' 'retirement route keeps verification metadata out of chat'
check_contains "$SKILL" '若使用者請求符合上方退役／缺口盤點路徑' 'presentation branch keys directly off the user request'
check_contains "$SKILL" '若使用者請求符合上方退役／缺口盤點路徑，聊天只輸出 `缺什麼／哪些已對應／退役前做哪三件` 與證據副檔連結，不把完整 blocks 或 self-verify 行貼回聊天。' 'Step 8 excludes full audit and verification metadata from chat'
check_contains "$TEMPLATE" '## 退役／缺口盤點路徑' 'template defines the retirement gap route'
check_contains "$TEMPLATE" '缺什麼／哪些已對應／退役前做哪三件' 'template defines the three-part retirement report'
check_contains "$TEMPLATE" '完整 Blocks 1–4 與 Gate Ledger 寫入證據副檔' 'template sends the full audit to the sidecar'

check_contains "$SKILL" '預設路徑聊天只輸出白話主報告與證據副檔連結' 'default route keeps chat to the plain-language main report plus sidecar link'
check_contains "$SKILL" '完整 Blocks 1–4 與 Gate Ledger 寫入證據副檔，不貼回聊天' 'default route sends the full blocks to the sidecar'
check_contains "$TEMPLATE" '預設路徑的聊天主報告' 'template defines the default-route chat main report'

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
test "$FAIL" -eq 0
