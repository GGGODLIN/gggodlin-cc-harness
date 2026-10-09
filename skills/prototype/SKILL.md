---
name: prototype
description: Build a throwaway prototype to answer a design question — a single shareable HTML file for state/logic questions (non-developers can drive it), or several structurally different UI variations switchable via URL param. Use when the user wants to sanity-check whether a state model or logic feels right, explore what a UI should look like, or a wayfinder prototype ticket needs resolving — triggers include "做個 prototype", "先試做看看", "這個狀態機感覺對不對", "UI 長怎樣先看幾個版本", "throwaway 驗證一下". Do not use when the design question is already settled or for building production features.
upstream: mattpocock/skills
upstream-path: skills/engineering/prototype/SKILL.md
upstream-pinned: 6654f6b
---

# Prototype

A prototype is **throwaway code that answers a question**. The question decides the shape.

## Pick a branch

Identify which question is being answered — from the user's prompt, the surrounding code, or by asking if the user is around:

- **"Does this logic / state model feel right?"** → [LOGIC.md](LOGIC.md). Build a single shareable HTML file — free-play buttons plus tabbed guided walkthroughs — that pushes the state machine through cases that are hard to reason about on paper, and that a non-developer can drive.
- **"What should this look like?"** → [UI.md](UI.md). Generate several radically different UI variations on a single route, switchable via a URL search param and a floating bottom bar.

The two branches produce very different artifacts — getting this wrong wastes the whole prototype. If the question is genuinely ambiguous and the user isn't reachable, default to whichever branch better matches the surrounding code (a backend module → logic; a page or component → UI) and state the assumption at the top of the prototype.

## Rules that apply to both

1. **Throwaway from day one, and clearly marked as such.** Locate the prototype code close to where it will actually be used (next to the module or page it's prototyping for) so context is obvious — but name it so a casual reader can see it's a prototype, not production. For throwaway UI routes, obey whatever routing convention the project already uses; don't invent a new top-level structure.
2. **Trivial to run.** A UI prototype starts from one command in the project's task runner — `pnpm <name>`, `python <path>`, `bun <path>`, etc. A logic demo is a single HTML file the user double-clicks. Either way, no thinking required to start it.
3. **No persistence by default.** State lives in memory. Persistence is the thing the prototype is _checking_, not something it should depend on. If the question explicitly involves a database, hit a scratch DB or a local file with a clear "PROTOTYPE — wipe me" name.
4. **Skip the polish.** No tests, no error handling beyond what makes the prototype _runnable_, no abstractions. The point is to learn something fast.
5. **Surface the state.** After every action (logic) or on every variant switch (UI), print or render the full relevant state so the user can see what changed.
6. **Capture it when done.** Fold any validated decision into the real code, then capture the prototype itself as a **primary source**: commit it to a throwaway branch, out of main. Record the answer — the verdict and the question it settled — in whatever planning artifact drove the prototype: the wayfinder ticket's Resolution, the openspec change dir's design doc, or the `.scratch` notes for the effort, with a pointer to the throwaway branch. The main branch keeps only the validated decision.

## 踩過的坑

- 2026-08-11 吸收上游 `6bcbcb0`：logic 分支載具從 terminal app 換成單檔 HTML（free-play 按鈕＋tabbed guided walkthrough、非開發者可自行操作），rule 2「One command to run」放寬為「Trivial to run」；LOGIC.md 整檔換上游版（本地原為 pin 原樣、無自訂要保）、description 同步；pin 推進 6bcbcb0。
- 2026-08-02 fork 自 mattpocock/skills `697d4ce`。改動僅 rule 6 capture 落點：上游寫回 issue tracker 的 implementation issue，本 fork 改寫回本地規劃 artifact（wayfinder 票 / openspec change dir / .scratch）；LOGIC.md、UI.md 原樣保留。上游 `agents/openai.yaml`（Codex runtime 介面宣告）不引入。
- 既有簡易 mockup 慣行（含 codex mockup）只覆蓋 UI 分支的單變體版——本 skill 的增量是 logic 分支單檔 HTML、UI 多變體結構性差異＋URL 切換、surface-the-state、capture 協議。產生變體的載具不限（codex 產 mockup 照用），落地與 capture 照本 skill。
