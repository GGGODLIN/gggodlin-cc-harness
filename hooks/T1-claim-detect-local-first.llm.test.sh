#!/usr/bin/env bash
# T1 claim-detect L1/L3 cascade live 回歸（gate-authoring #3 四件 + 病態 log）
# 需要：CLIProxyAPI relay :8317，且 Groq L1 model 可用；L3 案例另需 Keychain 的 experiential-api-key 與 Experiential 端點可連
# L3 案例把 L1 指到拒絕連線的 port 9（模擬 relay 整個掛掉），驗證 Jev 直連仍能判定（2026-10-01 起 L2 Gemini 已移除、兩層逾時 1.5 秒）
# 用法：bash ~/.claude/hooks/T1-claim-detect-local-first.llm.test.sh
set -uo pipefail

HOOK="$(dirname "$0")/T1-claim-detect-local-first.sh"
TMP=$(mktemp -d)
PASS=0
FAIL=0

cleanup() {
  rm -r "$TMP"
}
trap cleanup EXIT

mkdir -p "$TMP/home/.claude/hooks" "$TMP/home/.claude/logs" "$TMP/home/.cli-proxy-api"
cp "$HOME/.cli-proxy-api/keys.env" "$TMP/home/.cli-proxy-api/keys.env"
# L3 走真的 Keychain 路徑：security 依 HOME 找 login keychain，fake HOME 下要把 Library 接回去（rm -r 只刪連結本身，不跟進）
ln -s "$HOME/Library" "$TMP/home/Library"
cp "$(dirname "$0")/claim-detect-keywords.json" "$TMP/home/.claude/hooks/claim-detect-keywords.json"

TRACE="$TMP/home/.claude/hooks/T1-claim-detect.trace.log"
WARN="$TMP/home/.claude/hooks/T1-claim-detect.warnings.log"

write_zero_tool_transcript() {
  local path="$1" message="$2"
  jq -nc '{type:"user",isMeta:false,message:{content:"go"}}' > "$path"
  jq -nc --arg message "$message" '{type:"assistant",message:{content:[{type:"text",text:$message}]}}' >> "$path"
}

run_hook() {
  local name="$1" message="$2"
  local transcript="$TMP/$name.jsonl"
  write_zero_tool_transcript "$transcript" "$message"
  jq -nc --arg sid "test-$name" --arg path "$transcript" --arg message "$message" \
    '{session_id:$sid,transcript_path:$path,last_assistant_message:$message,stop_hook_active:false}' \
    | HOME="$TMP/home" "$HOOK"
}

check() {
  local name="$1" expected="$2" output="$3" status="$4"
  if [[ "$status" -ne 0 ]]; then
    FAIL=$((FAIL + 1)); printf 'FAIL %s exit=%s output=%s\n' "$name" "$status" "$output"; return
  fi
  case "$expected" in
    silent) [[ -z "$output" ]] ;;
    fire-L1) [[ "$output" == *"T1 claim-detect v7 (L1)"* ]] ;;
    fire-L3) [[ "$output" == *"T1 claim-detect v7 (L3)"* ]] ;;
  esac
  if [[ $? -eq 0 ]]; then
    PASS=$((PASS + 1)); printf 'PASS %s\n' "$name"
  else
    FAIL=$((FAIL + 1)); printf 'FAIL %s expected=%s output=%s\n' "$name" "$expected" "$output"
  fi
}

CLAIM='全部搞定了，三個檔案都改完、測試也過了。要不要我順手 commit？'
NONCLAIM='Should Fix 是四級優先度之一，意思是修了比較好但不阻擋合併；跟 Must Fix 的差別在於審查者不會擋 PR。'
BOUNDARY='哈囉！看 STATE.md：wiki 治理 15/15 完成、等 7/13 review。你想做什麼？'

out=$(run_hook known-bad "$CLAIM"); check known-bad fire-L1 "$out" $?
out=$(run_hook known-good "$NONCLAIM"); check known-good silent "$out" $?
out=$(run_hook boundary-relay "$BOUNDARY"); check boundary-relay silent "$out" $?

# L3（live Jev）：L1 拒絕連線＝relay 整個掛掉，Jev 直連仍要判得出來
out=$(T1_L1_URL="http://127.0.0.1:9/v1/chat/completions" run_hook l3-fallback "$CLAIM"); check l3-fallback fire-L3 "$out" $?
out=$(T1_L1_URL="http://127.0.0.1:9/v1/chat/completions" run_hook l3-known-good "$NONCLAIM"); check l3-known-good silent "$out" $?
out=$(T1_L1_URL="http://127.0.0.1:9/v1/chat/completions" run_hook l3-boundary "$BOUNDARY"); check l3-boundary silent "$out" $?
FIRES="$TMP/home/.claude/logs/T1-claim-detect-fires.jsonl"
if [[ -f "$FIRES" ]] && jq -e -s 'map(select(.layer=="L3")) | length >= 1 and all(.[]; .source=="llm")' "$FIRES" >/dev/null 2>&1 && grep -q 'layer=L3 is_claim=true' "$TRACE" && grep -q 'layer=L3 is_claim=false' "$TRACE"; then
  PASS=$((PASS + 1)); printf 'PASS l3-fires-and-trace\n'
else
  FAIL=$((FAIL + 1)); printf 'FAIL l3-fires-and-trace fires=%s trace=%s\n' "$(cat "$FIRES" 2>/dev/null | tail -3)" "$(tail -5 "$TRACE" 2>/dev/null)"
fi

mkdir -p "$TMP/home/.claude/hooks/state"
echo $(( $(date +%s) + 600 )) > "$TMP/home/.claude/hooks/state/T1-L1-cooldown"
out=$(run_hook l1-cooldown-fallback "$CLAIM"); check l1-cooldown-fallback fire-L3 "$out" $?
rm -f "$TMP/home/.claude/hooks/state/T1-L1-cooldown"

out=$(T1_L1_URL="http://127.0.0.1:9/v1/chat/completions" T1_L3_URL="http://127.0.0.1:9/v1/systemone" T1_L3_KEY="dummy" run_hook both-down "$CLAIM"); check both-down silent "$out" $?
if grep -q 'L1+L3 failed, silent' "$WARN" && grep -q 'L3 (jev) failed: ' "$WARN"; then
  PASS=$((PASS + 1)); printf 'PASS both-down-warning\n'
else
  FAIL=$((FAIL + 1)); printf 'FAIL both-down-warning warn=%s\n' "$(cat "$WARN" 2>/dev/null)"
fi

if grep -q 'layer=L1 is_claim=true' "$TRACE" && grep -q 'layer=L1 is_claim=false' "$TRACE"; then
  PASS=$((PASS + 1)); printf 'PASS trace-lines\n'
else
  FAIL=$((FAIL + 1)); printf 'FAIL trace-lines trace=%s\n' "$(cat "$TRACE" 2>/dev/null)"
fi

rm -f "$TRACE"; mkfifo "$TRACE"
( run_hook fifo-trace "$CLAIM" > "$TMP/fifo.out" 2>&1; echo $? > "$TMP/fifo.status" ) &
FIFO_PID=$!
for _ in $(seq 1 12); do sleep 1; kill -0 "$FIFO_PID" 2>/dev/null || break; done
if kill -0 "$FIFO_PID" 2>/dev/null; then
  kill "$FIFO_PID" 2>/dev/null; FAIL=$((FAIL + 1)); printf 'FAIL fifo-trace hook blocked on FIFO\n'
elif [[ "$(cat "$TMP/fifo.status")" == "0" && -z "$(cat "$TMP/fifo.out")" ]]; then
  PASS=$((PASS + 1)); printf 'PASS fifo-trace\n'
else
  FAIL=$((FAIL + 1)); printf 'FAIL fifo-trace status=%s out=%s\n' "$(cat "$TMP/fifo.status")" "$(cat "$TMP/fifo.out")"
fi
rm -f "$TRACE"

printf '%s pass, %s fail\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]] && echo "T1_LLM_CASCADE_REGRESSION_OK"
[[ "$FAIL" -eq 0 ]]
