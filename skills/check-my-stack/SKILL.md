---
name: check-my-stack
description: Evaluate whether a popular or hyped agent/dev tool is worth adopting or borrowing from, measured against the user's OWN existing stack — never in the abstract. Use when the user asks for competitive or 借鑑 analysis of a specific named tool against their workflow/stack — e.g. "X 對我現有流程的競合", "評估 X 值不值得借鑑", "X vs 我的 stack", "is X worth adopting given what I already have". Also invokable via /check-my-stack. Do NOT use for plain factual research with no "versus my stack" framing, nor for casual comparison questions — research-before-answer covers both.
---

<!-- 本檔在契約測試底下：bash ~/.claude/skills/check-my-stack/scripts/tests/plain-language-presentation.test.sh；python3 ~/.claude/commands/tests/test_skill_verify_one_shot_callers.py -->

# Competitive Stack Analysis

A tool reaches this skill because the user found it interesting enough to bring — the input is pre-filtered by their interest. The job is therefore: **build the strongest adoption hypothesis for the tool first, then try to break it**. There is no default verdict; only the analysis order has a default. This posture governs effort allocation (search hard for a path to value before rejecting), not the evidence standard (claims need the same proof either way).

## Governing rule (order is mandatory)

Enumerate the user's existing stack maturity FIRST → then map the tool point-by-point onto it. Never "list the tool's highlights first, then back-fill where the user could apply them" — reading the README first anchors the whole analysis on the tool's marketing framing. Every borrow candidate's real value = capability ÷ maturity of the user's existing equivalent, whichever way the arithmetic lands.

## Workflow

### Step 0 — Fast-kill check (the only paper-verdict shortcut)

Two qualifying routes; the qualification evidence goes into the Gate Ledger (Step 6.4):

- **(a) Settled rejection lineage hit** — all three required, because a lineage citation without them is exactly how stale verdicts self-perpetuate: (1) cite the lineage entry by name; (2) one sentence arguing this case's frame is the same shape as the lineage's frame; (3) mini-reconcile the entry (is the denominator behind that rejection still in place? any major upstream change in the tool?). Old entries without a frame count as leads, not qualification — annotate the frame when citing (incremental migration). An `exhausted` marker (Step 6.6) qualifies; overturning it needs new delta evidence.
- **(b) Structural dealbreaker hit** — cite the discipline entry (billing can't ride an existing subscription / agent-in-loop vs background-scraper mismatch / mission-critical environment incompatibility) + one sentence of applicability.

There is deliberately no "already covered by my superset" route here: that judgment needs Step 1's inventory, which hasn't run yet — calling it from memory of the stack is the anchoring failure this skill exists to prevent. Superset kills emerge naturally after Step 3.

Neither route qualifies → run the default path, Steps 1-6.

**Narrow-scope re-invocation** — when the user explicitly limits scope (e.g. "只評估這幾條規則、不要重做整個 repo 研究"), Blocks 1-4 may be skipped, but never the accounting: the output must still end with a minimal ledger — one line stating the declared scope and which gates were skipped because of it, plus a Verdict line naming the evidence the judgment rests on. A narrow answer with zero ledger is unauditable afterward (this exact hole showed up in the 2026-07-20 i-have-adhd re-invocation). Then run Step 7 Self-Verify as usual — R4 has a matching exception.

**退役／缺口盤點路徑** — when the user asks what remains missing before retiring or replacing an existing pack, run the full Steps 1–6 but change the presentation shape. The chat main report is exactly `缺什麼／哪些已對應／退役前做哪三件`; 完整 Blocks 1–4 與 Gate Ledger 寫入證據副檔。This is not a narrow-scope shortcut: analysis and accounting stay complete, and Step 7 verifies the combined main-report-plus-sidecar draft.

### Step 1 — Inventory the existing stack (HARD GATE), then reconcile load-bearing rows

Before reading the tool's README / feature list, dispatch a **deep-explore agent** to enumerate what the user already has in the tool's domain and how mature each piece is. Do not inline this; the fan-out spans many files. Inventory targets (adapt to domain): settings.json hooks + `~/.claude/hooks/`, `~/.claude/skills/` + `~/.claude/commands/`, automation pipelines (launchd / cron / local-analysis routines), memory + wiki system, installed plugins/agent suites, project CLAUDE.md — and tools the user **tried and removed** in this domain with the documented reason (the strongest signal of what does not fit). For each capability: name the concrete mechanism precisely, maturity, current status.

Then reconcile **only the load-bearing rows** — the 2-4 rows whose maturity will be cited as a divisor in Block 2 or in the verdict. Reconciling the whole table is expensive and invites rubber-stamping; a stale row no decision rests on is harmless. Probe by capability type:

- CLI tool → `scripts/reconcile.sh <name>` (install state across PATH/uv/npm/brew/pipx + self-stack references)
- skill / agent → session jsonl invoke counts (file existence never counts as adoption — agents marked "mature" have turned out to have 0 spawns)
- hook → its audit/trace log
- scheduled job → launchd/cron last-run

Mark each reconciled row `install-verified` and/or `adoption-verified`; a row that fails either check gets its honest label ("installed, adoption unverified") instead of "mature". Done → Step 2.

### Step 2 — The tool's real value props, health, and precedent recall

Use research-before-answer discipline (personal wiki + memory recall in parallel with external `gh` / docs / web). Separate substance from marketing — star count, i18n, badges, sponsor funnels are not capabilities. Capture: actual mechanism, distribution model, license, activity, maintainer concentration.

Precedent recall is calibration, not ammunition: grep the memory store for **prior tool-evaluation cases with any outcome**, and pick the nearest by shape (tool type + claim structure), not by verdict direction — a calibration set that only ever cites rejections is a one-way ratchet. Before citing a precedent, check it still holds and state one of: holds / partially stale / stale (citation and write-back rules live in the memory file's 帳本記錄格式 section — the SSOT; follow it rather than restating it here). If the grep finds nothing, say "no prior precedent retrieved" — never invent a precedent to fill the slot. Done → Step 3.

### Step 3 — Point-by-point ÷ maturity mapping

For each tool capability, ask "does the user already have an equivalent, and at what maturity?" — map before judging. Each row's quotient is a conclusion, stated honestly whichever way it lands: `≈0` (existing equivalent at least as good), `<0` (re-litigates a settled rejection — flag explicitly), or `non-zero` (carries to Block 4). Done → Step 4.

### Step 4 — Best-frame search, with the pain gate

The tool's own marketing frame is only one candidate. Search the user's stack for the frame where the tool would land best. Three guardrails:

1. A frame must anchor to a **named Block 1 capability area** — invented frames can't be checked against anything.
2. Every candidate frame passes the **pain-vs-absence check**: name which Block 1 gap it closes or which divisor it upgrades. An uncovered area nobody has felt as pain is absence, not a gap — "the tool covers X and you don't have X" is not by itself a reason to adopt.
3. At most one alternative frame beyond the tool's own; "none found" is a legal and common answer.

Lesson this step exists for: graphify's winning frame (brownfield structural signal) was never proposed during its analysis — the user hit it themselves 12 days after a "definitive" rejection. Done → Step 5.

### Step 5 — Draft the verdict direction; extraction hunt on rejection drafts

Draft where this is heading: adopt / trial / extract / watch-defer / landscape. Heading to adopt or trial → skip the hunt (the whole tool is coming; nothing to steal separately) and go to Step 6. Heading to rejection/landscape → hunt for extractable pieces now, because Step 6.3's challenge pass will demand this step's output as evidence:

- Minimum protocol: read README / API surface / examples / config / hooks / CLI entrypoints.
- Output three columns per candidate: `stealable mechanism / graft point in the user's stack / reason rejected`.
- Closed-source or no public source → downgrade to API-level / architecture-concept assessment and say so (guessing at internals produces hallucinated steals).

Lesson: ocr's "the deterministic layer can't be stolen" flipped to "it's the easiest part to steal" only after the user pushed. The hunt is cheap; re-running the analysis after the user pushes is not. Done → Step 6.

### Step 6 — Verdict

1. **Finalize the draft** into one of five outcomes: adopt / trial / extract / watch-defer / landscape. watch-defer carries a revisit trigger (e.g. "ships a local CLI", "supports MCP", "stack develops X pain").
2. **Ambiguous zone definition (fail-closed)**: every rejection/landscape verdict that did not qualify at Step 0 is in the ambiguous zone. No self-classification out of it.
3. **Challenge pass** — runs on every ambiguous-zone rejection. Answer four fixed questions, plus one row "tool-specific axis" (may be "none, checked"):
   - Mechanism layer checked? (an idea-level rejection does not cover the implementation layer)
   - Alternative frame? (does Step 4's answer still hold now that the full picture exists)
   - Really nothing to steal? (point to Step 5's three-column output)
   - Cheaply testable — why untested? (discharge via the triage in 6.4)
   Any answer that flips → loop back to that step and redo from there.
4. **Testing triage + Gate Ledger**. Triage the "why untested" question into exactly one of:
   - `Runnable now` (install command exists + local input to run it on) → run it; paste output into the Gate Ledger. Install involved → a snapshot-before-install check first (its audit cost counts toward the budget; over budget → paper verdict allowed, marked "untested — audit cost"). After testing, the install is either removed or registered in trials/active.md — an unowned leftover install is how supply-chain debt accumulates.
   - `Runnable with user approval` → present the minimal test command + risk, wait.
   - `Not runnable cheaply` → name the blocking factor (paid account / interactive auth / missing data / hardware) + the exact command that would run if it were testable.
   A test that can't finish in-session → verdict marked `provisional` + executable test plan attached. A positive in-session result that needs a time dimension (frequency / retention / long-run cost) → upgrade to a trial verdict. Calibration: headroom's afternoon dry-run overturned a too-harsh paper sub-verdict; RTK's data-driven retirement is the trial-verdict analogue.
   Then emit the **Gate Ledger** block (see output-template) — Step 0 route + qualification, the four challenge answers one line each (checked → evidence pointer; unchecked → say so), triage outcome + test output. The ledger is what makes partial execution visible afterward; prose claims without artifacts don't survive an audit, and that is the point.
5. **Symmetric evidence obligations** — the adoption-first posture must not become an over-recommendation machine, so action verdicts carry their own paperwork:
   - rejection (ambiguous zone): show the work — frames tried, test output, extraction three-columns — plus "what evidence would overturn this".
   - trial: KPI + review date + kill condition + register the H2 entry in `~/Desktop/projects/.claude/trials/active.md` (`## <name> (YYYY-MM-DD)`) yourself；新 entry 只在 H2 下留 `started`／`status`／`detail` 三個索引欄位，長段寫 `trials/active/<slug>-<started>.md`，detail 缺失就停並回報 — 未登記的 trial 沒有 review reminder。
   - extract: named file/mechanism + graft point + next action. "Worth stealing" with no landing site is not an extract verdict.
6. **Action exit + ledger write-back** (both are steps, not afterthoughts):
   - Close with "the cheapest path to value" or "the test that would settle it". "None — overturn condition: X" is a legal value; Step 0 fast-kills skip the action path entirely (padding an honest kill makes the tool look more useful than the arithmetic says).
   - Write the verdict back to the precedent log in frame-scoped format. This skill **auto-writes** — a deliberate exception to the ask-first memory convention, because the graphify ledger sat stale for 7 weeks under ask-first and misled a later session. One guard: if this run is a bench / probe / simulation (the prompt supplied fabricated inventory facts, or says "測試環境"), skip the write-back and state that — a synthetic verdict in the real ledger is a fabricated precedent that later sessions will cite. trial/extract entries get `pending-outcome` + a pointer to their follow-up ledger. Re-evaluating a tool under a new frame requires a stated delta (what changed on the tool side or the stack side); 3 frame-scoped rejections + zero residuals → mark the tool `exhausted` (soft seal — new delta evidence reopens). Keep rows short; details go to a `[[reference_*]]` file. Full format rules: memory 帳本記錄格式 section (SSOT).

Verdict 定案、write-back 落帳後，完成後接 Self-Verify：Done → Step 7. 不要跳過 Step 7 直接把報告呈給使用者。

### Step 7 — Self-Verify（mandatory — 報告寫完後、呈給使用者前）

報告按 Output contract 草擬完成後，**必須**派一個 verify subagent 檢查報告是否遵守本 skill 的規矩，才進 Step 8。不可跳過、不可用「這次是 fast-kill 短版」為由省略（短版一樣驗，R4 有短版例外條款）。

Dispatch 規格：

- 報告草稿先落到唯讀快照檔（session scratchpad 或持久證據副檔，`chmod 444 <path>`）並以 `wc -l < <path>` 取得實際總行數 `{lines}`；草稿同時包含聊天主報告與完整證據副檔內容（預設路徑與退役／缺口盤點路徑皆然）
- `Agent` tool、`subagent_type: skill-verify-auditor`（sonnet+low、tools 僅 Read，定義檔釘死）
- description 固定含 marker 字串 `skill-verify:check-my-stack`（採用率統計 grep 用，不要改字）
- prompt 開頭固定放 `AUDIT_INPUT_MODE: FILE_SNAPSHOT`、`SNAPSHOT_PATH: {path}`、`SNAPSHOT_TOTAL_LINES: {lines}` 三行標頭，再接下方 template 全文（`skill-verify-auditor` 定義檔規定未帶這三行時不啟用讀檔模式、直接拒讀並全判 FAIL）

Verify prompt template（原文嵌入、`{path}` 換成報告草稿絕對路徑、`{lines}` 換成該檔實際總行數正整數）：

```
AUDIT_INPUT_MODE: FILE_SNAPSHOT
SNAPSHOT_PATH: {path}
SNAPSHOT_TOTAL_LINES: {lines}

你是 adversarial 合規審查員。用 Read 從第 1 行讀到第 {lines} 行讀取 SNAPSHOT_PATH，檢查這份競合分析報告是否遵守 check-my-stack skill 的規矩。偏置是「找違規」：無法確認有遵守就判 FAIL，不要善意推定。輸出第一行固定回報 `READ_RANGE: 1-{lines} / {lines}`，接著輸出 R1–R5 與最後一行 VERDICT。

逐條檢查（每條回 PASS / FAIL / EVIDENCE-UNAVAILABLE + 一句證據引述）：

R1【對帳有真的跑】load-bearing 列（被 Block 2 或 verdict 引為分母的列）的 Reconciled 標記是否引用了真實 probe 輸出（scripts/reconcile.sh 結果 / session jsonl invoke counts / hook log / launchd last-run）而非只填標籤？且報告若引用 precedent，是否標了三態之一（holds / partially stale / stale）？明寫 "no prior precedent retrieved" 視同有落。任一缺 = FAIL。

R2【Gate Ledger】Gate Ledger block 是否存在且位於 Verdict 之前，7 行固定格式全在（Step 0 / Challenge 1-4 / Tool-specific axis / Test output）？每行是否有判定＋證據指針、或明寫 unchecked？缺行或空行 = FAIL。

R3【adoption 行為證據】maturity / adoption 判斷是否有行為證據支撐（invoke counts / 測試輸出 / log / last-run）？只引 memory 條目、文件宣稱、或以「檔案存在」當 adoption 證據 = FAIL；誠實標籤（"installed, adoption unverified"）= PASS。

R4【結構完整】報告是否照 output-template 順序完整：先用白話回答 → Block 1 → Block 2 → Block 3 → Block 4 → Gate Ledger → Verdict；白話開頭是否依序含六項（結論／它是什麼／跟你現有的差在哪／用了會得到什麼／代價／依結論二選一），且結論直接回答原問句，各 block 該有的表格欄位齊全？（例外一：Step 0 fast-kill 短版 = 白話回答 + Gate Ledger + Verdict，Gate Ledger 的 Step 0 行需載明 qualification。例外二：narrow-scope 短版 = 白話回答 + 最小帳（範圍限定 + 跳過的 gate 一行、Verdict 依據一行）。例外三：退役／缺口盤點路徑 = 聊天主報告含 `缺什麼／哪些已對應／退役前做哪三件`，同一草稿另含完整 Blocks 1–4、Gate Ledger 與 Verdict 作證據副檔；任一部分缺席 = FAIL。）

R5【anti-pattern】(a) Gate Ledger 的 testing triage 標 `Runnable now` 但 Test output 是 n/a / 空 = FAIL（paper verdict while runnable）；(b) 報告任何地方把 star / fork / i18n / sponsor badge 數字當能力證據引用 = FAIL。

三態判定與白名單：

某條的 FAIL 若屬「證據結構性取不到」，改判 EVIDENCE-UNAVAILABLE。結構性取不到只限以下四項（白名單，不得類推擴充）：

1. 規則要求引用既有 memory／先例，但實際 grep 結果為 0 命中
2. 規則要求貼測試輸出，但該項在本次條件下結構性不可執行，且報告已具名寫出阻塞因素
3. 規則要求對帳裝機狀態，但該工具未安裝且本次判決本身就是「不裝」
4. 規則要求引用行為數據，但該機制建立不足一個觀察週期、無數據可引

白名單不包含任何「沒做」或「做了但沒寫清楚」——那些一律照舊算 VIOLATIONS。

判 EVIDENCE-UNAVAILABLE 時，該條的證據句必須點名是白名單第幾項（例如「白名單第 1 項：memory grep 0 命中」），不可只寫「證據不足」。

verdict 三態判定：

- 沒有任何 FAIL 或 EVIDENCE-UNAVAILABLE → COMPLIANT
- 有非 PASS 條目，且**全部**都是 EVIDENCE-UNAVAILABLE（即全部落在白名單）→ NEEDS_HUMAN_REVIEW，列出這幾條編號
- 有任何一條 FAIL（不在白名單）→ VIOLATIONS，列出所有非 PASS 條目的編號（含 EVIDENCE-UNAVAILABLE 的那幾條）

輸出格式（固定，最後一行必須是 verdict 行）：

R1: PASS|FAIL|EVIDENCE-UNAVAILABLE — <一句證據>
R2: PASS|FAIL|EVIDENCE-UNAVAILABLE — <一句證據>
R3: PASS|FAIL|EVIDENCE-UNAVAILABLE — <一句證據>
R4: PASS|FAIL|EVIDENCE-UNAVAILABLE — <一句證據>
R5: PASS|FAIL|EVIDENCE-UNAVAILABLE — <一句證據>
<verdict 行，形狀見下>

verdict 行三選一，整行照抄其中一種、只把 <> 換成編號：

VERDICT: COMPLIANT
VERDICT: NEEDS_HUMAN_REVIEW: <R 編號逗號列表>
VERDICT: VIOLATIONS: <R 編號逗號列表>

這三行是三個候選、不是可以並列。下游用 grep 取這一行做二值判讀，行內出現第二個 verdict 名稱、`|`、括號補述或「若…則…」條件句，解析會同時拿到兩個互斥狀態。保留意見寫進該條的證據句，不要寫進 verdict 行。

判 NEEDS_HUMAN_REVIEW 之前先掃一次 R1–R5：只要還有任何一條寫著 FAIL，這輪就是 VIOLATIONS；一個 EVIDENCE-UNAVAILABLE 都沒有時，NEEDS_HUMAN_REVIEW 不可能成立。「這條 FAIL 我不確定算不算數」是不確定、不是證據取不到——判 FAIL、寫 VIOLATIONS，把保留意見放進該條證據句。
```

Verify 結果處理：退役／缺口盤點路徑的 self-verify 狀態只寫進證據副檔；下列「訊息末尾」只套用其他路徑。

**本回合這個 skill 只有一次 auditor 額度**：不論結果如何都不得重派，也不得用 SendMessage 續問同一個 auditor。末尾那行的狀態只能是下列四個之一（`NEEDS_HUMAN_REVIEW` 是 auditor 的 verdict 值、不是收尾狀態，它走下面第二條）：

- 全 PASS → 進 Step 8，訊息末尾附一行「🔎 self-verify: COMPLIANT (5/5)」
- NEEDS_HUMAN_REVIEW（全部非 PASS 條目都落在白名單）→ 報告照發（照進 Step 8），末尾標「🔎 self-verify: COMPLIANT — NEEDS_HUMAN_REVIEW R#（白名單第 N 項：<一句話>）」。**不要為了消除這條而在報告裡補寫實際上取不到的內容**——證據結構性取不到就如實留著讓使用者判，硬掰一句話滿足規則是繞過驗證而不是通過驗證
- 任一 FAIL 且已修正 → **先修報告再進 Step 8**（補 probe 輸出 / 補 Gate Ledger 行 / 改回誠實 maturity 標籤 / 重排 block），修完不重驗、在 Step 8 訊息末尾如實列出「🔎 self-verify: FIXED_AFTER_AUDIT — R#（…）」並明寫「未經第二次獨立稽查」
- 任一 FAIL 且修不掉 → 末尾標「🔎 self-verify: FAILED — R#（缺口）」，並把該條支撐的判斷從 Verdict 刪除或收窄成「證據不足、無法判定」，不得保留原結論
- Verify subagent 失敗（timeout / 空輸出 / 格式錯誤 / agent error）→ 照進 Step 8、末尾標「🔎 self-verify: SKIPPED (agent error)」，不要靜默省略
- 政策禁派 Agent（system prompt 出現 `Do not call the AgentTool unless the user requested it` 一類禁令）→ 改由 main 依同一份 rubric inline 逐條判，末尾照常標 self-verify 行並加註「inline 執行」，證據副檔寫明降級原因。降級只換執行者、不換標準：每條仍要判、仍要附證據句，判不出來標 FAIL 或 EVIDENCE-UNAVAILABLE，不得整段省略或改標 SKIPPED

已知限制：verify agent 沒有對話 context，驗的是報告的形式面與證據引用形跡（有沒有 probe 輸出被貼、有沒有缺行），驗不了引用的輸出是否真的來自本 session 執行——那層仍靠 Gate Ledger artifact 紀律與使用者過目把關。

處理完 verify 結果 → Step 8（呈現報告）。

### Step 8 — 呈現報告

預設路徑聊天只輸出白話主報告與證據副檔連結：先依 output-template「先用白話回答」段的六項依序作答（結論直接回答使用者原問句），再對六項沒涵蓋到的原問句各給一段白話答案，最後一行 Verdict；完整 Blocks 1–4 與 Gate Ledger 寫入證據副檔，不貼回聊天（2026-08-20 Freebuff 兩個口語問題：白話開頭有了、Block 1–4 與 Gate Ledger 仍整包進聊天、使用者仍跟丟）。白話主報告不使用 extract／frame／Gate Ledger／商數／maturity／reconcile 等內部術語，末尾附上 Step 7 的 self-verify 狀態行。若使用者請求符合上方退役／缺口盤點路徑，聊天只輸出 `缺什麼／哪些已對應／退役前做哪三件` 與證據副檔連結，不把完整 blocks 或 self-verify 行貼回聊天。Write-back 已在 Step 6.6 完成，這裡不再動 ledger。

## Output contract

Produce the plain-language opening and exact block structure in [references/output-template.md](references/output-template.md) — read it before writing the report. It includes the Gate Ledger block.

## Division of labor with sibling decision lenses

This skill owns **competitive/borrow ordering and value discounting**. It is complementary to, not a replacement for, two other decision lenses the user maintains:

- "Install or not" (Path A / A' / B — prompt-injection vs teach-the-agent) — a separate install-decision lens. A cheap-trial install is trial-scoped and reversible; it does not pre-decide Path A/A'/B. Skill-install-only tools pass that lens before any test install.
- "Agent-in-loop vs background scraper applicability" — a separate suitability lens.

If those personal feedback memories exist, recall them by grepping the memory store; reference them, do not duplicate their logic here.

## Anti-patterns (reject these)

- ❌ Reading the tool README and listing highlights first, then back-filling where the user could apply them
- ❌ A borrow list of naked capabilities without dividing by existing maturity
- ❌ Assigning priority labels before the Step 1 inventory has run
- ❌ Treating star count / fork count / i18n / sponsor badges as evidence of capability
- ❌ Calling something "fills a gap" when it fails Step 4's pain-vs-absence check (absence is not pain)
- ❌ Citing a sibling or precedent case that was not actually retrieved in Step 2 (confabulated calibration to fill the template slot)
- ❌ Rejecting in the ambiguous zone without the challenge pass, or with Gate Ledger rows missing
- ❌ Shipping a paper verdict while the triage says `Runnable now`
- ❌ Citing precedent or maturity without reconciling against reality — the ledger is a claim, not evidence

## 踩過的坑

- agentsview：「資料在 jsonl 直接問 Claude」否決判準本身是 agent-facing 盲點，human-facing UI 缺口被遮蔽 → 驗證軸要含 agent/human 兩視角。
- brooks-lint：檔案存在 ≠ 被使用，0-spawn agent 被標 mature → 分母要 adoption-verified。
- PullMD ×2：退役工具相隔 10 天在兩個獨立 session 被當 mature 分母 → load-bearing 列必對帳。
- Trellis：Block 1 盤點漏了團隊在用的 OpenSpec，唯一殘值被使用者一句歸零 → 盤點漏項比工具高估更常見。
- dsh 報告（2026-08-14）：使用者只問兩個口語問題，輸出卻先給六段術語與完整帳本，結論被蓋住並觸發兩次 `/wait-what` → 呈現時先用 2–4 句白話直接回答原問句，再附完整證據結構。
