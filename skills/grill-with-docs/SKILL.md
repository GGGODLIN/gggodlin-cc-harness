---
name: grill-with-docs
description: "Grilling session that stress-tests a plan against the project's documented domain model, recording terms and decisions as they crystallise. Wrapper — runs grill-me then domain-modeling. Use when user wants to stress-test a plan against their project's language and documented decisions (openspec/glossary.md, openspec/decisions/). Do not use for: plan grilling with no documentation to maintain (grill-me alone), or terminology/ADR work with no plan to grill (domain-modeling alone)."
upstream: mattpocock/skills
upstream-path: skills/engineering/grill-with-docs/SKILL.md
upstream-pinned: 447ca70
---

Call the Skill tool twice, for "grill-me" and "domain-modeling".

Run the grilling per grill-me's rules; as terms and decisions crystallise during the session, record them per domain-modeling's rules (openspec/glossary.md inline, decisions sparingly). Do not enact the plan until the user confirms shared understanding.

## 踩過的坑

- 2026-08-18 塌成 wrapper：原全文停在上游 2026-05 版、pin `ed37663` 從未真確（該 commit 只動 to-tickets）——「pin 指向 wrapper 化之後、內容停在 wrapper 化之前」讓週雷達永遠報綠。全文能力已由本機 grill-me（rounds 版）＋ domain-modeling（openspec 落點）覆蓋；CONTEXT.md / docs/adr/ 舊慣例與 2026-08-02 openspec 拍板矛盾，隨塌併移除本目錄 CONTEXT-FORMAT.md、ADR-FORMAT.md（domain-modeling 自帶 GLOSSARY-FORMAT.md / ADR-FORMAT.md 為準）。
