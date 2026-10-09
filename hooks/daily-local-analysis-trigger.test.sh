#!/bin/bash
# daily-local-analysis-trigger.test.sh — gate-authoring checklist §3 的三件回歸
# （known-good / known-bad / 邊界），加繞行場景表裡有機械攔截點的那幾條。
# 用法：bash daily-local-analysis-trigger.test.sh
set -uo pipefail

HOOK="$(cd "$(dirname "$0")" && pwd)/daily-local-analysis-trigger.sh"
PASS=0
FAIL=0

fire() {  # fire <prompt> → 印 "yes" 或 "no"
  local out
  out=$(printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps({"prompt": sys.stdin.read()}))' \
        | bash "$HOOK" 2>/dev/null)
  [ -n "$out" ] && echo yes || echo no
}

ctx() {  # ctx <prompt> → 印 additionalContext
  printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps({"prompt": sys.stdin.read()}))' \
    | bash "$HOOK" 2>/dev/null \
    | jq -r '.hookSpecificOutput.additionalContext // ""'
}

check() {
  local name="$1" expect="$2" actual="$3"
  if [ "$expect" = "$actual" ]; then
    PASS=$((PASS + 1)); printf '  ok   %-46s %s\n' "$name" "$actual"
  else
    FAIL=$((FAIL + 1)); printf '  FAIL %-46s expect=%s actual=%s\n' "$name" "$expect" "$actual"
  fi
}

echo "== known-good：該注入 =="
check "「每日本機分析」"        yes "$(fire '每日本機分析')"
check "「今日本機分析」"        yes "$(fire '今日本機分析')"
check "帶前後綴的自然說法"      yes "$(fire '幫我跑一下每日本機分析，謝謝')"

echo "== known-bad：不該注入 =="
check "系統通知含關鍵字"        no  "$(fire '[SYSTEM NOTIFICATION] 每日本機分析 完成')"
check "task-notification 含關鍵字" no "$(fire '<task-notification>每日本機分析</task-notification>')"
check "無關鍵字"                no  "$(fire '幫我看一下 wiki 健康度')"
LONG=$(python3 -c "print('每日本機分析 ' + 'x'*320)")
check ">300 字元的引用脈絡"     no  "$(fire "$LONG")"

echo "== 邊界：長度守衛的線 =="
AT300=$(python3 -c "print('每日本機分析' + 'x'*294)")   # len 300
AT301=$(python3 -c "print('每日本機分析' + 'x'*295)")   # len 301
check "剛好 300 字元 → 注入"    yes "$(fire "$AT300")"
check "301 字元 → 不注入"       no  "$(fire "$AT301")"

echo "== user-facing recipe 必須先於內部指示 =="
C=$(ctx '每日本機分析')
FIRST_NONEMPTY=$(printf '%s' "$C" | python3 -c '
import sys
for line in sys.stdin.read().splitlines():
    if line.strip():
        print(line)
        break
')
check "第一個非空內容是固定四格 heading" 1 "$([ "$FIRST_NONEMPTY" = "最後給使用者的 digest 先依固定四格順序呈現：" ] && echo 1 || echo 0)"
SLOT_PASS=0
for slot in "本機分析抓到什麼" "哪些已完成" "哪些尚未處理" "本輪每件只要決定什麼"; do
  n=$(printf '%s' "$C" | grep -cF -- "$slot")
  check "user-facing slot「${slot}」" 1 "$([ "$n" -ge 1 ] && echo 1 || echo 0)"
  [ "$n" -ge 1 ] && SLOT_PASS=$((SLOT_PASS + 1))
done
printf 'user-facing slots=%s/4\n' "$SLOT_PASS"
ORDER=$(printf '%s' "$C" | python3 -c '
import sys
text = sys.stdin.read()
slots = ["本機分析抓到什麼", "哪些已完成", "哪些尚未處理", "本輪每件只要決定什麼"]
positions = [text.find(slot) for slot in slots]
internal = text.find("Workflow tool")
print(1 if internal >= 0 and all(pos >= 0 for pos in positions) and positions == sorted(positions) and all(pos < internal for pos in positions) else 0)
')
check "四格依序且先於 Workflow tool" 1 "$ORDER"
check "四格是 main 呈現 recipe，不是 input schema" 1 "$(printf '%s' "$C" | grep -cF '這四格是 main 最終呈現 recipe，不是 workflow input schema。')"

echo "== 注入內容的必要條款（改壞會靜默掉規則）=="
for kw in "reconcile_cmd" "不要自己算" "recurring_promotion_cmd" "每輪最多 1 個" \
          "處理／忽略／延後" "source_key" "needs_read" "Wiki health" "原文保留" \
          "跨檔不重號" "強制下限" "範圍排除" "進場閘" "不要自行下根因結論" \
          "本次沉底" "只走腳本" "locked surface" "跳過了哪幾條"; do
  n=$(printf '%s' "$C" | grep -c -- "$kw")
  check "含「${kw}」" 1 "$([ "$n" -ge 1 ] && echo 1 || echo 0)"
done

check "ledger-lifecycle source_key 原樣照抄" 1 "$(printf '%s' "$C" | grep -cF 'ledger-lifecycle finding 的 source_key 也要原樣照抄')"
check "ledger-lifecycle 不受產品 repo 排除" 1 "$(printf '%s' "$C" | grep -cF 'ledger-lifecycle 命中不套用產品 repo 排除')"
check "ledger-lifecycle 走 H/M/L 與 pending-actions" 1 "$(printf '%s' "$C" | grep -cF '照既有 H/M/L 三檔、pending-actions、count 升檔與沉底行處理')"
check "ledger-lifecycle 不另建區塊" 1 "$(printf '%s' "$C" | grep -cF '不另建區塊')"

echo "== 可選欄（使用者只叫 agent 執行高中低，末尾提醒沒人接）=="
check "含可選欄標題" 1 "$([ "$(printf '%s' "$C" | grep -cF '## 可選（不回也沒關係）')" -ge 1 ] && echo 1 || echo 0)"
check "可選欄在執行完高中低的回報末尾" 1 "$(printf '%s' "$C" | grep -cF '執行完高中低、交完成回報時')"
check "沒回應即略過、不升級進三檔" 1 "$(printf '%s' "$C" | grep -cF '沒回應就算略過，不追問、不升級進高中低')"
check "rules-size 讀最近一份報告" 1 "$(printf '%s' "$C" | grep -cF '最近一份 rules-size 報告')"
check "rules-size 以檔名日期排序" 1 "$(printf '%s' "$C" | grep -cF '依檔名日期取最新')"
check "📏 進可選欄" 1 "$(printf '%s' "$C" | grep -cF '📏 always-on 超標')"
check "⚖️ 進可選欄" 1 "$(printf '%s' "$C" | grep -cF '⚖️ 留/殺待拍板')"
check "🪦 零使用規則進可選欄並指向 /rules-slim" 1 "$(printf '%s' "$C" | grep -cF '🪦 零使用規則 N 條 → /rules-slim')"
check "🪦 讀 rules-size 的零使用標題原文" 1 "$(printf '%s' "$C" | grep -cF '## 🪦 零使用規則候選（N）')"
check "🪦 N 為 0 不列" 1 "$(printf '%s' "$C" | grep -cF 'N 為 0 或報告沒有這段就不列')"
check "🪦 不自動跑 /rules-slim" 1 "$(printf '%s' "$C" | grep -cF '同樣不自動跑 /rules-slim')"
check "可選欄收三種" 1 "$(printf '%s' "$C" | grep -cF '目前收三種')"
check "🪦 零使用段不進三檔不寫 ledger" 1 "$(printf '%s' "$C" | grep -cF '零使用段只進可選欄，不進三檔、不進沉底行、不寫 ledger')"
# 反向斷言（2026-10-05 前的寫法）：📏 放 digest 末尾時 6 次提醒 0 次執行，舊理由句不得回來
check "舊的「digest 末尾唯一保證被讀到」理由已移除" 0 "$(printf '%s' "$C" | grep -cF '放末尾是因為那是 digest 唯一保證被讀到的位置')"

echo "== routed recap 接線條款 =="
check "啟動 routed recap wrapper" 1 "$(printf '%s' "$C" | grep -cF '~/code/social-info/scripts/local-analysis/recap-daily.sh')"
check "recap 以背景 Bash 啟動" 1 "$(printf '%s' "$C" | grep -cF 'run_in_background=true')"
check "workflow 跳過內建 recap" 1 "$([ "$(printf '%s' "$C" | grep -cF '"external_recap":true')" -ge 1 ] && echo 1 || echo 0)"
check "等待兩條工作再排檔" 1 "$(printf '%s' "$C" | grep -cF 'recap Bash 與 workflow 都完成後')"
check "workflow 回傳 external channel" 1 "$([ "$(printf '%s' "$C" | grep -cF 'external_channels')" -ge 1 ] && echo 1 || echo 0)"
check "recap 失敗進 failed" 1 "$(printf '%s' "$C" | grep -cF '把 recap 加進 failed')"

echo "== main 報告落檔交接 =="
for kw in 'pending_reports' 'report_markdown' 'deferred_writeback' '先用 Write 落檔' '不能把舊檔存在當成本輪成功' '成功後才加入 ran／channels' '只限原 source 已授權'; do
  check "主寫入含「${kw}」" 1 "$([ "$(printf '%s' "$C" | grep -cF -- "$kw")" -ge 1 ] && echo 1 || echo 0)"
done

echo "== beads-aging 專屬處理條款 =="
for kw in "beads-aging" "## 🧵 待辦老化" "不得寫入 pending-actions.jsonl" \
          "使用者拍板後" "絕對 repo path" "bead id" "未拍板不得執行 bd" \
          "bd defer" "bd update" "bd close --reason" "不套用第 8 條"; do
  n=$(printf '%s' "$C" | grep -cF -- "$kw")
  check "含 beads 條款「${kw}」" 1 "$([ "$n" -ge 1 ] && echo 1 || echo 0)"
done

echo "== publish-candidate 排檔條款（兩個 heading 與 social-info 的 publish-candidate-weekly.sh 逐字一致）=="
# 字串與 wrapper 的 H_CAND／H_FAIL 雙邊鎖定：wrapper 的 test 會讀本檔注入文字比對，這裡鎖本檔這一邊。
for kw in '## 📦 公開 harness 發布候選（需要你決策，agent 不得代做）' \
          '## ⚠️ 公開 harness 發布候選檢查失敗' \
          '-publish-candidate.md' \
          '本週沒有發布候選' \
          '發布／不發布／升級全審' \
          'agent 不得代做發布、push 或啟動全審' \
          '不套用第 8 條產品 repo 排除'; do
  check "含「${kw}」" 1 "$([ "$(printf '%s' "$C" | grep -cF -- "$kw")" -ge 1 ] && echo 1 || echo 0)"
done
check "候選固定放 🔴 高檔、不得下調" 1 "$(printf '%s' "$C" | grep -cF '固定放 🔴 高檔、不得下調')"
check "候選不寫 pending-actions.jsonl" 1 "$(printf '%s' "$C" | grep -cF '也不寫 pending-actions.jsonl（候選由每週 channel 重新產生')"
check "沒有候選的報告不進三檔也不列沉底" 1 "$(printf '%s' "$C" | grep -cF '不進三檔、不列沉底行')"
check "新條款出現在第 6 條（三檔）之後、第 7 條之前" 1 "$(printf '%s' "$C" | python3 -c '
import sys
text = sys.stdin.read()
a = text.find("6. 產「今天值得做的事")
b = text.find("公開 harness 發布候選（需要你決策")
c = text.find("7. reconcile 輸出")
print(1 if 0 <= a < b < c else 0)
')"

echo "== 動態值擺位（prefix cache：日期必須在尾端）=="
LAST=$(printf '%s' "$C" | tail -1)
check "最後一行是本次 args" 1 "$(printf '%s' "$LAST" | grep -c '本次 args')"
# macOS head 不吃 `-n -1`（會 illegal line count 並吐空，讓本檢查假通過）；用 sed 砍末行
BODY=$(printf '%s\n' "$C" | sed '$d')
check "去掉末行後仍有內容（防假通過）" 1 "$([ "$(printf '%s' "$BODY" | wc -c | tr -d ' ')" -gt 500 ] && echo 1 || echo 0)"
check "尾行以外不出現日期" 0 "$(printf '%s' "$BODY" | grep -cE '[0-9]{4}-[0-9]{2}-[0-9]{2}')"

echo "== 輸出必須是合法 JSON（jq 讀得動）=="
check "jq parse" 0 "$(printf '%s' '每日本機分析' \
  | python3 -c 'import json,sys; print(json.dumps({"prompt": sys.stdin.read()}))' \
  | bash "$HOOK" | jq -e '.hookSpecificOutput.hookEventName == "UserPromptSubmit"' >/dev/null 2>&1; echo $?)"

echo
echo "pass=$PASS fail=$FAIL"
[ "$FAIL" -eq 0 ]
