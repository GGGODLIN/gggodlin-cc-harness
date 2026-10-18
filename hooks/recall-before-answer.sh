#!/bin/bash
# Threat model：提示型 UserPromptSubmit hook，只防誠實但健忘的模型，不防主動規避。
# 字串比對只認常見入口，不承諾完整語意；判不出來就放行。模型可忽略 additionalContext，這不由本 hook 保證。
# Surface：Locked＝本 hook 與 fixture；Editable＝本次工作區草稿；Append-only＝無，本 hook 不寫 audit ledger；Human-controlled＝兩個 disabled sentinel。
# Locked 路徑：bootstrap 走一般 commit；update 改 hook/fixture 後跑 fixture；recovery 由使用者建立對應 disabled sentinel，三條路徑都留下 git 或測試痕跡。
# 繞行表：未收錄的自然語句由漏抓率腳本觀察；模型忽略提醒由人工副 KPI 觀察；英文同義句不在涵蓋範圍；通知、slash command 與長文依守衛放行。
# 精度取捨：`看一下`／`先確認` 曾在詞表內，因精度僅 25%／37.5%（占誤觸 64%）移除——兩者是向前的祈使動詞、不指涉過去；
# 代價是失去 4 個真命中（其中 2 個屬邊界案例），由 `之前`／`當初` 等新詞覆蓋大部分。`好像有點` 為「有點」固定詞組，
# 在比對前以參數展開剝除，不讓它被 `好像有` 誤命中；剝除只作用於比對用的副本，不改注入輸出。
# 2026-09-16 第三輪：補 7 個在 1,022 筆非命中訊息中誤觸為 0 的詞（看過／過去／跑過／一開始／當時／翻翻／有沒有做），
# 並把 RECALL_STRIP_PHRASES 擴成清單——`做過濾`／`檢查一下`／`調查一下`／`用過幾`／`所以`／`那之前` 都是跨詞邊界或
# 固定詞組造成的誤命中（做+過濾、檢+查一下、調+查一下、用過+幾個、所以+前X、在那+之前），與 `好像有點` 同類。
# 剝 `所以` 而非 `所以前`：後者會把「所以前幾天」吃成「幾天」、連帶弄丟 `前幾天` 這個真觸發詞。
# 觀察窗內未處理：`派出之前` 這種「動詞＋之前」的時序副詞（ERE 無 lookbehind，兩筆樣本不足以歸納通用形狀）。
# 本檔在契約測試底下：bash ~/.claude/hooks/recall-before-answer.test.sh
set -uo pipefail

INPUT=$(cat)
PROMPT=$(printf '%s' "$INPUT" | jq -r 'if (.prompt? | type) == "string" then .prompt else "" end' 2>/dev/null) || exit 0
SESSION_ID=$(printf '%s' "$INPUT" | jq -r 'if (.session_id? | type) == "string" then .session_id else "" end' 2>/dev/null) || exit 0
SOURCE=$(printf '%s' "$INPUT" | jq -r 'if (.source? | type) == "string" then .source else "" end' 2>/dev/null) || exit 0
PROMPT_SOURCE=$(printf '%s' "$INPUT" | jq -r 'if (.promptSource? | type) == "string" then .promptSource elif (.prompt_source? | type) == "string" then .prompt_source else "" end' 2>/dev/null) || exit 0
ORIGIN_KIND=$(printf '%s' "$INPUT" | jq -r 'if (.origin.kind? | type) == "string" then .origin.kind else "" end' 2>/dev/null) || exit 0
COMMAND_NAME=$(printf '%s' "$INPUT" | jq -r 'if (.command_name? | type) == "string" then .command_name elif (.commandName? | type) == "string" then .commandName else "" end' 2>/dev/null) || exit 0

case "$PROMPT" in
  /*|*"[SYSTEM NOTIFICATION"*|*"<task-notification>"*|*"<system-reminder>"*|*"<command-name>"*) exit 0 ;;
esac
case "$SOURCE" in
  command|command-name|slash|system|task-notification|peer) exit 0 ;;
esac
case "$PROMPT_SOURCE" in
  command|command-name|slash|system|task-notification|peer) exit 0 ;;
esac
case "$ORIGIN_KIND" in
  command|command-name|slash|system|task-notification|peer) exit 0 ;;
esac
[ -n "$COMMAND_NAME" ] && exit 0

STATE_DIR="${RECALL_BEFORE_ANSWER_STATE_DIR:-$HOME/.claude/hooks/state}"
RECALL_DISABLED="${RECALL_BEFORE_ANSWER_DISABLED_SENTINEL:-$STATE_DIR/recall-before-answer.disabled}"
INTERVIEW_DISABLED="${INTERVIEW_MODE_DISABLED_SENTINEL:-$STATE_DIR/interview-hook.disabled}"
RECALL_PATTERN='我記得|之前|上次|上一輪|翻一下|翻出|翻翻|查一下|重撈|撈到|撈過|好像有|應該有|處理過|做過|試過|測過|評估過|研究過|討論過|問過|裝過|用過|看過|跑過|有沒有做|眼熟|研究紀錄|自創|不是有|當初|當年|當時|原本|印象|以前|先前|過去|一開始|那次|那時|昨天|前幾天'
RECALL_STRIP_PHRASES='好像有點 做過濾 檢查一下 調查一下 用過幾 所以 那之前'
INTERVIEW_ENTER_PATTERN='訪談|一題一題|一項一項|訪談式'
INTERVIEW_ENTER_NEGATION_PATTERN='不要進入訪談模式|不要訪談'
INTERVIEW_EXIT_PATTERN='停(([[:space:][:punct:]]|[，。！？、；：…～~]|啊|呀|啦|喔|哦|吧|嘛|呢|一下)*)($|[[:space:][:punct:]，。！？、；：…～~])|不用訪談|一次問完'

RECALL_ENABLED=1
INTERVIEW_ENABLED=1
[ -f "$RECALL_DISABLED" ] && RECALL_ENABLED=0
[ -f "$INTERVIEW_DISABLED" ] && INTERVIEW_ENABLED=0

SAFE_SESSION_ID="$SESSION_ID"
case "$SAFE_SESSION_ID" in
  "") ;;
  *[!A-Za-z0-9._-]*) SAFE_SESSION_ID=$(printf '%s' "$SAFE_SESSION_ID" | LC_ALL=C tr -c 'A-Za-z0-9._-' '_') ;;
esac
INTERVIEW_SENTINEL=""
if [ -n "$SAFE_SESSION_ID" ]; then
  INTERVIEW_SENTINEL="$STATE_DIR/interview-mode-${SAFE_SESSION_ID}"
fi

if [ "$INTERVIEW_ENABLED" -eq 1 ] && printf '%s' "$PROMPT" | grep -qE "$INTERVIEW_EXIT_PATTERN"; then
  [ -z "$INTERVIEW_SENTINEL" ] || rm -f "$INTERVIEW_SENTINEL" 2>/dev/null || true
  exit 0
fi

[ "${#PROMPT}" -gt 300 ] && exit 0

INTERVIEW_ACTIVE=0
if [ "$INTERVIEW_ENABLED" -eq 1 ] && [ -n "$INTERVIEW_SENTINEL" ] && [ -f "$INTERVIEW_SENTINEL" ]; then
  INTERVIEW_ACTIVE=1
fi
if [ "$INTERVIEW_ENABLED" -eq 1 ] && [ -n "$INTERVIEW_SENTINEL" ] && ! (printf '%s' "$PROMPT" | grep -qE "$INTERVIEW_ENTER_NEGATION_PATTERN") && printf '%s' "$PROMPT" | grep -qE "$INTERVIEW_ENTER_PATTERN"; then
  if mkdir -p "$STATE_DIR" 2>/dev/null && touch "$INTERVIEW_SENTINEL" 2>/dev/null; then
    INTERVIEW_ACTIVE=1
  fi
fi

CONTEXT=""
if [ "$INTERVIEW_ACTIVE" -eq 1 ]; then
  CONTEXT='訪談模式：一次只問一題、附來龍去脈與建議答案、等答案再問下一題、不代答'
fi

if [ "$RECALL_ENABLED" -eq 1 ]; then
  RECALL_SCAN=$PROMPT
  for strip_phrase in $RECALL_STRIP_PHRASES; do
    RECALL_SCAN=${RECALL_SCAN//$strip_phrase/}
  done
  HIT=$(printf '%s' "$RECALL_SCAN" | grep -oE "$RECALL_PATTERN" | head -n 1 || true)
  if [ -n "$HIT" ]; then
    RECALL_CONTEXT="使用者在指涉過去的工作：回答前先翻 session 紀錄／git／memory，找到或確認不存在才下判斷；憑印象回＝違規（命中：${HIT}）"
    if [ -n "$CONTEXT" ]; then
      CONTEXT="${CONTEXT}
${RECALL_CONTEXT}"
    else
      CONTEXT="$RECALL_CONTEXT"
    fi
  fi
fi

[ -z "$CONTEXT" ] && exit 0
jq -cn --arg ctx "$CONTEXT" '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$ctx}}'
exit 0
