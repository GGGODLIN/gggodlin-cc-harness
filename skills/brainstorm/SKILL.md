---
name: brainstorm
description: "Use at the opening of a session when the user brings a topic that has not taken shape yet — 我有個還沒定形的題目 / 想討論一件事但還不確定要做什麼 / 幫我想想這個要怎麼弄 / 還沒想清楚先聊聊 / brainstorm / 一起想個方向 / 這個值不值得做. Pipeline-neutral — pure discussion that implements nothing afterwards is a fully legitimate use. Do not use for: answers that live in the user's own head and need extracting one question at a time (訪談模式), answers held by a third party (to-questionnaire), a proposal already formed that needs adversarial pressure (grill-me), or a feature already decided on that needs a spec (`to-spec`)."
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/memory-audit-contract.test.sh -->

A topic that has not taken shape yet is not a small version of a decided one, and improvising the clarification has four ways of going wrong:

1. **Anchoring** — the first reading of the request gets picked up and drilled, and the rest of the conversation rearranges the furniture in the wrong room.
2. **Early solutioning** — one proposal lands on the table, the user starts orbiting it, and the needs they never voiced never get their turn.
3. **A missing dimension** — the thing gets designed well and then never used, because nobody asked "in what situation would you reach for this".
4. **Evaporating residue** — "we considered X and dropped it because Y" lives only in this session's context and is re-derived from scratch next time.

The first three are invisible from the inside: an anchored discussion feels focused, and a missing dimension leaves no trace until months later. So the countermeasures below are unconditional structural steps, not things to stay alert for. Run them even when the topic looks obvious.

## Process

### 1. De-anchor and intake

The opening sentence usually arrives with a solution already baked in ("I want a hook that…", "let's make a script that…"). Strip the proposed solution, mechanism, and components; keep every observable fact — what the user did by hand, what happened, what annoyed them, counts, dates, names. **Strip theories, keep observations.** Then restate the underlying need in one or two sentences with the solution removed, and show that restatement to the user.

A "fact" that cannot be restated as an observation is a theory in disguise — put it back to the user instead of carrying it forward as a given.

Done when: the restatement contains no mechanism noun taken from the user's phrasing, and every observable the user supplied either appears in the restatement or was explicitly raised with them.

### 2. Widen — framings with receipts

Two parts, in this order.

**2a. Stack archaeology (before any framing is born).** Look for prior attempts at this same topic and their causes of death: memory (`~/.claude/memory`) and wiki prose via the docs-oriented semantic search, session jsonl history, and `git log` / notes in the repo the topic belongs to. Report what was found. "Nothing found" is a valid result only when reported together with the queries that were run — the receipts are the point.

**2a′. External archaeology (optional, decided explicitly).** Strip the personal nouns from the topic (names, repo names, home-grown mechanism names); if what remains still reads like the title of an analysis someone else could have published, find 3-5 such pieces and read off the axes they share. A cold-thought framing set drifts back to the angles visible from the question itself; the axes in the literature are what surface the questions nobody asked. Dispatch one agent per `~/.claude/references/perspective-sub-scout.md` (predicates, steps, return shape, ~2.5 min). Skip when the topic is a purely home-grown mechanism or has already taken shape. Either way the 2a report carries one fixed line: `External archaeology: ran (N artifacts; axes: …)` or `External archaeology: skipped (stripped: "<the topic with personal nouns removed, one sentence>"; predicate 1 or 2 fails: one sentence)` — a skipped line must show the stripped topic, because "my material is home-grown" is not the same as "my topic is home-grown" (2026-09-02 review: 2 of 6 skips conflated the two); a report without the line means the decision was never made.

**2b. Produce 3-5 rival problem framings.** A framing names a *problem the observations could be evidence for*, not a solution to one. They have to stand far apart: if two framings would lead to the same next step, they are one framing wearing two hats. One of them is always a **"maybe nothing needs building"** framing. Each framing carries its premise list (see Premise ledger).

This step is the countermeasure to anchoring, and it works because a single reading cannot pass it structurally — three genuinely rival framings cannot be produced by elaborating one.

Done when: every framing has at least one premise with a state assigned, the do-nothing framing is present, each surviving pair of framings differs in what it would have you do next, and — when external archaeology ran — at least one framing cites a literature axis with its URL as a receipt.

### 3. Clarify — discriminating questions

One question at a time, waiting for the answer before the next. Each question is the one that best splits the live framings: if an answer could not kill at least one framing, it is not the question to ask now.

Each turn of this step consists of exactly three parts, in this order:

1. The live framings, one line each, with the ones this answer killed struck out and their cause of death appended.
2. Exactly one question — the one that best splits what is still live.
3. A recommended answer to that question, so the user can disagree with something concrete rather than compose from scratch.

**Solutions stay locked while framings are live.** The three parts above are the whole turn: no mechanism, tool, design, or implementation appears before the framing is settled with the user, including as a passing illustration — the illustration is how the lock usually leaks. The lock exists because the first proposal on the table becomes the thing the user reacts to, and reaction crowds out the needs that were never voiced.

Done when: the user has confirmed one framing (or an explicit combination of framings), and every killed framing has a recorded cause of death.

### 4. Fill — the dimension table

Run this table before converging, regardless of how settled the answer already looks. Starting four rows:

| Dimension | The question |
| --- | --- |
| **Trigger** | In what situation will this be remembered or reached for, and what fires it? |
| **Maintenance** | Who updates it, and what makes it go stale? |
| **Competition** | Does something already in the stack occupy this slot? |
| **Exit** | What would count as failure, and what gets torn out when that happens? |

The table is per-topic extensible: add the rows this topic type demands (cost, data source, blast radius, who else sees it, …). Every post-mortem is allowed to add a permanent row — when a row comes from a real miss, record it in 踩過的坑 below along with the miss.

Unconditional because this is where failure mode 3 hides: the well-designed thing with zero invocations was never asked the Trigger question, and nothing inside the discussion would have surfaced that.

Done when: each of the four starting rows plus any added rows has an answer or an explicit "not applicable because X" — no row silently blank.

### 5. Converge — the gate

Put the exits to the user and let them choose; picking for them re-introduces failure mode 2 at the last step.

- **(a) Stop here.** The discussion was the deliverable. A legitimate, common ending — not a failure to reach implementation.
- **(b) Hand off to the local chain** — continue with `to-spec` → `to-tickets` → `implement`. The user chooses whether to continue at the moment of handoff; this skill does not start implementation.
- **(c) Open a ticket to upgrade into an artifact** — a research ticket, or a prototype built to be thrown away. Propose this when the contest between the last framings rests on a premise nobody can resolve by thinking.

**Residue lands whichever exit was taken.** Landing follows topic ownership:

- **Project-scoped topic** → inside that repo, following the note/spec convention already in context there; absent one, `.scratch/<topic-slug>/brainstorm-<YYYY-MM-DD>.md`.
- **General or cross-project topic** → a memory entry under `~/.claude/memory`, placed per the memory cluster rules already in context (cluster check before adding a top-level entry).

The residue has four slots. Fill each; an empty one is the thing that evaporates:

<residue-template>

# {{Topic}} — brainstorm residue, {{YYYY-MM-DD}}

**The need, de-anchored:** the step-1 restatement, one or two sentences.

**Framing chosen:** the surviving framing, and the exit the user picked.

**Framings killed:** one bullet per killed framing — the framing, then its cause of death. The do-nothing framing appears here too when it was not chosen.

**Premises still open:** the ledger entries that ended as *unknowable until built* or *checkable but unchecked*, each with what would settle it.

</residue-template>

Done when: the user has named an exit, and the residue exists at a path the user has seen with all four slots filled.

## Premise ledger

Every candidate framing carries a premise list, and each premise gets exactly one of four states. This is the structural form of "facts get looked up, decisions get asked" — the state decides who does what about that premise.

| State | Meaning | What it obliges |
| --- | --- | --- |
| **Verified** | Confirmed against a source | Cite the source inline next to the premise |
| **Checkable, unchecked** | Findable right now | Check it now — a framing is never handed over half-finished |
| **Unknowable until built** | Only doing it will tell | Fuel for exit (c). When two framings' contest rests on one of these, that is the moment to propose the ticket |
| **Pure preference** | The answer is in the user's head | Becomes a question for the user in step 3 |

A framing whose premises are all "pure preference" is not a framing yet — it is a question list.

## Cost tiers

| Tier | Examples | Who decides |
| --- | --- | --- |
| **Seconds** | grep memory, semantic code/docs search, session jsonl, `git log` | Unconditional — runs before a framing is born, no announcement needed |
| **Minutes** | fork a subagent for web research, run a small count over history | The agent's own call — announce that it ran, do not ask permission |
| **Ticket** | research ticket, throwaway prototype | This protocol proposes, the user decides |

## Boundary — where the answer lives

The family of adjacent tools splits on one axis: where the answer to the current blocker lives.

| The answer lives… | Use |
| --- | --- |
| Nowhere yet — the topic itself has no shape | **this skill** |
| In the user's head, needing one-at-a-time extraction | 訪談模式 (the interview mode in the always-on rules) |
| In a third party's head (PM, designer, coworker) | `to-questionnaire` |
| In a proposal already formed, needing pressure | `grill-me` |
| In a feature already decided on, needing its design recorded | `to-spec` |

## Red flags — the protocol is being skipped

- A mechanism, tool, or "we could just…" has appeared and the user never confirmed a framing.
- There are two framings on the table, or three that would all lead to the same next step.
- The dimension table got skipped because the answer felt settled — that feeling is what failure mode 3 feels like from the inside.
- Converging with no residue written, on the grounds that this one was a short discussion.

Any of these: back up to the step that was skipped and run it.

## 踩過的坑

- 2026-08-05 實例（trial-review 認領鎖設計 session）：skill 在討論已進行約百餘則、方向大致成形後才被 invoke——載入了但五步協議詞彙零出現，流程被既有討論吸收。這不是失敗模式而是邊界：協議的價值窗在「開場未定形」，討論已收斂到單一設計題時，invoke 只是載入背景紀律、五步自然退位。判準：invoke 時若使用者已鎖定唯一方向且在細化，直接進鑑別式提問（步驟 3）即可、不必回頭硬跑框架發散。
