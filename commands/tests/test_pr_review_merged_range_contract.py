#!/usr/bin/env python3

import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMAND_PATH = Path(os.environ.get("PR_REVIEW_COMMAND_PATH", ROOT / "commands/pr-review.md"))


class PrReviewMergedRangeContractTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.command = COMMAND_PATH.read_text()

  def section(self, start_marker, end_marker):
    start = self.command.index(start_marker)
    end = self.command.index(end_marker, start)
    return self.command[start:end]

  def range_prep(self):
    return self.section("## Step 2.06", "## Step 2.1")

  def test_header_marker_lists_this_suite(self):
    head = self.command[:self.command.index("## Input")]
    self.assertIn("python3 test_pr_review_merged_range_contract.py", head)
    self.assertIn("`--merged` 範圍模式另有第十二套 `commands/tests/test_pr_review_merged_range_contract.py`", head)
    self.assertIn("> `python3 ~/.claude/commands/tests/test_pr_review_merged_range_contract.py`", head)

  def test_input_and_step1_accept_merged_without_widening_the_list(self):
    head = self.section("## Input", "## Step 1: Parse Input")
    self.assertIn("`/pr-review --merged <PR URL...> [--since <owner/repo>=<SHA> ...]`", head)
    step = self.section("## Step 1: Parse Input", "## Step 2: Fetch PR Data")
    self.assertIn("範圍模式輸入（`--merged`）", step)
    self.assertIn("v1 只支援 GitHub", step)
    self.assertIn("每個 repo 內的 PR 必須合入同一條目的分支", step)
    self.assertIn("`--since` 跨 repo 時必須逐 repo 寫 `<owner/repo>=<SHA>`", step)
    self.assertIn("不自動擴大 PR 清單", step)
    self.assertIn("完成後接 Step 2.06", step)

  def test_range_preparation_sits_between_multi_target_prep_and_input_basis(self):
    for earlier, later in (
      ("## Step 2.05", "## Step 2.06"),
      ("## Step 2.06", "## Step 2.1"),
    ):
      with self.subTest(earlier=earlier, later=later):
        self.assertLess(self.command.index(earlier), self.command.index(later))

  def test_range_preparation_wires_prepare_fields(self):
    step = self.range_prep()
    for needle in (
      "pr-review-targets.py prepare",
      '"merged": true',
      '"since"',
      '"reports_root"',
      '"start_report"',
      '"merge_commit"',
      "mergeCommit",
    ):
      with self.subTest(needle=needle):
        self.assertIn(needle, step)

  def test_confirmation_shows_r_source_and_candidates_before_dispatch(self):
    step = self.range_prep()
    self.assertIn("派工前確認", step)
    for needle in ("`start.source`", "`start_candidates`", "`start.sha`", "`end.sha`", "`review_diff.file`"):
      with self.subTest(needle=needle):
        self.assertIn(needle, step)
    self.assertNotIn("靜默改走 fallback", step)
    self.assertIn("`START_REPORT_NOT_CANDIDATE`", step)
    self.assertIn("確認內容要明寫這次綁定沒採用", step)
    self.assertIn("未確認不派工", step)
    self.assertIn("authorize-dispatch", step)
    self.assertLess(step.index("pr-review-targets.py prepare"), step.index("派工前確認"))
    self.assertLess(step.index("派工前確認"), step.index("worktree add"))

  def test_confirmation_lists_the_adversarial_over_cap_reason(self):
    step = self.range_prep()
    confirm = step[step.index("派工前確認（範圍）"):step.index("逐範圍目標建 worktree")]
    self.assertIn("precheckAdversarialAxis", confirm)
    self.assertIn("`input-over-cap`", confirm)
    self.assertIn("使用者接受也不能繞過", confirm)

  def test_range_worktree_is_checked_out_at_t(self):
    step = self.range_prep()
    self.assertIn('worktree add --detach "$REVIEW_ROOT" "$RANGE_T"', step)
    self.assertIn('[ "$(git -C "$REVIEW_ROOT" rev-parse HEAD)" = "$RANGE_T" ]', step)

  def test_no_net_diff_is_not_a_pass(self):
    step = self.range_prep()
    self.assertIn("NO_NET_DIFF", step)
    self.assertIn("本次沒有淨差異可審", step)
    self.assertIn("不宣稱歷史 PR 已審查通過", step)

  def test_known_limit_is_in_range_section(self):
    self.assertIn("不支援同時跑兩輪", self.range_prep())

  def test_range_mode_disables_provenance_and_calibration_only_for_range(self):
    calibration = self.section("## Step 2.2", "## Step 2.5")
    self.assertIn("範圍模式（`kind: range`）不載入任何作者校準檔", calibration)
    self.assertIn("File exists → load the author's entries", calibration)
    provenance = self.section("## Step 2.55", "## Step 2.6")
    self.assertIn("範圍模式（`kind: range`）不跑本步", provenance)
    self.assertIn("不做 authored／inherited 判定", provenance)
    self.assertIn("不套 inherited cap 參考用降級", provenance)
    self.assertIn("inherited 檔上的 finding 視同範圍外", provenance)

  def test_c4_uses_r_as_authored_base_and_reports_changed_hunks_only(self):
    step = self.section("- **`spec-compliance-reviewer`** — dispatch only", "#### Shared prompt to primary")
    self.assertIn("範圍模式的 authored base 為 R", step)
    self.assertIn("`binding_context.authored_diff_base` = `start.sha`", step)
    self.assertIn("`review_head` = `end.sha`", step)
    self.assertIn("C4 只涵蓋變更區段", step)
    self.assertIn("derive C4 authored line ranges from `git diff --unified=0 origin/$TRUNK_BRANCH origin/$PR_BRANCH`", step)

  def test_range_shared_prompt_adds_two_sentences(self):
    step = self.section("#### Shared prompt to primary", "#### Consolidating CC-side findings")
    self.assertIn("受影響流程中未改程式可回報並說明關係", step)
    self.assertIn("跨目標介面相依時核對輸出 → 型別 → 使用端", step)
    self.assertIn("範圍模式", step)

  def test_axes_read_the_prepared_review_diff(self):
    sem = self.section("## Step 2.9", "## Step 2.95")
    self.assertIn('sem-pr-blast-radius.sh "$REVIEW_ROOT" "$RANGE_R" "$REVIEW_DIFF_FILE"', sem)
    self.assertIn('sem-pr-blast-radius.sh "$REVIEW_ROOT" "origin/$BASE_BRANCH"', sem)
    inventory = self.section("## Step 2.95", "## Step 2.96")
    self.assertIn("範圍模式的 F = 範圍目標的 `changed_files`", inventory)
    codex = self.section("#### 多目標整組材料（中性軸）", "### Codex Adversarial Review")
    self.assertIn("`review_diff.file`", codex)
    gemini = self.section("#### 多目標整組材料（Step 2.05 準備的多目標才跑；單輸入沿上方既有 Gemini 段）", "## Step 4:")
    self.assertIn("`review_diff.file`", gemini)
    coverage = self.section("## Step 4.5", "## Step 4.6")
    self.assertIn("`accounted_files`", coverage)
    self.assertIn("`coverage.unverified`", coverage)

  def test_range_report_uses_group_report_merged_range(self):
    step = self.section("## Step 4.8", "## Step 5: Compile")
    self.assertIn("範圍模式", step)
    self.assertIn('"mode": "merged-range"', step)
    self.assertIn("`no_net_diff`", step)
    self.assertIn("$REPORT_DIR/sets/set-<stable_id>-review.audit.draft.md", step)
    self.assertIn("C4 只涵蓋變更區段", step)
    self.assertIn("歸因三欄", step)
    self.assertIn("目前適用性欄未計算：`Target versions` 的 state 恆為 current，未檢查目的分支是否已越過 T（v2）", step)

  def test_range_mode_stops_before_step8(self):
    tail = self.section("## Step 7", "## Step 8")
    self.assertIn("範圍模式在 Step 7 結束、不接 Step 8", tail)
    self.assertIn("不修改 code、不 push、不建立或留言任何 PR", tail)
    self.assertIn("不接 Step 8", self.range_prep())


  def test_range_preparation_keeps_scope_and_failure_rules(self):
    step = self.range_prep()
    for needle in (
      "下游一律看 `target.kind` 分流",
      "--json state,baseRefName,headRefOid,author,mergeCommit",
      "`review_diff.file` 是唯一權威的已裁切 R→T 差異",
      "`--since` 解析失敗也不退回下一層起點",
      "不對它派工，其餘範圍目標照常",
      "jq -r '.end.sha'",
      "執行中目的分支前進也不替換已釘材料",
      "完成後接 Step 2.1",
    ):
      with self.subTest(needle=needle):
        self.assertIn(needle, step)

  def test_range_branches_in_prior_findings_c4_gate_and_sem(self):
    prior = self.section("## Step 2.52", "## Step 2.55")
    self.assertIn("範圍模式（`kind: range`）沒有單一 `PR_ID`", prior)
    gate = self.section("## Step 2.65", "### 2.65.1")
    self.assertIn("2.65.1 的 `AUTHORED_FILES` 改用該目標的 `changed_files`", gate)
    sem = self.section("## Step 2.9", "## Step 2.95")
    self.assertIn("jq -r '.start.sha'", sem)
    self.assertIn("jq -r '.review_diff.file'", sem)

  def test_range_report_payload_and_attribution_rules(self):
    step = self.section("## Step 4.8", "## Step 5: Compile")
    for needle in (
      '"no_net_diff": <prepare 輸出的 no_net_diff>',
      '"code_source"',
      '"introduction"',
      "缺失型 finding 設 `missing: true`、不把附近程式作者寫成責任人",
      "報告寫「本次沒有淨差異可審」",
    ):
      with self.subTest(needle=needle):
        self.assertIn(needle, step)

  def test_argument_hint_lists_merged_form(self):
    self.assertIn(
      'argument-hint: "<target-1> [<target-2> ...] | --merged <PR URL...> [--since <owner/repo>=<SHA> ...]"',
      self.command.splitlines()[2],
    )

  def test_range_preparation_fetches_destination_before_prepare(self):
    step = self.range_prep()
    self.assertIn("git -C <checkout> fetch origin <baseRefName>", step)
    self.assertIn("fetch 失敗就停整組並回報，不在過期的 ref 上跑 prepare", step)
    self.assertIn("gh repo view <owner/repo> --json id", step)
    self.assertLess(step.index("fetch origin <baseRefName>"), step.index("pr-review-targets.py prepare"))
    self.assertIn("不重新 fetch", step)

  def test_range_preparation_uses_checkout_as_repo_root_and_neutral_report_dir(self):
    step = self.range_prep()
    self.assertIn("每個範圍目標的 `checkout` 就是它的 repo root", step)
    self.assertIn("不用 cwd", step)
    self.assertIn('REPORT_DIR="$HOME/.claude/pr-review-reports"', step)
    self.assertIn("$REPORT_DIR/sets/set-<stable_id>-review.audit.draft.md", step)
    output = self.section("## Step 6: Output", "## Step 7")
    self.assertIn('範圍模式的 `REPORT_DIR` 固定是 `"$HOME/.claude/pr-review-reports"`', output)
    self.assertIn("範圍模式的 `$LOCAL_HEAD` 是該範圍目標的 `end.sha`", output)

  def test_range_start_precedence_is_explicit(self):
    step = self.range_prep()
    self.assertIn("`--since` > 本輪綁定的 `start_report` > 最早合併的 fallback", step)
    self.assertIn("該 repo 已有 `--since` 而綁定被忽略", step)

  def test_range_input_basis_binds_to_end_sha(self):
    step = self.section("## Step 2.1", "## Step 2.2")
    self.assertIn("範圍模式（`kind: range`）的 `review_input_basis`", step)
    self.assertIn("`gh repo view --json id`", step)
    self.assertIn("`source_sha` 與 `destination_sha` 都是 `end.sha`", step)
    self.assertIn("review root HEAD 等於 `end.sha`，且 T 來自 Step 2.06 步驟 1 的 fetch", step)

  def test_range_spec_detection_reads_specs_at_t(self):
    step = self.section("## Step 2.6", "## Step 2.65")
    self.assertIn("範圍模式（`kind: range`）", step)
    self.assertIn("各範圍目標 `changed_files` 的聯集", step)
    self.assertIn('git -C "$REVIEW_ROOT" ls-tree "<end.sha>"', step)
    self.assertIn('git show "<end.sha>:$path"', step)
    self.assertIn("git log --format='%an' <start.sha>..<end.sha> -- <spec paths>", step)
    self.assertIn("`related_prs` 的作者", step)
    self.assertIn('git -C "$REVIEW_ROOT" ls-tree "$PR_HEAD" -- "$path"', step)

  def test_react_doctor_is_skipped_in_range_mode(self):
    step = self.section("## Step 2.97", "## Step 2.98")
    self.assertIn(
      "`SKIPPED（範圍模式未接 react-doctor：--scope changed 以 merge-base 為基準，在已合併的 T 上會空掃）`",
      step,
    )
    self.assertIn("範圍模式（`kind: range`）不跑 react-doctor", step)

  def test_reduce_reply_example_carries_status_ok_and_dispositions(self):
    coverage = self.section("## Step 4.5", "## Step 4.6")
    example = coverage[coverage.index("```json"):]
    example = example[:example.index("```", 3)]
    self.assertIn('"status": "ok"', example)
    self.assertIn('"accounted_files"', example)
    self.assertIn('"disposition": "skipped"', example)
    self.assertIn("沒帶 `status: \"ok\"` 的回覆一律記 `FAILED`", coverage)
    self.assertIn("沒寫 `disposition` 視為已審", coverage)
    self.assertIn("`coverage.counts`", coverage)

  def test_report_header_writes_three_coverage_counts_for_range(self):
    header = self.section("### Report Structure", "## Spec 依據")
    self.assertIn("範圍模式照 `coverage.counts` 寫三個數字", header)
    self.assertIn("已審 A / 明確跳過 S / **未交代 U**", header)

  def test_range_group_payload_targets_come_from_prepare_not_reduce(self):
    coverage = self.section("## Step 4.5", "## Step 4.6")
    self.assertIn("範圍模式只取 `reduce` 的 `findings`、ledger 與 `coverage`", coverage)
    self.assertIn("不用 `reduce` 回傳的 `group_payload.targets`", coverage)
    report = self.section("## Step 4.8", "## Step 5: Compile")
    self.assertIn("不取 `reduce` 的 `group_payload.targets`", report)

if __name__ == "__main__":
  unittest.main()
