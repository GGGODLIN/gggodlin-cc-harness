#!/bin/bash
umask 077
# memory-ripple.sh — PostToolUse(Write|Edit) hook（v3 Gemini-sync，2026-08-23）
# 寫入 ~/.claude/memory/ 時：機械 regex 命中＋同主題兄弟檔 → 機械提醒；每個事件同步問一次 Gemini
# （fallback 由 model-routing.env 的 GEMINI_FLASH_MODEL 指定、12s 單次）：機械命中且 Gemini 判 false → 取消提醒；機械未命中且 Gemini 判 true
# → 也算命中。命中只輸出一行「已記錄」提示，triage 交隔天 memory channel。提示型 gate：Gemini 任何失敗一律 fail-open（機械命中照出、未命中靜默）。
# Kill switch：MEMORY_RIPPLE_DISABLE_GEMINI=1（純機械）。v2 legacy pipeline 已拆除。
# Trial entry: ~/Desktop/projects/.claude/trials/active.md「memory-ripple hook」；
# audit log 全量記錄每次 memory 寫入（fire 與否都記），review 時對照 stale 發現算 recall。

TEST_MODE=false
[ "${MEMORY_RIPPLE_TEST_MODE:-0}" = "1" ] && TEST_MODE=true

STOPWORDS='^(user|feedback|reference|project|trial|eval|setup|config|deployed|pending|progress|review|daily|weekly|index|memory|hook|skill|claude|model|profile|ended|closed|completed|subscription|20[0-9]{2}|[0-9]+)$'
# 兄弟檔規則只有這一份：hook 寫 audit 時用，隔天 memory channel（M-1）用 `--siblings <file>` 重算。
# audit log 只記 siblings 計數不記清單，所以 channel 必須能用同一套規則取回同一份名單。
ripple_tokens() {
  basename "$1" .md \
    | sed -E 's/^(user|feedback|reference|project)_//; s/_20[0-9]{2}([_-][0-9]{2})*$//' \
    | tr '_' '\n' | grep -E '.{3,}' | grep -viE "$STOPWORDS" | head -3
}
ripple_siblings() {
  local file="$1" dir="$2" toks tok
  toks=$(ripple_tokens "$file")
  [ -n "$toks" ] || return 0
  for tok in $toks; do
    grep -ril --include='*.md' -- "$tok" "$dir" 2>/dev/null
  done | sort -u | grep -vF "$file" | grep -vE '/(MEMORY|_orphan_registry)\.md$'
}
if [ "${1:-}" = "--siblings" ]; then
  [ -n "${2:-}" ] || { echo "usage: memory-ripple.sh --siblings <memory file>" >&2; exit 2; }
  SIB_DIR="$HOME/.claude/memory"
  [ "$TEST_MODE" = true ] && [ -n "${MEMORY_RIPPLE_DIR:-}" ] && SIB_DIR="$MEMORY_RIPPLE_DIR"
  SIB_DIR=$(/usr/bin/python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$SIB_DIR")
  SIB_FILE=$(/usr/bin/python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$2")
  ripple_siblings "$SIB_FILE" "$SIB_DIR"
  exit 0
fi

INPUT=$(cat)
RUNTIME="$(dirname "$0")/memory-ripple-runtime.py"
if [ "$TEST_MODE" = true ] && [ -n "${MEMORY_RIPPLE_RUNTIME:-}" ]; then
  RUNTIME="$MEMORY_RIPPLE_RUNTIME"
fi
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

MEM_DIR="$HOME/.claude/memory"
if [ "$TEST_MODE" = true ] && [ -n "${MEMORY_RIPPLE_DIR:-}" ]; then
  MEM_DIR="$MEMORY_RIPPLE_DIR"
fi
CANONICAL=$(printf '%s\0%s' "$MEM_DIR" "$FILE" | /usr/bin/python3 -c '
import os
import sys
root, target = sys.stdin.buffer.read().decode("utf-8", "replace").split("\0", 1)
root = os.path.realpath(os.path.expanduser(root))
raw_target = os.path.expanduser(target)
target = os.path.realpath(raw_target)
if os.path.commonpath([root, target]) != root or target == root or os.path.islink(raw_target):
  raise SystemExit(1)
print(root)
print(target)
' 2>/dev/null) || exit 0
MEM_DIR=$(printf '%s\n' "$CANONICAL" | head -1)
FILE=$(printf '%s\n' "$CANONICAL" | tail -1)

BASE=$(basename "$FILE")
case "$BASE" in
  MEMORY.md|_INDEX.md|_index_*|_orphan_registry.md|.verification-ledger.jsonl) exit 0 ;;
esac

OLD_TEXT=$(echo "$INPUT" | jq -r '.tool_input.old_string // empty' 2>/dev/null)
TEXT=$(echo "$INPUT" | jq -r '.tool_input.content // .tool_input.new_string // empty' 2>/dev/null)
SID=$(echo "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // empty' 2>/dev/null)
RELATIVE_PATH=${FILE#"$MEM_DIR"/}
TP=$(echo "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)

MODEL="unknown"; CCVER="unknown"
if [ -n "$TP" ] && [ -f "$TP" ]; then
  META=$(tail -n 200 "$TP")
  M=$(printf '%s' "$META" | jq -Rr 'fromjson? | .message.model? // empty' 2>/dev/null | tail -1)
  [ -n "$M" ] && MODEL="$M"
  V=$(printf '%s' "$META" | jq -Rr 'fromjson? | .version? // empty' 2>/dev/null | tail -1)
  [ -n "$V" ] && CCVER="$V"
fi

# 名單依 2026-07-05 jsonl 回測定稿（120 事件標註：v0 recall 52.6% → 補「推翻/翻案/過時/更正/取代」類 + \b 修 SKILL.md 誤中）
REVERSAL_RE='退訂|退役|結案|收案|\bKILL\b|\bSUPERSEDED\b|廢棄|斷炊|停用|已移除|移除|已刪除|已結束|已下架|\bdeprecated\b|\bretired\b|\bobsolete\b|不再|失效|取消|清除|清空|不存在|已翻動|改為[[:space:]]+deny|禁止使用|校正|\barchived\b|推翻|翻案|反轉|改名|取代|已放棄|過時|更正|與實際.{0,10}不符'

MATCH_TEXT=$(printf '%s' "$TEXT" | sed -E 's/不存在非已刪除//g; s/(非|不是|未)已刪除//g')
WORD_HITS=$(printf '%s' "$MATCH_TEXT" | grep -oiE "$REVERSAL_RE" | sed -E 's/^與實際.{0,10}不符$/reality-mismatch/I' | sort -fu | head -5 | paste -sd, -)
TRANSITION_HITS=$(printf '%s' "$INPUT" | /usr/bin/python3 -c '
import json
import re
import sys

data = json.load(sys.stdin)
tool_input = data.get("tool_input") or {}
old = str(tool_input.get("old_string") or "")
if "content" in tool_input and tool_input.get("content") is not None:
    new = str(tool_input.get("content") or "")
else:
    new = str(tool_input.get("new_string") or "")
hits = []

def add(value):
    if value not in hits:
        hits.append(value)

old_unconfirmed = re.search(r"未確認|待確認", old)
new_confirmed = re.search(r"已確認|確認完成", new)
new_unconfirmed = re.search(r"未確認|待確認", new)
if old and old_unconfirmed and new_confirmed and not new_unconfirmed:
    add("confirmation")
release = re.search(r"已解除.{0,12}\bhold\b|已恢復|重新啟用", new, re.I)
release_negated = re.search(r"(?:尚未|仍未|未|不|not|never|still\s+not).{0,12}(?:解除|恢復|啟用|\bhold\b)", new, re.I)
if old and re.search(r"\bhold\b|暫停|擱置", old, re.I) and release and not release_negated:
    add("hold-release")
architecture_shift = re.search(r"(?:原(?!始)|舊).{1,60}(?:(?:，|,|；|;|→|->)\s*(?:現(?:為|改|採|自建|新)|自建|新架構)|後隨|(?:已|完成)(?:改用|轉用|轉為|遷移(?:至|到)))", new, re.S)
architecture_negated = re.search(r"仍維持|維持原|保持不變|尚待|待決定|尚未|仍未|預計|計畫|考慮|可能|準備|即將|擬|將要|not\s+(?:changed|decided)|still\s+(?:uses|using)|plans?\s+to|will\s+", new, re.I)
if architecture_shift and not architecture_negated:
    add("architecture-shift")
migration_decision = re.search(r"(?:遷移|migration).{0,40}(?:已拍板|拍板完成|已定案|定案完成|已改用|已轉為|已移至)|(?:已拍板|拍板完成|已定案|定案完成).{0,40}(?:遷移|migration)", new, re.I | re.S)
migration_negated = re.search(r"(?:尚未|仍未|未|不|尚待|待決定|預計|計畫|考慮|可能|準備|即將|擬|將要|not|never|still\s+not|plans?\s+to|will\s+).{0,20}(?:拍板|定案|決定|遷移|migration|移至|轉為)", new, re.I | re.S)
if migration_decision and not migration_negated:
    add("migration-decision")

def nested_keys(text):
    lines = text.splitlines()
    found = set()
    for index, line in enumerate(lines[:-1]):
        match = re.match(r"^(\s*)([A-Za-z_][\w.-]*):\s*$", line)
        if not match:
            continue
        base_indent = len(match.group(1))
        for following in lines[index + 1:]:
            if not following.strip():
                continue
            indent = len(following) - len(following.lstrip())
            if indent > base_indent and re.match(r"^\s+[A-Za-z_][\w.-]*:\s*", following):
                found.add(match.group(2))
            break
    return found

scalar_keys = set(re.findall(r"^\s*([A-Za-z_][\w.-]*):\s+\S", new, re.M))
if old and nested_keys(old) & scalar_keys:
    add("schema-shape")
print(",".join(hits))
' 2>/dev/null)
HITS=$(printf '%s\n%s\n' "$WORD_HITS" "$TRANSITION_HITS" | tr ',' '\n' | sed '/^$/d' | sort -fu | head -5 | paste -sd, -)

LLM_CANDIDATE=false
if [ -z "$HITS" ]; then
  if [ -n "$OLD_TEXT" ] && [ "$OLD_TEXT" != "$TEXT" ]; then
    LLM_CANDIDATE=true
  elif printf '%s' "$TEXT" | grep -qiE '沒有.{0,20}(欄位|功能|支援|資料|紀錄)|缺少.{0,20}(欄位|功能|支援|資料|紀錄)|未收錄|未包含|不含.{0,20}(欄位|功能|資料)|\bschema\b|\bstale\b|遷移|\bmigration\b|(?:舊|原).{0,40}(?:架構|系統|stack).{0,40}(?:改用|轉用|轉為|遷移|新系統|自建)'; then
    LLM_CANDIDATE=true
  fi
fi

TOKENS=$(ripple_tokens "$FILE")
TOKEN_LABEL=$(printf '%s\n' "$TOKENS" | paste -sd' ' -)

SIBLINGS=""
SIB_COUNT=0
DISPLAY_COUNT=0
LEAF_DISPLAY_COUNT=0
INDEX_DISPLAY_COUNT=0
if [ -n "$HITS" ] && [ -n "$TOKENS" ]; then
  ALL_SIBLINGS=$(ripple_siblings "$FILE" "$MEM_DIR")
  if [ -n "$ALL_SIBLINGS" ]; then
    SIB_COUNT=$(printf '%s\n' "$ALL_SIBLINGS" | wc -l | tr -d ' ')
    LEAF_SIBLINGS=$(printf '%s\n' "$ALL_SIBLINGS" | grep -vE '/(_index_[^/]*|_INDEX)\.md$' | head -6)
    INDEX_SIBLINGS=$(printf '%s\n' "$ALL_SIBLINGS" | grep -E '/(_index_[^/]*|_INDEX)\.md$' | head -2)
    [ -n "$LEAF_SIBLINGS" ] && LEAF_DISPLAY_COUNT=$(printf '%s\n' "$LEAF_SIBLINGS" | wc -l | tr -d ' ')
    [ -n "$INDEX_SIBLINGS" ] && INDEX_DISPLAY_COUNT=$(printf '%s\n' "$INDEX_SIBLINGS" | wc -l | tr -d ' ')
    SIBLINGS=$(printf '%s\n%s\n' "$LEAF_SIBLINGS" "$INDEX_SIBLINGS" | sed '/^$/d')
    DISPLAY_COUNT=$((LEAF_DISPLAY_COUNT + INDEX_DISPLAY_COUNT))
  fi
fi

MATCHED="$([ -n "$HITS" ] && echo true || echo false)"
MECHANICAL_FIRED="$([ -n "$HITS" ] && [ "$SIB_COUNT" -gt 0 ] && echo true || echo false)"
FIRED="$MECHANICAL_FIRED"
GEMINI_STATUS="skipped"
GEMINI_SHOULD_FIRE=null
GEMINI_KIND=""
GEMINI_CONFIDENCE=null
GEMINI_LATENCY_MS=0
GEMINI_CLASSIFIER=""
GEMINI_SUPPRESSED=false
GEMINI_CONFIRMED=false
GEMINI_MESSAGE=""

if [ "${MEMORY_RIPPLE_DISABLE_GEMINI:-0}" = "1" ]; then
  GEMINI_STATUS="disabled"
elif [ -x "$RUNTIME" ]; then
  RUNTIME_PAYLOAD=$(printf '%s' "$INPUT" | jq -c --arg file "$BASE" --arg relative "$RELATIVE_PATH" \
    --arg sid "$SID" --arg agent "$AGENT_ID" --argjson mechanical "$MECHANICAL_FIRED" \
    '{file:$file,relative_path:$relative,session_id:$sid,agent_id:$agent,mechanical_fired:$mechanical,
      old:(.tool_input.old_string // ""),
      new:(.tool_input.content // .tool_input.new_string // "")}')
  GEMINI_RESULT=$(printf '%s' "$RUNTIME_PAYLOAD" | "$RUNTIME" gemini 2>/dev/null || true)
  GEMINI_STATUS=$(printf '%s' "$GEMINI_RESULT" | jq -r '.status // "unavailable"' 2>/dev/null || echo unavailable)
  GEMINI_SHOULD_FIRE=$(printf '%s' "$GEMINI_RESULT" | jq -r 'if (.should_fire | type) == "boolean" then .should_fire else null end' 2>/dev/null || echo null)
  GEMINI_KIND=$(printf '%s' "$GEMINI_RESULT" | jq -r '.kind // ""' 2>/dev/null || echo "")
  GEMINI_CONFIDENCE=$(printf '%s' "$GEMINI_RESULT" | jq -r 'if (.confidence | type) == "number" then .confidence else null end' 2>/dev/null || echo null)
  GEMINI_LATENCY_MS=$(printf '%s' "$GEMINI_RESULT" | jq -r '.latency_ms // 0' 2>/dev/null || echo 0)
  GEMINI_CLASSIFIER=$(printf '%s' "$GEMINI_RESULT" | jq -r '.classifier // ""' 2>/dev/null || echo "")
  GEMINI_MESSAGE=$(printf '%s' "$GEMINI_RESULT" | jq -r '.message // ""' 2>/dev/null || echo "")
fi
[ "$GEMINI_STATUS" = judged ] || { GEMINI_SHOULD_FIRE=null; GEMINI_KIND=""; GEMINI_CONFIDENCE=null; GEMINI_MESSAGE=""; }

if [ "$MECHANICAL_FIRED" = true ]; then
  if [ "$GEMINI_SHOULD_FIRE" = false ]; then
    FIRED=false
    GEMINI_SUPPRESSED=true
  elif [ "$GEMINI_SHOULD_FIRE" = true ]; then
    GEMINI_CONFIRMED=true
  fi
elif [ "$GEMINI_SHOULD_FIRE" = true ] && [ -n "$GEMINI_MESSAGE" ]; then
  FIRED=true
fi

AUDIT_RECORD=$(jq -cn --arg ts "$(date '+%Y-%m-%dT%H:%M:%S%z')" --arg file "$BASE" \
  --arg sid "$SID" --arg agent "$AGENT_ID" \
  --arg transitions "$TRANSITION_HITS" \
  --argjson matched "$MATCHED" --argjson mechanical "$MECHANICAL_FIRED" --argjson fired "$FIRED" --argjson llm "$LLM_CANDIDATE" \
  --arg gemini_status "$GEMINI_STATUS" --argjson gemini_fire "$GEMINI_SHOULD_FIRE" --arg gemini_kind "$GEMINI_KIND" \
  --argjson gemini_confidence "$GEMINI_CONFIDENCE" --argjson gemini_latency "$GEMINI_LATENCY_MS" \
  --argjson gemini_suppressed "$GEMINI_SUPPRESSED" --arg gemini_classifier "$GEMINI_CLASSIFIER" \
  --argjson siblings "$SIB_COUNT" --argjson displayed "$DISPLAY_COUNT" \
  --argjson leaf "$LEAF_DISPLAY_COUNT" --argjson index "$INDEX_DISPLAY_COUNT" \
  --arg model "$MODEL" --arg ccver "$CCVER" \
  '{ts:$ts, file:$file, session_id:$sid, agent_id:$agent,
    matched:$matched, mechanical_fired:$mechanical, fired:$fired, transition_hits:$transitions,
    llm_candidate:$llm,
    gemini_status:$gemini_status, gemini_should_fire:$gemini_fire, gemini_kind:$gemini_kind,
    gemini_confidence:$gemini_confidence, gemini_latency_ms:$gemini_latency,
    gemini_suppressed:$gemini_suppressed, gemini_classifier:$gemini_classifier,
    siblings:$siblings, displayed:$displayed, leaf_displayed:$leaf, index_displayed:$index,
    model:$model, cc_version:$ccver}')
printf '%s' "$AUDIT_RECORD" | "$RUNTIME" main-audit > /dev/null 2>&1 || true

[ "$FIRED" = false ] && exit 0

# sibling triage 交給隔天 memory channel 讀 audit log 處理；當場注入逐檔指示會把寫入者拉離手上任務，
# 所以命中只留一行「已記錄」提示，不列 sibling 檔名、不給修法指示（Ticket 02 / design D3）。
# Gemini-only 路徑刻意不用 runtime 的 GEMINI_MESSAGE（它內含逐檔 triage 指示），只取 kind。
if [ "$MECHANICAL_FIRED" = true ]; then
  DETAIL="命中詞: ${HITS}，同主題 ${SIB_COUNT} 檔"
  [ "$GEMINI_CONFIRMED" = true ] && DETAIL="${DETAIL}，Gemini 確認：${GEMINI_KIND}"
else
  DETAIL="Gemini 判定：${GEMINI_KIND:-state-reversal}"
fi
MSG="[memory-ripple] 已記錄狀態反轉寫入（${DETAIL}），隔天 memory channel 會 triage；本 session 不需處理。"

jq -cn --arg msg "$MSG" '{hookSpecificOutput:{hookEventName:"PostToolUse", additionalContext:$msg}}'
exit 0
