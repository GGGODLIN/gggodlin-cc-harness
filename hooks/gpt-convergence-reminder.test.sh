#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SCRIPT="${GPT_CONVERGENCE_HOOK:-$SCRIPT_DIR/gpt-convergence-reminder.sh}"
FIX=$(mktemp -d)
CACHE_FILE=""
trap 'rm -rf "$FIX"; [ -z "${CACHE_FILE:-}" ] || rm -f "$CACHE_FILE"' EXIT
PASS=0
FAIL=0
POLICY_FILE="$FIX/AGENTS.md"
printf '%s\n' \
  '<!-- SHARED-AGENT-CONVERGENCE:START -->' \
  '## Shared agent convergence' \
  '' \
  '- SHARED_SSOT_TEST_MARKER' \
  '- A stale marker used only for workflow bookkeeping must not cause completed work to be redone.' \
  '- Replay only when an actual dependency version, content, configuration, or resolution result changed.' \
  '- Never skip an execution receipt carrying command, input, result, and expectation, or integrity hash, checksum, signature, or revision identity.' \
  '<!-- SHARED-AGENT-CONVERGENCE:END -->' > "$POLICY_FILE"
export GPT_CONVERGENCE_POLICY="$POLICY_FILE"

check_fire() {
  local label=$1
  local input=$2
  local event=$3
  local vendor=${4:-}
  local output
  local status
  output=$(printf '%s' "$input" | HOME="$FIX" CC_HOST=claude-code CC_VENDOR="$vendor" bash "$SCRIPT")
  status=$?
  if [ "$status" -eq 0 ] && printf '%s' "$output" | jq -e --arg event "$event" '.hookSpecificOutput.hookEventName == $event and (.hookSpecificOutput.additionalContext | contains("以下只適用於當前主模型為 GPT 的 session") and contains("沿既有工具與派工入口，完成原始要求") and contains("指出原始需求、具體故障或既有契約") and contains("確認既有框架是否已處理") and contains("自己新寫的測試、文件與票不能反過來證成需求") and contains("驗收與必要收尾達標後交付") and contains("重驗要有新改動、實際失敗或尚未解決的驗收缺口") and contains("自我 review 維持只修 P0／CRITICAL") and contains("已證實的核心功能、輸出或驗收缺陷") and contains("修後只驗受影響部分") and contains("其他改善回報一次") and contains("授權與安全確認沿用既有規則") and contains("SHARED_SSOT_TEST_MARKER") and contains("workflow bookkeeping") and contains("actual dependency version, content, configuration, or resolution result changed") and contains("command, input, result, and expectation") and contains("integrity hash, checksum, signature, or revision identity") and contains("task-notification") and contains("不要用 TaskOutput block=true 站著等結果") and contains("ListAgents") and contains("date／true／sleep") and contains("進度回報不是停點") and contains("本條不增加授權") and contains("不得用輪詢、空轉或重做已完成工作代替進展") and contains("不要因為一個小錯改走另一條執行路徑") and contains("有 LCU 或 iPhone 鏡像可操作的 GUI 由 agent 自行操作驗證、不推回使用者") and contains("對使用者的溝通寫法") and contains("直接回答使用者實際提出的問題") and contains("需要糾正時，指出對應原句；對比必須有真實對象") and contains("進度只報新增結果、必要阻塞與下一步") and contains("同一限制集中說一次，條件改變時才更新") and contains("用修正結果回應糾正") and contains("首次提機制，用白話說它做什麼") and contains("改變方向時交代原同意事項與新證據") and contains("不改任何既有的查證"))' >/dev/null 2>&1; then
    printf 'PASS %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL %s: %s\n' "$label" "$output"
    FAIL=$((FAIL + 1))
  fi
}

check_silent() {
  local label=$1
  local input=$2
  local vendor=${3:-}
  local output
  local status
  output=$(printf '%s' "$input" | HOME="$FIX" CC_VENDOR="$vendor" bash "$SCRIPT")
  status=$?
  if [ "$status" -eq 0 ] && [ -z "$output" ]; then
    printf 'PASS %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL %s: %s\n' "$label" "$output"
    FAIL=$((FAIL + 1))
  fi
}

check_harness_only() {
  local label=$1
  local policy=$2
  local output
  local status
  output=$(printf '%s' '{"hook_event_name":"SessionStart","session_id":"harness-only","model":"gpt-5.6-sol","source":"startup"}' | HOME="$FIX" CC_HOST=claude-code GPT_CONVERGENCE_POLICY="$policy" bash "$SCRIPT")
  status=$?
  if [ "$status" -eq 0 ] && printf '%s' "$output" | jq -e '.hookSpecificOutput.hookEventName == "SessionStart" and (.hookSpecificOutput.additionalContext | contains("自我 review 維持只修 P0／CRITICAL") and contains("task-notification") and contains("進度回報不是停點") and contains("對使用者的溝通寫法") and (contains("SHARED_SSOT_TEST_MARKER") | not))' >/dev/null 2>&1; then
    printf 'PASS %s\n' "$label"
    PASS=$((PASS + 1))
  else
    printf 'FAIL %s: %s\n' "$label" "$output"
    FAIL=$((FAIL + 1))
  fi
}

check_host_contracts() {
  local input='{"hook_event_name":"SessionStart","session_id":"host-contract","model":"gpt-5.6-sol","source":"startup"}'
  local codex_output
  local cc_output
  local unknown_output
  codex_output=$(printf '%s' "$input" | HOME="$FIX" CC_HOST=codex bash "$SCRIPT")
  cc_output=$(printf '%s' "$input" | HOME="$FIX" CC_HOST=claude-code bash "$SCRIPT")
  unknown_output=$(printf '%s' "$input" | HOME="$FIX" CC_HOST=future-host bash "$SCRIPT")

  if printf '%s' "$codex_output" | jq -e '.hookSpecificOutput.additionalContext | contains("wait_agent") and contains("active turn") and contains("收到結果後立即整合") and contains("單次 timeout") and (contains("直接結束這一輪，通知到了 harness 會自動叫醒你") | not)' >/dev/null 2>&1; then
    printf 'PASS codex-host uses native wait contract\n'
    PASS=$((PASS + 1))
  else
    printf 'FAIL codex-host uses native wait contract: %s\n' "$codex_output"
    FAIL=$((FAIL + 1))
  fi

  if printf '%s' "$cc_output" | jq -e '.hookSpecificOutput.additionalContext | contains("不要用 TaskOutput block=true 站著等結果") and contains("直接結束這一輪，通知到了 harness 會自動叫醒你")' >/dev/null 2>&1; then
    printf 'PASS claude-code-host keeps background notification contract\n'
    PASS=$((PASS + 1))
  else
    printf 'FAIL claude-code-host keeps background notification contract: %s\n' "$cc_output"
    FAIL=$((FAIL + 1))
  fi

  if printf '%s' "$unknown_output" | jq -e '.hookSpecificOutput.additionalContext | contains("宿主未識別") and contains("不得假定 Codex 的完成通知會自動開啟新 turn") and (contains("通知到了 harness 會自動叫醒你") | not)' >/dev/null 2>&1; then
    printf 'PASS unknown-host does not assume codex auto-wake\n'
    PASS=$((PASS + 1))
  else
    printf 'FAIL unknown-host does not assume codex auto-wake: %s\n' "$unknown_output"
    FAIL=$((FAIL + 1))
  fi
}

NO_MARKER_POLICY="$FIX/no-marker.md"
DUPLICATE_POLICY="$FIX/duplicate-marker.md"
REVERSED_POLICY="$FIX/reversed-marker.md"
printf '%s\n' '## Shared agent convergence' '- no marker' > "$NO_MARKER_POLICY"
printf '%s\n' '<!-- SHARED-AGENT-CONVERGENCE:START -->' '<!-- SHARED-AGENT-CONVERGENCE:START -->' '- duplicate' '<!-- SHARED-AGENT-CONVERGENCE:END -->' > "$DUPLICATE_POLICY"
printf '%s\n' '<!-- SHARED-AGENT-CONVERGENCE:END -->' '- reversed' '<!-- SHARED-AGENT-CONVERGENCE:START -->' > "$REVERSED_POLICY"

check_harness_only missing-policy "$FIX/missing.md"
check_harness_only missing-marker "$NO_MARKER_POLICY"
check_harness_only duplicate-marker "$DUPLICATE_POLICY"
check_harness_only reversed-marker "$REVERSED_POLICY"
check_host_contracts

check_fire session-start-gpt '{"hook_event_name":"SessionStart","session_id":"gpt-start","model":"gpt-5.6-sol","source":"startup"}' SessionStart
check_fire session-resume-gpt '{"hook_event_name":"SessionStart","session_id":"gpt-resume","model":"gpt-5.6-sol","source":"resume"}' SessionStart
check_fire session-clear-gpt '{"hook_event_name":"SessionStart","session_id":"gpt-clear","model":"gpt-5.6-sol","source":"clear"}' SessionStart
check_fire session-compact-gpt '{"hook_event_name":"SessionStart","session_id":"gpt-compact-start","model":"gpt-5.6-sol","source":"compact"}' SessionStart
check_fire session-start-gpt-6-sol '{"hook_event_name":"SessionStart","session_id":"gpt-6-sol-start","model":"gpt-6-sol","source":"startup"}' SessionStart
check_fire session-start-gpt-6-astra '{"hook_event_name":"SessionStart","session_id":"gpt-6-astra-start","model":"gpt-6-astra","source":"startup"}' SessionStart
check_fire session-start-gpt-6-1-sol '{"hook_event_name":"SessionStart","session_id":"gpt-6-1-sol-start","model":"gpt-6.1-sol","source":"startup"}' SessionStart
check_silent gemini-session-vendor-conflict '{"hook_event_name":"SessionStart","session_id":"gemini-vendor-conflict","model":"gemini-4-argon","source":"startup"}' gpt
check_silent unsupported-event '{"hook_event_name":"PreToolUse","session_id":"gpt-tool-event","model":"gpt-6-astra","source":"startup"}' gpt
check_silent unsupported-source '{"hook_event_name":"SessionStart","session_id":"gpt-other-source","model":"gpt-6-astra","source":"other"}' gpt
VENDOR_OUTPUT=$(printf '%s' '{"hook_event_name":"SessionStart","session_id":"gpt-vendor","source":"startup"}' | HOME="$FIX" CC_HOST=claude-code CC_VENDOR="gpt" bash "$SCRIPT")
if printf '%s' "$VENDOR_OUTPUT" | jq -e '.hookSpecificOutput.hookEventName == "SessionStart" and (.hookSpecificOutput.additionalContext | contains("自我 review 維持只修 P0／CRITICAL") and contains("已證實的核心功能、輸出或驗收缺陷") and contains("SHARED_SSOT_TEST_MARKER") and contains("workflow bookkeeping") and contains("actual dependency version, content, configuration, or resolution result changed") and contains("command, input, result, and expectation") and contains("integrity hash, checksum, signature, or revision identity") and contains("task-notification") and contains("進度回報不是停點") and contains("本條不增加授權") and contains("不要因為一個小錯改走另一條執行路徑"))' >/dev/null 2>&1; then
  printf 'PASS session-start-vendor-fallback\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL session-start-vendor-fallback: %s\n' "$VENDOR_OUTPUT"
  FAIL=$((FAIL + 1))
fi
check_silent claude-session '{"hook_event_name":"SessionStart","session_id":"claude-start","model":"claude-opus-5","source":"startup"}'
check_silent claude-opus-5-5-session '{"hook_event_name":"SessionStart","session_id":"claude-opus-5-5-start","model":"claude-opus-5-5","source":"startup"}'
check_silent claude-session-vendor-conflict '{"hook_event_name":"SessionStart","session_id":"claude-vendor-conflict","model":"claude-opus-5","source":"startup"}' gpt
check_fire gpt-session-vendor-conflict '{"hook_event_name":"SessionStart","session_id":"gpt-vendor-conflict","model":"gpt-5.6-sol","source":"startup"}' SessionStart claude
check_silent missing-model '{"hook_event_name":"SessionStart","session_id":"unknown","source":"compact"}'
check_silent subagent-gpt '{"hook_event_name":"SessionStart","session_id":"subagent","model":"gpt-5.6-sol","agent_type":"routed-impl","source":"startup"}'
check_silent subagent-gpt-6 '{"hook_event_name":"SessionStart","session_id":"subagent-gpt-6","model":"gpt-6-sol","agent_type":"routed-impl","source":"startup"}'

printf '%s\n' '{"type":"assistant","message":{"id":"resp_fixture","type":"message","role":"assistant","model":"gpt-5.6-sol"}}' > "$FIX/gpt.jsonl"
check_fire session-compact-transcript "{\"hook_event_name\":\"SessionStart\",\"session_id\":\"gpt-compact\",\"transcript_path\":\"$FIX/gpt.jsonl\",\"source\":\"compact\"}" SessionStart

printf '%s\n' '{"type":"assistant","message":{"id":"resp_nested","type":"message","role":"assistant","content":[{"type":"text","text":"fixture with } before model"},{"type":"tool_use","input":{"nested":{"value":"x"}}}],"model":"gpt-5.6-sol"}}' > "$FIX/gpt-nested.jsonl"
check_fire session-compact-transcript-nested "{\"hook_event_name\":\"SessionStart\",\"session_id\":\"gpt-compact-nested\",\"transcript_path\":\"$FIX/gpt-nested.jsonl\",\"source\":\"compact\"}" SessionStart

export CC_WIDGET_CACHE_DIR="$FIX/widget-cache"
mkdir -p "$CC_WIDGET_CACHE_DIR"
CACHE_SID="gpt-convergence-conflict-$$"
CACHE_FILE="$CC_WIDGET_CACHE_DIR/model-${CACHE_SID}.txt"
printf '%s\n' 'gpt-5.6-sol' > "$CACHE_FILE"
check_silent session-input-claude-over-stale-gpt "{\"hook_event_name\":\"SessionStart\",\"session_id\":\"$CACHE_SID\",\"model\":\"claude-opus-5\",\"source\":\"startup\"}" gpt
printf '%s\n' '{"type":"assistant","message":{"id":"resp_claude","type":"message","role":"assistant","model":"claude-opus-5"}}' > "$FIX/claude.jsonl"
cp "$FIX/claude.jsonl" "$FIX/claude-long.jsonl"
i=0
while [ "$i" -lt 200 ]; do
  printf '%s\n' '{"type":"user","message":{"role":"user","content":"padding"}}' >> "$FIX/claude-long.jsonl"
  i=$((i + 1))
done
check_silent session-transcript-claude-before-tail-window "{\"hook_event_name\":\"SessionStart\",\"session_id\":\"$CACHE_SID\",\"transcript_path\":\"$FIX/claude-long.jsonl\",\"source\":\"compact\"}" gpt
check_silent session-transcript-claude-over-stale-gpt "{\"hook_event_name\":\"SessionStart\",\"session_id\":\"$CACHE_SID\",\"transcript_path\":\"$FIX/claude.jsonl\",\"source\":\"compact\"}" gpt
printf '%s\n' 'claude-opus-5' > "$CACHE_FILE"
check_fire session-transcript-gpt-over-stale-claude "{\"hook_event_name\":\"SessionStart\",\"session_id\":\"$CACHE_SID\",\"transcript_path\":\"$FIX/gpt.jsonl\",\"source\":\"compact\"}" SessionStart claude

STATIC_SHARED=0
for phrase in \
  'workflow bookkeeping' \
  '只用於流程 bookkeeping' \
  '不得當成重做已完成工作的理由' \
  'execution receipt' \
  'integrity hash'; do
  grep -Fq "$phrase" "$SCRIPT" && STATIC_SHARED=1
done
if grep -Fq 'GPT_CONVERGENCE_POLICY' "$SCRIPT" && [ "$STATIC_SHARED" -eq 0 ]; then
  printf 'PASS hook reads policy without embedding shared content\n'
  PASS=$((PASS + 1))
else
  printf 'FAIL hook reads policy without embedding shared content\n'
  FAIL=$((FAIL + 1))
fi

if [ "$FAIL" -ne 0 ]; then
  printf '%s passed, %s failed\n' "$PASS" "$FAIL"
  exit 1
fi

printf '%s passed, 0 failed\n' "$PASS"
