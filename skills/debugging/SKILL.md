---
name: debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes. Do not use for planning a feature before its spec is settled or reviewing an existing spec (review-spec).
upstream: mattpocock/skills
upstream-path: skills/engineering/diagnosing-bugs/SKILL.md
upstream-pinned: 4588b32ecab9ecc9fc8cc6b6c5e7d675b6004b0d
---

<!-- 本檔在契約測試底下：bash ~/.claude/skills/debugging/scripts/tests/presentation-shape.test.sh -->

# Systematic Debugging



## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** find the root cause before proposing a fix — random fixes waste time and create new bugs, and a symptom fix leaves the bug in place.

## When to Use

Use for any technical issue:
- Test failures
- Bugs in production
- Unexpected behavior
- Performance problems
- Build failures
- Integration issues

## The Four Phases

### Phase 1: Root Cause Investigation

Before proposing a fix:

1. **Read Error Messages Carefully**
   - Don't skip past errors or warnings
   - They often contain the exact solution
   - Read stack traces completely
   - Note line numbers, file paths, error codes

2. **Reproduce Consistently**
   - Can you trigger it reliably?
   - What are the exact steps?
   - Does it happen every time?
   - If not reproducible → run the non-repro decision tree below before anything else — "gather more data" without classification is just waiting

   **Non-repro decision tree**（absorbed from addyosmani/agent-skills debugging-and-error-recovery, 2026-07-11）— classify which axis the flakiness lives on, each has different next actions:
   - **Timing-dependent（race）？** → add artificial delays to widen the race window; log event ordering with timestamps; run under load/parallelism to raise the hit rate
   - **Environment-dependent？** → diff env vars / config / dependency versions between where it fails and where it doesn't; try empty vs populated database / cache
   - **State-dependent？** → check leaked state between tests or runs; run the failing case in isolation vs after the full suite — order sensitivity is the tell
   - **Truly random？** → rare. Instrument the suspect path first (structured logging + correlation id), then wait for the next occurrence with evidence capture already in place

   Classified and instrumented → continue to step 3 (Check Recent Changes) with the evidence collected.

3. **Check Recent Changes**
   - What changed that could cause this?
   - Git diff, recent commits
   - New dependencies, config changes
   - Environmental differences

4. **Gather Evidence in Multi-Component Systems**

   **WHEN system has multiple components (CI → build → signing, API → service → database):**

   **BEFORE proposing fixes, add diagnostic instrumentation:**
   ```
   For EACH component boundary:
     - Log what data enters component
     - Log what data exits component
     - Verify environment/config propagation
     - Check state at each layer

   Run once to gather evidence showing WHERE it breaks
   THEN analyze evidence to identify failing component
   THEN investigate that specific component
   ```

   **Example (multi-layer system):**
   ```bash
   # Layer 1: Workflow
   echo "=== Secrets available in workflow: ==="
   echo "IDENTITY: ${IDENTITY:+SET}${IDENTITY:-UNSET}"

   # Layer 2: Build script
   echo "=== Env vars in build script: ==="
   env | grep IDENTITY || echo "IDENTITY not in environment"

   # Layer 3: Signing script
   echo "=== Keychain state: ==="
   security list-keychains
   security find-identity -v

   # Layer 4: Actual signing
   codesign --sign "$IDENTITY" --verbose=4 "$APP"
   ```

   **This reveals:** Which layer fails (secrets → workflow ✓, workflow → build ✗)

   **Redact before showing**（吸收自上游 2026-08-11；適用於本步驟與 Phase 3 證據表——所有要秀給使用者的指令、輸出、log、抓包內容）：
   - Secret 值本身（API key / password / token 值 / DSN 密碼段）不逐字出現在你顯示的輸出裡——改寫**指位**：env var 名、`.env` 路徑＋行、keychain 條目名（與 save-session 同一條規則）；同一值的非 secret 部分（host / port / db 名）照舊原樣。
   - Feedback loop 綁 env var 讓憑證留在環境不進輸出——上面 `${IDENTITY:+SET}` 的「印存在性不印值」就是標準形。
   - 帶 auth header 的 captured artifact 只引用有訊號的行。
   - 遮完不足以診斷 → 明說並問使用者，不要印出 secret。

5. **Trace Data Flow**

   **WHEN error is deep in call stack:**

   See `root-cause-tracing.md` in this directory for the complete backward tracing technique.

   **Quick version:**
   - Where does bad value originate?
   - What called this with bad value?
   - Keep tracing up until you find the source
   - Fix at source, not at symptom

### Phase 2: Pattern Analysis

**Find the pattern before fixing:**

1. **Find Working Examples**
   - Locate similar working code in same codebase
   - What works that's similar to what's broken?

2. **Compare Against References**
   - If implementing pattern, read reference implementation COMPLETELY
   - Don't skim - read every line
   - Understand the pattern fully before applying

3. **Identify Differences**
   - What's different between working and broken?
   - List every difference, however small
   - Don't assume "that can't matter"

4. **Understand Dependencies**
   - What other components does this need?
   - What settings, config, environment?
   - What assumptions does it make?

### Phase 3: Hypothesis and Testing

**Scientific method:**

1. **Form 3-5 Ranked Hypotheses**（本地差異：原版是 single hypothesis，改多假設 anti-anchor + user checkpoint）

   **0. Strip the reporter's causal framing first**（absorbed from UditAkhourii/adhd REFRAME pre-pass, 2026-07-30）— a bug report carries two things: observables, and the reporter's theory about them. The theory silently narrows every hypothesis that follows, including the ones you think you invented independently.
   - **Strip**: the presumed locus ("the cache is stale"), the presumed mechanism ("it's a race"), the presumed component ("the API layer drops it"), and any "we already ruled out X" with no evidence attached.
   - **Keep every observable**: exact error text, stack traces, versions, file paths, timing numbers, repro steps, what changed recently. In debugging the details usually ARE the evidence — over-stripping here deletes the answer.
   - Restate as: what was observed, and what was expected instead, using no mechanism words.
   - **Two tracks from here on**: hypothesis generation below runs on the stripped restatement; Phase 4 evidence checks run against the original report wording. If the two disagree about what the bug even is, that disagreement is itself a hypothesis.

   - Generate 3-5 possible root causes **before testing any of them**. Single-hypothesis generation anchors on the first plausible idea.
   - Rank them: most likely first
   - **Spread requirement**（absorbed from UditAkhourii/adhd cognitive frames, 2026-07-30）— 3-5 hypotheses that are all variants of one story is still single-hypothesis debugging wearing a hat. At least two must sit on different vantages. Cycle these when the list looks monotone:
     - **hardware-eyes** — latency, memory layout, cache lines, timing budget, physical limits
     - **ant-colony** — no central planner: emergent behaviour, distributed race, ordering between independent actors
     - **biology** — feedback loops, homeostasis, retry amplification, something that self-corrects until it can't
     - **speedrunner** — boundaries and exception paths: off-by-one, first/last element, empty input, the path nobody walks

     Unlike open-ended ideation, **do not ban the obvious hypothesis** — in debugging it is often correct and it stays ranked first. The requirement is spread across the list, not novelty at the top.
   - Each must be **falsifiable** — state the prediction: "If X is the cause, then <changing Y> will fix it / <changing Z> will make it worse". If you cannot state the prediction, the hypothesis is a vibe — discard or sharpen it.
   - **Verify-then-discuss（2026-07-16 trial 收案改法，取代原「先給 user re-rank」checkpoint）**: after listing, immediately self-verify every hypothesis that is cheaply verifiable with your own tools (read code, grep, run repro, devtools) — do NOT stop to wait for user re-ranking. Then discuss the survivors using this shape first: `觀察到什麼 → 哪一步首次由正確變錯誤 → 根因 → 下一步`. If the failure crosses three or more components or layers, put one single-line call tree／狀態流 before the details. 先輸出問題形狀，再附假設表與證據表；evidence cells obey Phase 1 step 4's Redact rule (secret 值改指位、不逐字印). Rationale: 07-09~07-16 觀察，唯一一次 re-rank checkpoint user 回「還是你直接測，反正你有工具」；user 要的是看證據拍板、不是空想排序。Only stop to ask BEFORE verifying when a test is destructive, expensive, or needs access only the user has.

2. **Test Minimally**
   - Make the SMALLEST possible change to test hypothesis
   - One variable at a time
   - Don't fix multiple things at once

3. **Verify Before Continuing**
   - Did it work? Yes → Step 4 (Ask About a Bounded Same-Root-Cause Variant Scan)
   - Didn't work? Test the next ranked hypothesis; form new ones only after the list is exhausted
   - DON'T add more fixes on top

4. **Ask About a Bounded Same-Root-Cause Variant Scan**
   - After Step 3 confirms the root cause, ask in text whether the user wants a bounded exact→general sibling search for that same root cause.
   - Run the scan only after explicit affirmative consent. Refusal, no answer, or unclear consent → Phase 4.
   - If the user explicitly agrees, run exactly two rounds: exact symbol/error pattern once, then adjacent callers/same-kind implementations once.
   - Stop after those two rounds, when matches exceed 20, or after 10 minutes, whichever comes first. Do not expand this into a codebase-wide audit.
   - After the scan, or if explicit consent was not received, continue to Phase 4.

5. **When You Don't Know**
   - Say "I don't understand X"
   - Don't pretend to know
   - Ask for help
   - Research more

### Phase 4: Implementation

**Entry check:** Root cause confirmed but the Phase 3 Step 4 variant-scan question never asked? Ask it now, once, before touching the fix — in long sessions this skill loads early and that ask is easy to drop by the time the root cause lands.

**Fix the root cause, not the symptom:**

1. **Create Failing Test Case**
   - Simplest possible reproduction
   - Automated test if possible
   - One-off test script if no framework
   - MUST have before fixing
   - Use the `tdd` skill for writing proper failing tests

2. **Implement Single Fix**
   - Address the root cause identified
   - ONE change at a time
   - No "while I'm here" improvements
   - No bundled refactoring

3. **Verify Fix**
   - Test passes now?
   - No other tests broken?
   - Issue actually resolved?

4. **If Fix Doesn't Work**
   - STOP
   - Count: How many fixes have you tried?
   - If < 3: Return to Phase 1, re-analyze with new information
   - **If ≥ 3: STOP and question the architecture (step 5 below)**
   - DON'T attempt Fix #4 without architectural discussion

5. **If 3+ Fixes Failed: Question Architecture**

   **Pattern indicating architectural problem:**
   - Each fix reveals new shared state/coupling/problem in different place
   - Fixes require "massive refactoring" to implement
   - Each fix creates new symptoms elsewhere

   **STOP and question fundamentals:**
   - Is this pattern fundamentally sound?
   - Are we "sticking with it through sheer inertia"?
   - Should we refactor architecture vs. continue fixing symptoms?

   **Discuss with your human partner before attempting more fixes**

   This is NOT a failed hypothesis - this is a wrong architecture.

## Red Flags - STOP and Follow Process

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "Pattern says X but I'll adapt it differently"
- "Here are the main problems: [lists fixes without investigation]"
- Proposing solutions before tracing data flow
- **"One more fix attempt" (when already tried 2+)**
- **Each fix reveals new problem in different place**

**ALL of these mean: STOP. Return to Phase 1.**

**If 3+ fixes failed:** Question the architecture (see Phase 4.5)

- 使用者出現「是這樣嗎 / 停止猜測 / 我們卡住了嗎」這類回頭質疑時，當作「目前這條路不成立」的訊號，回 Phase 1 重新取證，不要繼續加修法。

## Quick Reference

| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, gather evidence | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, compare | Identify differences |
| **3. Hypothesis** | Strip causal framing, form 3-5 ranked hypotheses spanning ≥2 vantages, test minimally | Root cause confirmed; shape-first report; bounded sibling scan only if explicitly approved, otherwise next hypothesis or Phase 4 |
| **4. Implementation** | Create test, fix, verify | Bug resolved, tests pass |

## When Process Reveals "No Root Cause"

If systematic investigation reveals issue is truly environmental, timing-dependent, or external:

1. You've completed the process
2. Document what you investigated
3. Implement appropriate handling (retry, timeout, error message)
4. Add monitoring/logging for future investigation

**But:** treat "no root cause" as a conclusion that needs the same evidence as any other — most such cases turn out to be incomplete investigation.

## Supporting Techniques

These techniques are part of systematic debugging and available in this directory:

- **`root-cause-tracing.md`** - Trace bugs backward through call stack to find original trigger
- **`defense-in-depth.md`** - Add validation at multiple layers after finding root cause
- **`condition-based-waiting.md`** - Replace arbitrary timeouts with condition polling

**Related skills:**
- **tdd** - For creating the failing test case (Phase 4, Step 1)
- **implement** - For implementation closeout after the fix
- **dispatch-and-verify** - For expected-versus-actual verification before claiming success
