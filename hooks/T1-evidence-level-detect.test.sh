#!/usr/bin/env bash
# T1-evidence-level-detect.sh fixture 回歸（gate-authoring #3）
#
# === 基準沿革 ===
# 2026-07-29 初版：known-bad = ev-10（gemini-3.5-flash-low 時代穩定 TP）
# 2026-08-29 復活改版：判官換 groq-qwen-3.8-27b（temperature:0）後實測——
#   ev-10 現役兩候選判官（groq 3.8 / gemini-3.7-flash-high）temp0 均穩定漏判，
#   舊基準無現役判官可達 → ev-10 降為 documented known-miss（期望 false、非理想行為，
#   哪天翻 true = 判官能力變了、重審基準）。
#   新 known-bad = bad2.txt（取自 2026-08-29 weekly Opus dual-audit FAIL 樣本 85692db2、
#   groq temp0 2/2 穩定 true、evidence 引用逐字一致）。
#   ⚠️ 本次改版動機與 replay 數據全留 trial detail：
#   ~/Desktop/projects/.claude/trials/active/evidence-level-per-turn-revival-2026-08-29.md
#   不是為了變綠弱化——ev-10 案例保留在卷、期望值如實記錄現役判官行為。
#
# 案例：
#   known-miss    = bad.txt（ev-10）      → false（documented miss）
#   known-bad     = bad2.txt（85692db2）  → true
#   known-good    = good.txt（ev-18）     → false
#   boundary      = short.txt             → G0 skip、不進 ledger
#   pathology     = FIFO ledger 病態目標  → 快速靜默 exit、真 ledger 無新行（gate-authoring 會寫檔 gate 必測）
#
# 2026-09-29 判官改為 Jev 主判、Groq 補判（所有 session 一視同仁，使用者拍板）：
#   Groq 案例改成把 Jev 端點指到關閉的 port（T1_EV_JEV_URL）強制走 fallback，原 Groq 期望值不動，
#   同時驗證 fallback 分支真的會落到 groq。Jev 案例基準取自當日實測（每件連打兩次同向）：
#   ev-10 0.72／0.71 → true（Groq 的 documented miss，Jev 抓得到）；bad2 0.68／0.67 → true；
#   known-fp 0.57／0.57 → true（仍是 documented FP，離門檻只有 0.07，翻 false 要重審）；good 0.22／0.24 → false。
#   另一件斷言公司 cwd 也走 Jev（09-29 同日曾有「公司走 Groq」的分流版，已拿掉，此件防回歸）。
# 改 hook 或 rubric 後必重跑。
set -uo pipefail

HOOK="$(dirname "$0")/T1-evidence-level-detect.sh"
LEDGER="$HOME/.claude/logs/T1-evidence-level-detect.jsonl"
FIX="$(dirname "$0")/T1-evidence-level-fixtures"
PASS=0; FAIL=0
# 關閉的 port：讓 Jev 請求立刻連線失敗，強制走 Groq fallback
DEAD_JEV="http://127.0.0.1:9/v1/systemone"
# hook 由 CC 直接執行（非 bash 前綴），缺 +x 會在 settings 註冊後靜默失敗。
# 測試必須走同一條路徑（2026-07-29 實際踩過：644 權限 + bash 前綴測試全綠假象）
if [[ ! -x "$HOOK" ]]; then
  echo "FAIL: $HOOK 缺執行權限（chmod +x）"; exit 1
fi

run_case() {
  local name="$1" expect="$2" file="$3"
  local before after line got
  before=$(grep -c "" "$LEDGER" 2>/dev/null || echo 0)
  jq -nc --rawfile t "$file" \
    '{session_id:"test-ev-fixture", stop_hook_active:false, last_assistant_message:$t}' \
    | T1_EV_SYNC=1 T1_EV_TIMEOUT=60 T1_EV_JEV_URL="$DEAD_JEV" "$HOOK"
  after=$(grep -c "" "$LEDGER" 2>/dev/null || echo 0)
  if [[ "$expect" == "skip" ]]; then
    if [[ "$after" -eq "$before" ]]; then
      echo "PASS [$name] G0 skip、未進 ledger"; PASS=$((PASS+1))
    else
      echo "FAIL [$name] 預期 G0 skip 但被評分了"; FAIL=$((FAIL+1))
    fi
    return
  fi
  if [[ "$after" -le "$before" ]]; then
    echo "FAIL [$name] 預期落 ledger 但沒有新行（判官掛？）"; FAIL=$((FAIL+1)); return
  fi
  line=$(tail -1 "$LEDGER")
  # 不可寫 `.violation // "null"`——jq 的 // 對 false 也 fallback（2026-07-29 實際踩過）
  got=$(jq -r 'if has("violation") then (.violation|tostring) else "null" end' <<<"$line")
  if [[ "$(jq -r '.model // "null"' <<<"$line")" != "groq-qwen-3.8-27b" ]]; then
    echo "FAIL [$name] Jev 端點已關，預期 fallback 到 groq，實得 model=$(jq -r '.model // "null"' <<<"$line")"
    FAIL=$((FAIL+1)); return
  fi
  if [[ "$got" == "$expect" ]]; then
    echo "PASS [$name] violation=$got (types=$(jq -c '.types // []' <<<"$line"))"; PASS=$((PASS+1))
  else
    echo "FAIL [$name] 預期 violation=$expect 實得 $got"; FAIL=$((FAIL+1))
  fi
}

# Jev／分流案例：帶 cwd（與可選的 transcript_path），同時斷言 violation 與 ledger 的 model 欄
run_routed_case() {
  local name="$1" expect="$2" file="$3" cwd="$4" want_model="$5" tpath="${6:-}"
  local before after line got model
  before=$(grep -c "" "$LEDGER" 2>/dev/null || echo 0)
  jq -nc --rawfile t "$file" --arg cwd "$cwd" --arg tp "$tpath" \
    '{session_id:"test-ev-fixture", cwd:$cwd, transcript_path:$tp, stop_hook_active:false, last_assistant_message:$t}' \
    | T1_EV_SYNC=1 T1_EV_TIMEOUT=60 "$HOOK"
  after=$(grep -c "" "$LEDGER" 2>/dev/null || echo 0)
  if [[ "$after" -le "$before" ]]; then
    echo "FAIL [$name] 預期落 ledger 但沒有新行（判官掛？）"; FAIL=$((FAIL+1)); return
  fi
  line=$(tail -1 "$LEDGER")
  got=$(jq -r 'if has("violation") then (.violation|tostring) else "null" end' <<<"$line")
  model=$(jq -r '.model // "null"' <<<"$line")
  if [[ "$model" != "$want_model" ]]; then
    echo "FAIL [$name] 預期 model=$want_model 實得 $model"; FAIL=$((FAIL+1)); return
  fi
  if [[ "$expect" == "any" || "$got" == "$expect" ]]; then
    echo "PASS [$name] model=$model violation=$got p=$(jq -r '.p_violation // "-"' <<<"$line")"; PASS=$((PASS+1))
  else
    echo "FAIL [$name] 預期 violation=$expect 實得 $got（model=$model）"; FAIL=$((FAIL+1))
  fi
}

run_pathology_case() {
  # 病態 log 目標：FIFO ledger 在假 HOME 下，hook 必須快速靜默放行、不 block、不寫真 ledger
  local name="pathology FIFO ledger"
  local tmp before after elapsed
  tmp=$(mktemp -d)
  mkdir -p "$tmp/.claude/logs" "$tmp/.claude/hooks"
  mkfifo "$tmp/.claude/logs/T1-evidence-level-detect.jsonl"
  before=$(grep -c "" "$LEDGER" 2>/dev/null || echo 0)
  SECONDS=0
  jq -nc --rawfile t "$FIX/good.txt" \
    '{session_id:"test-ev-fixture", stop_hook_active:false, last_assistant_message:$t}' \
    | HOME="$tmp" T1_EV_SYNC=1 T1_EV_TIMEOUT=5 "$HOOK"
  local rc=$?
  elapsed=$SECONDS
  after=$(grep -c "" "$LEDGER" 2>/dev/null || echo 0)
  rm -rf "$tmp"
  if [[ "$rc" -eq 0 && "$elapsed" -lt 5 && "$after" -eq "$before" ]]; then
    echo "PASS [$name] exit=0、${elapsed}s、真 ledger 無新行"; PASS=$((PASS+1))
  else
    echo "FAIL [$name] rc=$rc elapsed=${elapsed}s ledger_delta=$((after-before))"; FAIL=$((FAIL+1))
  fi
}

run_case "known-miss ev-10（documented、翻 true 要重審）" "false" "$FIX/bad.txt"
sleep 3
run_case "known-fp URL＋表格（documented、翻 false 要重審）" "true" "$FIX/known-fp.txt"
sleep 3
run_case "known-bad 無據數字宣稱（bad2）" "true" "$FIX/bad2.txt"
sleep 3
run_case "known-good 證據齊全" "false" "$FIX/good.txt"
sleep 3
run_case "boundary 短回覆" "skip" "$FIX/short.txt"
PERSONAL="$HOME/Desktop/projects"
WORK="$HOME/Desktop/work/acme"
run_routed_case "jev ev-10（Groq miss、Jev 抓到）" "true" "$FIX/bad.txt" "$PERSONAL" "jev-latest"
run_routed_case "jev known-bad bad2" "true" "$FIX/bad2.txt" "$PERSONAL" "jev-latest"
run_routed_case "jev known-fp（documented、翻 false 要重審）" "true" "$FIX/known-fp.txt" "$PERSONAL" "jev-latest"
run_routed_case "jev known-good" "false" "$FIX/good.txt" "$PERSONAL" "jev-latest"
run_routed_case "公司 cwd 也走 jev（分流已拿掉，防回歸）" "any" "$FIX/bad2.txt" "$WORK" "jev-latest"
run_routed_case "cwd 缺失也走 jev" "any" "$FIX/bad2.txt" "" "jev-latest"
run_pathology_case

echo "---"
echo "PASS=$PASS FAIL=$FAIL"
[[ $FAIL -eq 0 ]]
