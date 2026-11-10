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

分流後，如果本次研究需要社群評價、實際使用經驗、跨平台評論或公開網頁資料，且 Monid 能補上資料缺口，就在任何 Monid 呼叫前讀 [Monid 贈額試用](references/monid-opt-in.md)。使用者已批准在剩餘原始贈額內跨任務直接使用，不逐次詢問；照 reference 查價、核餘額，贈額不足就退出並移除入口。不為耗贈額增加查詢；當次拒用、資料已足或不需外查時沿原路。下方搜尋配對、正文抓取與來源核對規則照常適用。

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

**派 subagent 做配對搜尋 → 用 `parallel-search` agent**：`Agent(subagent_type:'parallel-search')` 或 workflow `agent(prompt, {agentType:'parallel-search'})`。丟一個 query，它用自己的正式 LCU 呼叫讀 Google SERP，再把 SERP + WebSearch 兩段原始結果並列回來、自己關分頁，**不合成留給呼叫者**。如果目前 session 的工具列表本身沒有 `WebSearch`（例如在第三方 vendor runtime 下），則不派 `parallel-search`（因其內部呼叫 `WebSearch` 一樣不可用），直接由呼叫者走已配置的搜尋 API 搭配正式 LCU；如果派工後端無法提供正式 LCU MCP 與 host identity，就沿用可提供這些能力的原生 subagent 路徑；兩者都不可用時停止並回報，不用 Bash shared-client 假造正式接線。

Hook: `~/.claude/hooks/websearch-parallel-enforce.sh`（agent_type gate：main + `parallel-search` 強制、其餘 subagent 豁免；subagent 走 `agent_id` → 自己 transcript 的 redirect）。覺得不好用 → 移除 `settings.json` PreToolUse `WebSearch` matcher。

SERP 抽取 JS pattern 跟試用背景見 `~/.claude/memory/reference_search_tool_comparison_2026_05_10.md` + `feedback_websearch_misses_official_docs.md` + `feedback_parallel_decision_by_structural_failure.md`。

### URL 內容抓取

先看這次抓頁面要拿來做什麼，再選工具。`WebFetch` 回的不是原文：頁面先交給小模型照你的 prompt 改寫成回答。它回 200、讀起來通順，細節卻可能被改掉或漏掉（實例：從相對日期推錯年份、讀錯表格欄位、憑空加一段「官方回應」），而且這種錯不會命中下面任何退路條件——「回傳看起來完整」不是判斷依據。

**先判斷是否為使用者直接交付的 X／Twitter 研究連結**（`/status/` 貼文或 X 長文；不是日報／workflow 批次來源）。如果是，就走以下路線，不套用下方「exit 75/1 才升瀏覽器」的退路條件：

1. 以 LCU MCP（`mcp__lcu__js`）開啟指定連結，等待實際內容載入，讀回貼文、附帶或連到的 X 長文、程式碼與外部連結；只操作任務指定或自己建立的分頁。`x-fetch` 回成功仍可能只有長文入口，所以不先跑腳本來決定是否開瀏覽器。
2. 如果研究需要留言、作者串文或引用，就補跑 X／Twitter 抓取退路（見 WIRING.md「非官方內容抓取」），把回件當補充，不當全量討論。
3. 對照研究問題確認所需正文、程式碼與來源連結已讀到；缺少的項目明寫缺口，不以 exit 0 或頁面載入成功當作完整。LCU 不可用時停止並回報；登入、CAPTCHA 與核准照既有權限邊界處理。取得內容後接來源查證，答案成稿後接「交付前 inline 自查（R1–R3）」。

**公開 HTML 研究頁（文章、產品官網、HTML 文件／表格）預設先用 Context.dev Scrape API**，取得 Markdown 後再查證與分析。它不必開瀏覽器、subagent 與腳本都能呼叫，且保留表格結構。先分流：需要本人登入狀態、庫存或視覺／互動的頁面走正式 LCU；Reddit 沿用專用腳本；官方原生 Markdown 直接讀；直接交付的 X 研究連結走上方路線。日報／workflow 的既有批次腳本不因這條研究規則自動改接服務。

1. 抓取並存檔，不把 key 或整份回件印到畫面：
   ```bash
   curl -s https://api.context.dev/v1/web/scrape -H "Authorization: Bearer $(cat ~/.config/context-dev/api-key)" -H 'Content-Type: application/json' -d '{"url":"<url>","formats":{"markdown":true}}' > <scratchpad>/<名稱>.json
   python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));m=d.get("markdown") or {};open(sys.argv[2],"w").write(m.get("data") or "");print(d.get("url"),m.get("success"),len(m.get("data") or ""),(d.get("cache_metadata") or {}).get("status"),(d.get("key_metadata") or {}).get("credits_remaining"),d.get("message",""))' <scratchpad>/<名稱>.json <scratchpad>/<名稱>.md
   ```
   需要現況時在 JSON 加 `"maxAgeMs": 0`（預設可回三天內快取）；`cache_metadata.status` 是 `hit` 時不宣稱即時抓取。只送指定公開 URL，不帶 cookies、自訂 header 或私人檔案。免費方案同時最多 2 個請求，多頁要逐一抓。
2. 確認印出的 `url` 對應本次 URL（允許已確認的官方重新導向）、`success` 為 True，再 Read `.md` 檔，核對研究所需正文、程式碼、表格條件與來源連結。內文只剩開頭一句加「…」或出現登入／訂閱提示，代表要登入才看得到，改走正式 LCU。
3. 如果 Context.dev 回錯（`message` 非空，如額度不足 402、並行上限 429）、`success` 不是 True、或缺研究所需內容，就改用 Firecrawl Scrape API（不開瀏覽器）；但第 2 步那種截斷或登入／訂閱提示不走這條，直接開正式 LCU，因為 Firecrawl 與網址抓取退路（見 WIRING.md「非官方內容抓取」）一樣只拿得到截斷版。抓取並存檔，不把 key 或整份回件印到畫面：
   ```bash
   curl -s -X POST https://api.firecrawl.dev/v2/scrape -H "Authorization: Bearer $(cat ~/.config/firecrawl/api-key)" -H 'Content-Type: application/json' -d '{"url":"<url>","formats":["markdown"]}' > <scratchpad>/<名稱>-fc.json
   python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));data=d.get("data") or {};meta=data.get("metadata") or {};md=data.get("markdown") or "";open(sys.argv[2],"w").write(md);print(meta.get("sourceURL"),d.get("success"),len(md),meta.get("statusCode"),meta.get("cacheState"),meta.get("creditsUsed"),d.get("error",""))' <scratchpad>/<名稱>-fc.json <scratchpad>/<名稱>-fc.md
   ```
   需要現況時在 JSON 加 `"maxAge": 0`（預設可回兩天內快取）；`cacheState` 是 `hit` 時不宣稱即時抓取。只送指定公開 URL，不傳登入 cookies、私人檔案或憑證，不選 Summary、Query 或模型 JSON extraction（會多扣點數）。確認印出的 `sourceURL` 對應本次 URL（允許已確認的官方重新導向）、`success` 為 True，再 Read `.md` 檔。
4. 如果 Firecrawl 回錯（`error` 非空或額度不足）、`success` 不是 True、或缺研究所需內容，就接下方網址抓取退路（見 WIRING.md「非官方內容抓取」）；把 Context.dev 與 Firecrawl 的缺口記清楚，不重複扣額重試。腳本也失敗時，沿下方正式 LCU 升級規則處理。取得內容後接來源查證與「交付前 inline 自查（R1–R3）」。

Firecrawl 的 fallback、Reddit 與既有日報／workflow 批次來源沿用以下路線：

- **要讀整篇、研究一篇文章，或要引用頁面上的數字／日期／原句** → 不用 WebFetch。用網址抓取退路（見 WIRING.md「非官方內容抓取」）把正文存到 `<scratchpad>/<名稱>.md`（輸出已是正文 markdown；不要印到畫面上，長頁會吃掉 context），再用 Read 讀。長文先 `grep -n '^#'` 看標題，按段落範圍讀。寫給使用者的數字、日期、引文都從這個檔取，附行號。
- **只是導航**（找連結、確認頁面還在、判斷該讀哪一頁哪一段）→ 可用 `WebFetch`（快、省 token）。它的回答只用來決定下一步；要寫成事實就回上一條抓原文。

**WebFetch 拿 4xx/5xx 或內容明顯不夠（403 body / "Forbidden" / 亂碼 / < 200 字模板 / "Please enable JavaScript"）→ 必須立刻 fallback，不要回覆「官網沒爬到」「403 抓不到」就跳過——fallback 是 mandatory 不是 optional（踩坑紀錄 [[feedback_webfetch_fallback_must_trigger]]）。** 兩段退路階梯：

🔌 接線點：非官方內容抓取 — 見 WIRING.md
2. 如果腳本 exit 75/1 或仍缺研究所需內容，就升 LCU MCP（`mcp__lcu__js`）— 建立自己的任務分頁，導航指定 URL 並讀回實際內容；如果遇到 CAPTCHA、登入或核准，就按既有權限邊界回報。LCU 不可用時停止，不改走 OBU／Agent Chrome，也不把連線失敗當內容不存在。

常見觸發：

- reddit.com 整域 hardcoded refuse
- 站需 cookie / 登入 wall
- JS-only 內容 server-side fetch 拿不到
- WebFetch 抓回來但 incomplete（亂碼 / 模板 / 空白）

如果頁面是 SPA，就在抽取前依 LCU 的當次 API 說明等待實際內容，再讀回；不拿傳輸成功代替頁面就緒。

公開 HTML 研究頁先走上方 Context.dev、再試 Firecrawl；如果失敗或缺內容，就接網址抓取退路（見 WIRING.md「非官方內容抓取」），exit 75/1 或仍缺關鍵內容時以正式 LCU 補讀。需要本人登入狀態、視覺／互動或直接交付 X 研究連結時已先分流；既有批次腳本維持原路。

### 執行模式

- **淺題**（單次查）：沿「來源選路」直接查選定來源；最新外部題不額外讀 wiki index。搜尋層只負責找到候選 URL，找到後接「URL 內容抓取」讀過原頁再作答；LCU 不可用時直接走網址抓取退路（見 WIRING.md「非官方內容抓取」）／`gh`／registry，不要退成只剩 WebSearch——SERP 摘要不是頁面（2026-10-15 skill-up：LCU 失敗後 7 個線上題全部停在 WebSearch、0 次抓頁，全 FAIL）。
- **深題**（多輪研究）：派**背景 subagent**（`run_in_background: true`），**main session 繼續做其他工作、不要用 `sleep` 空轉輪詢**；背景 agent 完成會自動送 task-notification，收到才 merge（禁止 `Bash sleep 60` 類 poll、也不要 Read 未完成的 output 檔）
- **個人歷史**：查 wiki／memory；如果要找對話原文，就走 session 檢索路由。
- **外部搜尋受阻或沒答案**：如果已有原文 URL，就接「URL 內容抓取」；否則依既有授權換已配置的外部來源類型。仍受阻時回報具體缺口，不改查本機歷史收錄，也不把未找到當成不存在。
- **混合題**：外部現況、本人目前資格與個人歷史分開查、分開標出處；歷史紀錄不能佐證外部現況。

答案成稿後 → 接下方「交付前 inline 自查（R1–R3）」再送出。

## 交付前 inline 自查（R1–R3）

答案寫完、送出前逐條自查（與 rba-verify 每週離線抽驗同一套 rubric——那邊每週抽 3 個 session 事後重判，這裡是交付當下的第一道防線；2026-08-12 因連兩週抽驗有真 FAIL 而加入）：

- **R1 有真的查**：本回合有至少一次真實第一手查證 tool call。外部題可用 WebFetch / 網址抓取退路（見 WIRING.md「非官方內容抓取」）→Read / chrome（LCU）/ gh / registry / Context7；**WebSearch 與 Google SERP 只算「找到 URL」，不算查證**——那是搜尋引擎的摘要、不是頁面本身，寫進答案的發布日、價格、規格、數字或「有沒有出」都要來自實際讀到的頁面或指令輸出；只有 SERP 摘要時，該句前置 ⚠️ 並註「僅搜尋摘要（來源：<URL>）」，不能寫成讀過該頁；個人或本地現況可用權威檔案的 Read、git／CLI 原始輸出。nested agent 只有把實際 tool evidence 帶回 transcript 才算，agent 自述不算。invoke 完直接憑訓練資料作答＝違規。
- **R2 答案附出處**：先盤點答案內每個會改變決策或直接回答問題的 claim；推薦、排除、排序理由、decision table 每一列與「X 會增加成本／風險」這類方案取捨句都各算一條。每條都要有可追溯指針（URL / 文件名 / 指令輸出），表格逐列同列放；表格外的共用來源不能替未對應的列補證。沒有指針的 claim 必須刪除或原位標「未驗證」，且不得拿來推薦或排除方案。出處放在 claim 同句或緊鄰行，文末統一的「來源：」清單只是補充、不能替代（讀者與審查員都只看同句）。anchor：❌「**發布了**。兩款都在 9 月 22 日推出。…（文末）來源：MacRumors、DataNorth」／✅「gpt-6-sol 2026-09-22 發布（⚠️ 僅第三方轉述：MacRumors https://…，未見 OpenAI 官方頁）；gpt-6-luna 同日（同上）」。「漲多少／差多少」這類比較題，新舊兩個數與算式都是 claim：只拿到一邊時先算頁內能算的（如「空閒＝高峰一半」），再明說缺哪一邊，不以反問代替計算。
- **Decision table 固定形狀**：只要表格會推薦或排除方案，就必須含欄名逐字為 `來源` 的獨立欄；每列在 `來源` 欄用「取捨 claim → URL／文件／指令輸出」逐項對應。若該列含未驗證項，就在同列原位標「未驗證（不得影響判斷）」。表格後的證據清單只能補充，不能代替該列來源；任一決策列的 `來源` 欄空白就不得交付推薦。
- **未知不是反證**：「沒有證據證明 X 安全／便宜／相容」仍是未驗證，不能改寫成「因此不選 X」；只能在同列原位標「未驗證（不得影響判斷）」。若一句話混合已驗證機制與未驗證影響，拆成兩格或兩句，判斷只引用已驗證部分。
- **R3 查答一致**：主張與查到的內容一致；查證未覆蓋的區間不得當成推薦理由；跨來源合併身分（帳號 / 方案 / 額度池 / 版本）要有共同 identifier——無版號的成績不得掛到具體版號上。機制／trial verdict 另逐項對照 `observed metric → target outcome → attribution`：只有 proxy metric、未直接量到 target 時，只能寫「目前無法判定」，不得斷言已解決或未解決。nested agent 回報的「找不到／未能確認／只適用於 X」是查證結果的一部分，合成時逐條原樣進答案，不得刪掉或把限定範圍放大（2026-10-15 skill-up：子 agent 寫 could not find in the docs，final 整段消失，FAIL）。
- **R4 信心標記是輸出的一部分**：一個數字，或「已發布／免費／支援／存在」這類是非判斷，其來源只有第三方轉述、官方頁 4xx／內容截斷、僅 SERP 摘要、或對象自稱（README／官網自述且無公開方法論）→ **寫下該數字的當下**就前置 ⚠️ 並在同一行註「未經官方確認（來源：<名＋URL 或指令>）」——來源要是可點的 URL 或可重跑的指令，只寫來源名字不算。比較語（「100% working」「higher quality than X」）與倍數同樣算數字；先平述、打算文末補標的路徑不存在。
  - anchor（兩段只差 ⚠️＋同行來源註這一件事；審查員對著放位置、不按比例）：❌「從一次提示（宣稱 60–80%）到 spec + 人審（99%）」／✅「從一次提示（⚠️ 60–80%，未經官方確認，來源：README https://github.com/NeoLabHQ/context-engineering-kit#readme）到 spec + 人審（⚠️ 99%，同上來源）」。「宣稱」「自稱」字樣本身不算標記；第一手指令輸出（`gh api`、本機 grep）的數字不在此列、不要補 ⚠️
- 任一條過不了 → 修答案（補查 / 補指針 / 收斂宣稱範圍）再送出；修不了就在答案裡明寫「未驗證」「低信心」，不得靜默放行。

完成判準：R2／R3／R4 對答案內**每個**決策級主張都指得出對應證據，不是抽查幾條。自查完成後接下方「抽樣 dispatch verify」判斷要不要派工。

### 抽樣 dispatch verify（決策級輸出才跑；2026-08-18 加）

上段自查是自我申報——2026-08-12 加入後，rba-verify 離線抽驗仍抓到漏列 claim 與過度外推。全量加會太貴，所以答案含決策級 verdict（KILL／採用／重啟／值得・不值得／列選項要使用者拍板），且符合下列任一高風險形狀時 dispatch：

1. 本回合有 ≥3 次第一手查證；local authoritative Read 與 nested agent 帶回的真實 tool evidence 都計入
2. decision table／兩個以上替代方案比較，答案要推薦或排除其中一項
3. 用 proxy metric 判斷機制／trial 的 target outcome
4. 用未直接量測的成本、風險、cleanup、延遲等定性理由排除方案

成立 → 呈現答案**前**派 `Agent(subagent_type: skill-verify-auditor)`（sonnet+low、tools 僅 Read）：description 固定含 marker 字串 `skill-verify:research-before-answer`（採用率統計 grep 用，不要改字）；prompt 預設內嵌**準備直接送出的完整 draft**＋上方 R1–R4 規則原文，且當承重證據來自無落檔 CLI 時，必須一併附上可由 `Read` 獨立核對的來源路徑與行號（如當前 session transcript JSONL 絕對路徑＋對應 `tool_result` 行號，或既有證據副檔路徑）及關鍵原始輸出片段，禁止只貼呼叫端自述的工具摘要卻要求 auditor 直接當成已核實紀錄（若 draft 過長改走讀檔模式，caller 須先將草稿存為唯讀快照檔 `chmod 400`，並在 prompt 附上獨立三行標頭 `AUDIT_INPUT_MODE: FILE_SNAPSHOT`、`SNAPSHOT_PATH: <唯一絕對路徑>`、`SNAPSHOT_TOTAL_LINES: <N>`，同時仍須把 R1–R4 rubric 全文內嵌於 prompt，且收件時核對 auditor 回傳的 `READ_RANGE: 1..<N>` 確認完整讀取），要求逐條 R1–R4 單行 PASS/FAIL＋一句證據引述。最後一行只能是 `VERDICT: COMPLIANT` 或 `VERDICT: VIOLATIONS: <R 編號>` 其中一種；逐條結果有任一 FAIL 時，即使最後一行誤寫 COMPLIANT 也按 VIOLATIONS 處理。**本回合這個 skill 只有一次 auditor 額度**：不論結果如何都不得重派，也不得用 SendMessage 續問同一個 auditor。末尾那行的狀態只能是下列四個之一：

- 全 PASS → 「🔎 self-verify: COMPLIANT」
- 任一 FAIL 且已修正 → 修 draft（若本回合另有含相同錯誤主張的報告副檔亦同步修正）後直接交付，標「🔎 self-verify: FIXED_AFTER_AUDIT（R#）」並明寫「未經第二次獨立稽查」
- 任一 FAIL 且修不掉 → 停止推薦式結論，**把不實或佐證不足的主張從 draft 刪除或收窄**，只交付已驗證事實、未解決問題與「🔎 self-verify: FAILED（R#）」
- auditor error / timeout / 空輸出 / 格式錯誤 → 照發、標「🔎 self-verify: SKIPPED (agent error)」

audit 後不得新增或改寫推薦理由，交付文字須等於修正後的 draft。沒有命中高風險形狀時，上段 inline 自查即為終點；沒派 auditor 就不寫 `🔎 self-verify` 行——那一行轉述的是 auditor 的 verdict，自己填 COMPLIANT 等於偽造稽查（2026-10-15 skill-up 4 題自填 COMPLIANT、全 FAIL）。

## 記憶升級

學到 non-obvious pattern → 主動提議升級 wiki entity（使用者點頭才寫）。

## 手動觸發

`/research-before-answer` 在對話中直接呼叫，無需等待自動觸發。

## 核心原則

**寧可多搜一次，不要編。**

## 踩過的坑（撞新 case 就往下補）

如果要修改本 skill 的查證、抓取或自查規則，就在動手前讀 [references/pitfalls-history.md](references/pitfalls-history.md) 核對歷史失效模式與規則演進紀錄。
