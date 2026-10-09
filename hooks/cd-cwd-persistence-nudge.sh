#!/bin/bash
# PreToolUse Bash hook — Bash tool cwd 跨 call 持久化提示
# 偵測：相對 cd（`cd subdir`、不含絕對路徑 / subshell）→ 注入提醒
# 設計：取代 CLAUDE.md cwd 規矩（事件級觸發、不增 always-on context tax）
# Disable: touch ~/.claude/hooks/.cd-cwd-disabled
set -uo pipefail

SENTINEL="$HOME/.claude/hooks/.cd-cwd-disabled"
[ -f "$SENTINEL" ] && exit 0

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)

# Fast path: 沒命中的全部 exit 0、不延遲一般 Bash call
case "$cmd" in
  "("*) exit 0 ;;          # subshell 已用 `(cd ... && ...)`、不提示
  "cd /"*) exit 0 ;;       # 絕對路徑 cd（含 cd /tmp / cd $HOME 展開後等）
  "cd "*) ;;               # 相對 cd subdir → 命中
  *) exit 0 ;;             # 其他命令、不提示
esac

MSG="[本機自寫 hook ~/.claude/hooks/cd-cwd-persistence-nudge.sh] 偵測到相對 \`cd <subdir>\`。Bash tool cwd 跨 call 持久化、不會自動回 root —— 後續 Bash 若用 repo-root 相對路徑（特別 \`git add\` / \`git diff\` / \`git restore\`）會 exit 128 路徑重複。預防三選一：(a) subshell 包：\`(cd subdir && cmd)\` 結束自動回原 cwd；(b) 下個 Bash 顯式 \`cd \$REPO_ROOT && ...\`；(c) typecheck/build 類用 \`--project <path>\` flag 取代 \`cd subdir\`。"

jq -n --arg ctx "$MSG" '{hookSpecificOutput:{hookEventName:"PreToolUse",additionalContext:$ctx}}'
exit 0
