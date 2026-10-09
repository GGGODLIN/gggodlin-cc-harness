---
description: Generate ready-to-paste /goal condition for autonomous CC execution; output 依任務複雜度分流（simple 走 chat inline、complex 落 ./PLAN-goal.md）. Use when planning a self-contained task to hand off to /goal. 一般跨多輪實作規劃先走 local chain `brainstorm` → `to-spec` → `to-tickets` → `implement`.
---

# Goal Generator

User-provided task description:

$ARGUMENTS

---

## What this command does

Produce a complete plan for handing off to `/goal` (CC built-in autonomous loop, v2.1.139+, evaluates Stop condition every turn via small fast model; condition must be verifiable from transcript only — evaluator does not execute tools).

**Output mode 依任務複雜度分流**：

- **Simple path**：chat inline 全部（plan / pre-flight / condition / risk）
- **Complex path**：寫 `./PLAN-goal.md`（plan / hand-off / risk 細節）+ chat 回 pre-flight + condition + 一行摘要

兩條路徑使用者最終貼進 `/goal` 的東西都是 chat 裡的 condition code block；差別在 plan/risk/hand-off 寫進 chat 還是 PLAN-goal.md。

---

## Step 1 — Handle empty input

If `$ARGUMENTS` is empty, ask the user:

1. 任務描述（要做什麼，1-2 句）
2. 已有 setup 或約束（要保留什麼、不要動什麼）
3. 期望 turn cap（**強制設**，不要選「不設 cap」—— 無 cap 會讓 Stop hook 每 turn 阻擋浪費 turn budget）：
   - 25 turns（簡單 setup / config 任務）
   - **35 turns（default，dev / build / multi-phase 任務，留 retry buffer）**
   - 50 turns（極複雜 / 跨工具整合）

Wait for answer before proceeding.

---

## Step 2 — Mandatory fact-check

**Per `~/.claude/rules/common/fact-check.md` + `feedback_session_topic_shift_refetch.md`:**

Before generating the condition or plan, invoke `/research-before-answer` skill if the task mentions any of:

- Specific tool / library / SDK / framework name + version
- Model name + size + variant
- Platform / OS version requirement
- Recent feature / API / release

Use chrome nav + WebSearch parallel per ticket model. **Don't accept training data on version-specific facts** — recent miss case: training data 推 Qwen3-4B 給已在跑 Qwen3.6 的使用者，差兩世代。

Surface fact-check results in the response so the generated plan reflects current ground truth, not stale training data.

**In-execution re-fetch trigger**: 生成 condition 內加註「執行中遇到 stale / 矛盾 fact（如 API 改名、flag 必加、cache 路徑變）必須重新 invoke `/research-before-answer`，不要硬 retry 撞牆」。

**完成本步後必進 Step 2.5（dry-run probes）——確認環境實際能跑、無 human blocker，才到 Step 3。不要從 Step 2 直接跳 Step 3。**

---

## Step 2.5 — Dry-run prerequisite probes（**關鍵步驟，2026-05-13 加**）

Plan 階段做的 fact-check 只查文件 / API，**查不出「user 環境實際能不能跑」的 blocker**。必須額外跑 cheap probes 探實際狀態，把 human-blocking prerequisites 提前列出。

### 常見 probe pattern

| 任務類型 | Probe 命令 | 抓的 blocker |
|---|---|---|
| Build (Xcode/Swift) | `xcodebuild -version` + 跑 minimal `cmake -B /tmp/t -G Xcode .` 試載 plugin | License 沒 accept / First Launch 沒跑 / SDK 缺 |
| Build (rust/go/node) | `cargo --version` / `go version` / `node --version` | toolchain 版本不滿足 |
| 下載大 model / dataset | `test -s ~/.cache/huggingface/token && echo "HF token present"` + `ls -la <model-path>/*.safetensors` | HF token 沒設 / 已 cached 或要下載 |
| Cloud API | `gh auth status` / `aws sts get-caller-identity` / `gcloud auth list` | 登入過期 / 帳號未 link |
| Existing service | `curl --max-time 2 <endpoint>` + `lsof -i:<port>` | Port 衝突 / 舊 daemon 還在 |
| Git push | `git remote -v` + `gh auth status` | SSH key 沒設 / token 過期 |
| 任務會 git commit | `git status --porcelain` | 工作區有**非本任務**的未 commit 改動 → 自主 per-task commit 會把無關改動吸進 commit、破壞 clean-rollback；列 ⚠️ 請 user 先 stash / commit 掉 |
| sudo 需求 | grep task description「sudo / install / system」字 | 必須 user 自己跑 |
| GUI / Mic / Camera 權限 | `tccutil get Microphone <bundle>` | 跑前要先給 permission |

### Output format

```markdown
## Pre-flight Checklist

✅ <prereq>: already satisfied / probe 通過
⚠️ <prereq>: **USER ACTION REQUIRED** — <具體動作>
   - 為什麼 Claude 做不到：<sudo / GUI / interactive auth>
   - 確認命令：<跑完這個應該變 ✅>

請完成所有 ⚠️ 項目後再貼下方 condition 進 /goal。
```

如果**所有**都 ✅ 直接告訴 user 可以開跑。

### Anti-pattern

- ❌ Plan 階段只查文件版本不 probe → 跑進 /goal 中段才發現 blocker → 浪費 retry
- ❌ Probe 命令本身需要 sudo / GUI → 那條 probe 直接列 ⚠️ 不要試
- ❌ Pre-flight 跟 fact-check 混為一談 — 兩個 step 分開：fact-check 是 docs/版本、probe 是實際環境

---

## Step 3 — Identify human-required steps

Split task steps into:

| Type | Examples | Where it goes |
|---|---|---|
| Claude-autonomous | bash / file edit / curl / git clone / build / config write / memory update | Plan + condition evidence |
| Human-required (pre) | sudo / GUI install / 互動式 auth / sensitive credential 設定 / 系統升級 | Pre-flight checklist（chat / PLAN-goal.md，跑 goal 前） |
| Human-required (post) | macOS GUI / mic / physical action / subjective judgment | Hand-off list（PLAN-goal.md，跑完 goal 後） |

**「互動式 auth」歸類約束**（per `feedback_dont_overapply_interactive_cli_rule.md`）：把互動式 CLI 步驟歸 Human-required 前先查三點——(a) 有無 `config set` / 非互動 `--flag` / `--stdin` / `--file` 變體 (b) 能不能 inspect schema 後直接寫 config 檔（key 從鎖檔帶入、不 echo、改前備份）(c) 是不是 stdin 餵不了的 auth / OAuth / 密碼 prompt。(a) 或 (b) 可行 → 歸 Claude-autonomous；三點查完只剩純 (c) 才歸 human blocker。

Human-required steps **cannot** be condition evidence — the evaluator can't see GUI state or hear mic input.

---

## Step 4 — Complexity classification

判定後續 output 走哪條路徑。**任一觸發就走 complex path**：

- Plan steps > 5
- Pre-flight 有 ≥ 1 個 ⚠️
- Condition 預估 > 30 行
- 有 post-goal hand-off 項目（GUI / mic / 主觀判斷）

全部不觸發 → simple path。

---

## Step 5 — Generate output

### Simple path: chat inline

回給 user 4 個 chat section（無 hand-off — 簡單任務不該有 post-goal manual step）：

1. **Plan preview** — Numbered list ≤ 5 items；每 item: Action + Verification (machine-checkable)
2. **Pre-flight** — 全 ✅ 寫一句「all prereqs satisfied」；有 ⚠️ 不會走到 simple path
3. **Ready-to-paste condition** — Code block，見下方共用 condition writing rules
4. **Risk + fallback** — Mini table 2-4 rows inline

Condition 定稿後過 Step 5.5 red-team，再 end with simple path final delivery（見下）。

---

### Complex path: PLAN-goal.md + chat condensed

#### 5b-1: Check `./PLAN-goal.md` not exists

固定命名 `./PLAN-goal.md` 在 cwd。

- 不存在 → 寫入（5b-2）
- 存在 → **abort + 提示 user**：「`./PLAN-goal.md` 已存在，請先 rename / 移除既有檔再 retry，避免 silent overwrite 上次 plan」

不自動 rename / append（保留 user explicit control）。

#### 5b-2: Write `./PLAN-goal.md`

Structure:

```markdown
# Goal Plan: <task short summary>

Generated: <YYYY-MM-DD HH:MM>
Task: <user-provided $ARGUMENTS or paraphrased>
Turn budget: [N] (hard cap [M])

## Plan
<numbered phase list, 每 item 含 Action + Verification (machine-checkable)>

## Pre-flight checklist
✅ <satisfied prereqs>
⚠️ <user-action-required prereqs，含具體命令 / GUI 路徑>

## Hand-off (post-goal manual steps)
<numbered list，每 item: action + 為什麼 Claude 做不到 (GUI / mic / decision)>
含 background task lifecycle: long-lived service (如 `rapid-mlx serve`) 怎麼 stop / restart / 開機自啟

## Risk + fallback
| Risk | Fallback |
|---|---|
| ... | ... |

## Goal condition (reference copy)
<paste of condition for cross-reference>
```

#### 5b-3: Chat output (3 sections only)

1. **Pre-flight checklist** — 完整 ✅ + ⚠️ 列出（user 在 chat 馬上能做，不用切檔）
2. **Ready-to-paste condition** — Code block；第一句要 reference `./PLAN-goal.md` Plan section
3. **One-line summary** — 「Plan / Risk / Hand-off 詳見 `./PLAN-goal.md`；跑完 goal 後別忘該檔 `## Hand-off` section」

Condition 定稿後過 Step 5.5 red-team，再 end with complex path final delivery（見下）。

---

### Condition writing rules (both paths)

One code block, ready for direct paste into `/goal <condition>`. Follow CC docs' "effective condition" rules:

```
完成 [任務簡述] 至 transcript 包含全部以下證據後達成：

[Complex path 第一句加: 先讀 ./PLAN-goal.md 的 ## Plan section 了解 phase 結構。]

1. [Evidence 1]：[stated check — how to prove via transcript]
2. [Evidence 2]：...
...

不算達成（DOES NOT COUNT — 以下近似解不滿足任何 evidence）:
- [refusal-list 枚舉：如「code 寫了但測試沒實跑」「測試綠但斷言被改弱 / 被 skip」「宣稱完成但無 transcript 證據」]
- ...

Constraints:
- [User-specified constraints from $ARGUMENTS]
- 不要 git commit / push 任何東西
- 不要動 user 既有 setup 的主要組件（保留可恢復）

Retry / unblock policy:
- 同 root cause 最多 retry 2 次（不是 per phase 2 次）；發現新 root cause 不算 retry
- 同 root cause retry 2 次仍 fail → emit 「⏸ PENDING_USER_ACTION: <具體動作>」到 transcript 後等 user 完成，不算 phase failure、不消耗 budget
- 遇到 stale fact / 矛盾 fact 重新 invoke /research-before-answer，不要硬撞

External unblock 狀態：
- Phase 卡 sudo / GUI / 互動式 auth / sensitive credential / 系統升級 → transcript surface「⏸ PENDING_USER_ACTION: <動作> via <command/path>」，視為 pending、待 user 完成後自然 re-trigger
- 不算 phase failure

Sensitive credential 處理：
- 任何 API key / token / password / OAuth secret 走 hand-off「請在 terminal 跑 `<cli-login>` 自設」，不要請 user 貼進 chat
- 若 user 主動貼，提醒 transcript 會留紀錄 + 建議事後 revoke 重發

GUI / Mic / 人主觀：
- 不嘗試 GUI automation
- 直接記錄到 hand-off 後繼續或停下

or stop after [N] turns
```

Writing rules:
- **One measurable end state per evidence**: test result / exit code / file count / endpoint response —— 一律是 artifact 上可檢查的 predicate，不是 agent 自評（「我認為完成了」「confidence high」不是 evidence）
- **DOES-NOT-COUNT 用 refusal-list 法寫**：想像一個菜鳥協作者拿著各種「貌似完成的部分成果」回來，把每一種你會退回的逐條寫下——那份退回清單逐字就是 DOES-NOT-COUNT 區塊。沒有這區塊的 condition 等於邀請近似解過關
- **Persistence 必配等強驗證 gate**：condition / plan 裡每出現一句「堅持 / 不放棄 / 直到完成」，必須在同處配一個「怎麼驗你真的完成」的 gate；只加 persistence 不加 gate 會養出假裝完成（persistence-hacking，METR 實證）
- **Stated check per evidence**: `curl ...` 回傳 X / `ls -la X` 存在 / cat 出特定內容 / specific transcript line
- **Complex path 額外**: evidence 仍須 self-contained transcript-printable，**不能寫「PLAN-goal.md 所有 phase 完成」**（evaluator 看不到 PLAN.md，只看 transcript），要抽具體 stop evidence 寫進 condition
- **Constraints that matter**: 列出什麼不能變
- **Bound clause**: `or stop after N turns`（不要省略）
- **Max 4000 chars** (CC /goal hard limit) — complex path reference PLAN.md 而非 inline 整 plan 才不撞牆。**寫完 condition code block 必須 `printf '%s' "<condition>" | wc -c` 確認 < 3800（留 200 buffer 給 `/goal ` wrap 跟引號 escape）**。超就精簡，常見手段：(a) 同類別多條 evidence 合一（如 UI 紀律 7 條展開 → 「ui-design.md §8 7 條紀律全照（見 evidence X 完整列表）」）(b) Retry policy 簡寫，細節進 PLAN.md (c) Constraints 不重複寫（「不上 shadcn」這類已在 task description 不必再列）。**先給 user 字數超限版會浪費一個來回**——self-validate 是寫條件前最後一步。
- **Internal consistency lint**：對 condition 自掃一遍 — evidence 跟 system prompt / config 內容有沒有衝突？（例：evidence 要 output 含「冒號」vs prompt rule 寫「英文程式專名原樣保留」，「colon」屬英文 → 矛盾 → 改 prompt 加例外 或 改 evidence 措辭）

Condition 寫完（含 wc -c self-validate）→ 必進 Step 5.5 red-team，不要直接跳 Final delivery。

---

## Step 5.5 — Launch 前 red-team（condition 定稿後、交付前）

派一個 **fresh 對抗式 subagent**（`routed-judge`，fresh context 才有攻擊視角），prompt 只給：condition 全文（complex path 加 PLAN-goal.md 全文），問一題：

> 「你是要鑽漏洞的執行 agent。列出所有『滿足這份 condition 字面、但沒有真正解決任務』的做法——包括：改弱驗證、繞過 evidence、利用措辭歧義、DOES-NOT-COUNT 沒堵到的近似解。每條附你會怎麼做。」

回來的每個洞就地補進 condition（多半是往 DOES-NOT-COUNT 或 evidence stated-check 加一條）；補完不重跑 red-team（一輪即可，無限迭代是過度工程）。完成判準：red-team 產出的每一條都有對應處置（補進 condition / 判不成立附一句理由）。

完成後接 Final delivery。

---

### Final delivery

**Hedged ≠ approved**（兩條路徑共用）：交付 plan / condition 後，user 回「看起來合理」「應該可以吧」「I guess」這類 hedged 回應 = 還沒 approve——這是不確定訊號，不是同意。指出 hedge 所在、問清那一點，等明確的 yes（或修正）再讓 user 貼 condition。無人值守執行的授權必須是顯式的。

#### Simple path
End with:

> 1) 完成上面 pre-flight 任何 ⚠️ 項（如有）
> 2) Review condition
> 3) Paste 進 `/goal <condition>` start。Turn budget [N]，hard cap [M]。

#### Complex path
End with:

> 1) 完成上面 Pre-flight 所有 ⚠️ 項
> 2) Skim `./PLAN-goal.md`（特別是 `## Hand-off` 跑完要做的事）
> 3) Paste condition 進 `/goal <condition>` start。Turn budget [N]，hard cap [M]。

---

## Anti-patterns to avoid

- ❌ 沒 turn cap（甚至「不設 cap」）→ Stop hook 每 turn 阻擋燒 turn budget
- ❌ Constraint 漏「不要 commit」→ Claude 可能 git push 你不想要的東西
- ❌ Plan section 跟 condition section 不一致（plan 寫 10 步 condition 只 cover 3 步）
- ❌ Retry policy 寫「每 phase 2 次」太死板：dev 任務常需 5-10 次 unblock；改寫「同 root cause 2 次後 escalate hand-off」
- ❌ Sensitive credential 在 chat 接收 → transcript 留紀錄 + session backup 同步到 GitHub repo
- ❌ Pre-flight 跟 post-goal hand-off 混為一談（前者 user 跑 goal 前做、後者跑完做）
- ❌ **Simple path 硬塞 hand-off / > 5 phases**（如果真有 hand-off 或多 phase 該走 complex path）
- ❌ **複雜任務硬塞 simple path**（condition 超 30 行被 4000 char 限切，或 hand-off 漏列）

---

## Reference

- CC `/goal` 官方 docs: https://code.claude.com/docs/en/goal.md
- `~/.claude/skills/research-before-answer/SKILL.md` — fact-check 觸發條件
- `~/.claude/rules/common/fact-check.md` — 13 條 fact-check 紀律正本
- `feedback_session_topic_shift_refetch.md` — 為什麼強制 fact-check
- `feedback_goal_gen_scope_implementation_phase.md` — goal-gen scope = implement-phase bridge / PLAN.md 引用模式 origin
- `reference_cc_goal_command.md` — `/goal` 機制細節（Stop hook + Haiku evaluator）
- `reference_xcode_upgrade_first_launch_2026_05_13.md` — Step 2.5 dry-run probe 經典案例（升 Xcode 後 plugin chain 鬆動誤導成 CMake error）
- `reference_cc_macos_voice_input_landscape_2026_05_13.md` — 第一次 goal-gen real run 完整 5 phase / 7 retry trace
- 長時自主 brief 寫法外部參照：https://github.com/muratcankoylan/Agent-Skills-for-Context-Engineering/blob/main/skills/long-horizon-prompting/references/task-brief-template.md（DOES-NOT-COUNT / persistence-gate / red-team 三判準的來源模板，2026-07-12 absorb）
