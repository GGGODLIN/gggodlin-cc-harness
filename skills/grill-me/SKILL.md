---
name: grill-me
description: 'Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. Use when user wants to stress-test a plan, get grilled on their design, or mentions "grill me"; propose it proactively when matt-pipeline pre-spec requirements stay fuzzy (deep decision tree, hedgy answers; to-spec step 0 routes here). Do not use for: spec/plan already confirmed and in execution (switch to a fresh session instead), one-off throwaway scripts, or one-shot adversarial review without interaction (use /review-spec).'
upstream: mattpocock/skills
upstream-path: skills/productivity/grilling/SKILL.md
upstream-pinned: 6654f6b
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/memory-audit-contract.test.sh -->

Interview me relentlessly until we reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled — the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for my answers before the next round.

Format a round like so:

```
❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>

---

❓ **Q2** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

Each round I answer reshapes the tree — settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never mine. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent to find it — don't ask me for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report — ask the rest of the frontier now. When you dispatch a lookup, name in the same round which pending questions it blocks — a question you can't classify against a running lookup belongs to a later round. The _decisions_ are mine — put each one to me and wait for my answer.

If a decision belongs to a third party (such as a PM, designer, or coworker), propose `to-questionnaire`; wait for my confirmation before drafting it, and never send it on my behalf.

If I say 訪談我 or 一題一題來, switch to one question at a time — the global 訪談模式 rule takes precedence over rounds.

Track a running confidence number for "I could write this spec correctly right now" (e.g. ~30% → ~90%). Below ~70%, name what's missing in one line — the number forces honesty about gaps a vague "getting clearer" would hide.

Stopping test (checkable, not a vibe): can you predict my answers to the next three questions you would ask? Yes → stop interviewing and restate. If after many rounds you still can't predict, say so plainly — something foundational is missing and more questions of the same kind won't fix it.

When my answer signals sophistication rather than desire (scalable / clean / modern / best practice), probe want vs. should-want: "If you didn't have to justify this to anyone, what would you actually want?"

"Whatever you think is best" / "sounds good" / "sure" is delegation, not a decision — re-ask with two concrete options instead of accepting it as a yes.

Product-layer lens (2026-07-11, condensed from gstack /office-hours forcing questions): when the thing being grilled is an idea / tool / feature rather than a technical design, add these before drilling architecture — (1) Demand reality: what's the strongest evidence anyone wants this — real behavior, not "sounds interesting"; "I think X would want…" is hypothetical, "I did X three times last month by hand" is real. (2) Status quo: what's the current workaround and what does it cost — if the answer is "nothing", the pain may not be real. (3) Actual human + narrowest wedge: name the specific person/scenario (a category is not a person) and the smallest version that delivers value this week, not after the platform. Stack the pressure; don't collapse into one soft question. Skip this lens for pure refactors or spec-confirmed work.

The final restate covers six fields: Outcome / User / Why now / Success / Constraint / Out of scope. "Out of scope" is where scope creep hides — its absence means the boundary was never actually decided.

Do not enact the plan until I confirm we have reached a shared understanding.

## 踩過的坑

- 2026-08-06 rounds graft：本文原內聯 v1.1.0 grilling（one-at-a-time），換成 v1.2.2 rounds 段（frontier 分回合＋固定題型＋子代理不阻塞）；九條在地增修全保留，終止判準沿用本地預測式（比上游 frontier-empty 強）。upstream-path 同步改追 grilling 原語檔（原追 wrapper 導致週雷達永遠報綠、靜默漏 6 個上游 commit）。不加 Self-Verify（純對話引導、無可對表產出）。matt-pipeline trial 換版日已記 ledger。
