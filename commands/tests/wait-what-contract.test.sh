#!/bin/bash
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
WAIT="$ROOT/commands/wait-what.md"
PASS=0
FAIL=0

check() {
  local name="$1"
  local expected="$2"
  if grep -qF -- "$expected" "$WAIT"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

check_absent() {
  local name="$1"
  local unexpected="$2"
  if grep -qF -- "$unexpected" "$WAIT"; then
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  else
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  fi
}

check "標示契約測試跑法" "wait-what-contract.test.sh"
check "回傳前執行三題自查" "回傳前自查三題"
check "自查結論位置" "結論在前兩行"
check "自查單句單意" "有沒有一句塞兩個意思"
check "自查術語註解" "術語都有白話註解"
check "STE 只借原則，不宣稱英文合規" "借用 ASD-STE100 的清晰表達原則，不宣稱符合英文標準"
check "STE 明確寫出動作者" "寫清楚誰做什麼"
check "STE 同一概念使用同一名稱" "同一概念沿用同一名稱"
check "STE 必要條件放在動作前" "條件影響動作或結論時先寫條件"
check "壓縮不刪必要條件與不確定性" "保留必要條件、例外與不確定性"
check "依摩擦協議記錄" "~/.claude/friction/PROTOCOL.md"
check "跟丟原因寫入全域摩擦紀錄" "~/.claude/friction/workflow-general.md"
check_absent "已移除 Archify 互動圖分支" "Archify"
check_absent "已移除跨邊界視覺 nudge" "跨 boundary"
check_absent "已移除畫圖選項" "a. 畫圖  b. 不用"
check "摩擦敘事採資料最小化" "原因＋影響＋建議方向"
check "摩擦不搬原始外部內容" "不搬 user 原話、log、error 或 code"
check "必要短引文先遮敏" "短 sanitized excerpt"
check "摩擦來源帶 session provenance" "source_ref=session:<id>#<turn>"
check "摩擦 owner 帶 skill target" "target=skill:<name>"
check "候選 flag 僅作 annotation" "候選 flag 只 annotation、不影響 append"

printf '\n%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
