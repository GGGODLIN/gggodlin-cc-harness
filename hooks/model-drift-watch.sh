#!/bin/bash
# model-drift-watch.sh — UserPromptSubmit hook
# 首次見到某個 resolved model id 時提醒開 model review（coevolution spec §3：換代事件＝alias 解析變化）
# 解析 pattern 沿用 fable-gate.sh 錨定式（避開 Agent tool 參數 "model" 誤中）；fail-open。
# 2026-07-25 實測：本檔 pattern 在真實 transcript 命中 58 次、100% 落在 type=="assistant" 行；
#   注入文字裡的同款字面（escaped 形式）0 誤中——JSON 轉義中和了 payload 層繞行。
# 動態值（model id）置於訊息尾端（原為 additionalContext 時代的 prefix cache 紀律；systemMessage 不進 context、僅保留排版慣例）。
INPUT=$(cat)
TP=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
[ -z "$TP" ] || [ ! -f "$TP" ] && exit 0

MODEL=$(tail -c 200000 "$TP" | jq -Rr 'fromjson? | select(type == "object" and .type == "assistant" and (.message | type == "object") and (.message.model | type == "string") and .message.model != "") | .message.model' 2>/dev/null | tail -1)
[ -z "$MODEL" ] && exit 0

STATE_DIR="${MODEL_DRIFT_STATE_DIR:-$HOME/.claude/hooks/state}"
SEEN="$STATE_DIR/seen-models.txt"
mkdir -p "$STATE_DIR"
touch "$SEEN"
grep -qxF "$MODEL" "$SEEN" && exit 0
echo "$MODEL" >> "$SEEN"

AUDIT="${MODEL_DRIFT_AUDIT:-$HOME/.claude/logs/model-drift-watch.jsonl}"
mkdir -p "$(dirname "$AUDIT")"
jq -cn --arg ts "$(date '+%Y-%m-%dT%H:%M:%S%z')" --arg sid "$SID" --arg m "$MODEL" \
  '{ts:$ts,session:$sid,model:$m}' >> "$AUDIT"

# 2026-08-17 systemmessage-hook-conversion：首見通知改走 systemMessage 直接顯示（渲染當日實證）。
# 已知代價（audit 表明列）：失去「Claude 先判 alias 位移再轉告」的過濾層，每次首見直接顯示。
MSG="🆕 [model-drift-watch] 首次觀測到一個新的 resolved model id——換代事件候選。若屬在籍 alias 位移或新模型採用，考慮依 coevolution spec §8 開 model review。模型: ${MODEL}"
jq -cn --arg msg "$MSG" '{systemMessage:$msg}'
exit 0
