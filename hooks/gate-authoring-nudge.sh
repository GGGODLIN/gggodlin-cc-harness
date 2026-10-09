#!/bin/bash
# gate-authoring-nudge.sh — PostToolUse(Edit|Write)
# 編輯 hooks 路徑檔案時注入「先過 gate-authoring checklist」提醒。
# 降噪：once-per-session（/tmp marker）+ transcript 查重（session 內已 invoke gate-authoring 就不 fire）。
# Trial entry: ~/Desktop/projects/.claude/trials/active.md「gate-authoring skill 觸發觀察」；
# audit log 只記實際 fire 的事件（供 review 期比對 miss）。

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
[ -z "$FILE" ] && exit 0

case "$FILE" in
  */.claude/hooks/*) ;;
  *) exit 0 ;;
esac

SID=$(echo "$INPUT" | jq -r '.session_id // "nosession"' 2>/dev/null)
MARK="/tmp/gate-authoring-nudge-$SID"
[ -f "$MARK" ] && exit 0

TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
if [ -n "$TRANSCRIPT" ] && [ -f "$TRANSCRIPT" ] && grep -q '"skill":"gate-authoring"' "$TRANSCRIPT" 2>/dev/null; then
  touch "$MARK"
  exit 0
fi

touch "$MARK"
AUDIT_LOG="$HOME/.claude/logs/gate-authoring-nudge-audit.jsonl"
mkdir -p "$(dirname "$AUDIT_LOG")"
jq -cn --arg ts "$(date '+%Y-%m-%dT%H:%M:%S%z')" --arg file "$(basename "$FILE")" --arg sid "$SID" \
  '{ts:$ts, file:$file, sid:$sid}' >> "$AUDIT_LOG"

jq -cn '{hookSpecificOutput:{hookEventName:"PostToolUse", additionalContext:"⚠️ [gate-authoring-nudge] 你在改 hooks 路徑的檔案——若本次屬設計/修改 gate 或 hook 行為，先 invoke gate-authoring skill 過 checklist（surface 四分表 / 三件 fixture / 繞行場景表）再繼續；純 typo 或註解修改可忽略本提醒。"}}'
exit 0
