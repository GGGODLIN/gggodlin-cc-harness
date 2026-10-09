#!/bin/bash
set -uo pipefail

ROOT="$HOME/.claude/skills/handoff-impl"
SKILL="$ROOT/SKILL.md"
TEMPLATE="$ROOT/references/file-template.md"
DESIGN="$ROOT/design.md"
PASS=0
FAIL=0

check() {
  local name="$1"
  local file="$2"
  local expected="$3"
  if grep -qF -- "$expected" "$file"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

check "Create 標示 ENV_READY 證據邊界" "$SKILL" "驗證者 / 執行環境"
check "Create 標示未驗證機制路徑" "$SKILL" "機制路徑若未對完整 code chain 實證"
check "Implementer 使用 round_base" "$SKILL" "round_base...HEAD"
check "Verifier 有非 Git 分支" "$SKILL" "非 Git 任務改用回報檔案清單與驗收產物逐項核對"
check "同輪重試使用 Attempt" "$SKILL" "Attempt <N>"
check "Template 宣告 round_base" "$TEMPLATE" "round_base: <"
check "Template ENV_READY 標示執行邊界" "$TEMPLATE" "| 前置 | 驗證者 | 執行環境 |"
check "Template 定義 Round 與 Attempt" "$TEMPLATE" "Round 只代表 verifier 退回輪次"
check "Design 同步 round_base" "$DESIGN" "round_base"
check "Design 同步證據執行環境" "$DESIGN" "驗證者 / 執行環境"

printf '\n%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
