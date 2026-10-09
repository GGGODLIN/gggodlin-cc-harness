---
# 本檔在契約測試底下；跑法：bash ~/.claude/skills/handoff-impl/scripts/tests/friction-hardening.test.sh && cd ~/.claude/skills/handoff-impl && skill-up-run run evals/eval.yaml --output-dir ~/Desktop/projects/.claude/trials/skill-up-cli/eval-runs
name: handoff-impl
description: 跨 session 實作委外信道（handoff 單在 ~/.claude/handoffs/*.md，發單 session 驗收、另一 session 實作；信道預設手動搬單，自動接力屬未穩定實驗路徑、僅使用者明確要求實驗才走）。Use when 使用者說「開 handoff 單」「把這個實作交給 GPT / codex / 另一個 session 做」「自動派給 codex」「接單」「GPT 說他好了、驗收」，或 /handoff-impl（帶任務描述 = 開單；無參數 = 掃待辦單自動定角色）。Do not use for：同 session 派 subagent（Agent tool 直接派）、同一工作斷點續命（save/resume-session）、產 spec 或 plan（既有 brainstorming / writing-plans 流程）、快速第二意見或卡關救援（codex:rescue）、研究 / review / spec 撰寫類委外（非實作、另案設計）。
---

# handoff-impl — 跨 session 實作委外信道

核心概念三行：**單是唯一信道**（implementer 零對話脈絡，單要自包含）；**status 決定角色**（同一 skill 兩側通用）；**本 skill 是信道不是規範**——spec 內容、驗收紀律、風格約束全部引用 context 內既有機制，不在單裡重造。設計決策與邊界表見 [design.md](design.md)（改本 skill 前先讀）。

## Step 0：dispatch（每次 invoke 先做）

1. 有任務描述參數 → 進「Create 模式」
2. 無參數或參數是檔案路徑 → 掃 `~/.claude/handoffs/*.md`（不含 `done/`）讀各檔 frontmatter：
   - `SPEC_READY` / `CHANGES_REQUESTED` → 本 session 該當 **implementer**
   - `IMPL_DONE` → 本 session 該當 **verifier**
   - 恰一張可行動 → 續 3；多張 → 列表給 user 選（frontmatter `workdir` 含當前 cwd 者排最前）；零張 → 回報「無待辦單」結束
3. **角色確認 gate**：對 user 輸出一行「單 <slug>、status=<X>，我以 <implementer|verifier> 身分執行——確認？」，**等 user 肯定回覆才動**（防 verifier 誤接自己剛開的單）

完成判準：user 已確認角色，或已回報無單。

## Create 模式（發單，verifier 側做）

1. Spec 內容從當前對話 / 既有 artifact 取得——本 skill 不產 spec；根因、改法、驗收條件還沒收斂就先回既有流程收斂完再開單
2. code 任務先備好隔離工作區（repo 有 worktree 腳本用之，無則 `git worktree add`；純檔案任務可跳過），確定 frontmatter `workdir` / `branch`
3. 照 [references/file-template.md](references/file-template.md) 的 base template 產檔到 `~/.claude/handoffs/<date>-<slug>.md`，逐欄填 frontmatter——`runtime` 要釘死（測試需特定 Node 版本就寫全 PATH 前綴）、`test_evidence` 三檔位擇一（預設 transcript）、`spec_level` 按解法收斂度選（唯一解寫 method、開放解寫 outcome 並少寫改法多寫驗收）；Git 任務把交單前 HEAD 寫進 round 1 的 `round_base`，非 Git 寫 `N-A`。來源是已核准 Matt ticket 且帶 TDD 決策時，才套用 reference 的完整 Matt TDD propagation graft，逐字傳遞 `required`＋seam 或 `waived`＋closed reason＋approval；來源沒有決策時維持 base template，不加入任何 TDD 專屬段落、協議、禁動欄位或回報欄位。兩側都不得改來源決策
4. Spec 段能用指標就用指標（workdir 內已有 plan：寫「讀 <路徑> 執行 <範圍>」），不複製內容。引用外部檔案作先例時必須先實讀並附行號或關鍵片段；讀不到就不得把它當先例或事實，只能列為「未驗證候選」、不得據此指定改法或驗收條件。outcome 級單若預測「會走哪條內部機制」，機制路徑若未對完整 code chain 實證，逐句標「未驗證推測」，驗收仍以可觀察 outcome 為準
5. 填完 template 的 `ENV_READY` 收據再定稿：把 implementer 開工前必須成立的環境前置逐項列為 `前置 / 驗證者 / 執行環境 / probe 或證據 / 預期 / 實際 / ready`，用「驗證者 / 執行環境」標明證據在哪個 runtime 或控制面成立，`ready` 只填 `yes`、`no` 或 `N-A（理由）`。implementer 會依賴的 credential 或控制面能力必須在 implementer runtime probe；無法預驗時只可寫 `N-A（implementer 開工第一步驗，失敗即停損）`，發單者環境成功不能代替。逐項實跑；任一 `no` 或缺證據就先處理環境、不要把單交出去。純檔案任務可填一列 `N-A`，但仍要證明 workdir 與 runtime 可用。驗收命令中只有 implementer 改完才有意義的項目則明標「未實跑、預期輸出為推測」。基線數字必須是此刻親測的全量數字，不可拿單一 suite 外推成「全綠」
6. 對 user 輸出檔案路徑，信道**一律走手動搬單**：輸出一行操作指引（implementer 是 CC → 「在該 session 貼 /handoff-impl」；非 CC → 貼 template 尾端的 bootstrap prompt 全文）。
   - **自動接力是 🔬 未穩定實驗路徑、不預設提供也不主動推銷**。進入條件只有一個：使用者在**本次任務中明確點名要跑自動接力／背景派工實驗**（例：「這張走自動接力」「背景派 codex 直接跑」）。下列都**不構成**授權：「外包給 codex」「走 handoff」「你處理」等概括委外語句——那只決定 implementer 是誰，不決定信道（2026-07-30 活體：概括授權被解讀成自動接力授權、搶跑了一張會動真店的驗證單）。
   - 條件成立才接下方「自動接力模式」段；不成立而使用者語句像在要自動化 → 回一句「自動接力目前是實驗路徑、預設手動搬單，要實驗請明說」然後照手動走。

完成判準：檔案存在且 status=SPEC_READY、frontmatter 無空欄、`ENV_READY` 每列皆為 `yes` 或附理由的 `N-A`、user 已拿到手動搬單操作指引（或已明確授權實驗並進自動接力段）。

## 自動接力模式（🔬 未穩定實驗路徑——僅 Create 步驟 6 的明確實驗授權成立時進入）

> 🔬 未穩定實驗路徑：端到端尚無成功 round，行為未驗證。跑通後把實際成功的完整命令回寫步驟 1 並移除本行。

把「user 搬單 + 盯完成」換成機器信使：背景 `codex exec` 施工、結束自動喚醒本 session 進驗收。只換信使、不換合約——狀態機、單側寫入權、驗收紀律全部沿用。

1. 組派工命令，prompt 用 template 尾端 bootstrap prompt 全文（單自包含、協議在單內），環境照 frontmatter `runtime` 釘的前綴：
   ```
   codex exec -C <workdir> -s workspace-write --add-dir ~/.claude/handoffs "<bootstrap prompt 全文>"
   ```
   `--add-dir` 不可省：單在 workdir 外的 `~/.claude/handoffs/`，sandbox 只放 workdir 會讓 codex 寫不進回報段——活做完了卻交不了收據，喚醒側會誤判失敗
2. 以 Bash `run_in_background` 執行上述命令。對 user 輸出一行：「已背景派工 <slug>，完成會自動喚醒；本 session 若中途關閉，下個 session 貼 /handoff-impl 掃描會接手」
3. 背景結束喚醒後讀單 frontmatter `status` 分流：
   - `IMPL_DONE` → 一行通知 user、直接進 Verifier 模式。跳過 Step 0 角色確認 gate 的理由：gate 防「誤接自己剛開的單」，本路角色由派工動作固定為 verifier、無誤接可防
   - 仍 `SPEC_READY`（codex 收工卻沒填回報，或中途死）→ 沒有回報的完成不存在：不動單、貼 codex 輸出尾段給 user，列選項：原單重派 / `codex exec resume --last` 續跑原 session / 轉手動搬單 / 先查原因

完成判準：派工通知已出，且喚醒後已按 status 分流（進 Verifier 模式、或 user 已收到失敗選項）。

## Implementer 模式（接單施工）

1. 整讀單檔，照「給 implementer 的協議」段執行——協議全文在單內（template 已內建：不准問、只寫回報段、不 push、多 phase 逐 phase commit + 自檢 + 停損）。遇 dcg 攔截先換等價非破壞性作法；換不掉就停損交單，不等待互動放行
2. `CHANGES_REQUESTED` 的單：先讀驗收記錄最新 round 的 findings，只修 findings 涵蓋範圍，不加料
3. 單內有「TDD decision」才執行：required 保留來源 seam 並依測試優先流程施工；waived 保留來源 closed reason 與 approval，不新增 TDD claim。沒有該段的既有 handoff 完全不受影響
4. 驗收條件逐條自跑、原樣輸出貼進回報
5. Git 任務先 commit 本 round 的範圍內改動，再用 `git diff --name-only <round_base>...HEAD` 產生改動檔清單並貼 `git status --short`；本 round 歸屬以 `round_base...HEAD` 為準。目標在 submodule 時，round_base、diff、commit 數與 commit 都從 submodule 內取得，另貼 superproject 的 `git status --short`，pointer 是否更新照單內約束，沒寫就留給 verifier／user 決定。完成後填「實作回報」段 `### Round <N>` 子節（六個必填欄含協議摩擦欄，template 有骨架）；同一 round 內重試用 `#### Attempt <N>` 或時間小節，`Round` 只代表 verifier 退回輪次。最後把 frontmatter `status` 改 `IMPL_DONE`

完成判準：回報 template 全欄填妥（「無」或 `N-A` 也要明寫）、status 已改、除回報段與 status 外未動單檔任何段落。

## Verifier 模式（驗收）

1. 讀單檔實作回報，然後**全部重驗、不採信回報數字**（回報再完整也不構成抽驗理由——完整的回報只證明 implementer 會寫回報）。單內有「TDD decision」時，核對 implementer 是否原樣保留來源決策：required 不得轉 waived，waived reason 與 approval 不得由 implementer 新增或改寫。Git 任務再查 `git status --short`：若有與本單相關的未 commit 修改，視為 implementer 尚未交單，先停止驗收並回報狀態；既有且與本單無關的髒檔只記錄、不阻擋。確認本單改動已 commit 後，先用 `git diff <round_base>...HEAD` 判本 round 歸屬，再用三點 merge-base diff 看累積產品改動；不得拿累積 diff 冒充本 round 所有權。非 Git 任務改用回報檔案清單與驗收產物逐項核對。兩類任務都逐條親跑驗收命令，多 phase 單沿 commit 軌跡逐段驗
2. 敵對立場 review：用 context 內既有驗收紀律（dispatch-and-verify 的 verify 段；repo 有敵對 review 模板則套用）；回報中「發現但沒動的問題」查證後才收錄
3. 判定並寫驗收記錄 `### Round <N>` 子節（N = frontmatter 當前 round；逐項重驗表 + 摩擦欄）：
   - **ACCEPTED** → status 改 `ACCEPTED`、單移 `~/.claude/handoffs/done/`、對 user 報告結果；**git 動作（push / 更 PR）停下等 user 指示**，除非 user 已在本次任務單次授權。報告完接「收案後：迭代迴路」
   - **CHANGES_REQUESTED** → findings 逐條寫（file:line + 問題一句 + 失敗場景）、status 改之、frontmatter `round` +1；Git 任務把當下 HEAD 寫進 `round_base` 作下一 round 起點，非 Git 保持 `N-A`。最後給 user 一行轉發指引（「到 implementer session 貼 /handoff-impl」）
4. 退回上限 2 輪（本質是方向錯煙霧偵測器）；質性訊號任一命中**不等額度直接升級**：diff 越修越滾越大、繞過驗收而非通過、同 error 換裝重現。升級 = 不再退回，對 user 出摘要：試過什麼 / 為何不過 / 剩什麼選項（換 method 級重派、verifier 接手、放棄此路）。摘要出完接「收案後：迭代迴路」

完成判準：驗收記錄子節已寫齊、status 已推進、user 已收到判定與下一步。

## 收案後：迭代迴路（每張單 ACCEPTED / 升級時順手做）

1. 彙整該單兩側摩擦欄：**bug 級**（協議壞了、照做會出錯）→ 當下走 skill-creator 修本 skill；**判斷級**（規則要不要改、樣本還不夠）→ append [friction-log.md](friction-log.md) 的「待折」段
2. append 後計數：同類摩擦累計第 2 次，或「待折」達 3 項 → 當次收案直接走 skill-creator 內建的 RED → GREEN → REFACTOR 行為驗證迴圈批次折；未達門檻就保留到後續單據。折入時不刪原紀錄，移到「已折／已否決」並附日期與落點

完成判準：兩側摩擦欄內容已分流落地（或確認雙側皆「無」）；命中門檻時已完成批次折，未命中時待折數已回報。

## 踩過的坑

- 概括委外語句 ≠ 自動接力授權：「外包給 codex、走 handoff」被解讀成自動接力授權、開單後跳過信道確認直接背景派工——單內含部署指令，等於未經確認就啟動會動線上環境的動作鏈（幸被使用者及時叫停、codex 尚在讀 help、零副作用）→ 信道預設固定手動、自動接力降級為需明確實驗授權的路徑（2026-07-30 活體）
- 手寫改動清單與憑印象引用會製造假證據：proj-v5 單把實改 `bitbucket-pipelines.yml` 寫成不存在的檔名，absorb 單誤述未實看的先例檔 → 清單由 Git 產生、引用先實讀（2026-07-27 活體）
- 驗收命令跑過仍不夠：runtime symlink、managed-install、測試店 feature preview 與 Market 狀態前置未驗，讓 implementer 額外繞 round；同類失守重複兩次後，單靠散文規則仍會漏 → 用 `ENV_READY` 固定收據逐項留下 probe、實際值與 ready 判定（2026-07-27～08-05 活體）
- 多 round 未 commit 就讓 verifier 進場會把施工中狀態誤當交付；submodule 又會讓主 repo commit 數失真 → 交單先 commit + 貼 status，submodule commit 落點另列（2026-07-27 活體）
- dcg 攔截與「無人回答、不要問」互卡時，不可等待放行或繞過 gate → 先換等價非破壞性作法，換不掉就停損交單（2026-07-27 活體）
- worktree 的 docs symlink 只在建立時鋪，repo 內放 handoff 檔 implementer 會看不到 → 檔案一律 global `~/.claude/handoffs/`（2026-07-16 round-1 活體）
- runtime 沒釘死：implementer 機器預設 Node 26 跑舊 deps 炸 23 個 suite，退 Node 18 才過 → frontmatter `runtime` 必填（2026-07-16）
- 既有測試套件全綠 ≠ 修對：`yarn test-custom-js` 根本不載入被改檔 → `test_evidence` 檔位在開單時就要選，不留給 implementer 猜（2026-07-16）
- Self-Verify 段在畢業時重評仍不加：本 skill 有 create／implementer／verifier 三種不同輸出，沒有單一固定產物可用同一 rubric 對表；而 implementer 產物本來就由獨立 verifier 全量重驗，再派一次 rubric agent 會重複同一責任（2026-08-06）
- Matt TDD 決策只可沿信道傳遞、不可由 handoff 自行發明：一律加欄會污染非 Matt 單，一律不傳會讓跨 session required 票失去條件脈絡；所以 presence-preserving——來源有才原樣帶 required／waived 決策，來源沒有則維持既有八段信道行為。第一版另帶 child receipt 與 validator 指令，被獨立 review 判定把信道膨脹成證據引擎，已移除（2026-08-12）。
- 證據沒標成立邊界時，發單者環境會被誤當 implementer 環境、累積 diff 會被誤當本 round 歸屬、未驗機制路徑會被寫成驗收事實；以 `round_base`、ENV_READY 驗證者／執行環境與「未驗證推測」三處分開固化，`Round` 只保留給 verifier 退回輪次（2026-08-06～08-10 活體）。
