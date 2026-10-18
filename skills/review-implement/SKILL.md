---
name: review-implement
description: "Use after a spec-backed implementation reaches closeout and before shipping when a post-implementation scope or YAGNI review is needed, or when the user explicitly invokes `/review-implement`. Do not use for pre-implementation spec review, correctness code review, or code repair; use `review-spec`, `/code-review`, or `implement` instead."
---

<!-- 本檔在契約測試底下：bash ~/.claude/skills/review-implement/scripts/tests/review-implement-contract.test.sh -->
<!-- 本檔在契約測試底下：bash ~/.claude/skills/implement/scripts/tests/review-implement-handoff-contract.test.sh -->
<!-- 本檔在契約測試底下：bash ~/.claude/skills/implement/scripts/tests/architecture-visual-gate-contract.test.sh -->

# review-implement

把 review-implement 放在 implement closeout 完成測試、code review、修正與 local commits 後，final push／PR handback／archiving 前，當成唯讀的 post-implementation acceptance gate。Scope 檢查實作是否留在已接受的決策內；YAGNI 檢查 final diff 能否縮小而仍滿足同一組 confirmed acceptance。兩軸分開，Main 保留 evidence verification 與決策責任。

## 1. 自動選軸與 Opus 席，揭露後鎖定 target

1. 本 Step 1 是唯一的 user-facing SSOT。Stage 啟動後，在任何 reviewer dispatch 前先逐字輸出固定三句，再輸出自動選軸結果、角度建議、模型矩陣與推薦理由，最後顯示選單。輸出完不等回答，直接接第 2 步；選單只是讓使用者改選或 skip 的入口，不是 gate：

   ```text
   剛完成 implement、測試與 commit。
   現在要確認實作留在 accepted scope 內，並看看能不能縮小。
   選 a/all 跑兩軸；選 b/scope 或 c/yagni 跑單軸；選 d/skip 只記 WAIVED，不跑 review。
   ```

   軸由推薦規則自動決定：一般 spec-backed work 跑 `scope`。符合任一 long-axis signal 時跑 `all`：存在 wayfinder、ticket count >= 3、工作跨過 session／resume boundary、或 code review 產生至少 3 個 confirmed core findings。這是角度建議，不是模型能力排名。

   自動選出的軸一律用 Claude 側的 Opus 席（`routed-judge`／`opus`）：`scope` 派 `opus/scope`，`all` 派 `opus/scope` 與 `opus/yagni`。揭露要寫明選了哪軸、哪幾席、依哪一條訊號（沒有 long-axis signal 就寫「無 long-axis signal」）。Fable 席耗外部額度，只列為推薦或可選，Fable seat 只在使用者明選時才派；沒有回答就不派、也不擋收尾。使用者若已在 invocation 或同輪訊息說 skip 或指定 seat，以使用者說的為準，不套自動選擇。

   先把 Scope／YAGNI 當工作目的、把 model／execution path 當執行選擇，列出本次可配矩陣。模型／執行路徑為列，當次適用審查角度為欄；每個 cell 都標 `推薦`、`可選`、`需補材料／工具` 或 `不可用`。自動選出軸上的 Opus cell 標 `推薦` 並註明「自動派」，未選軸上的 Opus cell 標 `可選`：

   | 執行路徑／logical model（resolved model） | Scope | YAGNI |
   | --- | --- | --- |
   | `routed-judge`／`fable`（`fable`；native 從 model options cache 解出，vendor 從既有 mapping 取值） | `<本輪狀態>` | `<本輪狀態>` |
   | `routed-judge`／`opus`（`opus`；native 從 model options cache 解出，vendor 從既有 mapping 取值） | `<本輪狀態>` | `<本輪狀態>` |

   這兩列是本 stage 已有的完整執行路徑，不是固定推薦；每次依本次任務與材料，在每個 cell 填一個 `推薦`、`可選`、`需補材料／工具` 或 `不可用`。例如本輪若需要獨立觀點，可把 fable cell 填 `推薦`（仍不自動派，等使用者明選）；這只是示例，不是預設或能力排名。若某列缺 mapping、材料或工具能力，就在該 cell 寫明原因，不隱藏也不靜默換列。只知道 logical alias 時把 resolved model 寫成 `unknown`。推薦理由只能引用材料完整性、本地讀取需求或是否需要獨立觀點；同級模型是選用前提，不把名稱或階級寫成量測排名。

   矩陣完整呈現後、固定選單前，另輸出一行 `Recommended seats: <model>/<axis>[, ...]`；這行只列本輪標為 `推薦` 的 seat，供使用者回「照推薦」時綁定當次選擇。使用者可用自然語言回「照推薦」、「scope 用 opus」、「all 都用 opus」或「scope 用 opus 和 fable」，也可明說增減角度；派出後才到的回答只增加尚未派出的 seat（例如補選 Fable），已派的 seat 不重派。這幾種句型整句就是選擇本身，後面不要再接問句或補充——授權 gate 對整句比對，「all，但都用 opus 行嗎」這種帶尾綴的回答會被判成未綁定選擇而擋下，得重跑選單。只回 `scope`／`yagni`／`all` 或固定字母時，使用本輪矩陣標成推薦的 seat，不暗加其他可選 seat。Controller 將自動選擇與使用者回答整理成當輪的 `<model, axis>` seat 清單，未明說且非自動選出的 seat 不啟動；不要求使用者重打 flags 或 command 參數。

   ```text
   Choose review axes:
   a. all
   b. scope
   c. yagni
   d. skip
   ```

   使用者的回答只接受 top-level user 的完整 axis、固定字母或包含明確 model／axis 的自然語言；把字母轉成 semantic axis 後再寫 report。沒有回答不阻擋：Opus 席照推薦已派，Fable 席沒被明選就不派，Run 照常往下走。完成條件：聊天中有逐字固定選單、自動選軸揭露、角度與模型推薦；使用者若有回答，其選擇 evidence 也記下；report 記錄 semantic axes 與 selected seats。

2. 使用者說 `skip` 時直接接第 8 節，寫入 `WAIVED`，不要求 target、model 或 reviewer input。其他情況（含沒有回答）才確認 stable `base_sha` 與 `head_sha` 都是 target feature 的 commit，並以該 range 讀 final diff。target-scope 只要仍在未 commit 的 working tree，就把 Run 記為 `BLOCKED`，不審 moving target，也不先設 speculative size gate。

   完成條件：非 skip Run input 有可重現的 target、`base_sha`、`head_sha` 與 selected seats；若任一不穩定，report 有 `BLOCKED` event 且沒有 reviewer output；skip 直接產生 `WAIVED` event。

3. 一個 feature 只使用一份 report：OpenSpec 變更寫到 `openspec/changes/<change>/review-implement.md`，scratch feature 寫到 `.scratch/<feature>/review-implement.md`。新 Run 先 append input 與 start event，再 dispatch；start event 記選擇來源（auto 或 user）。

   完成條件：目標路徑唯一，且當前 Run 的 target、commit range、spec、tickets、selected axes 與 selected seats 已落檔。

## 2. 組兩個互斥的 context

1. 為 Scope 由 Main 自動重建 raw session chain。從 save／resume handoff 開始，遞迴追蹤 handoff path、session IDs 與 transcript references；每條 edge 都記錄一個唯一 handoff／session-ID evidence tuple。缺 edge、同一 edge 有多個候選、session ID 對不上或 transcript reference 有歧義，都把 Scope axis 記為 `failed`、Run 記為 `BLOCKED`，不猜 chain，也不把可查的 path 丟回使用者找。

   Scope authority 順序固定為：最新的 explicit top-level user-authored decision → accepted wayfinder／grill resolution → spec → ticket → code convention。assistant、tool、agent 與外部引用只能當 evidence；後續 top-level user 明確接受後才升為 scope。同一層衝突保留成 `PLAUSIBLE` scope finding。

   Scope packet 只交 raw-session paths、authority contract 與 stable diff，讓 reviewer 用 Read／search 按需取資料；不把 Main conclusion、YAGNI output 或整段 raw session 複製進 prompt。

   完成條件：每條 chain edge 都有唯一 evidence；chain 不完整時已產生 `BLOCKED` 而沒有猜測；Scope reviewer packet 不含 Main conclusion。

2. 為 YAGNI 組乾淨 packet，只放 confirmed requirements、acceptance clauses／IDs 與 stable final diff。排除 raw sessions、作者辯護、implement-author conclusion、前輪 findings 與 Main final judgment。每條 YAGNI finding 都要求 diff hunk、較小替代方案，以及仍滿足的 acceptance IDs。

   完成條件：packet 可逐項列出每個 confirmed requirement／acceptance，且 grep 不到 raw session、author defense、previous finding 或 final judgment。

## 3. 依選定 seat 沿既有 routing 形狀派 reviewer

Scope／YAGNI 是工作目的，model／execution path 是 seat 選擇。這個 stage 目前列出 `routed-judge` 的 `fable` 與 `opus` 兩條既有路徑；把 logical model 與 resolved model 分開記錄。native 路徑從既有 model options cache 解出值，vendor 路徑取既有 mapping；只知道 alias 時記 `unknown`，派工完成後再以 subagent jsonl 的 `message.model` 記錄實際值。缺 mapping、材料或工具能力的 cell 不派工，保留不可用原因。

每個 selected seat 使用同一個 reviewer type，description 的 selection marker 綁定該 seat。自動選出的 Opus 席不等使用者回答就派；派工檢查 hook 對沒有使用者選擇的 Opus 席只留 `would_deny` 稽核列並放行，這是預期行為，不補使用者選擇、不改 marker、不換 `subagent_type`：

```text
Agent(
  subagent_type: "routed-judge",
  model: "opus",
  description: "<review-implement-selection:v1 model=opus axis=scope>",
  prompt: "<Scope packet + scope-only instructions>"
)
```

Fable seat 使用 `model: "fable"` 與 `<fable-ok> <review-implement-selection:v1 model=fable axis=scope>`；YAGNI 只把 `axis=scope` 換成 `axis=yagni`。既有 `<review-implement-fable:v1 axis=scope|yagni>` 仍可讀作相容快捷方式，但新選用一律記 generic selection marker。不要改成其他 `subagent_type`、裸 Fable 或新的 permit 機制。

- 每個 `<model, axis>` selected seat 恰派一次；同一 axis 可選兩個不同 model，不能因推薦而暗加另一席。
- 選 `scope` 或 `yagni` 時只派該軸已選 seat；選 `all` 時平行派出本輪 selected 的 seat（自動選出的 Opus 席，加使用者明選的 seat），不把 `all` 擴成未列出的模型或配對。兩個不同 model 的 prompt 不放對方 output、finding 或結論。
- 同一 report Run 的 failed-seat retry 先以新的成功 `Skill(review-implement)` invocation 重新顯示同一份矩陣與固定選單；使用者重選後只派失敗的 `<model, axis>` seat，成功 seat 不重派。保留每次 dispatch 的 logical／resolved model、selected seat 與 agent result。

完成條件：每個 selected seat 恰有一個獨立 dispatch，報告只列本輪 selected seats；retry event 只增加失敗 seat，且同一 assistant response 啟動的平行 seat 互不共享 output。

## 4. 收齊結果，對失敗 fail closed

等本輪所有 selected seat reviewer results 都回來後才進 Main triage。Reviewer failure、實際發生的 context overflow、或 Scope 找不到完整 chain 都是該 seat 失敗、所屬 axis `failed` 與 Run `BLOCKED`；不要用另一個 model 或 seat 靜默替代，也不要用 speculative session／byte limit 先拒絕。

同一 axis 若一個 seat 成功、一個 seat 失敗，成功 seat output 仍附在同一 Run；向使用者提供 retry、換 mapping 或 waive。使用者選 retry 後重新 invoke 本 skill、顯示同一份矩陣與固定選單，再只派 failed `<model, axis>` seat。若使用者 waive 該 seat 或所屬軸，記錄 `waived`，不要把它改寫成 `completed`。

完成條件：report 同時保存每個成功與失敗 seat 的結果／原因；retry 不會重新派成功 seat；缺資料與 runtime failure 都可追到 `BLOCKED` event。

## 5. Main 逐條驗證與決策

Main 收到本輪全部 reviewer 結果後，逐條查相關 evidence，再決定 finding。合成只使用本輪 selected seats 的 output，按 `<model, axis>` 保留來源；未選 seat 不補成缺席、不寫成完成。source／requirements evidence 每條都查；只有 behavioral claim 才跑 regression test；只有 safety／risk claim 才查 threat model。先去重再逐條依授權缺口分流，保留每個來源 ID 與 evidence。

- Scope finding 用 `S1`、`S2`…；每條附 session path、event／turn ID、verbatim top-level user quote 與 implementation file:line，並標 `CONFIRMED` 或 `PLAUSIBLE`。直接 evidence 證明 reviewer 誤讀時才 dismiss；`CONFIRMED` scope finding block completion，`PLAUSIBLE` scope finding 上呈使用者。
- YAGNI finding 用 `Y1`、`Y2`…；每條附 diff hunk、較小替代方案與仍滿足的 acceptance IDs。是否上呈只看授權缺口，不看 finding 數量、reviewer 異議或可撤回性。留在已批准授權內、且不改既有 acceptance 的條目，Main 查證後自決 `accept` 或 `dispute`，並記下 evidence 與理由；沒有實益就 `dispute`。`accept` 轉成 repair obligation；`dispute` 留在本輪 disposition，不因 reviewer 不同意就上呈。提案若是未批准的需求縮減、新承諾、範圍擴張或風險承擔改變，才標使用者待決策；只暫停依賴該決定的工作，已批准且不相依的工作繼續。
- 去重後的列數只影響呈現：列數多時先給完整 overview，仍逐條做上面的授權分流。不因列數 >5 停止自動處理，也不隱藏、刪除或合併到使用者看不到的 finding。

**橡皮圖章訊號靠紀錄算出來，不靠記得。** 派 reviewer 前先讀回同一份 report 既有 Run 的 disposition 行（`grep -h '^- disposition:' <report 路徑>`），當場數出前幾輪各有幾條 substantive finding、其中幾條被 accepted，並印給使用者。**連續 2+ 輪有 substantive findings 而 0 條 accepted** 就停下，把 Main 的判定理由攤給使用者檢查，不要繼續蓋章。首輪查無前輪 disposition 就明寫查無，不要當成乾淨。

完成條件：每條 finding 都有對應 evidence 與 `S`／`Y` ID；授權內條目有 Main 的 `accept`／`dispute` 與理由，只有未批准的需求縮減、新承諾、範圍擴張或風險承擔改變才標使用者待決策，且只暫停相依工作；列數不決定是否上呈，列數多時 overview 與逐條分流一起留下，不自動關閉待人決定的列；dispatch 前已輸出前輪 disposition 統計或「查無前輪」。

## 6. 保持唯讀，讓 implement 完成既有 obligation

Reviewer 與 review-implement 不修改 production code。Main 將 accepted scope／YAGNI findings 交回 implement 作為 repair obligations；本 stage 只 append report event，不在 review 裡找、修、再自我批准。

每次 repair attempt 後只對 accepted 的原始 finding IDs 與其 acceptance evidence 做 targeted recheck。targeted recheck 不得新增 finding；失敗就維持 `BLOCKED`，把同一 finding ID 依既有 correction budget 交回 implement，不要求使用者重複決定同一 obligation。只有 correction budget 用盡、需要擴大 scope，或要開新的 full review 時才請使用者決定。

不要在 targeted recheck 後自動開新的 full review。所有 accepted obligations 的 targeted recheck 通過後，implement 仍須針對新的 `head_sha` 跑 final suite，Run 才能轉成 `PASS`；新的 full review 仍由使用者啟動。

完成條件：code diff 在本 stage 維持不變；每個 repair event 只引用既有 ID；targeted recheck 沒有新 finding；沒有自動 full-review dispatch。

## 7. 以單一 append-only report 留下 Run 歷史

每個 Run 使用以下欄位，summary 可以更新當前狀態，但歷史 event 不覆寫。Axis status 只列 selected axes；未選 axis 不算 `waived`，`skip` 才依第 8 節把兩軸明確記為 `waived`。Selected seats 以 `<logical model, axis>` 記錄，不把任何一個 model 當成固定 Run model：

```text
## Run 1
### Input
- target:
- base_sha:
- head_sha:
- spec:
- tickets:
- raw_session_paths:
- selected_axes:
- selected_seats:
- logical_models:
- resolved_models:
- started_at:
- session_count:
- total_raw_bytes:
- elapsed_time:
- token_use:
### Axis status
- scope: completed | failed | waived
- yagni: completed | failed | waived
### Events
### Findings
### Main decisions
### Dispositions
### Repair obligations
### Targeted rechecks
### Summary
- Run status: PASS | BLOCKED | WAIVED
```

`resolved_models` 逐一對應 selected seats；只能知道 alias 時寫 `unknown`，不能把 alias 當成已確認的底層模型。Run status 只使用 `PASS`、`BLOCKED`、`WAIVED`：

- `WAIVED`：使用者選 `skip`，或 selected seat／axis 被明確 waive。
- `BLOCKED`：selected seat failed、decision unresolved、chain／context 不完整，或 repair obligation 尚未通過 targeted recheck。
- `PASS`：每個 selected seat 所屬 axis 都是 `completed`、所有 obligations 的 targeted recheck 都是 `pass`，且 implement 已對新的 `head_sha` 完成 final suite。

`### Dispositions` 段逐條寫一行固定形狀，讓下一輪與跨機制統計都只需一個 grep：

```text
- disposition: <ID> | <class> | main=<verdict> | user=<verdict> | <一行理由>
```

- `<ID>` 用該 finding 的 `S`／`Y` ID；`<class>` 寫 `scope` 或 `yagni`
- `main=`：Scope 用 `CONFIRMED`／`PLAUSIBLE`／`dismissed`，YAGNI 用 `accept`／`dispute`
- `user=`：`accepted`／`dismissed`／`deferred`／`n/a`，其中 `n/a` 代表 Main 自決、沒上呈；上呈的條目照使用者實際回答填，不預填
- 這一行的形狀與 /review-spec 落檔共用同一形狀，所以兩支機制的紀錄可以一起 grep
- 沒有任何條目上呈的 Run 也要寫這段——全部 `user=n/a` 是有資訊的紀錄

完成條件：Run 內有 input、各軸 status、events、findings、Main decisions、dispositions、repair／recheck 與 summary；每條 finding 恰有一行 disposition；新增 Run 只 append，舊 Run 的 events、decisions 與 dispositions 保持原樣。

## 8. `skip` 只代表明確 waiver

使用者選 `skip` 或固定選單的 `d` 時不派 reviewer，寫入一個 explicit `WAIVED` Run event，`selected_axes: none`、`selected_seats: none`，並將 Scope 與 YAGNI axis 記為 `waived`。回覆可以說 review 已 waived，不可以宣稱 review `PASS`。

Opus 席派出後才收到 `skip`：已派的 seat 不中止、照常完成並記錄，各軸 status 照實寫 `completed` 或 `failed`；Events 另記一筆使用者 waive（時間與原話），Run 記下使用者的 waive，Run status 寫 `WAIVED`，Summary 註明已派 seat 與其結果，不宣稱 `PASS`。已回來的 findings 仍照第 5 節記錄並揭露，不因 waive 刪除。

完成條件：skip Run 有使用者選項 evidence、Run status 是 `WAIVED`，且沒有 reviewer output 或 PASS claim；派出後才 skip 的 Run 有已派 seat 的結果、使用者 waive 的 event，且沒有 PASS claim。

## 首版邊界

首版只提供這個 stage 的 instructions、既有 routing gate 的授權形狀與 contract test。不新增 Workflow、hook、binary、reducer、manifest、agent definition、context-size gate 或 session-chain producer；不重做 `/review-spec`、`/code-review`、測試或 TDD，也不宣稱 reviewer reasoning、dedupe 或 status reduction deterministic。

## 踩過的坑

- 只給 sanitized context 的 reviewer 會漏掉 raw session 裡的禁止項與未拍板 scope；Scope 先重建 chain，不能用猜測補洞。
- 把 Scope 與 YAGNI 放在同一個 prompt，或把一軸 output 轉給另一軸，會把獨立判斷變成互相 anchoring；`all` 只共享 stable diff 與各自契約。
- 把作者辯護、前輪 findings 放進 YAGNI packet，會讓 reviewer 替既有實作找理由，而不是找更小替代。
- 只看到 reviewer 的 finding 就自動接受，會把誤讀升成 obligation；Main 先查 evidence，再決定 dismiss、CONFIRMED、PLAUSIBLE、accept 或 dispute。
- `skip` 不是乾淨 review；它是可追溯的 `WAIVED`。targeted recheck 也不是新一輪 full review，否則 accepted obligation 會形成無限 loop。
