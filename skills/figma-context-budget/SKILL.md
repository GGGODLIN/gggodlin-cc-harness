---
name: figma-context-budget
description: Use BEFORE any Figma MCP tool call during design-to-code work — reading, planning, or implementing a Figma design. Complements implement-design by adding context-budget discipline on top of its code-generation workflow. Do not use when writing back to Figma or when generating new Figma files from code — no budget rules apply there.
---

# Figma Context Budget

## Purpose

`get_design_context` on a full Frame can return 50k+ tokens of raw node JSON and blow the context window. This skill enforces four rules that keep Figma MCP usage context-efficient.

This skill **complements** `implement-design` — it adds context discipline on top of the code-generation workflow. Do not skip the code-gen skill; run this one alongside it.

## Skill Boundaries

- Triggers when the user asks to read, plan, or implement Figma designs using any Figma MCP tool that返回 design context (`get_design_context` / `get_metadata` / `get_screenshot` 等——不釘 server namespace，因為 `mcp__figma-desktop__*` 與 `mcp__claude_ai_Figma__*` 兩個 connector 都可能命中).
- Does not apply when writing back to Figma (`use_figma`) or when building new Figma files from code — no budget rules needed there.

---

## Rule 1 — Phase Separation (hard rule)

**Plan phase is lightweight. Implement phase is per-component. Never mix.**

| Phase | Goal | Allowed tools | Forbidden |
|---|---|---|---|
| **Plan** | Understand overall structure, slice into tasks | `get_screenshot`, `get_metadata` | `get_design_context` |
| **Implement** | Build a single component/section | `get_design_context` on the selected component only (full-Frame JSON blows the window, see Purpose) | Calling on a whole Frame or Page |

### Required flow

1. Plan phase: screenshot + metadata → produce a task list (save to a markdown file if non-trivial).
2. Between phases: prompt the user to `/clear` or open a new session. Main session should not hold plan artifacts during implementation.
3. Implement phase: per component, repeat `get_design_context` → generate code → validate. After every `get_design_context`, immediately scan annotations (Rule 5).

### Red flags (stop and re-check)

- About to call `get_design_context` but no plan exists yet → go to Plan phase first.
- About to call `get_design_context` on a selection that is a Frame, Page, or Section → narrow to a single component or the smallest meaningful sub-tree.
- About to call `get_design_context` on a complex multi-section page → split into multiple calls, one per section, ideally across sessions.

---

## Rule 2 — Design Tokens Cache (one-time extraction, then read from disk)

**Never call `get_variable_defs` if a cached tokens file exists in the project.**

### Cache location (per repo)

- Check that repo's existing design-token convention first (theme / tokens file); if none, write the first extraction to a sensible location in that repo and treat it as the cache from then on.

### Protocol

1. Before calling `get_variable_defs`, check whether the repo's token cache file (see Cache location above) exists and is non-empty.
2. If it exists: read that file instead of calling MCP. Treat it as source of truth for colors, spacing, typography.
3. If it does NOT exist: call `get_variable_defs` once (a single extraction is enough — the cache file becomes source of truth), then write the output to the cache file as typed constants. Do this before writing any component code.
4. Never re-extract tokens mid-implementation. If a new token is genuinely missing, add it to the cache file in a dedicated call.

### Shape

```typescript
export const color = { primary: '#1890FF', /* ... */ } as const
export const spacing = { xs: 4, sm: 8, md: 16, lg: 24 } as const
export const typography = { /* ... */ } as const
```

---

## Rule 3 — Code Connect Short-Circuit

**If a Figma component has an existing Code Connect mapping to a local React component, skip Figma MCP entirely for that component.**

### Protocol

1. When `get_metadata` reveals an instance of a mapped component, note its `mainComponent` name.
2. Check `components/`, `features/*/components/`, or `proj-app/libs/*/components/` for the mapped React component.
3. If found: emit `<LocalComponent {...propsFromFigma} />` directly. Do NOT call `get_design_context` on the instance — the component's own implementation is the source of truth, not Figma's node data.
4. Only call `get_design_context` when the component is net-new or intentionally being redesigned.

### Why

A mapped component's visual spec is already captured in code. Re-fetching its Figma node data duplicates information and inflates context for no gain.

---

## Rule 4 — Selection Granularity (figma-desktop MCP only)

**The user's Figma selection determines context size. Coach the user on selection before calling.**

### Protocol

- Before any `get_design_context` call, confirm what is selected. If unknown, call `get_metadata` first — its output reveals the current selection scope.
- If the selection is a Frame / Page / Section, instruct the user to narrow selection in Figma to a single component or the smallest meaningful sub-tree.
- Do not proceed with `get_design_context` until selection is component-level.

### Example dialogue

> "Your current Figma selection looks like the entire `Homepage` Frame. Please select just the `ProductCard` component and confirm — I'll then fetch its design context."

---

## Rule 5 — Annotation Extraction (hard rule)

**`get_design_context` returns annotations as `data-annotations="..."` and `data-link-annotations="..."` attributes. These are part of the spec, not optional decoration. Skipping them ships visually-correct but behaviorally-wrong code.**

### What annotations encode

- `data-annotations="Zendesk"` / `"GTM"` / `"關閉後當天不再顯示"` → behavioral spec: which integration wires up, dismissal persistence, trigger events, accessibility hints
- `data-link-annotations="[text](url)"` → designer-specified URL: button targets, form endpoints, external link destinations
- Other free-text annotations → constraints, edge-case behavior, designer notes

### Protocol

1. After EVERY `get_design_context` call, immediately scan for `data-(link-)?annotations` in the response. Run it as the first action, before reading layout/copy.
2. Treat each annotation as a hard requirement equal in weight to layout and text content.
3. When summarizing a component's spec for a plan or implementation, list extracted annotations alongside layout and copy. Do not silently drop them.
4. Annotation conflicts with Asana / Google Doc / Slack thread → annotation wins (consistent with Figma-source-of-truth rule).
5. Component has annotations but implementation ignores them → STOP. The spec is incomplete; do not write code yet.

### Why

Annotations encode the things that aren't visually obvious: which trigger behavior wires up to which UI control, what URL a button goes to, dismissal persistence, accessibility hints. Visual layout alone cannot communicate these.

---

## Pre-flight Checklist (before ANY Figma MCP call)

- [ ] Am I in Plan or Implement phase? (if unclear, default to Plan)
- [ ] If Plan: am I only using `get_screenshot` / `get_metadata`?
- [ ] If Implement: is the user's selection a single component (not a Frame)?
- [ ] Does the repo's design-token cache file already exist? (avoid `get_variable_defs` if so)
- [ ] Is the target component already Code-Connect-mapped? (skip MCP if so)
- [ ] Does the main session already hold prior Figma context? (suggest `/clear` or sub-agent isolation if so)
- [ ] **After each `get_design_context`, did I scan for `data-(link-)?annotations` and treat them as spec?** (Rule 5 — non-negotiable)

---

## Session Hygiene

- After Plan phase completes, write the task list to `docs/` or a plan file. For the `/clear` between phases, see Required flow Step 2.
- For multi-component implementation, prefer the Task tool (sub-agent) per component so main-session context stays small. Sub-agent returns only the file paths and a short summary.
- Never keep `get_design_context` output from a previous component in context while working on the next one.

---

## When This Skill Does Not Apply

- User explicitly asks to ignore context budget for a quick one-off.
- Single tiny component where full-Frame fetch is still under ~5k tokens (rare; do not assume, check with `get_metadata` first).
- Reading `get_screenshot` alone (no node JSON is returned).

---

## Cross-skill: Workflow companion

This skill enforces **HOW** to talk to Figma MCP efficiently (context engineering). It does NOT cover **WHAT** Figma-driven feature work produces (spec / plan / QA artifacts, 5-stage workflow, retro discipline).

If the project has a workflow-side companion skill, invoke both:

- **oldco-shop repo:** [`.claude/skills/figma-to-production/SKILL.md`](../../../Desktop/work/oldco-shop/.claude/skills/figma-to-production/SKILL.md) — 5-stage process (figma-scan → spec/plan → implement → QA → ship), artifact templates, retrospective references. Invoke at first Figma MCP call alongside this skill.
- **Other projects:** check `.claude/skills/` for `figma-*` workflow skills. If none, this skill alone is sufficient.

**Phase split discipline** (resolves the `figma-to-production` Phase 1 "三欄 raw 屬性" requirement vs this skill's `get_design_context`-forbidden Plan phase):
- Plan phase (this skill's tool restriction): `get_metadata` + `get_screenshot` → produce structure / node-ID map / component breakdown in figma-spec.md, leave raw-attr columns as TODO
- Implement phase: per-component sub-agent runs `get_design_context` → fills raw fills/dimensions/typography + scans annotations into the same figma-spec.md (Rule 5 applies)

This hybrid is the canonical split; do not try to satisfy "raw 屬性 in Plan phase" by full-frame `get_design_context` — that violates Rule 1.
