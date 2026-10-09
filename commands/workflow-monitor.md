---
description: Watch, pause, and resume any background Workflow so a long run survives a quota / service squeeze without re-spending tokens on already-completed agents. Vendor-aware — guards CC's 5h+7d OAuth quota or relay's service stability, selected from CC_VENDOR. GLM is retired and has no adapter. Use when launching a long workflow, when one is about to blow its limit, or to continue a suspended one. Do not use for workflow debugging or errors (squeeze survival only), nor for short workflows that finish within minutes.
---

# /workflow-monitor — watch · pause · resume any background Workflow

`$ARGUMENTS`:
- `watch` — guard a just-launched workflow: spawn a background limit-watch that wakes me to pause when the vendor's metric hits the threshold. **This is what the PostToolUse-on-Workflow hook injects.**
- `pause` — stop the guarded/running workflow now, save resume state
- `resume` — continue a suspended workflow from cache
- a `wf_...` runId — target that specific run
- `--vendor <anthropic|relay>` — override vendor detection (combinable with any mode above)
- empty → **auto**: suspend state exists → resume; watching state exists → pause; else → pause

📎 踩過的坑 / provenance for every step below: `~/.claude/references/workflow-monitor-lessons.md`. Read it before changing a threshold or when a step misbehaves — not on a normal run.

---

## Step V — resolve the vendor (do this first, it parameterises everything else)

Pause/resume/watch mechanics are vendor-independent. The **only** thing that differs is which metric the watch polls, by which script, at what thresholds — and that table lives in one adapter, not in forked copies of this file (the two forks that used to exist drifted for a month; see the lessons file's Merge history).

🔌 接線點：後端標記 CC_VENDOR — 見 WIRING.md

| `CC_VENDOR` | Metric source | Watcher script |
|---|---|---|
| unset | CC 5h + 7d OAuth quota cache (`~/.claude/cache/quota-*.json`, **active account**) | `workflow-limit-watch.sh` |
| anything else (mimo / deepseek / …) | **no adapter — do NOT arm a watch.** Their credit/PAYG shapes don't fit a threshold gate; arming the anthropic watcher would guard a quota the run doesn't burn. Report that and stop. | — |

`CC_VENDOR=glm` is retired and has no adapter. Stop, report that state, and do not arm `glm-quota-watch.sh` or substitute the Anthropic watcher.

Thresholds per vendor (the resolver is the source of truth; this table is for reading):

| Vendor | Pause when | Resume when |
|---|---|---|
| anthropic | 5h ≥ 90% **OR** 7d ≥ 99% | 5h ≤ 60% **AND** 7d ≤ 95% |

Pause is OR / resume is AND on every vendor — deliberate hysteresis: any one dimension tightening pauses, but every dimension must recover to resume.

🔌 接線點：中轉站 — 見 WIRING.md

---

## Step 0 — show the current metric (best-effort, never block)

```bash
🔌 接線點：workflow-monitor 後端轉接 — 見 WIRING.md
```

Add the vendor name as an argument to override detection (e.g. `... status relay`).

---

## Step 0a — resolve SESSION_ID (per-session isolation)

State files and watch processes are **per-session** so multiple CC sessions on one box don't step on each other (added 2026-06-19). Pull the current session id from the launch result's `Transcript dir:` (path shape is `~/.claude/projects/<proj>/<SESSION_ID>/...`) — that string is what gates the state-file path, the pgrep filter, and the pkill scope below.

```bash
# launch result in context includes "Transcript dir: .../projects/<proj>/<SESSION_ID>/subagents/..."
SESSION_ID="<extract from Transcript dir — the dir name two levels up from /subagents/>"
STATE_FILE="$HOME/.claude/workflow-monitor-state-${SESSION_ID}.json"
ARGS_FILE="$HOME/.claude/workflow-monitor-args-${SESSION_ID}.json"
```

Then resolve the vendor's watcher. `WATCH_PROC` is the pgrep pattern every cleanup snippet below needs; the two launch commands are printed for you to paste verbatim in Step W.4 / Step 2.7:

```bash
WATCH_PROC=$(bash ~/.claude/scripts/workflow-monitor-vendor.sh proc) || echo "NO ADAPTER — stop here"
echo "watcher: $WATCH_PROC"
bash ~/.claude/scripts/workflow-monitor-vendor.sh resolve "${SESSION_ID}"
```

A non-zero exit means the vendor has no adapter: stop, tell the user, do not arm anything. Do **not** try to `eval` the `resolve` output — dcg blocks `eval` on dynamically generated source (`heredoc.posix:eval-dynamic`), which is why `proc` exists as its own subcommand. Read the two `WM_*_CMD` lines and paste them; the only value that becomes a shell variable is the watcher filename, which is pure ASCII.

The state namespace is shared across vendors (one command, one namespace), so cleanup snippets always filter by `SESSION_ID`, never by vendor. If you can't resolve SESSION_ID (e.g. the command was invoked stand-alone with no launch result in context), fall back to the legacy single-session paths `~/.claude/workflow-monitor-state.json` / `workflow-monitor-args.json`. Other sessions on this box may still have their own — never `pkill -f` watch processes; always `kill <pid>` a recorded PID or `pgrep -af <WATCH_PROC> | grep $SESSION_ID` to filter.

---

## Step 1 — pick mode

1. `$ARGUMENTS` forces `watch`/`pause`/`resume`/a runId → honor it.
2. Else read `$STATE_FILE` (per-session, from Step 0a) if present:
   - `phase=suspended` → **RESUME** (Step 3)
   - `phase=watching` → **PAUSE** (Step 2)  *(you were almost certainly woken by the limit-watch)*
3. Else → **PAUSE** (Step 2).

---

## Mechanism (verified 2026-06-06 by live tests; vendor-independent)

A Workflow runs as a background task and journals to `~/.claude/projects/<proj>/<session>/workflows/wf_<runId>.json`. `Workflow({scriptPath, resumeFromRunId})` replays from that journal the longest **deterministic prefix** of `agent()` calls whose (prompt, opts) reproduce **byte-identical** on re-execution — those return **instantly, zero LLM tokens**; from the first agent whose prompt differs, everything re-runs live.

> ⚠️ **Resume only saves tokens to the extent the workflow is DETERMINISTIC. This is the big caveat.** The journal caches agent *results* keyed on the agent's prompt, but the script body re-executes top-to-bottom on resume — so any agent whose prompt is computed from nondeterministic intermediate state (mutable counters, `parallel()`/`pipeline()` completion-order races, unsorted dedup, anything that varies run-to-run) gets a *different* prompt → cache miss → it and everything after re-run. Measured 2026-06-07 on deep-research-paced: a run paused mid-Verify (83/100 agents journaled) replayed only **6** agents and **re-ran 94**. For a nondeterministic workflow, pause→resume ≈ full re-run — so the win is "survive the squeeze / don't crash", not "save tokens"; to actually save the in-flight cost, prefer switching to a fresh account (anthropic) and letting it RUN to completion. Full measurement in the lessons file.

> ⚠️ **Resume re-runs the script body from the top — so the original `args` MUST be re-passed, byte-identical.** Statements above the first `agent()` (arg parsing, the `if (!QUESTION) return` guard) execute fresh every resume. Omit `args` and an arg-reading script bails at its guard → that failed run "completes" with `agentCount=0` and **overwrites the journal, destroying the cache prefix**. So: PAUSE captures `.args` from the killed journal, RESUME replays it via the inject helper.

| Stage | journal file | journal `status` | transcript dir |
|---|---|---|---|
| **running** | **absent** | — | present |
| **after TaskStop** | present | `killed` | present |
| **completed** | present | `completed` | present |

Two bridges this command stands on:
- **Metric source is a free local read or an admin endpoint — no token cost, no throttle.** Per vendor, see Step V. Re-resolved every poll, so a mid-run `/login` account switch (anthropic) is followed live: switch to a fresh account and the reverse-watch sees its low utilization and fires resume.
- **background bash exit → re-invokes the main session.** That is the *only* way an external signal can wake an idle main session, and it only works for a watch **the main session launched itself** via `Bash(run_in_background=true)`. A hook- or externally-spawned poller cannot wake the session — so watch mode must run from here, not from the hook.

---

## Step W — WATCH (guard a running workflow)

> **Always arm — no judgement.** Arm watch on EVERY background workflow launch. Do NOT weigh whether the run "looks long enough" — the cost of arming is one idle background poll (≈0), while the cost of NOT arming (a run blowing its window mid-flight and re-spending tokens, or hard-rate-limiting) is large and asymmetric. The user's standing instruction (2026-06-06): always arm. The one exception is a vendor with no adapter (Step V) — there, arming nothing is correct.

1. Identify the workflow to guard from the **launch result in context** (`Task ID:`, `Run ID: wf_...`, `Script file:`, `Transcript dir:`). This is the moment to capture the task_id — it is NOT derivable later. Also run Step 0a (SESSION_ID + vendor resolve).
2. **Avoid duplicates (session-scoped):** if a watch is already running **for this session**, do nothing more. Other sessions' watches are unrelated — never global-match.

   ```bash
   pgrep -lf "${WATCH_PROC}" | grep -F "${SESSION_ID}" >/dev/null && echo "watch already running for this session — skip" && exit 0 || true
   ```

3. Record what we're guarding (per-session state file, `phase=watching`):

   ```bash
   # dcg 的 redirect-truncate-root-home 規則會擋 shell `>` 寫 home 路徑，改 python 寫檔（2026-07-11）
   python3 -c 'import sys; open(sys.argv[1],"w").write(sys.stdin.read())' "$STATE_FILE" <<EOF
   {"phase":"watching","runId":"<runId>","taskId":"<task_id>","watchTaskId":"","vendor":"<WM_VENDOR from Step 0a>","watchProc":"${WATCH_PROC}","scriptPath":"<scriptPath>","sessionDir":"<...workflows dir>","sessionId":"${SESSION_ID}","pauseRule":"<WM_PAUSE_RULE from Step 0a>"}
   EOF
   ```

   `watchTaskId` 留空、由 Step 5 回填 — 它是 cleanup 唯一可靠的停止把手，別漏。`vendor` / `watchProc` 讓 pause 與 resume 不必重跑 vendor 偵測就知道要停哪支 watcher。

4. Launch the watch as a **main-session background bash** (this gives the wake bridge). Use the resolver's line verbatim — it already carries this vendor's thresholds, poll interval, DIRECTION polarity and the SESSION_ID tag that makes the watch `pgrep`-filterable:

   ```
   Bash(run_in_background=true): <paste the WM_PAUSE_CMD line printed in Step 0a, verbatim>
   ```

   Do not retype the thresholds. They are per-vendor, the relay polarity is inverted, and only the anthropic line carries a 6th arg (7d threshold). `workflow-monitor-vendor.test.sh` pins every one of these launch lines.

5. **Back-fill `watchTaskId` into the state file, immediately.** The Bash tool's return line reads `Command running in background with ID: <id>` — that id is the watch's own background-task handle, and like the workflow's task_id it is **not derivable later**. Write it in now:

   ```bash
   python3 - "$STATE_FILE" <<'PY'
   import json, sys
   p = sys.argv[1]
   d = json.load(open(p))
   d["watchTaskId"] = "<paste the Bash background ID from the launch result>"
   open(p, "w").write(json.dumps(d))
   PY
   ```

   Why this step earns its own number: every cleanup block below stops the watch through `TaskStop({task_id: watchTaskId})`, because that is the **only** method verified to actually work — shell `kill` and even `kill -9` have been observed failing silently against these watchers (2026-08-01). Skip the back-fill and cleanup degrades to the shell path that is known to leave orphans, and the id is unrecoverable once the launch result scrolls away. Done when `jq -r .watchTaskId "$STATE_FILE"` prints a non-empty id. Then continue to Step 6.

6. Return to waiting. Two possible wake-ups:
   - **limit-watch completes** with a trip line ending `ACTION: invoke /workflow-monitor pause` → immediately invoke `/workflow-monitor pause`.
   - **the workflow completes first** → stop **only this session's** watch and clear state. **Order matters — `TaskStop` first, shell kill only as fallback:**

     ```
     TaskStop({task_id: "<watchTaskId from $STATE_FILE>"})
     ```

     Verified 2026-08-01: `TaskStop` cleanly dropped a watch (PIDs 6031/6114) that had just survived both `kill` and `kill -9`. Expect the reply `Successfully stopped task: <id>`. Then confirm it is gone and clear state; drop to the shell path below **only** if `watchTaskId` was never back-filled or `TaskStop` errored:

     ```bash
     # FALLBACK ONLY (no watchTaskId / TaskStop errored) — this path is known to fail silently.
     # session-scoped kill with VERIFICATION: TERM → wait → re-check → KILL escalation → loud fail
     # NEVER `pkill -f` (cross-session). NEVER `awk '{print $1}'` (CC harness rewrites `$1` to task id).
     # NEVER trust kill silently — 2026-06-19 verified: "watch cleaned" reported but watcher survived 1+ hour.
     pids=$(pgrep -lf "${WATCH_PROC}" | grep -F "${SESSION_ID}" | cut -d' ' -f1 | grep -E '^[0-9]+$')
     if [ -n "$pids" ]; then
       kill $pids 2>/dev/null; sleep 0.5
       still=$(pgrep -lf "${WATCH_PROC}" | grep -F "${SESSION_ID}" | cut -d' ' -f1 | grep -E '^[0-9]+$')
       [ -n "$still" ] && kill -9 $still 2>/dev/null && sleep 0.3
     fi
     if pgrep -lf "${WATCH_PROC}" | grep -F "${SESSION_ID}" >/dev/null; then
       echo "❌ watch for $SESSION_ID STILL ALIVE after kill+kill-9 — keeping $STATE_FILE for retry/diagnosis"
       ps aux | grep -F "${WATCH_PROC}" | grep -F "${SESSION_ID}" | grep -v grep
     else
       rm -f "$STATE_FILE" "$ARGS_FILE"
       echo "✅ workflow done; this-session watch stopped"
     fi
     ```

     走到這條 = workflow 自然跑完，**watch 任務到此結束**——不要繼續往 pause/resume 步驟走，那些只給「被額度擠壓」的路徑用。

     **`❌ STILL ALIVE` 分支的收尾**（否則這裡是 premature-completion 的入口）：**不要 `rm` state file** — 留著 `watchTaskId` 才能再試一次 `TaskStop`，它也是使用者診斷的唯一線索。然後在給使用者的回報裡寫明三件事：殘留的 PID、這是已知的 shell-kill 失效模式（正解是 `TaskStop`）、以及你已經試過什麼。**不要因為 workflow 本身成功就把殘留當無害而靜默放過** —— 一個還活著的 watch 會在下次跨閾值時醒來，要求你 pause 一個早就結束的 run。這條分支不阻塞你回報 workflow 結果，但必須出現在同一則回報裡。

---

## Step 2 — PAUSE

1. **task_id**: prefer `taskId` from the `watching` state file (captured at watch time — this is why watch mode solves the old "task_id not derivable later" problem). Fallback: the launch result in context. Also take `watchProc` / `vendor` from that file rather than re-detecting.
2. Stop it: `TaskStop({task_id: "<task_id>"})`
3. Wait ~8s, confirm it froze. (TaskStop lags — a few queued agents finish first; they still cache.)
4. Read back the killed journal for resume coordinates **and capture the original args** (the killed journal still holds `.args` — grab it now, before any no-args resume can overwrite it):

   ```bash
   shopt -s nullglob 2>/dev/null || setopt null_glob 2>/dev/null || true
   # Scope to THIS session's project dir so multi-session machines don't pick another session's journal
   J=$(ls -t ~/.claude/projects/*/${SESSION_ID}/workflows/wf_*.json 2>/dev/null | head -1)
   jq -r '"runId=\(.runId) status=\(.status) scriptPath=\(.scriptPath) argsType=\(.args|type)"' "$J"
   jq '.args' "$J" | python3 -c 'import sys; open(sys.argv[1],"w").write(sys.stdin.read())' "$ARGS_FILE"   # sidecar for inject-and-resume helper to read (Step 3.4)；python 寫檔避開 dcg redirect 攔截
   ```

   Expect `status=killed`. (Fall back to runId/scriptPath from the launch result if scriptPath is null, e.g. an inline-script workflow.) If `argsType=null` the workflow took no args (name-only) — resume will skip args.
5. **GOLDEN snapshot — first thing after capturing args, before any resume attempt** (immutable base for fork-from-GOLDEN restore; this is the load-bearing safety mechanism — without it, a single bad resume permanently pollutes journal+jsonl and you lose the ability to retry cleanly):

   ```bash
   SD=$(dirname "$J" | sed 's|/workflows$|/subagents/workflows|')/wf_<runId>
   cp "$J" "$J.GOLDEN"
   [[ ! -d "${SD}.GOLDEN" ]] && cp -r "$SD" "${SD}.GOLDEN"
   echo "GOLDEN: $J.GOLDEN + ${SD}.GOLDEN ($(ls "${SD}.GOLDEN" | wc -l) entries)"
   ```

   **Why GOLDEN must come BEFORE any resume**: a bad resume overwrites journal `.args` and adds polluted jsonl files under the same `<runId>/` dir. Without a pre-resume snapshot, you cannot get back to clean state for the next attempt. Make GOLDEN unconditionally — cost is one `cp -r` on a small dir (~10MB), benefit is infinite retry capability.
6. Flip state to `suspended` (stop any lingering watch **for this session only** first). If the pause was triggered by the limit-watch itself, that watch already exited to wake you — `TaskStop` will just report the task is not running, which is fine and not an error to chase. Still try it first:

   ```
   TaskStop({task_id: "<watchTaskId from $STATE_FILE>"})
   ```

   ```bash
   # FALLBACK ONLY (no watchTaskId / TaskStop errored) — this path is known to fail silently.
   # session-scoped kill WITH VERIFICATION (avoid silent-kill failure — see the lessons file)
   pids=$(pgrep -lf "${WATCH_PROC}" | grep -F "${SESSION_ID}" | cut -d' ' -f1 | grep -E '^[0-9]+$')
   if [ -n "$pids" ]; then
     kill $pids 2>/dev/null; sleep 0.5
     still=$(pgrep -lf "${WATCH_PROC}" | grep -F "${SESSION_ID}" | cut -d' ' -f1 | grep -E '^[0-9]+$')
     [ -n "$still" ] && kill -9 $still 2>/dev/null && sleep 0.3
   fi
   pgrep -lf "${WATCH_PROC}" | grep -F "${SESSION_ID}" >/dev/null && \
     echo "⚠️ lingering watch for $SESSION_ID — investigate before flipping to suspended"
   # dcg 的 redirect-truncate-root-home 規則會擋 shell `>` 寫 home 路徑，改 python 寫檔（2026-07-11）
   python3 -c 'import sys; open(sys.argv[1],"w").write(sys.stdin.read())' "$STATE_FILE" <<EOF
   {"phase":"suspended","runId":"<runId>","vendor":"<WM_VENDOR from Step 0a>","watchProc":"${WATCH_PROC}","scriptPath":"<scriptPath>","sessionDir":"<...workflows dir>","sessionId":"${SESSION_ID}","argsFile":"${ARGS_FILE}","watchTaskId":"","pausedNote":"<why — quote the watcher's trip line>"}
   EOF
   ```

   `watchTaskId` again starts empty — Step 7 refills it with the **reverse** watch's id, which is what Step 3.1 stops.

7. **Arm auto-resume** — launch the reverse watch (slow poll, waits for the metric to recover). Again use the resolver's line verbatim; on anthropic it carries the 7d AND-condition, on relay the inverted `above` direction:

   ```
   Bash(run_in_background=true): <paste the WM_RESUME_CMD line printed in Step 0a, verbatim>
   ```

   The resume condition is an AND across every dimension (see Step V) — that matters when the pause was tripped by the slower-moving 7d dimension: a metric-1-only reverse-watch would mis-fire on the fast dimension's rolling recovery and re-burn the already-saturated slow one. Validated 2026-06-28→29 on anthropic: a reverse watch armed with the 7d cap blocked resume while owner 7d=99% held, then fired the moment cross-day rolling slid it to 0%.

   Then back-fill this reverse watch's background id the same way Step W.5 did — Step 3.1 stops it via `TaskStop` and has no other reliable handle:

   ```bash
   python3 - "$STATE_FILE" <<'PY'
   import json, sys
   p = sys.argv[1]
   d = json.load(open(p))
   d["watchTaskId"] = "<paste the Bash background ID from the reverse-watch launch>"
   open(p, "w").write(json.dumps(d))
   PY
   ```

   Done when `jq -r .watchTaskId "$STATE_FILE"` prints the reverse watch's id. Then continue to Step 8.
8. Tell the user: paused `<runId>`, quoting the watcher's trip line as the reason; **auto-resume armed**, quoting the `WM_RESUME_RULE` line from Step 0a as the condition. Keep CC open. They can also resume manually with `/workflow-monitor` anytime.

---

## Step 3 — RESUME

(Triggered manually, OR automatically when the reverse watch wakes you with `ACTION: invoke /workflow-monitor resume`.)

⚠️ **DO NOT manually re-pass args via the Workflow tool args parameter** — the main session LLM cannot achieve byte-identical args reproduction (unicode normalization happens at the cognitive layer: full-width 「：（）；，」get unconsciously rewritten to half-width, markdown bold sometimes dropped; both verified 2026-06-14 F8 case — failed twice trying to manually replay). Use the **inject-and-resume helper** instead — it bypasses the LLM entirely by injecting args into the script literal via `bash`+`python` byte-faithful file IO.

1. Stop the reverse watch — it did its job. **`TaskStop` first**; session-scoped shell kill only as fallback, never `pkill -f`:

   ```
   TaskStop({task_id: "<watchTaskId from $STATE_FILE>"})
   ```

   On an auto-resume the reverse watch already exited to wake you, so a "not running" reply is expected. On a **manual** resume it is still polling and this is the call that actually stops it.

   ```bash
   # FALLBACK ONLY (no watchTaskId / TaskStop errored) — this path is known to fail silently.
   # session-scoped kill WITH VERIFICATION (see the lessons file for the silent-kill failure mode)
   pids=$(pgrep -lf "${WATCH_PROC}" | grep -F "${SESSION_ID}" | cut -d' ' -f1 | grep -E '^[0-9]+$')
   if [ -n "$pids" ]; then
     kill $pids 2>/dev/null; sleep 0.5
     still=$(pgrep -lf "${WATCH_PROC}" | grep -F "${SESSION_ID}" | cut -d' ' -f1 | grep -E '^[0-9]+$')
     [ -n "$still" ] && kill -9 $still 2>/dev/null && sleep 0.3
   fi
   ```

2. Read `$STATE_FILE` (per-session, from Step 0a) → `runId`, `scriptPath`, `sessionDir`, `argsFile`, `vendor`, `watchProc`. `argsFile` in the state file is already per-session (`workflow-monitor-args-<sid>.json`).
3. **Same-session guard:** if the current session's project dir differs from `sessionDir`, STOP → cross-session fallback below.
4. **Run the inject helper to produce a byte-faithful injected script** (this replaces the broken "manually re-pass args" path):

   ```bash
   # workflow-script = the ORIGINAL workflow source (e.g. <workflow-script.js>)
   # sidecar      = the per-session args.json captured in Step 2.4 ($ARGS_FILE)
   # output       = a /tmp/ injected script with args hardcoded into the QUESTION literal
   ~/.claude/scripts/resume-workflow-with-injected-args.sh \
     ~/.claude/workflows/<original-workflow-name>.js \
     "$ARGS_FILE" \
     /tmp/<workflow-name>-injected.js
   ```

   The helper:
   - Reads sidecar args via `python json.loads` (byte-faithful, no normalization)
   - Replaces the workflow's args-reading line (e.g. `const QUESTION = (typeof args === "string" && args.trim()) || ""`) with `const QUESTION = <json.dumps(args, ensure_ascii=False)>` — a JS string literal with full unicode preserved
   - Writes the injected script via `python file.write` (byte-faithful)
   - Reports byte counts + the next-step Workflow call

5. **Resume with the injected script — DO NOT pass args** (QUESTION is now hardcoded; the `args` global is ignored):

   ```
   Workflow({scriptPath: "/tmp/<workflow-name>-injected.js", resumeFromRunId: "<runId>"})
   ```

   ⚠️ All three Workflow tool parameters (`scriptPath`, `resumeFromRunId`, no args) are pure ASCII → no LLM normalization risk. Cache hits because the runtime reads the injected script byte-faithfully, `QUESTION` evaluates to the byte-identical original args, every agent prompt embedding it produces the original hash, and the `agent-<hash>.jsonl` files are still in `<runId>/`.

6. **If resume fails (cache miss / runtime rejects injected script / agent prompts diverge)** — fork-from-GOLDEN and try a new approach:

   ```bash
   # Restore from immutable GOLDEN base, then either: (a) re-run helper with different sidecar, or (b) abandon resume → manual aggregation / fresh run
   cp "$J.GOLDEN" "$J"
   rm -rf "$SD" && cp -r "${SD}.GOLDEN" "$SD"
   echo "restored to clean GOLDEN state — safe to retry or abandon resume"
   ```

   **Fork-from-GOLDEN means GOLDEN itself stays immutable** — each retry restores from GOLDEN, never overwrites it. This is what makes "infinite retry until success" possible.

7. **Re-arm:** resuming is itself a `Workflow` call, so the hook fires again and re-injects `/workflow-monitor watch` — re-guarding the resumed run automatically. The full loop (watch→pause→reverse-watch→inject→resume→watch…) continues across multiple squeeze windows untouched. Note the hook is deliberately silent for every vendor other than unset (Anthropic-native) — under those, re-arm by invoking `/workflow-monitor watch --vendor <name>` yourself.
8. On completion, report token spend (cached agents ≈ 0 token). Clear **this session's** state including GOLDEN (only after success):

   ```bash
   rm -f "$STATE_FILE" "$ARGS_FILE"
   rm -f "$J.GOLDEN"
   rm -rf "${SD}.GOLDEN"
   rm -f /tmp/<workflow-name>-injected.js
   ```

---

## Cross-session fallback (original session gone)

`resumeFromRunId` won't rehydrate in a new session even though the journal is on disk. Best first:
1. **Per-unit workflows** (deep-research = one topic per run): completed units are already persisted as output files — just start the next unit fresh. Don't fight the journal.
2. **Manual aggregation rescue (preferred when the workflow reached verify stage)**: if `subagents/workflows/wf_<runId>/agent-*.jsonl` is full of completed phases (scope+search+fetch+most of verify), the **cache IS the result** — write a phase-classifier + jq/python aggregator + tally votes by claim text + main session hand-craft synth. See `[[reference_workflow_jsonl_cache_rescue_pattern]]` for the template (F8 case 2026-06-14 saved a full topic this way, zero token loss). The synth phase is optional from the main session's perspective — main is already doing reflow judgment that synth merely approximates.
3. **Last resort:** hand-author a continuation script — read `agent-*.jsonl`, replay results into a fresh workflow. Only for very large interrupted runs where neither (1) nor (2) applies.

## When NOT to attempt resume (decision tree)

After pause, before reaching for the inject-and-resume helper, check which phase the workflow hit:

| agents journaled | likely phase | preferred action |
|---|---|---|
| < 10 | scope / early search | **start fresh run** with clean runId; token cost is small, no inject-helper risk |
| 10-30 | search → fetch | inject-and-resume is worth it; verify the inject helper produced expected byte counts before launching |
| > 30, verify happening | verify phase | inject-and-resume → cache-hits the heavy scope+search+fetch (the expensive ones); only ~6-15 in-flight verify boundary rerun |
| > 75, verify mostly done, synth pending | nearly complete | **manual aggregation rescue beats resume**: jsonl already holds all research content; main session synth is more faithful to user context than the generic synth agent |

Resume is NOT the default — it's the right choice only when heavy phases (fetch) are already cached and the in-flight verify boundary rerun is cheaper than starting over.

---

## Rules that still bind

Distilled from `~/.claude/references/workflow-monitor-lessons.md` — these are the ones that will bite you inside a normal run. Read the lessons file for the evidence and for anything vendor-specific.

- **Stop watches with `TaskStop`, not `kill`.** Shell `kill` and `kill -9` have been observed failing silently. The fallback shell chain must always TERM → verify → KILL → verify → loud `❌`; never report "watch cleaned" without a post-kill `pgrep`.
- **`watchTaskId` is unrecoverable — back-fill it in the same turn you launch a watch.** `TaskList` lists neither background bash nor workflow tasks, so once the launch result scrolls away the id is gone for good.
- **Never `pkill -f` a watcher, and never global-match one.** Multiple CC sessions share this box; both detection and cleanup filter by `SESSION_ID`.
- **Avoid `$1` / `$2` / `$NF` in any shell snippet in this file.** The harness rewrites `$1` at injection time to the active task id, which silently breaks `awk`. Use `cut -d' ' -f1`, and always follow it with `| grep -E '^[0-9]+$'` because `pgrep -lf` emits multi-line command strings whose continuation lines start with non-PID tokens.
- **GOLDEN before any resume attempt.** No exceptions, no cost/benefit weighing.
- **Never re-pass workflow args by hand.** Always the inject helper.
- **Never infer "did resume replay?" from utilization %.** Count fresh `agent-*.jsonl` per launch window against the journal `agentCount` delta.
- **Always arm — except for a vendor with no adapter,** where arming the wrong vendor's watcher would guard a quota the run doesn't burn.
- **Take launch lines from the resolver, never retype thresholds.** Poll intervals, extra positional args and DIRECTION polarity all differ per vendor; relay's is inverted.
- **Adding a vendor = a `case` arm in `workflow-monitor-vendor.sh` + a threshold assertion in its contract test.** Do not fork this command file; the two forks that existed from 2026-06 to 2026-09 silently missed the 2026-08-01 TaskStop fix for a month because nothing notices when a fork's original gets fixed.
