# check-my-stack v2 spec review 合成報告（2026-07-05）

對象：[2026-07-05-v2-redesign-spec.md](~/.claude/skills/check-my-stack/specs/2026-07-05-v2-redesign-spec.md)
配置：T3（簡化軸 12 條 / 弱點軸 16 條 / 一致性軸 14 條 / 意圖對齊 main in-context）+ T4（codex 12 條 / agy Gemini 3.5 Flash 6 條；Pro 依使用者指示未跑）
原始 findings 共 ~59 條，合成後 7 個主題。

## 跨流共識（五路中 ≥3 路命中）

### C1. Step 5.5 cheap-trial gate 不可執行（5/5 路命中，全場最強共識）

三路判 Blocker。「半天內可實測」LLM 無法客觀判定（fail-open 自由裁量）、「必須實測不准出判決」會卡死（缺 API key / auth / 環境）或被 scope-lawyering 繞過、把決策評估膨脹成整合測試、無條件觸發是成本炸彈、RTK 正例其實是 4 週 trial 不是半天 cheap-trial（證據錯配）。

**定案解法（合成）**：
- 條件觸發：只在「草判決 = 模糊地帶否決」時啟動（採用/trial 判決本身就是實測入口）
- 三態 triage：`Runnable now`（有 install 指令 + 本地可跑輸入 = 必測）/ `Runnable with user approval`（附最小實測命令 + 風險）/ `Not runnable cheaply`（枚舉阻斷因子：付費帳號 / 互動 auth / 缺資料 / 硬體；附「如果可測會跑的指令」）
- session 內測不完 → 判決標 `provisional` + 附可執行測試計畫
- 涉 install → 先過 safe-trial trigger 判斷（audit 成本計入預算；超預算 → 允許紙上判決但標「未實測，因 audit 成本」）
- 測後收尾二擇一：當場移除 or 登錄 trials/active.md（禁無主殘留）
- in-session 測不能定案但正向 → 強制升 Step 6 trial 判決；正例只留 headroom，RTK 移去 Step 6

### C2. Step 0 快殺通道防護不足（4/5 路）

弱點軸 B1：位置在 Step 1 前卻依賴未對帳的分母印象；單憑帳本 lineage 違反自家「帳本是 claim」anti-pattern；跳過 frame 搜尋會重演 graphify。agy：v2 越重、快殺越變避難所。一致性軸 H1：通道 under-inclusive——billing 出局 / agent-in-loop 軸錯這類 structural dealbreaker 不在兩條件內。簡化軸 H1：「超集覆蓋」通道在 Step 0 位置上循環（需要盤點結果才能判）。

**定案解法（合成）**：Step 0 資格三件套缺一不可——(a) lineage 條目引用 + 一句同型論證（Open Q2 = yes）+ 本案 frame 與 lineage frame 同型檢查；(b) 對該條目 mini 對帳（否決依據的分母還在？upstream 有無重大變化？舊無 frame 條目只當線索、不構成快殺資格）；(c) 新增第三通道：structural dealbreaker 紀律條目命中（billing / agent-in-loop / mission-critical 不適配），須引條目 + 適用論證。
**Contested（見 D1）**：「超集覆蓋」通道去留。

### C3. Gate 過多會橡皮圖章化 → 合併 + artifact 化（4/5 路，polarity 對撞的合成解）

簡化軸 B1（Blocker）：3.5 / 5.5 / Step 6 舉證是同一失敗模式的三重防禦，prose 自證型 gate 必被填空走過場；使用者 63 次介入的真實形狀是「判決時的選擇性 review」不是全程管線。弱點軸 B2（Blocker）：gate 沒有輸出合約 artifact = 部分執行不可偵測。codex：分層 core path / expanded gates。

**定案解法（polarity 合成）**：刪 Step 3.5、5.5 作為獨立步驟 → Step 6 內單一「**否決前挑戰 pass**」：草判決 = 否決/landscape 且非 Step 0 快殺 → 回答固定四問（機制層驗了嗎 / 換 frame 呢 / 真的偷不了嗎 / 半天能實測為何沒測），任一問翻案就回圈。挑戰 pass 的輸出是 Verdict 前強制「gate 帳」區塊（走哪個通道 + 證明 / 四問各一行：驗過→證據、未驗→明寫），事後可 grep 稽核。抗橡皮圖章的分界：**產出物是貼指令輸出的 gate 抗、自述 prose 的 gate 不抗**。

### C4. Prior 清除清單不完整（3/5 路）

spec 只列 3 處，實際至少 6 處：SKILL.md L8 overview「usually a superset」、L37 Step 2 檢索詞「collapse cases」（檢索層就只召回否決先例）、L41 Step 3「Most rows resolve to ≈0」、L53 Step 6 強制 superset root cause、output-template L21 Block 2 key collapse、L38 Verdict 同款。
**定案解法**：完整清單入 spec + 實作驗收條件 `grep -in "collapse|superset|toward zero|thin"` 逐命中處理（保留須附理由）；Step 2 檢索詞改中性（any outcome）；Step 3 改「保留機制、改寫商數示例語句」。

### C5. 帳本閉環缺口（4/5 路）

codex Blocker：v2 沒真正修掉 stale ledger——缺 schema 強制欄位 / 失效條件 / 更新觸發 / superseding。簡化軸 M3：read-side 修了、write-side 漏了。弱點軸 M2/M6：trial/抽件判決需 `pending-outcome` 標記 + 結局回寫；舊無 frame 條目遷移規則缺席。一致性軸 M2/M3：對帳規則三處複寫需 SSOT（= memory 格式段，其他兩處寫 pointer）；自動寫回 vs github-repo-research ask-first 慣例分歧須明寫例外。
**定案解法**：擴充 memory「帳本記錄格式」段（SSOT）——引用時三態輸出（仍成立 / 部分失效 / 已失效）+ 失效當場回寫；trial/抽件標 `pending-outcome` 指向 active.md entry；舊條目 = 線索非資格、引用時增量補 frame；Step 6 明寫「本 skill 判決自動寫回（graphify 教訓，ask-first 慣例的刻意例外）」+ row 長度上限、細節外掛 reference 檔。

### C6. Gap = pain 防線被誤刪（3/5 路；一致性軸 B1 = spec 內部矛盾）

Step 4 重寫刪了 real-gap check，但 anti-patterns 宣稱「原 6 條保留」而第 5 條引用的正是被刪步驟；「absence 非 pain」是「先盡力讓它成立」姿態下防過度建議的承重牆（使用者翻過一次 awesome-harness 過度建議）。
**定案解法**：Step 4 = 最佳 frame 搜尋 + 每個候選 frame 必過 pain-vs-absence 過濾（答「對應 Block 1 哪個缺口 / 哪個可升級分母」，答不出不進判決）；frame 錨定 Block 1 具名項目、上限一個替代 frame、找不到寫 none found；anti-pattern 5 改指新 Step 4。

### C7. 對帳範圍與 probe 錯配（4/5 路）

無界對帳（每列 which/npm）成本高且誘使規避；probe 清單只驗 CLI 裝機，但立案事故（PullMD / brooks-lint）是 fetch 工具退役與 0-spawn agent——revealed adoption 沒給驗法。
**定案解法**：對帳限 load-bearing 列（Block 2 商數引為除數的 2-4 列，其餘標「未對帳」）；probe 按類型分欄（CLI → which 系；skill/agent → session jsonl invoke 計數；hook → audit log；排程 → launchd last-run）；achieved 標記二分「裝機已驗 / 採用已驗」，不准檔案存在冒充採用。

## 單流但採納的條目

- codex #3：「預設立場 = 引入」改寫為「先建立最強 adoption hypothesis、再嘗試推翻」；verdict 無 default、只有分析順序有 default（+ 弱點軸 N3：姿態管力氣分配、不管證據標準——一句進定位段）
- codex #10：判決加第五類 `watch/defer`（必附 revisit trigger）
- codex #11 + 弱點軸 M5 + 一致性軸 M6：行動出口允許合法空值「無——翻案條件：X」；快殺判決豁免行動路徑欄（防 padding 編造）
- codex #12 + 一致性軸 N1 + 弱點軸 N2：github-repo-research patch contract——memory hit 標 `unchecked prior`、對帳（裝機 + 自家 skill 引用 grep）後才升格 evidence；frame 同型檢查一併做；description 第三入口補半句
- codex #6：抽件狩獵最低 protocol（README / API surface / examples / config / hooks / CLI entrypoints；輸出 stealable mechanism / graft point / reason rejected 三欄）+ agy #6：閉源工具自動降級「API/架構概念層」並註明
- 弱點軸 H3：舉證對稱化——trial 判決必附 KPI + review date + kill 條件 + active.md 登錄；抽件判決必附檔案/機制名 + 落點 + 下一步（禁「值得偷」空頭抽件）；模糊地帶定義 fail-closed =「凡未過 Step 0 資格的否決一律視為模糊」
- 弱點軸 H5（部分）：frame 重評必聲明 delta（工具端或 stack 端變了什麼），無 delta 不開案
- 一致性軸 H2：trial 出口明寫登錄 active.md H2 格式義務（不依賴 safe-trial 自動登記；headroom 型純 library install 落在 safe-trial 例外內）
- 一致性軸 N4：實作範圍加 carry-over checklist（Division of labor 段、table-width 紀律等宣稱不動的段落）
- 軸清單（Open Q3）：挑戰 pass 四問即固定問題形式（codex #8 的問題形式 + 簡化軸固定制 + 弱點軸 N1 混合制自然收斂）；另留一欄「本工具特有軸」可填「無、已檢查」

## 否決的建議（附理由）

- agy #2 `stack-manifest.json` SSOT + agy #4 `active-pains.md`：新增自維護 artifact = 新的 stale 面，正是本案病灶（帳本 stale）的再生產；load-bearing 列限縮 + Block 1 錨定已用更輕機制解掉同一問題
- codex #7 maturity 四欄位（installed / invoked / integrated / accepted）：方向對但四欄過重，二分「裝機已驗 / 採用已驗」+ 類型化 probe 已覆蓋失效類型

## Contested — 使用者拍板

- **D1 Step 0「超集覆蓋」通道去留**：簡化軸主張移除（位置循環：需盤點結果才能判、留著 = v1 anchoring 後門）；弱點軸/codex/agy 主張加防護保留（active-installed 超集具名等）。合成推薦：移除，超集型快殺在 Step 3 後自然浮現、不需專門通道。→ **已拍板（2026-07-05）：移除**
- **D2 分段 ship**（簡化軸 N4）：姿態/prior 清除與 gate 機制分開 ship 以利 trial 歸因 vs 一次 ship。合成推薦：一次 ship（gate 已瘦身成單一挑戰 pass、分段 = 兩輪觀察期）。→ **已拍板（2026-07-05）：一次 ship**
- **D3 exhausted 標記**（弱點軸 H5）：同工具 3 個 frame 否決 + 零殘值 → tool-level exhausted、翻案只認新 delta。與 frame-scoped 改革方向有張力。合成推薦：採，但寫成「exhausted 後翻案僅認 delta 證據」＝軟封存。→ **已拍板（2026-07-05）：採**

## 意圖對齊檢查（main in-context）

合成後方向仍對準使用者原始意圖：挑戰 pass 觸發位置（判決時、否決草案上）= 使用者 63 次介入的實際位置；Step 4 frame 搜尋留在 core path（主動性保留）；H3 舉證對稱 + C6 pain gate 守住「判決誠實度不降」的 non-goal。無意圖偏離 finding。

## 附：T4 執行備註

agy CLI 語法陷阱：`agy -p --model X "prompt"` 中 `-p` 會把 `--model` 字面吃成 prompt（-p 取下一個參數為值），正確語法 `agy --model X --print-timeout 10m -p "prompt"`。review-spec skill 文件內的範例指令是舊語法、需修正。agy Flash 前兩次無效輸出即此因，修正後 6 findings 全部有效。
