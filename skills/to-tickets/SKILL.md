---
name: to-tickets
description: "Break a plan, spec, or the current conversation into tracer-bullet tickets, each declaring its blocking edges. Lands in the repo's convention: sections in the openspec change's tasks.md if openspec/ exists, else one file per ticket under .scratch/{feature-slug}/issues/. Use when a spec or plan has converged and it is time to break it into executable units — 拆 ticket / 排 task / to-tickets, or the local pipeline was chosen at kickoff. Do not use for: single-step fixes too small to slice, or editing an existing ticket set (edit it directly)."
upstream: mattpocock/skills
upstream-path: skills/engineering/to-tickets/SKILL.md
upstream-pinned: 49dd158
---

<!-- 本檔在契約測試底下：node ~/.claude/skills/implement/scripts/tests/testing-mode-contract.test.mjs -->

# To Tickets

Break a plan, spec, or conversation into a set of **tickets** — tracer-bullet vertical slices, each declaring the tickets that **block** it.

## Process

### 1. Gather context

Work from whatever is already in the conversation context. If the user passes a reference (a spec path, an issue number or URL) as an argument, fetch it and read its full body and comments. Done when: the source spec/plan is fully in context.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the current state of the code. Ticket titles and descriptions should use the project's domain glossary vocabulary, and respect ADRs in the area you're touching.

Look for opportunities to prefactor the code to make the implementation easier. "Make the change easy, then make the easy change."

### 3. Draft vertical slices

Break the work into **tracer bullet** tickets.

<vertical-slice-rules>

- Each slice cuts a narrow but COMPLETE path through every layer (schema, API, UI, tests) — vertical, NOT a horizontal slice of one layer
- A completed slice is demoable or verifiable on its own
- Each slice is sized to fit in a single fresh context window
- Any prefactoring should be done first

</vertical-slice-rules>

Give each ticket its **blocking edges** — the other tickets that must complete before it can start. A ticket with no blockers can start immediately.

**Classify every verification-shaped acceptance item, because the class decides where it goes.** An item is verification-shaped when its output is an answer or a piece of evidence rather than code:

- **Gate** — a wrong answer makes downstream work wasted (does the platform even support this? what does production actually have?). A gate does not belong inside the ticket it informs: pull it into its own ticket at the front of the dependency graph, blocking everything that depends on the answer. Labelling a gate without moving it forward buys nothing.
- **Confirmation** — the answer is expected to be "yes" and you need the evidence. These batch into one pass after the code is complete. Running them ticket-by-ticket serializes the chain to prove things you already believe.
- **Contract** — produces samples or measurements that a later artifact quotes (a handoff doc, an acceptance spec). Batch with the confirmations, but "after the code" must still be *before* the ticket that quotes them — draw that blocking edge.

Done when: every verification-shaped acceptance item carries one of the three labels, and every gate sits in its own ticket that blocks whatever it informs.

**A gate with two possible answers can produce a conditional ticket.** When the answer decides whether a whole body of work exists at all (upgrade needed or not, migration needed or not), write that work as a ticket now, marked conditional on the gate's outcome, blocked by the gate and blocking whatever it would gate. The gate's result then either activates it or deletes it — no mid-flight replanning, and no work spent on a branch that turned out not to exist.

**Propose best-of-N only where tests can settle the comparison.** N parallel implementations cost N times the tokens, and the payoff comes from the judge: to separate near-identical candidates it has to verify them, which produces the tests neither candidate wrote. Where the output can't be pinned by tests (wording, layout, pure style), the judge has nothing to verify and you pay N times for a small preference. Mark a ticket best-of-N only with the user's agreement, and when marking it, require the judge to verify hands-on rather than read diffs.

**Wide refactors are the exception to vertical slicing.** A **wide refactor** is one mechanical change — rename a column, retype a shared symbol — whose **blast radius** fans across the whole codebase, so a single edit breaks thousands of call sites at once and no vertical slice can land green. Don't force it into a tracer bullet; sequence it as **expand–contract**. First expand: add the new form beside the old so nothing breaks. Then migrate the call sites over in batches sized by blast radius (per package, per directory), each batch its own ticket blocked by the expand, keeping CI green batch to batch because the old form still exists. Finally contract: delete the old form once no caller remains, in a ticket blocked by every migrate batch. When even the batches can't stay green alone, keep the sequence but let them share an integration branch that all block a final integrate-and-verify ticket — green is promised only there.

**核票前確認每票測試義務，不選執行順序。** Every ticket carries `Tests: required` or `Tests: waived`; silence is invalid. Required 票寫明公開測試邊界與已確認需維持的回歸行為，不要求此時決定何時寫測試。Waived tickets use one closed reason code — `docs-only`, `generated-only`, `no-stable-seam`, or `non-executable-artifact`. Show every waiver in the numbered breakdown review. Write `ticket-breakdown-user-approved` only after the user approves that one-round breakdown; implement controllers and workers preserve the test obligation and may not add or change a waiver later. 原 TDD／回歸收尾只由 implement 開頭選本批一次，這裡不另問、不預填模式、不把回歸收尾列成 waived。Then continue to the acceptance-readiness pass below.

**Run a lightweight acceptance-readiness pass before step 4.** For every important acceptance criterion, map it directly to `Story <N>` or `Requirement: <title>`, state an observable signal, and cover it in the ticket's Validation method and Evidence required. Unhappy paths come from the failure-mode probe table, not from imagination: if the ticket has any async action, backend data, third party, or a rule that also lives elsewhere, read `~/.claude/references/failure-mode-taxonomy.md` before writing its negative criteria, walk the classes that apply (F1 timing, F2 data shape, F3 third-party contract, F4 external failure, F5 multi-entry drift, F6 boundaries), and write each hit as its own observable criterion tagged `— Failure: Fn`; skip classes the ticket has no surface for. Why: a generic "add an unhappy path" produced single-action failures (API error → Alert) on 33 real tickets while every post-ship fix was a state transition or a real-data shape nobody had listed. Add a must-not-change criterion when the slice risks existing behavior. If the ticket's Needs cannot support a feasible validation method, mark it blocked rather than `ready-for-agent`. Keep trivial tickets to one source-mapped criterion plus concise validation/evidence; omit inapplicable negative or non-regression bullets instead of adding ceremony. Done when: every important criterion is traceable and observable, every applicable probe class has either a `— Failure: Fn` criterion or no surface on this ticket, applicable non-regression behavior is present, and every ready ticket has feasible validation and evidence.

### 4. Quiz the user

Present the proposed breakdown as a numbered list. For each ticket, show:

- **Title**: short descriptive name
- **Blocked by**: which other tickets (if any) must complete first
- **What it delivers**: the end-to-end behaviour this ticket makes work
- **Tests**: required 與公開測試邊界／回歸保護範圍，或 waived 與封閉理由；不是本批執行模式
- **Validation**: the method/evidence and source mapping for important criteria, including any blocked validation

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the blocking edges correct — does each ticket only depend on tickets that genuinely gate it?
- Should any tickets be merged or split further?

Iterate until the user approves the breakdown. Done when: the user has approved. Then continue to step 5.

### 5. Land the tickets

**Repo has an `openspec/` directory** → append the tickets to the change's `openspec/changes/<change-name>/tasks.md`, one `## <NN> — <title>` section per ticket in dependency order (blockers first), each section using the per-ticket template fields below. End the file with a `## Verification Log` section (empty at first) — implementation-time Minor findings land there, not in any tool-owned workspace. Done when: every approved ticket has a section and the Verification Log section exists.

**No `openspec/` directory** → write one file per ticket under `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01` in dependency order. Each file's "Blocked by" lists the numbers/titles it depends on. Use the per-ticket template — one ticket per file, never a single combined file. Done when: every approved ticket has a file.

Before handing off, check ticket fields once with the same parser /implement will use: `MATT_TDD_ROOT=$(mktemp -d) node ~/.claude/skills/implement/scripts/tdd-policy.mjs init --session check --run check --tickets <canonical-ticket-set>`；scratch 傳完整 `.scratch/<feature-slug>/issues/`，OpenSpec 傳該 change 的 `tasks.md`。這份隔離暫存 manifest 只檢查欄位，不是正式 run、不替使用者選模式；省略模式旗標的舊相容值不可當成開工批准。A non-zero exit names the ticket and field to fix (`Test waiver:` with a closed reason and `Test waiver approved:`). 舊票 `TDD:`／`TDD seam:`／`TDD waiver:`／`TDD waiver approved:` 一族仍接受；單票不能混用兩族。Done when: the command prints `ticket_count` equal to the approved number of tickets.

Ticket sections/files are **ordered** blockers-first; **execution** follows the frontier — any ticket whose blockers are all done, which for a purely linear chain means top to bottom — and execution is /implement's job. Hand off there.

Do NOT close or modify any parent issue or Asana card — cards stay card-level SSOT; tickets are plan-level artifacts.

<local-ticket-template>

# {{NN}} — {{Ticket title}}

**What to build:** the end-to-end behaviour this ticket makes work, from the user's perspective — not a layer-by-layer implementation list.

**Blocked by:** the numbers/titles of the tickets that gate this one, or "None — can start immediately".

**Status:** `ready-for-agent` when every important criterion has a feasible validation method; otherwise `blocked — validation method unresolved`

**Needs:** whatever an acceptance item requires before it can be checked at all — real store or account, VPN, running REPL or dev server, browser session, a teammate's answer — or "None — a worker can check every item unaided". Written per ticket so /implement sees the setup cost before dispatching into it, rather than a worker discovering it mid-flight.

**Validation method:** the smallest feasible check that covers every important acceptance criterion — test, command, inspection, or manual observation

**Evidence required:** the exact observable output, state, artifact, or receipt that proves those criteria passed

**Tests:** `required` or `waived`

Required tickets:

**Test seam:** the public interface where approved behaviour is observed

**Regression scope:** 已確認需維持的行為與本次不可改壞的既有行為；引用下方驗收來源，不保存任意實作細節

Waived tickets:

**Test waiver:** `docs-only`, `generated-only`, `no-stable-seam`, or `non-executable-artifact`

**Test waiver approved:** `ticket-breakdown-user-approved`

- [ ] {{Observable acceptance criterion 1}} — Source: {{Story N | Requirement: title}}
- [ ] {{Observable acceptance criterion 2}} — Source: {{Story N | Requirement: title}}

</local-ticket-template>

In either form, avoid specific file paths or code snippets — they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it and note briefly that it came from a prototype. Trim to the decision-rich parts — not a working demo, just the important bits.

## 踩過的坑

- 2026-07-28 fork 時刪掉上游的 real-tracker publish 分支（GitHub/Linear issue 發布）：本 stack 的 Asana 維持卡層 SSOT、plan 層 ticket 一律 openspec tasks.md 或 .scratch 本地檔。要恢復看 upstream 原文。
- 2026-07-28 Self-Verify 段評估不加：step 4 Quiz the user 本身就是人審 checkpoint、產出再過一層 LLM rubric 是重複。
- 2026-08-12 第二輪三張實作票都沒有顯式 TDD 分類，0/3 接線成功；分類必須前移到使用者核准 ticket breakdown 的時刻，否則 implementer 能把沉默直接解讀成跳過。第一版又把分類膨脹成命令、輸出、路徑與收據引擎，獨立 review 判定過度工程且擴大執行面；現只保留 required／waived 決策與 waiver 核准。
