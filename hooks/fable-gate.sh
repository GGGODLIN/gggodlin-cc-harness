#!/bin/bash
# fable-gate: session 當前 model 含 "fable" 時 skip 被包的 heavy hook（deny/nudge 型對 fable 暫停）
# 例外（2026-07-20 routing 政策）：T2-routing-gate 不 bypass、改帶 CC_FABLE_MAIN=1 執行——
#   Fable main 正是 T2 要攔「未指定 model 默默繼承 Fable」的場景
# 用法（settings.json command）: ~/.claude/hooks/fable-gate.sh <原 hook 路徑> [args...]
# 恢復方式：settings.json 把 fable-gate.sh 前綴拿掉即可，hook 本體未動
INPUT="$(cat)"
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
MODEL=""
T2_HOOK=${FABLE_GATE_T2_HOOK_PATH:-/Users/you/.claude/hooks/T2-routing-gate.sh}
# 主：statusline wrapper 落的 per-session cache（跟 statusline model pill 同源、每次 render 刷新）
if [ -n "$SID" ] && [ -f "/tmp/cc-widget-cache/model-${SID}.txt" ]; then
  MODEL=$(cat "/tmp/cc-widget-cache/model-${SID}.txt" 2>/dev/null)
fi
# 備：headless / cron 無 statusline 時 fallback transcript；錨定 message-level model
# （避免抓到 Agent tool 參數的 "model":"sonnet"，2026-07-03 T1 誤 fire 根因）
if [ -z "$MODEL" ]; then
  TP=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
  if [ -n "$TP" ] && [ -f "$TP" ]; then
    MODEL=$(tail -c 200000 "$TP" | grep -o '"message":{"model":"[^"]*"' | tail -1)
  fi
fi
case "$MODEL" in
  *[Ff]able*)
    if [ "${1:-}" = "$T2_HOOK" ]; then
      export CC_FABLE_MAIN=1
      printf '%s' "$INPUT" | "$@"
      exit $?
    fi
    exit 0
    ;;
esac
printf '%s' "$INPUT" | "$@"
exit $?
