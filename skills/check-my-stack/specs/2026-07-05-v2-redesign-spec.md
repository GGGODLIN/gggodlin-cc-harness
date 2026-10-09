# check-my-stack v2 重寫 spec（2026-07-05 · v2.1 — 已折入五路 review 定案 + 使用者拍板 D1-D3）

Review 紀錄：[2026-07-05-check-my-stack-v2-review.md](~/.claude/skills/check-my-stack/specs/2026-07-05-check-my-stack-v2-review.md)（T3 三 lens + T4 codex/agy Flash，59 條 findings 合成）。拍板：D1 移除超集快殺通道、D2 一次 ship、D3 exhausted 軟封存。

## 使用者真正要什麼（intent brief）

使用者維護一套個人 agent 基礎建設，check-my-stack 是評估「熱門工具值不值得引入/借鑑」的核心決策 skill。2026-07-05 對 35 個實際 invoke session 的全樣本 review 發現：59% session 需要使用者出手引導（~63 次）；11 個行動型結局中 9 個靠使用者推動；零引導 session 幾乎全收斂到紙上否決。使用者出手類型固定（要求證據、補驗證軸、推 dry-run、挖抽件、切「以採用為前提」模式）且命中率高。判決帳本是單向棘輪（graphify 案）；分母失真沒人驗（PullMD / OpenSpec / brooks-lint 案）。

使用者拍板方向：進到分析的工具已通過他的興趣濾網。**姿態改寫**（codex #3 定稿措辭）：「先建立該工具最強的 adoption hypothesis、再嘗試推翻它」——判決沒有 default、只有分析順序有 default。姿態翻轉管的是**力氣分配**（先盡力找成立路徑），不是**證據標準**（判準不鬆）。

## Goals

1. 把使用者手動出手的動作模式編成 skill 預設步驟（judgment 點的挑戰 pass、實測分流、抽件狩獵、最佳 frame、分母對帳）
2. 模糊地帶否決的舉證責任翻轉：須秀工作量 + 翻案條件；同時舉證對稱化防鏡像失效
3. 行動出口內建：判決結尾給「取得價值的最便宜路徑」或「能定案的測試」（允許合法空值）
4. 帳本 frame-scoped 閉環：讀端對帳 + 寫端回寫 + pending-outcome 追蹤（規則 SSOT = memory 帳本格式段）

## Non-goals

- 不是把判準調鬆、不是提高採用率 KPI（settled lineage / dealbreaker 快殺是 feature）
- 不動 sibling 決策 lens 分工（Path A/A'/B install lens、agent-in-loop lens）；skill-install-only 工具實測前先過 install lens
- 不改四 block output 的表格寬度紀律

## v2.1 結構

### 定位改寫

Governing rule：「進到這個 skill 的工具已通過使用者的興趣濾網；先建立它最強的 adoption hypothesis、再嘗試推翻。順序紀律不變：先盤點自家 stack 再讀工具。姿態管力氣分配、不管證據標準。」

**Prior 清除（完整清單，實作驗收跑 `grep -in "collapse\|superset\|toward zero\|thin\|≈0"` 逐命中處理、保留須附理由）**：

1. description「most collapse toward zero」
2. overview（SKILL.md L8）「usually already a superset」
3. governing rule「usually a superset」「converge to landscape observation」
4. Step 2 先例檢索詞「collapse cases」→ 改中性「prior tool-evaluation cases, any outcome」
5. Step 3「Most rows resolve to ≈0」→ 保留機制、改寫商數示例語句（≈0 / <0 / non-zero 並列中性呈現）
6. Step 6 + output-template Verdict「name the structural root cause (superset)」強制斷言 → 改為「陳述收斂位置與根因（何種根因皆可）」
7. output-template Block 2「key collapse」強制段 → 改「關鍵商數論證」（collapse 或 non-zero 皆可）
8. Block 4「be explicit that most residuals are thin」→ 「report the arithmetic honestly whichever way it goes」

### 流程

- **Step 0 快殺檢查**（唯一紙上快判通道；資格證明落 gate 帳）。兩條資格：
  - (a) **settled lineage 命中**，三件套缺一不可：引用 lineage 條目 + 一句「本案 frame 與該 lineage 同型」論證 + 對條目 mini 對帳（否決依據的分母還在？工具 upstream 有無重大變化？）。舊無 frame 條目只當線索、不構成資格（引用時增量補 frame 回寫）。
  - (b) **structural dealbreaker 條目命中**（billing 不能串既有訂閱 / agent-in-loop 軸錯 / mission-critical 不適配等既有紀律），須引條目 + 一句適用論證。
  - （D1 拍板：v2 草案的「超集覆蓋」通道移除——該判斷需要 Step 1 盤點結果、放 Step 0 是循環論證；超集型快殺在 Step 3 後自然浮現。）
  - 帳本有 exhausted 標記（見 Step 6）→ 可引用為 lineage 資格，翻案只認 delta 證據。
- **Step 1 盤點 + 對帳**：Explore 盤點硬 gate 保留。對帳限 **load-bearing 列**（Block 2 商數引為除數、且被判決引用的 2-4 列；其餘標「未對帳」）。probe 按類型分欄：CLI → `which` / `uv tool list` / `npm ls -g` / `brew list`；skill/agent → session jsonl invoke 計數；hook → audit log；排程 → launchd/cron last-run。成熟度標記二分「裝機已驗 / 採用已驗」，檔案存在不得冒充採用。
- **Step 2 工具實質 + 先例召回 + 對帳**：研究紀律保留。檢索詞中性化（any outcome）；挑先例按「形狀最近」不按「結論同向」；引用前驗先例仍成立（三態：仍成立 / 部分失效 / 已失效；失效當場回寫帳本——規則細節引 memory 帳本格式段，不在 skill 內複寫）。
- **Step 3 逐項 ÷ 成熟度映射**：機制不變，示例語句中性化（見 prior 清除 #5）。
- **Step 4 最佳 frame 搜尋（含 pain gate）**：主動在使用者 stack 找工具最能落的位置，不按工具行銷 frame 評。三道圍欄：frame 必須錨定 Block 1 具名 capability area（不准自由發明）；每個候選 frame 必過 pain-vs-absence 過濾（答「對應 Block 1 哪個缺口 / 哪個可升級分母」，答不出不進判決——qiaomu 洞察#2 / Agent-Reach 洞察#4 判準）；替代 frame 上限一個、找不到寫「none found」。反例教材：graphify 的 brownfield 結構訊號 frame 該由本步主動提案、而不是 12 天後使用者自己撞到。
- **Step 5 抽件狩獵（條件執行）**：草判決走向否決/landscape 時執行（走向採用/trial 者整包都要了、免狩獵）。最低 protocol：看 README / API surface / examples / config / hooks / CLI entrypoints；輸出三欄 `stealable mechanism / graft point / reason rejected`。閉源或無公開 source → 自動降級「API/架構概念層借鑑評估」並註明。反例教材：ocr 案「確定性層偷不了」被使用者一句翻成「最好偷的部分」。
- **Step 6 判決（含挑戰 pass + gate 帳）**：
  - **判決五擇**：採用 / trial / 抽件 / watch-defer / landscape。watch-defer 必附 revisit trigger（例：出現本地 CLI、支援 MCP、stack 端出現 X 痛點）。
  - **否決前挑戰 pass**（v2 草案 Step 3.5 + 5.5 收斂於此）：草判決 = 否決/landscape 且非 Step 0 快殺 → 回答固定四問：(1) 機制層驗了嗎（理念層否決不自動涵蓋機制層）？(2) 換 frame 呢（Step 4 的 none found 還站得住嗎）？(3) 真的偷不了嗎（Step 5 三欄有據嗎）？(4) 可實測為何沒測？任一問翻案 → 回圈對應步驟。另留一欄「本工具特有軸」（可填「無、已檢查」）。
  - **第四問的實測分流（三態 triage）**：`Runnable now`（有 install 指令 + 本地可跑輸入）→ 必測、輸出貼 gate 帳；`Runnable with user approval` → 附最小實測命令 + 風險、等核准；`Not runnable cheaply` → 枚舉阻斷因子（付費帳號 / 互動 auth / 缺資料 / 硬體）+ 附「如果可測會跑的那條指令」。涉 install → 先過 safe-trial trigger 判斷（audit 成本計入預算；超出 → 允許紙上判決、標「未實測，因 audit 成本」）。session 內測不完 → 判決標 `provisional` + 附可執行測試計畫。測後收尾二擇一：當場移除 or 登錄 trials/active.md。in-session 測試正向但需時間維度驗證 → 強制升 trial 判決。正例：headroom（真 cheap-trial）；RTK 屬 trial 判決量級正例。
  - **gate 帳區塊**（Verdict 前強制 artifact，事後可 grep 稽核）：Step 0 走哪個通道 + 資格證明；挑戰四問各一行（驗過 → 證據指標、未驗 → 明寫）；實測三態判定 + 輸出。
  - **舉證對稱**：模糊地帶定義 fail-closed =「凡未過 Step 0 資格的否決一律視為模糊」，否決須附工作量證明 + 翻案條件。trial 判決必附 KPI + review date + kill 條件 + trials/active.md H2 登錄（`## <name> (YYYY-MM-DD)` 格式；不依賴 safe-trial 自動登記）。抽件判決必附檔案/機制名 + 落點 + 下一步動作，禁「值得偷」空頭抽件。
  - **行動出口**：結尾輸出「取得價值的最便宜路徑」或「能定案的測試」，允許合法空值「無——翻案條件：X」；Step 0 快殺判決豁免行動路徑欄、只填翻案條件。
  - **帳本寫回**：判決以 frame-scoped 格式自動寫回 precedent log（graphify stale 教訓，是 github-repo-research ask-first 慣例的**刻意例外**、明寫）。trial/抽件標 `pending-outcome` + 指向後續 ledger。同工具重評新 frame 必聲明 delta（工具端或 stack 端變了什麼）、無 delta 不開案；累積 3 個 frame-scoped 否決 + 零殘值 → 打 tool-level `exhausted` 軟封存（D3 拍板；翻案只認新 delta 證據）。row 長度設上限、細節外掛 `[[reference_*]]` 檔。

### Output template 對應改動

- Block 2 prose 段中性化（prior 清除 #7）
- Block 3 改「最佳 frame 搜尋結果」（含 pain-vs-absence 欄）
- Block 4 改「抽件狩獵結果」（三欄 protocol；條件執行時標「未執行——草判決非否決」）
- Verdict 前插 gate 帳區塊；Verdict 加翻案條件 + 行動路徑（允許合法空值）+ 根因措辭中性化（prior 清除 #6）
- 表格寬度紀律不動

### Anti-patterns

原 6 條保留、第 5 條改指新 Step 4 pain gate。新增 3 條：

- ❌ 否決前未走挑戰 pass（或 gate 帳缺對應行）
- ❌ `Runnable now` 而未實測就出紙上判決
- ❌ 引先例/成熟度未對帳現實（帳本是 claim 不是 evidence）

### 附帶 patch（github-repo-research）

Patch contract：memory 既評命中 → 輸出前標 `unchecked prior`；完成對帳（裝機狀態 + grep 自家 skill 引用 + 本次提問 frame 與舊結論 frame 同型檢查）後才升格 evidence。description 的「已評過只想回憶結論 → 引舊結論即可」句尾補「引用前對帳（見 memory 帳本格式段）」。

### 帳本規則 SSOT

frame-scoped 格式、引用三態 + 回寫、pending-outcome、舊條目遷移、exhausted——全部住在 memory `feedback_competitive_analysis_check_own_stack_first.md`「帳本記錄格式」段；本 skill 與 github-repo-research 只寫 pointer、不複寫（防三處漂移）。

## 實作範圍與驗收

- `~/.claude/skills/check-my-stack/SKILL.md` 重寫 + `references/output-template.md` 對應改
- `~/.claude/skills/github-repo-research/SKILL.md` patch（見上 contract）
- memory 帳本格式段擴充（引用三態 / pending-outcome / 舊條目遷移 / exhausted 四條）
- **Carry-over checklist**（宣稱不動的段落，重寫時逐項確認保留）：Division of labor 段、table-width 紀律、Step 1 Explore 硬 gate 原文、anti-pattern 原 6 條（第 5 條改引用）、「禁止虛構先例」條款
- 驗收：prior 清除 grep 零未處理命中；gate 帳區塊在 output template 有固定落點；D2 拍板一次 ship
- 流程：skill-creator → superpowers:writing-skills review → review-zh 繁中副本
