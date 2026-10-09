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
L1_HTTP=$(echo "$TODAY_WARNINGS" | grep -c "L1 http=" || true)
ALL_FAIL=$(echo "$TODAY_WARNINGS" | grep -c "L1+L2 failed" || true)
NOKEY=$(echo "$TODAY_WARNINGS" | grep -c "CLIPROXY_KEY_CC unset" || true)

PARTS=()
[[ "$L1_QUOTA" -gt 0 ]] && PARTS+=("L1 (Groq 27B via relay) 撞限 $L1_QUOTA 次")
[[ "$L1_HTTP" -gt 0 ]] && PARTS+=("L1 非 200 回應 $L1_HTTP 次（413 過大 / relay 鏈異常）")
[[ "$ALL_FAIL" -gt 0 ]] && PARTS+=("**L1+L2 全 fail $ALL_FAIL 次** (本機 8B 也死)")
[[ "$NOKEY" -gt 0 ]] && PARTS+=("CLIPROXY_KEY_CC unset $NOKEY 次")

if [[ ${#PARTS[@]} -eq 0 ]]; then
  exit 0
fi

# Inline join with comma
SUMMARY=$(printf "; %s" "${PARTS[@]}")
SUMMARY="${SUMMARY:2}"

# ${VAR} 大括號必須保留：bash 3.2 對「$VAR 後直接接全形字元」會把多位元組併進變數名（set -u 下炸 unbound）
MESSAGE="📊 T1 hook 今日警告（${TODAY}）: ${SUMMARY}。詳細見 ~/.claude/hooks/T1-claim-detect.warnings.log。L1 掛 = 退本機 8B (recall 較低)、L1+L2 全掛 = 該回合無 nudge。"

# 2026-08-17 systemmessage-hook-conversion：純 FYI 改走 systemMessage（不進 Claude context）
jq -nc --arg msg "$MESSAGE" '{systemMessage: $msg}'
