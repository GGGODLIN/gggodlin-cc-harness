#!/bin/bash
# distill-extract.sh — 確定性指紋抽取（零 LLM），distill-weekly channel 的 Step 1。
# 掃「上個檢查點 → 現在」的 main session jsonl，抽工具序列指紋 + 首個 user intent，
# 寫入永久 ledger。2026-06-12 改 checkpoint 機制（原固定 7 天窗口）：
#   - 缺跑不漏：窗口自動回看到上次成功跑的時點
#   - 活 session 重抽：mtime > checkpoint 的 session 一律重抽並「替換」ledger 舊行
#     （ledger 語意 = per-session 最新指紋，非 append-only 演化史）
# 用法：distill-extract.sh [--since 'YYYY-MM-DD']（手動指定窗口起點，回填用；不更新 checkpoint 邏輯照常）
# Ledger 是 derived cache——cleanupPeriodDays=3650，任何時候都能從 jsonl 全量重建。
set -euo pipefail

OUT_DIR="$HOME/code/social-info/reports/local-analysis"
LEDGER="$OUT_DIR/distill-candidates.jsonl"
CHECKPOINT="$OUT_DIR/distill-extract.checkpoint"
mkdir -p "$OUT_DIR"
touch "$LEDGER"

RUN_START=$(date '+%Y-%m-%d %H:%M:%S')

if [ "${1:-}" = "--since" ] && [ -n "${2:-}" ]; then
  WINDOW_START="$2"
elif [ -f "$CHECKPOINT" ]; then
  WINDOW_START=$(cat "$CHECKPOINT")
else
  WINDOW_START=$(date -v-7d '+%Y-%m-%d %H:%M:%S')
fi

TMP_NEW=$(mktemp)
trap 'rc=$?; rm -f "$TMP_NEW"; exit $rc' EXIT

scanned=0
extracted=0

while IFS= read -r f; do
  scanned=$((scanned+1))
  sid=$(basename "$f" .jsonl)

  date_str=$(stat -f '%Sm' -t '%Y-%m-%d' "$f")

  intent=$(jq -r 'select(.type=="user" and (.message.content|type)=="string" and ((.isMeta // false)|not)) | .message.content' "$f" 2>/dev/null \
    | grep -avE '^(<|Caveat:|Shell cwd|Stop hook|AUTO-SAVE)' | head -1 | tr -d '\n' | cut -c1-120 || true)

  # seq 只留每個 Bash 指令前兩個詞，但 `TOKEN=xxx; curl` 這種寫法會把 secret 前綴存進 ledger（2026-09-29 distill 揭露 24+ 個 key 指紋）；含 = 的詞一律改成 VAR=<redacted>
  seq=$(jq -r 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use")
      | if .name=="Bash" then "Bash:"+((.input.command // "")|gsub("[\\n\\t]";" ")|split(" ")|map(select(length>0))|.[0:2]|map(if test("=") then (split("=")[0]+"=<redacted>") else . end)|join(" "))
        elif .name=="Skill" then "Skill:"+(.input.skill // "")
        elif .name=="Agent" then "Agent:"+(.input.subagent_type // "general")
        elif .name=="Workflow" then "Workflow"
        else .name end' "$f" 2>/dev/null \
    | awk 'NR==1||$0!=prev{print} {prev=$0}' | head -200 | paste -sd '|' - || true)

  [ -z "$seq" ] && continue

  jq -cn --arg d "$date_str" --arg s "$sid" --arg i "$intent" --arg q "$seq" \
    '{date:$d,session:$s,intent:$i,seq:$q}' >> "$TMP_NEW"
  extracted=$((extracted+1))
done < <(find "$HOME/.claude/projects" -name '*.jsonl' -not -path '*/subagents/*' -newermt "$WINDOW_START")

# 批次內 dedup：同 session id 多個 jsonl 實體（跨 cwd resume / 複製）→ 留 seq 最長那份
if [ -s "$TMP_NEW" ]; then
  TMP_DEDUP=$(mktemp)
  jq -cs 'group_by(.session) | map(max_by(.seq|length)) | .[]' "$TMP_NEW" > "$TMP_DEDUP"
  mv "$TMP_DEDUP" "$TMP_NEW"
fi

# 替換合併：本輪重抽到的 session 以新行為準，其餘舊行保留
if [ -s "$TMP_NEW" ]; then
  TMP_MERGED=$(mktemp)
  jq -r '.session' "$TMP_NEW" | sort -u > "${TMP_NEW}.ids"
  grep -vFf <(sed 's/.*/"session":"&"/' "${TMP_NEW}.ids") "$LEDGER" > "$TMP_MERGED" || true
  cat "$TMP_NEW" >> "$TMP_MERGED"
  mv "$TMP_MERGED" "$LEDGER"
  rm -f "${TMP_NEW}.ids"
fi

# 成功跑完才推進 checkpoint（寫 run 開始時間，防 run 中被改的 session 落縫隙）
echo "$RUN_START" > "$CHECKPOINT"

echo "window since: $WINDOW_START | scanned $scanned sessions, extracted $extracted (replace-on-rescan)"
echo "ledger total: $(wc -l < "$LEDGER" | tr -d ' ') sessions | checkpoint → $RUN_START"
