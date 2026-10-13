---
name: research-before-answer
description: Use when answering a factual question about a named repo, package, library, framework, SDK, API, version, release note, deprecation, company, product, market, or person activity, or when making a current-state claim. Do not use for pure framework, principle, design-pattern, or concept explanations, or trivial single-fact lookups you are already certain of. Also invokable manually via /research-before-answer.
---

# Research Before Answer

<!-- 本檔在契約測試底下：scripts/tests/inline-verify-contract.test.sh + evals/eval.yaml + scripts/tests/{decision-table,low-confidence}-output-contract.py — 改動後先跑 contract，再跑 `cd ~/.claude/skills/research-before-answer && skill-up-run run evals/eval.yaml --output-dir ~/Desktop/projects/.claude/trials/skill-up-cli/eval-runs`，最後用兩個 output contract 檢查該 run 的 report.json；python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->

涉及**事實**的問題預設**先查證再回答**，不要用訓練資料編。

## 觸發條件（符合任一即 invoke）

- 具體 repo / 專案 / 套件 / library / framework / SDK
- API / CLI 用法、版本、release notes、deprecation
- 公司、產品、人物、市場近況
- 任何「現狀」「最新」「最近」「這個 X 怎麼用」類問題
- 混合題（框架 + 事實）→ 先查事實部分，再套框架

**不觸發**：純框架 / 原則 / 設計模式 / 概念解釋（用訓練知識即可）。

## 來源選路：先分最新外部題與個人歷史

1. 如果是最新外部事實查核或外部探索，就直接接「外部工具分流」，用網路搜尋、第一手來源或已配置的外部查詢工具。本機 memory、wiki、session、報告與歷史收錄不作探索入口，也不作搜尋失敗的替代；收錄內容無法代表最新外部資訊。
2. 如果同時問「我能不能用」，就並行讀目前帳號、設定或即時資格回應；「我的」不因此觸發個人歷史檢索。外部功能現況與本人資格分開舉證。
3. 如果是個人歷史、既有決策或經驗回顧，就接「個人資料層」。混合題只對回顧部分查本機紀錄，最新外部部分仍走第 1 步。

完成條件：每個待答問題已分到外部現況、本人現況或個人歷史，選定來源後再查詢。

### 個人資料層（只用於歷史／決策／經驗回顧）

- **wiki** (`~/.claude/wiki/`): 個人經驗／偏好／踩過的坑
  - 寫/改 entity 前：(1) `cat ~/.claude/wiki/_schema.md` 確認格式 (2) `grep -ri "<keyword>" ~/.claude/memory/` 撈既有 reference / project / feedback memory，不要只憑當次對話
- **session memory** (`~/.claude/memory/`, canonical 由 `autoMemoryDirectory` setting 指定): hand-curated reference / project / feedback / user 4 類 .md + 兩層 index 結構（MEMORY.md + `_index_*.md` cluster files，2026-05-07 起）
  - Step 0：**query 要回顧個人歷史（「我之前 X 怎處理」「我有沒有寫過」）→ 並行查 wiki 與 memory**，用既有散文／session 檢索路由列出 hit file，補捕 MEMORY.md 沒列 pointer 但 file 還在的 standalone reference。只有「我的 X setup」「我這台機器」時，依上一段讀目前設定，不啟動本段。
  - Step 1：`cat ~/.claude/memory/MEMORY.md` 看索引（含 `### Cluster indexes` + `### Standalone reference` 兩段）
  - Step 2：MEMORY.md 看到相關 cluster pointer → `Read ~/.claude/memory/_index_<topic>.md` 看 sub-entries
  - Step 3：drill 進具體 topic file 取細節（**注意**：cluster index 內每 entry 的 1 行 description 通常已足夠形成 informed opinion，不要無腦 Read 對應 topic file 浪費 context）
  - Cluster 結構是動態的（每次重新 `ls _index_*.md` 拿當下狀態，不要記住固定 cluster list），規則見 `feedback_memory_cluster_maintenance.md`

### 外部工具分流

針對問題核心選工具，不要泛泛「搜相關資料」：

| 問題類型 | 工具 |
|---|---|
| SDK / library 用法 | Context7 (`mcp__context7__*`) |
| GitHub repo / issue / PR | `gh` CLI |
| 套件（npm / pypi / crates） | registry search 或 WebSearch |
| 市場 / 人物 / 公司動態 | WebSearch、Exa |
| 深度多輪研究 | `Skill(deep-research)` 或 `Workflow({name:"deep-research-paced"})` |

分流後，如果使用者要補查社群評價、實際使用經驗或跨平台評論，或明確指定 Monid，就在任何 Monid 呼叫前讀 [Monid 當次選用](references/monid-opt-in.md)，照其中步驟提出選項與核對當次授權；一般文件查詢不加問。沒有選用時沿原路查證，不把 Monid 當自動 fallback。下方搜尋配對、正文抓取與來源核對規則照常適用。

### 搜尋 layer：同 query 一輪 nav + WS（2026-06-01 結案保留，agent_type 範圍化）

任何「給 query 找 URL」場景，一輪搜尋保留同 query 的 **LCU Google SERP + WebSearch**：

1. 依目前 LCU server 的 initialization instructions 與 tool descriptors，在 `mcp__lcu__js` 建立自己的 Google 搜尋分頁。`createBrowserTab`／`goto` 操作碼保留完整的 `https://www.google.com/search?q=<URL-encoded query>` 字面值，實際導航並讀回頁面；只印 URL 不算搜尋。
2. 確認 LCU provider 沒有 isError，且頁面讀回有可用的搜尋結果，再在另一則訊息 call `WebSearch`，query 使用同一個原字串。未載入／失敗時停止並回報，不自動啟動 OBU、Cua 或 Agent Chrome。
3. 交叉比對兩份真實結果；收尾只關自己的搜尋分頁，不處理使用者其他分頁。正式 host 的 Stop／SubagentStop 收尾不代替成功讀頁的證據。

LCU 只改變 browser 入口；不取消同 query 配對、官方來源核對或成功 ticket 的要求。

**規則（2026-05-11 ticket model）**：

- 每張 nav 給一張 query-specific ticket，每次成功 WebSearch 消耗一張同 query ticket
- **順序**：先 navigate 再 WebSearch（不是嚴格同 message 並行 — `PreToolUse` hook fire 時 nav 必須已寫進 transcript，所以拆兩個 message 比較穩）
- **被 block 的 WS 不消耗 ticket**（retry-friendly：補 nav 後可直接 retry 同 query WS）
- **同 query 跑兩次成功 WS 會被擋**（結果一樣浪費 quota；要再跑請補新 nav 表達明確意圖）
- **不同 query 不共用 ticket**（每個 query 自己配對自己的 nav）

**強制範圍（2026-06-01 結案）**：hook 只硬擋兩種 context — **main session** 跟 **`parallel-search` agent**；其他所有 fan-out subagent（deep-research-paced 的 Search / Verify agent 等）一律**豁免**、WebSearch 自由（否則上百個平行小兵被迫各開 chrome 會塞爆真實瀏覽器，實證見 trial review）。

**派 subagent 做配對搜尋 → 用 `parallel-search` agent**：`Agent(subagent_type:'parallel-search')` 或 workflow `agent(prompt, {agentType:'parallel-search'})`。丟一個 query，它用自己的正式 LCU 呼叫讀 Google SERP，再把 SERP + WebSearch 兩段原始結果並列回來、自己關分頁，**不合成留給呼叫者**。如果派工後端無法提供正式 LCU MCP 與 host identity，就沿用可提供這些能力的原生 subagent 路徑；兩者都不可用時停止並回報，不用 Bash shared-client 假造正式接線。

Hook: `~/.claude/hooks/websearch-parallel-enforce.sh`（agent_type gate：main + `parallel-search` 強制、其餘 subagent 豁免；subagent 走 `agent_id` → 自己 transcript 的 redirect）。覺得不好用 → 移除 `settings.json` PreToolUse `WebSearch` matcher。

SERP 抽取 JS pattern 跟試用背景見 `~/.claude/memory/reference_search_tool_comparison_2026_05_10.md` + `feedback_websearch_misses_official_docs.md` + `feedback_parallel_decision_by_structural_failure.md`。

### URL 內容抓取

先看這次抓頁面要拿來做什麼，再選工具。`WebFetch` 回的不是原文：頁面先交給小模型照你的 prompt 改寫成回答。它回 200、讀起來通順，細節卻可能被改掉或漏掉（實例：從相對日期推錯年份、讀錯表格欄位、憑空加一段「官方回應」），而且這種錯不會命中下面任何退路條件——「回傳看起來完整」不是判斷依據。

- **要讀整篇、研究一篇文章，或要引用頁面上的數字／日期／原句** → 不用 WebFetch。用網址抓取退路（見 WIRING.md「非官方內容抓取」）把正文存到 `<scratchpad>/<名稱>.md`（輸出已是正文 markdown；不要印到畫面上，長頁會吃掉 context），再用 Read 讀。長文先 `grep -n '^#'` 看標題，按段落範圍讀。寫給使用者的數字、日期、引文都從這個檔取，附行號。
- **只是導航**（找連結、確認頁面還在、判斷該讀哪一頁哪一段）→ 可用 `WebFetch`（快、省 token）。它的回答只用來決定下一步；要寫成事實就回上一條抓原文。

**WebFetch 拿 4xx/5xx 或內容明顯不夠（403 body / "Forbidden" / 亂碼 / < 200 字模板 / "Please enable JavaScript"）→ 必須立刻 fallback，不要回覆「官網沒爬到」「403 抓不到」就跳過——fallback 是 mandatory 不是 optional（踩坑紀錄 [[feedback_webfetch_fallback_must_trigger]]）。** 兩段退路階梯：

🔌 接線點：非官方內容抓取 — 見 WIRING.md
2. exit 75/1 才升 LCU MCP（`mcp__lcu__js`）— 建立自己的任務分頁，導航指定 URL 並讀回實際內容；如果遇到 CAPTCHA、登入或核准，就按既有權限邊界回報。LCU 不可用時停止，不改走 OBU／Agent Chrome，也不把連線失敗當內容不存在。

常見觸發：

- reddit.com 整域 hardcoded refuse
- 站需 cookie / 登入 wall
- JS-only 內容 server-side fetch 拿不到
- WebFetch 抓回來但 incomplete（亂碼 / 模板 / 空白）

如果頁面是 SPA，就在抽取前依 LCU 的當次 API 說明等待實際內容，再讀回；不拿傳輸成功代替頁面就緒。

讀內容走網址抓取退路（見 WIRING.md「非官方內容抓取」）；只在它 exit 75/1 時啟用 LCU browser，不額外開重複分頁。

### 執行模式

- **淺題**（單次查）：沿「來源選路」直接查選定來源；最新外部題不額外讀 wiki index。
- **深題**（多輪研究）：派**背景 subagent**（`run_in_background: true`），**main session 繼續做其他工作、不要用 `sleep` 空轉輪詢**；背景 agent 完成會自動送 task-notification，收到才 merge（禁止 `Bash sleep 60` 類 poll、也不要 Read 未完成的 output 檔）
- **個人歷史**：查 wiki／memory；如果要找對話原文，就走 session 檢索路由。
- **外部搜尋受阻或沒答案**：如果已有原文 URL，就接「URL 內容抓取」；否則依既有授權換已配置的外部來源類型。仍受阻時回報具體缺口，不改查本機歷史收錄，也不把未找到當成不存在。
- **混合題**：外部現況、本人目前資格與個人歷史分開查、分開標出處；歷史紀錄不能佐證外部現況。

答案成稿後 → 接下方「交付前 inline 自查（R1–R3）」再送出。

## 交付前 inline 自查（R1–R3）

答案寫完、送出前逐條自查（與 rba-verify 每週離線抽驗同一套 rubric——那邊每週抽 3 個 session 事後重判，這裡是交付當下的第一道防線；2026-08-12 因連兩週抽驗有真 FAIL 而加入）：

- **R1 有真的查**：本回合有至少一次真實第一手查證 tool call。外部題可用 WebSearch / WebFetch / chrome / gh / registry / Context7；個人或本地現況可用權威檔案的 Read、git／CLI 原始輸出。nested agent 只有把實際 tool evidence 帶回 transcript 才算，agent 自述不算。invoke 完直接憑訓練資料作答＝違規。
- **R2 答案附出處**：先盤點答案內每個會改變決策或直接回答問題的 claim；推薦、排除、排序理由、decision table 每一列與「X 會增加成本／風險」這類方案取捨句都各算一條。每條都要有可追溯指針（URL / 文件名 / 指令輸出），表格逐列同列放；表格外的共用來源不能替未對應的列補證。沒有指針的 claim 必須刪除或原位標「未驗證」，且不得拿來推薦或排除方案。
- **Decision table 固定形狀**：只要表格會推薦或排除方案，就必須含欄名逐字為 `來源` 的獨立欄；每列在 `來源` 欄用「取捨 claim → URL／文件／指令輸出」逐項對應。若該列含未驗證項，就在同列原位標「未驗證（不得影響判斷）」。表格後的證據清單只能補充，不能代替該列來源；任一決策列的 `來源` 欄空白就不得交付推薦。
- **未知不是反證**：「沒有證據證明 X 安全／便宜／相容」仍是未驗證，不能改寫成「因此不選 X」；只能在同列原位標「未驗證（不得影響判斷）」。若一句話混合已驗證機制與未驗證影響，拆成兩格或兩句，判斷只引用已驗證部分。
- **R3 查答一致**：主張與查到的內容一致；查證未覆蓋的區間不得當成推薦理由；跨來源合併身分（帳號 / 方案 / 額度池 / 版本）要有共同 identifier——無版號的成績不得掛到具體版號上。機制／trial verdict 另逐項對照 `observed metric → target outcome → attribution`：只有 proxy metric、未直接量到 target 時，只能寫「目前無法判定」，不得斷言已解決或未解決。
- **信心標記是輸出的一部分**：一個數字的來源只有第三方轉述、官方頁 4xx／內容截斷、僅 SERP 摘要、或對象自稱（README／官網自述且無公開方法論）→ **寫下該數字的當下**就前置 ⚠️ 並在同一行註「未經官方確認（來源：<名＋URL 或指令>）」——來源要是可點的 URL 或可重跑的指令，只寫來源名字不算。比較語（「100% working」「higher quality than X」）與倍數同樣算數字；先平述、打算文末補標的路徑不存在。
  - anchor（兩段只差 ⚠️＋同行來源註這一件事；審查員對著放位置、不按比例）：❌「從一次提示（宣稱 60–80%）到 spec + 人審（99%）」／✅「從一次提示（⚠️ 60–80%，未經官方確認，來源：README https://github.com/NeoLabHQ/context-engineering-kit#readme）到 spec + 人審（⚠️ 99%，同上來源）」。「宣稱」「自稱」字樣本身不算標記；第一手指令輸出（`gh api`、本機 grep）的數字不在此列、不要補 ⚠️
- 任一條過不了 → 修答案（補查 / 補指針 / 收斂宣稱範圍）再送出；修不了就在答案裡明寫「未驗證」「低信心」，不得靜默放行。

完成判準：R2／R3 對答案內**每個**決策級主張都指得出對應證據，不是抽查幾條。自查完成後接下方「抽樣 dispatch verify」判斷要不要派工。

### 抽樣 dispatch verify（決策級輸出才跑；2026-08-18 加）

上段自查是自我申報——2026-08-12 加入後，rba-verify 離線抽驗仍抓到漏列 claim 與過度外推。全量加會太貴，所以答案含決策級 verdict（KILL／採用／重啟／值得・不值得／列選項要使用者拍板），且符合下列任一高風險形狀時 dispatch：

1. 本回合有 ≥3 次第一手查證；local authoritative Read 與 nested agent 帶回的真實 tool evidence 都計入
2. decision table／兩個以上替代方案比較，答案要推薦或排除其中一項
3. 用 proxy metric 判斷機制／trial 的 target outcome
4. 用未直接量測的成本、風險、cleanup、延遲等定性理由排除方案

成立 → 呈現答案**前**派 `Agent(subagent_type: skill-verify-auditor)`（sonnet+low、tools 僅 Read）：description 固定含 marker 字串 `skill-verify:research-before-answer`（採用率統計 grep 用，不要改字）；prompt 內嵌**準備直接送出的完整 draft**＋上方 R1–R3 與信心標記規則原文，要求逐條 PASS/FAIL＋一句證據引述。最後一行只能是 `VERDICT: COMPLIANT` 或 `VERDICT: VIOLATIONS: <R 編號>` 其中一種；逐條結果有任一 FAIL 時，即使最後一行誤寫 COMPLIANT 也按 VIOLATIONS 處理。**本回合這個 skill 只有一次 auditor 額度**：不論結果如何都不得重派，也不得用 SendMessage 續問同一個 auditor。末尾那行的狀態只能是下列四個之一：

- 全 PASS → 「🔎 self-verify: COMPLIANT」
- 任一 FAIL 且已修正 → 修 draft 後直接交付，標「🔎 self-verify: FIXED_AFTER_AUDIT（R#）」並明寫「未經第二次獨立稽查」
- 任一 FAIL 且修不掉 → 停止推薦式結論，**把不實或佐證不足的主張從 draft 刪除或收窄**，只交付已驗證事實、未解決問題與「🔎 self-verify: FAILED（R#）」
- auditor error / timeout / 空輸出 / 格式錯誤 → 照發、標「🔎 self-verify: SKIPPED (agent error)」

audit 後不得新增或改寫推薦理由，交付文字須等於修正後的 draft。沒有命中高風險形狀時，上段 inline 自查即為終點。

## 記憶升級

學到 non-obvious pattern → 主動提議升級 wiki entity（使用者點頭才寫）。

## 手動觸發

`/research-before-answer` 在對話中直接呼叫，無需等待自動觸發。

## 核心原則

**寧可多搜一次，不要編。**

## 踩過的坑（撞新 case 就往下補）

- WebSearch 排名容易漏掉官方文件，需搭配 chrome SERP nav 並行比對才不會漏 → [[feedback_websearch_misses_official_docs]] / [[feedback_parallel_decision_by_structural_failure]]
- WebFetch 拿到 4xx/5xx 或內容明顯不夠（403 / 亂碼 / 模板）時必須立刻 fallback，不能回「抓不到」就跳過 → [[feedback_webfetch_fallback_must_trigger]]
- 用瀏覽器抽取 SPA 內容時要按頁面狀態等待再讀，通用抓法會漏（舊瀏覽器工具時期的經驗，原文已退役、公開版不附）
- 查證做得再全、交付端仍會丟資訊：低信心標記被平述、來源限制被整條省略、無版號成績掛到具體版號（rba-verify 離線抽驗連兩週抓到真 FAIL）→ 2026-08-12 加「交付前 inline 自查」段；抽驗 verdict 見 trials archived.md rba-verify 段
- 2026-08-25 抽驗抓到三種漏網：decision table 的取捨列沒逐列出處、proxy metric 被外推成 target verdict、未查證的 cleanup／成本理由被拿來排除方案；另有 auditor 回 `R2 FAIL` 卻同時寫 `VERDICT: COMPLIANT`。修法是 claim inventory、metric→target→attribution、替代方案理由納入 R2/R3，以及互斥 verdict＋final draft 重驗。
- 2026-08-29 同一份 draft、同一條「信心標記」規則，auditor 兩輪各自解讀（第一輪抓 2 處漏 token 倍數、第二輪只抓 token 倍數）：規則只寫判準沒給實例，「宣稱」兩字被當成標記、對象自稱沒列進來源清單。修法＝來源清單補「對象自稱」、附一對只差 ⚠️＋來源註的 ❌／✅ anchor、第一手指令數字明文排除；同稿加 anchor 後 2/2 抓全，壓力場景 4 FAIL／1 PASS／3 N-A 零誤標。機制借自 NeoLabHQ/context-engineering-kit meta-judge（改寫不抄）；trial `cek-anchor-rubric` review 2026-09-05
