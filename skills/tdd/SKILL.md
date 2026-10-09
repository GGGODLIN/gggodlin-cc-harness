---
name: tdd
description: "Use when the current implement batch explicitly selected tdd and has required tests, or the user explicitly asks for test-first / red-green / 先寫測試 outside a batch selected regression-closeout. Do not use for regression-closeout batches, including their late regression tests; use their selected recipe and standalone test-quality references instead. Do not use for test-suite auditing (mutation-testing) or trivial code / prose with approved test waivers."
upstream: mattpocock/skills
upstream-path: skills/engineering/tdd/SKILL.md
upstream-pinned: 4588b32ecab9ecc9fc8cc6b6c5e7d675b6004b0d
---

<!-- 本檔在契約測試底下：node ~/.claude/skills/implement/scripts/tests/testing-mode-contract.test.mjs -->

# Test-Driven Development

適用條件與 description 相同：本批 implement 已明確選 `tdd` 且有 required 測試，或使用者在沒有選回歸收尾的批次之外明確要求 test-first／red-green／先寫測試。保留 model-callable 與 implement → Skill(tdd) 接線，也保留使用者手動入口；這是選用條件，不是 runtime 安全鎖。

如果本批選的是 `regression-closeout`，包括收尾補測試，就回到所選配方；不要套用以下 TDD 迴圈。測試品質檔 [tests.md](/skills/tdd/tests.md) 與 [mocking.md](/skills/tdd/mocking.md) 可以獨立讀，不因此載入本 skill。已載入的正文不能卸載，也不聲稱這段排除能清空 context。

TDD is the red → green loop. This skill is the reference that makes that loop produce tests worth keeping: what a good test is, where tests go, the anti-patterns, and the rules of the loop. Every section applies on every cycle — consult them before and during the loop, not after.

When exploring the codebase, use the project's domain docs already in context (openspec/ conventions, CONTEXT.md if present) so test names and interface vocabulary match the project's domain language, and respect ADRs in the area you're touching.

## What a good test is

Tests verify behavior through public interfaces, not implementation details. Code can change entirely; tests shouldn't. A good test reads like a specification — "user can checkout with valid cart" tells you exactly what capability exists — and survives refactors because it doesn't care about internal structure.

See [tests.md](tests.md) for good/bad test examples and [mocking.md](mocking.md) for the mock/no-mock boundary rules (external APIs vs your own collaborators) — read it before deciding what to mock.

## Seams — where tests go

A **seam** is the public boundary you test at: the interface where you observe behavior without reaching inside. Tests live at seams, never against internals.

**Test only at pre-agreed seams.** On the local pipeline the seams are agreed during to-spec (its step 2) — reuse those. If none were agreed, write down the seams under test and confirm them with the user before writing any test. No test is written at an unconfirmed seam. You can't test everything — agreeing the seams up front is how testing effort lands on the critical paths and complex logic instead of every edge case.

Ask (only when no seams are on record): "What's the public interface, and which seams should we test?"

## Anti-patterns

- **Implementation-coupled** — mocks internal collaborators, tests private methods, or verifies through a side channel (querying the database instead of using the interface). The tell: the test breaks when you refactor but behavior hasn't changed.
- **Tautological** — the assertion recomputes the expected value the way the code does (`expect(add(a, b)).toBe(a + b)`, a snapshot derived by hand the same way, a constant asserted equal to itself), so it passes by construction and can never disagree with the code. Expected values must come from an independent source of truth — a known-good literal, a worked example, the spec.
- **Speculative horizontal slicing** — writing tests for behavior nobody has agreed on yet (a whole feature's suite up front, or cases the ticket does not list) before any implementation. Bulk speculative tests verify _imagined_ behavior: you test the _shape_ of things rather than user-facing behavior, the tests go insensitive to real changes, and you commit to test structure before understanding the implementation. The risk is the amount of unconfirmed design commitment in the batch, not batching itself: the ticket's agreed acceptance list was confirmed at to-spec／to-tickets, so writing exactly those cases together is the **acceptance batch** described below, not this anti-pattern. Cases discovered during implementation are tracer bullets — add them one at a time, each with its own red.

## Rules of the loop

- **Red before green.** Write the failing tests first, then only enough code to pass them. Don't anticipate future tests or add speculative features.
- **One acceptance batch per ticket.** Write every test on the ticket's agreed acceptance list (typically 3–5, all at the declared seam) before any implementation, run once, and confirm each one is red _because the ticket's behavior is missing_ — a red caused by a broken harness or a missing import is not a baseline. Then implement until the batch is green; if some stay red, diagnose and repair against the whole batch rather than restarting per test. The batch is bounded by the checklist: anything not on it is added afterwards one test at a time, each with its own red. Why batch: an agent holds the whole ticket at once, and a red→green cycle per test cost 37–59 test runs per implement session (measured 2026-09-11) without buying design feedback the agreed acceptance list had not already fixed. Why bounded: a test beyond the agreed list is a design commitment nobody confirmed — that is the anti-pattern above.
- **Refactoring is not part of the loop.** It belongs to the review stage (/code-review at implement's close-out), not the red → green implementation cycle.

## Conditional TDD gate boundary

On tickets, this reference applies only when the batch selected `tdd` and the approved test obligation is `required`; `waived` preserves its approved closed reason. 在這條路線上，a required ticket is done when its acceptance batch at the declared seam was written first, observed red, and the minimum implementation made it pass — focused tests and code review are what establish that. `regression-closeout` 的 required 不是 TDD 豁免，也不使用這份執行配方；其測試義務由所選配方與共用收尾驗收。

## 踩過的坑

- 2026-07-28 引入定位：implement 的組件（inline 由主 session 叫、subagent 模式由 worker 配方叫），使用者不手動觸發；先前以「已有其他流程覆蓋」為由跳過判決，在遷移 frame 下翻案，導致 local pipeline 缺件。
- upstream watch 只盯 SKILL.md path；mocking.md / tests.md 兩姊妹檔不在雷達上（上游動它們通常伴隨 SKILL.md 動、殘餘風險接受）。
- 2026-09-11 上游 mattpocock 的「One slice at a time」＋「Horizontal slicing 反模式」在 agent worker 上量到每 session 37–59 次測試、單票 13 個切片各自紅綠（View B 實測，證據見 `~/Desktop/projects/.claude/trials/active.md` 的 tdd-acceptance-batch 條）。改成「票內有界驗收批次」：只把 to-tickets 已談定的 acceptance 一次寫紅、一次掃綠，批次外仍一測一紅。與上游分歧的理由是風險來源在「未經確認的設計承諾量」而非批次本身；ChatGPT Pro 顧問 2026-09-11 同一結論。刻意不動 seam 高度與拆票粒度，讓 trial 能單獨歸因。RED 基線：改前 agent 三條驗收跑 3 輪紅綠、13 次測試指令。
- 2026-08-12 `use /tdd where possible` 在三張自然 implement 票上得到 0/3 顯式接線，且 production-first 仍可被事後散文包裝成 TDD。把修正做成 RED／GREEN 收據引擎又讓 gate 冒充測試品質證明並擴大攻擊面；現只證明 conditional reference 被實際 invoke，不再宣稱能機器證明紅綠品質。2026-09-06 再降：Stop gate 不 block、只提示（`hooks/matt-tdd-gate.sh` 檔頭），required／waived 決策與 manifest 保留。
