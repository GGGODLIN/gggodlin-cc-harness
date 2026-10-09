#!/bin/bash

set -euo pipefail

export CC_VENDOR=""
export ANTHROPIC_DEFAULT_OPUS_MODEL=""
export ANTHROPIC_DEFAULT_FABLE_MODEL=""
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PERMIT="$SCRIPT_DIR/review-spec-dual-permit.py"
VERIFY="$SCRIPT_DIR/review-spec-dual-verify.py"
TMP=$(mktemp -d)
HOME="$TMP/home"
export HOME
RUNTIME="$TMP/runtime"
SESSION="seat-test-$$"
PROJECT_DIR="$HOME/.claude/projects/seat-test"
MAIN="$PROJECT_DIR/$SESSION.jsonl"
SUBAGENTS="$PROJECT_DIR/$SESSION/subagents"
SPEC="$TMP/spec.md"
PASSES=0
FAILURES=0

cleanup() {
  rm -rf "$TMP"
}
trap cleanup EXIT
mkdir -p "$SUBAGENTS" "$RUNTIME" "$HOME/.claude/logs"
chmod 700 "$HOME" "$HOME/.claude" "$HOME/.claude/projects" "$HOME/.claude/projects/seat-test" "$PROJECT_DIR" "$SUBAGENTS" "$RUNTIME" "$HOME/.claude/logs"
printf '%s\n' 'selection fixture' > "$SPEC"
chmod 600 "$SPEC"

pass() {
  PASSES=$((PASSES + 1))
  printf 'PASS: %s\n' "$1"
}

fail() {
  FAILURES=$((FAILURES + 1))
  printf 'FAIL: %s\n' "$1"
  printf '  expected: %s\n  actual: %s\n' "$2" "$3"
}

assert_eq() {
  local label=$1 expected=$2 actual=$3
  if [ "$expected" = "$actual" ]; then
    pass "$label"
  else
    fail "$label" "$expected" "$actual"
  fi
}

write_command() {
  local uuid=$1
  jq -nc --arg session "$SESSION" --arg uuid "$uuid" --arg spec "$SPEC" --arg cwd "$TMP" \
    '{type:"user",userType:"external",sessionId:$session,uuid:$uuid,timestamp:"2026-09-09T03:00:00Z",cwd:$cwd,message:{role:"user",content:("<command-name>/review-spec</command-name>\n<command-message>review-spec</command-message>\n<command-args>3 "+$spec+"</command-args>")}}' > "$MAIN"
}

write_selection() {
  local text=$1 uuid=$2
  jq -nc --arg session "$SESSION" --arg text "$text" --arg uuid "$uuid" \
    '{type:"user",userType:"external",sessionId:$session,uuid:$uuid,timestamp:"2026-09-09T03:01:00Z",message:{role:"user",content:$text}}' >> "$MAIN"
}

write_recommendation() {
  local seats=$1 uuid=$2
  jq -nc --arg session "$SESSION" --arg uuid "$uuid" --arg permit "$PERMIT_ID" --arg seats "$seats" \
    '{type:"assistant",sessionId:$session,uuid:$uuid,timestamp:"2026-09-09T03:00:30Z",message:{role:"assistant",content:("<review-spec-recommendation:v1 permit_id="+$permit+" seats="+$seats+">")}}' >> "$MAIN"
}

run_permit() {
  REVIEW_SPEC_DUAL_RUNTIME_DIR="$RUNTIME" REVIEW_SPEC_DUAL_NOW="2026-09-09T03:02:00Z" "$PERMIT" "$@"
}

run_verify() {
  REVIEW_SPEC_DUAL_RUNTIME_DIR="$RUNTIME" REVIEW_SPEC_DUAL_NOW="2026-09-09T03:03:00Z" "$VERIFY" \
    --session "$SESSION" --permit-id "$PERMIT_ID" \
    --expires-at "$EXPIRES_AT" --snapshot "$SNAPSHOT" "$@"
}

write_embedded_agent() {
  local id=$1 model=$2 packet=$3
  jq -nc --arg id "$id" --arg prompt "$packet" \
    '{type:"user",isSidechain:true,agentId:$id,message:{role:"user",content:$prompt}}' > "$SUBAGENTS/agent-$id.jsonl"
  jq -nc --arg id "$id" --arg model "$model" \
    '{type:"assistant",isSidechain:true,agentId:$id,attributionAgent:"architecture-critic",message:{role:"assistant",model:$model,stop_reason:"end_turn",content:[{type:"text",text:"embedded report"}]}}' >> "$SUBAGENTS/agent-$id.jsonl"
}

write_agent() {
  local id=$1 model=$2 reference=$3
  local packet_path read_result
  packet_path=$(printf '%s' "$reference" | python3 -c 'import sys; print(next(line.split("=", 1)[1] for line in sys.stdin.read().splitlines() if line.startswith("REVIEW_SPEC_PACKET_PATH=")))')
  read_result=$(python3 -c 'from pathlib import Path; import sys; print("\n".join(f"{index}\t{line}" for index, line in enumerate(Path(sys.argv[1]).read_text().splitlines(), 1)), end="")' "$packet_path")
  jq -nc --arg id "$id" --arg prompt "$reference" \
    '{type:"user",isSidechain:true,agentId:$id,message:{role:"user",content:$prompt}}' > "$SUBAGENTS/agent-$id.jsonl"
  jq -nc --arg id "$id" --arg model "$model" --arg path "$packet_path" \
    '{type:"assistant",isSidechain:true,agentId:$id,message:{role:"assistant",model:$model,stop_reason:"tool_use",content:[{type:"tool_use",id:"read_packet",name:"Read",input:{file_path:$path}}]}}' >> "$SUBAGENTS/agent-$id.jsonl"
  jq -nc --arg id "$id" --arg result "$read_result" \
    '{type:"user",isSidechain:true,agentId:$id,message:{role:"user",content:[{type:"tool_result",tool_use_id:"read_packet",content:$result}]}}' >> "$SUBAGENTS/agent-$id.jsonl"
  jq -nc --arg id "$id" --arg model "$model" \
    '{type:"assistant",isSidechain:true,agentId:$id,attributionAgent:"architecture-critic",message:{role:"assistant",model:$model,stop_reason:"end_turn",content:[{type:"text",text:"seat report"}]}}' >> "$SUBAGENTS/agent-$id.jsonl"
}

write_command single-command
OUT=$(run_permit issue --session "$SESSION" --spec "$SPEC")
PERMIT_ID=$(printf '%s' "$OUT" | jq -r '.permit_id')
SNAPSHOT=$(printf '%s' "$OUT" | jq -r '.snapshot_path')
EXPIRES_AT=$(printf '%s' "$OUT" | jq -r '.expires_at')
write_recommendation 'simplify:opus' single-recommendation
write_selection '只派 simplify 角度的 Opus，其他席位不派' single-selection
set +e
OUT=$(run_permit finalize --session "$SESSION" --seats failure:fable --recommendation-event single-recommendation 2>/dev/null)
STATUS=$?
set -e
assert_eq 'caller cannot replace explicit user seat' '3' "$STATUS"
assert_eq 'caller/user seat mismatch is explicit' 'selection-mismatch' "$(printf '%s' "$OUT" | jq -r '.reason')"
OUT=$(run_permit finalize --session "$SESSION" --seats simplify:opus --recommendation-event single-recommendation)
assert_eq 'single seat selection is authorized' 'simplify:opus' "$(printf '%s' "$OUT" | jq -r '.seats | join(",")')"
assert_eq 'finalized seat state carries no digest field' '0' "$(jq '[keys[] | select(test("sha|digest|checksum"; "i"))] | length' "$RUNTIME/$SESSION.json")"
CURRENT_LENS=simplify
PACKET=$(run_permit packet --session "$SESSION" --lens simplify --model opus --reference)
set +e
OUT=$(run_permit packet --session "$SESSION" --lens simplify --model fable 2>/dev/null)
STATUS=$?
set -e
assert_eq 'unselected Fable packet is denied' '3' "$STATUS"
assert_eq 'unselected Fable denial is explicit' 'seat-not-authorized' "$(printf '%s' "$OUT" | jq -r '.reason')"
write_agent single-opus claude-opus-5 "$PACKET"
OUT=$(run_verify --seat simplify:opus:single-opus)
assert_eq 'single seat verifies without an unselected pair' 'true' "$(printf '%s' "$OUT" | jq -r '.valid')"
assert_eq 'single seat report has no pair' '0' "$(printf '%s' "$OUT" | jq '.pairs | length')"
assert_eq 'single seat report identifies model' 'opus' "$(printf '%s' "$OUT" | jq -r '.seats[0].model')"
set +e
UNSELECTED_OUT=$(run_verify --seat simplify:opus:single-opus --seat simplify:fable:unselected 2>/dev/null)
UNSELECTED_STATUS=$?
set -e
assert_eq 'unselected seat cannot enter completion set' '3' "$UNSELECTED_STATUS"
assert_eq 'unselected seat mismatch is explicit' 'true' "$(printf '%s' "$UNSELECTED_OUT" | jq '.errors | any(. == "seat-set-mismatch")')"
RECEIPT=$(printf '%s' "$OUT" | jq -r '.receipt_path')
OUT=$(run_permit close --session "$SESSION" --permit-id "$PERMIT_ID" --receipt "$RECEIPT")
assert_eq 'single seat receipt closes permit' 'true' "$(printf '%s' "$OUT" | jq -r '.allowed')"

SESSION="seat-follow-single-$$"
PROJECT_DIR="$HOME/.claude/projects/seat-test-follow-single"
MAIN="$PROJECT_DIR/$SESSION.jsonl"
SUBAGENTS="$PROJECT_DIR/$SESSION/subagents"
mkdir -p "$SUBAGENTS"
chmod 700 "$PROJECT_DIR" "$SUBAGENTS"
write_command follow-single-command
OUT=$(run_permit issue --session "$SESSION" --spec "$SPEC")
PERMIT_ID=$(printf '%s' "$OUT" | jq -r '.permit_id')
write_recommendation 'simplify:opus' follow-single-recommendation
write_selection '照推薦' follow-single-selection
OUT=$(run_permit finalize --session "$SESSION" --seats simplify:opus --recommendation-event follow-single-recommendation --follow-recommendation)
assert_eq '照推薦 follows a single-seat recommendation' 'simplify:opus' "$(printf '%s' "$OUT" | jq -r '.seats | join(",")')"

SESSION="seat-stale-recommendation-$$"
PROJECT_DIR="$HOME/.claude/projects/seat-test-stale-recommendation"
MAIN="$PROJECT_DIR/$SESSION.jsonl"
SUBAGENTS="$PROJECT_DIR/$SESSION/subagents"
mkdir -p "$SUBAGENTS"
chmod 700 "$PROJECT_DIR" "$SUBAGENTS"
write_command stale-recommendation-command
OUT=$(run_permit issue --session "$SESSION" --spec "$SPEC")
PERMIT_ID=$(printf '%s' "$OUT" | jq -r '.permit_id')
write_recommendation 'simplify:opus' stale-recommendation-old
write_recommendation 'simplify:fable' stale-recommendation-new
write_selection '照推薦' stale-selection-old
write_selection '照推薦' stale-selection-new
set +e
OUT=$(run_permit finalize --session "$SESSION" --seats simplify:fable --selection-event stale-selection-old --recommendation-event stale-recommendation-new --follow-recommendation 2>/dev/null)
STATUS=$?
set -e
assert_eq 'superseded selection UUID is rejected' '3' "$STATUS"
assert_eq 'superseded selection denial is explicit' 'selection-event-superseded' "$(printf '%s' "$OUT" | jq -r '.reason')"
set +e
OUT=$(run_permit finalize --session "$SESSION" --seats simplify:opus --selection-event stale-selection-new --recommendation-event stale-recommendation-old --follow-recommendation 2>/dev/null)
STATUS=$?
set -e
assert_eq 'stale recommendation UUID is rejected' '3' "$STATUS"
assert_eq 'stale recommendation denial is explicit' 'recommendation-event-superseded' "$(printf '%s' "$OUT" | jq -r '.reason')"
OUT=$(run_permit finalize --session "$SESSION" --seats simplify:fable --selection-event stale-selection-new --recommendation-event stale-recommendation-new --follow-recommendation)
assert_eq 'latest recommendation is accepted' 'simplify:fable' "$(printf '%s' "$OUT" | jq -r '.seats | join(",")')"

SESSION="seat-no-selection-$$"
PROJECT_DIR="$HOME/.claude/projects/seat-test-no-selection"
MAIN="$PROJECT_DIR/$SESSION.jsonl"
SUBAGENTS="$PROJECT_DIR/$SESSION/subagents"
mkdir -p "$SUBAGENTS"
chmod 700 "$PROJECT_DIR" "$SUBAGENTS"
write_command no-selection-command
OUT=$(run_permit issue --session "$SESSION" --spec "$SPEC")
PERMIT_ID=$(printf '%s' "$OUT" | jq -r '.permit_id')
write_recommendation 'simplify:opus' no-selection-recommendation
set +e
OUT=$(run_permit finalize --session "$SESSION" --seats simplify:opus --recommendation-event no-selection-recommendation 2>/dev/null)
STATUS=$?
set -e
assert_eq 'seat selection requires top-level user evidence' '3' "$STATUS"
assert_eq 'missing selection evidence fails closed' 'selection-missing' "$(printf '%s' "$OUT" | jq -r '.reason')"
set +e
OUT=$(run_permit finalize --session "$SESSION" --lenses simplify 2>/dev/null)
STATUS=$?
set -e
assert_eq 'legacy pair shortcut also requires user evidence' '3' "$STATUS"
assert_eq 'legacy shortcut without selection fails closed' 'selection-missing' "$(printf '%s' "$OUT" | jq -r '.reason')"

SESSION="seat-legacy-reference-$$"
PROJECT_DIR="$HOME/.claude/projects/seat-test-legacy-reference"
MAIN="$PROJECT_DIR/$SESSION.jsonl"
SUBAGENTS="$PROJECT_DIR/$SESSION/subagents"
mkdir -p "$SUBAGENTS"
chmod 700 "$PROJECT_DIR" "$SUBAGENTS"
write_command legacy-reference-command
OUT=$(run_permit issue --session "$SESSION" --spec "$SPEC")
PERMIT_ID=$(printf '%s' "$OUT" | jq -r '.permit_id')
SNAPSHOT=$(printf '%s' "$OUT" | jq -r '.snapshot_path')
EXPIRES_AT=$(printf '%s' "$OUT" | jq -r '.expires_at')
write_selection '只選 simplify:opus,simplify:fable' legacy-reference-selection
OUT=$(run_permit finalize --session "$SESSION" --lenses simplify)
EMBEDDED_OPUS_PACKET=$(run_permit packet --session "$SESSION" --lens simplify --model opus)
EMBEDDED_FABLE_PACKET=$(run_permit packet --session "$SESSION" --lens simplify --model fable)
write_embedded_agent legacy-opus claude-opus-5 "$EMBEDDED_OPUS_PACKET"
write_embedded_agent legacy-fable claude-fable-5 "$EMBEDDED_FABLE_PACKET"
set +e
OUT=$(run_verify --pair simplify:legacy-opus:legacy-fable 2>/dev/null)
STATUS=$?
set -e
assert_eq 'new legacy shortcut still requires reference Read' '3' "$STATUS"
assert_eq 'legacy shortcut embedded packet fails Read' 'true' "$(printf '%s' "$OUT" | jq '.errors | any(contains("packet-read"))')"

SESSION="seat-pair-test-$$"
PROJECT_DIR="$HOME/.claude/projects/seat-test-pair"
MAIN="$PROJECT_DIR/$SESSION.jsonl"
SUBAGENTS="$PROJECT_DIR/$SESSION/subagents"
mkdir -p "$SUBAGENTS"
chmod 700 "$PROJECT_DIR" "$SUBAGENTS"
write_command pair-command
OUT=$(run_permit issue --session "$SESSION" --spec "$SPEC")
PERMIT_ID=$(printf '%s' "$OUT" | jq -r '.permit_id')
SNAPSHOT=$(printf '%s' "$OUT" | jq -r '.snapshot_path')
EXPIRES_AT=$(printf '%s' "$OUT" | jq -r '.expires_at')
write_recommendation 'simplify:opus,simplify:fable' pair-recommendation
write_selection '照推薦' pair-selection
set +e
OUT=$(run_permit finalize --session "$SESSION" --seats simplify:opus --recommendation-event pair-recommendation 2>/dev/null)
STATUS=$?
set -e
assert_eq '照推薦 cannot silently reduce recommended pair' '3' "$STATUS"
assert_eq 'recommendation mismatch is explicit' 'recommendation-selection-mismatch' "$(printf '%s' "$OUT" | jq -r '.reason')"
OUT=$(run_permit finalize --session "$SESSION" --seats simplify:opus,simplify:fable --recommendation-event pair-recommendation --follow-recommendation)
assert_eq 'selected pair preserves both seats' 'simplify:opus,simplify:fable' "$(printf '%s' "$OUT" | jq -r '.seats | join(",")')"
assert_eq 'finalized seat state carries no digest field' '0' "$(jq '[keys[] | select(test("sha|digest|checksum"; "i"))] | length' "$RUNTIME/$SESSION.json")"
CURRENT_LENS=simplify
OPUS_PACKET=$(run_permit packet --session "$SESSION" --lens simplify --model opus --reference)
FABLE_PACKET=$(run_permit packet --session "$SESSION" --lens simplify --model fable --reference)
EMBEDDED_OPUS_PACKET=$(run_permit packet --session "$SESSION" --lens simplify --model opus)
EMBEDDED_FABLE_PACKET=$(run_permit packet --session "$SESSION" --lens simplify --model fable)
write_embedded_agent embedded-opus claude-opus-5 "$EMBEDDED_OPUS_PACKET"
write_embedded_agent embedded-fable claude-fable-5 "$EMBEDDED_FABLE_PACKET"
set +e
OUT=$(run_verify --seat simplify:opus:embedded-opus --seat simplify:fable:embedded-fable 2>/dev/null)
STATUS=$?
set -e
assert_eq 'new selected seats require reference Read' '3' "$STATUS"
assert_eq 'embedded selected seats fail Read contract' 'true' "$(printf '%s' "$OUT" | jq '.errors | any(contains("packet-read"))')"
write_agent pair-opus claude-opus-5 "$OPUS_PACKET"
write_agent pair-fable claude-fable-5 "$FABLE_PACKET"
jq -c 'if .message.role == "user" and (.message.content | type) == "string" then .message.content += "\\nprompt divergence" else . end' "$SUBAGENTS/agent-pair-fable.jsonl" > "$TMP/pair-fable.jsonl"
mv "$TMP/pair-fable.jsonl" "$SUBAGENTS/agent-pair-fable.jsonl"
set +e
OUT=$(run_verify --seat simplify:opus:pair-opus --seat simplify:fable:pair-fable 2>/dev/null)
STATUS=$?
set -e
assert_eq 'seat-form pair checks prompt equality' '3' "$STATUS"
assert_eq 'seat-form pair prompt mismatch is explicit' 'true' "$(printf '%s' "$OUT" | jq '.errors | any(. == "pair-prompt-mismatch:simplify")')"
write_agent pair-fable claude-fable-5 "$FABLE_PACKET"
set +e
OUT=$(run_verify --pair simplify:pair-opus:pair-fable 2>/dev/null)
STATUS=$?
set -e
assert_eq 'pair requires selected Fable authorization consumption' '3' "$STATUS"
PAYLOAD=$(jq -nc --arg session "$SESSION" --arg transcript "$MAIN" --arg description "<review-spec-dual:v1 permit_id=$PERMIT_ID lens=simplify>" --arg prompt "$(printf '%s\nreview' "$FABLE_PACKET")" \
  '{session_id:$session,transcript_path:$transcript,tool_name:"Agent",tool_input:{subagent_type:"architecture-critic",model:"fable",description:$description,prompt:$prompt}}')
OUT=$(printf '%s' "$PAYLOAD" | REVIEW_SPEC_DUAL_RUNTIME_DIR="$RUNTIME" REVIEW_SPEC_DUAL_NOW="2026-09-09T03:03:00Z" "$PERMIT" consume)
assert_eq 'selected Fable seat consumes once' 'true' "$(printf '%s' "$OUT" | jq -r '.allowed')"
OUT=$(run_verify --pair simplify:pair-opus:pair-fable)
assert_eq 'selected pair verifies together' 'true' "$(printf '%s' "$OUT" | jq -r '.valid')"
assert_eq 'pair report has two seats' '2' "$(printf '%s' "$OUT" | jq '.seats | length')"
assert_eq 'pair report retains pair projection' '1' "$(printf '%s' "$OUT" | jq '.pairs | length')"
RECEIPT=$(printf '%s' "$OUT" | jq -r '.receipt_path')
OUT=$(run_permit close --session "$SESSION" --permit-id "$PERMIT_ID" --receipt "$RECEIPT")
assert_eq 'pair receipt closes permit' 'true' "$(printf '%s' "$OUT" | jq -r '.allowed')"

SESSION="seat-old-recommendation-$$"
PROJECT_DIR="$HOME/.claude/projects/seat-test-old-recommendation"
MAIN="$PROJECT_DIR/$SESSION.jsonl"
SUBAGENTS="$PROJECT_DIR/$SESSION/subagents"
mkdir -p "$SUBAGENTS"
chmod 700 "$PROJECT_DIR" "$SUBAGENTS"
write_command old-recommendation-command
OUT=$(run_permit issue --session "$SESSION" --spec "$SPEC")
PERMIT_ID=$(printf '%s' "$OUT" | jq -r '.permit_id')
jq -nc --arg session "$SESSION" --arg permit "$PERMIT_ID" --arg zeros "$(printf '%064d' 0)" \
  '{type:"assistant",sessionId:$session,uuid:"old-recommendation",timestamp:"2026-09-09T03:00:30Z",message:{role:"assistant",content:("<review-spec-recommendation:v1 permit_id="+$permit+" spec_sha256="+$zeros+" seats=simplify:opus>")}}' >> "$MAIN"
write_selection '照推薦' old-recommendation-selection
set +e
OUT=$(run_permit finalize --session "$SESSION" --seats simplify:opus --recommendation-event old-recommendation --follow-recommendation 2>/dev/null)
STATUS=$?
set -e
assert_eq 'recommendation marker with sha field is not a current marker' '3' "$STATUS"
assert_eq 'old-form recommendation falls to the generic missing-recommendation deny' 'recommendation-required' "$(printf '%s' "$OUT" | jq -r '.reason')"

printf '%s\n' '----'
printf 'PASS=%s FAIL=%s\n' "$PASSES" "$FAILURES"
[ "$FAILURES" -eq 0 ]
