---
name: wayfinder
description: Plan a huge, foggy chunk of work — more than one agent session can hold — as a local map of decision tickets, resolved one at a time until the way to the destination is clear. Use when the user types /wayfinder, or when a requirements gate (e.g. to-spec step 0) reports wayfinder-scale fog and the user explicitly agrees to chart a map. Do not use for well-scoped features (to-spec / to-tickets handle those), single-session work, or without the user's explicit go-ahead.
upstream: mattpocock/skills
upstream-path: skills/engineering/wayfinder/SKILL.md
upstream-pinned: 49dd158
---

<!-- 本檔在契約測試底下：python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->

A loose idea has arrived — too big for one agent session, and wrapped in fog: the way from here to the **destination** isn't visible yet. Wayfinding is about finding that way, not charging at the destination. This skill charts the way as a **map** of **decision tickets** — questions whose resolution is a decision, not slices of a build to execute — and works them one at a time until the route is clear.

The destination varies per effort, and naming it is the first act of charting — it shapes every ticket. It might be a spec to hand off, a decision to lock before planning starts, or a change made in place like a data-structure migration.

## Plan, don't do

Wayfinder is **planning** by default: each ticket resolves a decision, and the map is done when the way is clear — nothing left to decide before someone goes and builds. The pull to just do the work is usually the signal you've reached the edge of the map and it's time to hand off to /to-spec. An effort can override this in the map's **Notes**, but absent that, produce decisions, not deliverables.

## Refer by name

Every ticket has a **name** — its title. In everything the human reads — narration, the map's Decisions-so-far — refer to it by that name wrapped around its file link, never by a bare number or path. A wall of `#42, #43, #44` is illegible; names read at a glance.

## The board (local landing)

The board is a directory, landed by the repo's convention (same adaptive rule as /to-spec and /to-tickets):

- Repo has `openspec/` → `openspec/changes/<effort-slug>/wayfinder/` — so when the map clears, /to-spec lands the spec in the same change dir.
- Otherwise → `.scratch/<effort-slug>/wayfinder/`

```
wayfinder/
├── map.md            (the canonical low-res view)
└── tickets/
    └── NNN-<kebab-name>.md
```

### map.md

The whole effort at low resolution, loaded once per session. Open tickets are **not** listed here — they are found by scanning `tickets/`. The map is an **index**, not a store: a decision lives in exactly one place — its ticket — so the map never restates it, only gists it and links.

```markdown
## Destination

<what reaching the end looks like — the spec, decision, or change this effort is finding its way to. One or two lines; every session orients to it before choosing a ticket.>

## Notes

<domain; skills or conventions every session should consult; standing preferences for this effort>

## Decisions so far

- [<closed ticket name>](tickets/NNN-name.md) — <one-line gist of the answer>

## Not yet specified

<!-- see "Fog of war": in-scope fog you can't ticket yet -->

## Out of scope

<!-- work ruled beyond the destination; never graduates -->
```

### Tickets

Each ticket is one file, `tickets/NNN-<kebab-name>.md`, sized to one agent session:

```markdown
---
status: open | claimed | closed
type: research | prototype | grilling | task
blocked-by: [NNN, NNN]
---

## Question

<the decision or investigation this ticket resolves>

## Resolution

<written on close: the answer, plus links to any assets created>
```

A session **claims** a ticket by setting `status: claimed` **first**, before any work. A ticket is **unblocked** when every ticket in its `blocked-by` is closed; the **frontier** is the open, unblocked tickets — the edge of the known. List it with `scripts/frontier.sh <board-dir>`.

Assets created while resolving (research files, mockups) are linked from the ticket, not pasted in.

## Ticket types

Every ticket is either **HITL** — human in the loop, worked *with* the user — or **AFK**, driven by the agent alone. A HITL ticket only resolves through live exchange; the agent never stands in for the user's side of it (a grilling session that answers its own questions has broken this — the questioning discipline already in context applies).

- **Research** (AFK): reading documentation, third-party APIs, codebases, or the user's own knowledge base to surface a fact a decision waits on. Resolve by dispatching a background research agent per the routing rules already in context; the agent leaves a cited findings file linked from the ticket.
- **Prototype** (HITL): raise the fidelity of the discussion with a cheap, rough, concrete artifact to react to. Resolve via the /prototype skill — it picks the branch (single shareable HTML file for logic/state questions, structurally different UI variants behind a URL param for looks questions) and defines the capture protocol. Use when "how should it look / behave" is the key question.
- **Grilling** (HITL): interview the user — one question at a time, each with a recommended answer; asking several at once is bewildering. Look up facts the environment can answer (filesystem, git, docs) instead of asking; the decisions are the user's — put each one to them and wait, never answering in their place. Propose /grill-me when the decision tree is deep; invoke /domain-modeling when a term turns out fuzzy or a resolution deserves a decision record. The default type.
- **Task** (HITL or AFK): manual work that must happen before a decision can be made — provisioning access, signing up for a service, moving data so its shape can be seen. The one type that *does* rather than decides, earning its place by unblocking a decision. The agent drives it alone where it can; otherwise it hands the user a precise numbered checklist. The resolution records what was done and any resulting facts (credential locations, URLs, counts) later tickets depend on.

## Fog of war

The map is _deliberately_ incomplete: don't chart what you can't yet see. Beyond the live tickets lies the **fog of war** — decisions you can tell are coming but can't yet pin down, because they hang on questions still open. Resolving a ticket clears the fog ahead of it, graduating whatever's now specifiable into fresh tickets — until the way is clear and no tickets remain.

The map's **Not yet specified** section holds that dim view: the suspected question, the area to revisit. **Fog or ticket?** The test is whether you can state the question precisely now — _not_ whether you can answer it now. Ticket when the question is sharp (even if blocked); fog when you can't phrase it that sharply. Don't pre-slice fog into ticket-sized pieces — one patch may graduate into several tickets, or none.

## Out of scope

The destination fixes the scope, so work beyond it is **out of scope** — it isn't fog and doesn't belong in Not-yet-specified. When an existing ticket turns out to sit past the destination, **close it** and leave one line in Out of scope: the gist, why it's out, linking the closed ticket. It stays out of Decisions-so-far, which records the route actually walked. Out-of-scope work never graduates; it returns only if the destination is redrawn, as a fresh effort.

## Invocation

This skill is a local decision-map aid. When the map clears, hand off to the local chain (`to-spec` → `to-tickets` → `implement`).

Two modes. Either way, resolve one ticket per session by default — one decision at a time is what keeps the reasoning sharp and the resolution auditable, not a context-size limit. Batch only when the user asks.

### Chart the map

User invokes with a loose idea, or accepts the proposal after a requirements gate reports wayfinder-scale fog.

0. Confirm the user has explicitly agreed to chart a map (they typed /wayfinder, or said yes to a proposal). If not, propose it with a one-line cost warning — charting is a full session of interviewing — and stop. Done when: explicit user go-ahead is on record.
1. **Name the destination.** Interview per the questioning discipline in context to pin down what this map is finding its way to. Done when: the user has confirmed a one-or-two-line destination.
2. **Map the frontier.** Interview again, **breadth-first**: fan out across the whole space rather than deep on any one thread, surfacing the open decisions and the first steps takeable now. **If this surfaces no fog** — the way is already clear, the journey small enough for one session — stop, tell the user a map isn't needed, and route to /to-spec or direct work instead. Done when: open decisions and fog patches are listed and the user confirms nothing major is missing, or the no-fog exit fired.
3. **Create the board**: map.md with Destination and Notes filled in, Decisions-so-far empty, fog sketched into Not yet specified. Done when: map.md exists with all five sections.
4. **Create the tickets you can specify now**, then wire `blocked-by` in a **second pass** (tickets need numbers before they can reference each other). Everything you can't yet specify stays in the fog. Done when: every sharp question has a ticket file and blocking edges are wired.
5. **Fire the research agents.** For each research ticket, dispatch a background agent per the routing rules in context, pointing its findings file back at the ticket. Done when: every research ticket has an agent dispatched, or a stated reason to defer.
6. **Self-Verify** (mandatory — board written, before presenting). Dispatch an `Agent` with `subagent_type: skill-verify-auditor` (sonnet+low, Read-only, pinned in the agent definition), description containing the marker string `skill-verify:wayfinder` (statistics grep — keep verbatim)。

   **Prompt 要內嵌 board 全文，不要給目錄路徑。** 兩個理由：

   - 那個 auditor 的工具**只有 Read**，沒有 Glob 也沒有 LS——它展不開 `tickets/*.md`，也列不出目錄。2026-09-14 一輪稽核就是這樣壞的：W2／W3 判 FAIL 不是板子有問題，是它找不到票檔（session `0ac623bb`）。
   - 它的定義檔 `agents/skill-verify-auditor.md` 另有輸入契約：**交付物必須全文內嵌，給路徑不算數**。內嵌的文字在派工當下凍結，磁碟上的檔在它讀到之前可能已經變了，那樣稽核的是移動中的目標。

   所以先自己 Read `map.md` 與 `tickets/` 下每一張票，把**內容**貼進 prompt：

   ```
   你是 adversarial 合規審查員。以下是整個 board 的全文；你不需要也不應該去讀任何檔案。
   偏置是「找違規」：無法確認有遵守就判 FAIL。

   ===== map.md =====
   <map.md 全文>

   ===== tickets/<檔名> =====
   <該票全文>

   （每張票一段，全部貼完為止）

   逐條檢查（每條回 PASS / FAIL + 一句證據引述）：
   W1【Destination】map.md 的 Destination 是否 ≤ 2 行且具體（能判斷「到了沒」）？
   W2【票體】每張 ticket 是否都有 status / type / blocked-by 三欄 + ## Question 段，且 Question 是「待決定的問題」而非施工項？
   W3【接線】blocked-by 引用的編號是否都存在？有沒有票引用不存在的票？
   W4【霧不預切】Not yet specified 是否為粗顆粒描述，而非一排已經 ticket 形狀的細項？
   W5【地圖不重述】map.md 是否只 gist + link、沒有把某張票的完整答案貼進來？

   輸出格式（最後一行必須是 verdict 行）：
   W1: PASS|FAIL — <證據>
   ...
   VERDICT: COMPLIANT | VIOLATIONS: <W 編號列表>
   ```

   **派工前的 completeness check（擋在 dispatch 之前，不是事後補救）**：貼進 prompt 的 `===== tickets/` 段數必須 **等於** `tickets/` 下 `.md` 檔的實際數量（自己數一次對上，不要估），且 map.md 全文在內、prompt 裡沒有任何要 auditor 自行讀檔或展開萬用字元的句子。三項有任一項不成立就**先補齊再派**——額度只有一次，派出去才發現貼漏，就沒有第二次機會了。

   **本回合這個 skill 只有一次 auditor 額度**：不論結果如何都不得重派，也不得用 SendMessage 續問同一個 auditor。末尾那行的狀態只能是下列四個之一：

   - 全 PASS → 「🔎 self-verify: COMPLIANT (5/5)」
   - 任一 FAIL 且已修正 → 先修 board 再呈現，標「🔎 self-verify: FIXED_AFTER_AUDIT — W#（抓到什麼、怎麼修的）」，同句明寫「未經第二次獨立稽查」
   - 任一 FAIL 且修不掉 → 標「🔎 self-verify: FAILED — W#（缺口）」，並把該條涵蓋的票或 map 段落刪除或收窄成「未定案」後才呈現，不得當成已驗證的板子交給下一步
   - agent error / timeout / 空輸出 / 格式錯誤 → 標「🔎 self-verify: SKIPPED (agent error)」，不靜默省略

   FAIL 是 auditor 說「材料缺了什麼」而不是指板子的內容問題時（例如它回報某張票沒貼進來），那是**這一步貼漏了**：額度已經用掉，標「🔎 self-verify: SKIPPED (材料不完整，稽核未涵蓋全板)」並在呈現時明說哪幾張票沒進稽核範圍，**不要重派、也不要因此去改 board**。這正是上面 completeness check 要擋在派工前的原因。
7. Stop — charting is one session's work; it hand-resolves nothing (the background research agents are the only work in flight).

### Work through the map

User invokes with a board (or the session resumes one). A named ticket is optional — without one, the agent picks the next decision, not the user's priorities.

1. Load **map.md** only — the low-res view, not every ticket body. Done when: destination and Notes are in context.
2. Choose the ticket: the user-named one, else the first frontier ticket from `scripts/frontier.sh`. **Claim it** (`status: claimed`) before any work. Done when: exactly one ticket is claimed.
3. Resolve it by its type — zoom into related or closed tickets on demand; consult whatever the map's Notes name. HITL tickets resolve only through live exchange with the user.
4. Record: write `## Resolution` on the ticket, set `status: closed`, append one line to the map's Decisions-so-far (name wrapping the link + one-line gist). Done when: all three writes exist.
5. Update the frontier: create-then-wire any newly surfaced tickets; graduate fog the answer made specifiable (clearing each graduated patch from Not yet specified); rule mis-scoped tickets out of scope; update or delete tickets the decision invalidated. Done when: the board reflects the new state of knowledge.
6. Stop after one ticket. When the frontier is empty and no fog remains, the map is clear: **hand off, don't build** — run /to-spec to collapse the map's linked decisions into a spec, then /to-tickets and /implement as usual. Skipping to-spec throws the linked detail away.

## 踩過的坑

- 2026-08-02 fork 自 mattpocock/skills `2602257`。上游是 issue-tracker 版（native blocking / assignee claim / wayfinder:map label）；本 fork 落本地檔案板，tracker 能力（frontier 視覺化、多人併發 claim）以 frontier.sh + status 欄近似，多人真併發需求出現時再評 tracker 版。
