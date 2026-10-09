#!/bin/bash
# model-drift-watch.sh 五案 fixture 回歸
HOOK="$HOME/.claude/hooks/model-drift-watch.sh"
TMP=$(mktemp -d); PASS=0; FAIL=0
export MODEL_DRIFT_STATE_DIR="$TMP/state"
export MODEL_DRIFT_AUDIT="$TMP/audit.jsonl"

mk_transcript() {
  printf '{"type":"assistant","message":{"model":"%s","content":[]},"version":"2.1.220","uuid":"u1"}\n' "$1" > "$2"
}
mk_reordered_transcript() {
  printf '{"type":"assistant","message":{"content":[],"model":"%s"},"version":"2.1.220","uuid":"u2"}\n' "$1" > "$2"
}
run_case() {
  local name="$1" transcript="$2" expect_fire="$3"
  local input out
  input=$(jq -cn --arg tp "$transcript" '{session_id:"s1",transcript_path:$tp}')
  out=$(printf '%s' "$input" | bash "$HOOK")
  if [ "$expect_fire" = yes ] && printf '%s' "$out" | grep -q 'model-drift-watch'; then
    PASS=$((PASS+1)); echo "PASS: $name"
  elif [ "$expect_fire" = no ] && [ -z "$out" ]; then
    PASS=$((PASS+1)); echo "PASS: $name"
  else
    FAIL=$((FAIL+1)); echo "FAIL: $name — out=[$out]"
  fi
}
assert_seen() {
  local name="$1" model="$2"
  if grep -qxF "$model" "$TMP/state/seen-models.txt"; then
    PASS=$((PASS+1)); echo "PASS: $name"
  else
    FAIL=$((FAIL+1)); echo "FAIL: $name"
  fi
}
assert_audit() {
  local name="$1" model="$2"
  if jq -se --arg model "$model" 'map(select(.model == $model and .session == "s1" and (.ts | type == "string"))) | length == 1' "$TMP/audit.jsonl" >/dev/null 2>&1; then
    PASS=$((PASS+1)); echo "PASS: $name"
  else
    FAIL=$((FAIL+1)); echo "FAIL: $name"
  fi
}

mk_transcript claude-test-model-x "$TMP/t1.jsonl"
mk_reordered_transcript claude-test-model-reordered "$TMP/reordered.jsonl"
printf '%s\n' \
  '{"type":"assistant","message":{"model":"claude-test-model-before","content":[]},"version":"2.1.220","uuid":"u3"}' \
  '{"type":"assistant","message":{"model":"claude-test-model-malformed"' \
  '{"type":"assistant","message":{"content":[],"model":"claude-test-model-latest"},"version":"2.1.220","uuid":"u4"}' \
  '{"type":"assistant","message":{"model":"claude-test-model-truncated"' \
  > "$TMP/t3.jsonl"
run_case "首見 id → fire" "$TMP/t1.jsonl" yes
run_case "assistant message model 欄位順序不同 → fire" "$TMP/reordered.jsonl" yes
run_case "截斷與非法 JSON 行略過" "$TMP/t3.jsonl" yes
assert_seen "最後有效 assistant model 已選取" claude-test-model-latest
printf '%s\n' \
  '{"type":"user","message":{"model":"claude-test-model-user","content":[]},"version":"2.1.220","uuid":"u5"}' \
  '{"type":"assistant","message":{"model":null,"content":[]},"version":"2.1.220","uuid":"u6"}' \
  '{"type":"assistant","message":{"model":{"id":"claude-test-model-object"},"content":[]},"version":"2.1.220","uuid":"u7"}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","input":{"model":"claude-test-model-tool"}}]},"version":"2.1.220","uuid":"u8"}' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"quoted model: \\"model\\":\\"claude-test-model-quoted\\""}]},"version":"2.1.220","uuid":"u9"}' \
  '{"type":"assistant","message":"quoted model: \\"model\\":\\"claude-test-model-message-string\\"","version":"2.1.220","uuid":"u10"}' \
  > "$TMP/t4.jsonl"
run_case "非 assistant 與巢狀 model 不觸發" "$TMP/t4.jsonl" no
run_case "已見 id → silent" "$TMP/t1.jsonl" no
run_case "transcript 不存在 → silent" "$TMP/nope.jsonl" no
printf '{"type":"user","uuid":"u0"}\n' > "$TMP/t2.jsonl"
run_case "無 assistant message → silent" "$TMP/t2.jsonl" no
assert_audit "首見 id 已寫入 audit 且去重" claude-test-model-x
grep -qxF claude-test-model-x "$TMP/state/seen-models.txt" \
  && { PASS=$((PASS+1)); echo "PASS: seen 檔已記錄"; } \
  || { FAIL=$((FAIL+1)); echo "FAIL: seen 檔未記錄"; }
echo "== $PASS pass / $FAIL fail =="; rm -rf "$TMP"; [ "$FAIL" -eq 0 ]
