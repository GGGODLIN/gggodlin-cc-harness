---
name: hillclimb
description: Use when the user wants sustained, multi-round iterative optimization of a measurable metric (latency, throughput, memory, bundle size, accuracy, or score on a fixed test set) toward a target threshold — triggers include "/hillclimb", "用爬山法優化", "持續迭代壓低延遲", "跑多輪實驗調優這個指標", "對著測試集一路優化到目標分數". Do not use for one-off bug fixes or single-pass root-cause diagnosis (use debugging), building features from a spec (use implement), or running a single parallel N-candidate bakeoff without iterative refinement (use best-of-n-implement).
---

<!-- 本檔在契約測試底下：bash ~/.claude/skills/hillclimb/scripts/tests/hillclimb-contract.test.sh -->

# Hillclimb

Sustained, scientific single-variable optimization against a frozen measurement harness.

**Why this structure works:** Unstructured "find problems and optimize" loops fail in four predictable ways: the agent edits the benchmark to flatter its code, stacks new changes on top of a regression, mistakes run-to-run noise for a win, or forgets failed attempts after context compaction and tries them again. Freezing a sensitivity-proven harness first, reverting every non-winning round to the last winning commit, and logging both kept and reverted rounds in `decision.tsv` closes all four failure modes.

## Invocation and Trigger

- **Invocation capability**: Model-callable via `Skill(hillclimb)` and user-invocable via `/hillclimb`. Inbound pointers from `debugging` and `implement` route here when a one-off performance task turns into multi-round metric climbing.
- **Trigger condition**: Authoring guidance — choose this skill when there is a quantifiable metric, a repeatable test corpus or workload, and the goal requires trying multiple sequential hypotheses to improve the number.

## Process

### 1. Pin the metric, corpus, and isolated worktree baseline

1. Identify the single scalar metric, its winning direction (lower-is-better or higher-is-better), the target threshold (or maximum round budget), and the fixed input corpus or test suite that guards correctness.
2. Prepare a clean, isolated git worktree (or verify `git status --porcelain` is empty on a dedicated branch) and record `current_best_sha=$(git rev-parse HEAD)`. Never run a hillclimb loop inside a dirty shared worktree containing another session's uncommitted changes, because reverting a failed round would destroy unrelated work.

Done when: metric, direction, target/budget, correctness test command, isolated worktree path, and `current_best_sha` are explicitly recorded.

### 2. Build, prove sensitivity, and freeze the measurement harness

1. 如果本次指標涉及延遲、吞吐量、CPU／記憶體或速度宣稱，就在執行基準量測前讀 `~/.claude/references/verification-recipes-and-probes.md` 的「效能宣稱核驗」，確保計時區間內工作真發生且 0 報錯、正式環境入口與參數對齊，並測量基準中位數與雜訊區間（noise band）。
2. 如果本次目標是要大幅重寫「純計算、確定性、無外部 I/O 依賴」的核心或解析器，且既有測試對語意邊界覆蓋薄弱，就在凍結量測尺前讀 `~/.claude/references/verification-recipes-and-probes.md` 的「純計算／解析器爬山前導配方」（外層熱點鎖定、原函式當標準答案機與衍生邊界網）。
3. **Prove harness sensitivity before trusting it**: 如果本次新建或修改了量測腳本或自訂評分比較器，就在凍結量測尺前讀 `~/.claude/references/verification-recipes-and-probes.md` 的「驗證配方維護」第 3 點，在隔離副本中故意引入一個已知退步或錯誤輸出，確認量測尺能抓出退步且正確性檢查會報紅燈，測試後立即還原。
4. **One-time human checkpoint to freeze the ruler**: Present the baseline metric, noise band, exact harness command, correctness command, and sensitivity proof to the user once (`「量測尺與基準已驗證（基準 <X>、雜訊 ±<Y>），確認鎖定這支量測尺後我就連續跑爬山迴圈，可以嗎？」`). Wait for approval before starting Step 4 (unless the user already approved the exact harness command in the opening prompt).
5. Once approved, the measurement harness, input corpus, and correctness assertions are **frozen (read-only)** for the rest of the run. Never modify the ruler, loosen an assertion, or filter out slow cases mid-climb.

Done when: baseline median and noise band are measured, sensitivity proof passed on an isolated copy and was restored, human approval to freeze the harness is obtained, and the harness files are locked read-only.

### 3. Initialize `decision.tsv` outside git tracking

Create `<scratchpad>/decision.tsv` (or a gitignored path outside the target repo's tracked tree) with this exact 8-column header and row `0`:

```tsv
iter	hypothesis	change	before	after	delta	tests	verdict
0	baseline	initial state at <current_best_sha>	<baseline>	<baseline>	0	pass	baseline
```

Why outside git: reverting a losing round in the target worktree must not erase the record of why that round failed.

Done when: `decision.tsv` exists outside git tracking with the 8-column header and row `0` recorded.

### 4. Run the single-variable keep / revert loop

Main session stays lean as supervisor: dispatch a `routed-impl` subagent for multi-file edits or heavy profiling so raw traces do not flood main context. On each iteration `i = 1..N`:

1. **Read `decision.tsv` in full first**: Check every prior `keep` and `revert` row before choosing the next hypothesis so context compaction never causes you to retry a dead end.
2. **Form one falsifiable hypothesis and change one variable**: State what bottlenecks the metric and why this single change should move it by more than the noise band. Apply only that single change on top of `current_best_sha`.
3. **Run correctness tests, then the frozen harness**:
   - If correctness tests fail, output diverges, or the metric does **not** beat `before` by more than the noise band → **`verdict = revert`**.
   - If correctness tests pass AND the metric beats `before` beyond the noise band → **`verdict = keep`**.
4. **Act on the verdict immediately**:
   - On **`keep`**: Commit the change (`git commit -m "perf(<scope>): <change> (<before> -> <after>)"`), update `current_best_sha=$(git rev-parse HEAD)`, and set `before = after` for the next round.
   - On **`revert`**: Reset the isolated worktree back to `current_best_sha` (reverting tracked diffs against `current_best_sha` and removing any new untracked files created in round `i`), then verify `git status --porcelain` is empty and `HEAD == current_best_sha`. Never stack round `i+1` on top of a reverted round.
5. **Append one row to `decision.tsv`** recording `iter`, `hypothesis`, `change`, `before`, `after`, `delta`, `tests` (`pass`/`fail`), and `verdict` (`keep`/`revert`).
6. **Check stopping criteria**: Stop when (a) the target threshold is achieved, (b) the iteration budget is reached, or (c) 3 consecutive iterations across distinct mechanisms fail to beat the baseline.

Done when: a stopping criterion is met, the isolated worktree is clean at the latest `current_best_sha`, and every executed round (both `keep` and `revert`) has a corresponding row in `decision.tsv`.

### 5. Hand back the verified trajectory

Report in the final message:
1. **Metric summary**: metric name, target, baseline → final (`delta` and `%` improvement), noise band, and total iterations (`kept` vs `reverted`).
2. **Accepted wins**: each `keep` commit SHA with its one-line change and measured delta.
3. **Full experiment ledger**: inline or link the complete `decision.tsv` (including all `revert` rows and why they failed) so the user sees what was ruled out.
4. **Next hypothesis**: the highest-leverage idea left on the table if further climbing is needed.

Done when: all four items are present in the final chat message and `git rev-parse HEAD` matches the last `keep` row (or initial `baseline` if 0 wins).
