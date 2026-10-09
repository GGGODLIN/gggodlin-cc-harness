#!/bin/bash
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
SAVE="$ROOT/commands/save-session.md"
PASS=0
FAIL=0

check() {
  local name="$1"
  local expected="$2"
  if grep -qF -- "$expected" "$SAVE"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

R6_LINE=$(grep -F 'R6【secret 形跡】' "$SAVE")

check_r6() {
  local name="$1"
  local expected="$2"
  if printf '%s' "$R6_LINE" | grep -qF -- "$expected"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

check "R1 允許摘要式 short-id" "short-id 可以是人類可讀的摘要式命名"
check "R2 接受語意等效空句" "語意等效的空內容句子 = PASS"
check "R2 允許選填 Environment section" "\`Environment & Setup Notes\` 是合法選填 section"
check "R6 保留非 secret DSN 部分" "secret 值已遮蔽或改為佔位符時，非 secret 部分保留原樣 = PASS"
check "R6 使用封閉列舉" "本欄是封閉列舉"
check "R6 排除一般識別碼" "sha256 內容雜湊、UUID、spreadsheet／document ID"
check_r6 "R6 列出 sk-" '`sk-`'
check_r6 "R6 列出 ghp_" '`ghp_`'
check_r6 "R6 列出 AKIA" '`AKIA`'
check_r6 "R6 列出 xoxb" '`xoxb`'
check_r6 "R6 列出 password=" '`password=`'
check_r6 "R6 列出內嵌密碼 URL" '`://user:pass@`'
check_r6 "R6 列出 PEM block" "PEM block"

printf '\n%s PASS / %s FAIL\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
