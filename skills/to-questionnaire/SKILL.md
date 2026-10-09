---
name: to-questionnaire
description: "Turn a decision the user can't answer alone into a Markdown questionnaire for a specific person (PM / designer / coworker) to fill in async. Use when a discussion hits something outside the user's own authority — 你我敲不定、但必須向第三方釐清 — and a person holds the answer: surface this tool and offer to draft the questionnaire (要問 同事甲 / 要跟 同事乙 對 / 收需求 / to-questionnaire). Do not use for: questions the user can answer themselves (訪談模式), dispatching work to an LLM implementer (handoff-impl), or facts findable by research (research-before-answer)."
upstream: mattpocock/skills
upstream-path: skills/productivity/to-questionnaire/SKILL.md
upstream-pinned: 6654f6b
---

Turn something the user can't answer alone into a **questionnaire** — a Markdown document they hand to one person to fill in async, or fill out together over a meeting. The recipient holds knowledge the user lacks; the questionnaire pulls it out of them.

When triggered proactively mid-discussion (not by the user's explicit request): first surface and confirm — 「這題超出你的權責、要不要出一份問卷給 {{對方}}？」 — and proceed only on yes. The reminder is the job; drafting starts after the user agrees.

**Grill the send, not the subject.** Interview the user only about the _send_, which they can always answer: who it goes to, and what they need back. The questions in the document then target the **gap** between what the recipient knows and what the user needs.

1. **Who is it going to?** Ask, in one exchange (one message covering the sub-points together), the recipient's role, expertise, and relationship to the user. This fixes the questionnaire's tone and how much context it must carry. Done when you know who the recipient is and what they know that the user doesn't.

2. **What do you need back?** Ask, in one exchange (one message covering the sub-points together), the specific decisions or facts the user can't resolve alone and needs from this person. Done when you have a concrete list of what the user must walk away able to do or decide.

3. **Write the questionnaire.** Draft questions aimed at the gap from steps 1–2, following the Document structure below. Write it to `.scratch/<topic-slug>/questionnaire-<recipient-slug>.md` (create the dir) and report the path — the user sends it themselves (Slack / Asana comment); never send on their behalf. Done when the file exists, every item the user named in step 2 is covered by a question, and the user has seen the path.

## Document structure

Frame the document as a **discovery questionnaire**: the user lacks context, the recipient holds it. Order questions most-important-first — async means you may only get one pass — and group them under `##` headings by theme once there are more than a handful. Write it using the template below.

問卷語言跟隨收件人：收件人讀什麼語言就寫那個語言（模板是骨架，不是語言規定）。

<questionnaire-template>

# {{Questionnaire title}}

**Purpose:** why this questionnaire exists and the decision riding on it.

**From:** {{the user}} — **To:** {{the recipient}} — **How your answers will be used:** {{where they go}}

## Context

One paragraph orienting a recipient who wasn't in the user's head. Enough to answer well, not a page.

## How to answer

Deadline and rough effort. Partial answers and "I don't know" are useful — flag anything you're unsure of rather than skipping it.

## {{Theme heading}}

One `##` section per theme. Under each, its questions, most-important-first. Every question is one idea — never compound — with an answer stub directly beneath, and a one-line _why this matters_ only where the question could be misread or invite a throwaway answer.

<question-example>
### What load is the system expected to handle at launch?

_Why this matters: it decides whether we provision for burst traffic now or defer it._

>
</question-example>

## Anything else?

A closing catch-all: anything we didn't ask that we should know?

</questionnaire-template>

## 踩過的坑

