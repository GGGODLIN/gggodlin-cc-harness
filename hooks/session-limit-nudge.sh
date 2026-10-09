#!/usr/bin/env bash
# PostToolUse(*) hook — 當前登入帳號 5h 用量 >= 95% 時注入一次「掛 session limit watcher」提醒。
# Hook 自己不能起 watcher（hook 起的背景程序沒有 exit→喚醒 session 的橋），
# 只負責偵測條件 + 注入指令讓 main session 自己 arm（同 workflow-monitor 的 hook 分工）。
# 低於門檻 / 已有 watcher / debounce 期內 → 完全靜默（exit 0 無輸出）。
set -uo pipefail

# Vendor-session bypass (2026-06-19): hook 推 /session-monitor 是針對 Anthropic OAuth
# 5h quota 設計、vendor session 燒的是 vendor 自家 quota（z.ai prompt cap / MiMo credit /
# DeepSeek PAYG balance）不是 Anthropic 5h，nudge 內容不適用。
# See [[feedback_hook_vendor_session_bypass_design]].
[ -n "${CC_VENDOR:-}" ] && exit 0

THRESHOLD=${SESSION_NUDGE_THRESHOLD:-95}
DEBOUNCE_SECONDS=${SESSION_NUDGE_DEBOUNCE:-600}
MARKER="$HOME/.claude/cache/session-limit-nudge.last"

# 帳號解析走 lib（兩段式：CLAUDE_CONFIG_DIR 優先、$HOME 退回）——只讀 $HOME 會在
# lock session（cc -max / cc -team）讀錯帳號，該提醒則會在錯的時間跳。詳見 lib 檔頭。
printf '%s\n' 'harness: wiring point "多帳號與帳號判定" is not provided in this public copy; see WIRING.md' >&2; exit 1
email=$(cc_resolve_account_email) || exit 0
f=$(cc_resolve_quota_file) || exit 0
[ -f "$f" ] || exit 0
u=$(jq -r '.data.five_hour.utilization // empty' "$f" 2>/dev/null)
[[ "$u" =~ ^[0-9]+$ ]] || exit 0
(( u >= THRESHOLD )) || exit 0

pgrep -f session-limit-watch.sh >/dev/null 2>&1 && exit 0

if [ -f "$MARKER" ]; then
  now=$(date +%s)
  m=$(stat -f %m "$MARKER" 2>/dev/null || echo 0)
  (( now - m < DEBOUNCE_SECONDS )) && exit 0
fi
touch "$MARKER"

resets=$(jq -r '.data.five_hour.resets_at // "n/a"' "$f" 2>/dev/null)
# 2026-08-17 systemmessage-hook-conversion 拆分：帳號／百分比／resets_at 是給使用者的狀態
# → systemMessage；Claude 只需要「過門檻＋該不該 arm」的靜態指令 → additionalContext
# （動態值全移出 context、prefix cache 全穩定）。PostToolUse 渲染當日經使用者親眼實證。
jq -cn --arg email "$email" --arg u "$u" --arg resets "$resets" '{
  systemMessage: ("⏳ 當前帳號（" + $email + "）5h 用量已達 " + $u + "%（resets_at " + $resets + "）——長時間自主工作建議讓 Claude 掛 /session-monitor watcher"),
  hookSpecificOutput: {
    hookEventName: "PostToolUse",
    additionalContext: "⏳ 帳號 5h 用量已過警戒門檻（具體數字已直接顯示給使用者）。若本 session 正在長時間自主工作（/goal、長 plan 執行、無人值守任務），invoke /session-monitor 的 arm 模式掛上額度恢復 watcher——額度歸零時它會喚醒你直接續跑。純互動式對話可忽略。"
  }
}'
