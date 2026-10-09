---
description: Save current session state to a dated file in ~/.claude/sessions/ so work can be resumed in a future session with full context.
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/beads-task-graph.test.sh && bash ~/.claude/commands/tests/save-session-self-verify.test.sh；另有回歸考卷 ~/.claude/evals/save-session/evals/eval.yaml（`cd ~/.claude/evals/save-session && skill-up run evals/eval.yaml`）；python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->

# Save Session Command

Capture everything that happened in this session — what was built, what worked, what failed, what's left — and write it to a dated file so the next session can pick up exactly where this one left off.

## When to Use

- End of a work session before closing Claude Code
- Before hitting context limits (run this first, then start a fresh session)
- After solving a complex problem you want to remember
- Any time you need to hand off context to a future session

## Process

### Step 1: Gather context

Before writing the file, collect:

- Read all files modified during this session (use git diff or recall from conversation)
- Review what was discussed, attempted, and decided
- Note any errors encountered and how they were resolved (or not)
- Check current test/build status if relevant

### Step 2: Create the sessions folder if it doesn't exist

Create the canonical sessions folder in the user's Claude home directory:

```bash
mkdir -p ~/.claude/sessions
```

### Step 3: Write the session file

Create `~/.claude/sessions/YYYY-MM-DD-<short-id>-session.tmp` using today's actual date and a short-id satisfying:

- Allowed characters: lowercase `a-z`, digits `0-9`, hyphens `-`
- Minimum length: 8 characters
- No uppercase letters, no underscores, no spaces

Valid examples: `abc123de`, `a1b2c3d4`, `frontend-worktree-1`
Invalid examples: `ABC123de` (uppercase), `short` (under 8 chars), `test_id1` (underscore)

Full valid filename example: `2026-07-08-abc123de-session.tmp`

### Step 4: Populate the file with all sections below

Write every section honestly. Do not skip sections — write "Nothing yet" or "N/A" if a section genuinely has no content. An incomplete file is worse than an honest empty section.

`Project` 是後續 resume 的 repo 身分鍵：有 owning git repo 時，**Project 欄必須寫入 owning git repo 的絕對路徑**，格式為 `<human-readable name> — <absolute repo path>`；純研究且沒有 owning project 時固定寫 `N/A — pure research`。不得只寫 project name。若應有 project 但無法唯一解析絕對路徑，先完成事實查找；仍無法解析才向 user 收斂，不得用 cwd 猜測後寫檔。

**引用不重複**：spec / plan / ADR / commit message / diff 已載明的內容不貼進 session 檔——寫 path 或 commit hash 引用即可（resume 時自取），session 檔只寫 artifact 之外的脈絡。

**Exact-form constraint literals（逐字保存，hard rule）**：session 中使用者給過的精確值——connection string / DSN、port、hostname、env var 值、token 名、檔案路徑、完整命令列含 flags、ID、seed、version pin——寫進任何 section 時必須**逐 byte 原樣保存**（backticks、標點、兩個只差 port 的 DSN 要分開各留一份）。摘要成「使用者給了一個 DB 設定」等於把值弄丟——這些值存在的意義就是下個 session 逐字召回。不確定算不算精確值 → 當作是，照抄。逐字之外還有**擺位**：resume 起手就要用的識別碼（下一步的命令 / 檔案路徑 / 錯誤碼）優先落在結構化欄位（Current State of Files 表 / Exact Next Step / Environment），不要只埋在敘述段——敘述會被略讀，欄位不會。**唯一例外：secret 值本身**（API key / password / token 值 / private key / DSN 內嵌的密碼段）不逐字保存——改寫指位（env var 名 / `.env` 路徑＋行 / keychain 條目名），下個 session 照指位自取；同一值的非 secret 部分（host / port / db 名）照舊原樣。理由：session 檔會被轉發接手（resume-session 明文支援），secret 原文落檔 = 外洩面。

**Must-keep（使用者明示保留，語意判準）**：回顧本 session 對話，找出使用者曾以交代語氣明確要求保留／之後要用的具體內容——判斷看語意、不看字面用詞（使用者不一定會說「記住」二字）。Agent 自認重要但使用者沒交代的不算：豁免區一通膨，壓縮就名存實亡。命中的內容寫進「Must-Keep」section（原文逐字、每條附一句出處脈絡），該 section 在後續任何摘要／投影（含 STATE.md）不得壓縮改寫。做法是逐句掃使用者訊息裡的交代語氣句、每句明判入或不入——內容已寫進其他 section（What WORKED / Environment 等）不豁免，仍要在 Must-Keep 收一份：分散提及不等於保全標記，resume 時只有這區保證不被壓。有交代句未判 = 本步未完成。寫完接 Step 4.5。

### Step 4.5: Self-Verify（mandatory — 檔案寫完後、呈給使用者前）

Session 檔寫完後，**必須**派一個 verify subagent 檢查檔案是否遵守本 command 的規矩，才進 Step 5。唯二例外是下方兩條降級路徑（subagent 失敗、政策禁派 Agent）。

Dispatch 規格：

- `Agent` tool、`subagent_type: skill-verify-auditor`（sonnet+low、tools 僅 Read，定義檔釘死）
- description 固定含 marker 字串 `skill-verify:save-session`（採用率統計 grep 用，不要改字）
- prompt 給 session 檔的絕對路徑（verify agent 自己 Read）+ 下方 template 全文

Verify prompt template（原文嵌入、`{path}` 換成檔案絕對路徑）：

```
你是 adversarial 合規審查員。Read {path}，檢查這份 session 檔是否遵守 save-session command 的規矩。偏置是「找違規」：無法確認有遵守就判 FAIL，不要善意推定。

逐條檢查（每條回 PASS / FAIL + 一句證據引述）：

R1【檔名】檔名是否符合 `YYYY-MM-DD-<short-id>-session.tmp`，short-id 全小寫 a-z0-9- 且 ≥ 8 字元？（short-id 可以是人類可讀的摘要式命名；只依字元集合與長度判斷，不要求隨機 token。缺 short-id 或含大寫 / underscore / 空白 = FAIL）

R2【section 完整】必要 section 是否全在：What We Are Building / Task Constraints / Must-Keep / What WORKED / What Did NOT Work / What Has NOT Been Tried Yet / Current State of Files / Decisions Made / Blockers & Open Questions / Exact Next Step？空 section 是否明寫 "Nothing yet" / "N/A" / "None stated" 類句子而非缺段？語意等效的空內容句子 = PASS；`Environment & Setup Notes` 是合法選填 section，不得因此 FAIL。

R3【證據紀律】What WORKED 每項是否附具體證據（confirmed by / 證據：…）？What Did NOT Work 每項是否寫出確切失敗原因（錯誤訊息 / 具體機制），而非「didn't work」「沒成功」類空話？

R4【exact-form literals】檔內引用的精確值（命令列 / 路徑 / DSN / port / version pin / ID）是否以原樣形式保存（backtick 或 code block 包、含完整 flags）？出現「使用者給了一個 XX 設定」「某個命令」類摘要化句子 = FAIL。

R5【Exact Next Step 可執行】Next Step 是否具體到恢復時零思考可起手（指名檔案 / 指令 / 動作）？「繼續做」「接著處理」類 = FAIL；明寫「Next step not determined — review …」= PASS。

R6【secret 形跡】本欄是封閉列舉：只有檔內出現下列 secret 原文 pattern 才 FAIL——`sk-` / `ghp_` / `AKIA` / `xoxb` / `password=` / `://user:pass@` 內嵌密碼形式 / PEM block；不得類推清單外形狀。sha256 內容雜湊、UUID、spreadsheet／document ID 未命中上述 pattern 時固定 PASS。命中值改寫指位：env var 名 / `.env` 路徑＋行 / keychain 條目名。secret 值已遮蔽或改為佔位符時，非 secret 部分保留原樣 = PASS；不得因 user / host / port / db name 仍存在而 FAIL。

輸出格式（固定，最後一行必須是 verdict 行）：

R1: PASS|FAIL — <一句證據>
R2: PASS|FAIL — <一句證據>
R3: PASS|FAIL — <一句證據>
R4: PASS|FAIL — <一句證據>
R5: PASS|FAIL — <一句證據>
R6: PASS|FAIL — <一句證據>
VERDICT: COMPLIANT | VIOLATIONS: <R 編號逗號列表>
```

Verify 結果處理。**本回合這個 command 只有一次 auditor 額度**：不論結果如何都不得重派，也不得用 SendMessage 續問同一個 auditor。末尾那行的狀態只能是下列四個之一：

- 全 PASS → 進 Step 5，訊息末尾附一行「🔎 self-verify: COMPLIANT (6/6)」
- 任一 FAIL 且已修正 → **先修檔案再進 Step 5**（改名 / 補 section / 補證據 / 還原 literal），修完不重驗、在 Step 5 訊息末尾如實列出「🔎 self-verify: FIXED_AFTER_AUDIT — R4（…）」並明寫「未經第二次獨立稽查」。修 R6（secret 形跡）時只把 secret 段本身改指位，同一值的非 secret 部分（host / port / db 名 / user 名）必須保留原樣——整行刪掉或整值改「請自 .env 取得」是把 R6 修成 R4 違規
- 任一 FAIL 且修不掉 → 標「🔎 self-verify: FAILED — R#（缺口）」，並把無法佐證的那幾條從檔案刪除或收窄後才進 Step 5，不得留著不實內容
- Verify subagent 失敗（timeout / 空輸出 / 格式錯誤 / agent error）→ 照進 Step 5、末尾標「🔎 self-verify: SKIPPED (agent error)」，不要靜默省略
- 政策禁派 Agent（system prompt 出現 `Do not call the AgentTool unless the user requested it` 一類禁令）→ 改由 main 依同一份 rubric inline 逐條判，末尾照常標 self-verify 行並加註「inline 執行」，同時寫明降級原因。降級只換執行者、不換標準：每條仍要判、仍要附證據句，判不出來標 FAIL，不得整段省略或改標 SKIPPED

R4 的已知限制：verify agent 沒有對話 context，只能驗「格式面」（有沒有 backtick 原樣保存的形跡、有沒有摘要化句子），驗不了「有沒有漏抄某個使用者給過的值」——漏抄仍靠 Step 5 使用者過目把關。

### Step 5: Show the file to the user

After writing, display the full contents and ask:

```
Session saved to [actual resolved path to the session file]

Does this look accurate? Anything to correct or add before we close?
```

Must-Keep section 非空時，過目訊息中把該清單明列出來請使用者確認（標錯的當場刪）；超過 5 條時附一句「must-keep 已達 N 條，建議回收不再需要的」——過目是防 marker 通膨的第二道保險。

Wait for confirmation. Make edits if requested.

### Step 6: Sync STATE.md via /state-update (handoff layer 2)

`.tmp` is the global superset and the source of truth. STATE.md is its **project-local concise projection** — same source, NOT a separate merge, NOT the full `.tmp` context.

**Resolve the OWNING PROJECT dir from the session file, not from cwd:**

1. `Project` 欄含唯一絕對 git repo path → owning dir = 該 path；重新驗證 `.git` 存在
2. `Project: N/A — pure research` → **SKIP STATE.md entirely**。Never write STATE.md under the `~/Desktop/projects/` root. The `.tmp` alone is the handoff
3. `Project` 欄缺絕對 path、path 無效或有多個候選 → 不用 cwd 補猜；先修正 session file 的 Project 欄並讓 user 過目，再進行 STATE sync

**For a resolved owning dir, invoke `/state-update <owning-dir>`** to handle STATE.md mutation. `/state-update` owns:

- create from template if STATE.md missing (with `docs/owner/` gitignore handling)
- incremental update if exists (Edit only changed sections, do NOT rewrite the whole file)
- PR stale-check via Bitbucket API (auto-skip on non-Bitbucket repos / API failure)
- ship/merge case → redirect user to `/state-archive`

**Boundary**: this step resolves the OWNING dir; `/state-update` owns the mutation. Do NOT edit STATE.md inline here. bd（beads）支線捕捉也由 `/state-update` Step 9 統一負責——本 command 不自行跑任何 `bd` 指令（避免重複記帳）。

`/state-update` 返回後，驗收其最後一個 `BD_CAPTURE` 收據：只接受 `created`、`existing`、`not-needed`、`skipped-error`、`not-evaluated` 五種終態。找不到收據時不要自行補跑或建立 bead，記為 `BD_CAPTURE: not-evaluated beads 捕捉未驗證：state-update 未回傳收據`。pure research 因沒有 owning project 跳過 Step 6 時，記為 `BD_CAPTURE: not-evaluated no owning project`。完成（或確定跳過）後接 Step 6.5。

### Step 6.5: 摩擦盤點（通用摩擦協議）

回顧本 session 的執行型摩擦（卡住、繞路、重複踩坑、規則沒被遵守；含 pure research session）並分流落點：

1. 有主（屬於某個 skill / command / agent / hook）→ append 該機制目錄的 `friction-log.md`
2. 無主（工作流級）→ append `~/.claude/friction/workflow-general.md`
3. 盤點結果一律在 Step 7 最終訊息帶一行（放 `BD_CAPTURE` 行之前）：`摩擦盤點：無` 或 `摩擦盤點：N 筆 → <落點檔>`——無摩擦也明寫、不靜默跳過，friction-log 本身則無摩擦不留紀錄

格式與門檻見 `~/.claude/friction/PROTOCOL.md`，本步只 append 不折入（折入由 sweep 提醒後使用者拍板）。

### Step 7: Final handoff receipt

STATE sync 與 Step 6.5 摩擦盤點完成後才送最終狀態訊息；**最終訊息最後一行**固定放且只放一個 `BD_CAPTURE` 終態：state-update 有合法收據就逐字轉貼，沒有就用上一段的 `not-evaluated`。該行之後不得再加 self-verify、解釋或問句，讓呼叫端可以固定擷取最後一行。

STATE.md stays concise: frontmatter + key decisions + blockers + exact next step. The full worked/failed/files context lives in `.tmp` only.

精簡投影時 exact-form literals 不豁免：Resume Notes / Recent Decisions 裡若引用到使用者給過的精確值（命令列 / 路徑 / port 等），照抄 `.tmp` 的逐字版本，不要在投影時改寫。

---

## Session File Format

```markdown
# Session: YYYY-MM-DD

**Started:** [approximate time if known]
**Last Updated:** [current time]
**Project:** [project name — absolute git repo path / N/A — pure research]
**Topic:** [one-line summary of what this session was about]

---

## What We Are Building

[1-3 paragraphs describing the feature, bug fix, or task. Include enough
context that someone with zero memory of this session can understand the goal.
Include: what it does, why it's needed, how it fits into the larger system.]

---

## Task Constraints (must survive into every future session)

[使用者在任務開場或途中講過的限制——「不要動 X」「必須相容 Y」「只改 Z 範圍」。
這些最容易在長 session 後段被忘掉，resume 時又最致命，所以獨立成段放前面，
不與過程敘述混寫。逐字保留使用者原話中的精確範圍。]

- [constraint]

If none stated: "None stated."

---

## Must-Keep（使用者明示要保留的內容）

[使用者曾明確交代要保留／之後要用的具體內容。語意判斷、不限字面用詞。
原文逐字保留，每條附一句出處脈絡。Agent 自判重要的不放這裡。]

- [content] — 出處：[使用者在什麼脈絡交代的]

If none: "None."

---

## What WORKED (with evidence)

[List only things that are confirmed working. For each item include WHY you
know it works — test passed, ran in browser, Postman returned 200, etc.
Without evidence, move it to "Not Tried Yet" instead.]

- **[thing that works]** — confirmed by: [specific evidence]
- **[thing that works]** — confirmed by: [specific evidence]

If nothing is confirmed working yet: "Nothing confirmed working yet — all approaches still in progress or untested."

---

## What Did NOT Work (and why)

[This is the most important section. List every approach tried that failed.
For each failure write the EXACT reason so the next session doesn't retry it.
Be specific: "threw X error because Y" is useful. "didn't work" is not.]

- **[approach tried]** — failed because: [exact reason / error message]
- **[approach tried]** — failed because: [exact reason / error message]

If nothing failed: "No failed approaches yet."

---

## What Has NOT Been Tried Yet

[Approaches that seem promising but haven't been attempted. Ideas from the
conversation. Alternative solutions worth exploring. Be specific enough that
the next session knows exactly what to try.]

- [approach / idea]
- [approach / idea]

If nothing is queued: "No specific untried approaches identified."

---

## Current State of Files

[Every file touched this session. Be precise about what state each file is in.]

| File              | Status         | Notes                      |
| ----------------- | -------------- | -------------------------- |
| `path/to/file.ts` | ✅ Complete    | [what it does]             |
| `path/to/file.ts` | 🔄 In Progress | [what's done, what's left] |
| `path/to/file.ts` | ❌ Broken      | [what's wrong]             |
| `path/to/file.ts` | 🗒️ Not Started | [planned but not touched]  |

If no files were touched: "No files modified this session."

---

## Decisions Made

[Architecture choices, tradeoffs accepted, approaches chosen and why.
These prevent the next session from relitigating settled decisions.]

- **[decision]** — reason: [why this was chosen over alternatives]

If no significant decisions: "No major decisions made this session."

---

## Blockers & Open Questions

[Anything unresolved that the next session needs to address or investigate.
Questions that came up but weren't answered. External dependencies waiting on.]

- [blocker / open question]

If none: "No active blockers."

---

## Exact Next Step

[If known: The single most important thing to do when resuming. Be precise
enough that resuming requires zero thinking about where to start.]

[If not known: "Next step not determined — review 'What Has NOT Been Tried Yet'
and 'Blockers' sections to decide on direction before starting."]

---

## Environment & Setup Notes

[Only fill this if relevant — commands needed to run the project, env vars
required, services that need to be running, etc. Skip if standard setup.]

[If none: omit this section entirely.]
```

---

## Example Output

```markdown
# Session: 2026-07-08

**Started:** ~2pm
**Last Updated:** 5:30pm
**Project:** my-app — /Users/you/code/my-app
**Topic:** Building JWT authentication with httpOnly cookies

---

## What We Are Building

User authentication system for the Next.js app. Users register with email/password,
receive a JWT stored in an httpOnly cookie (not localStorage), and protected routes
check for a valid token via middleware. The goal is session persistence across browser
refreshes without exposing the token to JavaScript.

---

## Task Constraints (must survive into every future session)

- 不動既有的 Prisma schema（user 明示 migration 已鎖）
- Token 一律 httpOnly cookie，不落 localStorage

---

## Must-Keep（使用者明示要保留的內容）

- `JWT_SECRET` 放 `.env.local` 第 3 行、不進 git — 出處：使用者設定 env 時交代「這個位置之後會用到」

---

## What WORKED (with evidence)

- **`/api/auth/register` endpoint** — confirmed by: Postman POST returns 200 with user
  object, row visible in Supabase dashboard, bcrypt hash stored correctly
- **JWT generation in `lib/auth.ts`** — confirmed by: unit test passes
  (`npm test -- auth.test.ts`), decoded token at jwt.io shows correct payload
- **Password hashing** — confirmed by: `bcrypt.compare()` returns true in test

---

## What Did NOT Work (and why)

- **Next-Auth library** — failed because: conflicts with our custom Prisma adapter,
  threw "Cannot use adapter with credentials provider in this configuration" on every
  request. Not worth debugging — too opinionated for our setup.
- **Storing JWT in localStorage** — failed because: SSR renders happen before
  localStorage is available, caused React hydration mismatch error on every page load.
  This approach is fundamentally incompatible with Next.js SSR.

---

## What Has NOT Been Tried Yet

- Store JWT as httpOnly cookie in the login route response (most likely solution)
- Use `cookies()` from `next/headers` to read token in server components
- Write middleware.ts to protect routes by checking cookie existence

---

## Current State of Files

| File                             | Status         | Notes                                           |
| -------------------------------- | -------------- | ----------------------------------------------- |
| `app/api/auth/register/route.ts` | ✅ Complete    | Works, tested                                   |
| `app/api/auth/login/route.ts`    | 🔄 In Progress | Token generates but not setting cookie yet      |
| `lib/auth.ts`                    | ✅ Complete    | JWT helpers, all tested                         |
| `middleware.ts`                  | 🗒️ Not Started | Route protection, needs cookie read logic first |
| `app/login/page.tsx`             | 🗒️ Not Started | UI not started                                  |

---

## Decisions Made

- **httpOnly cookie over localStorage** — reason: prevents XSS token theft, works with SSR
- **Custom auth over Next-Auth** — reason: Next-Auth conflicts with our Prisma setup, not worth the fight

---

## Blockers & Open Questions

- Does `cookies().set()` work inside a Route Handler or only in Server Actions? Need to verify.

---

## Exact Next Step

In `app/api/auth/login/route.ts`, after generating the JWT, set it as an httpOnly
cookie using `cookies().set('token', jwt, { httpOnly: true, secure: true, sameSite: 'strict' })`.
Then test with Postman — the response should include a `Set-Cookie` header.
```

---

## Notes

- Each session gets its own file — never append to a previous session's file
- The "What Did NOT Work" section is the most critical — future sessions will blindly retry failed approaches without it
- If the user asks to save mid-session (not just at the end), save what's known so far and mark in-progress items clearly
- The file is meant to be read by Claude at the start of the next session via `/resume-session`
- Use the canonical global session store: `~/.claude/sessions/`
- 檔名格式 `YYYY-MM-DD-<short-id>-session.tmp` 是唯一合法格式（見 Step 3）
