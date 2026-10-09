---
name: github-repo-research
description: Use when 使用者貼 GitHub repo URL 並要求研究 / 分析 / 評估 / 「幫我看看這個」 / 「這是什麼」。與 research-before-answer 疊加觸發（它管查證紀律，本 skill 管 repo 專屬路徑）。Do not use for：非 GitHub 的套件 / 產品研究（research-before-answer 即可）、使用者明確要「vs 我的 stack」競合分析（直接走 check-my-stack）、已評過且使用者只想回憶結論（grep memory 引舊結論即可、引用前照 Step 1a 對帳）。
---
<!-- 本檔在契約測試底下：evals/eval.yaml（skill-up-run run，包裝會剝掉 better-rm）——改完必跑再宣告完成；python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->
<!-- 2026-07-31 純 slash 化（disable-model-invocation）提案已試過並撤銷，不要重提：粗看 30 天手打 47 vs auto 20 像純手動，逐筆驗屍後 auto 拆成 10 次 eval 污染 + 7 次「URL 在前、slash 收尾」打法（靠模型 invoke、flag 會砍斷）+ 2 次真自動長尾（不典型 URL / repo 藏句中，手打習慣不會出手）。省 140 tokens/session 不值這兩條路。翻案條件：使用者打字習慣改為一律 slash 開頭且長尾情境另有接手機制 -->


# GitHub Repo Research

為何固化：130 個 session 實證，`gh repo view` 欄位集每次現編（25 抽樣無兩次相同、會漏 isArchived/latestRelease）、34/130 沒先查 memory 導致重評已評過的 repo、報告結構每次重新發揮。本 skill 把這三個不穩定點釘死，「查哪些」的判斷力留給當下。

## 流程

### 1. 並行三路起手（同一 message 內發）

a. **Memory 既評比對**：`grep -rli "<repo名與owner>" ~/.claude/memory/`——命中先讀，讀到的舊結論先標 `unchecked prior`、不直接當 evidence。引用前對帳三件事：(1) 跑 `~/.claude/skills/check-my-stack/scripts/reconcile.sh <tool名>`（裝機狀態 + 自家 skill 引用）(2) 本次提問 frame 與舊結論 frame 是否同型 (3) 不符 → 當場依帳本格式段回寫（SSOT：memory `feedback_competitive_analysis_check_own_stack_first.md`）。對帳過了才升格 evidence → 引舊結論 + 問「要重評嗎」，使用者沒點頭不重做
b. **元資料（固定欄位集，不要現編）**：
```bash
gh repo view <owner>/<repo> --json name,description,homepageUrl,createdAt,updatedAt,pushedAt,stargazerCount,forkCount,primaryLanguage,licenseInfo,repositoryTopics,isArchived,isFork,latestRelease
```
c. **README**：`gh api repos/<owner>/<repo>/readme --jq '.content' | base64 -d`

### 2. 按需加查（依 repo 類型挑，不是全跑）

- 檔案結構：`gh api "repos/O/R/git/trees/HEAD?recursive=1" --jq '.tree[].path'`（URL 帶 `?` 必須加引號，否則 zsh glob 報錯）
- 活躍度：`gh api repos/O/R/commits --jq '.[0:5]'` / `gh release list`
- issue 健康度：`gh issue list --state open --limit 10`
- npm 套件：`npm view <pkg>`
- 社群評價：WebSearch（走 research-before-answer 的 nav+WS 配對規則）
- 官方 blog / docs：WebFetch（4xx 走網址抓取退路，見 WIRING.md「非官方內容抓取」）

### 3. 報告固定骨架

1. 一句話定位（這是什麼、誰做的、解什麼問題）
2. 狀態表：stars / created→last push / license / fork:star 比——**fork:star 比異常低 + 帳號新 = star inflate 嫌疑，明寫**
3. 核心 thesis（它的主張，不是 feature 清單）
4. 對使用者環境的相關性（引 memory 既有條目對位；只是觀察就說觀察）
5. 風險（維護者集中度 / 商業模式 / 供應鏈 / 過度行銷訊號）
6. 建議（明確三擇：值得深入 / 記錄即可 / 跳過）

骨架 6 段填完＝內部成稿。**成稿後的下一步固定是 Step 5 Self-Verify，不是輸出報告**——verify 處理完才回 Step 4 收尾問句、Step 6 呈現。做完的判準：本次 session 已出現 `skill-verify:github-repo-research` 的 Agent dispatch。未進 Step 3（純 metadata 快查、幾行 `gh repo view` 就答完）不算成稿、Self-Verify 不適用。

### 4. 條件收尾問句

- 結論值得留 → 問「要存 memory 嗎？」（不自動寫；reference/project 過 cluster check）
- repo 是 CLI 工具且使用者顯興趣 → 問「要加進 radar 嗎？」（CLAUDE.md radar 規則，CLI 類常漏問，這裡釘住）
- 使用者說「跟我的 stack 比 / 值不值得借鑑」→ 升級 invoke check-my-stack，本 skill 的相關性段不取代它
- 使用者沒說，但 Step 6 第 3 項判定重疊大到值得逐點細比 → 只問「要升級成 check-my-stack 逐點比對嗎？」；使用者點頭才跑，沒回答不跑

### 5. Self-Verify（mandatory — 報告成稿後、呈現使用者前）

報告成稿後（成稿 = 內部草稿，此時**不要**先輸出報告文字——harness 對 tool call 之間的文字不保證顯示，verify 的 Agent call 會把先輸出的報告吞掉），派一個 verify subagent 檢查報告是否遵守本 skill 的規矩。不可跳過。Verify 回來後接 Step 6 呈現。

Dispatch 規格：

- `Agent` tool、`subagent_type: skill-verify-auditor`（sonnet+low、tools 僅 Read，定義檔釘死）
- description 固定含 marker 字串 `skill-verify:github-repo-research`（採用率統計 grep 用，不要改字）
- prompt 內嵌：(1) 完整報告原文 (2) 下方 template 全文。不需給 gh api 權限——rubric 全部可從報告文本判定

Verify prompt template（原文嵌入、`{report}` 換成報告全文）：

```
你是 adversarial 合規審查員，檢查一份 GitHub repo 研究報告是否遵守其 SKILL.md 的規矩。偏置是「找違規」：無法從報告文本確認有遵守就判 FAIL，不要善意推定。

報告原文：
{report}

逐條檢查（每條回 PASS / FAIL / EVIDENCE-UNAVAILABLE / N-A + 一句證據引述）：

R1【狀態表完整】報告是否含狀態表，且至少涵蓋：stars、created→last push 時間軸、license、fork:star 比？缺 fork:star 比 = FAIL（star inflate 偵測依賴它）。

R2【六段骨架】報告是否含全部六段：一句話定位 / 狀態表 / 核心 thesis（主張而非 feature 清單）/ 對使用者環境的相關性 / 風險（維護者集中度・商業模式・供應鏈・行銷訊號至少涉及其一）/ 建議？

R3【memory 對位】相關性段是否有 memory 既評比對的痕跡（引具體 memory / wiki 條目名對位、或明寫「memory 無既評」）？完全沒提 = FAIL（表示起手三路的 memory grep 可能被跳過）。

R4【建議三擇】建議段是否明確落在三擇之一（值得深入 / 記錄即可 / 跳過）？模糊收尾（「看需求」「都可以」）= FAIL。

R5【條件收尾問句】結論值得留時是否問了「要存 memory 嗎？」；repo 是 CLI 工具且使用者顯興趣時是否問了「要加進 radar 嗎？」？（兩者條件都不成立 = N-A）

三態判定與白名單：

某條的 FAIL 若屬「證據結構性取不到」，改判 EVIDENCE-UNAVAILABLE。結構性取不到只限以下四項（白名單，不得類推擴充）：

1. 規則要求引用既有 memory／先例，但實際 grep 結果為 0 命中
2. 規則要求貼測試輸出，但該項在本次條件下結構性不可執行，且報告已具名寫出阻塞因素
3. 規則要求對帳裝機狀態，但該工具未安裝且本次判決本身就是「不裝」
4. 規則要求引用行為數據，但該機制建立不足一個觀察週期、無數據可引

白名單不包含任何「沒做」或「做了但沒寫清楚」——那些一律照舊算 VIOLATIONS。

判 EVIDENCE-UNAVAILABLE 時，該條的證據句必須點名是白名單第幾項（例如「白名單第 1 項：memory grep 0 命中」），不可只寫「證據不足」。

verdict 三態判定（N-A 不計入非 PASS）：

- 沒有任何 FAIL 或 EVIDENCE-UNAVAILABLE → COMPLIANT
- 有非 PASS 條目，且**全部**都是 EVIDENCE-UNAVAILABLE（即全部落在白名單）→ NEEDS_HUMAN_REVIEW，列出這幾條編號
- 有任何一條 FAIL（不在白名單）→ VIOLATIONS，列出所有非 PASS 條目的編號（含 EVIDENCE-UNAVAILABLE 的那幾條）

輸出格式（固定，最後一行必須是 verdict 行）：

R1: PASS|FAIL|EVIDENCE-UNAVAILABLE — <一句證據>
R2: PASS|FAIL|EVIDENCE-UNAVAILABLE — <一句證據>
R3: PASS|FAIL|EVIDENCE-UNAVAILABLE — <一句證據>
R4: PASS|FAIL|EVIDENCE-UNAVAILABLE — <一句證據>
R5: PASS|FAIL|EVIDENCE-UNAVAILABLE|N-A — <一句證據>
<verdict 行，形狀見下>

verdict 行三選一，整行照抄其中一種、只把 <> 換成編號：

VERDICT: COMPLIANT
VERDICT: NEEDS_HUMAN_REVIEW: <R 編號逗號列表>
VERDICT: VIOLATIONS: <R 編號逗號列表>

這三行是三個候選、不是可以並列。下游用 grep 取這一行做二值判讀，行內出現第二個 verdict 名稱、`|`、括號補述或「若…則…」條件句，解析會同時拿到兩個互斥狀態。保留意見寫進該條的證據句，不要寫進 verdict 行。

判 NEEDS_HUMAN_REVIEW 之前先掃一次 R1–R5：只要還有任何一條寫著 FAIL，這輪就是 VIOLATIONS；一個 EVIDENCE-UNAVAILABLE 都沒有時，NEEDS_HUMAN_REVIEW 不可能成立。「這條 FAIL 我不確定算不算數」是不確定、不是證據取不到——判 FAIL、寫 VIOLATIONS，把保留意見放進該條證據句。
```

### 6. 呈現（唯一輸出點 — verify 完成後）

報告放在 verify 之後的**回合最終訊息**輸出（最終訊息 = 後面不再有任何 tool call 的那則，是唯一保證顯示給使用者的位置）。不論 verify 結果如何，最終訊息都必須含主報告，不可寫「報告如上」指涉中段文字。

主報告與證據分兩層。聊天主報告固定下列六項、依序、用小標題分開，Step 3 六段骨架壓縮在裡面。每項寫給沒看過這個 repo 的使用者：先講它對使用者的意義，再講技術細節；術語第一次出現就附一句白話。

1. **結論**：一句話，開頭字面寫「建議：」再接三擇之一（值得深入／記錄即可／跳過），加一句理由。「建議」兩字跟第 2 項的「狀態表」一樣是下游定位用的標籤。
2. **它是什麼**：白話講它幫人做什麼，並點名「在你這裡對應的是 X」；沒有同類就寫「你手上沒有同類工具」。再接兩行，開頭字面照寫、不改畫成表格：「狀態表：stars …／created→last push …／license …／fork:star 比 …」與「核心 thesis：」它的主張。下游 eval 與稽核用「狀態表」三個字定位這一行，改成表格或換標籤就找不到。
3. **跟你現有的差在哪**：一兩句，對照第 2 項的 X 寫多了什麼、少了什麼，並帶 memory 對位（引條目名，或寫「memory 無既評」）。只用 Step 1–2 已查到的資訊，不為這項另做盤點；沒查證的寫「未驗證」。重疊大到值得逐點細比，就在 Step 4 收尾問要不要升級 check-my-stack，不自己跑。
4. **用了會得到什麼**：在哪些情況用得上，以及使用者有沒有遇過它要解的問題（依 memory 與對話判斷，看不出來就寫「看不出你遇過」）。
5. **代價**：會不會動到使用者的設定或 repo、跟現有流程衝不衝突、要花的錢／token／API key／訂閱，加上 Step 3 風險段最多三條（維護者集中度、license、供應鏈、行銷訊號）。
6. **依結論二選一**：值得深入 → 最小試用步驟，最多三步；記錄即可或跳過 → 不裝也能拿走的部分，沒有就寫「沒有」。

狀態表全欄、查證指令、issue 清單、環境衝突細節、thesis 展開與 self-verify 逐條，寫進證據附檔 `<scratchpad>/github-repo-research-<owner>-<repo>.md`，聊天末尾附 file:// 連結一行＋ self-verify 一行。為什麼：2026-10-01 回溯 456 個 session、513 段工具評估後的 2,169 則追問，使用者看完報告最常回頭補問的就是這六項（它是什麼 23.5%、得到什麼 18.3%、跟現有比 18.1%、代價 17.3%、怎麼試 10.2%、能借什麼 5.8%）；舊的四塊只答到其中一部分，而且「看不懂」的追問有 86% 是報告寫了但沒寫白話。

按 verify 結果收尾：

**本回合這個 skill 只有一次 auditor 額度**：不論結果如何都不得重派，也不得用 SendMessage 續問同一個 auditor。末尾那行的狀態只能是下列四個之一（`NEEDS_HUMAN_REVIEW` 是 auditor rubric 的 verdict 值、不是收尾狀態，它走下面第二條）：

- 全 PASS / N-A → 報告末尾附一行「🔎 self-verify: COMPLIANT (5/5)」
- NEEDS_HUMAN_REVIEW（非 PASS 條目全部落在白名單）→ 報告照發，末尾標「🔎 self-verify: COMPLIANT — NEEDS_HUMAN_REVIEW R#（白名單第 N 項：<一句話>）」。**不要為了消除這條而在報告裡補寫實際上取不到的內容**——證據結構性取不到就如實留著讓使用者判，硬掰一句話滿足規則是繞過驗證而不是通過驗證
- 任一 FAIL 且已修正 → **先修報告再發**（補欄位 / 補段落 / 補 memory 對位 / 收斂三擇），修完不重驗、末尾如實列出「🔎 self-verify: FIXED_AFTER_AUDIT — R1（…）」並明寫「未經第二次獨立稽查」
- 任一 FAIL 且修不掉 → 末尾標「🔎 self-verify: FAILED — R#（缺口）」，並把該條支撐的建議從三擇整段移除或收窄成「證據不足、不建議下判斷」
- Verify subagent 失敗（timeout / 空輸出 / 格式錯誤 / agent error）→ 報告照發、末尾標「🔎 self-verify: SKIPPED (agent error)」，不要靜默省略

## 踩過的坑

- 沒先 grep memory 就開查 → 重評已評 repo（crawl4ai 案，使用者說「有點眼熟」才發現）。起手三路的 memory 路不可省。
- `gh repo view` 欄位現編漏 `isArchived` → 對已封存 repo 給出「活躍」誤判。用固定欄位集。
- 報告寫在 verify Agent call 之前輸出 → harness 吞掉中段文字、使用者只看到 verdict 行（openwiki 案 2026-07-03）。報告全文只在 Step 6 最終訊息輸出。
- 引 memory 既評結論沒對帳 → graphify「不裝」stale 判決在工具已實裝 7 週後仍被複誦（2026-07-05 案）。Step 1a 的 unchecked-prior 對帳不可省。
- 追問「有沒有可借鑑」的第二輪直接開翻案區塊＋三層分類清單，沒先重述 repo 是什麼、每條借鑑對應使用者哪條既有規則 → 被叫 wait-what（nerd 案 2026-08-29）。追問回合固定：先一句「原判／新判」，每條借鑑附「對應你現有的哪條」一句，清單不超過兩層。
