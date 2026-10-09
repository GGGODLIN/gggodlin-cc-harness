#!/bin/bash
# PostToolUse(Workflow) nudge: 背景 Workflow 剛啟動 → 提醒 invoke workflow-monitor
# skill watch 模式守護 5h 用量窗口。從 settings.json inline echo 抽出來補 vendor gate
# (2026-06-20)。對應 command: ~/.claude/commands/workflow-monitor.md。
set -uo pipefail

# Vendor-session routing (2026-06-20；glm monitor retired 2026-09-02):
#   CC_VENDOR unset → Anthropic-native session → /workflow-monitor (5h OAuth quota guard)
#   CC_VENDOR set   → silent。GLM 的 vendor-glm quota producer 已退休，其他 vendor 也不共用 Anthropic quota。
case "${CC_VENDOR:-}" in
  "")
    :
    ;;
  *)
    exit 0
    ;;
esac

read -r -d '' CTX <<'EOF' || true
背景 Workflow 剛啟動。一律 invoke workflow-monitor skill 的 watch 模式守護它撐過 5 小時用量限額——不要自行判斷「夠不夠長」，一律掛：掛的成本極低（一個背景輪詢），不掛的代價（中途撞 5h 窗口、token 重燒）大且不對稱。它會掛 background limit-watch（讀本地 quota cache、5h 達 90% 自動喚醒你 pause、窗口恢復自動 resume），全程不用盯。啟動結果裡有它需要的 Task ID / Run ID / Script file。
EOF

jq -n --arg ctx "$CTX" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$ctx}}'
