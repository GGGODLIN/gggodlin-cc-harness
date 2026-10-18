#!/bin/bash
# 跨檔字串依賴：下方報告的「🎯 建議處理」heading 必須與
# ~/.claude/hooks/daily-local-analysis-trigger.sh 第 12 條的排檔條件逐字一致。
# 兩邊任一改字，digest 的超標提醒會靜默失效（代價只是提醒不出現，故未配測試）。
# 零使用段的「## 🪦 零使用規則候選（N）」heading 由 session-audit.py zero-use 輸出，
# 同一個 hook 也逐字比對它，有同樣的依賴；「🎯 建議處理」只在超標時出現，未超標但有候選時不能寫。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd /
set -euo pipefail

PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:~/.local/bin"
export PATH

# 以下 RULES_SIZE_* / SESSION_AUDIT_* 覆寫只給測試把路徑導到臨時目錄用。
REPO_DIR="${RULES_SIZE_REPO_DIR:-$HOME/code/social-info}"
OUT_DIR="$REPO_DIR/reports/local-analysis"
LOG_DIR="$REPO_DIR/logs"

mkdir -p "$OUT_DIR" "$LOG_DIR"
DATE="${LOCAL_ANALYSIS_DATE:-$(date +%Y-%m-%d)}"
OUT="$OUT_DIR/$DATE-rules-size.md"
LOG="$LOG_DIR/local-analysis-rules-size-$DATE.log"

# P-len 門檻（harness-audit-2026-07-03 拍板；env 可覆寫供測試）
# 校準依據補充（2026-07-11 自 HumanLayer "Writing a Good CLAUDE.md" 收）：
# LLM 可穩定遵循 ~150-200 條 instruction（CC system prompt 已占 ~50 條）、
# 單檔理想 <300 行、prompt 周邊位置（開頭/結尾）注意力較高。
# byte cap 是 proxy——若未來要調 cap，用「指令條數」重新換算而非直接放大 bytes。
# 2026-09-22 使用者拍板 CLAUDE.md cap 12288 → 14000：09-03 瘦身到 13058 後三週長回 13718，選擇認了不再砍。
CLAUDE_HOME="${RULES_SIZE_CLAUDE_HOME:-$HOME/.claude}"
CLAUDE_MD="$CLAUDE_HOME/CLAUDE.md"
CLAUDE_CAP="${RULES_SIZE_CLAUDE_CAP:-14000}"   # 14KB（2026-09-22 起）
RULE_CAP="${RULES_SIZE_RULE_CAP:-9728}"        # 9.5KB
TOTAL_CAP="${RULES_SIZE_TOTAL_CAP:-46080}"     # 45KB

# 零使用候選清單（唯讀、不呼叫模型）：state 與 rules repo 走 session-audit.py 的 production 預設。
# python 不能用 /usr/bin/python3（3.9，session-audit.py 要 3.11+）。
ZERO_PY="${SESSION_AUDIT_PYTHON:-/opt/homebrew/bin/python3}"
ZERO_SCRIPT="${RULES_SIZE_ZERO_USE_SCRIPT:-$SCRIPT_DIR/session-audit.py}"
ZERO_ARGS=(zero-use)
[ -z "${SESSION_AUDIT_STATE:-}" ] || ZERO_ARGS+=(--state "$SESSION_AUDIT_STATE")
[ -z "${RULES_SIZE_RULES_REPO:-}" ] || ZERO_ARGS+=(--rules-repo "$RULES_SIZE_RULES_REPO")

{
  echo "=== rules-size weekly started: $(date) ==="

  VIOLATIONS=$(mktemp)
  ZERO_OUT=$(mktemp)
  ZERO_ERR=$(mktemp)
  trap 'rc=$?; rm -f "$VIOLATIONS" "$ZERO_OUT" "$ZERO_ERR"; exit $rc' EXIT
  TOTAL=0

  check_file() {
    local f="$1" cap="$2"
    [ -f "$f" ] || return 0
    local size
    size=$(wc -c < "$f" | tr -d ' ')
    TOTAL=$((TOTAL + size))
    if [ "$size" -gt "$cap" ]; then
      echo "| \`$f\` | $size | $cap | 超 $((size - cap)) bytes |" >> "$VIOLATIONS"
    fi
  }

  check_file "$CLAUDE_MD" "$CLAUDE_CAP"
  for f in "$CLAUDE_HOME"/rules/common/*.md "$CLAUDE_HOME"/rules/external/*.md; do
    check_file "$f" "$RULE_CAP"
  done

  TOTAL_LINE=""
  if [ "$TOTAL" -gt "$TOTAL_CAP" ]; then
    TOTAL_LINE="⚠️ scope 總和 ${TOTAL} bytes 超過 cap ${TOTAL_CAP}（45KB）"
  fi

  HIT_COUNT=$(wc -l < "$VIOLATIONS" | tr -d ' ')

  # zero-use 失敗不讓週報整份失敗：記原因、報告照常產生。失敗也不靜默，否則這段會無聲消失。
  ZERO_COUNT=""
  ZERO_FAIL=""
  if "$ZERO_PY" "$ZERO_SCRIPT" ${ZERO_ARGS[@]+"${ZERO_ARGS[@]}"} > "$ZERO_OUT" 2> "$ZERO_ERR"; then
    ZERO_COUNT=$(sed -n '1s/^## 🪦 零使用規則候選（\([0-9][0-9]*\)）$/\1/p' "$ZERO_OUT")
    [ -n "$ZERO_COUNT" ] || ZERO_FAIL="輸出沒有零使用段 heading"
  else
    ZERO_FAIL="$(head -n 1 "$ZERO_ERR" | tr -d '\r')"
    [ -n "$ZERO_FAIL" ] || ZERO_FAIL="指令異常結束"
  fi

  OVER=0
  if [ "$HIT_COUNT" -gt 0 ] || [ -n "$TOTAL_LINE" ]; then OVER=1; fi

  if [ "$OVER" -eq 0 ] && [ -z "$ZERO_FAIL" ] && [ "$ZERO_COUNT" -eq 0 ]; then
    printf '__SILENT__' > "$OUT"
    echo "all within caps (total=$TOTAL bytes), no zero-use candidates, __SILENT__"
  else
    {
      echo "# Rules 檔長度健康度 Weekly — $DATE"
      echo ""
      if [ "$OVER" -eq 1 ]; then
        echo "**門檻（P-len、harness-audit-2026-07-03 拍板）**：CLAUDE.md ≤ ${CLAUDE_CAP} bytes、rules 檔 ≤ ${RULE_CAP} bytes、scope 總和 ≤ ${TOTAL_CAP} bytes"
        echo "**Scope**：~/.claude/CLAUDE.md + rules/common/*.md + rules/external/*.md（不含 MEMORY.md、project CLAUDE.md）"
        echo ""
        if [ "$HIT_COUNT" -gt 0 ]; then
          echo "## 超標檔案（${HIT_COUNT}）"
          echo ""
          echo "| 檔案 | 現況 bytes | Cap | 超標量 |"
          echo "|---|---|---|---|"
          cat "$VIOLATIONS"
          echo ""
        fi
        if [ -n "$TOTAL_LINE" ]; then
          echo "$TOTAL_LINE"
          echo ""
        fi
        echo "## 🎯 建議處理"
        echo ""
        echo "找出該砍哪幾段、產草稿逐段拍板：\`/rules-slim\`（手動觸發，排檔不會自動跑它）"
        echo ""
        echo "瘦身方向：刪過時段落、下放 memory cluster、或砍掉已有 hook 覆蓋的散文（詳細規則與歷史脈絡見 ~/Desktop/projects/harness-audit-2026-07-03.md P-len 段）。門檻的目的是強迫「先刪再加」、不是禁止成長——確有必要成長時調 cap 並在本 wrapper 檔頭留一行原因。"
      fi
      echo ""
      if [ -n "$ZERO_FAIL" ]; then
        # daily-local 只原文保留含 ⚠️ 的行；沒有它，失敗行會在摘要裡消失。
        echo "⚠️ 零使用清單產生失敗：$ZERO_FAIL"
      else
        cat "$ZERO_OUT"
      fi
    } > "$OUT"
    echo "violations=$HIT_COUNT total=$TOTAL → report written"
  fi

  echo "=== rules-size weekly finished: $(date) ==="
  echo "Output: $OUT ($(wc -c < "$OUT") bytes)"
} >> "$LOG" 2>&1
