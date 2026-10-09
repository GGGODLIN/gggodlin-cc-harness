---
name: absorb-pack
description: 對「已拍板要借鑑」的外部 pack 做全量逐條重評與碎片吸收。適用單位可枚舉、逐條可對標的包：skill/agent pack、rule 集、config repo、awesome list。觸發：「用 mattpocock / agent-skills 那場的方式評」「全量逐條重評」「這包逐條看要吸什麼」「跟上次那種一大包的評估一樣」。Do not use for：要不要借鑑還沒定（走 check-my-stack）、repo 初見概覽三擇（走 github-repo-research）、單一工具 / 文章 / 影片（無可枚舉單位）。
---

<!-- 本檔在契約測試底下：python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->

# Absorb Pack — 全量逐條重評與碎片吸收

管線位置：`github-repo-research`（這是什麼）→ `check-my-stack`（值不值得借鑑）→ **本 skill**（已定要借鑑，逐條該吸什麼、吸到哪）。前提「要借鑑」必須已成立——還在辯值不值得，退回 check-my-stack。

## Step 1 — 起手三路（同一 message 內並行）

a. **Memory 歷史裁決**：`grep -rli "<pack 名與 owner>" ~/.claude/memory/`。命中的舊裁決標 `unchecked prior`：曾整包拔除 / 否決的，重驗方式見「判準集」的 commit 史規則；曾吸收過的碎片列成「已吸清單」帶進 Step 2（防重列）。
b. **上游全量 inventory**：拉完整檔案樹枚舉所有可裁決單位——主體（skills / rules）**加周邊件**（commands / agents / references / hooks / eval / scripts）。周邊件常是含金量所在（agent-skills 案：唯一移植動作出自 eval framework）。記下總件數 N，收尾對帳用。
c. **Stack 對標摘要（兩軸）**，寫成一段可嵌進 subagent prompt 的文字：
   - **七層落點**（結構穩定）：CLAUDE.md/rules（always-on 紀律）、skill/command（觸發式流程）、agent（審查視角）、hook（enforce）、script（確定性計算）、workflow channel（週期掃描）、memory/wiki（低頻知識）
   - **活系統清單**（會漂移，動態撈、不硬編）：逐一讀取四個來源，按固定格式產出收據，再用完整集合整理當前持續優化中的系統：
     ```text
     STACK_RECEIPT v1
     active-trials: 來源=~/Desktop/projects/.claude/trials/active.md；抽取=以含 YYYY-MM-DD 的括號收尾之全部 H2 trial 標題；完整新格式逐項讀 `started`／`status`／`detail` 索引欄位、按 detail 指針讀長段並核對前兩行 `detail-key`／`detail-title`；沒有索引欄位的 legacy H2 直接讀 H2 下長段；索引不完整、detail 缺檔或身分不符報 `detail-missing`／`detail-mismatch`；count=<N>；items=<完整名稱集合>
     local-analysis-channels: 來源=~/.claude/workflows/local-analysis.js；定位=CHANNELS；抽取=陣列內全部 key；count=<N>；items=<完整 key 集合>
     work-index: 來源=~/.claude/memory/work/_INDEX.md；抽取=目標以 /_INDEX.md 結尾的全部 Markdown link；count=<N>；items=<完整標題集合>
     projects-index: 來源=~/.claude/memory/projects/_INDEX.md；抽取=目標以 /_INDEX.md 結尾的全部 Markdown link；count=<N>；items=<完整標題集合>
     ```
     `count` 與 `items` 必須來自當次讀檔，無命中寫 `count=0；items=NONE`；不得填 yes/no、`read`、`done` 或憑印象補寫，兩個 memory index 不得合併。吸收候選才能路由到具體活系統而非籠統「放 memory」。
   - 附使用者環境的 **deny / 衝突清單**（AskUserQuestion deny、Explore deny、haiku deny、不寫註解等），subagent 對標時直接標衝突

完成判準：舊裁決全部標了 unchecked prior 或「無既評」、N 已計；`STACK_RECEIPT v1` 四個命名欄位各恰出現一次，來源可定位，`count` 與完整 `items` 已填實值且無 `<...>`；active-trials 逐項分辨完整新格式與無索引欄位的 legacy H2，索引不完整、detail 缺檔或身分不符明報 `detail-missing`／`detail-mismatch`；同一份收據已原樣帶入 Step 2 prompt；對標摘要含七層 + 活系統 + deny 清單三塊。任一來源讀取失敗或收據不完整時停在 Step 1，不派 Step 2 agents。

## Step 2 — 分組 fan-out 逐條對標

按上游自己的分類分 4-6 組，`Agent` tool 同一 message 並行派出（`subagent_type: routed-judge`——opus + high 已在定義檔釘死，見 subagent-routing.md）。每組 prompt 內嵌：

1. 抓取指令（`gh api .../contents/... | base64 -d` 逐檔讀原文，不准只看 README 摘要）
2. Step 1c 的完整 stack 對標摘要（以 `STACK_RECEIPT v1` 開頭，四欄原樣保留）
3. 歷史裁決重驗指令（該組若含曾拔除件：「檢查現版是否實質演進到動搖判決，明寫維持/動搖 + 證據」）
4. 已吸清單（「下列碎片已吸收過，不重列」）
5. 固定輸出格式，每件五欄：

```
- 對標物：管線位置上的自家對應（或明寫「無對應物」）
- Q2/Q3：Q2 = 有對應物（走對照吸收）；Q3 = 無對應物（走引入裁決）
- 上游獨有機制：對照後多出來的具體機制/表/判準（引原文短句，每條 ≤2 句）
- 吸收候選：哪些碎片值得吸進哪個落點（具體到七層之一 + 檔名/段名）；沒有就寫「無 + 理由一句」
- verdict 建議：吸收 N 條 / 不吸收 / 引入 / 不引入 + 一句理由
```

完成判準：每個 inventory 單位都被恰好一組涵蓋（分組聯集 = N、無重疊無遺漏）。

## Step 3 — 綜合成帳本 + 拍板表

收齊後 main 綜合（判斷工作、不外派）：

1. **帳本行**：「N 件全數裁決、對帳平」——加總各組件數對 Step 1b 的 N，不平就補查漏件，平不了不准宣告
2. **STACK_RECEIPT v1**：把 Step 1c 產生的同一份收據原樣嵌入成稿，恰好一次
3. **歷史判決重驗結果**一段（維持 / 動搖，各附證據）
4. **拍板表分 Tier**：Tier 1 機制級增量（對標物真實缺）/ Tier 2 有價值但單條輕 / Tier 3 邊際（預設不做、點名即可）。每條：碎片內容一句 + 來源件 + 落點 + 推薦標記
5. **衝突警示段**：上游建議撞自家 deny / 規則清單的，逐條列（引用上游時的地雷圖）
6. 一輪收斂（CLAUDE.md「問題一次收斂」）：表尾給拍板方式範例（「Tier 1+2 全做」「只做 #1 #4」），**結束回合等使用者拍板**——落點含 CLAUDE.md 的條目在表中預先標記「需逐字討論」
7. **成稿分兩層**：N 件逐件五欄明細（Step 2 各組回傳的原文）寫進證據附檔 `<scratchpad>/absorb-pack-<pack>-<YYYY-MM-DD>.md`，聊天主報告固定只交三步狀態流「這包看完了→大多數跟現有哪些治理重疊→真正建議只吸哪幾條」＋ Tier 1 候選表＋單一拍板句＋附檔 file:// 連結一行；帳本行、`STACK_RECEIPT v1`、歷史重驗、Tier 2／3 列、衝突段全部只寫進附檔（R0 仍以附檔內的成稿計數）。拍板表每列只留「碎片一句＋來源件號＋落點」，不重貼五欄。為什麼：37 件五欄全進聊天曾讓使用者當場跟丟（2026-08-25 `/wait-what`）；2026-08-29 Paperthin 又因收據＋8 列 Tier 表＋衝突段進聊天再跟丟一次，拍板只需要 Tier 1 候選

完成判準：帳本平、`STACK_RECEIPT v1` 在待審成稿中恰好一次且四欄完整、每條候選有落點、衝突段存在（無衝突就明寫「無」）、附檔已落地且聊天稿不含逐件五欄。成稿（主報告＋附檔）後先過下方 Self-Verify 再呈現。

## Step 4 — 拍板後落地

- **動 CLAUDE.md / rules 的條目**：先在 response 攤出逐字 draft 讓使用者審過才 Edit——**不進批次落地，即使該條已被籠統核准**（2026-07-11 使用者明訂）。順帶自查 always-on 稅：低頻知識別往 CLAUDE.md 塞（那是 memory 的活）；反向也查：需要 enforce 的別只寫紀律（考慮 hook）
- **改既有 skill / command**：invoke `skill-creator`（接線判準：補段必補指針、約束放決策點旁、副作用升格編號步驟），改完走 skill-creator 內建 RED → GREEN → REFACTOR 行為驗證 + 更新 `INVENTORY.md`
- **script / channel 類**：實跑驗證（真實資料命中 + 邊界態，如 baseline / `__SILENT__` 兩態），不是寫完就算
- 修改後 grep 驗證引用未破壞（枚舉一致性：如「four sections」這種計數式接線）
- 逐項對照回報（預期 / 實際 / 匹配），並如實列「沒做的部分」（例：graft 未跑 pressure test → 指出由哪個既有 trial / channel 監測）

## Step 5 — Memory 回寫 + 收尾

1. 既有裁決條目**補段不開新條**：加「YYYY-MM-DD vX 全量重評」段（帳本數字 + 判決維持與否 + 吸收明細落點）+ `Re-checked: YYYY-MM-DD 仍適用/已翻案` 行；對應 cluster index 行同步更新
2. 純知識碎片落 memory 的照 cluster check 規則入 cluster
3. 收尾宣告必附帳本數字（「46 件全數裁決」），宣稱與證據對位

## 判準集（兩次實跑的教訓，對標時強制套用）

- **對標物以管線位置為準、不是名字像**：mattpocock wayfinder 初判誤配 writing-plans、實為 brainstorming 的跨 session 放大版——名字軸錯會讓整條 verdict 錯，被抓出後要全鏈重驗
- **歷史拔除判決用 commit 史重驗**：`gh api "repos/O/R/commits?path=<file>"` 判決日後零實質 commit = 直接維持，不用重讀內容
- **拔除理由是「管線位置被佔」時，內容演進只影響「可吸碎片」、不影響「重不重裝」**：skill 寫得再好，走不到的位置就是走不到（agent-skills review skill 案：auto-invoke 0/6 的結構事實不因內容變好而改變）
- **已吸收過的碎片不重列**：Step 1a 的已吸清單要真的傳進 subagent prompt
- **教學級 vs enforce 級**：上游是教學散文、自家同義物是 hook / agent / 機制時，判「已覆蓋且自家更強」，不要因上游寫得完整就想吸
- **「好書不等於好工具」**：內容品質高但環境結構性錯位（無場景 / 無決策權）→ 不引入，需要時現查

## Self-Verify（mandatory — 拍板表成稿後、呈現使用者前）

拍板表成稿後（= 內部草稿，**不要**先輸出——tool call 之間的文字不保證顯示），派 verify subagent 對表。Dispatch 規格：`Agent` tool、`subagent_type: skill-verify-auditor`（sonnet+low、tools 僅 Read，定義檔釘死）、description 含 marker `skill-verify:absorb-pack`、內嵌完整拍板表原文 + 下列 rubric：

```
你是 adversarial 合規審查員。偏置是「找違規」：無法從文本確認就判 FAIL。
R0【STACK_RECEIPT v1】只在待審成稿內計數，不計本 rubric。獨立讀取四欄所列絕對路徑，依各欄的抽取規則重算完整集合；標籤與 active-trials / local-analysis-channels / work-index / projects-index 是否各恰出現一次，且 `count` 相等、`items` 集合無漏列或多列？任一欄缺失或重複、來源或定位不符、來源讀取失敗、兩個 index 合併、摘要僅為 yes/no/read/done、仍含佔位符，或集合不一致 = FAIL；只有獨立讀檔確認為零時，`count=0；items=NONE` 才可 PASS。R0 不得 N-A。
R1【帳本平】是否宣告總件數 N 且各組加總 = N？
R2【五欄完整・附檔】讀 Step 3 第 7 項的證據附檔（路徑在待審成稿內），抽查 3 件：對標物 / Q2Q3 / 獨有機制（有原文引句）/ 吸收候選（落點具體到層+檔名）/ verdict 是否齊？附檔不存在、或聊天主報告仍逐件貼五欄 = FAIL。
R3【歷史重驗】曾拔除/否決件是否明寫「維持/動搖 + 證據」？（無歷史裁決 = N-A）
R4【衝突警示段】存在且逐條列（或明寫「無」）？
R5【CLAUDE.md 標記】落點含 CLAUDE.md 的候選是否標「需逐字討論」？（無此類候選 = N-A）
輸出：R0 只允許 PASS|FAIL；R1-R5 各 PASS|FAIL|N-A + 一句證據。最後一行只能輸出 `VERDICT: COMPLIANT` 或 `VERDICT: VIOLATIONS: <R 編號列表>`。
```

**本回合這個 skill 只有一次 auditor 額度**：不論結果如何都不得重派，也不得用 SendMessage 續問同一個 auditor。表尾固定一行，狀態只能是下列四個之一：

- R0=PASS 且 R1–R5 無 FAIL → 「🔎 self-verify: COMPLIANT」
- 任一 FAIL 且已修正 → 「🔎 self-verify: FIXED_AFTER_AUDIT — R#（抓到什麼、怎麼修的）」，同句明寫「未經第二次獨立稽查」
- 任一 FAIL 且修不掉 → 「🔎 self-verify: FAILED — R#（缺口）」，並把佐證不足的件從拍板表刪除或降級為「證據不足、不建議吸收」
- verify agent error / timeout / 空輸出 / 格式錯誤 → 照發、標「🔎 self-verify: SKIPPED (agent error)」

拍板表全文只在 verify 之後的回合最終訊息輸出。
