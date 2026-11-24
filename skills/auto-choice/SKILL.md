---
name: auto-choice
description: "Use when 一段實作已完成、交回或合併前，需要列出實作者在規格或 prompt 沒寫到的地方自己做了哪些決定——implement closeout 在 commit 前呼叫；使用者說「列出你替我做的決定」「auto-choice」「這段你自己拍板了什麼」，或臨時修改越改越大、/goal 或 handoff-impl 跑完、subagent 交件回來時也用。Do not use for 正確性 code review（/code-review）、範圍或 YAGNI 審查（review-implement）、實作前的 spec review（review-spec）、修改程式碼或修 bug。"
metadata:
  upstream: dzhng/skills
  upstream-path: skills/engineering/audit-decisions/SKILL.md
  upstream-pinned: 5e69685d935be8fffccfbe0224f9aa57d078e611
---

<!-- 本檔在契約測試底下：python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py；bash ~/.claude/skills/implement/scripts/tests/review-implement-handoff-contract.test.sh（接線）；python3 ~/.claude/commands/tests/test_independent_verification_and_consensus_gates.py -->

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
- `unsound` 寫出該從哪個正確決定重做（必須成立的性質），不寫補丁。在錯的決定上打補丁，等於保留錯的決定。可由數學、時區或協定定義客觀推導，或實作與同專案規格、型別、註解互相矛盾卻靠自寫斷言拿綠燈的項目，一律判 `unsound`，不歸入 `needs-user`——把客觀矛盾包裝成商業偏好附暫定做法，會讓顛倒的結果頂著全綠測試直接出廠。
- **權限、邊界、揭露與副作用紅線（不得判 `sound`）**：凡規格或提示詞未明文授權，卻改變權限（permissions）、信任／驗證邊界（trust/auth boundaries）、資料揭露範圍（data exposure），或引入破壞性／對外副作用（destructive/external side-effects，如刪除資料、寫入外部系統、發送對外請求或通知）的決定，一律不得標為 `sound`。違反既有規格、型別或安全不變量者判 `unsound`；無客觀正解者一律判 `needs-user` 交由人類裁決（並在交回時標 `BLOCKING_CHOICE`，見第 5 節第 4 點）。理由：標成 `sound` 會讓實作者代簽的邊界擴張沉在呈現末尾當成既成架構放行，跳過人工把關。
- `needs-user` 只留給品味、產品方向、外部成本或上述四類未明文邊界變更這類沒有客觀正解、真的只有使用者能決定的事；每條附一個可撤回的暫定做法和撤回方式，無人值守的流程照暫定做法繼續（但會改變對外計算結果、權限、信任／驗證邊界、資料揭露範圍或破壞性／對外副作用者仍須標阻斷，見第 5 節第 4 點）。

- **三家族共識閘（Step 1 掃出 ≥1 條實質決定時自動執行；掃出 `0 條` 實質決定時直接跳過）**：單一模型自評容易放過隱性工程缺陷或應問人邊界，因此將本次全部待判決定整理為**去除判定與把握度**的盲測決策卡，以**單一批次**平行送交三個**不同家族**模型投票（每次收尾 1 批共 3 席，不逐條拆送以避開 429）。收件後從執行轉錄核對各席**實際服務模型**確屬不同家族（如 Magpie 下的 Gemini、GPT、Claude），嚴禁同家族別名冒充，且全程不計算、不儲存、不比對任何**驗證用途 hash**。合議與保守降級規則如下：
  - **3/3 不同家族全數回 `proceed`**：通過共識閘（可維持 `sound`，並於既有帳本判定理由欄附記三家族共識摘要）；但上方四類**紅線永遠優先於共識閘**，命中紅線者即使三家皆回 `proceed` 仍不得標為 `sound`。
  - **任一家回 `ask-user` 或 `reject`**：攔下不得自動放行，依理由升格為 `needs-user` 或 `unsound`（維持既有 `BLOCKING_CHOICE` 語意），並將喊停家族與理由附記於既有帳本的判定理由欄（不另建第二份帳本）。
  - **缺席 1 家（429／逾時／格式錯誤）**：僅在剩餘 2 個不同家族均回 `proceed` 時放行，並於帳本理由欄與呈現明標「**共識閘 2/3**（缺席：<模型與原因>）」；任一家異議即依上條升格為 `needs-user` 或 `unsound`（維持既有 `BLOCKING_CHOICE` 語意與呈現／阻斷規則），並記明喊停家族與理由。
  - **有效不同家族 ≤1 家（含原生單模型環境）或全掛**：退回現有單模型判定，並於帳本與呈現明寫「**三家族共識閘未構成**（原因）」，不卡死收尾。

完成條件：每條都有判定與把握度；掃出 ≥1 條實質決定時已完成三家族共識閘（含實際服務模型跨家族核對、異議攔截或 2/3／≤1 家降級揭露）；涉及權限、信任／驗證邊界、資料揭露範圍或破壞性／對外副作用的未明文決定皆未標為 `sound`；每條 `unsound` 有正確決定；每條 `needs-user` 有暫定做法與撤回方式。

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
- prompt 預設內嵌本次帳本段全文與下方 template（`{ledger}` 換成全文）；帳本太長不適合全文內嵌時，改走下方 `FILE_SNAPSHOT` 檔案模式

本回合這支 skill 只有一次 auditor 額度：不論結果都不重派，也不用 SendMessage 續問同一個 auditor。

```
你是 adversarial 合規審查員，檢查一份「實作決定帳本」是否遵守規矩。偏置是找違規：無法從帳本文本確認有遵守就判 FAIL。

帳本原文（若上方已宣告 AUDIT_INPUT_MODE: FILE_SNAPSHOT，請依 SNAPSHOT_PATH 與 SNAPSHOT_TOTAL_LINES 分段 Read 完整快照檔並於首行輸出 READ_RANGE）：
{ledger}

逐條檢查（每條回 PASS / FAIL + 一句證據引述）：

R1【八類掃描】帳本是否對八類（資料形狀與格式／存放位置與命名／API 契約與錯誤行為／新增相依套件／並行與效能取捨／範圍解讀／測試設定改動／會被照抄的模式）逐一寫了「有」或「無」？缺任一類 = FAIL。

R2【判定、把握度與邊界紅線】每條是否都有判定（sound／unsound／needs-user）與把握度（低／中／高）？凡規格未明文授權卻改變權限、信任／驗證邊界、資料揭露範圍，或引入破壞性／對外副作用的決定，是否皆未標為 sound（須判 unsound 或 needs-user）？將此類決定標為 sound = FAIL。

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

帳本太長、不全文內嵌時，改走檔案模式：先把本次帳本段合成一份快照檔並設成唯讀，派出後內容就不會再變（例如 `cp <帳本檔> <scratchpad>/auto-choice-audit-snapshot.md && chmod a-w <scratchpad>/auto-choice-audit-snapshot.md && wc -l <scratchpad>/auto-choice-audit-snapshot.md`），再把這三行放在 prompt 最前面，rubric 照樣全文內嵌（省略 `{ledger}` 原文段）：

```
AUDIT_INPUT_MODE: FILE_SNAPSHOT
SNAPSHOT_PATH: <唯一一個快照檔的絕對路徑>
SNAPSHOT_TOTAL_LINES: <快照檔總行數>
```

稽查員與前置 gate 只認單一既存非 symlink 一般檔絕對路徑與正整數行數：列了多個檔、給相對路徑或缺任何一行，gate 會在消耗額度前攔下（或稽查員一行都不讀、五條全判 FAIL）。

收尾四態（寫在呈現的最後一行）：

- 全 PASS → `🔎 self-verify: COMPLIANT (5/5)`
- 有 FAIL 且已修帳本 → `🔎 self-verify: FIXED_AFTER_AUDIT — R#（…）`，同句寫「未經第二次獨立稽查」
- 有 FAIL 且修不掉 → `🔎 self-verify: FAILED — R#（缺口）`，撐不住的條目刪除或降級成「未完成：缺 <欄位>」，不原樣交付
- auditor timeout、空輸出、格式錯誤 → `🔎 self-verify: SKIPPED (agent error)`
- 稽查員沒讀到交付物（第一行是 `READ_RANGE: 未讀`，或逐條寫明沒拿到材料）→ `🔎 self-verify: SKIPPED (稽查員沒讀到交付物)`，不標 `FAILED`：它沒看到內容，判不出帳本對錯。同一回合不重派（hook 會擋）；交付時寫明要上一層（派你的 main）或下一回合照上方檔案模式合成單一快照、重派一次，那一次照四態落定，之後不再重派

完成條件：本回合已出現一次 `skill-verify:auto-choice` 的 Agent dispatch，且收尾落在四態之一。完成後接 Step 5。

## 5. 呈現

1. 開頭一行「先看這幾條」：整本帳本把握度最低的 2–3 條，不分判定。
2. 依判定分組：`needs-user` → `unsound` → `sound`；組內依把握度由低到高。`sound` 也要列——那是使用者現在擁有的架構。
3. 附帳本的 file:// 連結與 Step 4 的收尾行。
4. 被 implement 呼叫時，把這段交回 implement；它的 handback「替你做了哪些決定」引用這段與帳本連結，不重寫一份。若本次帳本含有未修掉的 `unsound`，或會改變對外計算結果、權限、信任／驗證邊界、資料揭露範圍或破壞性／對外副作用的 `needs-user`，在交回段落開頭標明 `BLOCKING_CHOICE` 交由 main 停下裁決，不在無人值守下直接當成可推上線。

完成條件：呈現含「先看這幾條」、分組排序、帳本連結與 self-verify 行。
