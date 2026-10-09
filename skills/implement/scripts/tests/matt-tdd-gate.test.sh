#!/usr/bin/env bash
# 本檔在契約測試底下；跑法：bash skills/implement/scripts/tests/matt-tdd-gate.test.sh
set -u

# 跟著測試檔找 repo root。寫死 ~/.claude 時，worktree 會測到 live hook／policy。
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../../../.." && pwd)
HOOK="$REPO_ROOT/hooks/matt-tdd-gate.sh"
POLICY="$REPO_ROOT/skills/implement/scripts/tdd-policy.mjs"
if [ ! -f "$HOOK" ] || [ ! -f "$POLICY" ]; then
  printf 'FAIL locate worktree hook/policy hook=%s policy=%s\n' "$HOOK" "$POLICY"
  exit 1
fi
TMP=$(mktemp -d)
ROOT="$TMP/state"
PENDING="$TMP/pending"
PASSES=0
FAILURES=0
export MATT_TDD_ROOT="$ROOT"
export MATT_TDD_PENDING_DIR="$PENDING"
export MATT_TDD_POLICY="$POLICY"
mkdir -p "$ROOT" "$PENDING"

cleanup() {
  rm -r "$TMP"
}
trap cleanup EXIT

pass() {
  PASSES=$((PASSES + 1))
  printf 'PASS %s\n' "$1"
}

fail() {
  FAILURES=$((FAILURES + 1))
  printf 'FAIL %s expected=%s actual=%s\n' "$1" "$2" "$3"
}

payload() {
  local event=$1 session=$2 transcript=$3 skill=${4:-} tool_use=${5:-tool-use-1} agent_id=${6:-}
  jq -nc --arg event "$event" --arg session "$session" --arg transcript "$transcript" --arg skill "$skill" --arg tool_use "$tool_use" --arg agent_id "$agent_id" '{hook_event_name:$event,tool_name:(if $event == "PreToolUse" then "Skill" else "" end),session_id:$session,transcript_path:$transcript,tool_use_id:$tool_use,agent_id:$agent_id,tool_input:(if $event == "PreToolUse" then {skill:$skill} else {} end)}'
}

call_hook() {
  "$HOOK"
}

expect_allow() {
  local label=$1 output=$2
  if printf '%s' "$output" | grep -q '"decision"[[:space:]]*:[[:space:]]*"block"' || printf '%s' "$output" | grep -q '"systemMessage"'; then
    fail "$label" 'allow without block or advisory' "$output"
  else
    pass "$label"
  fi
}

expect_advise() {
  local label=$1 needle=$2 output=$3
  if printf '%s' "$output" | grep -q '"decision"[[:space:]]*:[[:space:]]*"block"'; then
    fail "$label" "advisory without block containing $needle" "$output"
  elif printf '%s' "$output" | jq -e '.systemMessage and .hookSpecificOutput.additionalContext' >/dev/null 2>&1 && printf '%s' "$output" | grep -q "$needle"; then
    pass "$label"
  else
    fail "$label" "advisory systemMessage containing $needle" "$output"
  fi
}

expect_deny() {
  local label=$1 needle=$2 output=$3
  local decision
  decision=$(printf '%s' "$output" | jq -r '.hookSpecificOutput.permissionDecision // empty' 2>/dev/null)
  if [ "$decision" = deny ] && printf '%s' "$output" | grep -q "$needle"; then
    pass "$label"
  else
    fail "$label" "permissionDecision deny containing $needle" "$output"
  fi
}

expect_armed() {
  local label=$1 output=$2
  local context
  context=$(printf '%s' "$output" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)
  if printf '%s' "$context" | grep -q 'gate armed'; then
    pass "$label"
  else
    fail "$label" 'arming additionalContext' "$output"
  fi
}

new_transcript() {
  local path=$1
  : > "$path"
  chmod 600 "$path"
}

append_tdd_call() {
  local path=$1 tool_use=${2:-tool-tdd}
  jq -nc --arg tool_use "$tool_use" '{type:"assistant",message:{content:[{type:"tool_use",id:$tool_use,name:"Skill",input:{skill:"tdd"}}]}}' >> "$path"
}

append_tdd_result() {
  local path=$1 tool_use=${2:-tool-tdd} is_error=${3:-false}
  jq -nc --arg tool_use "$tool_use" --argjson is_error "$is_error" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$tool_use,is_error:$is_error,content:"loaded"}]}}' >> "$path"
}

append_tdd_result_variant() {
  local path=$1 tool_use=$2 variant=$3
  case "$variant" in
    missing) jq -nc --arg tool_use "$tool_use" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$tool_use,content:"loaded"}]}}' >> "$path" ;;
    null) jq -nc --arg tool_use "$tool_use" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$tool_use,is_error:null,content:"loaded"}]}}' >> "$path" ;;
    string-false) jq -nc --arg tool_use "$tool_use" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$tool_use,is_error:"false",content:"loaded"}]}}' >> "$path" ;;
  esac
}

append_tdd_runtime_result() {
  local path=$1 tool_use=$2 success=$3 command=${4:-tdd}
  jq -nc --arg tool_use "$tool_use" --arg command "$command" --argjson success "$success" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$tool_use,content:"Launching skill: tdd"}]},toolUseResult:{success:$success,commandName:$command}}' >> "$path"
}

append_implement_call() {
  local path=$1 tool_use=$2
  jq -nc --arg tool_use "$tool_use" '{type:"assistant",message:{content:[{type:"tool_use",id:$tool_use,name:"Skill",input:{skill:"implement"}}]}}' >> "$path"
}

append_tool_call() {
  local path=$1 name=$2 tool_use=${3:-tool-$2}
  jq -nc --arg tool_use "$tool_use" --arg name "$name" '{type:"assistant",message:{content:[{type:"tool_use",id:$tool_use,name:$name,input:{}}]}}' >> "$path"
}

stop_payload_active() {
  local session=$1 transcript=$2 active=$3
  jq -nc --arg session "$session" --arg transcript "$transcript" --argjson active "$active" '{hook_event_name:"Stop",tool_name:"",session_id:$session,transcript_path:$transcript,tool_use_id:"tool-use-1",agent_id:"",tool_input:{},stop_hook_active:$active}'
}

audit_lines() {
  if [ -f "$ROOT/loopguard/audit.jsonl" ]; then wc -l < "$ROOT/loopguard/audit.jsonl" | tr -d ' '; else printf '0'; fi
}

set_marker_contract() {
  local path=$1 contract=$2
  python3 - "$path" "$contract" <<'PY'
import json,sys
path,contract=sys.argv[1:3]
with open(path) as source:
  value=json.load(source)
value["contract"] = contract
if contract == "MATT_TDD_PENDING v2":
  value.pop("transcript_prefix_bytes",None)
with open(path,"w") as target:
  json.dump(value,target,indent=2)
  target.write("\n")
PY
}

append_same_record_calls() {
  local path=$1 tool_use=$2
  jq -nc --arg tool_use "$tool_use" '{type:"assistant",message:{content:[{type:"tool_use",id:$tool_use,name:"Skill",input:{skill:"implement"}},{type:"tool_use",id:"tool-tdd-same",name:"Skill",input:{skill:"tdd"}}]}}' >> "$path"
}

append_tdd_prose() {
  local path=$1
  jq -nc '{type:"assistant",message:{content:[{type:"text",text:"I invoked Skill(tdd) and used tdd."}]}}' >> "$path"
}

write_required_ticket() {
  printf '%s\n' '# 01 — Required' '' '**TDD:** required' '' '**TDD seam:** CLI output' > "$1"
}

write_waived_ticket() {
  printf '%s\n' '# 01 — Docs' '' '**TDD:** waived' '' '**TDD waiver:** `docs-only`' '' '**TDD waiver approved:** `ticket-breakdown-user-approved`' > "$1"
}

ticket_path() {
  local session=$1
  mkdir -p "$TMP/openspec/changes/$session"
  printf '%s/tasks.md' "$TMP/openspec/changes/$session"
}

write_shim() {
  local directory=$1 name=$2 body=$3
  printf '%s\n' '#!/bin/sh' "$body" > "$directory/$name"
  chmod 700 "$directory/$name"
}

SESSION=non-matt
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" tdd tool-non-matt | call_hook 2>/dev/null)
[ -z "$OUT" ] && pass 'valid non-Matt Skill call silently passes' || fail 'valid non-Matt Skill call silently passes' empty "$OUT"
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_allow 'non-Matt Stop is unaffected' "$OUT"

# 2026-09-13 反向斷言：Codex 內部 thread 的 Stop 帶 transcript_path:null，舊版回 PreToolUse 式 deny、被總機當 block 連擋 166 次
OUT=$(jq -nc '{hook_event_name:"Stop",session_id:"codex-internal-null",transcript_path:null,cwd:"/",stop_hook_active:false}' | call_hook 2>/dev/null)
[ -z "$OUT" ] && pass 'Stop with null transcript_path is silent, never a PreToolUse deny' || fail 'Stop with null transcript_path is silent, never a PreToolUse deny' empty "$OUT"
OUT=$(printf '{"hook_event_name":"Stop","session_id":42,"transcript_path":["x"]}' | call_hook 2>/dev/null)
[ -z "$OUT" ] && pass 'Stop with non-string fields is silent' || fail 'Stop with non-string fields is silent' empty "$OUT"
OUT=$(printf 'not json' | call_hook 2>/dev/null)
expect_deny 'unparseable payload without a Stop event still denies' 'invalid hook payload' "$OUT"
OUT=$(jq -nc '{hook_event_name:"PreToolUse",tool_name:"Skill",tool_input:{skill:"implement"},session_id:"null-transcript-arm",tool_use_id:"tool-null",transcript_path:null}' | call_hook 2>/dev/null)
expect_deny 'PreToolUse arming with null transcript_path still denies' 'required arming payload' "$OUT"

SESSION=subagent-implement
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-subagent-arm agent-worker | call_hook 2>/dev/null)
[ -z "$OUT" ] && pass 'subagent Skill implement does not arm main TDD gate' || fail 'subagent Skill implement does not arm main TDD gate' empty "$OUT"
[ ! -e "$PENDING/$SESSION.json" ] && pass 'subagent Skill implement leaves no pending marker' || fail 'subagent Skill implement leaves no pending marker' absent present

SESSION=subagent-stop
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-main-arm | call_hook >/dev/null
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" '' tool-use-1 agent-worker | call_hook 2>/dev/null)
expect_allow 'subagent Stop ignores a main-session pending marker' "$OUT"
[ -e "$PENDING/$SESSION.json" ] && pass 'subagent Stop does not consume main-session pending marker' || fail 'subagent Stop does not consume main-session pending marker' present absent

OUT=$(printf '%s' '{bad json' | call_hook 2>/dev/null)
expect_deny 'invalid hook payload denies arming' 'invalid hook payload' "$OUT"
RAW=$(jq -nc --arg session "$SESSION" --arg transcript "$TRANSCRIPT" '{hook_event_name:"PreToolUse",tool_name:"Skill",session_id:$session,transcript_path:$transcript,tool_use_id:"tool-invalid-skill",tool_input:{skill:{name:"tdd"}}}')
OUT=$(printf '%s' "$RAW" | call_hook 2>/dev/null)
expect_deny 'invalid non-Matt Skill payload does not silently pass' 'invalid hook payload' "$OUT"
SESSION=invalid-agent-id
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
RAW=$(jq -nc --arg session "$SESSION" --arg transcript "$TRANSCRIPT" '{hook_event_name:"PreToolUse",tool_name:"Skill",session_id:$session,transcript_path:$transcript,tool_use_id:"tool-invalid-agent",agent_id:{bad:true},tool_input:{skill:"implement"}}')
OUT=$(printf '%s' "$RAW" | call_hook 2>/dev/null)
expect_deny 'non-string subagent id denies malformed hook payload' 'invalid hook payload' "$OUT"

FALLBACK_PATH="$TMP/fallback-path"
mkdir -p "$FALLBACK_PATH"
for COMMAND in bash python3 node stat id chmod mkdir mktemp mv ln unlink cat; do
  TARGET=$(command -v "$COMMAND")
  [ -n "$TARGET" ] && ln -s "$TARGET" "$FALLBACK_PATH/$COMMAND"
done
SESSION=fallback-non-matt
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" tdd tool-fallback-non-matt | PATH="$FALLBACK_PATH" call_hook 2>/dev/null)
[ -z "$OUT" ] && pass 'missing jq fallback preserves legal non-Matt Skill' || fail 'missing jq fallback preserves legal non-Matt Skill' empty "$OUT"
SESSION=fallback-implement
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-fallback-arm | PATH="$FALLBACK_PATH" MATT_TDD_PENDING_DIR="$TMP/fallback-pending" call_hook 2>/dev/null)
expect_allow 'missing jq fallback still arms protected Skill implement' "$OUT"
append_implement_call "$TRANSCRIPT" tool-fallback-arm
append_tool_call "$TRANSCRIPT" Edit
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | PATH="$FALLBACK_PATH" MATT_TDD_PENDING_DIR="$TMP/fallback-pending" call_hook 2>/dev/null)
expect_advise 'missing jq fallback still advises on armed Stop' 'decision manifest' "$OUT"

for FIELD in session transcript tool-use; do
  SESSION="missing-$FIELD"
  TRANSCRIPT="$TMP/$SESSION.jsonl"
  new_transcript "$TRANSCRIPT"
  case "$FIELD" in
    session) RAW=$(jq -nc --arg transcript "$TRANSCRIPT" '{hook_event_name:"PreToolUse",tool_name:"Skill",transcript_path:$transcript,tool_use_id:"tool-missing-session",tool_input:{skill:"implement"}}') ;;
    transcript) RAW=$(jq -nc --arg session "$SESSION" '{hook_event_name:"PreToolUse",tool_name:"Skill",session_id:$session,tool_use_id:"tool-missing-transcript",tool_input:{skill:"implement"}}') ;;
    tool-use) RAW=$(jq -nc --arg session "$SESSION" --arg transcript "$TRANSCRIPT" '{hook_event_name:"PreToolUse",tool_name:"Skill",session_id:$session,transcript_path:$transcript,tool_input:{skill:"implement"}}') ;;
  esac
  OUT=$(printf '%s' "$RAW" | call_hook 2>/dev/null)
  expect_deny "missing required $FIELD payload denies arming" 'required arming payload' "$OUT"
done

for SESSION in . ..; do
  TRANSCRIPT="$TMP/dot-session-${SESSION//./x}.jsonl"
  new_transcript "$TRANSCRIPT"
  OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-dot-session | call_hook 2>/dev/null)
  expect_deny "session id $SESSION denies arming" 'session id' "$OUT"
done

SESSION=dot-run
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement . | call_hook 2>/dev/null)
expect_deny 'dot run id denies arming' 'tool use id' "$OUT"
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement 'bad/id' | call_hook 2>/dev/null)
expect_deny 'invalid implement tool use id denies arming' 'tool use id' "$OUT"

SESSION=existing-marker
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-first | call_hook >/dev/null
FIRST=$(cksum "$PENDING/$SESSION.json")
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-second | call_hook 2>/dev/null)
expect_deny 'second Skill implement is denied while pending marker exists' 'already pending' "$OUT"
SECOND=$(cksum "$PENDING/$SESSION.json")
[ "$FIRST" = "$SECOND" ] && pass 'second Skill implement cannot overwrite first marker' || fail 'second Skill implement cannot overwrite first marker' "$FIRST" "$SECOND"

SESSION=no-manifest
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-1 | call_hook 2>/dev/null)
expect_allow 'Skill implement arms the session' "$OUT"
append_implement_call "$TRANSCRIPT" tool-arm-1
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
# 2026-10-09：implement 契約規定使用者選測試模式前不得建 manifest；等人回答的那段只有探查、沒有改檔或派工，不算漏建
append_tool_call "$TRANSCRIPT" Bash
append_tool_call "$TRANSCRIPT" Read
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
[ -z "$OUT" ] && pass 'Stop without a manifest stays silent before any work tool' || fail 'Stop without a manifest stays silent before any work tool' empty "$OUT"
[ -e "$PENDING/$SESSION.json" ] && pass 'silent pre-work Stop keeps the pending marker' || fail 'silent pre-work Stop keeps the pending marker' present absent
append_tool_call "$TRANSCRIPT" Edit
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'Stop without a manifest advises once an Edit happened after arming' 'decision manifest' "$OUT"

# 2026-10-09 反向斷言：Stop 的 additionalContext 會讓對話續跑（官方 hooks 文件 Stop decision control），
#   舊版不看 stop_hook_active，提示叫醒模型、模型回話又觸發 Stop，本機一個 session 8 秒內連跳 4 次直到 loop guard 放行並刪 marker
BEFORE=$(audit_lines)
OUT=$(stop_payload_active "$SESSION" "$TRANSCRIPT" true | call_hook 2>/dev/null)
[ -z "$OUT" ] && pass 'Stop continuation (stop_hook_active=true) stays silent' || fail 'Stop continuation (stop_hook_active=true) stays silent' empty "$OUT"
[ "$(audit_lines)" = "$BEFORE" ] && pass 'Stop continuation does not advance the loop guard' || fail 'Stop continuation does not advance the loop guard' "$BEFORE" "$(audit_lines)"
[ -e "$PENDING/$SESSION.json" ] && pass 'Stop continuation keeps the pending marker' || fail 'Stop continuation keeps the pending marker' present absent
OUT=$(stop_payload_active "$SESSION" "$TRANSCRIPT" false | call_hook 2>/dev/null)
expect_advise 'natural Stop (stop_hook_active=false) still advises' 'decision manifest' "$OUT"

for TOOL_NAME in Write NotebookEdit Agent; do
  SESSION="no-manifest-$TOOL_NAME"
  TRANSCRIPT="$TMP/$SESSION.jsonl"
  new_transcript "$TRANSCRIPT"
  payload PreToolUse "$SESSION" "$TRANSCRIPT" implement "tool-arm-$TOOL_NAME" | call_hook >/dev/null
  append_implement_call "$TRANSCRIPT" "tool-arm-$TOOL_NAME"
  append_tool_call "$TRANSCRIPT" "$TOOL_NAME"
  OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
  expect_advise "$TOOL_NAME after arming counts as started work" 'decision manifest' "$OUT"
done

SESSION=no-manifest-edit-before-arm
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
append_tool_call "$TRANSCRIPT" Edit tool-edit-before
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-before | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-before
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
[ -z "$OUT" ] && pass 'Edit before arming does not count as started work' || fail 'Edit before arming does not count as started work' empty "$OUT"

SESSION=no-manifest-bad-transcript
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-bad | call_hook >/dev/null
printf '%s\n' '{not json' >> "$TRANSCRIPT"
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'unreadable post-arm transcript still advises a missing manifest' 'decision manifest' "$OUT"

SESSION=required-order
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
append_tdd_call "$TRANSCRIPT"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-2 | call_hook >/dev/null
append_same_record_calls "$TRANSCRIPT" tool-arm-2
append_tdd_result "$TRANSCRIPT" tool-tdd-same
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'Skill tdd before or in the armed implement record does not count' 'strictly later' "$OUT"
append_tdd_prose "$TRANSCRIPT"
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'prose containing tdd does not count' 'strictly later' "$OUT"
append_tdd_call "$TRANSCRIPT" tool-tdd-success
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'Skill tdd without a later matching tool result does not count' 'successful Skill(tdd)' "$OUT"
append_tdd_result "$TRANSCRIPT" tool-tdd-success false
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_allow 'required ticket with later successful Skill tdd allows' "$OUT"
if [ ! -e "$PENDING/$SESSION.json" ] && [ -e "$ROOT/$SESSION/$RUN_ID/decision.json" ]; then
  pass 'successful Stop clears pending marker and preserves decision manifest'
else
  fail 'successful Stop clears pending marker and preserves decision manifest' 'pending absent and manifest present' 'lifecycle mismatch'
fi
VALIDATION=$(node "$POLICY" validate --session "$SESSION" --run "$RUN_ID" 2>/dev/null)
printf '%s' "$VALIDATION" | grep -q '"valid":true' && pass 'closeout validates the preserved decision manifest' || fail 'closeout validates the preserved decision manifest' valid "$VALIDATION"
node "$POLICY" consume --session "$SESSION" --run "$RUN_ID" >/dev/null
[ ! -e "$ROOT/$SESSION/$RUN_ID/decision.json" ] && pass 'terminal consume removes the decision manifest' || fail 'terminal consume removes the decision manifest' absent present

SESSION=runtime-result
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-runtime | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-runtime
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
append_tdd_call "$TRANSCRIPT" tool-tdd-runtime
append_tdd_runtime_result "$TRANSCRIPT" tool-tdd-runtime true
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_allow 'runtime Skill result with toolUseResult success allows' "$OUT"

SESSION=runtime-result-error
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-runtime-error | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-runtime-error
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
append_tdd_call "$TRANSCRIPT" tool-tdd-runtime-error
append_tdd_runtime_result "$TRANSCRIPT" tool-tdd-runtime-error false
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'runtime Skill result with toolUseResult failure advises' 'successful Skill(tdd)' "$OUT"

SESSION=runtime-result-mismatch
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-runtime-mismatch | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-runtime-mismatch
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
append_tdd_call "$TRANSCRIPT" tool-tdd-runtime-mismatch
append_tdd_runtime_result "$TRANSCRIPT" tool-tdd-runtime-mismatch true implement
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'runtime Skill result with mismatched command advises' 'successful Skill(tdd)' "$OUT"

SESSION=errored-tdd
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-error | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-error
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
append_tdd_call "$TRANSCRIPT" tool-tdd-error
append_tdd_result "$TRANSCRIPT" tool-tdd-error true
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'errored Skill tdd does not count' 'successful Skill(tdd)' "$OUT"

for VARIANT in missing null string-false; do
  SESSION="invalid-is-error-$VARIANT"
  TRANSCRIPT="$TMP/$SESSION.jsonl"
  TICKETS=$(ticket_path "$SESSION")
  new_transcript "$TRANSCRIPT"
  write_required_ticket "$TICKETS"
  payload PreToolUse "$SESSION" "$TRANSCRIPT" implement "tool-arm-$VARIANT" | call_hook >/dev/null
  append_implement_call "$TRANSCRIPT" "tool-arm-$VARIANT"
  RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
  node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
  append_tdd_call "$TRANSCRIPT" "tool-tdd-$VARIANT"
  append_tdd_result_variant "$TRANSCRIPT" "tool-tdd-$VARIANT" "$VARIANT"
  OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
  expect_advise "Skill tdd is_error $VARIANT does not count" 'successful Skill(tdd)' "$OUT"
done

SESSION=direct-slash
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-direct-slash | call_hook >/dev/null
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'direct slash without post-arm Skill tdd advises' 'successful Skill(tdd)' "$OUT"
append_tdd_call "$TRANSCRIPT" tool-tdd-direct-slash
append_tdd_result "$TRANSCRIPT" tool-tdd-direct-slash
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_allow 'direct slash arm with later successful Skill tdd allows without implement record' "$OUT"

SESSION=pre-arm-tdd-only
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
append_tdd_call "$TRANSCRIPT" tool-tdd-pre-arm
append_tdd_result "$TRANSCRIPT" tool-tdd-pre-arm
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-pre-arm-tdd | call_hook >/dev/null
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'only pre-arm successful Skill tdd does not count for v3' 'successful Skill(tdd)' "$OUT"

SESSION=missing-implement-record
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-missing | call_hook >/dev/null
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
set_marker_contract "$PENDING/$SESSION.json" 'MATT_TDD_PENDING v2'
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
append_tdd_call "$TRANSCRIPT"
append_tdd_result "$TRANSCRIPT"
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'legacy v2 missing armed implement transcript record advises' 'implement tool_use_id' "$OUT"

SESSION=partial-prefix
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
printf '%s' '{"type":"assistant","message":{"content":[' > "$TRANSCRIPT"
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-partial-prefix | call_hook 2>/dev/null)
expect_deny 'partial transcript prefix denies v3 arming' 'transcript prefix' "$OUT"
[ ! -e "$PENDING/$SESSION.json" ] && [ ! -L "$PENDING/$SESSION.json" ] && pass 'partial transcript prefix leaves no marker' || fail 'partial transcript prefix leaves no marker' absent present

SESSION=hash-free-state
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
jq -nc '{type:"user",message:{content:[]}}' > "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-hash-free | call_hook >/dev/null
if jq -e '(keys == ["contract","implement_tool_use_id","run_id","session_id","transcript_path","transcript_prefix_bytes"]) and (.transcript_prefix_bytes | type == "number")' "$PENDING/$SESSION.json" >/dev/null 2>&1; then
  pass 'armed state records the prefix offset and no digest field'
else
  fail 'armed state records the prefix offset and no digest field' 'exact key set with numeric prefix bytes' "$(cat "$PENDING/$SESSION.json")"
fi

SESSION=prefix-truncated
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
jq -nc '{type:"user",message:{content:[]}}' > "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-prefix-truncated | call_hook >/dev/null
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
new_transcript "$TRANSCRIPT"
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'transcript shorter than the armed prefix offset advises' 'transcript prefix' "$OUT"

SESSION=prefix-tamper
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
jq -nc '{type:"user",message:{content:[]}}' > "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-prefix-tamper | call_hook >/dev/null
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
python3 - "$TRANSCRIPT" <<'PY'
import sys
path=sys.argv[1]
with open(path,"r+b") as source:
  value=bytearray(source.read())
  value[0] = 88 if value[0] != 88 else 89
  source.seek(0)
  source.write(value)
PY
append_tdd_call "$TRANSCRIPT" tool-tdd-prefix-tamper
append_tdd_result "$TRANSCRIPT" tool-tdd-prefix-tamper
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'corrupted transcript prefix still advises through the JSON parse' 'malformed JSON' "$OUT"

SESSION=pre-arm-malformed
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
printf '%s\n' '{bad json' > "$TRANSCRIPT"
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-pre-arm-malformed | call_hook 2>/dev/null)
expect_deny 'malformed arm-prefix JSON denies v3 arming' 'transcript prefix' "$OUT"
[ ! -e "$PENDING/$SESSION.json" ] && [ ! -L "$PENDING/$SESSION.json" ] && pass 'malformed arm-prefix JSON leaves no marker' || fail 'malformed arm-prefix JSON leaves no marker' absent present

SESSION=malformed-implement-record
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-malformed-record | call_hook >/dev/null
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
jq -nc --arg tool_use tool-arm-malformed-record '{type:"assistant",message:{content:[{type:"tool_use",id:$tool_use,name:"Skill",input:{skill:"tdd"}}]}}' >> "$TRANSCRIPT"
append_tdd_call "$TRANSCRIPT" tool-tdd-malformed-record
append_tdd_result "$TRANSCRIPT" tool-tdd-malformed-record
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'malformed v3 implement record blocks Stop' 'implement record' "$OUT"

SESSION=duplicate-implement-record
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-duplicate-record | call_hook >/dev/null
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-duplicate-record
append_implement_call "$TRANSCRIPT" tool-arm-duplicate-record
append_tdd_call "$TRANSCRIPT" tool-tdd-duplicate-record
append_tdd_result "$TRANSCRIPT" tool-tdd-duplicate-record
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'duplicate v3 implement records block Stop' 'implement record' "$OUT"

SESSION=assistant-content-object
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-assistant-content-object | call_hook >/dev/null
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
jq -nc '{type:"assistant",message:{content:{type:"text",text:"not-a-list"}}}' >> "$TRANSCRIPT"
append_tdd_call "$TRANSCRIPT" tool-tdd-assistant-content-object
append_tdd_result "$TRANSCRIPT" tool-tdd-assistant-content-object
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'assistant content object invalidates v3 scanner' 'assistant transcript' "$OUT"

SESSION=invalid-tdd-tool-id
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-invalid-tdd-id | call_hook >/dev/null
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
jq -nc '{type:"assistant",message:{content:[{type:"tool_use",name:"Skill",input:{skill:"tdd"}}]}}' >> "$TRANSCRIPT"
jq -nc '{type:"user",message:{content:[{type:"tool_result",is_error:false,content:"loaded"}]}}' >> "$TRANSCRIPT"
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'TDD tool and result without valid ids invalidate v3 scanner' 'successful Skill(tdd)' "$OUT"

SESSION=all-waived
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_waived_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-3 | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-3
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_allow 'all-waived manifest allows without Skill tdd' "$OUT"
[ ! -e "$PENDING/$SESSION.json" ] && [ -e "$ROOT/$SESSION/$RUN_ID/decision.json" ] && pass 'waived Stop preserves manifest for closeout' || fail 'waived Stop preserves manifest for closeout' 'pending absent and manifest present' 'lifecycle mismatch'
VALIDATION=$(node "$POLICY" validate --session "$SESSION" --run "$RUN_ID" 2>/dev/null)
printf '%s' "$VALIDATION" | grep -q '"valid":true' && pass 'all-waived closeout validates preserved manifest' || fail 'all-waived closeout validates preserved manifest' valid "$VALIDATION"
node "$POLICY" consume --session "$SESSION" --run "$RUN_ID" >/dev/null
[ ! -e "$ROOT/$SESSION/$RUN_ID/decision.json" ] && pass 'all-waived terminal consume removes manifest' || fail 'all-waived terminal consume removes manifest' absent present

SESSION=not-started
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-4 | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-4
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" not-started --session "$SESSION" --run "$RUN_ID" --reason preflight-only >/dev/null
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_allow 'validated not-started manifest allows' "$OUT"
[ ! -e "$PENDING/$SESSION.json" ] && [ ! -e "$ROOT/$SESSION/$RUN_ID/decision.json" ] && pass 'not-started Stop consumes both control files' || fail 'not-started Stop consumes both control files' absent present

SESSION=malformed-manifest
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-7 | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-7
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
mkdir -p "$ROOT/$SESSION/$RUN_ID"
printf '{bad json\n' > "$ROOT/$SESSION/$RUN_ID/decision.json"
chmod 600 "$ROOT/$SESSION/$RUN_ID/decision.json"
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'malformed manifest blocks Stop' 'manifest' "$OUT"

for CASE in symlink non-directory unwritable; do
  CASE_ROOT="$TMP/pending-$CASE"
  case "$CASE" in
    symlink) mkdir -p "$TMP/pending-target"; ln -s "$TMP/pending-target" "$CASE_ROOT" ;;
    non-directory) printf x > "$CASE_ROOT" ;;
    unwritable) mkdir -p "$CASE_ROOT"; chmod 500 "$CASE_ROOT" ;;
  esac
  SESSION="pending-$CASE"
  TRANSCRIPT="$TMP/$SESSION.jsonl"
  new_transcript "$TRANSCRIPT"
  OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement "tool-$CASE" | MATT_TDD_PENDING_DIR="$CASE_ROOT" call_hook 2>/dev/null)
  expect_deny "$CASE pending root denies arming" 'pending root' "$OUT"
done

SESSION=cleanup-failure
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-cleanup | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-cleanup
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" not-started --session "$SESSION" --run "$RUN_ID" --reason preflight-only >/dev/null
SHIMS="$TMP/shims-cleanup"
mkdir -p "$SHIMS"
REAL_NODE=$(command -v node)
write_shim "$SHIMS" node "case \"\$1 \$2\" in *tdd-policy.mjs\\ consume) exit 1 ;; esac; \"$REAL_NODE\" \"\$@\""
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | PATH="$SHIMS:$PATH" call_hook 2>/dev/null)
expect_advise 'not-started cleanup failure blocks without consuming the pending marker' 'could not be consumed' "$OUT"
[ -e "$PENDING/$SESSION.json" ] && [ -e "$ROOT/$SESSION/$RUN_ID/decision.json" ] && pass 'not-started cleanup failure keeps both control files retryable' || fail 'not-started cleanup failure keeps both control files retryable' present absent
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_allow 'not-started cleanup retry succeeds' "$OUT"

SESSION=cleanup-backup-failure
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-cleanup-backup | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-cleanup-backup
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" not-started --session "$SESSION" --run "$RUN_ID" --reason preflight-only >/dev/null
SHIMS="$TMP/shims-cleanup-backup"
mkdir -p "$SHIMS"
REAL_UNLINK=$(command -v unlink)
write_shim "$SHIMS" unlink "case \"\$1\" in *.cleanup) exit 1 ;; esac; \"$REAL_UNLINK\" \"\$@\""
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | PATH="$SHIMS:$PATH" call_hook 2>/dev/null)
expect_allow 'consumed state cleanup-backup failure is advisory' "$OUT"
printf '%s' "$OUT" | grep -q 'cleanup backup' && pass 'cleanup-backup failure is visible' || fail 'cleanup-backup failure is visible' 'Stop advisory' "$OUT"
[ ! -e "$PENDING/$SESSION.json" ] && [ ! -e "$ROOT/$SESSION/$RUN_ID/decision.json" ] && pass 'advisory cleanup leaves consumed control state absent' || fail 'advisory cleanup leaves consumed control state absent' absent present
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-cleanup-backup-next | call_hook 2>/dev/null)
expect_armed 'next implement can arm after cleanup-backup failure' "$OUT"
append_implement_call "$TRANSCRIPT" tool-cleanup-backup-next
NEXT_RUN=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" not-started --session "$SESSION" --run "$NEXT_RUN" --reason preflight-only >/dev/null
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_allow 'next implement cleans independently of stale backup' "$OUT"

SESSION=post-create-cleanup-failure
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
SHIMS="$TMP/shims-post-create-cleanup"
mkdir -p "$SHIMS"
REAL_UNLINK=$(command -v unlink)
write_shim "$SHIMS" unlink "case \"\$1\" in *.ready) exit 1 ;; esac; \"$REAL_UNLINK\" \"\$@\""
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-cleanup-first | PATH="$SHIMS:$PATH" call_hook 2>/dev/null)
expect_deny 'ready-file cleanup failure denies first arm' 'temp cleanup failed' "$OUT"
[ ! -e "$PENDING/$SESSION.json" ] && [ ! -L "$PENDING/$SESSION.json" ] && pass 'ready-file cleanup failure rolls back exclusive marker' || fail 'ready-file cleanup failure rolls back exclusive marker' absent present
OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-cleanup-second | call_hook 2>/dev/null)
expect_armed 'retry after ready-file cleanup failure can arm' "$OUT"
append_implement_call "$TRANSCRIPT" tool-cleanup-second
append_tool_call "$TRANSCRIPT" Edit
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'Stop remains governed after cleanup-failure retry' 'decision manifest' "$OUT"

REAL_CHMOD=$(command -v chmod)
REAL_MV=$(command -v mv)
for CASE in temp write chmod rename; do
  SHIMS="$TMP/shims-$CASE"
  mkdir -p "$SHIMS"
  case "$CASE" in
    temp) write_shim "$SHIMS" mktemp 'exit 1' ;;
    write) write_shim "$SHIMS" mktemp 'target=${1%XXXXXX}writefail; mkdir "$target"; printf "%s\\n" "$target"' ;;
    chmod) write_shim "$SHIMS" chmod "case \"\$*\" in *.pending.*) exit 1 ;; esac; \"$REAL_CHMOD\" \"\$@\"" ;;
    rename) write_shim "$SHIMS" mv 'exit 1' ;;
  esac
  SESSION="failure-$CASE"
  TRANSCRIPT="$TMP/$SESSION.jsonl"
  new_transcript "$TRANSCRIPT"
  OUT=$(payload PreToolUse "$SESSION" "$TRANSCRIPT" implement "tool-$CASE" | PATH="$SHIMS:$PATH" call_hook 2>/dev/null)
  expect_deny "$CASE failure denies arming" "$CASE" "$OUT"
done

# 回歸收尾正例必須打真 helper。stub 自報 count 看不出 Stop 仍用 required_count 把 required 票叫去跑 tdd。
SESSION=regression-closeout-required
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-regression-closeout | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-regression-closeout
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
MANIFEST="$ROOT/$SESSION/$RUN_ID/decision.json"
INIT_OUT=$(node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" --testing-mode regression-closeout 2>"$TMP/regression-init.err")
INIT_STATUS=$?
VALIDATION=$(node "$POLICY" validate --session "$SESSION" --run "$RUN_ID" 2>&1 || true)
if [ "$INIT_STATUS" -eq 0 ] && printf '%s' "$INIT_OUT" | jq -e '.testing_mode == "regression-closeout" and .required_count == 1 and .tdd_required_count == 0' >/dev/null 2>&1 && [ -f "$MANIFEST" ] && jq -e '.status == "started" and .testing_mode == "regression-closeout" and .tickets[0].decision == "required"' "$MANIFEST" >/dev/null; then
  pass 'real helper regression-closeout init keeps required and records the mode'
else
  fail 'real helper regression-closeout init keeps required and records the mode' 'started required testing_mode regression-closeout with tdd_required_count 0' "status=$INIT_STATUS stdout=$INIT_OUT stderr=$(cat "$TMP/regression-init.err") validate=$VALIDATION manifest=$( [ -f "$MANIFEST" ] && cat "$MANIFEST" || echo missing )"
fi
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_allow 'regression-closeout required ticket is not asked for Skill tdd' "$OUT"
if [ -f "$MANIFEST" ] && jq -e '.status == "started" and .testing_mode == "regression-closeout" and .tickets[0].decision == "required"' "$MANIFEST" >/dev/null && [ ! -e "$PENDING/$SESSION.json" ]; then
  pass 'regression-closeout Stop keeps the started manifest'
else
  fail 'regression-closeout Stop keeps the started manifest' 'pending absent and started required manifest retained' "pending=$( [ -e "$PENDING/$SESSION.json" ] && echo present || echo absent ) manifest=$( [ -f "$MANIFEST" ] && cat "$MANIFEST" || echo missing ) stop=$OUT"
fi

SESSION=tdd-mode-reminds
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-tdd-reminds | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-tdd-reminds
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" --testing-mode tdd >/dev/null
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_advise 'tdd mode without a successful Skill tdd still advises' 'successful Skill(tdd)' "$OUT"
MANIFEST="$ROOT/$SESSION/$RUN_ID/decision.json"
if [ -e "$PENDING/$SESSION.json" ] && [ -f "$MANIFEST" ] && jq -e '.status == "started" and .tickets[0].decision == "required"' "$MANIFEST" >/dev/null; then
  pass 'tdd reminder keeps the started required manifest'
else
  fail 'tdd reminder keeps the started required manifest' 'pending present and started required manifest' "pending=$( [ -e "$PENDING/$SESSION.json" ] && echo present || echo absent ) manifest=$( [ -f "$MANIFEST" ] && cat "$MANIFEST" || echo missing )"
fi

SESSION=legacy-count-fallback
TRANSCRIPT="$TMP/$SESSION.jsonl"
TICKETS=$(ticket_path "$SESSION")
new_transcript "$TRANSCRIPT"
write_required_ticket "$TICKETS"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-count-fallback | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-count-fallback
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" init --session "$SESSION" --run "$RUN_ID" --tickets "$TICKETS" >/dev/null
REAL_NODE=$(command -v node)
REAL_PYTHON=$(command -v python3)
SHIMS="$TMP/shims-count-fallback"
mkdir -p "$SHIMS"
cat > "$SHIMS/strip_tdd_required_count.py" <<'PY'
import json, sys
raw = sys.stdin.read()
try:
    value = json.loads(raw)
except Exception:
    sys.stdout.write(raw)
else:
    if isinstance(value, dict):
        value.pop("tdd_required_count", None)
    json.dump(value, sys.stdout)
    if raw.endswith("\n"):
        sys.stdout.write("\n")
PY
cat > "$SHIMS/node" <<EOF
#!/bin/sh
if [ "\$2" = validate ]; then
  err=\$(mktemp)
  out=\$("$REAL_NODE" "\$@" 2>"\$err")
  status=\$?
  cat "\$err" >&2
  rm -f "\$err"
  printf '%s' "\$out" | "$REAL_PYTHON" "$SHIMS/strip_tdd_required_count.py"
  exit \$status
fi
exec "$REAL_NODE" "\$@"
EOF
chmod 700 "$SHIMS/node"
RAW_VALIDATION=$(PATH="$SHIMS:$PATH" node "$POLICY" validate --session "$SESSION" --run "$RUN_ID" 2>/dev/null || true)
if printf '%s' "$RAW_VALIDATION" | jq -e '.required_count == 1 and (has("tdd_required_count") | not)' >/dev/null 2>&1; then
  pass 'fallback fixture hides tdd_required_count and keeps required_count'
else
  fail 'fallback fixture hides tdd_required_count and keeps required_count' 'required_count 1 without tdd_required_count' "$RAW_VALIDATION"
fi
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | PATH="$SHIMS:$PATH" call_hook 2>/dev/null)
expect_advise 'missing tdd_required_count still reminds from required_count' 'successful Skill(tdd)' "$OUT"
MANIFEST="$ROOT/$SESSION/$RUN_ID/decision.json"
if [ -e "$PENDING/$SESSION.json" ] && [ -f "$MANIFEST" ] && jq -e '.status == "started" and .tickets[0].decision == "required"' "$MANIFEST" >/dev/null; then
  pass 'required_count fallback reminder keeps the started manifest'
else
  fail 'required_count fallback reminder keeps the started manifest' 'pending present and started required manifest' "pending=$( [ -e "$PENDING/$SESSION.json" ] && echo present || echo absent ) manifest=$( [ -f "$MANIFEST" ] && cat "$MANIFEST" || echo missing ) stop=$OUT"
fi

SESSION=not-started-cleanup-kept
TRANSCRIPT="$TMP/$SESSION.jsonl"
new_transcript "$TRANSCRIPT"
payload PreToolUse "$SESSION" "$TRANSCRIPT" implement tool-arm-not-started-kept | call_hook >/dev/null
append_implement_call "$TRANSCRIPT" tool-arm-not-started-kept
RUN_ID=$(jq -r '.run_id' "$PENDING/$SESSION.json")
node "$POLICY" not-started --session "$SESSION" --run "$RUN_ID" --reason user-deferred >/dev/null
OUT=$(payload Stop "$SESSION" "$TRANSCRIPT" | call_hook 2>/dev/null)
expect_allow 'not-started still allows without inventing a testing mode' "$OUT"
if [ ! -e "$PENDING/$SESSION.json" ] && [ ! -e "$ROOT/$SESSION/$RUN_ID/decision.json" ]; then
  pass 'not-started Stop still consumes both control files'
else
  fail 'not-started Stop still consumes both control files' absent present
fi

printf 'TOTAL %d passed, %d failed\n' "$PASSES" "$FAILURES"
[ "$FAILURES" -eq 0 ]
