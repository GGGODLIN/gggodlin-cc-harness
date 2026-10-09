#!/bin/bash
# T2-routing-gate 回歸測資（routed-agent-enforce trial, 2026-07-26）
#
# 兩組斷言：
#   sentinel 關閉 → legacy token、routed-mech opt-in、review-spec dual 與 workflow E2 行為（case 1-4, 18, 20, 25, 32-33, 35, 42-43）
#   sentinel 開啟 → routed-*、Fable 授權、一次性 Tier 3 permit 與 workflow E2 行為（case 5-24, 26-31, 34, 36-41）
#
# case 1 與 case 7 是同一組輸入、預期相反 —— 那一對就是整套 enforce 的 pass/fail 判準。
# review-implement cases exercise transcript authorization before the existing Fable branches.
#
# 用法: bash hooks/T2-routing-gate.test.sh
# 真實 sentinel / audit / trace 不受影響（全部走 env override 指向 tmp）

set -u

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
HOOK=${T2_ROUTING_GATE_HOOK:-$SCRIPT_DIR/T2-routing-gate.sh}
TMP=$(mktemp -d)
MALFORMED_ALLOW_HOOK="$TMP/malformed-allow-hook.sh"
MALFORMED_MECH_HOOK="$TMP/malformed-mech-hook.sh"
SENTINEL="$TMP/routed-enforce.on"
AUDIT="$TMP/audit.jsonl"
TRACE="$TMP/trace.log"
AGENT_DIR="$TMP/agents"
WF_TRANSCRIPT="$TMP/workflows/wf_test/transcript.jsonl"
TEST_SESSION="t2-test-$$"
VENDOR_SESSION="t2-vendor-test-$$"
REVIEW_SESSION="t2-review-test-$$"
REVIEW_YAGNI_SESSION="t2-review-yagni-$$"
REVIEW_OPUS_SESSION="t2-review-opus-$$"
REVIEW_NL_SESSION="t2-review-natural-language-$$"
REVIEW_ADVERB_SESSION="t2-review-adverb-$$"
REVIEW_ADVERB_BARE_SESSION="t2-review-adverb-bare-$$"
REVIEW_ADVERB_TRAILING_SESSION="t2-review-adverb-trailing-$$"
REVIEW_PAIR_SESSION="t2-review-pair-$$"
REVIEW_RECOMMENDED_SESSION="t2-review-recommended-$$"
REVIEW_NO_RECOMMENDATION_SESSION="t2-review-no-recommendation-$$"
REVIEW_CROSS_STAGE_RECOMMENDATION_SESSION="t2-review-cross-stage-recommendation-$$"
REVIEW_SIDECHAIN_RECOMMENDATION_SESSION="t2-review-sidechain-recommendation-$$"
REVIEW_RECOMMENDED_ALIAS_SESSION="t2-review-recommended-alias-$$"
REVIEW_SIDECHAIN_RESULT_SESSION="t2-review-sidechain-result-$$"
REVIEW_ALL_SESSION="t2-review-all-$$"
REVIEW_DUP_SESSION="t2-review-duplicate-$$"
REVIEW_REPEAT_SESSION="t2-review-repeat-$$"
REVIEW_RERUN_SESSION="t2-review-rerun-$$"
REVIEW_CURRENT_SESSION="t2-review-current-$$"
REVIEW_STALE_SESSION="t2-review-stale-$$"
REVIEW_COMPANION_BOUNDARY_SESSION="t2-review-companion-boundary-$$"
REVIEW_SYSTEM_FILTER_SESSION="t2-review-system-filter-$$"
REVIEW_LOCAL_COMMAND_SESSION="t2-review-local-command-$$"
REVIEW_COMMAND_MIXED_SESSION="t2-review-command-mixed-$$"
REVIEW_ERROR_SESSION="t2-review-error-$$"
REVIEW_SKIP_SESSION="t2-review-skip-$$"
REVIEW_MISSING_SESSION="t2-review-missing-$$"
REVIEW_OTHER_SESSION="t2-review-other-$$"
REVIEW_ALIAS_B_SESSION="t2-review-alias-b-$$"
REVIEW_ALIAS_A_SESSION="t2-review-alias-a-$$"
REVIEW_ALIAS_NO_MENU_SESSION="t2-review-alias-no-menu-$$"
REVIEW_ALIAS_TAMPERED_SESSION="t2-review-alias-tampered-$$"
REVIEW_ALIAS_DUPLICATE_SESSION="t2-review-alias-duplicate-$$"
REVIEW_ALIAS_SKIP_SESSION="t2-review-alias-skip-$$"
REVIEW_ALIAS_SIDECHAIN_SESSION="t2-review-alias-sidechain-$$"
REVIEW_ALIAS_UNKNOWN_SESSION="t2-review-alias-unknown-$$"
PROJECT_FIXTURE_DIR="$HOME/.claude/projects/t2-routing-test-$$"
PLAIN_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$TEST_SESSION.jsonl"
VENDOR_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$VENDOR_SESSION.jsonl"
REVIEW_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_SESSION.jsonl"
REVIEW_YAGNI_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_YAGNI_SESSION.jsonl"
REVIEW_OPUS_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_OPUS_SESSION.jsonl"
REVIEW_NL_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_NL_SESSION.jsonl"
REVIEW_ADVERB_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ADVERB_SESSION.jsonl"
REVIEW_ADVERB_BARE_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ADVERB_BARE_SESSION.jsonl"
REVIEW_ADVERB_TRAILING_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ADVERB_TRAILING_SESSION.jsonl"
REVIEW_PAIR_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_PAIR_SESSION.jsonl"
REVIEW_RECOMMENDED_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_RECOMMENDED_SESSION.jsonl"
REVIEW_NO_RECOMMENDATION_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_NO_RECOMMENDATION_SESSION.jsonl"
REVIEW_CROSS_STAGE_RECOMMENDATION_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_CROSS_STAGE_RECOMMENDATION_SESSION.jsonl"
REVIEW_SIDECHAIN_RECOMMENDATION_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_SIDECHAIN_RECOMMENDATION_SESSION.jsonl"
REVIEW_RECOMMENDED_ALIAS_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_RECOMMENDED_ALIAS_SESSION.jsonl"
REVIEW_SIDECHAIN_RESULT_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_SIDECHAIN_RESULT_SESSION.jsonl"
REVIEW_ALL_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ALL_SESSION.jsonl"
REVIEW_DUP_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_DUP_SESSION.jsonl"
REVIEW_REPEAT_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_REPEAT_SESSION.jsonl"
REVIEW_RERUN_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_RERUN_SESSION.jsonl"
REVIEW_CURRENT_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_CURRENT_SESSION.jsonl"
REVIEW_STALE_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_STALE_SESSION.jsonl"
REVIEW_COMPANION_BOUNDARY_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_COMPANION_BOUNDARY_SESSION.jsonl"
REVIEW_SYSTEM_FILTER_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_SYSTEM_FILTER_SESSION.jsonl"
REVIEW_LOCAL_COMMAND_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_LOCAL_COMMAND_SESSION.jsonl"
REVIEW_COMMAND_MIXED_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_COMMAND_MIXED_SESSION.jsonl"
REVIEW_ERROR_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ERROR_SESSION.jsonl"
REVIEW_SKIP_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_SKIP_SESSION.jsonl"
REVIEW_MISSING_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_MISSING_SESSION.jsonl"
REVIEW_OTHER_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_OTHER_SESSION.jsonl"
REVIEW_ALIAS_B_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ALIAS_B_SESSION.jsonl"
REVIEW_ALIAS_A_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ALIAS_A_SESSION.jsonl"
REVIEW_ALIAS_NO_MENU_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ALIAS_NO_MENU_SESSION.jsonl"
REVIEW_ALIAS_TAMPERED_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ALIAS_TAMPERED_SESSION.jsonl"
REVIEW_ALIAS_DUPLICATE_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ALIAS_DUPLICATE_SESSION.jsonl"
REVIEW_ALIAS_SKIP_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ALIAS_SKIP_SESSION.jsonl"
REVIEW_ALIAS_SIDECHAIN_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ALIAS_SIDECHAIN_SESSION.jsonl"
REVIEW_ALIAS_UNKNOWN_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$REVIEW_ALIAS_UNKNOWN_SESSION.jsonl"
DUAL_RUNTIME="$TMP/review-spec-dual"
DUAL_HELPER=${REVIEW_SPEC_DUAL_PERMIT_HELPER:-$SCRIPT_DIR/review-spec-dual-permit.py}
DUAL_SPENT_DIR="$HOME/.claude/logs/review-spec-dual-issued/$TEST_SESSION"
VENDOR_SPENT_DIR="$HOME/.claude/logs/review-spec-dual-issued/$VENDOR_SESSION"
SPEC="$TMP/design.md"
PASSES=0
FAILURES=0
TEST_OPUS_MODEL=""
TEST_FABLE_MODEL=""

mkdir -p "$AGENT_DIR" "$(dirname "$WF_TRANSCRIPT")" "$DUAL_RUNTIME" "$PROJECT_FIXTURE_DIR"
printf '%s\n' '#!/bin/bash' 'printf '\''%s\n'\'' '\''{"action":"allow","reason":"oracle_allow"}'\'' >> "$T2_AUDIT_LOG"' 'printf '\''%s\n'\'' '\''not-json'\''' > "$MALFORMED_ALLOW_HOOK"
chmod 700 "$MALFORMED_ALLOW_HOOK"
printf '%s\n' '#!/bin/bash' 'printf '\''%s\n'\'' '\''{"action":"pass-e1","reason":"mech_opt_in_ok","token":"<mech-ok>"}'\'' >> "$T2_AUDIT_LOG"' 'printf '\''%s\n'\'' '\''not-json'\''' > "$MALFORMED_MECH_HOOK"
chmod 700 "$MALFORMED_MECH_HOOK"
REVIEW_LETTER_MENU=$(printf '%s\n' 'Choose review axes:' 'a. all' 'b. scope' 'c. yagni' 'd. skip')

write_review_alias_transcript() {
  local path=$1
  local session=$2
  local selection=$3
  local mode=$4
  jq -nc \
    --arg session "$session" \
    '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-alias",name:"Skill",input:{skill:"review-implement"}}]}}' > "$path"
  jq -nc \
    --arg session "$session" \
    '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-alias",is_error:false,content:"Launching skill: review-implement"}]}}' >> "$path"
  case "$mode" in
    exact)
      jq -nc --arg session "$session" --arg text "$REVIEW_LETTER_MENU" \
        '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"text",text:$text}]}}' >> "$path"
      ;;
    tampered)
      jq -nc --arg session "$session" --arg text $'Choose review axes:\na. scope\nb. all\nc. yagni\nd. skip' \
        '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"text",text:$text}]}}' >> "$path"
      ;;
    duplicate)
      jq -nc --arg session "$session" --arg text "$REVIEW_LETTER_MENU"$'\n\n'"$REVIEW_LETTER_MENU" \
        '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"text",text:$text}]}}' >> "$path"
      ;;
    sidechain)
      jq -nc --arg session "$session" --arg text "$REVIEW_LETTER_MENU" \
        '{type:"assistant",sessionId:$session,isSidechain:true,message:{role:"assistant",content:[{type:"text",text:$text}]}}' >> "$path"
      jq -nc --arg session "$session" --arg text "$REVIEW_LETTER_MENU" \
        '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"unrelated",is_error:false,content:$text}]}}' >> "$path"
      ;;
    none)
      ;;
  esac
  jq -nc --arg session "$session" --arg selection "$selection" \
    '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:$selection},origin:{kind:"human"},promptSource:"typed"}' >> "$path"
  chmod 600 "$path"
}

write_review_alias_transcript "$REVIEW_ALIAS_B_TRANSCRIPT" "$REVIEW_ALIAS_B_SESSION" b exact
write_review_alias_transcript "$REVIEW_ALIAS_A_TRANSCRIPT" "$REVIEW_ALIAS_A_SESSION" a exact
write_review_alias_transcript "$REVIEW_ALIAS_NO_MENU_TRANSCRIPT" "$REVIEW_ALIAS_NO_MENU_SESSION" b none
write_review_alias_transcript "$REVIEW_ALIAS_TAMPERED_TRANSCRIPT" "$REVIEW_ALIAS_TAMPERED_SESSION" b tampered
write_review_alias_transcript "$REVIEW_ALIAS_DUPLICATE_TRANSCRIPT" "$REVIEW_ALIAS_DUPLICATE_SESSION" b duplicate
write_review_alias_transcript "$REVIEW_ALIAS_SKIP_TRANSCRIPT" "$REVIEW_ALIAS_SKIP_SESSION" d exact
write_review_alias_transcript "$REVIEW_ALIAS_SIDECHAIN_TRANSCRIPT" "$REVIEW_ALIAS_SIDECHAIN_SESSION" b sidechain
write_review_alias_transcript "$REVIEW_ALIAS_UNKNOWN_TRANSCRIPT" "$REVIEW_ALIAS_UNKNOWN_SESSION" e exact

: > "$WF_TRANSCRIPT"
printf '%s\n' 'trusted Tier 3 design' > "$SPEC"
jq -nc \
  --arg session "$TEST_SESSION" \
  --arg uuid "review-spec-command-test" \
  --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg cwd "$TMP" \
  --arg spec "$SPEC" \
  '{type:"user",userType:"external",sessionId:$session,uuid:$uuid,timestamp:$timestamp,cwd:$cwd,message:{role:"user",content:("<command-name>/review-spec</command-name>\n<command-message>review-spec</command-message>\n<command-args>3 "+$spec+"</command-args>")}}' > "$PLAIN_TRANSCRIPT"
jq -nc \
  --arg session "$VENDOR_SESSION" \
  --arg uuid "review-spec-vendor-command-test" \
  --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg cwd "$TMP" \
  --arg spec "$SPEC" \
  '{type:"user",userType:"external",sessionId:$session,uuid:$uuid,timestamp:$timestamp,cwd:$cwd,message:{role:"user",content:("<command-name>/review-spec</command-name>\n<command-message>review-spec</command-message>\n<command-args>3 "+$spec+"</command-args>")}}' > "$VENDOR_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage",content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"scope"}}' >> "$REVIEW_TRANSCRIPT"
chmod 600 "$REVIEW_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_YAGNI_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-yagni",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_YAGNI_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_YAGNI_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-yagni",is_error:false,content:"Launching skill: review-implement"}]}}' >> "$REVIEW_YAGNI_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_YAGNI_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"yagni"}}' >> "$REVIEW_YAGNI_TRANSCRIPT"
chmod 600 "$REVIEW_YAGNI_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_OPUS_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-opus",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_OPUS_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_OPUS_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-opus",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_OPUS_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_OPUS_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"opus all"}}' >> "$REVIEW_OPUS_TRANSCRIPT"
chmod 600 "$REVIEW_OPUS_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_NL_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-natural-language",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_NL_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_NL_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-natural-language",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_NL_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_NL_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"用 opus 審 scope"}}' >> "$REVIEW_NL_TRANSCRIPT"
chmod 600 "$REVIEW_NL_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ADVERB_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-adverb",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_ADVERB_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ADVERB_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-adverb",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_ADVERB_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ADVERB_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"all 都用 opus"}}' >> "$REVIEW_ADVERB_TRANSCRIPT"
chmod 600 "$REVIEW_ADVERB_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ADVERB_BARE_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-adverb-bare",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_ADVERB_BARE_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ADVERB_BARE_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-adverb-bare",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_ADVERB_BARE_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ADVERB_BARE_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"都用 opus"}}' >> "$REVIEW_ADVERB_BARE_TRANSCRIPT"
chmod 600 "$REVIEW_ADVERB_BARE_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ADVERB_TRAILING_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-adverb-trailing",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_ADVERB_TRAILING_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ADVERB_TRAILING_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-adverb-trailing",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_ADVERB_TRAILING_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ADVERB_TRAILING_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"all,但都用opus行嗎"}}' >> "$REVIEW_ADVERB_TRAILING_TRANSCRIPT"
chmod 600 "$REVIEW_ADVERB_TRAILING_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_PAIR_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-pair",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_PAIR_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_PAIR_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-pair",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_PAIR_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_PAIR_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"scope 用 opus 和 fable"}}' >> "$REVIEW_PAIR_TRANSCRIPT"
chmod 600 "$REVIEW_PAIR_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RECOMMENDED_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-recommended",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_RECOMMENDED_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RECOMMENDED_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-recommended",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_RECOMMENDED_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RECOMMENDED_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"text",text:"Recommended seats: opus/scope"}]}}' >> "$REVIEW_RECOMMENDED_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RECOMMENDED_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"照推薦"}}' >> "$REVIEW_RECOMMENDED_TRANSCRIPT"
chmod 600 "$REVIEW_RECOMMENDED_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_NO_RECOMMENDATION_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-no-recommendation",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_NO_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_NO_RECOMMENDATION_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-no-recommendation",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_NO_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_NO_RECOMMENDATION_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"照推薦"}}' >> "$REVIEW_NO_RECOMMENDATION_TRANSCRIPT"
chmod 600 "$REVIEW_NO_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_CROSS_STAGE_RECOMMENDATION_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"cross-old-stage",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_CROSS_STAGE_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_CROSS_STAGE_RECOMMENDATION_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"cross-old-stage",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_CROSS_STAGE_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_CROSS_STAGE_RECOMMENDATION_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"text",text:"Recommended seats: opus/scope"}]}}' >> "$REVIEW_CROSS_STAGE_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_CROSS_STAGE_RECOMMENDATION_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"cross-new-stage",name:"Skill",input:{skill:"review-implement"}}]}}' >> "$REVIEW_CROSS_STAGE_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_CROSS_STAGE_RECOMMENDATION_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"cross-new-stage",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_CROSS_STAGE_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_CROSS_STAGE_RECOMMENDATION_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"照推薦"}}' >> "$REVIEW_CROSS_STAGE_RECOMMENDATION_TRANSCRIPT"
chmod 600 "$REVIEW_CROSS_STAGE_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SIDECHAIN_RECOMMENDATION_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-sidechain-recommendation",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_SIDECHAIN_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SIDECHAIN_RECOMMENDATION_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-sidechain-recommendation",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_SIDECHAIN_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SIDECHAIN_RECOMMENDATION_SESSION" \
  '{type:"assistant",sessionId:$session,isSidechain:true,message:{role:"assistant",content:[{type:"text",text:"Recommended seats: opus/scope"}]}}' >> "$REVIEW_SIDECHAIN_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SIDECHAIN_RECOMMENDATION_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"照推薦"}}' >> "$REVIEW_SIDECHAIN_RECOMMENDATION_TRANSCRIPT"
chmod 600 "$REVIEW_SIDECHAIN_RECOMMENDATION_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RECOMMENDED_ALIAS_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-recommended-alias",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_RECOMMENDED_ALIAS_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RECOMMENDED_ALIAS_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-recommended-alias",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_RECOMMENDED_ALIAS_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RECOMMENDED_ALIAS_SESSION" --arg text "$REVIEW_LETTER_MENU" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"text",text:("Recommended seats: opus/scope\n" + $text)}]}}' >> "$REVIEW_RECOMMENDED_ALIAS_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RECOMMENDED_ALIAS_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"b"},origin:{kind:"human"},promptSource:"typed"}' >> "$REVIEW_RECOMMENDED_ALIAS_TRANSCRIPT"
chmod 600 "$REVIEW_RECOMMENDED_ALIAS_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SIDECHAIN_RESULT_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-sidechain-result",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_SIDECHAIN_RESULT_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SIDECHAIN_RESULT_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,isSidechain:true,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-sidechain-result",is_error:false,content:"Launching skill: review-implement"}]},toolUseResult:{success:true,commandName:"review-implement"}}' >> "$REVIEW_SIDECHAIN_RESULT_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SIDECHAIN_RESULT_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"scope"}}' >> "$REVIEW_SIDECHAIN_RESULT_TRANSCRIPT"
chmod 600 "$REVIEW_SIDECHAIN_RESULT_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ALL_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-all",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_ALL_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ALL_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-all",is_error:false,content:"Launching skill: review-implement"}]}}' >> "$REVIEW_ALL_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ALL_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"(Re-invocation of /review-implement — the skill instructions were previously loaded; the arguments or dynamic output below are new.)"},isMeta:true,turnCompanion:true,sourceToolUseID:"review-stage-all"}' >> "$REVIEW_ALL_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ALL_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"text",text:"Base directory for this skill: ~/.claude/skills/review-implement"}]},isMeta:true,turnCompanion:true,sourceToolUseID:"review-stage-all"}' >> "$REVIEW_ALL_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ALL_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"all"},origin:{kind:"human"},promptSource:"typed"}' >> "$REVIEW_ALL_TRANSCRIPT"
chmod 600 "$REVIEW_ALL_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_LOCAL_COMMAND_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-local-command",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_LOCAL_COMMAND_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-local-command",is_error:false,content:"Launching skill: review-implement"}]}}' >> "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_LOCAL_COMMAND_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"all"},origin:{kind:"human"},promptSource:"typed"}' >> "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_LOCAL_COMMAND_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"<bash-input> ~/.claude/hooks/agent-contract-gate-permit.sh issue</bash-input>"}}' >> "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_LOCAL_COMMAND_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"<bash-stdout>permit issued for staged tree fixture\nvalid for 900 seconds, single use, consumed by the gate on the next commit\nstaged paths:\n  hooks/T2-routing-gate.sh\n  hooks/T2-routing-gate.test.sh</bash-stdout><bash-stderr></bash-stderr>"}}' >> "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_LOCAL_COMMAND_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"<local-command-caveat>Caveat: The messages below were generated by the user while running local commands.</local-command-caveat>"},isMeta:true}' >> "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_LOCAL_COMMAND_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"<command-name>/compact</command-name>\n            <command-message>compact</command-message>\n            <command-args></command-args>"}}' >> "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_LOCAL_COMMAND_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"<command-message>resume-session</command-message>\n<command-name>/resume-session</command-name>"}}' >> "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
chmod 600 "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_COMMAND_MIXED_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-command-mixed",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_COMMAND_MIXED_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_COMMAND_MIXED_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-command-mixed",is_error:false,content:"Launching skill: review-implement"}]}}' >> "$REVIEW_COMMAND_MIXED_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_COMMAND_MIXED_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"all"},origin:{kind:"human"},promptSource:"typed"}' >> "$REVIEW_COMMAND_MIXED_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_COMMAND_MIXED_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"scope\n<command-name>/compact</command-name>"},origin:{kind:"human"},promptSource:"typed"}' >> "$REVIEW_COMMAND_MIXED_TRANSCRIPT"
chmod 600 "$REVIEW_COMMAND_MIXED_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_COMPANION_BOUNDARY_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-companion-boundary",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_COMPANION_BOUNDARY_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_COMPANION_BOUNDARY_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-companion-boundary",is_error:false,content:"Launching skill: review-implement"}]}}' >> "$REVIEW_COMPANION_BOUNDARY_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_COMPANION_BOUNDARY_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"(Re-invocation of /review-implement — the skill instructions were previously loaded; the arguments or dynamic output below are new.)"},origin:{kind:"human"},promptSource:"typed"}' >> "$REVIEW_COMPANION_BOUNDARY_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_COMPANION_BOUNDARY_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"(Re-invocation of /review-implement — the skill instructions were previously loaded; the arguments or dynamic output below are new.)"},isMeta:false,turnCompanion:false,origin:{kind:"human"},promptSource:"typed"}' >> "$REVIEW_COMPANION_BOUNDARY_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_COMPANION_BOUNDARY_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"all"},origin:{kind:"human"},promptSource:"typed"}' >> "$REVIEW_COMPANION_BOUNDARY_TRANSCRIPT"
chmod 600 "$REVIEW_COMPANION_BOUNDARY_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SYSTEM_FILTER_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-system-filter",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_SYSTEM_FILTER_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SYSTEM_FILTER_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-system-filter",is_error:false,content:"Launching skill: review-implement"}]}}' >> "$REVIEW_SYSTEM_FILTER_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SYSTEM_FILTER_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"all"},promptSource:"system"}' >> "$REVIEW_SYSTEM_FILTER_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SYSTEM_FILTER_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"all"},origin:{kind:"task-notification"}}' >> "$REVIEW_SYSTEM_FILTER_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SYSTEM_FILTER_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"unrelated-tool",is_error:false,content:"all"}]}}' >> "$REVIEW_SYSTEM_FILTER_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SYSTEM_FILTER_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"all"},origin:{kind:"human"},promptSource:"typed"}' >> "$REVIEW_SYSTEM_FILTER_TRANSCRIPT"
chmod 600 "$REVIEW_SYSTEM_FILTER_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_DUP_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-duplicate",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_DUP_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_DUP_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-duplicate",is_error:false,content:"Launching skill: review-implement"}]}}' >> "$REVIEW_DUP_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_DUP_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-duplicate",name:"Skill",input:{skill:"review-implement"}}]}}' >> "$REVIEW_DUP_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_DUP_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"scope"}}' >> "$REVIEW_DUP_TRANSCRIPT"
chmod 600 "$REVIEW_DUP_TRANSCRIPT"
jq -c --arg session "$REVIEW_REPEAT_SESSION" \
  'if .sessionId? != null then .sessionId = $session else . end | if .session_id? != null then .session_id = $session else . end' \
  "$REVIEW_TRANSCRIPT" > "$REVIEW_REPEAT_TRANSCRIPT"
chmod 600 "$REVIEW_REPEAT_TRANSCRIPT"
jq -c --arg session "$REVIEW_RERUN_SESSION" \
  'if .sessionId? != null then .sessionId = $session else . end | if .session_id? != null then .session_id = $session else . end' \
  "$REVIEW_TRANSCRIPT" > "$REVIEW_RERUN_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RERUN_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"prior-failed-scope",name:"Agent",input:{subagent_type:"routed-judge",model:"fable",description:"<fable-ok> <review-implement-fable:v1 axis=scope>",prompt:"failed scope reviewer"}}]}}' >> "$REVIEW_RERUN_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RERUN_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"prior-failed-scope",is_error:true,content:"review_implement_axis_stale"}]}}' >> "$REVIEW_RERUN_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RERUN_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-rerun",name:"Skill",input:{skill:"review-implement"}}]}}' >> "$REVIEW_RERUN_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RERUN_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-rerun",is_error:false,content:"Launching skill: review-implement"}]}}' >> "$REVIEW_RERUN_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_RERUN_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"scope"}}' >> "$REVIEW_RERUN_TRANSCRIPT"
chmod 600 "$REVIEW_RERUN_TRANSCRIPT"
jq -c --arg session "$REVIEW_CURRENT_SESSION" \
  'if .sessionId? != null then .sessionId = $session else . end | if .session_id? != null then .session_id = $session else . end' \
  "$REVIEW_TRANSCRIPT" > "$REVIEW_CURRENT_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_CURRENT_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"tu_test",name:"Agent",input:{subagent_type:"routed-judge",model:"fable",description:"<fable-ok> <review-implement-fable:v1 axis=scope>",prompt:"current scope reviewer"}}]}}' >> "$REVIEW_CURRENT_TRANSCRIPT"
chmod 600 "$REVIEW_CURRENT_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_STALE_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-stale",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_STALE_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_STALE_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-stale",is_error:false,content:"Launching skill: review-implement"}]}}' >> "$REVIEW_STALE_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_STALE_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"scope"}}' >> "$REVIEW_STALE_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_STALE_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"proceed"}}' >> "$REVIEW_STALE_TRANSCRIPT"
chmod 600 "$REVIEW_STALE_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ERROR_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-error",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_ERROR_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ERROR_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-error",is_error:true,content:"review-implement failed"}]}}' >> "$REVIEW_ERROR_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ERROR_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"scope"}}' >> "$REVIEW_ERROR_TRANSCRIPT"
chmod 600 "$REVIEW_ERROR_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SKIP_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-skip",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_SKIP_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SKIP_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"review-stage-skip",is_error:false,content:"Launching skill: review-implement"}]}}' >> "$REVIEW_SKIP_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_SKIP_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"skip"}}' >> "$REVIEW_SKIP_TRANSCRIPT"
chmod 600 "$REVIEW_SKIP_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_MISSING_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"review-stage-missing",name:"Skill",input:{skill:"review-implement"}}]}}' > "$REVIEW_MISSING_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_MISSING_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"scope"}}' >> "$REVIEW_MISSING_TRANSCRIPT"
chmod 600 "$REVIEW_MISSING_TRANSCRIPT"

for a in routed-impl routed-mech routed-judge routed-secure code-reviewer deep-explore architecture-critic; do
  printf -- '---\nname: %s\n---\n' "$a" > "$AGENT_DIR/$a.md"
done

cleanup() {
  rm -f "$AGENT_DIR"/*.md "$AUDIT" "$AUDIT".lock "$TRACE" "$SENTINEL" "$MALFORMED_ALLOW_HOOK" "$MALFORMED_MECH_HOOK"
  rm -f "$WF_TRANSCRIPT" "$PLAIN_TRANSCRIPT" "$VENDOR_TRANSCRIPT" "$REVIEW_TRANSCRIPT" "$REVIEW_YAGNI_TRANSCRIPT" "$REVIEW_OPUS_TRANSCRIPT" "$REVIEW_NL_TRANSCRIPT" "$REVIEW_ADVERB_TRANSCRIPT" "$REVIEW_ADVERB_BARE_TRANSCRIPT" "$REVIEW_ADVERB_TRAILING_TRANSCRIPT" "$REVIEW_PAIR_TRANSCRIPT" "$REVIEW_RECOMMENDED_TRANSCRIPT" "$REVIEW_NO_RECOMMENDATION_TRANSCRIPT" "$REVIEW_CROSS_STAGE_RECOMMENDATION_TRANSCRIPT" "$REVIEW_SIDECHAIN_RECOMMENDATION_TRANSCRIPT" "$REVIEW_RECOMMENDED_ALIAS_TRANSCRIPT" "$REVIEW_SIDECHAIN_RESULT_TRANSCRIPT" "$REVIEW_ALL_TRANSCRIPT" "$REVIEW_LOCAL_COMMAND_TRANSCRIPT" "$REVIEW_COMPANION_BOUNDARY_TRANSCRIPT" "$REVIEW_SYSTEM_FILTER_TRANSCRIPT" "$REVIEW_DUP_TRANSCRIPT" "$REVIEW_REPEAT_TRANSCRIPT" "$REVIEW_RERUN_TRANSCRIPT" "$REVIEW_CURRENT_TRANSCRIPT" "$REVIEW_STALE_TRANSCRIPT" "$REVIEW_ERROR_TRANSCRIPT" "$REVIEW_SKIP_TRANSCRIPT" "$REVIEW_MISSING_TRANSCRIPT" "$REVIEW_OTHER_TRANSCRIPT" "$REVIEW_ALIAS_B_TRANSCRIPT" "$REVIEW_ALIAS_A_TRANSCRIPT" "$REVIEW_ALIAS_NO_MENU_TRANSCRIPT" "$REVIEW_ALIAS_TAMPERED_TRANSCRIPT" "$REVIEW_ALIAS_DUPLICATE_TRANSCRIPT" "$REVIEW_ALIAS_SKIP_TRANSCRIPT" "$REVIEW_ALIAS_SIDECHAIN_TRANSCRIPT" "$REVIEW_ALIAS_UNKNOWN_TRANSCRIPT" "$SPEC"
  rm -f "$DUAL_RUNTIME"/* "$DUAL_SPENT_DIR"/* "$VENDOR_SPENT_DIR"/* "$PROJECT_FIXTURE_DIR/t2-acc-$$"-*.jsonl 2>/dev/null
  for acc_spent in "$HOME/.claude/logs/review-spec-dual-issued/t2-acc-$$"-*; do
    rm -f "$acc_spent"/* 2>/dev/null
    rmdir "$acc_spent" 2>/dev/null
  done
  rmdir "$DUAL_SPENT_DIR" "$VENDOR_SPENT_DIR" "$PROJECT_FIXTURE_DIR" "$DUAL_RUNTIME" "$AGENT_DIR" "$(dirname "$WF_TRANSCRIPT")" "$TMP/workflows" 2>/dev/null
  rmdir "$TMP" 2>/dev/null
}
trap cleanup EXIT

pass() { PASSES=$((PASSES + 1)); printf '  \033[32mPASS\033[0m  %s\n' "$1"; }
fail() {
  FAILURES=$((FAILURES + 1))
  printf '  \033[31mFAIL\033[0m  %s\n' "$1"
  printf '        expected: %s\n        actual:   %s\n' "$2" "$3"
}

# payload <subagent_type> <prompt> <desc> <model> <transcript> [omit_st]
payload_for() {
  local session=$1 st=$2 p=$3 d=$4 m=$5 t=$6 omit=${7:-no}
  jq -nc --arg st "$st" --arg p "$p" --arg d "$d" --arg m "$m" --arg t "$t" --arg omit "$omit" --arg session "$session" '
    {
      tool_name: "Agent",
      session_id: $session,
      tool_use_id: "tu_test",
      transcript_path: $t,
      tool_input: (
        {prompt: $p, description: $d}
        + (if $omit == "yes" then {} else {subagent_type: $st} end)
        + (if $m == "" then {} else {model: $m} end)
      )
    }'
}

payload() {
  payload_for "$TEST_SESSION" "$@"
}

parse_hook_output() {
  local output=$1
  HOOK_OUTPUT_VALID=1
  HOOK_OUTPUT_DECISION=allow
  HOOK_OUTPUT_REASON=

  if [ -z "$output" ]; then
    return 0
  fi

  if ! printf '%s' "$output" | jq -e -s '
    length == 1 and
    (.[0] |
      type == "object" and
      (keys | sort) == ["hookSpecificOutput"] and
      (.hookSpecificOutput | type == "object") and
      ((.hookSpecificOutput | keys | sort) == ["hookEventName","permissionDecision","permissionDecisionReason"]) and
      .hookSpecificOutput.hookEventName == "PreToolUse" and
      .hookSpecificOutput.permissionDecision == "deny" and
      (.hookSpecificOutput.permissionDecisionReason | type) == "string" and
      (.hookSpecificOutput.permissionDecisionReason | length > 0)
    )
  ' >/dev/null 2>&1; then
    HOOK_OUTPUT_VALID=0
    HOOK_OUTPUT_DECISION=invalid
    return 0
  fi

  HOOK_OUTPUT_DECISION=$(printf '%s' "$output" | jq -r '.hookSpecificOutput.permissionDecision')
  HOOK_OUTPUT_REASON=$(printf '%s' "$output" | jq -r '.hookSpecificOutput.permissionDecisionReason')
}

# check <label> <enforce 0|1> <fable_main 0|1> <expect_action> <expect_reason_substr> <payload...>
check() {
  local label=$1 enforce=$2 fable=$3 want_action=$4 want_reason=$5
  shift 5

  if [ "$enforce" = "1" ]; then : > "$SENTINEL"; else rm -f "$SENTINEL"; fi
  : > "$AUDIT"

  local out env_fable=""
  [ "$fable" = "1" ] && env_fable="1"

  out=$(payload "$@" | env \
    T2_ROUTED_SENTINEL="$SENTINEL" \
    T2_FORK_GATE_OFF="${T2_FORK_GATE_OFF:-$TMP/nonexistent-fork-gate.off}" \
    T2_AUDIT_LOG="$AUDIT" \
    T2_TRACE_LOG="$TRACE" \
    T2_AGENT_DIR="$AGENT_DIR" \
    CC_FABLE_MAIN="$env_fable" \
    CC_VENDOR="${TEST_VENDOR:-}" \
    ANTHROPIC_DEFAULT_OPUS_MODEL="$TEST_OPUS_MODEL" \
    ANTHROPIC_DEFAULT_FABLE_MODEL="$TEST_FABLE_MODEL" \
    T2_MODEL_OPTIONS_JSON="${TEST_MODEL_OPTIONS_JSON:-/nonexistent-model-options.json}" \
    REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" \
    REVIEW_SPEC_DUAL_PERMIT_HELPER="$DUAL_HELPER" \
    "$HOOK" 2>/dev/null)

  parse_hook_output "$out"
  local got_decision=$HOOK_OUTPUT_DECISION
  local got_action got_reason output_valid=$HOOK_OUTPUT_VALID output_reason=$HOOK_OUTPUT_REASON
  got_action=$(jq -r '.action // "NONE"' "$AUDIT" 2>/dev/null | tail -1)
  got_reason=$(jq -r '.reason // ""' "$AUDIT" 2>/dev/null | tail -1)

  local want_decision="allow"
  [ "$want_action" = "deny" ] && want_decision="deny"
  if [ "$got_decision" = "deny" ]; then
    case "$want_reason" in
      review_implement_*)
        case "$output_reason" in *"$want_reason"*) ;; *) output_valid=0 ;; esac
        ;;
    esac
  fi

  if [ "$got_decision" = "$want_decision" ] &&
     [ "$got_action" = "$want_action" ] &&
     [ "$output_valid" = "1" ] &&
     { [ "$want_decision" = "deny" ] || [ -z "$out" ]; } &&
     case "$got_reason" in *"$want_reason"*) true ;; *) false ;; esac; then
    pass "$label"
  else
    fail "$label" \
      "decision=$want_decision action=$want_action reason~=$want_reason valid-json=1" \
      "decision=$got_decision action=$got_action reason=$got_reason output-reason=$output_reason valid-json=$output_valid"
  fi
}

check_mech() {
  local label=$1 enforce=$2 want_action=$3 want_reason=$4 want_token=$5
  shift 5

  if [ "$enforce" = "1" ]; then : > "$SENTINEL"; else rm -f "$SENTINEL"; fi
  : > "$AUDIT"

  local out
  out=$(payload "$@" | env \
    T2_ROUTED_SENTINEL="$SENTINEL" \
    T2_FORK_GATE_OFF="${T2_FORK_GATE_OFF:-$TMP/nonexistent-fork-gate.off}" \
    T2_AUDIT_LOG="$AUDIT" \
    T2_TRACE_LOG="$TRACE" \
    T2_AGENT_DIR="$AGENT_DIR" \
    CC_FABLE_MAIN="" \
    CC_VENDOR="${TEST_VENDOR:-}" \
    REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" \
    REVIEW_SPEC_DUAL_PERMIT_HELPER="$DUAL_HELPER" \
    "$HOOK" 2>/dev/null)

  parse_hook_output "$out"
  local got_decision=$HOOK_OUTPUT_DECISION
  local got_action got_reason got_token output_valid=$HOOK_OUTPUT_VALID output_reason=$HOOK_OUTPUT_REASON guidance_valid=1 want_decision="allow"
  [ "$want_action" = "deny" ] && want_decision="deny"
  got_action=$(jq -r '.action // "NONE"' "$AUDIT" 2>/dev/null | tail -1)
  got_reason=$(jq -r '.reason // ""' "$AUDIT" 2>/dev/null | tail -1)
  got_token=$(jq -r '.token // ""' "$AUDIT" 2>/dev/null | tail -1)

  if [ "$want_action" = "deny" ]; then
    case "$output_reason" in
      *"輸入完整"*"輸出固定"*"不需搜尋／驗證／取捨"*"<mech-ok>"*"不要猜填"*"routed-judge"*) ;;
      *) guidance_valid=0 ;;
    esac
  fi

  if [ "$got_decision" = "$want_decision" ] &&
     [ "$got_action" = "$want_action" ] &&
     [ "$got_reason" = "$want_reason" ] &&
     [ "$got_token" = "$want_token" ] &&
     [ "$output_valid" = "1" ] &&
     { [ "$want_action" = "deny" ] || [ -z "$out" ]; } &&
     [ "$guidance_valid" = "1" ]; then
    pass "$label"
    return
  fi

  fail "$label" \
    "decision=$want_decision action=$want_action reason=$want_reason token=$want_token empty-allow-stdout=1" \
    "decision=$got_decision action=$got_action reason=$got_reason token=$got_token output-valid=$output_valid guidance-valid=$guidance_valid output=$out"
}

echo
echo "── sentinel 關閉：trial 前行為回歸 ──"

check "1  general-purpose + token + model:opus → allow" \
  0 0 allow "model:opus" \
  "general-purpose" "<routed:判斷> 分析這段" "" "opus" "$PLAIN_TRANSCRIPT"

check "2  general-purpose 無 token → deny no_routing_token" \
  0 0 deny "no_routing_token" \
  "general-purpose" "分析這段" "" "" "$PLAIN_TRANSCRIPT"

check "3  Fable main + 未指定 model → deny fable_inherit_no_model" \
  0 1 deny "fable_inherit_no_model" \
  "general-purpose" "<routed:判斷> 分析這段" "" "" "$PLAIN_TRANSCRIPT"

check "4  code-reviewer → pass-e1（舊黑名單邏輯）" \
  0 0 pass-e1 "specialized_agent:code-reviewer" \
  "code-reviewer" "review 這個 diff" "" "" "$PLAIN_TRANSCRIPT"

echo "── review-implement model selection authorization ──"
SAVED_TEST_SESSION=$TEST_SESSION
SAVED_PLAIN_TRANSCRIPT=$PLAIN_TRANSCRIPT
SAVED_TEST_VENDOR=${TEST_VENDOR:-}
SAVED_TEST_FABLE_MODEL=$TEST_FABLE_MODEL
TEST_SESSION=$REVIEW_SESSION
PLAIN_TRANSCRIPT=$REVIEW_TRANSCRIPT
TEST_VENDOR=gpt
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
check "review-implement scope + mapped Fable → allow" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_TRANSCRIPT"
if jq -s -e --arg session "$REVIEW_SESSION" \
  '.[-1] | .stage == "review-implement" and .axis == "scope" and .session_id == $session and .logical_model == "fable" and .resolved_model == "gpt-5.6-sol" and .action == "allow" and (.prompt_head | not) and (.description | not)' \
  "$AUDIT" >/dev/null 2>&1; then
  pass "review-implement audit binds stage axis session and mapped model without prompt"
else
  fail "review-implement audit binds stage axis session and mapped model without prompt" \
    "stage/axis/session/logical_model/resolved_model and no prompt fields" \
    "$(jq -c '.[-1]' "$AUDIT" 2>/dev/null)"
fi
TEST_VENDOR=""
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
MODEL_OPTIONS_FIXTURE=$(mktemp)
printf '%s\n' '{"additionalModelOptionsCache":[{"value":"claude-fable-5-1[1m]","label":"Fable"}]}' > "$MODEL_OPTIONS_FIXTURE"
TEST_MODEL_OPTIONS_JSON=$MODEL_OPTIONS_FIXTURE
check "review-implement native Fable → allow (resolved from model options cache)" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_TRANSCRIPT"
if jq -s -e '.[-1].logical_model == "fable" and .[-1].resolved_model == "claude-fable-5-1"' "$AUDIT" >/dev/null 2>&1; then
  pass "review-implement native audit resolves fable alias from model options cache without pinning a version"
else
  fail "review-implement native audit resolves fable alias from model options cache without pinning a version" \
    "logical_model=fable resolved_model=claude-fable-5-1" "$(jq -c '.[-1]' "$AUDIT" 2>/dev/null)"
fi
rm -f "$MODEL_OPTIONS_FIXTURE"
TEST_MODEL_OPTIONS_JSON=""
check "review-implement native Fable without model options cache → allow" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_TRANSCRIPT"
if jq -s -e '.[-1].resolved_model == "fable"' "$AUDIT" >/dev/null 2>&1; then
  pass "review-implement native audit falls back to the alias when no cache exists"
else
  fail "review-implement native audit falls back to the alias when no cache exists" \
    "resolved_model=fable" "$(jq -c '.[-1]' "$AUDIT" 2>/dev/null)"
fi
TEST_VENDOR=gpt
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
check "completed review stage + generic Fable escalation → allow" \
  1 0 pass-e1 "enforce_allowed:routed-judge" \
  "routed-judge" "ordinary failure escalation" "<fable-ok>" "fable" "$REVIEW_TRANSCRIPT"
check "review-implement scope + sentinel off → allow" \
  0 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_TRANSCRIPT"
TEST_SESSION=$REVIEW_YAGNI_SESSION
PLAIN_TRANSCRIPT=$REVIEW_YAGNI_TRANSCRIPT
check "review-implement yagni + mapped Fable → allow" \
  1 0 allow "review_implement_authorized:yagni" \
  "routed-judge" "yagni reviewer" "<fable-ok> <review-implement-fable:v1 axis=yagni>" "fable" "$REVIEW_YAGNI_TRANSCRIPT"
TEST_SESSION=$REVIEW_OPUS_SESSION
PLAIN_TRANSCRIPT=$REVIEW_OPUS_TRANSCRIPT
TEST_OPUS_MODEL='gpt-5.6-luna(max)'
check "review-implement selected Opus scope → allow" \
  1 0 allow "review_implement_authorized:opus:scope" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_OPUS_TRANSCRIPT"
check "review-implement selected Opus yagni from all → allow" \
  1 0 allow "review_implement_authorized:opus:yagni" \
  "routed-judge" "yagni reviewer" "<review-implement-selection:v1 model=opus axis=yagni>" "opus" "$REVIEW_OPUS_TRANSCRIPT"
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
check "review-implement user-selected model mismatch → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_model_not_selected" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-selection:v1 model=fable axis=scope>" "fable" "$REVIEW_OPUS_TRANSCRIPT"
TEST_SESSION=$REVIEW_NL_SESSION
PLAIN_TRANSCRIPT=$REVIEW_NL_TRANSCRIPT
TEST_OPUS_MODEL='gpt-5.6-luna(max)'
check "review-implement natural-language Opus scope → allow" \
  1 0 allow "review_implement_authorized:opus:scope" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_NL_TRANSCRIPT"
TEST_SESSION=$REVIEW_ADVERB_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ADVERB_TRANSCRIPT
check "review-implement adverb 都用 binds both axes → allow" \
  1 0 allow "review_implement_authorized:opus:scope" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_ADVERB_TRANSCRIPT"
check "review-implement adverb 都用 yagni seat → allow" \
  1 0 allow "review_implement_authorized:opus:yagni" \
  "routed-judge" "yagni reviewer" "<review-implement-selection:v1 model=opus axis=yagni>" "opus" "$REVIEW_ADVERB_TRANSCRIPT"
TEST_SESSION=$REVIEW_ADVERB_BARE_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ADVERB_BARE_TRANSCRIPT
check "review-implement adverb without axis → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_stale" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_ADVERB_BARE_TRANSCRIPT"
TEST_SESSION=$REVIEW_ADVERB_TRAILING_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ADVERB_TRAILING_TRANSCRIPT
check "review-implement adverb with trailing question stays fail-closed → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_stale" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_ADVERB_TRAILING_TRANSCRIPT"
TEST_SESSION=$REVIEW_NL_SESSION
PLAIN_TRANSCRIPT=$REVIEW_NL_TRANSCRIPT
TEST_SESSION=$REVIEW_OPUS_SESSION
PLAIN_TRANSCRIPT=$REVIEW_OPUS_TRANSCRIPT
MODEL_OPTIONS_FIXTURE=$(mktemp)
printf '%s\n' '{"additionalModelOptionsCache":[{"value":"claude-opus-5[1m]","label":"Opus"}]}' > "$MODEL_OPTIONS_FIXTURE"
TEST_VENDOR=""
TEST_MODEL_OPTIONS_JSON=$MODEL_OPTIONS_FIXTURE
check "review-implement native Opus resolves model options cache" \
  1 0 allow "review_implement_authorized:opus:scope" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_OPUS_TRANSCRIPT"
if jq -s -e '.[-1].logical_model == "opus" and .[-1].resolved_model == "claude-opus-5"' "$AUDIT" >/dev/null 2>&1; then
  pass "review-implement native Opus audit resolves selected model"
else
  fail "review-implement native Opus audit resolves selected model" \
    "logical_model=opus resolved_model=claude-opus-5" "$(jq -c '.[-1]' "$AUDIT" 2>/dev/null)"
fi
rm -f "$MODEL_OPTIONS_FIXTURE"
TEST_MODEL_OPTIONS_JSON=""
TEST_VENDOR=gpt
TEST_OPUS_MODEL=""
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
check "review-implement selected Opus missing vendor mapping → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_model_mapping_missing" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_OPUS_TRANSCRIPT"
TEST_SESSION=$REVIEW_PAIR_SESSION
PLAIN_TRANSCRIPT=$REVIEW_PAIR_TRANSCRIPT
TEST_OPUS_MODEL='gpt-5.6-luna(max)'
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
check "review-implement selected Opus seat in same-axis pair → allow" \
  1 0 allow "review_implement_authorized:opus:scope" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_PAIR_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_PAIR_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"pair-opus",name:"Agent",input:{subagent_type:"routed-judge",model:"opus",description:"<review-implement-selection:v1 model=opus axis=scope>",prompt:"prior scope reviewer"}}]}}' >> "$REVIEW_PAIR_TRANSCRIPT"
check "review-implement selected Fable seat beside Opus → allow" \
  1 0 allow "review_implement_authorized:fable:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-selection:v1 model=fable axis=scope>" "fable" "$REVIEW_PAIR_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_PAIR_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"pair-fable",name:"Agent",input:{subagent_type:"routed-judge",model:"fable",description:"<fable-ok> <review-implement-selection:v1 model=fable axis=scope>",prompt:"prior scope reviewer"}}]}}' >> "$REVIEW_PAIR_TRANSCRIPT"
check "review-implement repeated model-axis seat → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_selection_already_dispatched" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-selection:v1 model=fable axis=scope>" "fable" "$REVIEW_PAIR_TRANSCRIPT"
TEST_SESSION=$REVIEW_RECOMMENDED_SESSION
PLAIN_TRANSCRIPT=$REVIEW_RECOMMENDED_TRANSCRIPT
TEST_OPUS_MODEL='gpt-5.6-luna(max)'
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
check "review-implement recommendation selects Opus scope → allow" \
  1 0 allow "review_implement_authorized:opus:scope" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_RECOMMENDED_TRANSCRIPT"
check "review-implement recommendation rejects unselected Fable scope → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_model_not_selected" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-selection:v1 model=fable axis=scope>" "fable" "$REVIEW_RECOMMENDED_TRANSCRIPT"
check "review-implement recommendation rejects unselected Opus yagni → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_not_selected" \
  "routed-judge" "yagni reviewer" "<review-implement-selection:v1 model=opus axis=yagni>" "opus" "$REVIEW_RECOMMENDED_TRANSCRIPT"
TEST_SESSION=$REVIEW_NO_RECOMMENDATION_SESSION
PLAIN_TRANSCRIPT=$REVIEW_NO_RECOMMENDATION_TRANSCRIPT
TEST_OPUS_MODEL='gpt-5.6-luna(max)'
check "review-implement recommendation without declaration → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_recommendation_missing" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_NO_RECOMMENDATION_TRANSCRIPT"
TEST_SESSION=$REVIEW_CROSS_STAGE_RECOMMENDATION_SESSION
PLAIN_TRANSCRIPT=$REVIEW_CROSS_STAGE_RECOMMENDATION_TRANSCRIPT
check "review-implement prior-stage recommendation cannot authorize → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_recommendation_missing" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_CROSS_STAGE_RECOMMENDATION_TRANSCRIPT"
TEST_SESSION=$REVIEW_SIDECHAIN_RECOMMENDATION_SESSION
PLAIN_TRANSCRIPT=$REVIEW_SIDECHAIN_RECOMMENDATION_TRANSCRIPT
check "review-implement sidechain recommendation cannot authorize → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_recommendation_missing" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_SIDECHAIN_RECOMMENDATION_TRANSCRIPT"
TEST_SESSION=$REVIEW_RECOMMENDED_ALIAS_SESSION
PLAIN_TRANSCRIPT=$REVIEW_RECOMMENDED_ALIAS_TRANSCRIPT
TEST_OPUS_MODEL='gpt-5.6-luna(max)'
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
check "review-implement recommendation + b uses Opus → allow" \
  1 0 allow "review_implement_authorized:opus:scope" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_RECOMMENDED_ALIAS_TRANSCRIPT"
check "review-implement recommendation + b rejects Fable → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_model_not_selected" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-selection:v1 model=fable axis=scope>" "fable" "$REVIEW_RECOMMENDED_ALIAS_TRANSCRIPT"
TEST_SESSION=$REVIEW_SIDECHAIN_RESULT_SESSION
PLAIN_TRANSCRIPT=$REVIEW_SIDECHAIN_RESULT_TRANSCRIPT
check "review-implement sidechain-only stage result → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_invocation_result_missing" \
  "routed-judge" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_SIDECHAIN_RESULT_TRANSCRIPT"
TEST_SESSION=$REVIEW_ALIAS_B_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ALIAS_B_TRANSCRIPT
check "review-implement exact menu + b → authorize scope" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_ALIAS_B_TRANSCRIPT"
TEST_SESSION=$REVIEW_ALIAS_A_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ALIAS_A_TRANSCRIPT
check "review-implement exact menu + a → authorize all for scope" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_ALIAS_A_TRANSCRIPT"
TEST_SESSION=$REVIEW_ALIAS_NO_MENU_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ALIAS_NO_MENU_TRANSCRIPT
check "review-implement letter without menu → deny unbound alias" \
  1 0 would_deny "review_implement_axis_alias_unbound" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_ALIAS_NO_MENU_TRANSCRIPT"
TEST_SESSION=$REVIEW_ALIAS_TAMPERED_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ALIAS_TAMPERED_TRANSCRIPT
check "review-implement tampered menu + b → deny unbound alias" \
  1 0 would_deny "review_implement_axis_alias_unbound" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_ALIAS_TAMPERED_TRANSCRIPT"
TEST_SESSION=$REVIEW_ALIAS_DUPLICATE_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ALIAS_DUPLICATE_TRANSCRIPT
check "review-implement duplicate menu + b → deny unbound alias" \
  1 0 would_deny "review_implement_axis_alias_unbound" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_ALIAS_DUPLICATE_TRANSCRIPT"
TEST_SESSION=$REVIEW_ALIAS_SKIP_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ALIAS_SKIP_TRANSCRIPT
check "review-implement exact menu + d → deny reviewer as skip" \
  1 0 would_deny "review_implement_axis_not_selected" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_ALIAS_SKIP_TRANSCRIPT"
TEST_SESSION=$REVIEW_ALIAS_SIDECHAIN_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ALIAS_SIDECHAIN_TRANSCRIPT
check "review-implement sidechain and tool-result menus cannot bind b" \
  1 0 would_deny "review_implement_axis_alias_unbound" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_ALIAS_SIDECHAIN_TRANSCRIPT"
TEST_SESSION=$REVIEW_ALIAS_UNKNOWN_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ALIAS_UNKNOWN_TRANSCRIPT
check "review-implement unknown letter + exact menu → deny unbound alias" \
  1 0 would_deny "review_implement_axis_alias_unbound" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_ALIAS_UNKNOWN_TRANSCRIPT"
TEST_SESSION=$SAVED_TEST_SESSION
PLAIN_TRANSCRIPT=$SAVED_PLAIN_TRANSCRIPT
TEST_VENDOR=$SAVED_TEST_VENDOR
TEST_FABLE_MODEL=$SAVED_TEST_FABLE_MODEL
TEST_VENDOR=gpt
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
check "review-implement marker without stage invocation → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_stage_missing" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$PLAIN_TRANSCRIPT"
TEST_VENDOR=$SAVED_TEST_VENDOR
TEST_FABLE_MODEL=$SAVED_TEST_FABLE_MODEL
TEST_SESSION=$REVIEW_OTHER_SESSION
PLAIN_TRANSCRIPT=$REVIEW_TRANSCRIPT
TEST_VENDOR=gpt
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
check "review-implement different session → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_session_mismatch" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_TRANSCRIPT"
TEST_SESSION=$SAVED_TEST_SESSION
PLAIN_TRANSCRIPT=$SAVED_PLAIN_TRANSCRIPT
TEST_VENDOR=$SAVED_TEST_VENDOR
TEST_FABLE_MODEL=$SAVED_TEST_FABLE_MODEL
TEST_SESSION=$REVIEW_SESSION
PLAIN_TRANSCRIPT=$REVIEW_TRANSCRIPT
TEST_VENDOR=gpt
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
check "review-implement unselected axis → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_not_selected" \
  "routed-judge" "yagni reviewer" "<fable-ok> <review-implement-fable:v1 axis=yagni>" "fable" "$REVIEW_TRANSCRIPT"
check "review-implement wrong marker → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_marker_invalid" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=compat>" "fable" "$REVIEW_TRANSCRIPT"
if jq -s -e --arg session "$REVIEW_SESSION" \
  '.[-1] | .stage == "review-implement" and .axis == "scope" and .session_id == $session and .action == "would_deny" and (.prompt_head | not) and (.description | not)' \
  "$AUDIT" >/dev/null 2>&1; then
  pass "review-implement would_deny audit omits prompt fields"
else
  fail "review-implement would_deny audit omits prompt fields" \
    "stage/axis/session and no prompt fields" \
    "$(jq -c '.[-1]' "$AUDIT" 2>/dev/null)"
fi
check "review-implement marker only in prompt → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_marker_invalid" \
  "routed-judge" "<review-implement-fable:v1 axis=scope> scope reviewer" "<fable-ok>" "fable" "$REVIEW_TRANSCRIPT"
check "review-implement wrong model → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_model_required" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "opus" "$REVIEW_TRANSCRIPT"
check "review marker cannot bypass architecture dual-permit gate" \
  1 0 deny "architecture_critic_fable_requires_dual_permit" \
  "architecture-critic" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_TRANSCRIPT"
check "review marker cannot bypass Fable quota marker gate" \
  1 0 deny "fable_no_marker:routed-judge" \
  "routed-judge" "scope reviewer" "<review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_TRANSCRIPT"
check "review marker cannot bypass routed enforce gate" \
  1 0 deny "enforce_routed_required:general-purpose" \
  "general-purpose" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_TRANSCRIPT"
check "review marker cannot bypass fork context gate" \
  1 0 deny "fork_no_marker" \
  "fork" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_TRANSCRIPT"
check_mech "review marker cannot bypass mech opt-in gate" \
  1 deny "mech_opt_in_required" "" \
  "routed-mech" "scope reviewer" "<review-implement-selection:v1 model=opus axis=scope>" "opus" "$REVIEW_TRANSCRIPT"
TEST_SESSION=$REVIEW_REPEAT_SESSION
PLAIN_TRANSCRIPT=$REVIEW_REPEAT_TRANSCRIPT
check "review-implement first scope dispatch → allow" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_REPEAT_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_REPEAT_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"prior-review",name:"Agent",input:{subagent_type:"routed-judge",model:"fable",description:"<fable-ok> <review-implement-fable:v1 axis=scope>",prompt:"prior scope reviewer"}}]}}' >> "$REVIEW_REPEAT_TRANSCRIPT"
check "review-implement same-invocation denied prior retry → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_already_dispatched" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_REPEAT_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_REPEAT_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"prior-review",is_error:null,content:"Launching agent"}]},toolUseResult:{status:"async_launched",isAsync:true,resolvedModel:"gpt-5.6-sol"}}' >> "$REVIEW_REPEAT_TRANSCRIPT"
check "review-implement successful repeated scope dispatch → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_already_dispatched" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_REPEAT_TRANSCRIPT"
TEST_SESSION=$REVIEW_RERUN_SESSION
PLAIN_TRANSCRIPT=$REVIEW_RERUN_TRANSCRIPT
check "review-implement fresh invocation retries prior failed scope → allow" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_RERUN_TRANSCRIPT"
TEST_SESSION=$REVIEW_CURRENT_SESSION
PLAIN_TRANSCRIPT=$REVIEW_CURRENT_TRANSCRIPT
check "review-implement current tool use is not prior dispatch → allow" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_CURRENT_TRANSCRIPT"
TEST_SESSION=$REVIEW_ALL_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ALL_TRANSCRIPT
check "review-implement all authorizes scope → allow" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_ALL_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ALL_SESSION" \
  '{type:"assistant",sessionId:$session,message:{role:"assistant",content:[{type:"tool_use",id:"all-prior-scope",name:"Agent",input:{subagent_type:"routed-judge",model:"fable",description:"<fable-ok> <review-implement-fable:v1 axis=scope>",prompt:"prior all scope reviewer"}}]}}' >> "$REVIEW_ALL_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_ALL_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:[{type:"tool_result",tool_use_id:"all-prior-scope",is_error:null,content:"Launching agent"}]},toolUseResult:{status:"async_launched",isAsync:true,resolvedModel:"gpt-5.6-sol"}}' >> "$REVIEW_ALL_TRANSCRIPT"
check "review-implement all repeated scope → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_already_dispatched" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_ALL_TRANSCRIPT"
check "review-implement all authorizes yagni → allow" \
  1 0 allow "review_implement_authorized:yagni" \
  "routed-judge" "yagni reviewer" "<fable-ok> <review-implement-fable:v1 axis=yagni>" "fable" "$REVIEW_ALL_TRANSCRIPT"
TEST_SESSION=$REVIEW_LOCAL_COMMAND_SESSION
PLAIN_TRANSCRIPT=$REVIEW_LOCAL_COMMAND_TRANSCRIPT
check "review-implement local-command envelopes stay ignored → allow" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
jq -nc \
  --arg session "$REVIEW_LOCAL_COMMAND_SESSION" \
  '{type:"user",userType:"external",sessionId:$session,message:{role:"user",content:"proceed"},origin:{kind:"human"},promptSource:"typed"}' >> "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
check "review-implement ordinary second human text stays stale → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_stale" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_LOCAL_COMMAND_TRANSCRIPT"
TEST_SESSION=$REVIEW_COMMAND_MIXED_SESSION
PLAIN_TRANSCRIPT=$REVIEW_COMMAND_MIXED_TRANSCRIPT
check "review-implement human text with trailing command tag stays stale → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_stale" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_COMMAND_MIXED_TRANSCRIPT"
TEST_SESSION=$REVIEW_COMPANION_BOUNDARY_SESSION
PLAIN_TRANSCRIPT=$REVIEW_COMPANION_BOUNDARY_TRANSCRIPT
check "review-implement human-provenance companion text stays stale → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_stale" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_COMPANION_BOUNDARY_TRANSCRIPT"
TEST_SESSION=$REVIEW_SYSTEM_FILTER_SESSION
PLAIN_TRANSCRIPT=$REVIEW_SYSTEM_FILTER_TRANSCRIPT
check "review-implement system task and tool records stay ignored → allow" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_SYSTEM_FILTER_TRANSCRIPT"
TEST_SESSION=$REVIEW_DUP_SESSION
PLAIN_TRANSCRIPT=$REVIEW_DUP_TRANSCRIPT
check "review-implement duplicate invocation → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_duplicate_invocation" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_DUP_TRANSCRIPT"
TEST_SESSION=$REVIEW_STALE_SESSION
PLAIN_TRANSCRIPT=$REVIEW_STALE_TRANSCRIPT
check "review-implement stale axis selection → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_stale" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_STALE_TRANSCRIPT"
# review-implement 觀測型契約（2026-09-18 取代 2026-09-11 的 sentinel log-only trial）：分支恆不攔截，
# 授權判定失敗一律走 audit row action=would_deny 後放行；唯一仍 deny 的是 audit row 寫不進去。
TEST_SESSION=$REVIEW_STALE_SESSION
PLAIN_TRANSCRIPT=$REVIEW_STALE_TRANSCRIPT
check "review-implement observe: known-bad stale selection → allow with would_deny row" \
  1 0 would_deny "review_implement_axis_stale" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_STALE_TRANSCRIPT"
TEST_SESSION=$REVIEW_SESSION
PLAIN_TRANSCRIPT=$REVIEW_TRANSCRIPT
check "review-implement observe: known-good authorized seat still allow (unchanged reason)" \
  1 0 allow "review_implement_authorized:scope" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_TRANSCRIPT"
OBSERVE_AUDIT_DIR="$TMP/audit-as-dir"
mkdir -p "$OBSERVE_AUDIT_DIR"
OBSERVE_BOUNDARY_OUT=$(payload_for "$REVIEW_STALE_SESSION" "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_STALE_TRANSCRIPT" | env \
  T2_ROUTED_SENTINEL="$SENTINEL" \
  T2_FORK_GATE_OFF="$TMP/nonexistent-fork-gate.off" T2_AUDIT_LOG="$OBSERVE_AUDIT_DIR" T2_TRACE_LOG="$TRACE" T2_AGENT_DIR="$AGENT_DIR" \
  T2_MODEL_OPTIONS_JSON="/nonexistent-model-options.json" "$HOOK" 2>/dev/null)
parse_hook_output "$OBSERVE_BOUNDARY_OUT"
if [ "$HOOK_OUTPUT_DECISION" = "deny" ] && case "$HOOK_OUTPUT_REASON" in *"audit log 無法安全追加"*) true ;; *) false ;; esac; then
  pass "review-implement observe: boundary — audit row unwritable still fails closed"
else
  fail "review-implement observe: boundary — audit row unwritable still fails closed" "deny + audit-failed reason" "decision=$HOOK_OUTPUT_DECISION reason=$HOOK_OUTPUT_REASON"
fi
rmdir "$OBSERVE_AUDIT_DIR"
# 反向斷言（gate-authoring §3）：鎖住 2026-09-18 移除的兩件事不再回來。
# (a) gate 不得再讀 review-implement-log-only sentinel——舊寫法讓「刪檔即恢復 deny」，攔截會靜默復活。
if command grep -q 'REVIEW_LOG_ONLY' "$HOOK"; then
  fail "review-implement observe: gate no longer reads log-only sentinel" "no REVIEW_LOG_ONLY in hook" "found REVIEW_LOG_ONLY reference"
else
  pass "review-implement observe: gate no longer reads log-only sentinel"
fi
# (b) review_deny 不得再輸出 permissionDecision deny——它現在只記帳後 exit 0。
if awk '/^review_deny\(\) \{/{f=1} f&&/^\}/{f=0} f' "$HOOK" | command grep -q 'permissionDecision'; then
  fail "review-implement observe: review_deny emits no deny decision" "review_deny body has no permissionDecision" "found permissionDecision in review_deny body"
else
  pass "review-implement observe: review_deny emits no deny decision"
fi
TEST_SESSION=$REVIEW_ERROR_SESSION
PLAIN_TRANSCRIPT=$REVIEW_ERROR_TRANSCRIPT
check "review-implement errored stage result → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_invocation_error" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_ERROR_TRANSCRIPT"
TEST_SESSION=$REVIEW_SKIP_SESSION
PLAIN_TRANSCRIPT=$REVIEW_SKIP_TRANSCRIPT
check "review-implement skip selection with stage marker → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_axis_not_selected" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_SKIP_TRANSCRIPT"
TEST_SESSION=$REVIEW_MISSING_SESSION
PLAIN_TRANSCRIPT=$REVIEW_MISSING_TRANSCRIPT
check "review-implement missing stage result → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_invocation_result_missing" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_MISSING_TRANSCRIPT"
TEST_SESSION=$SAVED_TEST_SESSION
PLAIN_TRANSCRIPT=$SAVED_PLAIN_TRANSCRIPT
TEST_VENDOR=$SAVED_TEST_VENDOR
TEST_FABLE_MODEL=$SAVED_TEST_FABLE_MODEL
TEST_SESSION=$REVIEW_SESSION
PLAIN_TRANSCRIPT=$REVIEW_TRANSCRIPT
TEST_VENDOR=gpt
TEST_FABLE_MODEL='gpt-5.6-sol(max)'
check "review-implement fixed Fable marker alone keeps generic escalation" \
  1 0 pass-e1 "enforce_allowed:routed-judge" \
  "routed-judge" "ordinary failure escalation" "<fable-ok>" "fable" "$REVIEW_TRANSCRIPT"
TEST_FABLE_MODEL=""
check "review-implement vendor mapping missing → observe (allow + would_deny row)" \
  1 0 would_deny "review_implement_model_mapping_missing" \
  "routed-judge" "scope reviewer" "<fable-ok> <review-implement-fable:v1 axis=scope>" "fable" "$REVIEW_TRANSCRIPT"
TEST_SESSION=$SAVED_TEST_SESSION
PLAIN_TRANSCRIPT=$SAVED_PLAIN_TRANSCRIPT
TEST_VENDOR=$SAVED_TEST_VENDOR
TEST_FABLE_MODEL=$SAVED_TEST_FABLE_MODEL

echo
echo "── sentinel 開啟：routed-* 強制 ──"

check "5  routed-judge → allow" \
  1 0 pass-e1 "enforce_allowed:routed-judge" \
  "routed-judge" "判斷這個架構決策" "" "" "$PLAIN_TRANSCRIPT"

check "6  routed-impl → allow" \
  1 0 pass-e1 "enforce_allowed:routed-impl" \
  "routed-impl" "實作這個 function" "" "" "$PLAIN_TRANSCRIPT"

check "7  general-purpose + token + model:opus → DENY（case 1 同輸入、反轉）" \
  1 0 deny "enforce_routed_required:general-purpose" \
  "general-purpose" "<routed:判斷> 分析這段" "" "opus" "$PLAIN_TRANSCRIPT"

check "8  subagent_type 空字串 → deny" \
  1 0 deny "enforce_routed_required:empty" \
  "" "<routed:機械> 翻譯這段" "" "" "$PLAIN_TRANSCRIPT"

check "9  subagent_type 整個省略 → deny" \
  1 0 deny "enforce_routed_required:empty" \
  "" "<routed:機械> 翻譯這段" "" "" "$PLAIN_TRANSCRIPT" yes

check "10 claude（內建、無定義檔）→ deny" \
  1 0 deny "enforce_routed_required:claude" \
  "claude" "隨便做點事" "" "" "$PLAIN_TRANSCRIPT"

check "11 routed-impl + model:fable 無標記 → deny" \
  1 0 deny "fable_no_marker:routed-impl" \
  "routed-impl" "實作這個" "" "fable" "$PLAIN_TRANSCRIPT"

check "12 routed-impl + model:fable + description <fable-ok> → allow" \
  1 0 pass-e1 "enforce_allowed:routed-impl" \
  "routed-impl" "升級終級重試" "<fable-ok> 完整失敗軌跡" "fable" "$PLAIN_TRANSCRIPT"

check "13 workflow transcript + general-purpose → pass-e2（不誤殺 fan-out）" \
  1 0 pass-e2 "workflow_context" \
  "general-purpose" "workflow 內派工" "" "" "$WF_TRANSCRIPT"

check "14 codex:codex-rescue（plugin agent、無本地檔）→ allow" \
  1 0 pass-e1 "enforce_allowed:codex:codex-rescue" \
  "codex:codex-rescue" "救援這個 bug" "" "" "$PLAIN_TRANSCRIPT"

# 15a–15h：2026-09-05 起 fork 一律要 description 的 <fork-ok: 理由>、不分 main model
# （原 B 案「main 非 Fable 直接放行」已廢；理由見 hook 內 fork 分支註解）

check "15a fork + main 非 Fable + 無 marker → deny（known-bad；原 B 案放行已廢）" \
  1 0 deny "fork_no_marker" \
  "fork" "繼承 context 查證" "" "" "$PLAIN_TRANSCRIPT"

check "15b fork + Fable main 無 marker → deny（known-bad）" \
  1 1 deny "fork_no_marker" \
  "fork" "繼承 context 查證" "" "" "$PLAIN_TRANSCRIPT"

check "15c fork + description <fork-ok: 足夠理由> → allow（known-good）" \
  1 0 pass-e1 "fork_ok" \
  "fork" "繼承 context 查證" "<fork-ok: 需要前面十二輪的 ticket 討論脈絡才接得下去>" "" "$PLAIN_TRANSCRIPT"

# 15c-fable 系列：額度軸（2026-09-05 拍板兩軸分開）。原生 Fable 當 main 時脈絡軸過了
# 還要 <fable-ok>；vendor 檔位偵測不到 CC_FABLE_MAIN，只走脈絡軸。這三格原本無測資。
check "15c1 Fable main + 只有 <fork-ok> → deny（額度軸未授權）" \
  1 1 deny "fork_fable_main_no_marker" \
  "fork" "繼承 context 查證" "<fork-ok: 需要前面十二輪的 ticket 討論脈絡才接得下去>" "" "$PLAIN_TRANSCRIPT"

check "15c2 Fable main + <fork-ok> + <fable-ok> → allow（兩軸都授權）" \
  1 1 pass-e1 "fork_ok" \
  "fork" "繼承 context 查證" "<fable-ok> <fork-ok: 需要前面十二輪的 ticket 討論脈絡才接得下去>" "" "$PLAIN_TRANSCRIPT"

check "15c3 Fable main + 只有 <fable-ok> → deny（脈絡軸未授權）" \
  1 1 deny "fork_no_marker" \
  "fork" "繼承 context 查證" "<fable-ok> 值得燒配額" "" "$PLAIN_TRANSCRIPT"

check "15c4 非 Fable main + 只有 <fork-ok> → allow（vendor 不受額度軸限制）" \
  1 0 pass-e1 "fork_ok" \
  "fork" "繼承 context 查證" "<fork-ok: 需要前面十二輪的 ticket 討論脈絡才接得下去>" "" "$PLAIN_TRANSCRIPT"

# 理由內含 '>' 不得被截斷（舊 [^>]* 會截成 10 bytes 並誤報「理由太短」）
check "15j fork + 理由含 '>' → allow（不得截斷）" \
  1 0 pass-e1 "fork_ok" \
  "fork" "繼承 context 查證" "<fork-ok: 需要 A -> B -> C 的完整討論脈絡才接得下去>" "" "$PLAIN_TRANSCRIPT"

check "15d fork + marker 只在 prompt → deny（邊界：只讀 description）" \
  1 0 deny "fork_no_marker" \
  "fork" "<fork-ok: 需要前面十二輪的討論脈絡> 繼承 context 查證" "" "" "$PLAIN_TRANSCRIPT"

check "15e sentinel off + fork + 無 marker → deny（legacy E1 不得放行 fork）" \
  0 1 deny "fork_no_marker" \
  "fork" "繼承 context 查證" "" "" "$PLAIN_TRANSCRIPT"

check "15f sentinel off + fork + <fork-ok: 理由> → allow（兩態共用同一門檻）" \
  0 0 pass-e1 "fork_ok" \
  "fork" "繼承 context 查證" "<fork-ok: 需要前面十二輪的 ticket 討論脈絡才接得下去>" "" "$PLAIN_TRANSCRIPT"

check "15g fork + <fork-ok:> 理由過短 → deny（邊界：鎖住長度線）" \
  1 0 deny "fork_reason_too_thin" \
  "fork" "繼承 context 查證" "<fork-ok: 需要>" "" "$PLAIN_TRANSCRIPT"

check "15h fork + 舊的 <fable-ok> → deny（反向斷言：舊寫法 2026-09-05 起失效）" \
  1 1 deny "fork_no_marker" \
  "fork" "繼承 context 查證" "<fable-ok> 值得燒 Fable 的理由" "" "$PLAIN_TRANSCRIPT"

# 15i：recovery 路徑（checklist 1 第三條）——routed-enforce.on 改名救不了 fork 分支，
# 誤攔時唯一出口是 fork-gate.off；沒有這件測資等於 recovery 只存在於註解裡
FORK_OFF_SENTINEL="$TMP/fork-gate.off"
: > "$FORK_OFF_SENTINEL"
T2_FORK_GATE_OFF="$FORK_OFF_SENTINEL" \
check "15i fork + 無 marker + fork-gate.off → allow（recovery 出口）" \
  1 1 pass-e1 "fork_gate_disabled" \
  "fork" "繼承 context 查證" "" "" "$PLAIN_TRANSCRIPT"
rm -f "$FORK_OFF_SENTINEL"

check "16 未知 agent 無定義檔 → deny（fail-closed）" \
  1 0 deny "enforce_routed_required:some-unknown-agent" \
  "some-unknown-agent" "做點事" "" "" "$PLAIN_TRANSCRIPT"

check_mech "17 sentinel on + description marker → allow" \
  1 pass-e1 "mech_opt_in_ok" "<mech-ok>" \
  "routed-mech" "依固定格式轉換" "<mech-ok> mechanical transform" "" "$PLAIN_TRANSCRIPT"

check_mech "18 sentinel off + description marker → allow" \
  0 pass-e1 "mech_opt_in_ok" "<mech-ok>" \
  "routed-mech" "依固定格式轉換" "<mech-ok> mechanical transform" "" "$PLAIN_TRANSCRIPT"

check_mech "19 sentinel on + 無 marker → deny with guidance" \
  1 deny "mech_opt_in_required" "" \
  "routed-mech" "依固定格式轉換" "mechanical transform" "" "$PLAIN_TRANSCRIPT"

check_mech "20 sentinel off + 無 marker → deny with guidance" \
  0 deny "mech_opt_in_required" "" \
  "routed-mech" "依固定格式轉換" "mechanical transform" "" "$PLAIN_TRANSCRIPT"

check_mech "21 marker 只在 prompt → deny" \
  1 deny "mech_opt_in_required" "" \
  "routed-mech" "<mech-ok> 依固定格式轉換" "mechanical transform" "" "$PLAIN_TRANSCRIPT"

check "22 routed-secure 無 mech marker → allow" \
  1 0 pass-e1 "enforce_allowed:routed-secure" \
  "routed-secure" "修補安全問題" "" "" "$PLAIN_TRANSCRIPT"

check "23 routed-mech + Fable 無 <fable-ok> → Fable 優先 deny" \
  1 0 deny "fable_no_marker:routed-mech" \
  "routed-mech" "依固定格式轉換" "<mech-ok> mechanical transform" "fable" "$PLAIN_TRANSCRIPT"

check "24 sentinel on + workflow routed-mech 無 marker → pass-e2" \
  1 0 pass-e2 "workflow_context" \
  "routed-mech" "workflow 內機械派工" "" "" "$WF_TRANSCRIPT"

check "25 sentinel off + workflow routed-mech 無 marker → pass-e2" \
  0 0 pass-e2 "workflow_context" \
  "routed-mech" "workflow 內機械派工" "" "" "$WF_TRANSCRIPT"

DUAL_ISSUE=$(CC_VENDOR="" ANTHROPIC_DEFAULT_OPUS_MODEL="" ANTHROPIC_DEFAULT_FABLE_MODEL="" \
  REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" \
  "$DUAL_HELPER" issue \
  --session "$TEST_SESSION" \
  --spec "$SPEC")
DUAL_PERMIT_ID=$(printf '%s' "$DUAL_ISSUE" | jq -r '.permit_id // empty')
DUAL_SNAPSHOT=$(printf '%s' "$DUAL_ISSUE" | jq -r '.snapshot_path // empty')
jq -nc --arg session "$TEST_SESSION" '{type:"user",userType:"external",sessionId:$session,uuid:"review-spec-selection-test",timestamp:"2026-08-06T03:02:10Z",message:{role:"user",content:"只選 simplify:opus,simplify:fable,failure:opus,failure:fable,repo:opus,repo:fable,compat:opus,compat:fable"}}' >> "$PLAIN_TRANSCRIPT"
CC_VENDOR="" ANTHROPIC_DEFAULT_OPUS_MODEL="" ANTHROPIC_DEFAULT_FABLE_MODEL="" REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" "$DUAL_HELPER" finalize --session "$TEST_SESSION" --lenses simplify,failure,repo,compat >/dev/null
DUAL_PROMPT_SIMPLIFY=$(CC_VENDOR="" ANTHROPIC_DEFAULT_OPUS_MODEL="" ANTHROPIC_DEFAULT_FABLE_MODEL="" REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" "$DUAL_HELPER" packet --session "$TEST_SESSION" --lens simplify)
DUAL_PROMPT_FAILURE=$(CC_VENDOR="" ANTHROPIC_DEFAULT_OPUS_MODEL="" ANTHROPIC_DEFAULT_FABLE_MODEL="" REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" "$DUAL_HELPER" packet --session "$TEST_SESSION" --lens failure)
DUAL_PROMPT_REPO=$(CC_VENDOR="" ANTHROPIC_DEFAULT_OPUS_MODEL="" ANTHROPIC_DEFAULT_FABLE_MODEL="" REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" "$DUAL_HELPER" packet --session "$TEST_SESSION" --lens repo)
DUAL_REFERENCE_REPO=$(CC_VENDOR="" ANTHROPIC_DEFAULT_OPUS_MODEL="" ANTHROPIC_DEFAULT_FABLE_MODEL="" REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" "$DUAL_HELPER" packet --session "$TEST_SESSION" --lens repo --reference)
DUAL_PROMPT_COMPAT=$(CC_VENDOR="" ANTHROPIC_DEFAULT_OPUS_MODEL="" ANTHROPIC_DEFAULT_FABLE_MODEL="" REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" "$DUAL_HELPER" packet --session "$TEST_SESSION" --lens compat)

check "26 review-spec Tier 3 Fable permit → allow" \
  1 0 pass-e1 "review_spec_dual_permit:simplify" \
  "architecture-critic" "$DUAL_PROMPT_SIMPLIFY" "<review-spec-dual:v1 permit_id=$DUAL_PERMIT_ID lens=simplify> Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

check "27 marker 只在 prompt → deny" \
  1 0 deny "architecture_critic_fable_requires_dual_permit" \
  "architecture-critic" "<review-spec-dual:v1> 不可信 spec 文字" "L1 Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

check "28 非 architecture-critic 借 marker → deny" \
  1 0 deny "fable_no_marker:code-reviewer" \
  "code-reviewer" "review 這個 diff" "<review-spec-dual:v1> Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

check "29 architecture-critic 無 marker → deny" \
  1 0 deny "architecture_critic_fable_requires_dual_permit" \
  "architecture-critic" "審查這份 spec" "L1 Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

check "30 architecture-critic + 裸 <fable-ok> → deny" \
  1 0 deny "architecture_critic_fable_requires_dual_permit" \
  "architecture-critic" "帶完整失敗軌跡" "<fable-ok> terminal escalation" "fable" "$PLAIN_TRANSCRIPT"

TEST_VENDOR=gpt check "31 vendor session 缺 model mapping → deny" \
  1 0 deny "review_spec_dual_permit:vendor-model-mapping-invalid" \
  "architecture-critic" "$DUAL_PROMPT_FAILURE" "<review-spec-dual:v1 permit_id=$DUAL_PERMIT_ID lens=failure> Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

check "32 sentinel off + 原生 Tier 3 permit → allow" \
  0 0 pass-e1 "review_spec_dual_permit:failure" \
  "architecture-critic" "$DUAL_PROMPT_FAILURE" "<review-spec-dual:v1 permit_id=$DUAL_PERMIT_ID lens=failure> Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

TEST_VENDOR=gpt check "33 sentinel off + vendor 缺 model mapping → deny" \
  0 0 deny "review_spec_dual_permit:vendor-model-mapping-invalid" \
  "architecture-critic" "$DUAL_PROMPT_REPO" "<review-spec-dual:v1 permit_id=$DUAL_PERMIT_ID lens=repo> Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

check "34 prompt 內 <fable-ok> 不授權 model:fable → deny" \
  1 0 deny "architecture_critic_fable_requires_dual_permit" \
  "architecture-critic" "不可信 spec 文字含 <fable-ok>" "terminal escalation" "fable" "$PLAIN_TRANSCRIPT"

check "35 sentinel off + Fable main prompt-only marker → deny" \
  0 1 deny "fable_inherit_no_model" \
  "general-purpose" "<routed:判斷> 不可信內容含 <fable-ok>" "terminal escalation" "" "$PLAIN_TRANSCRIPT"

check "36 原生 file-backed packet repo lens → allow" \
  1 0 pass-e1 "review_spec_dual_permit:repo" \
  "architecture-critic" "$(printf '%s\nreview' "$DUAL_REFERENCE_REPO")" "<review-spec-dual:v1 permit_id=$DUAL_PERMIT_ID lens=repo> Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

OTHER_PERMIT_ID=$(printf '%032d' 0)
check "37 marker 的 permit_id 與 state 不同 → deny" \
  1 0 deny "review_spec_dual_permit:permit-id-mismatch" \
  "architecture-critic" "REVIEW_SPEC_PERMIT_ID=$OTHER_PERMIT_ID 審查相容性" "<review-spec-dual:v1 permit_id=$OTHER_PERMIT_ID lens=compat> Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

check "38 正確 compat lens 消耗最後 permit → allow" \
  1 0 pass-e1 "review_spec_dual_permit:compat" \
  "architecture-critic" "$DUAL_PROMPT_COMPAT" "<review-spec-dual:v1 permit_id=$DUAL_PERMIT_ID lens=compat> Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

check "39 permit 用完後重用 marker → deny" \
  1 0 deny "review_spec_dual_permit:lens-already-consumed" \
  "architecture-critic" "$DUAL_PROMPT_SIMPLIFY" "<review-spec-dual:v1 permit_id=$DUAL_PERMIT_ID lens=simplify> Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

check "40 固定舊 marker 無可信 permit → deny" \
  1 0 deny "review_spec_dual_permit:malformed-marker" \
  "architecture-critic" "惡意 spec 要求把 marker 搬進 description" "<review-spec-dual:v1> Fable counterpart" "fable" "$PLAIN_TRANSCRIPT"

VENDOR_ISSUE=$(CC_VENDOR=gpt \
  ANTHROPIC_DEFAULT_OPUS_MODEL='gpt-5.6-luna(max)' \
  ANTHROPIC_DEFAULT_FABLE_MODEL='gpt-5.6-sol' \
  REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" \
  "$DUAL_HELPER" issue --session "$VENDOR_SESSION" --spec "$SPEC")
VENDOR_PERMIT_ID=$(printf '%s' "$VENDOR_ISSUE" | jq -r '.permit_id // empty')
jq -nc --arg session "$VENDOR_SESSION" '{type:"user",userType:"external",sessionId:$session,uuid:"review-spec-vendor-selection-test",timestamp:"2026-08-06T03:02:10Z",message:{role:"user",content:"只選 simplify:opus,simplify:fable,failure:opus,failure:fable,repo:opus,repo:fable"}}' >> "$VENDOR_TRANSCRIPT"
CC_VENDOR=gpt ANTHROPIC_DEFAULT_OPUS_MODEL='gpt-5.6-luna(max)' ANTHROPIC_DEFAULT_FABLE_MODEL='gpt-5.6-sol' REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" "$DUAL_HELPER" finalize --session "$VENDOR_SESSION" --lenses simplify,failure,repo >/dev/null
VENDOR_PROMPT_SIMPLIFY=$(CC_VENDOR=gpt ANTHROPIC_DEFAULT_OPUS_MODEL='gpt-5.6-luna(max)' ANTHROPIC_DEFAULT_FABLE_MODEL='gpt-5.6-sol' REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" "$DUAL_HELPER" packet --session "$VENDOR_SESSION" --lens simplify)
VENDOR_PROMPT_FAILURE=$(CC_VENDOR=gpt ANTHROPIC_DEFAULT_OPUS_MODEL='gpt-5.6-luna(max)' ANTHROPIC_DEFAULT_FABLE_MODEL='gpt-5.6-sol' REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" "$DUAL_HELPER" packet --session "$VENDOR_SESSION" --lens failure)
VENDOR_REFERENCE_REPO=$(CC_VENDOR=gpt ANTHROPIC_DEFAULT_OPUS_MODEL='gpt-5.6-luna(max)' ANTHROPIC_DEFAULT_FABLE_MODEL='gpt-5.6-sol' REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" "$DUAL_HELPER" packet --session "$VENDOR_SESSION" --lens repo --reference)
NATIVE_SESSION=$TEST_SESSION
NATIVE_TRANSCRIPT=$PLAIN_TRANSCRIPT
TEST_SESSION=$VENDOR_SESSION
PLAIN_TRANSCRIPT=$VENDOR_TRANSCRIPT
TEST_VENDOR=gpt
TEST_OPUS_MODEL='gpt-5.6-terra(max)'
TEST_FABLE_MODEL='gpt-5.6-sol'
check "40a vendor permit + mapping drift → deny" \
  1 0 deny "review_spec_dual_permit:vendor-model-binding-mismatch" \
  "architecture-critic" "$VENDOR_PROMPT_FAILURE" "<review-spec-dual:v1 permit_id=$VENDOR_PERMIT_ID lens=failure> Fable counterpart" "fable" "$VENDOR_TRANSCRIPT"
TEST_OPUS_MODEL='gpt-5.6-luna(max)'
check "40b vendor permit + distinct mapped roles → allow" \
  1 0 pass-e1 "review_spec_dual_permit:simplify" \
  "architecture-critic" "$VENDOR_PROMPT_SIMPLIFY" "<review-spec-dual:v1 permit_id=$VENDOR_PERMIT_ID lens=simplify> Fable counterpart" "fable" "$VENDOR_TRANSCRIPT"
check "40c sentinel off + vendor permit → allow" \
  0 0 pass-e1 "review_spec_dual_permit:failure" \
  "architecture-critic" "$VENDOR_PROMPT_FAILURE" "<review-spec-dual:v1 permit_id=$VENDOR_PERMIT_ID lens=failure> Fable counterpart" "fable" "$VENDOR_TRANSCRIPT"
check "40d vendor file-backed packet permit → allow" \
  1 0 pass-e1 "review_spec_dual_permit:repo" \
  "architecture-critic" "$(printf '%s\nreview' "$VENDOR_REFERENCE_REPO")" "<review-spec-dual:v1 permit_id=$VENDOR_PERMIT_ID lens=repo> Fable counterpart" "fable" "$VENDOR_TRANSCRIPT"
TEST_SESSION=$NATIVE_SESSION
PLAIN_TRANSCRIPT=$NATIVE_TRANSCRIPT
TEST_VENDOR=""
TEST_OPUS_MODEL=""
TEST_FABLE_MODEL=""

check "41 非 architecture reviewer 的終級 <fable-ok> → allow" \
  1 0 pass-e1 "enforce_allowed:routed-judge" \
  "routed-judge" "帶完整失敗軌跡" "<fable-ok> terminal escalation" "fable" "$PLAIN_TRANSCRIPT"

check "42 sentinel off + architecture-critic 裸 <fable-ok> → deny" \
  0 0 deny "architecture_critic_fable_requires_dual_permit" \
  "architecture-critic" "帶完整失敗軌跡" "<fable-ok> terminal escalation" "fable" "$PLAIN_TRANSCRIPT"

check "43 sentinel off + architecture-critic 無 marker → deny" \
  0 0 deny "architecture_critic_fable_requires_dual_permit" \
  "architecture-critic" "審查 spec" "plain description" "fable" "$PLAIN_TRANSCRIPT"

echo
echo "── Tier 3 permit 身分綁定：逐欄相等、用一次即消耗、過期與缺欄 deny ──"
ACC_PREFIX="t2-acc-$$"
ACC_STATE_BACKUP="$TMP/acc-state.bak"

acc_helper() {
  CC_VENDOR="" ANTHROPIC_DEFAULT_OPUS_MODEL="" ANTHROPIC_DEFAULT_FABLE_MODEL="" \
    REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" "$DUAL_HELPER" "$@"
}

# acc_setup <name>：建同 session 的 command 事件、issue、人類選擇事件、finalize、取 simplify packet
acc_setup() {
  ACC_SESSION="$ACC_PREFIX-$1"
  ACC_TRANSCRIPT="$PROJECT_FIXTURE_DIR/$ACC_SESSION.jsonl"
  jq -nc \
    --arg session "$ACC_SESSION" \
    --arg uuid "acc-command-$1" \
    --arg timestamp "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg cwd "$TMP" \
    --arg spec "$SPEC" \
    '{type:"user",userType:"external",sessionId:$session,uuid:$uuid,timestamp:$timestamp,cwd:$cwd,message:{role:"user",content:("<command-name>/review-spec</command-name>\n<command-message>review-spec</command-message>\n<command-args>3 "+$spec+"</command-args>")}}' > "$ACC_TRANSCRIPT"
  ACC_PERMIT_ID=$(acc_helper issue --session "$ACC_SESSION" --spec "$SPEC" | jq -r '.permit_id // empty')
  jq -nc --arg session "$ACC_SESSION" --arg uuid "acc-selection-$1" \
    '{type:"user",userType:"external",sessionId:$session,uuid:$uuid,timestamp:"2026-08-06T03:02:10Z",message:{role:"user",content:"只選 simplify:opus,simplify:fable,failure:opus,failure:fable,repo:opus,repo:fable,compat:opus,compat:fable"}}' >> "$ACC_TRANSCRIPT"
  acc_helper finalize --session "$ACC_SESSION" --lenses simplify,failure,repo,compat >/dev/null
  ACC_PROMPT=$(acc_helper packet --session "$ACC_SESSION" --lens simplify)
}

acc_marker() { printf '<review-spec-dual:v1 permit_id=%s lens=%s> Fable counterpart' "$ACC_PERMIT_ID" "$1"; }

# acc_check <label> <want_action> <want_reason> <prompt> <description>
acc_check() {
  local label=$1 want_action=$2 want_reason=$3 prompt=$4 desc=$5 saved_session=$TEST_SESSION
  TEST_SESSION=$ACC_SESSION
  check "$label" 1 0 "$want_action" "$want_reason" "architecture-critic" "$prompt" "$desc" "fable" "$ACC_TRANSCRIPT"
  TEST_SESSION=$saved_session
}

acc_state_edit() {
  local state="$DUAL_RUNTIME/$ACC_SESSION.json"
  cp "$state" "$ACC_STATE_BACKUP"
  jq -c "$1" "$ACC_STATE_BACKUP" > "$state"
  chmod 600 "$state"
}

acc_state_restore() {
  local state="$DUAL_RUNTIME/$ACC_SESSION.json"
  cp "$ACC_STATE_BACKUP" "$state"
  chmod 600 "$state"
}

acc_deny_text() {
  : > "$SENTINEL"
  : > "$AUDIT"
  payload_for "$ACC_SESSION" architecture-critic "$1" "$2" fable "$ACC_TRANSCRIPT" | env \
    T2_ROUTED_SENTINEL="$SENTINEL" \
    T2_FORK_GATE_OFF="$TMP/nonexistent-fork-gate.off" \
    T2_AUDIT_LOG="$AUDIT" \
    T2_TRACE_LOG="$TRACE" \
    T2_AGENT_DIR="$AGENT_DIR" \
    CC_FABLE_MAIN="" \
    CC_VENDOR="" \
    ANTHROPIC_DEFAULT_OPUS_MODEL="" \
    ANTHROPIC_DEFAULT_FABLE_MODEL="" \
    REVIEW_SPEC_DUAL_RUNTIME_DIR="$DUAL_RUNTIME" \
    REVIEW_SPEC_DUAL_PERMIT_HELPER="$DUAL_HELPER" \
    "$HOOK" 2>/dev/null | jq -r '.hookSpecificOutput.permissionDecisionReason // ""'
}

acc_setup valid
acc_check "44 有效、未消耗、未過期的身分 marker → allow" \
  pass-e1 "review_spec_dual_permit:simplify" "$ACC_PROMPT" "$(acc_marker simplify)"
CONSUMED_INDEX=$(jq -r '.remaining_lenses | index("simplify")' "$DUAL_RUNTIME/$ACC_SESSION.json")
if [ "$CONSUMED_INDEX" = "null" ]; then
  pass "44a 放行後 state 標記 simplify 已消耗"
else
  fail "44a 放行後 state 標記 simplify 已消耗" "simplify 不在 remaining_lenses" "index=$CONSUMED_INDEX"
fi
acc_check "45 同 permit 同 lens 第二次 → deny 已消耗" \
  deny "lens-already-consumed" "$ACC_PROMPT" "$(acc_marker simplify)"
CONSUMED_TEXT=$(acc_deny_text "$ACC_PROMPT" "$(acc_marker simplify)")
case "$CONSUMED_TEXT" in
  *lens-already-consumed*) pass "45b deny 文案寫出已消耗原因" ;;
  *) fail "45b deny 文案寫出已消耗原因" "含 lens-already-consumed" "$CONSUMED_TEXT" ;;
esac

acc_setup session
acc_state_edit '.session_id = "t2-acc-other-session"'
acc_check "46 state 記的 session_id 與呼叫 session 不同 → deny" \
  deny "permit-context-mismatch" "$ACC_PROMPT" "$(acc_marker simplify)"
acc_state_restore
acc_check "46a 還原 state 後同一呼叫放行（排除是 fixture 壞掉）" \
  pass-e1 "review_spec_dual_permit:simplify" "$ACC_PROMPT" "$(acc_marker simplify)"

acc_setup expiry
acc_state_edit '.expires_at = "2026-01-01T00:00:00Z"'
acc_check "47 expires_at 已過 → deny 到期" \
  deny "permit-expired" "$ACC_PROMPT" "$(acc_marker simplify)"
acc_state_restore
acc_state_edit '.expires_at = "2026-01-01T00:00:00Z"'
EXPIRED_TEXT=$(acc_deny_text "$ACC_PROMPT" "$(acc_marker simplify)")
case "$EXPIRED_TEXT" in
  *permit-expired*) pass "47b deny 文案寫出到期原因" ;;
  *) fail "47b deny 文案寫出到期原因" "含 permit-expired" "$EXPIRED_TEXT" ;;
esac

acc_setup fields
for field in session_id command_uuid permit_id spec_path snapshot_path expires_at; do
  acc_state_edit "del(.$field)"
  acc_check "48 state 缺 $field → deny 不當成放行" \
    deny "invalid-permit-state" "$ACC_PROMPT" "$(acc_marker simplify)"
  acc_state_restore
done

acc_setup oldmarker
OLD_FORMAT_DESC="<review-spec-dual:v1 permit_id=$ACC_PERMIT_ID lens=simplify spec_sha256=$(printf '%064d' 0)> Fable counterpart"
acc_check "49 帶 sha 欄位的舊 marker → 通用 deny" \
  deny "review_spec_dual_permit:malformed-marker" "$ACC_PROMPT" "$OLD_FORMAT_DESC"
OLD_FORMAT_TEXT=$(acc_deny_text "$ACC_PROMPT" "$OLD_FORMAT_DESC")
case "$OLD_FORMAT_TEXT" in
  *'<review-spec-dual:v1 permit_id=<id> lens=<slug>>'*) pass "49a 通用 deny 文案帶目前 marker 格式一句" ;;
  *) fail "49a 通用 deny 文案帶目前 marker 格式一句" "文案含 <review-spec-dual:v1 permit_id=<id> lens=<slug>>" "$OLD_FORMAT_TEXT" ;;
esac
case "$OLD_FORMAT_TEXT" in
  *hash*) fail "49b 通用 deny 文案不再提文件 hash" "文案無 hash 字樣" "$OLD_FORMAT_TEXT" ;;
  *) pass "49b 通用 deny 文案不再提文件 hash" ;;
esac

echo
SAVED_HOOK=$HOOK
HOOK=$MALFORMED_ALLOW_HOOK
ORACLE_ALLOW_RESULT=$(
  PASSES=0
  FAILURES=0
  check "oracle expected-allow malformed stdout" \
    0 0 allow "oracle_allow" \
    "routed-judge" "oracle" "" "" "$PLAIN_TRANSCRIPT" >/dev/null
  printf '%s:%s' "$PASSES" "$FAILURES"
)
if [ "$ORACLE_ALLOW_RESULT" = "0:1" ]; then
  pass "malformed stdout cannot pass expected-allow check"
else
  fail "malformed stdout cannot pass expected-allow check" "0:1" "$ORACLE_ALLOW_RESULT"
fi
HOOK=$MALFORMED_MECH_HOOK
ORACLE_MECH_RESULT=$(
  PASSES=0
  FAILURES=0
  check_mech "oracle mech expected-allow malformed stdout" \
    0 pass-e1 "mech_opt_in_ok" "<mech-ok>" \
    "routed-mech" "oracle" "<mech-ok> oracle" "" "$PLAIN_TRANSCRIPT" >/dev/null
  printf '%s:%s' "$PASSES" "$FAILURES"
)
if [ "$ORACLE_MECH_RESULT" = "0:1" ]; then
  pass "malformed stdout cannot pass mech expected-allow check"
else
  fail "malformed stdout cannot pass mech expected-allow check" "0:1" "$ORACLE_MECH_RESULT"
fi
HOOK=$SAVED_HOOK

echo
printf '總計: \033[32m%d passed\033[0m' "$PASSES"
[ "$FAILURES" -gt 0 ] && printf ', \033[31m%d failed\033[0m' "$FAILURES"
echo
echo
[ "$FAILURES" -eq 0 ] || exit 1
