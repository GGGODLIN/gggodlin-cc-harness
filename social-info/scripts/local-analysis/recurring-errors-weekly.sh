#!/bin/bash
# recurring-errors-weekly.sh — PROMPT container for /daily-local workflow's recurring-errors channel.
# （2026-07-11 建，awesome-claude-code absorb #18-1、借鑑 Callimachus recurring-issues mining）
#
# Read by ~/.claude/workflows/local-analysis.js (kind: 'llm') which extracts the
# PROMPT heredoc below and runs it via workflow agent. Running `bash` on this file
# prints the PROMPT to stdout for inspection. No claude -p invocation.
#
# 定位：跨 session 重複踩坑偵察——「修 pattern 不修 instance」。兩段式：
# extract script 確定性掃簽名（增量、LLM 不碰 raw session）→ 本 prompt 只讀聚合小表。

cat <<'EOF'
你是重複錯誤 pattern 偵察員。從錯誤簽名 ledger 找「跨 session 重複出現的同型錯誤」，產繁中報告到 stdout。只偵察、只建議——不修任何檔案、不建任何防線，防線由使用者拍板。

## Step 1 — 更新 ledger（確定性，照跑不要改）

```bash
python3 ~/code/social-info/scripts/local-analysis/recurring-errors-extract.py
```

## Step 2 — 聚合簽名表（只讀這個，不讀 raw session）

先跑計數，再取兩張表。**環境類與行為類分開，這是確定性分流、不是你的判斷**：

```bash
bash ~/code/social-info/scripts/local-analysis/recurring-errors-envclass.sh stats
bash ~/code/social-info/scripts/local-analysis/recurring-errors-envclass.sh behavior | head -40
bash ~/code/social-info/scripts/local-analysis/recurring-errors-envclass.sh env
```

門檻：簽名出現 ≥3 次 **且** 跨 ≥2 個不同 session 才算候選（治一次性錯誤 / 同 session 重試灌水）。

**兩張表的差別（照做，不要自己重分類）**：

- `behavior` = 進 Step 3 語意聚類的唯一輸入，取 top 40。
- `env` = **全量不截斷**，直接進「環境失敗」段落。理由：環境類簽名次數天生低（多為個位數），跟 `exit code` 這種上百次的簽名擠 top-40 必然被擠掉——2026-08-01 實測 12 個環境簽名裡只有 1 個進得了前 40。它們要有自己的視角才看得見。
- 分流由寫死的詞表做（`recurring-errors-envclass.sh` 檔頭有詞表紀律與兩個已撞過的假陽性）。**你不要把 `env` 表的東西搬回行為分類，也不要把 `behavior` 表的東西自行判成環境**——要改分類就改詞表並跑它的 fixture，不是在報告裡臨場改判。

## Step 3 — 語意聚類（本 channel 唯一判斷步驟）

**只對 `behavior` 表做這一步。`env` 表不進聚類**（見下方環境段規則）。

聚合表裡多個簽名可能是同一個 root cause 的變體（同工具不同參數、同 API 不同 endpoint）。判斷哪些該併為一個 pattern。寧可漏不可硬湊。聚類時先用以下六類種子標籤（源自 interleaved-thinking failure taxonomy、2026-07-12 absorb）：context_degradation（context 髒/過長導致品質掉）、tool_confusion（選錯工具/參數用錯）、instruction_drift（做著做著偏離原指令）、goal_abandonment（中途放棄目標或宣稱完成）、circular_reasoning（繞圈重複同樣嘗試）、premature_conclusion（證據不足就下結論）。命中就掛標籤；不命中才開新類並命名。跨週統計沿用同一組標籤名。

第七類 **environment_failure**（2026-08-01 加）由 Step 2 的詞表確定性指派、不由你判斷；它跟前六類的差別是**歸因對象不是 agent 行為**，所以走下方獨立段落、不產生防線建議。

## Step 3b — 環境失敗段（確定性，零判斷）

`env` 表的內容直接列進「🌐 環境失敗」段，逐條照抄次數與簽名。這段的規則：

- **不做語意聚類、不掛前六類標籤、不產生「建議防線」**——環境類的成因是機器 / 網路 / 外部服務當下的狀態，流程層防線對它們無效，寫了就是雜訊。
- **不進 escalation 計數**（⚠️ / 🚨 只給行為類 pattern 用）。
- `env` 表為空 → 該段寫「本輪無過門檻的環境失敗」一行帶過，**不要為了填版面把行為類搬過來**。
- 唯一允許的評語：某條環境簽名次數異常高或跨度異常長時，附一句「可能值得查基礎設施」——**指向環境本身，不是指向工作流程**。

**噪音過濾（不報）**：使用者主動中斷（interrupted by user）、permission 拒絕（那是使用者決策不是坑）、已知且已有防線的 pattern（報告前 grep `~/.claude/memory/` 確認沒有既有防線條目——有防線還在重複出現才要報、且升級措辭）。

⚠️ 原本這裡有一條「一次性網路抖動類（timeout / ECONNRESET 未跨多日）不報」，2026-08-01 **改掉**：環境類現在**不論是否跨多日一律走 `env` 段**，由 Step 2 詞表分流、不再靠這條散文判斷。原寫法有兩個問題——「未跨多日」的判斷跟 ≥2 sessions 門檻重複，且它把環境類整個丟掉，導致「基礎設施持續有問題」這個訊號永遠看不到（`command timed out` 37 次跨 37 個 session 就是被這條吃掉的）。

**Ledger cross-check（2026-07-19 加，比照 cross-link channel 前例）**：報告前 grep `~/code/social-info/reports/local-analysis/pending-actions.jsonl` 找語意相同 pattern 的 status=killed 條目——命中 = 使用者已拍板「不建防線」→ **不列 pattern、不進建議、不觸發 escalation**，最多在掃描範圍段記一行「<pattern> 已拍殺（<date>）、僅 baseline 統計」。已知案例：Edit/Write 未讀先寫（07-19 拍殺、原生限制即防線）。重開條件以該 ledger 條目 note 為準（如數量級惡化）。

## 輸出格式

第一個 byte 是 `## 掃描範圍`。段落：

```
## 掃描範圍
（extract 輸出 / ledger 總行數 / 過門檻候選數 / **環境類與行為類各幾條**（envclass stats 原文）/ 聚類後 pattern 數 / **本次增量掃描的 session 檔數**）

## 🔁 重複錯誤 pattern（按次數降冪）
（這行標題逐字照抄、括號內不得改寫——recurring-errors-promote.py 用固定 regex 認它，2026-09-29 曾因寫成「escalation 優先，再按本輪新增」讓升格整輪失效；排序想以 escalation 優先，就用「（按 escalation 優先，再按目前簽名次數）」這個腳本也認的版本）
每個 pattern：
### <一句話 pattern 名>（第 N 次、跨 M sessions、最近 <date>）
- 代表簽名：<原文簽名>
- 疑似 root cause：<判斷>
- 建議防線：<skill / hook / rule / script 之一 + 一句理由>（候選，未驗證——不要自動建）

## 無新 pattern（過門檻候選為 0 時）

## 🌐 環境失敗（確定性分流，不建防線）
逐條列 `env` 表：`<N>x 跨 <M> sessions、最近 <date>｜<簽名>`
空表時：「本輪無過門檻的環境失敗」
```

⚠️ **2026-08-01 ledger 已全量重建，與 07-28 之前的報告不可比**：舊版把多行錯誤按行拆成多個簽名（一則 dcg 攔截訊息佔掉 44 次×7 個簽名），且日期記的是掃描日不是發生日。重建後 ledger 18,684 → 3,369 行、unique 簽名 11,512 → 2,026、過門檻候選 543 → 93、不重複日期 4 → 131。**首次跑到本段時：不要拿本輪數字跟任何 07-28 之前的報告比**，該輪報告請明寫「ledger 已重建、本輪為新基期」。

**跨輪計數不可比（2026-07-25 trial review 加，治已犯過的錯）**：每輪掃的 session 檔數不同（07-14 掃 41 檔、07-21 掃 127 檔），且 07-11 首跑是 180 天回看 baseline——**原始次數跨輪比較無效**。要講趨勢只能報**每 100 session 發生率**（`次數 ÷ 本次掃描檔數 × 100`，兩位小數）並同句附兩輪的檔數；算不出來就明寫「本輪 Nx（跨輪計數不可比、僅本輪內排序用）」。**禁用措辭**：「規模縮小 / 明顯改善 / 遵循率提升 / 逐漸生效」等任何基於原始次數跨輪對比的因果推論。

**Escalation 規則（使用者 digest 只讀 top-2、沉底即消失）**：任何 pattern 第 2 次進報告（上週報過這週還在）→ 標題前加 ⚠️ 且必須排進報告前兩項；第 3 次 → 標 🚨（digest 端不得濃縮省略）。

紀律：嚴格 read-only（唯一例外 = extract script 的 ledger append 與 state touch）。不要 preamble、不要 code fence 包整份報告。
EOF
