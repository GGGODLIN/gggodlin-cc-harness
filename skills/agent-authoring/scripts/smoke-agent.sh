#!/bin/bash
# smoke-agent.sh <agent-name> — agent 定義檔上線前的磁碟 side-effect smoke test
#
# 為什麼要有這支：2026-07-27 routed-* 事故——tools: [] 讓 agent 零工具，
# 模型把 tool call 吐成文字再幻覺假結果（連 git status 輸出都編得出來）。
# 只驗 jsonl 的 model/effort 解析值抓不到這型失敗（07-26 smoke 4/4 過、隔天 live 全滅）。
# 判準必須是「headless 新 process + 磁碟上真的出現 side-effect 檔」。
#
# headless 新 process = 重新載入定義檔（agent 檔 per-session 載入，
# 在既有 session 內改檔測不到）；等效開新 session。
#
# Exit: 0 = PASS（tool call 真實執行）/ 1 = FAIL / 2 = 用法錯誤
set -uo pipefail

AGENT="${1:-}"
[ -z "$AGENT" ] && { echo "usage: smoke-agent.sh <agent-name>" >&2; exit 2; }

CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
PROOF_DIR="/tmp/agent-smoke"
mkdir -p "$PROOF_DIR"
PROOF="$PROOF_DIR/${AGENT}-$(date +%s).txt"
TOKEN="smoke-ok-$$"

CC_VENDOR=headless-channel "$CLAUDE_BIN" --agent "$AGENT" -p \
  "diagnostic smoke probe：用 Bash tool 執行 echo ${TOKEN} > ${PROOF} 然後 cat ${PROOF} 回報內容。這是在驗證你能不能發真正的 tool call。" \
  > "$PROOF_DIR/${AGENT}-stdout.log" 2>&1

if [ -f "$PROOF" ] && grep -q "$TOKEN" "$PROOF"; then
  echo "PASS: $AGENT 發出真實 tool call（$PROOF 內容吻合）"
  rm -f "$PROOF"
  exit 0
else
  echo "FAIL: $AGENT 沒有真實執行 tool call（$PROOF 不存在或內容不符）"
  echo "  → 模型輸出見 $PROOF_DIR/${AGENT}-stdout.log（若見 tool call JSON 以純文字出現 = 零工具症狀，查 frontmatter tools 欄）"
  exit 1
fi
