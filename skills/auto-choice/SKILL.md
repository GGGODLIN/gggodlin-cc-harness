---
name: auto-choice
description: "Use when 一段實作已完成、交回或合併前，需要列出實作者在規格或 prompt 沒寫到的地方自己做了哪些決定——implement closeout 在 commit 前呼叫；使用者說「列出你替我做的決定」「auto-choice」「這段你自己拍板了什麼」，或臨時修改越改越大、/goal 或 handoff-impl 跑完、subagent 交件回來時也用。Do not use for 正確性 code review（/code-review）、範圍或 YAGNI 審查（review-implement）、實作前的 spec review（review-spec）、修改程式碼或修 bug。"
metadata:
  upstream: dzhng/skills
  upstream-path: skills/engineering/audit-choices/SKILL.md
  upstream-pinned: d513228
---

<!-- 本檔在契約測試底下：python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py；bash ~/.claude/skills/implement/scripts/tests/review-implement-handoff-contract.test.sh（接線） -->

# auto-choice

規格沒寫到的地方，實作者會自己拍板，diff 不會標出來。程式能跑，不代表那些決定是使用者會做的；它們會被之後的工作照著用下去。這支把那些決定列成**帳本**，讓人審決定、不審 diff。

只審、不改：不動 code、測試或 build 狀態。可以讀任何檔、跑既有測試、寫臨時探針，但交回前刪掉探針。不擋流程：每條判定是交給下一個行動者的判斷，不是停下來等回答的問題。

## 1. 收集決定

1. 先問實作者（審自己的 session 就問自己）：「規格沒寫、你自己決定的事有哪些？全列。」這只是起點——實作者會少報。
2. 回頭追證據：session 步驟、subagent 回報、diff、commit。每條決定記出處（`file:line`、commit 或 session 位置）。
3. 逐類掃，每一類都寫「有（列哪幾條）」或「無」，不能空著：
   - 資料形狀與格式
   - 存放位置與命名
   - API 契約與錯誤行為
   - 新增的相依套件，連同它帶進來的預設行為與上限
   - 並行與效能取捨：快取、容量上限、逾時、重試
   - 範圍解讀：套用範圍比規格寬或窄
   - 測試設定改動：timeout、skip、mock、放寬斷言
   - 之後的程式會照抄的模式
4. 規格明文交給實作者自決的不列；內部命名、純外觀選擇合併成一行計數。

非小改動卻掃出 0 條，代表沒掃乾淨：回頭找規格留白的地方，總有東西填了那些空。

完成條件：八類每類都有「有／無」；每條決定都有出處。

## 2. 判定

每條給兩個值：

- **判定**：`sound`（合理）／`unsound`（要重做）／`needs-user`（只有使用者能決定）。
- **把握度**：低／中／高——你多有把握使用者會做同樣的決定。這個值決定排序。

判定方式：

- 「能跑」不是判定。調大 timeout 或 buffer、加特例這類剛好蓋過失敗案例的修法，要問「什麼性質保證它一般成立」；答案只是「這個案例過了」就判 `unsound`。
- `unsound` 寫出該從哪個正確決定重做（必須成立的性質），不寫補丁。在錯的決定上打補丁，等於保留錯的決定。
- `needs-user` 只留給品味、產品方向、外部成本這類真的只有使用者能決定的事；每條附一個可撤回的暫定做法和撤回方式，無人值守的流程照暫定做法繼續。

完成條件：每條都有判定與把握度；每條 `unsound` 有正確決定；每條 `needs-user` 有暫定做法與撤回方式。

## 3. 寫帳本

位置依專案慣例：

- 有 openspec change → `openspec/changes/<change>/choices.md`
- 有 `.scratch/<feature>/` → `.scratch/<feature>/choices.md`
- 沒有 spec → session scratchpad 的 `choices-<主題>.md`

檔案已存在就 append 一段，以本次 pass 或 commit 當段標題。已記在帳本裡的決定是定案，不重列、不重判。

每條六欄：

- **何時**：落在哪個 pass 或 commit
- **決定**：一行標題，再寫白話情境——觸發事件、現在怎麼做、沒選的做法會怎樣；術語第一次出現就地解釋。讀者沒看過 session、diff 和 spec，也要讀得懂
- **規格缺口**：規格哪裡沒寫，逼出這個決定
- **影響範圍**：之後哪些工作會被它綁住
- **判定**：值＋一句理由（`unsound` 附正確決定；`needs-user` 附暫定做法與撤回方式）
- **把握度**：低／中／高

同一區塊的條目扎堆，代表規格在那裡有霧：在帳本段尾建議回 spec 重切那一塊，不要一直判同一類決定。

完成條件：帳本檔存在；本次每條都有六欄。完成後接 Step 4。

## 4. Self-Verify

帳本寫完、呈現之前，派一個 subagent 對帳本對表：

- `Agent` tool，`subagent_type: skill-verify-auditor`
- description 固定含 `skill-verify:auto-choice`
- prompt 內嵌本次帳本段全文與下方 template（`{ledger}` 換成全文）

本回合這支 skill 只有一次 auditor 額度：不論結果都不重派，也不用 SendMessage 續問同一個 auditor。

```
你是 adversarial 合規審查員，檢查一份「實作決定帳本」是否遵守規矩。偏置是找違規：無法從帳本文本確認有遵守就判 FAIL。

帳本原文：
{ledger}

逐條檢查（每條回 PASS / FAIL + 一句證據引述）：

R1【八類掃描】帳本是否對八類（資料形狀與格式／存放位置與命名／API 契約與錯誤行為／新增相依套件／並行與效能取捨／範圍解讀／測試設定改動／會被照抄的模式）逐一寫了「有」或「無」？缺任一類 = FAIL。

R2【判定與把握度】每條是否都有判定（sound／unsound／needs-user）與把握度（低／中／高）？

R3【可行動】每條 unsound 是否寫了該重做成的正確決定（不是補丁）？每條 needs-user 是否有暫定做法與撤回方式？沒有這兩類條目 = PASS。

R4【白話情境】每條「決定」欄是否有觸發事件、現在怎麼做、沒選的做法會怎樣三件事？只有一行標題 = FAIL。

R5【出處】每條是否附出處（file:line、commit 或 session 位置）？

輸出格式（最後一行必須是 verdict 行）：

R1: PASS|FAIL — <一句證據>
R2: PASS|FAIL — <一句證據>
R3: PASS|FAIL — <一句證據>
R4: PASS|FAIL — <一句證據>
R5: PASS|FAIL — <一句證據>
<verdict 行>

verdict 行二選一，整行照抄其中一種：

VERDICT: COMPLIANT
VERDICT: VIOLATIONS: <R 編號逗號列表>

保留意見寫進該條證據句，不要寫進 verdict 行。
```

收尾四態（寫在呈現的最後一行）：

- 全 PASS → `🔎 self-verify: COMPLIANT (5/5)`
- 有 FAIL 且已修帳本 → `🔎 self-verify: FIXED_AFTER_AUDIT — R#（…）`，同句寫「未經第二次獨立稽查」
- 有 FAIL 且修不掉 → `🔎 self-verify: FAILED — R#（缺口）`，撐不住的條目刪除或降級成「未完成：缺 <欄位>」，不原樣交付
- auditor timeout、空輸出、格式錯誤 → `🔎 self-verify: SKIPPED (agent error)`

完成條件：本回合已出現一次 `skill-verify:auto-choice` 的 Agent dispatch，且收尾落在四態之一。完成後接 Step 5。

## 5. 呈現

1. 開頭一行「先看這幾條」：整本帳本把握度最低的 2–3 條，不分判定。
2. 依判定分組：`needs-user` → `unsound` → `sound`；組內依把握度由低到高。`sound` 也要列——那是使用者現在擁有的架構。
3. 附帳本的 file:// 連結與 Step 4 的收尾行。
4. 被 implement 呼叫時，把這段交回 implement；它的 handback「替你做了哪些決定」引用這段與帳本連結，不重寫一份。

完成條件：呈現含「先看這幾條」、分組排序、帳本連結與 self-verify 行。
