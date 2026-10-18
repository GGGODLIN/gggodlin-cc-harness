---
name: write-pr-description
description: Use when a pull request title or description needs drafting or revising — before running `gh pr create`, `gh pr edit --body`, or any other command that opens a PR or replaces its description on any provider, and when the user asks to "write the PR description", "draft PR text", or "revise the PR body for the latest commits". Returns prose only; the caller or provider adapter (such as bitbucket-pr-mutation) performs the write. Do not use for PR comments, reviews, approvals, merges, state changes, or read-only PR queries.
---

<!-- 本檔在契約測試底下：bash ~/.claude/skills/write-pr-description/scripts/tests/write-pr-description-contract.test.sh -->

# Write PR Description

Keep evidence-based prose separate from provider mutation so every adapter can reuse the same draft without transferring approval or write authority.

## Workflow

1. **Set the draft boundary.** Produce title/body prose only. Do not call provider APIs, run provider preview/apply commands, create approval artifacts, or publish a PR. If a provider adapter invoked this skill, return the candidate to that adapter; the adapter remains the sole writer and approval/read-back owner. If it runs ahead of a direct CLI write such as `gh pr create`, return the candidate to the caller, which performs that write under its own confirmation rules. Done when the planned actions contain no provider mutation.

2. **Build the local evidence set.** Use the target branch supplied by the user or adapter; if it is unresolved, ask for it rather than guessing.
   - Read committed scope from `git log <base>..HEAD`, `git diff --stat <base>...HEAD`, and the relevant committed diff.
   - Read `git status --short`, `git diff --cached`, and `git diff` separately. Treat staged and unstaged work as uncommitted even when it is intended for the same PR.
   - Read the repository PR template, preserving its headings, order, required prompts, and comments as the structural authority.
   - Read locally available issue/spec context as intent and rationale, not as proof that the branch delivered it.
   - Use only actual validation receipts: an observed command/result, supplied test output, captured screenshot, or explicit statement that a check was not run. Missing evidence means “no receipt available,” not “passed.”
   - Treat session investigation notes — how the defect was found, dead ends, measurements behind a chosen value — as background for understanding the diff, not as body content.

   Done when every prospective result claim maps to committed diff evidence or an actual validation receipt, and every uncommitted path is identified separately.

3. **Choose the draft shape.** Read [references/drafting-rules.md](references/drafting-rules.md) before deciding density, claim phrasing, validation wording, or reviewer-guide inclusion.
   - Let the repository template outrank the default shape. Do not reorder its top-level headings or add a competing generic skeleton.
   - Without a template, default to `Summary` and `Validation`; add `Risk` only when the change has a meaningful failure mode. For external effects, destructive data changes, or a new persisted format, apply the recovery-boundary rules from drafting-rules.md in the existing Risk or reviewer Focus.
   - Add a reviewer guide only when reading order is non-obvious, review focus needs an explicit invariant, or blast radius is wider than the diff size suggests. An authorization, permission, data-ownership, or migration change always needs the guide, however few files it touches. When included, use four compact slots: `Start` for the first exact file/symbol, `Then` for the dependent implementation path, `Validate` for the exact test/evidence path when one exists, and `Focus` for the invariant or blast radius. Use paths and symbols from the evidence instead of generic labels. Nest it under the nearest template section when an extra top-level heading would disrupt the template.
   - Add a change outline when the diff changes an API or data contract, a key type, a component tree, file responsibilities, or a call or data flow; a change with no structural shift gets none. A reviewer reads a six-line tree faster than three paragraphs describing it, so the outline replaces the Summary bullets that would narrate that structure; keep Summary for what the views cannot show, such as intent and deliberate omissions. Place it as `### Change outline` under Summary unless the template has a closer slot, put one short sentence before each view, and pick only the views that match what changed:
     - endpoint request/response or table columns → `diff` of the contract or columns
     - a type the implementation hinges on → the type definition
     - behavior logic → short pseudocode
     - file responsibilities → shallow file tree, one comment per line
     - React component structure → component tree with the hooks, state, and package boundaries that matter
     - call or data flow → call tree

     Use `diff` when an existing shape changes and a `text` or language block when it is new; drop unchanged branches; write `<` and `>` literally inside blocks; use no Mermaid, so the body stays readable where Markdown diagrams are not rendered.

   Done when drafting-rules.md has been read in this run, every section has evidence-backed content, small changes have no ceremonial filler, a required reviewer guide shows all four slots, and a structural change has its outline.

4. **Draft from facts.** Match the repository’s title convention when local history shows one; otherwise use a short action-oriented title grounded in the committed diff.
   - Describe verified implementation changes directly.
   - Phrase issue/spec goals as intent unless diff or validation evidence proves the outcome. Never turn “should,” “acceptance asks,” or a future rollout goal into a completed result.
   - Preserve validation commands and observed outcomes exactly enough to audit. Pair available before/after receipts using the validation rules in drafting-rules.md. Name important checks that were explicitly not run; do not convert unit, build, or typecheck receipts into UI, integration, rollout, or performance evidence.
   - Keep a small PR to a few useful bullets. For a large foundational PR, summarize boundaries rather than listing every file.

   For a body with a change outline, assign each fact to one place before writing: field/type inventories and call order belong to the views; intent, effects, conditions, and limitations belong to Summary. When revising, use the old body as a fact source rather than copying its bullet structure. Check every Summary bullet against the views: a sentence that only says a field was added, exists, or is exposed belongs only in the view. A field name may still appear in a condition or effect; “Adds a `breed` field” duplicates a view, while “Cycles without a breed cannot contribute to the comparison” adds behavior the view does not show. Split mixed sentences and retain the behavior. Keep the reviewer guide, rollout, recovery boundary, and validation receipts in their own sections.

   Done when a reviewer can tell what changed, why, what was actually checked, and what remains unverified without reading intent as proof, and Summary contains no field/type inventory or call-order narration already owned by a view. Continue to Step 5.

5. **Return the candidate.** Emit Markdown in this shape:

   ```markdown
   ## Title
   <title>

   ## Body
   <body using the repository template or the justified default>
   ```

   If the tree is dirty, append `## Draft basis (not part of PR body)` and distinguish committed scope from staged/unstaged paths excluded from the candidate. Do not silently blend uncommitted work into the title or body. Done when title/body are copyable as a candidate and any dirty-tree note is visibly outside the PR body.

## 踩過的坑

- Diff size does not equal review risk: a tiny permission edit can need a reviewer guide because its blast radius is wide, while an ordinary two-file bugfix usually does not.
- A validation plan is not a validation receipt. Preserve “not run” and “no receipt available” instead of turning either into a checked result.
- Self-Verify is intentionally omitted: PR drafting is expected to be a frequent prose task, so an extra subagent on every use fails the low/medium-frequency gate; contract tests and bounded evals cover the recurring pressure cases instead.
