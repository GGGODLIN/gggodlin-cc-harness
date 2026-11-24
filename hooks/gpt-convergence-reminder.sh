#!/usr/bin/env bash
# 本檔在契約測試底下：bash ~/.claude/hooks/gpt-convergence-reminder.test.sh
# gpt-convergence-reminder.sh — SessionStart(startup|resume|clear|compact)
# 提示型 hook：只注入文字、不擋任何事，判不出來就靜默 exit 0（fail-open 是正確方向）。
# Threat model：防誠實 agent 套錯宿主等待契約；不保證 runtime 排程或通知傳輸，
# 也不保證斷網、配額不足或裝置睡眠時仍能接續。
# Shared convergence 由 ~/.codex/AGENTS.md 的 marker block 提供；缺檔、空白或 marker
# 不完整時只保留 GPT-specific 與 Claude Code harness 規則，不阻擋 SessionStart。
# 注入內容進 conversation layer，會被 compact 壓掉——所以 source 白名單含 compact，
# 每次壓縮後重新補打。外部啟動器另帶 harness 規則；本 hook 補 shared
# convergence，並涵蓋 launcher 啟動與中途切到 GPT 後的下一次 compact／resume。
set -uo pipefail

INPUT=$(cat)
EVENT=$(printf '%s' "$INPUT" | jq -r '.hook_event_name // empty' 2>/dev/null)
SOURCE=$(printf '%s' "$INPUT" | jq -r '.source // empty' 2>/dev/null)
AGENT_TYPE=$(printf '%s' "$INPUT" | jq -r '.agent_type // empty' 2>/dev/null)
[ -n "$AGENT_TYPE" ] && exit 0

case "$EVENT" in
  SessionStart)
    case "$SOURCE" in
      startup|resume|clear|compact) ;;
      *) exit 0 ;;
    esac
    ;;
  *) exit 0 ;;
esac

MODEL=$(printf '%s' "$INPUT" | jq -r '.model // empty' 2>/dev/null)
SID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null)
TP=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)

if [ -z "$MODEL" ] && [ -n "$TP" ] && [ -f "$TP" ]; then
  MODEL=$(jq -r 'select(.type == "assistant") | .message.model // empty' "$TP" 2>/dev/null | tail -1 || true)
fi

if [ -z "$MODEL" ] && [ -n "$SID" ] && [ -f "${CC_WIDGET_CACHE_DIR:-/tmp/cc-widget-cache}/model-${SID}.txt" ]; then
  MODEL=$(<"${CC_WIDGET_CACHE_DIR:-/tmp/cc-widget-cache}/model-${SID}.txt")
fi

[ -n "$MODEL" ] || MODEL="${CC_VENDOR:-}"

case "$MODEL" in
  *[Gg][Pp][Tt]*) ;;
  *) exit 0 ;;
esac

MSG_GPT='以下只適用於當前主模型為 GPT 的 session。GPT 實作收斂：沿既有工具與派工入口，完成原始要求。新增 retry、fallback、驗證器、狀態或抽象層前，指出原始需求、具體故障或既有契約，並確認既有框架是否已處理。自己新寫的測試、文件與票不能反過來證成需求。驗收與必要收尾達標後交付。重驗要有新改動、實際失敗或尚未解決的驗收缺口。自我 review 維持只修 P0／CRITICAL，以及已證實的核心功能、輸出或驗收缺陷；修後只驗受影響部分。其他改善回報一次。授權與安全確認沿用既有規則。'
POLICY_PATH="${GPT_CONVERGENCE_POLICY:-$HOME/.codex/AGENTS.md}"
SHARED_START='<!-- SHARED-AGENT-CONVERGENCE:START -->'
SHARED_END='<!-- SHARED-AGENT-CONVERGENCE:END -->'
MSG_SHARED=""

if [ -f "$POLICY_PATH" ]; then
  START_COUNT=$(grep -Fxc "$SHARED_START" "$POLICY_PATH" 2>/dev/null || true)
  END_COUNT=$(grep -Fxc "$SHARED_END" "$POLICY_PATH" 2>/dev/null || true)
  if [ "$START_COUNT" = "1" ] && [ "$END_COUNT" = "1" ]; then
    MSG_SHARED=$(awk -v start="$SHARED_START" -v finish="$SHARED_END" '
      $0 == start {
        if (seen_start || seen_end) exit 2
        seen_start = 1
        inside = 1
        next
      }
      $0 == finish {
        if (!inside || seen_end) exit 2
        seen_end = 1
        inside = 0
        next
      }
      inside { print }
      END {
        if (seen_start != 1 || seen_end != 1 || inside) exit 2
      }
    ' "$POLICY_PATH" 2>/dev/null) || MSG_SHARED=""
  fi
fi

MSG_CONVERGE="$MSG_GPT"
[ -z "$MSG_SHARED" ] || MSG_CONVERGE="${MSG_CONVERGE}"$'\n\n'"${MSG_SHARED}"

case "${CC_HOST:-claude-code}" in
  codex)
    MSG_HARNESS_HOST='Codex 原生 collaboration：派工後先做下一件不相依工作，不用 ListAgents 或 date／true／sleep 輪詢。若仍有已批准、必要的子工作 pending，main 的下一步被結果阻塞，且沒有其他工作可做，就不要 final；留在 active turn 用 wait_agent 等待完成。收到結果後立即整合結果並接著做下一個必要步驟。單次 timeout 只代表這次有界等待結束，不代表子工作完成或取消，也不是必須 final 的理由；子工作仍必要且無其他工作時，繼續用 wait_agent 有界等待。不能因等 child 就先 final 並假定完成通知會自動開啟新 turn。'
    ;;
  claude|claude-code|cc)
    MSG_HARNESS_HOST='Agent 與背景 Bash 完成時，harness 會自動送 task-notification 回來喚醒 session，不需要你主動確認。派工後直接進行下一件不相依的工作，不要用 TaskOutput block=true 站著等結果。只有在沒有其他可做的事、且必須拿到該結果才能繼續時，才查一次；查完仍未完成就回去做別的，不要連續輪詢。反覆用 ListAgents 查狀態、或用 date／true／sleep 這類空指令耗時間等通知，也是輪詢，同樣不要做；等待期間沒有別的事可做時，直接結束這一輪，通知到了 harness 會自動叫醒你。'
    ;;
  *)
    MSG_HARNESS_HOST='宿主未識別：不得假定 Codex 的完成通知會自動開啟新 turn，也不得套用 Claude Code 的背景 task-notification 喚醒承諾。先依目前宿主可用的原生等待契約處理必要子工作；查明契約前，不因等待子工作就先 final。不要用 ListAgents 或 date／true／sleep 輪詢。'
    ;;
esac

MSG_HARNESS_COMMON='僅適用 GPT main session。已授權交付若有未被阻塞的必要下一步，直接推進；進度回報不是停點。本條不增加授權，不得用輪詢、空轉或重做已完成工作代替進展。撞錯先修根因：格式、參數、路徑等小錯若三行內可修就直接修，不要因為一個小錯改走另一條執行路徑；確需換路先說明根因何以不可修。人類專屬點交還上限：撞到只有使用者本人在場能做或能拍板的事（sudo／macOS 權限視窗或實體接線／互動式 auth／憑證設定／系統升級，或範圍・權威・對外行為・風險的拍板；有 LCU 或 iPhone 鏡像可操作的 GUI 由 agent 自行操作驗證、不推回使用者），同一點最多試 2 次即自包含交還（脈絡、選項後果、建議與理由各一句；能標「我假設 1…N」就續跑，否則收工）。'
MSG_HARNESS="背景工作等待規則：${MSG_HARNESS_HOST}${MSG_HARNESS_COMMON}"

# 只放 GPT：同一套 always-on 規則下不同模型的報告精簡度有落差，
# 寫進共用 command 或 output style 會連 Claude 一起改動。
MSG_COMM='對使用者的溝通寫法（僅適用當前 GPT main）：直接回答使用者實際提出的問題。需要糾正時，指出對應原句；對比必須有真實對象。進度只報新增結果、必要阻塞與下一步。同一限制集中說一次，條件改變時才更新。出錯時，簡述錯誤、修正與影響，接著處理問題；用修正結果回應糾正。首次提機制，用白話說它做什麼；改變方向時交代原同意事項與新證據。本段只管寫法，不改任何既有的查證、證據副檔或拍板要求。'

MSG="${MSG_CONVERGE}"$'\n\n'"${MSG_HARNESS}"$'\n\n'"${MSG_COMM}"

jq -cn --arg event "$EVENT" --arg ctx "$MSG" '{hookSpecificOutput:{hookEventName:$event,additionalContext:$ctx}}'
