<!-- 本檔在契約測試底下：bash ~/.claude/skills/handoff-impl/scripts/tests/friction-hardening.test.sh -->

# handoff-impl 設計文件

> 2026-07-16 brainstorm 定案（oldco-shop session、活體實驗 = QA PR #2209 round 1）。skill 本體依本文件走 skill-creator + writing-skills 流程產出。

## 目的

**主目的（a）**：跨 vendor 品管線——實作交給另一個 session 的 implementer（首發對象 ccp-gpt / GPT-5.6），main session（Claude）當 spec 打包者 + verifier，「寫的人 ≠ 驗的人」。

**副目的（d）**：實驗載具——用 `spec_level: outcome` 的單觀察強模型脫離 superpowers 中段儀式（executing-plans / subagent-per-task）的自主實作品質，餵「superpowers 對強模型是否太重」議題。

**路徑**：c（實驗期、迭代流程本身）→ a（常備工具）。2026-08-06 經 8 張真實實作單與三輪 review 後畢業；摩擦紀錄與批次折入迴路保留為常備維護機制。

## 定位邊界（信道，不是規範）

| handoff-impl 管（純信道層） | 不管（既有機制地盤，引用不重寫） |
|---|---|
| 檔案骨架：frontmatter schema + 八段標題框架（含 `ENV_READY` 收據） | Spec 段內容——由既有流程（brainstorming / writing-plans / 六件套）產出後裝進容器 |
| 狀態機四態 + 單側寫入權 + round append | 驗收條件怎麼訂 |
| 無參數自動發現 + 角色確認 | 驗收怎麼跑（指向 dispatch-and-verify + dispatch-templates ⑤ 敵對立場） |
| implementer 信道規則（不准問 / 只寫回報段 / 不 push / 不動協議段） | spec 規定性拿捏、過度設計提醒（規劃者一般職責） |
| 摩擦欄 + friction log + 重複／數量門檻批次折 | 風格約束（CLAUDE.md / repo 規範） |
| bootstrap prompt fallback | |

工作流定位：不取代任何現有 lane；新增第 6 條「跨 session、user 中介、檔案信道、正式驗收合約」。長期蠶食 Lane 2（in-session subagent 實作）的中大型份額；Lane 3 只換掉 executing 段（上游 brainstorm/OpenSpec/plan 與下游 finishing 不動）。與 codex:rescue 的分工線由後續真實摩擦決定，不預先立規。

## 檔案協議

- 位置 `~/.claude/handoffs/<date>-<slug>.md`；ACCEPTED 收案移 `~/.claude/handoffs/done/`（掃描只看 active）
- frontmatter：`status`（SPEC_READY / IMPL_DONE / ACCEPTED / CHANGES_REQUESTED）、`round`、`round_base`（Git 任務本 round 的起點 commit；非 Git 為 N-A）、`spec_level`（method|outcome，純告知 implementer 自由度的欄位、不附模板）、`workdir`、`branch`、`pr`、`runtime`（釘死執行環境，如 node 版本 + PATH 前綴）、`scope`（自由文字；Lane 3 用寫 plan 路徑 + phase 範圍）、`test_evidence`（permanent|transcript|verifier-probe，預設 transcript）、`implementer`、`verifier`
- 正文八段：implementer 協議 → 背景（自包含）→ Spec → 約束（禁動檔等）→ `ENV_READY`（開工前置的驗證者 / 執行環境／probe／預期／實際／ready 收據）→ 驗收條件（可執行命令 + 預期輸出）→ 實作回報（implementer 專屬、按 round 分節、必填協議摩擦欄）→ 驗收記錄（verifier 專屬 append、按 round 分節、必填摩擦欄）
- `ENV_READY` 的每列只接受 `yes`、`no`、`N-A（理由）`；所有列皆為 `yes` 或有理由的 `N-A` 才能交單。implementer 依賴的 credential 或控制面能力要在 implementer runtime probe；無法預驗時明列為開工第一步且失敗即停損。純檔案任務仍要證明 workdir 與 runtime 可用
- Spec 段可以是指標：workdir 內已有 plan/spec artifact 時寫「讀 X 檔執行 Y 範圍」，不複製內容；引用外部檔案作先例前要實讀並附行號／片段，讀不到只能列未驗證候選、不得據此指定改法或驗收。outcome 級單的機制路徑若未對完整 code chain 實證，逐句標「未驗證推測」，驗收仍看可觀察 outcome

## 狀態機與角色 dispatch

```
/handoff-impl <任務描述>   → create：從對話脈絡打包 handoff 檔 + 輸出 bootstrap 行
/handoff-impl              → 無參數：掃 active 單 → 按 status 定角色
   SPEC_READY / CHANGES_REQUESTED → 本 session = implementer
   IMPL_DONE                      → 本 session = verifier
   恰一張 → 一行角色確認後執行；多張 → 列表（cwd 對位 workdir 者排前）；零張 → 回報無單
/handoff-impl <檔>         → 指定單，同上按 status 定角色
```

- 誤觸防護：執行前必出一行角色宣告（「單 X、status=Y，我以 Z 身分…確認？」）等 user 點頭
- 寫入權：status 與 round 的推進單側化——implementer 只改 status→IMPL_DONE；verifier 寫 ACCEPTED / CHANGES_REQUESTED 並在退回時 round+1
- bootstrap fallback：create 產出時附一段純文字 prompt（「讀 X 檔，你是 implementer，照協議執行"），implementer 非 CC 時用

## implementer 協議（寫進骨架的協議段）

- 不准問（session 無人回）：Spec 有預設照預設、沒寫到的小事自采合理預設並列進回報；dcg 攔截先換等價非破壞性作法，換不掉就停損交單
- 只寫「實作回報」段 + 改 status；不 push、不動 PR、不 rebase；Git 任務交單前 commit 留本地給 verifier；submodule 的 base／diff／commit 數與 commit 都在 submodule 內取得，另報 superproject status，pointer 是否上推由單內約束決定
- Lane 3 / 多 phase 單（b 模式）三守則：逐 phase commit + 跑 plan 內建的 phase 自檢；自檢過不了且範圍內修不好（對照 dispatch-and-verify 方向錯訊號）→ 停損交單，回報「做到 N、卡在 M、原因 X」，不蓋壞地基、不自改計畫
- 回報必填：Git 任務由 `git diff --name-only <round_base>...HEAD` 產生本 round 改動清單 + `git status --short`，非 Git 直接列檔案；另補 file:line、驗收命令原樣輸出、test_evidence 對應證據、沒做的部分、發現但沒動的問題（無則明寫）、協議摩擦欄。同一 round 內重試以 `Attempt <N>` 或時間小節記錄，`Round` 只代表 verifier 退回輪次

## verifier 協議

- 不採信回報數字；Git 任務先檢查 `git status --short`，與本單相關的未 commit 修改代表尚未交單、不開始驗收；既有且無關的髒檔只記錄、不阻擋。本單改動已 commit 後，用 `round_base...HEAD` 判本 round 歸屬、用三點 merge-base diff 看累積產品改動；非 Git 任務依回報檔案清單與驗收產物逐項核對。兩類都重跑全部驗收命令並做敵對立場 review（引用 dispatch-templates ⑤）；回報中「發現但沒動的問題」查證後才收錄
- 驗收記錄用「預期 / 實際 / 匹配」表；多 phase 單沿 commit 軌跡逐段驗
- 退回：findings 固定格式（file:line + 問題 + 失敗場景）、status→CHANGES_REQUESTED、round+1；Git 任務同步把當下 HEAD 寫進 `round_base` 作下一 round 起點，非 Git 保持 N-A
- 上限 2 輪退回（本質是方向錯煙霧偵測器，非省額度）；質性訊號（diff 越滾越大 / 繞過驗收 / 同 error 換裝重現）任一命中不等額度直接升級；升級摘要 = 試過什麼 / 為何不過 / 剩什麼選項
- ACCEPTED 後停下報告，git 動作（push / 更 PR）等 user 指示（預設值，user 可單次授權）

## 常備迭代迴路

- 雙側摩擦欄必填 → bug 級摩擦即折回 skill（走 skill-creator）；判斷級 append `~/.claude/skills/handoff-impl/friction-log.md`「待折」段
- 每次 append 後計數：同類摩擦第 2 次，或待折達 3 項 → 當次收案走 skill-creator 內建的 RED → GREEN → REFACTOR 行為驗證迴圈批次折；未達門檻就留給後續單據
- 折入時保留原始摩擦，移到「已折／已否決」並附日期與修改落點；不再依賴 trial review 日期或使用者想起來巡檢
- outcome 級單另立觀察軸（GPT 自主方案品質 vs method 級 spec 品質），餵 d 議題，不影響常備信道運作

## Non-goals（明列不做，防範圍蔓延）

- 自動跑腿（SessionStart hook 注入待辦單提醒、檔案輪詢自動驗收）——friction log 候選，被跑腿煩到再做
- implementer 側專用 command——bootstrap prompt 即萬用介面
- method/outcome spec 撰寫模板——spec 內容歸既有機制
- 機械腳本（handoff.sh）——常備後仍不做；目前檔案協議與 Skill dispatch 足夠，只有重複手寫同形狀命令形成摩擦時才重評
- spec 寫作 / review / 研究類 handoff——另一種形狀，留給未來通用 `handoff` 設計

## 常備範圍

Lane 2 大小的自包含任務是已驗證主場；Lane 3 整合沿用「Spec 段可為指標 + scope 欄位 + implementer 三守則」，不另加第二套協議。

## 2026-07-17 增補：自動接力信道（transport 第二選項）

動機：手動流程 user 當人肉信使兩次（搬單去 codex、完工再搬回），卡的是使用者注意力。解法評估過 ACP / edda task rail（見 memory reference_edda_eval_2026_07_17），結論：CC 原生零件已夠——Bash run_in_background 完成通知 = 快路徑、Step 0 掃描 = 兜底（level-triggered：快路徑掉了是晚點撿、不是單丟了）、單內回報 = 收據。ACP 只在「獨立調度器跨 vendor 駕駛」的路線才有戲，此處調度器就是 CC session 本身，不引入。

邊界不變：自動模式只換信使（誰搬單、誰盯完成），狀態機、單側寫入權與驗收合約全部沿用。手動是固定預設；只有使用者在本次任務明確點名「自動接力／背景派工實驗」才進自動路徑，概括委外語句不構成授權。自動 implementer → 完成喚醒 → verifier 的完整活體鏈仍未驗證；CHANGES_REQUESTED 是否自動重派不預先立規，留給 friction log 觀察。
