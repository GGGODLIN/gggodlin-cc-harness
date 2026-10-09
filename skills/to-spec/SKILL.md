---
name: to-spec
description: "Turn the current conversation into a spec — no interview, just synthesis of what was already discussed. Lands in the repo's spec convention: openspec/ change dir (validator-compliant) if present, else .scratch/{feature-slug}/spec.md. Use when a discussion has converged and it is time to write it down — 寫成 spec / 收斂成 spec / to-spec, or the local pipeline was chosen at kickoff. Do not use for: interviewing the user (grill-me / 訪談模式), reviewing an existing spec (/review-spec), or a topic that has not yet taken shape (brainstorm)."
upstream: mattpocock/skills
upstream-path: skills/engineering/to-spec/SKILL.md
upstream-pinned: 6654f6b
---
<!-- 本檔在契約測試底下：bash skills/to-spec/scripts/tests/adr-authoring-contract.test.sh -->

# To Spec

This skill takes the current conversation context and codebase understanding and produces a spec. Do NOT interview the user — just synthesize what you already know.

## Process

0. **Requirements gate — to-spec synthesizes, it never discovers.** Scan the conversation for confirmation evidence: decisions the user actually made, scope/behavior questions they answered, alternatives weighed. If that evidence is missing (a fuzzy idea jumped straight to 「寫 spec」), stop — do not synthesize. Run the missing confirmation instead: plain interviewing per the questioning discipline already in context, or propose /grill-me when the decision tree is deep or the user's answers hedge. Fog check while confirming: when unresolved items exceed what one conversation can close AND several are undecidable until work happens first (facts to research, a prototype to react to, access to provision), tell the user this is wayfinder-scale fog and propose /wayfinder — a decision-ticket map worked across sessions — with a one-line cost warning (charting is a full session of interviewing). On explicit yes, invoke the wayfinder skill and stop this flow. Done when: the open decisions are closed (then continue to step 1), or the user chose the wayfinder path.

1. Explore the repo to understand the current state of the codebase, if you haven't already. Use the project's domain glossary vocabulary throughout the spec, and respect any ADRs in the area you're touching. Done when: the modules the feature touches and their existing seams are identified.

2. Sketch out the seams at which you're going to test the feature. Existing seams should be preferred to new ones. Use the highest seam possible. If new seams are needed, propose them at the highest point you can. The fewer seams across the codebase, the better - the ideal number is one.

Check with the user that these seams match their expectations. Done when: the user has confirmed the seams. Then continue to step 2a.

2a. **ADR authoring gate — after requirements and test seams are confirmed, before drafting or landing.** Inspect each decision already supported by the confirmed conversation against the three ADR-FORMAT conditions: hard-to-reverse, surprising without context, and real trade-off. Only a decision with all three true enters one candidate decision set. If the set is non-empty, use the Skill tool to make exactly one `domain-modeling` invoke for ADR authoring, passing the complete candidate decision set and its relevant context, alternatives, and consequences to its owner. Do not invoke it once per decision. If any condition is false for a decision, omit only that decision; do not let a non-qualifying decision suppress other qualifying decisions. If no decision qualifies, make zero `domain-modeling` invokes. This ADR gate does not execute `check-decisions`; landing still follows its existing checker rules, including `openspec validate`. Done when: every decision has a three-condition result, the candidate set is either handed off once or empty, and the flow continues to step 3.

3. Draft the spec using the template below. Provenance tags (defined in the template) are mandatory on every user story and implementation decision — they are audited by the yagni review axis: `[inferred]` items carry the burden of proof there, and fabricated quotes are treated as findings. Before landing, continue to step 3a. Done when: every drafted story/decision has a tag.

3a. **Behavior completeness pass — scan only what applies.** Review the draft for states and transitions; inputs; empty, error, loading, and cancel behavior; permissions, offline behavior, and timeouts; races, concurrency, and stale state; focus and accessibility. Add concrete behavior only where the feature can encounter it, fold it into User Stories or Implementation Decisions, and retain the required source tag on each addition. Do not add a behavior matrix, category headings, or empty optional headings; omit inapplicable cases. Then land the spec per the Landing convention section. Done when: every applicable behavior is explicit and source-tagged, inapplicable cases created no empty headings, and the spec is landed.

4. Hand off with one question before ticketing: 「要不要先跑 /review-spec？spec 是模型代寫時建議至少跑 yagni 軸（審值不值得，可單獨跑）。」 If the user declines, the natural next step is /to-tickets. Done when: the user has answered the review question.

<spec-template>

## Problem Statement

The problem that the user is facing, from the user's perspective.

## Solution

The solution to the problem, from the user's perspective.

## User Stories

A numbered list of user stories. Each in the format:

1. As an {{actor}}, I want a {{feature}}, so that {{benefit}} {{source-tag}}

`{{source-tag}}` is REQUIRED, exactly one of: `[user: "<verbatim quote>"]` (the user actually said it — quote them verbatim), `[evidence: <data source>]` (a measured fact), or `[inferred]` (the model's own extrapolation).

Cover every behavior the feature actually needs; a story the conversation does not support is an `[inferred]` item and carries the burden of proof at review.

## Implementation Decisions

A list of implementation decisions that were made. This can include:

- The modules that will be built/modified
- The interfaces of those modules that will be modified
- Technical clarifications from the developer
- Architectural decisions
- Schema changes
- API contracts
- Specific interactions

Each decision ends with the same REQUIRED `{{source-tag}}` as user stories.

Do NOT include specific file paths or code snippets. They may end up being outdated very quickly.

Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it within the relevant decision and note briefly that it came from a prototype. Trim to the decision-rich parts — not a working demo, just the important bits.

## Testing Decisions

A list of testing decisions that were made. Include:

- A description of what makes a good test (only test external behavior, not implementation details)
- Which modules will be tested
- Prior art for the tests (i.e. similar types of tests in the codebase)

## Out of Scope

A description of the things that are out of scope for this spec.

## Further Notes

Any further notes about the feature.

</spec-template>

## Landing convention (check once per feature — the whole feature lands on one path, no mixing)

**Repo has an `openspec/` directory** → land as an openspec change, mapping the template onto the repo's artifacts (its openspec/AGENTS.md is the SSOT for structure and tiering):

- `openspec/changes/<change-name>/proposal.md` ← Problem Statement + Solution + User Stories (as Why / What Changes), plus Out of Scope
- `design.md` ← Implementation Decisions + Testing Decisions (small change: fold into proposal.md)
- `specs/<capability>/spec.md` delta ← the requirements, under `## ADDED/MODIFIED/REMOVED Requirements` markers. Validator hard rules: header must be unnumbered `### Requirement: <title>`, each requirement body must contain SHALL or MUST (English keywords), and at least one `#### Scenario:` block.

Done when: `openspec validate <change-name>` passes green — do not hand off on a red validate.

**No `openspec/` directory** → write the spec verbatim from the template to `.scratch/{feature-slug}/spec.md`. Done when: the file exists and the user has seen the path.

## 踩過的坑

