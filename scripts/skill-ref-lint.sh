#!/usr/bin/env bash
# skill-ref-lint.sh — skill/command 文件 stale 引用檢查（doc-invariant lint）
#
# 概念來源：ruvnet/ruflo「plugin 契約文件 + smoke grep 驗 stale 用詞」抽件（2026-07-14）。
# 痛點：skill/command markdown 引用的腳本路徑，實體改名/刪除後文件不會跟上
#（前例：PullMD 退役後兩度被當 mature 分母）。
#
# v1 範圍：只驗「本機絕對路徑引用的實體存在」。flag 存在性驗證（parse 目標
# script 的參數表）留待 trial review 再決定要不要做。
#
# 用法：
#   skill-ref-lint.sh              # 掃 ~/.claude/skills + ~/.claude/commands
#   skill-ref-lint.sh <dir>...     # 掃指定目錄（fixture 測試用）
#
# 輸出：每筆 "檔案:行號: 缺失路徑"；結尾統計行。無缺失 → 只有統計行、exit 0。
set -u

DIRS=("$@")
if [[ ${#DIRS[@]} -eq 0 ]]; then
  DIRS=("$HOME/.claude/skills" "$HOME/.claude/commands")
fi

missing=0
checked=0

while IFS= read -r md; do
  while IFS=: read -r lineno line; do
    while IFS= read -r raw; do
      [[ -z "$raw" ]] && continue
      # 展開 ~ / $HOME
      path="${raw/#\~/$HOME}"
      path="${path/#\$HOME/$HOME}"
      # 去尾端標點（中英句讀、括號、反引號）
      path="${path%%[,)。，、；;\`\"]*}"
      path="${path%/}"
      # 含 placeholder / glob / 變數殘留 → 跳過
      [[ "$path" == *'<'* || "$path" == *'>'* || "$path" == *'*'* || \
         "$path" == *'{'* || "$path" == *'$('* || "$path" == *'YYYY'* || \
         "$path" == *'XXX'* ]] && continue
      # 動態檔名前綴（quota-<ts> 這型）、省略號示例、空白路徑斷詞殘片 → 跳過
      [[ "$path" == *- || "$path" == *_ || "$path" == *'...'* || \
         "$path" == "$HOME/Library/Application" ]] && continue
      # 佔位假名（文件舉例用：foo / entity-X / abc123de 型 session id）→ 跳過（R2 2026-07-21）
      [[ "$path" == */foo || "$path" == */foo/* || "$path" == *__foo__* || \
         "$path" == "$HOME/project/"* || "$path" == *entity-X* || \
         "$path" =~ [0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]{8}-session ]] && continue
      # runtime 產物（執行期才生成、非 repo 實體：monitor state / review-zh 產出 / research_output / sessions）→ 跳過（R2 2026-07-21）
      [[ "$path" == *-state.json || "$path" == "$HOME/.claude/review-zh/"* || \
         "$path" == "$HOME/.claude/research_output"* || "$path" == "$HOME/.claude/sessions/"* ]] && continue
      # 太短（如純 ~/）跳過
      [[ "${#path}" -lt 8 ]] && continue
      ((checked++))
      if [[ ! -e "$path" ]]; then
        echo "${md#$HOME/}:$lineno: $raw"
        ((missing++))
      fi
    done < <(grep -oE '(~|\$HOME|~)/[A-Za-z0-9_.@/-]+' <<<"$line" | sort -u)
  done < <(grep -nE '(~|\$HOME|~)/' "$md" 2>/dev/null || true)
done < <(find "${DIRS[@]}" -name '*.md' -type f 2>/dev/null)

echo "---- checked $checked path refs, $missing missing ----"
exit 0
