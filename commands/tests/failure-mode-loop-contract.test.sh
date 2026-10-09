#!/bin/bash
# 回流機制（failure-mode feedback loop）契約測試。
# 讀的檔：
#   ~/.claude/references/failure-mode-taxonomy.md（探針表：登記格式、誰在哪一步讀）
#   ~/.claude/skills/implement/SKILL.md（收尾 Step 3.4：兩種標記、append 編號步驟、缺驗收依據）
#   ~/.claude/commands/pr-review.md（Step 4.9 事後分類標記、Step 6.5 append、缺驗收依據）
#   ~/.claude/workflows/local-analysis.js（CHANNELS 有 failure-mode daily shell channel）
#   ~/.claude/workflows/failure-mode-daily.sh（wrapper 只管路徑、邏輯在 scripts/failure-mode-daily.py）
#   ~/Desktop/projects/.claude/commands/trial-review.md（Step 0 第三類候選、Step 1 兩種提案與不改處置、reviewed 尾碼）
# 票 02–05 會往本檔加斷言（implement SKILL.md、pr-review.md、local-analysis CHANNELS、trial-review.md），
# 不各開一支；每加一個讀取對象就補到上面的清單。
set -uo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TAXONOMY="$ROOT/references/failure-mode-taxonomy.md"
IMPLEMENT="$ROOT/skills/implement/SKILL.md"
PRREVIEW="$ROOT/commands/pr-review.md"
LOCAL="$ROOT/workflows/local-analysis.js"
WRAPPER="$ROOT/workflows/failure-mode-daily.sh"
TRIALREVIEW="$HOME/Desktop/projects/.claude/commands/trial-review.md"
PASS=0
FAIL=0

check() {
  local name="$1"
  local file="$2"
  local expected="$3"
  if grep -qF -- "$expected" "$file"; then
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  else
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  fi
}

check_absent() {
  local name="$1"
  local file="$2"
  local unexpected="$3"
  if grep -qF -- "$unexpected" "$file"; then
    FAIL=$((FAIL + 1))
    printf '  FAIL %s\n' "$name"
  else
    PASS=$((PASS + 1))
    printf '  ok   %s\n' "$name"
  fi
}

echo "[01] 探針表登記格式"
check "登記行七欄格式說明" "$TAXONOMY" 'YYYY-MM-DD | <Failure-miss|Acceptance-miss> | Fn | <repo> | <ticket 或 PR> | 條件 → 症狀 | 發現於（implement-review／pr-review）'
check "Acceptance-miss 的 Fn 可填 -" "$TAXONOMY" 'Acceptance-miss` 的 Fn 可填 `-`'
check "登記區目前 0 行的事實" "$TAXONOMY" '目前 0 行'
check_absent "不留舊格式相容分支" "$TAXONOMY" '發現於（review／production）'
check "誰在哪一步讀：Failure-miss" "$TAXONOMY" 'Failure-miss: Fn'
check "誰在哪一步讀：Acceptance-miss" "$TAXONOMY" '對得上標 `Acceptance-miss`（票有列、實作沒做）'
check "誰在哪一步讀：trial-review 消費" "$TAXONOMY" 'trial-review'
check "誰在哪一步讀：回流只追加本檔" "$TAXONOMY" '回流只追加本檔'

echo "[02] implement 收尾 3.4"
check "先對驗收清單再判標記" "$IMPLEMENT" '先對票的驗收清單：對得上標 `Acceptance-miss`，對不上標 `Failure-miss: Fn`'
check "append 在判定成立後、同一編號步驟內" "$IMPLEMENT" '判定成立後 append 一行到 `~/.claude/references/failure-mode-taxonomy.md` 的「案例登記」區'
check "被推翻的 finding 不 append" "$IMPLEMENT" '被推翻的不 append'
check "兩種模式都走到 append" "$IMPLEMENT" 'Inline 與 Subagent-Driven 兩種模式都由主 session 寫'
check "拿不到驗收清單註明缺驗收依據" "$IMPLEMENT" '拿不到票的驗收清單（票檔缺失）時，finding 保留並註明「缺驗收依據」，不標記、不 append'

echo "[03] pr-review 標記與 append"
check_absent "分類段不在 Step 2.8 內（2.8 會逐字進 reviewer prompt）" "$PRREVIEW" '### 失敗模式標記（主 session 事後分類'
check "Step 4.9 是事後分類不是偵測" "$PRREVIEW" '## Step 4.9: 失敗模式標記'
check "分類不新增偵測" "$PRREVIEW" '對已產出的 finding 做分類標記，不新增偵測'
check "有 spec 沒驗收項比照沒有" "$PRREVIEW" '有 spec 但沒有驗收項（brainstorm、design、日期檔名的 plan）比照沒有處理'
check "被推翻的 finding 不標" "$PRREVIEW" '驗證結果不是 `REFUTED`／`OUT_OF_SCOPE` 的 finding'
check "4.8 接到 4.9" "$PRREVIEW" '進 Step 5 前先做 Step 4.9 的失敗模式標記'
check "4.7 單目標路也經 4.9" "$PRREVIEW" '中間只經 Step 4.9 的失敗模式標記'
check "5.0 checklist 有分類項" "$PRREVIEW" '每個 admitted finding 都經過 Step 4.9 失敗模式分類'
check "6.5 零標記也回報三個數" "$PRREVIEW" '分類 N、標記 0、缺驗收依據 K'
check "不進 reviewer prompt" "$PRREVIEW" '本段不注入任何 reviewer prompt'
check "標記寫在 finding 文字內" "$PRREVIEW" '標記寫在 finding 本身的文字（標題或備註）'
check "沒有驗收清單註明缺驗收依據" "$PRREVIEW" '註明「缺驗收依據」，不標記、不 append'
check "Step 6.5 append 步驟存在" "$PRREVIEW" '## Step 6.5: 回流登記'
check "單目標與多目標同一 append 步驟" "$PRREVIEW" '單目標與多目標（Step 4.8）兩條路都經過本步'
check "6.5 在 Step 7 之前" "$PRREVIEW" '本步完成後才接 Step 7'
order_ok() {
  local a b
  a=$(grep -nF -- "$2" "$1" | head -1 | cut -d: -f1)
  b=$(grep -nF -- "$3" "$1" | head -1 | cut -d: -f1)
  [ -n "$a" ] && [ -n "$b" ] && [ "$a" -lt "$b" ]
}
if order_ok "$PRREVIEW" '## Step 4.9: 失敗模式標記' '## Step 5: Compile Comparison Report' && order_ok "$PRREVIEW" '## Step 6.5: 回流登記' '## Step 7: Cleanup'; then PASS=$((PASS + 1)); printf '  ok   %s\n' "步驟順序 4.9<5、6.5<7"; else FAIL=$((FAIL + 1)); printf '  FAIL %s\n' "步驟順序 4.9<5、6.5<7"; fi

echo "[04] 每日 channel"
check "CHANNELS 登記 failure-mode daily shell" "$LOCAL" "{ key: 'failure-mode', freq: 'daily', kind: 'shell', src: '~/.claude/workflows/failure-mode-daily.sh'"
check "wrapper 呼叫 python 腳本" "$WRAPPER" 'python3 ~/.claude/scripts/failure-mode-daily.py --date "$DATE" --out "$OUT"'
check "wrapper 不含邏輯（只管路徑）" "$WRAPPER" '本檔只負責路徑約定'

echo "[05] trial-review 消費"
check "Step 0 第三類候選來源是登記區未處理行" "$TRIALREVIEW" '**失敗模式提案候選**：讀 `~/.claude/references/failure-mode-taxonomy.md`「案例登記」區沒有 `[reviewed ` 尾碼的登記行'
check "當日 channel 只是提醒不是唯一來源" "$TRIALREVIEW" '每日 channel 的 failure-mode 輸出只是提醒，不是候選的唯一來源'
check "提案只有兩種形狀" "$TRIALREVIEW" '提案只准兩種：改探針表某一類的問句、把 F7 累積的形狀升格為新類別'
check "不改是合法處置" "$TRIALREVIEW" '「不改探針、證據不足、同案重複」是合法處置'
check "Acceptance-miss 原樣列出不分流" "$TRIALREVIEW" '`Acceptance-miss` 條目原樣列出、當場決定，不套預設分流'
check "處理後加 reviewed 尾碼" "$TRIALREVIEW" '在該行行尾加 `[reviewed YYYY-MM-DD <處置>]`'
check "只改探針表不動流程檔" "$TRIALREVIEW" '只改探針表，不動 to-tickets／implement／pr-review 的流程檔'
check "登記行判定與腳本共用同一條正則" "$TRIALREVIEW" '與 `scripts/failure-mode-daily.py` 的 `ROW_RE` 同一條'
check "無鎖：已有尾碼就跳過不覆寫" "$TRIALREVIEW" '已有 `[reviewed ` 尾碼就跳過不覆寫'
check "Step 2 有失敗模式落地分支" "$TRIALREVIEW" '**失敗模式落地**：不經所有權 gate'
check "Step 3 有 R6" "$TRIALREVIEW" 'R6【失敗模式消費一致性】'
check "Step 4 有失敗模式計數" "$TRIALREVIEW" '失敗模式的 N 改問句 / N 升格 / N 不改'

echo
printf 'PASS=%d FAIL=%d\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
