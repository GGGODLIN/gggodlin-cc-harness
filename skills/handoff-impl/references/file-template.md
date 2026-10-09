# 本檔在契約測試底下；跑法：bash ~/.claude/skills/handoff-impl/scripts/tests/friction-hardening.test.sh && cd ~/.claude/skills/handoff-impl && ~/.local/bin/skill-up run evals/eval.yaml --output-dir ~/Desktop/projects/.claude/trials/skill-up-cli/eval-runs

# Handoff 單骨架（create 模式照此產檔；`<>` 為填空）

存檔路徑：`~/.claude/handoffs/<YYYY-MM-DD>-<slug>.md`（目錄不存在先 `mkdir -p ~/.claude/handoffs/done`）

```markdown
---
status: SPEC_READY
round: 1
round_base: <Git 任務本 round 起點 commit SHA；非 Git 寫 N-A>
spec_level: <method | outcome>
workdir: <implementer 的 cwd 絕對路徑，通常是 worktree>
branch: <branch 名>
pr: <PR URL 或 none>
runtime: <釘死執行環境，如 node v18.18.2 via PATH 前綴；無特殊需求寫 default>
scope: <一句話；Lane 3 寫 plan 路徑 + phase 範圍，如「plans/implementation.md Task 1-6」>
test_evidence: <permanent | transcript | verifier-probe>
implementer: <自由文字，如 ccp-gpt session（GPT-5.6）>
verifier: <自由文字，如 main session（Fable）>
---

# Handoff: <標題>

## 給 implementer 的協議（先讀）

- 只做「Spec」段列的改動，**只准寫「實作回報」段**與 frontmatter `status`，其他段落一字不改
- 所有改動在 frontmatter `workdir` 內做；**不 push、不 rebase、不動 PR**，commit 留本地給 verifier
- 遇到選擇：Spec 有預設照預設；沒寫到的小事自采合理預設並列進回報，**不要停下來問**（本 session 無人回答）
- 遇 dcg 攔截：先換等價非破壞性作法；換不掉就視同停損交單，不等待放行、不繞過 gate
- 多 phase 任務：逐 phase commit、跑 plan 內建的 phase 自檢；自檢過不了且範圍內修不好（同 error 兩次修法後仍現 / diff 越滾越大 / 想繞過驗收）→ **停損交單**，回報寫「做到 phase N、卡在 M、原因 X」，不蓋壞地基、不自改計畫
- Git 任務交單前 commit 本 round 的範圍內改動；目標在 submodule 時 commit 落 submodule，superproject pointer 是否更新照「約束」段，沒寫就留給 verifier／user 決定
- 發現 CRITICAL 安全問題（暴露的 secret / 注入漏洞等，含 Spec 範圍外）→ 視同停損事件：立即交單、寫在回報最上方，不自行修範圍外的檔
- 做完：填「實作回報」段（Round <N> 子節）、frontmatter `status` 改 `IMPL_DONE`
- 禁動檔：本檔 Spec / 驗收段、<其他禁動清單>

## 背景（自包含）

<症狀、根因結論、為什麼要改——寫到 implementer 零對話脈絡也能做對>

## Spec

<既有流程產出的 spec 內容裝進來；workdir 內已有 plan/spec artifact 時寫指標：「讀 <路徑>，執行 <範圍>」>

> outcome 級單若預測內部機制路徑，未對完整 code chain 實證的句子標「未驗證推測」；驗收條件仍以可觀察 outcome 為準。

## 約束

<禁動檔清單、風格要求（引用 repo 規範即可，不重抄）、commit message 約定；目標在 submodule 時寫明 commit 落點與 superproject pointer 是否在 scope>

## ENV_READY（發單者填，implementer 不改）

| 前置 | 驗證者 | 執行環境 | probe 或證據 | 預期 | 實際 | ready |
|---|---|---|---|---|---|---|
| <implementer 開工前必須成立的條件> | <發單者 / implementer> | <實際跑 probe 的 runtime 或控制面> | <實跑命令、讀回或 artifact> | <期望狀態> | <實際讀值> | <yes / no / N-A（理由）> |

> 所有列皆為 `yes` 或附理由的 `N-A` 才能交單；任一 `no` 先處理環境。implementer 會依賴的 credential 或控制面能力必須在 implementer runtime probe；無法預驗時寫 `N-A（implementer 開工第一步驗，失敗即停損）`。發單者環境成功不能代替。純檔案任務仍要證明 workdir 與 runtime 可用。

## 驗收條件（implementer 自跑後貼原樣輸出；verifier 會獨立重跑）

<下列命令已由開單者實跑；只有 implementer 改完才有意義的項目逐項標「未實跑、預期輸出為推測」>

1. <可執行命令> — <預期輸出>
2. ...

## 實作回報（implementer 填，按 round 分節 append）

### Round <N>

> Round 只代表 verifier 退回輪次；同一 Round 內重試用 `#### Attempt <N>` 或時間標題分段，不得另開 Round。

- 改動清單（Git 任務貼 `git diff --name-only <round_base>...HEAD` 與 `git status --short` 原樣輸出，再補 file:line；submodule 內改動從 submodule 內取 round_base／diff／commit 數，另貼 superproject status；非 Git 任務直接列檔案）：
- 驗收命令原樣輸出：
- test_evidence 對應證據（transcript 檔位要貼臨時測試原始碼全文）：
- 沒做的部分（無則明寫「無」）：
- 發現但沒動的問題（無則明寫「無」）：
- 協議摩擦（必填：哪裡卡 / 哪裡模糊 / 建議改什麼；無則明寫「無」）：

## 驗收記錄（verifier 填，按 round 分節 append）

### Round <N> — <ACCEPTED | CHANGES_REQUESTED>（<日期>）

- 逐項重驗表（驗收項 / 預期 / 實際 / 匹配）：
- findings（退回時必填；格式 file:line + 問題一句 + 失敗場景）：
- 協議摩擦（必填；無則明寫「無」）：
```

## Matt TDD propagation graft

只有來源 ticket 已帶核准決策時，才把下列整組內容一起 graft 進 handoff；來源沒有決策時一項都不加，base template 全文不會出現 TDD 專屬 protocol 或 report field。

1. 在「給 implementer 的協議」加入：`- 單內有「TDD decision」才照來源決策施工；required 依 declared seam 走測試優先，waived 保留既有核准理由`
2. 把禁動檔改為包含 `TDD decision`
3. 在 Spec 後加入：

```markdown
<!-- MATT_TDD_PROPAGATION v1 -->
## TDD decision

- Ticket: <ticket artifact path + NN>
- Decision: <required | waived，原樣傳遞>
- Required seam: <來源 ticket 的 seam；不適用則寫 N-A>
- Waiver: <closed reason / ticket-breakdown-user-approved；不適用則寫 N-A>
<!-- /MATT_TDD_PROPAGATION -->
```

4. 在「實作回報」的 `test_evidence` 後加入：`- TDD decision follow-through（required／waived 決策如何被原樣保留）：`

## Bootstrap prompt（create 模式產檔後輸出給 user，implementer 非 CC 時的萬用介面）

```
讀 <handoff 檔絕對路徑>，你是 implementer，照檔內「給 implementer 的協議」與 Spec 執行；完成後填「實作回報」段、status 改 IMPL_DONE。不要停下來問。
```

implementer 是 CC session（共享 ~/.claude/）時，user 只需在該 session 貼 `/handoff-impl` 即可，不用 bootstrap 全文。
