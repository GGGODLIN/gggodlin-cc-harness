---
description: Load the most recent session file from ~/.claude/sessions/ and resume work with full context from where the last session ended.
---

<!-- 本檔在契約測試底下：bash ~/.claude/commands/tests/beads-task-graph.test.sh -->

# Resume Session Command

Load the last saved session state and orient fully before doing any work.
This command is the counterpart to `/save-session`.

## When to Use

- Starting a new session to continue work from a previous day
- After starting a fresh session due to context limits
- When handing off a session file from another source (just provide the file path)
- Any time you have a session file and want Claude to fully absorb it before proceeding

## Usage

```
/resume-session                                                      # loads most recent file in ~/.claude/sessions/
/resume-session 2026-07-08                                           # loads most recent session for that date
/resume-session ~/.claude/sessions/2026-07-08-abc123de-session.tmp   # loads a specific session file
```

## Process

### Step 1: Find the session file

If no argument provided:

1. Check `~/.claude/sessions/`
2. Pick the most recently modified `*-session.tmp` file
3. If the folder does not exist or has no matching files, tell the user:
   ```
   No session files found in ~/.claude/sessions/
   Run /save-session at the end of a session to create one.
   ```
   Then stop.

If an argument is provided:

- If it looks like a date (`YYYY-MM-DD`), search `~/.claude/sessions/` for files matching
  `YYYY-MM-DD-<shortid>-session.tmp` and load the most recently modified variant for that date
- If it looks like a file path, read that file directly
- If not found, report clearly and stop

### Step 2: Read the entire session file

Read the complete file. Do not summarize yet.

### Step 2.5: Also read the owning-project STATE.md if present (handoff layer 2)

The `.tmp` is global; STATE.md is the project-local projection. Resolve owning project from the loaded session itself before considering cwd：

1. 解析 session file 的 `Project` 欄；其中有唯一絕對 path 且該 path 是 git repo → owning dir = 該 repo
2. 使用者明確傳入 session file path 時，**session file 的 Project 優先於 cwd**；即使 cwd 是另一個 git repo，也不得改用 cwd
3. `Project: N/A — pure research` → owning project 明確為無；不以 cwd fallback，不執行 Step 2.7 / 2.8
4. **legacy session 缺絕對 path → unresolved，不以 cwd fallback**：Project 缺失或只有舊格式名稱時，不論 cwd basename / origin 是否同名都不得據此認定 repo；明寫需要絕對 repo path，停止 Step 2.7 / 2.8
5. session path 與 cwd 指向不同 repo → surface `OWNING PROJECT OVERRIDE: <session repo>（cwd=<cwd repo>）`
6. session project unresolved → 不執行 Step 2.7 / 2.8 mutation 或 bd 讀取，STATE.md 標 N/A 並明寫 unresolved

Owning dir 確定後，若 `<owning-dir>/docs/owner/STATE.md` 存在就讀取。

Compare STATE.md against the `.tmp`:
- **Aligned** → STATE.md confirms; note nothing special
- **STATE.md newer / has info not in `.tmp`** → it was patched mid-session after the last save; **trust the newer one**, surface the delta
- **`.tmp` newer** → STATE.md is stale; note it, `.tmp` wins

If no STATE.md (pure research or never created) → just use `.tmp`, no delta line.

### Step 2.7: Run /state-update to catch drift across sessions

If `<owning-dir>/docs/owner/STATE.md` exists, invoke `/state-update <owning-dir>` **before Step 3 briefing**（不再以 Bitbucket origin 為前置條件——`/state-update` 內部對非 Bitbucket repo 會 graceful skip PR check、仍會做 branch / openspec / master compare 等其他 stale-check）。

`/state-update` will read STATE.md, run applicable stale-checks, and propose patch if drift found between sessions. User confirms → Edit STATE.md / User skips → exit. After `/state-update` returns：

若 STATE.md 存在，重新 Read 最終 STATE.md，並從最終內容掃 `<!-- stall:N -->` marker；不得沿用 Step 2.5 的舊快照建立 escalation 清單。任何 N ≥ 3 的 row → 記入 escalation 清單，Step 3 briefing 的 OPEN QUESTIONS / BLOCKERS 之後加一段 `⚠️ STALL:`，每筆固定升級為拍板問句「這條卡 N 輪了：繼續等／改路／砍掉？」＋一句不動作的後果（從 row 內容推導，例：merge gate 不動＝PR 持續 open、後續變更全堵在後面）。不得只照唸 row 內容代替問句。邊界固定：舊 `stall:2` 更新成 `stall:3`，本輪必須提醒；舊 `stall:3` marker 被移除，本輪不得提醒。此機制與 bd 無關，`.beads/` 不存在也照跑。完成最終 stall 掃描後才進 Step 2.8。

- owning project unresolved 或明確為無 → 跳過 Step 2.7 與 Step 2.8，直接進 Step 3；不得再用 cwd 或未解析 path 補跑
- owning dir 已解析、但 STATE.md 不存在 → 只跳過 Step 2.7，仍執行 Step 2.8 後再進 Step 3

### Step 2.8: bd task-graph read（常態接線；2026-08-07 beads trial KEEP 結案）

若 `<owning-dir>/.beads/` 存在，在該 dir 讀兩份全量 JSON：

1. `bd ready --json --readonly --limit 0`：目前可執行的 open 任務
2. `bd list --json --readonly --limit 0 --status deferred`：因 bd 1.1.2 的 `ready` 即使 defer 日期已過仍排除 deferred，需另讀後 client-side 篩選

日期語意固定：取本機 `Asia/Taipei` 今天的日曆日期；RFC3339 `defer_until` 先轉成 `Asia/Taipei` 再取日期，只有 `defer_date <= today` 才列為到期。未到日期與無日期的 deferred 排除；任一 `defer_until` 無法解析時，整份 deferred 來源標成 `defer-parse-failed <id>`，不得把 malformed row 當成未到期或空資料。

分別記錄兩個命令的 success / failure，再將成功來源依 id 去重：

- 有任務 → Step 3 briefing 的 CURRENT STATE 之後**加一段** `🧵 BD READY:`，最多 3 筆，每筆列 id、priority、一句描述，另標 `ready` 或 `defer 到期，待拍板`
- 排序先放與 STATE.md `current_change` / `next_action` 明確相關的任務，再放 ready、defer 到期，最後按 priority、updated_at、id 固定排序
- 超過 3 筆 → 展開前三筆後加 `其餘 N 筆停放中`，不要把全部低優先項倒進 briefing
- 任一命令失敗、JSON/schema 無效或 defer parse 失敗 → 不論另一份有沒有項目，都在同一段加 `⚠️ BD 讀取不完整：<ready-failed / deferred-failed / defer-parse-failed id>`；沿用成功來源，但不得把失敗來源冒充空集合
- 只有 `.beads/` 不存在，或兩個命令都成功且合併後確實為空，才完全跳過此段

完成後接 Step 3。

Rationale: STATE.md drift accumulates across sessions (PR shipped/merged/declined between resume points). `/save-session` only catches drift at session end; `/resume-session` catches drift at session start, aligned with the user's natural "check STATE freshness when reopening" ritual.

### Step 3: Confirm understanding

Respond with a structured briefing in this exact format:

```
SESSION LOADED: [actual resolved path to the file]
STATE.md: [aligned with .tmp / DELTA: <what STATE has that tmp lacks> / stale, .tmp wins / N/A — none]
════════════════════════════════════════════════

PROJECT: [project name / topic from file]

WHAT WE'RE BUILDING:
[2-3 sentence summary in your own words]

CURRENT STATE:
✅ Working: [count] items confirmed
🔄 In Progress: [list files that are in progress]
❌ Broken: [list files that are broken]
🗒️ Not Started: [list planned but untouched]

WHAT NOT TO RETRY:
[list every failed approach with its reason — this is critical]

OPEN QUESTIONS / BLOCKERS:
[list any blockers or unanswered questions]

NEXT STEP:
[exact next step if defined in the file]
[if not defined: "No next step defined — recommend reviewing 'What Has NOT Been Tried Yet' together before starting"]

ENVIRONMENT & SETUP:
[commands / env vars / services from the session file's "Environment & Setup Notes" section, if present]
[if that section was omitted in the source file: "N/A — no setup notes in session file"]

════════════════════════════════════════════════
Ready to continue. What would you like to do?
```

### Step 4: Wait for the user

Do NOT start working automatically. Do NOT touch any files. Wait for the user to say what to do next.

If the next step is clearly defined in the session file and the user says "continue" or "yes" or similar — proceed with that exact next step.

If no next step is defined — ask the user where to start, and optionally suggest an approach from the "What Has NOT Been Tried Yet" section.

---

## Edge Cases

**Multiple sessions for the same date** (`2026-07-08-abc123de-session.tmp`, `2026-07-08-worktree2-session.tmp`):
Load the most recently modified matching file for that date.

**Session file references files that no longer exist:**
Note this during the briefing — "⚠️ `path/to/file.ts` referenced in session but not found on disk."

**Session file is from more than 7 days ago:**
Note the gap — "⚠️ This session is from N days ago (threshold: 7 days). Things may have changed." — then proceed normally.

**User provides a file path directly (e.g., forwarded from a teammate):**
Read it and follow the same briefing process — the format is the same regardless of source.

**Session file is empty or malformed:**
Report: "Session file found but appears empty or unreadable. You may need to create a new one with /save-session."

---

## Example Output

```
SESSION LOADED: /Users/you/.claude/sessions/2026-07-08-abc123de-session.tmp
STATE.md: aligned with .tmp
════════════════════════════════════════════════

PROJECT: my-app — JWT Authentication

WHAT WE'RE BUILDING:
User authentication with JWT tokens stored in httpOnly cookies.
Register and login endpoints are partially done. Route protection
via middleware hasn't been started yet.

CURRENT STATE:
✅ Working: 3 items (register endpoint, JWT generation, password hashing)
🔄 In Progress: app/api/auth/login/route.ts (token works, cookie not set yet)
🗒️ Not Started: middleware.ts, app/login/page.tsx

WHAT NOT TO RETRY:
❌ Next-Auth — conflicts with custom Prisma adapter, threw adapter error on every request
❌ localStorage for JWT — causes SSR hydration mismatch, incompatible with Next.js

OPEN QUESTIONS / BLOCKERS:
- Does cookies().set() work inside a Route Handler or only Server Actions?

NEXT STEP:
In app/api/auth/login/route.ts — set the JWT as an httpOnly cookie using
cookies().set('token', jwt, { httpOnly: true, secure: true, sameSite: 'strict' })
then test with Postman for a Set-Cookie header in the response.

════════════════════════════════════════════════
Ready to continue. What would you like to do?
```

---

## Notes

- Never modify the session file when loading it — it's a read-only historical record
- The briefing format is fixed — do not skip sections even if they are empty
- "What Not To Retry" must always be shown, even if it just says "None" — it's too important to miss
- After resuming, the user may want to run `/save-session` again at the end of the new session to create a new dated file
- STATE.md is handoff layer 2 (project-local projection). resume-session 本身**不 inline 編輯 STATE.md**；只有 Step 2.7 明確 dispatch `/state-update` 且 user 確認其 patch 時，才由 state-update Edit。`.tmp` 始終 read-only
