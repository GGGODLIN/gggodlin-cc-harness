---
name: domain-modeling
description: Build and sharpen a project's domain model. Use when the user wants to pin down domain terminology or a ubiquitous language — triggers include "定義領域詞彙", "統一術語", "這兩個詞是不是同一件事", "domain model", "ubiquitous language", "記一下這個架構決策" — when a term keeps being used ambiguously or two words fight over one concept, when an architectural decision needs recording, or when another skill (wayfinder grilling / to-spec) needs the domain vocabulary maintained. Do not use for merely reading existing glossary entries — that's a one-line lookup, not this skill.
upstream: mattpocock/skills
upstream-path: skills/engineering/domain-modeling/SKILL.md
upstream-pinned: 4588b32ecab9ecc9fc8cc6b6c5e7d675b6004b0d
---

# Domain Modeling

Actively build and sharpen the project's domain model as you design. This is the *active* discipline — challenging terms, inventing edge-case scenarios, and writing the glossary and decisions down the moment they crystallise. (Merely *reading* the glossary for vocabulary is not this skill — that's a one-line habit any skill can do. This skill is for when you're changing the model, not just consuming it.)

## File structure

Domain knowledge lands in the repo's `openspec/` tree — the same convention the spec pipeline uses:

```
openspec/
├── glossary.md       ← the ubiquitous language (this skill owns it)
└── decisions/
    ├── 0001-some-decision.md
    └── 0002-another-decision.md
```

Create files lazily — only when there is something to write. No `openspec/` dir yet? Create it with just the file being written; the rest of the tree grows when other skills need it. If the repo already keeps decision files elsewhere under `openspec/` (a different subdir name, an architecture doc), match the existing convention instead of creating a parallel one.

## During the session

### Challenge against the glossary

When the user uses a term that conflicts with the existing language in `openspec/glossary.md`, call it out immediately. "Your glossary defines 'cancellation' as X, but you seem to mean Y — which is it?"

### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You're saying 'account' — do you mean the Customer or the User? Those are different things."

### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible — which is right?"

### Update the glossary inline

When a term is resolved, update `openspec/glossary.md` right there. Don't batch these up — capture them as they happen. Use the format in [GLOSSARY-FORMAT.md](./GLOSSARY-FORMAT.md).

The glossary should be totally devoid of implementation details. Do not treat it as a spec, a scratch pad, or a repository for implementation decisions. It is a glossary and nothing else.

### Offer ADRs sparingly

Only offer to create a decision record when all three are true:

1. **Hard to reverse** — the cost of changing your mind later is meaningful
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons

If any of the three is missing, skip the ADR. Use the format in [ADR-FORMAT.md](./ADR-FORMAT.md).

## 踩過的坑

- oldco-shop 既有 `openspec/decisions/0001-0010` 為四位數編號、單段落體——寫新決策時照 ADR-FORMAT 的「沿既有慣例」規則直接續編，不改既有檔。
- 2026-08-06 SSOT 界線（使用者拍板）：proj 系 repo 的 codebase-aliases 管「code 實體的別名」、glossary 管「領域概念詞」，互不重述、glossary 詞條可指向 alias。另有全域層 `~/.claude/glossary.md`（跨專案個人用語、wait-what 回收迴路進料）——repo 領域詞不放那裡、本 skill 不擁有它。
