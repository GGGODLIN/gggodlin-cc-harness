#!/bin/bash
set -euo pipefail

COMMAND="$HOME/.claude/commands/daily-local.md"
HOOK="$HOME/.claude/hooks/daily-local-analysis-trigger.sh"

command_text=$(cat "$COMMAND")
hook_text=$(cat "$HOOK")

read_pos=$(printf '%s' "$command_text" | grep -nF 'Read `~/.claude/hooks/daily-local-analysis-trigger.sh`' | cut -d: -f1)
workflow_pos=$(printf '%s' "$command_text" | grep -nF '呼叫 Workflow tool' | cut -d: -f1)
[[ -n "$read_pos" && -n "$workflow_pos" && "$read_pos" -lt "$workflow_pos" ]]
printf '%s' "$command_text" | grep -F '照 hook 的啟動與排檔規則逐條執行' >/dev/null
printf '%s' "$command_text" | grep -F '`{"date":"<%F 結果>","weekday":<%u 結果數字>,"external_recap":true}`' >/dev/null
if printf '%s' "$command_text" | grep -F 'args 使用 hook 尾行' >/dev/null; then
  exit 1
fi

for phrase in '~/code/social-info/scripts/local-analysis/recap-daily.sh' 'run_in_background=true' '"external_recap":true' 'recap Bash 與 workflow 都完成後' 'external_channels' '把 recap 加進 failed'; do
  printf '%s' "$hook_text" | grep -F "$phrase" >/dev/null
done

delegate_pos=$(printf '%s' "$command_text" | grep -nF '如果你已收到 workflow 分派的單一 channel 任務' | cut -d: -f1)
[[ -n "$delegate_pos" && "$delegate_pos" -lt "$read_pos" ]]
printf '%s' "$command_text" | grep -F '不再啟動 recap 或 Workflow' >/dev/null
printf '%s' "$command_text" | grep -F '報告是允許的輸出；read-only 限制的是分析來源' >/dev/null
printf '%s' "$command_text" | grep -F 'report_markdown' >/dev/null
printf '%s' "$command_text" | grep -F 'deferred_writeback' >/dev/null
printf '%s' "$command_text" | grep -F 'pending_reports' >/dev/null

printf 'daily-local routed recap command contract: PASS\n'
