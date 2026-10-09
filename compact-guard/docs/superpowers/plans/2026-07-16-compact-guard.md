# Compact Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and install a local compact guard that preserves high-salience source excerpts across Claude Code, ccp-gpt, Codex CLI, and local Codex Desktop compaction.

**Architecture:** One dependency-free Node.js core consumes hook JSON from stdin. Two transcript adapters normalize Claude and Codex JSONL into the same message shape; `PreCompact` writes a private per-session checkpoint, `SessionStart(source=compact)` injects the bounded recovery packet, and `PostCompact` appends content-free audit metrics. An idempotent installer merges three handlers into both user-level hook files without replacing existing handlers.

**Tech Stack:** Node.js 24, ES modules, `node:test`, built-in `fs`, `readline`, `crypto`, and `os` modules.

## Global Constraints

- Support Claude Code, ccp-gpt, Codex CLI, and local Codex Desktop; exclude Codex Cloud.
- Keep one shared core and exactly two transcript adapters: `claude` and `codex`.
- Use only Node.js built-ins and add no runtime or development dependencies.
- Preserve all existing hooks and make install/uninstall idempotent.
- Treat transcript text as untrusted evidence; never inject tool output, system instructions, developer instructions, thinking blocks, or subagent transcripts.
- Classify pure Claude sidechain transcripts and Codex metadata with a subagent source or non-empty `parent_thread_id` as subagent scope; all three compact hooks must no-op before state or audit access.
- Treat any non-empty hook `agent_id` as subagent scope. Compact Claude `SessionStart` and both vendors' `PostCompact` must also no-op when the current `transcript_path` is null, unreadable, or lacks positive root-session evidence. Codex compact `SessionStart` is the sole exception: the [Codex 0.144.4 hook runtime](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/hook_runtime.rs#L103-L128) dispatches `SessionStart` only to root sessions and converts thread-spawn children to `SubagentStart`, so it may recover from the validated same-vendor, same-session checkpoint when the nullable path is absent or unreadable. Codex [queues the compact start source](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/session/mod.rs#L3070-L3073) and [dispatches it before the next user turn](https://github.com/openai/codex/blob/rust-v0.144.4/codex-rs/core/src/session/turn.rs#L186-L192) rather than immediately after compaction.
- Redact likely credentials before checkpoint persistence and injection.
- Store checkpoint files with mode `0600` under `~/.compact-guard/checkpoints/<vendor>/` and audit JSONL without conversation text, raw session IDs, or full transcript paths under `~/.compact-guard/audit.jsonl`.
- Cap injected recovery context at 8,500 characters, below Claude Code's 10,000-character inline-context threshold.
- Put stable recovery instructions before dynamic session identifiers and counts.
- `PreCompact` fails closed when it cannot create a valid checkpoint; `PostCompact` remains non-blocking; `SessionStart(source=compact)` does not depend on `PostCompact` ordering.
- During the first seven-day trial, do not override either product's native compact prompt.
- Generated JavaScript contains no comments, uses two-space indentation, ES modules, pure functions where practical, `??` for value fallback, and `JSON.stringify()` for console output.
- Every behavior change follows red-green-refactor and every completion claim requires fresh verification output.

---

### Task 1: Transcript normalization and evidence selection

**Files:**
- Create: `package.json`
- Create: `src/text.mjs`
- Create: `src/transcript.mjs`
- Create: `test/fixtures/claude.jsonl`
- Create: `test/fixtures/codex.jsonl`
- Create: `test/text.test.mjs`
- Create: `test/transcript.test.mjs`

**Interfaces:**
- Produces: `extractMessages({ vendor, transcriptPath }) -> Promise<{ messages, transcriptHash, recordCount }>`
- Produces: `selectEvidence(messages, options?) -> EvidenceEntry[]`
- Produces: `renderRecoveryPacket(checkpoint, options?) -> string`
- Produces: `redactSecrets(text) -> string`
- `EvidenceEntry` fields: `id`, `role`, `category`, `timestamp`, `text`, `hash`, `index`.

- [ ] **Step 1: Write failing transcript tests**

Cover these exact behaviors:

- Claude extracts only top-level user strings and assistant `text` blocks.
- Claude aggregates split assistant records by `message.id`, then `requestId`, then `uuid`.
- Claude skips `tool_result`, `thinking`, `tool_use`, compact summaries, meta messages, sidechains, and tool-originated user records.
- Claude rejects an entire pure-sidechain transcript with a fixed subagent error, while a main transcript containing only some sidechain records remains eligible.
- Codex extracts human user text only from top-level `event_msg` records with `payload.type="user_message"` and a non-empty `payload.message`; assistant text comes only from top-level `response_item.payload.type="message"` records with `role="assistant"` and `output_text` blocks.
- Codex rejects every `response_item` with `role="user"` because real records mix human text with internal `recommended_plugins`, `AGENTS.md`, and `environment_context` injections; it also skips developer/system messages, `compacted.replacement_history`, and unknown Desktop-only records.
- Codex rejects the entire transcript with the same fixed subagent error when `session_meta.payload.source.subagent` exists or `parent_thread_id` is non-empty.
- Malformed complete JSONL lines are counted and skipped; a final unterminated partial line is deferred rather than counted as malformed; a file with no valid conversation messages rejects.
- The parser returns a SHA-256 hash and total record count.

- [ ] **Step 2: Run transcript tests and verify RED**

Run: `node --test test/transcript.test.mjs`

Expected: FAIL because `src/transcript.mjs` does not exist.

- [ ] **Step 3: Implement minimal transcript adapters**

Use `readline.createInterface` to stream the file. Normalize all accepted text to:

```js
{
  id: "stable-source-id",
  role: "user",
  timestamp: "2026-07-16T00:00:00.000Z",
  text: "source text",
  index: 0
}
```

- [ ] **Step 4: Run transcript tests and verify GREEN**

Run: `node --test test/transcript.test.mjs`

Expected: all transcript tests pass with zero warnings.

- [ ] **Step 5: Write failing evidence-selection tests**

Cover known-good, known-bad, and boundary fixtures:

- Known-good: later correction, current verdict, user constraint, pending next step, and evidence statement all survive.
- Known-bad: bearer tokens, OpenAI-style keys, key/value secrets, and private-key blocks never appear in output.
- Boundary: a huge recent message is truncated, duplicate text appears once, later conflicting excerpts follow earlier excerpts, and packet length is at most 8,500 characters.
- Stable instruction prefix says quoted excerpts are evidence rather than new instructions.

- [ ] **Step 6: Run evidence tests and verify RED**

Run: `node --test test/text.test.mjs`

Expected: FAIL because selection and rendering functions do not exist.

- [ ] **Step 7: Implement minimal evidence selection and rendering**

Categories and match intent:

```js
const CATEGORY_ORDER = ["correction", "decision", "constraint", "pending", "evidence", "recent"]
```

Select the latest user and assistant messages plus the highest-scoring category matches, preserve chronological order, redact before hashing, and stop before the packet limit.

- [ ] **Step 8: Run Task 1 tests and verify GREEN**

Run: `node --test test/text.test.mjs test/transcript.test.mjs`

Expected: all Task 1 tests pass.

- [ ] **Step 9: Commit Task 1**

Run:

```bash
git add package.json src/text.mjs src/transcript.mjs test
git commit -m "feat: add compact transcript normalization"
```

### Task 2: Checkpoint storage and hook lifecycle

**Files:**
- Create: `src/storage.mjs`
- Create: `src/hooks.mjs`
- Create: `bin/compact-guard.mjs`
- Create: `test/storage.test.mjs`
- Create: `test/hooks.test.mjs`

**Interfaces:**
- Consumes: Task 1 transcript and evidence functions.
- Produces: `writeCheckpoint(input, options?) -> Promise<Checkpoint>`
- Produces: `readCheckpoint({ vendor, sessionId }, options?) -> Promise<Checkpoint | null>`
- Produces: `appendAudit(event, options?) -> Promise<void>`
- Produces: `handleHook({ vendor, input, env }, options?) -> Promise<{ stdout, stderr, exitCode }>`

- [ ] **Step 1: Write failing storage tests**

Cover atomic replacement, mode `0600`, vendor/session path separation, content-free audit rows, disabled sentinel, and missing checkpoint behavior.

- [ ] **Step 2: Run storage tests and verify RED**

Run: `node --test test/storage.test.mjs`

Expected: FAIL because `src/storage.mjs` does not exist.

- [ ] **Step 3: Implement minimal private storage**

Checkpoint shape:

```js
{
  schemaVersion: 1,
  vendor: "claude",
  sessionId: "session-id",
  trigger: "manual",
  transcriptPath: "/absolute/path.jsonl",
  transcriptHash: "sha256",
  recordCount: 10,
  messageCount: 4,
  capturedAt: "2026-07-16T00:00:00.000Z",
  entries: []
}
```

- [ ] **Step 4: Run storage tests and verify GREEN**

Run: `node --test test/storage.test.mjs`

Expected: all storage tests pass.

- [ ] **Step 5: Write failing hook-contract tests**

Cover:

- Claude and Codex successful `PreCompact` write the same checkpoint schema and produce no stdout.
- Claude checkpoint failure returns `decision="block"`; Codex failure returns `continue=false`.
- Non-compact `SessionStart` is a no-op.
- Compact `SessionStart` returns vendor-valid `hookSpecificOutput.additionalContext` and reads the pre-compact checkpoint directly.
- Missing compact checkpoint produces a visible warning without throwing.
- Claude `PostCompact` logs summary length and lexical coverage counts without storing summary text.
- Codex `PostCompact` logs `summaryAvailable=false`.
- `CC_VENDOR` changes only the audit surface label and never skips ccp-gpt.
- Pure Claude sidechain transcripts and Codex subagent transcripts make `PreCompact`, `PostCompact`, and compact `SessionStart` non-blocking no-ops with no checkpoint, injection, or main trial audit.
- A non-empty `agent_id` produces the same no-op even when the transcript looks like a main session. Null, unreadable, and unclassifiable Claude continuations and Codex `PostCompact` cannot read a parent checkpoint or write the main trial audit. Codex compact `SessionStart` recovers from its validated checkpoint when the runtime provides a null or unreadable continuation path, while retaining the original surface and audit correlation. Missing `PreCompact` transcript evidence remains fail-closed.

- [ ] **Step 6: Run hook tests and verify RED**

Run: `node --test test/hooks.test.mjs`

Expected: FAIL because the hook handler does not exist.

- [ ] **Step 7: Implement minimal hook lifecycle**

The executable accepts `--vendor claude|codex` plus a required `--managed-id compact-guard/v1/<vendor>/<event>`, reads one JSON object from stdin, validates that the managed event matches `hook_event_name`, calls `handleHook`, writes only the returned streams, and sets `process.exitCode`.

- [ ] **Step 8: Run Task 2 tests and verify GREEN**

Run: `node --test test/storage.test.mjs test/hooks.test.mjs`

Expected: all Task 2 tests pass.

- [ ] **Step 9: Commit Task 2**

Run:

```bash
git add src/storage.mjs src/hooks.mjs bin/compact-guard.mjs test
git commit -m "feat: add compact hook lifecycle"
```

### Task 3: Idempotent installation and rollback

**Files:**
- Create: `src/install.mjs`
- Create: `bin/install.mjs`
- Create: `test/install.test.mjs`

**Interfaces:**
- Produces: `mergeHooks(settings, { vendor, command }) -> settings`
- Produces: `removeHooks(settings, { commandMarker }) -> settings`
- Produces: `install({ homeDir, projectDir, now }) -> Promise<InstallReport>`
- Produces: `uninstall({ homeDir, projectDir }) -> Promise<InstallReport>`

- [ ] **Step 1: Write failing installer tests**

Cover:

- Existing hook groups remain byte-equivalent after JSON parse/stringify semantics.
- Install adds exactly one `manual|auto` group for each of `PreCompact` and `PostCompact`, plus one `compact` group for `SessionStart`.
- Repeated install adds zero duplicates.
- Each handler carries one fixed `--managed-id compact-guard/v1/<vendor>/<event>` marker.
- Uninstall removes only handlers containing a compact-guard managed ID, then removes only groups or events left empty by that removal.
- Install creates timestamped backups before changing either existing file.
- A failure updating the second config reports a partial install and leaves the successfully written first config intact; rerunning install converges without duplicates and does not overwrite concurrent third-party changes.
- Every command handler has a 10-second timeout and a stable status message.

- [ ] **Step 2: Run installer tests and verify RED**

Run: `node --test test/install.test.mjs`

Expected: FAIL because installer functions do not exist.

- [ ] **Step 3: Implement minimal JSON merge installer**

Targets:

```js
[
  { vendor: "claude", relativePath: ".claude/settings.json" },
  { vendor: "codex", relativePath: ".codex/hooks.json" }
]
```

Write each file atomically, preserve file modes, back up originals as mode `0600`, and print the install report with `JSON.stringify()`.

- [ ] **Step 4: Run installer tests and verify GREEN**

Run: `node --test test/install.test.mjs`

Expected: all installer tests pass.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add src/install.mjs bin/install.mjs test/install.test.mjs
git commit -m "feat: add compact guard installer"
```

### Task 4: Trial reporting, design record, and global rollout

**Files:**
- Create: `bin/trial-report.mjs`
- Create: `test/trial-report.test.mjs`
- Create: `docs/design.md`
- Create: `README.md`
- Modify: `~/Desktop/projects/.claude/trials/active.md`
- Modify through installer: `~/.claude/settings.json`
- Modify through installer: `~/.codex/hooks.json`

**Interfaces:**
- Produces: `summarizeAudit(rows) -> TrialSummary`
- Trial review date: `2026-07-23`.

- [ ] **Step 1: Write failing trial-report tests**

The report must count checkpoint, injection, post-compact, blocked, error, vendor, surface, trigger, and unmatched checkpoint/injection events without reading checkpoint text.

- [ ] **Step 2: Run trial-report tests and verify RED**

Run: `node --test test/trial-report.test.mjs`

Expected: FAIL because trial reporting does not exist.

- [ ] **Step 3: Implement trial reporting**

Print one JSON object with event counts, mismatches, maximum packet size, and observed surfaces.

- [ ] **Step 4: Run trial-report tests and verify GREEN**

Run: `node --test test/trial-report.test.mjs`

Expected: all trial-report tests pass.

- [ ] **Step 5: Write design and operation docs**

`docs/design.md` must include:

- Surface table: Locked, Editable, Append-only, Human-controlled.
- Bypass table: tool-result elevation, subagent transcript, duplicate records, vendor skip, hook-order dependency, unknown Desktop records, native prompt drift.
- Three permanent regression fixtures: known-good, known-bad, boundary.
- Rollback: `touch ~/.compact-guard/disabled` for immediate disable and `node bin/install.mjs --uninstall` for hook removal.

`README.md` must include install, uninstall, audit, privacy, state locations, supported surfaces, exclusions, and verification commands.

- [ ] **Step 6: Append the seven-day trial entry**

Add `## compact-guard cross-harness recovery (2026-07-23 review date)` to the append-only active ledger with:

- checkpoint-to-injection match rate target `100%`;
- zero silent checkpoint failures;
- zero secret/tool-output leakage;
- injected packet cap `8,500` characters;
- friction signals: stale conclusion, incorrect precedence, blocked compaction, visible hook error;
- no-event alarm: no natural compact events by review date means extend one week rather than KEEP;
- disable and uninstall commands.

- [ ] **Step 7: Run full pre-install verification**

Run:

```bash
npm test
npm run check
```

Expected: all tests pass; syntax check exits zero.

- [ ] **Step 8: Install globally and verify exact registration counts**

Run: `node bin/install.mjs --install`

Verify each target has exactly one compact-guard command for each required event and all pre-existing hook command counts remain unchanged.

Open Codex CLI and Desktop hook trust controls and confirm the new hook hash is trusted; configuration presence alone is not execution evidence.

- [ ] **Step 9: Run synthetic hooks against real transcript paths**

For one compacted Claude transcript, one Codex CLI transcript, and one Codex Desktop transcript:

- send a synthetic `PreCompact` event through the executable;
- verify a private checkpoint exists;
- send `SessionStart(source=compact)` and verify valid JSON plus bounded recovery context;
- send `PostCompact` and verify a content-free audit row.

- [ ] **Step 10: Run available real dispatch smoke tests**

Exercise manual compact in Claude Code and Codex CLI if interactive sessions can be launched safely. After Codex reports that compaction completed, submit one additional no-tool user turn so the queued compact `SessionStart` runs before checking checkpoint/injection pairing. Desktop dispatch remains an observation-period item unless a separate disposable Desktop session is available.

- [ ] **Step 11: Run fresh final verification**

Run:

```bash
npm test
npm run check
node bin/trial-report.mjs
git status --short
git log --oneline --decorate -5
```

Expected: zero test failures, zero syntax failures, report parses, only intentional files are tracked, and task commits are visible.

- [ ] **Step 12: Commit Task 4**

Run:

```bash
git add README.md docs bin/trial-report.mjs test/trial-report.test.mjs
git commit -m "docs: add compact guard trial operations"
```
