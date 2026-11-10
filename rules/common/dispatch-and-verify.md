# Dispatch + Verify 工作紀律

兩條互補規則：dispatch 控制 main session 不亂吃 context、verify 控制宣告完成的證據強度。各節完整正反例見 `~/.claude/references/dispatch-and-verify-examples.md`（判斷模糊時再讀）。

## Main scope 差額檢查

首次形成實作要求、改派／重派／換方案、採納擴大範圍的 review 建議前，main 自做或派工都對照使用者最近明確批准的目標、環境與仍有效限制，比較累積差額；不以上一版 plan、ticket、測試或 worker 驗收自證授權。

- 區分目標必要與選型衍生配套。新增能力、跨系統修改、假設風險機制或持續維護責任時，先找仍滿足原驗收的較小方案；能縮回就自決，不能縮回或想保留新增承諾，才帶原授權、差額、取捨與替代請使用者拍板。
- 原範圍必要啟用、局部修正、等效替換自決；不以工具名、行數、檔數判越權，也不逐次請示讀檔／測試。縮小方案不降驗收；證據不足先縮宣稱，不自動擴測來支撐更大宣稱。
- 被否決時也考慮縮小或停止；真缺陷不代表其建議修法已獲授權。授權不清先查決策，仍有範圍取捨才問；未答或拒絕不做新增部分，不靠改名、換 worker、改驗收重開，原範圍不相依工作可繼續。

## 終端派工只由 main 管理

- 只有直接承接使用者需求的 main 可用 Herdr 啟動、接續、轉派 agent；subagent／受委派 terminal worker 不向下開 agent，繼承終端身分變數不授權。
- 需要另一 agent 或真實 agent 測試，受委派者回報任務、repo、模型／effort、backend、必要操作，由 main 核對授權後親自啟動、派工、收結果、清理。brief 要求測試不等於准許再派工。
- 不得以 `pane run`、shell wrapper、其他 CLI 或 probe／preflight／測試名義繞過。原授權內的唯讀狀態查詢、一般 shell、不啟動真 agent 的測試及既有 routing 允許的原生 subagent 派工照常。

## Dispatch — Main session 不幹活

Main session 預設只做三件事：

1. Routing — 讀 STATE / plan / spec / memory 決定下一步要派誰
2. State read — `cat` / `ls` / `grep -l` 等小檔小指令
3. Surgical edit — < 3 行的精確修改

下列任一 → **考慮** dispatch subagent（不是強制；先看 Don't dispatch when 段是否命中）：

| Trigger | 派誰 |
|---|---|
| 預估 task 工作量 > 30K tokens（多檔 Read + 跨主題推理）| `deep-explore`（context-aware search/locate/inventory mapping；取代 built-in Explore）|
| Edit > 5 個檔 | `routed-impl` + plan |
| WebSearch / WebFetch / chrome nav > 2 次（事實研究類）| parallel-search，或 `routed-judge` 打包必要脈絡與原始來源；fork 規則見下方。 |
| 跑 > 30 秒指令（build / test / install）| Bash run_in_background |
| 多檔 refactor / 跨模組改 | Plan agent → 多 subagent 分檔 |

規模判準（治 overinvestment）：簡單事實查證 1 個 agent（3-10 tool calls）、直接對比 2-4 個（各 10-15）、複雜研究/全量掃描才 10+。fan-out 前先問「這題需要幾個」，不是預設開滿。

派工後先做不相依工作，禁止輪詢（`implement` 的 20 分鐘單次 `WORKER-WATCHDOG` 除外）。僅任務已無需、範圍改變或方向錯誤／不安全時中止 running agent。

## Don't dispatch when

下列任一 → **main 自己做**（不派 subagent，即使命中上面 trigger）：

- **需完整對話的工作**：main 自做，或把必要原文與來源交一般 subagent；fork 每次先問、只准當次，細節見 subagent-routing.md「fork 每次先問」。
- **應用 user rule**（反晶晶體 / voice profile / specific style）— 派出去 subagent 對細節 rule 容易 drift；例外：blog 產線的文體 phase——voice profile 已檔案化（repo `style/voice-profile*.md`）、phase prompt 逐字內嵌 rubric、產出必經使用者 review——可派 `blog-phase-runner`
- **Cross-check 既有 memory / inventory 而需要 reasoning「對應」**（subagent 拿不到既有清單的全貌）
- **Exploratory debugging**（你還不知道要找什麼 / 需要邊看邊調整方向）
- **Shared state**（agents 會踩到同一塊檔案 / state）
- **Quick targeted change**（< 3 行 / 確定範圍小）
- **Task 跨越單一 turn 才能解**（需要多輪 back-and-forth 才知道下一步）

**判準心法**：「這個 task 沒看過我的 CLAUDE.md / memory / 既有清單 / 對話脈絡，做不做得出來？做不出來 → main 自己做或用 `deep-explore`（它會 load context）」

例外：使用者明確說「你直接改」「不要派 subagent」→ 走 inline。

## Verify — Show expected, ask if matches

宣告任務完成前，不寫：
- 「測過了 / works as expected / should work now」
- 「應該沒問題了」
- 純粹「跑了 lint 沒錯」

改寫成逐項對照：

```
我預期會看到：<具體可觀察的 outcome>
實際看到：<貼 output / 截圖 / grep 結果>
匹配嗎？<yes / 差在哪>
```

驗證成本階梯：

- 完成宣稱列出實際檢查與結果，不必標 V0–V4。按成本選能直接驗證宣稱的最低級：不驗（純讀、未改）→語法／靜態→最近的單一測試→型別／build／套件→全套件／e2e。任何改檔至少語法或靜態檢查；改後行為宣稱需新鮮證據。
- 僅五種情況准升級：改動跨套件／服務／持久化／公開契約；安全／授權／migration／資料遺失／併發／release；窄檢查模糊或暴露更廣影響；窄檢查看不到關鍵宣稱；使用者或 repo 明文要求。不能只因有全套件便跑；implement 收尾固定一次全套件不受限。
- 純讀或未跑檢查，在宣稱旁寫「未驗證（Not verified）」；證據較窄就縮宣稱。agent 有工具可驗的不得以未驗結案；驗不到逐項寫原因。
- 說失敗原有或無關前，在改前版本（併上游用上游原版）的臨時 worktree 重跑同組測試，逐條對比失敗名稱；只比數量不算。

描述某機制「會擋／會保證 X」時，同句寫出它明文**不**保證的相鄰情況（例：「T2 gate 擋沒帶 token 的派工，不擋帶 token 但內容空洞的」）；只講會擋什麼、不講擋不住什麼，讀者會高估它。

失敗 case 處理：

- 同 session 內 < 3 個失敗 → 記在 response 表格直接修

## 方向錯訊號 — 該換路而非重試

計數口徑用 subagent-routing.md「失敗後升降級路徑」的唯一定義（key = 子任務 × root cause、單位 = 修正嘗試、上限 2 次），本節不另立。任一訊號命中 → 停止當前修法、回到問題定義重拆：

1. **同一 key 的修正嘗試額度用盡**（= 同一 error / 同一驗證項在兩次不同修法後第三次出現）→ 修的不是根因。驗的是不同項 = 不同 key、各自計數
2. **diff 越修越滾越大、開始動與任務敘述無關的檔，或同一個繞路修補跨無關位置反覆出現並違反原資料所有權假設（如被迫塞轉型 cast／`any` 或幫原本不共用的狀態加鎖）**。shared util 的直接 caller、單次合法邊界轉型或既有共享資源鎖不算
3. **發現自己在繞過驗證而不是通過驗證（最強訊號、單獨命中即停、不等額度用盡）**：放寬 assert、skip test、把驗收條件改弱、mock 掉真實路徑讓測試變綠、調大 timeout / 加 retry / 塞 sleep 掩蓋競態或效能退化、本次改動**新引入**的 warning 被無聲放行或驗收標準在修正迴圈中被單方面降級且未揭露（既有 warning 不觸發）。例外：測試本身寫錯（斷言與 spec 不符）且修前先列 spec 對照 → 合法修測試；節流參數本身即根因（調參前說得出「根因就是這個參數」並附證據，如 429 burst 調 stagger / cooldown）→ 合法調參

## 停下問使用者 vs 自己決定

先答後問：見 CLAUDE.md「問題一次收斂」條（能先答的先答、把模糊處先處理掉、要問一輪問完）。

任一命中 → 停下問：

1. **不可逆 / 破壞性動作且未被既有授權涵蓋**：對照 `git-workflow.md`「仍要 confirm」清單；工作 repo 無 vibe coding 授權、範圍更窄
2. **解法需要動使用者沒提到的系統邊界（scope 變更）**；同 repo 內順著原請求影響面的呼叫端不算
3. **goal-gen 五類 human blocker**：sudo / 需要使用者本人在場的動作（macOS 權限視窗、鎖手機、實體接線）/ 互動式 auth / sensitive credential 設定 / 系統升級 → Claude 結構性做不到、列出具體動作（含命令 / 路徑）等使用者。有工具可操作的 GUI（LCU、iPhone 鏡像、`ssh`／排程工作可操作的遠端機器）不算 blocker：agent 自己操作、自己驗，不推回使用者；例外是使用者要親自體驗的 UX 項目。有非互動 setter 的 config 變更 → 先查三點再說做不到（[[feedback_dont_overapply_interactive_cli_rule]]）
4. **修正額度用盡 + 換路仍不過**：接 subagent-routing.md「額度用盡四選一」的出口 4 → 帶完整失敗軌跡問（試過什麼、為什麼排除、剩什麼選項），不要只丟「做不出來」

反例通則（不問直接做）：動作可逆（git 可回復 / 檔案可還原）且是順著原請求的下一步 → 不問。「要不要我繼續？」「我可以開始了嗎？」這類問句一律禁止。
