#!/usr/bin/env bash
# T1 warning check — SessionStart handler
# 把今天的 T1 hook warning surface 到 main session (僅當有今日 warning)
set -uo pipefail

WARN_LOG="${T1_WARN_LOG:-$HOME/.claude/hooks/T1-claim-detect.warnings.log}"

if [[ ! -f "$WARN_LOG" ]]; then
  exit 0
fi

TODAY=$(date +%Y-%m-%d)
TODAY_WARNINGS=$(grep "^$TODAY" "$WARN_LOG" 2>/dev/null)

if [[ -z "$TODAY_WARNINGS" ]]; then
  exit 0
fi

# Summarize by type
L1_QUOTA=$(echo "$TODAY_WARNINGS" | grep -c "L1.*429 quota" || true)
L1_NO_RESPONSE=$(echo "$TODAY_WARNINGS" | command grep -c "L1 http=000" || true)
L1_HTTP=$(echo "$TODAY_WARNINGS" | command grep -cE "L1 http=[1-5][0-9]{2}" || true)
L3_FALLBACK=$(echo "$TODAY_WARNINGS" | command grep -cF "L1 failed, trying L3" || true)
ALL_FAIL=$(echo "$TODAY_WARNINGS" | command grep -cF "L1+L3 failed" || true)
NOKEY=$(echo "$TODAY_WARNINGS" | grep -c "CLIPROXY_KEY_CC unset" || true)

PARTS=()
[[ "$L1_QUOTA" -gt 0 ]] && PARTS+=("L1 (Groq 27B via relay) 撞限 $L1_QUOTA 次")
[[ "$L1_NO_RESPONSE" -gt 0 ]] && PARTS+=("L1 未收到 HTTP 回應（http=000）${L1_NO_RESPONSE} 次")
[[ "$L1_HTTP" -gt 0 ]] && PARTS+=("L1 HTTP 錯誤回應 ${L1_HTTP} 次")
[[ "$L3_FALLBACK" -gt 0 ]] && PARTS+=("改由 Jev 備援 ${L3_FALLBACK} 次")
[[ "$ALL_FAIL" -gt 0 ]] && PARTS+=("Groq 與 Jev 皆失敗 ${ALL_FAIL} 次（該回合無提醒）")
[[ "$NOKEY" -gt 0 ]] && PARTS+=("CLIPROXY_KEY_CC unset $NOKEY 次")

if [[ ${#PARTS[@]} -eq 0 ]]; then
  exit 0
fi

# Inline join with comma
SUMMARY=$(printf "; %s" "${PARTS[@]}")
SUMMARY="${SUMMARY:2}"

# ${VAR} 大括號必須保留：bash 3.2 對「$VAR 後直接接全形字元」會把多位元組併進變數名（set -u 下炸 unbound）
MESSAGE="📊 T1 hook 今日警告（${TODAY}）: ${SUMMARY}。詳細見 ~/.claude/hooks/T1-claim-detect.warnings.log。L1（Groq）失敗時改由 L3（Jev）判定；兩者皆失敗時，該回合無提醒。"

# 2026-08-17 systemmessage-hook-conversion：純 FYI 改走 systemMessage（不進 Claude context）
jq -nc --arg msg "$MESSAGE" '{systemMessage: $msg}'
