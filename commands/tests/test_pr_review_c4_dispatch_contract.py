#!/usr/bin/env python3

import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMAND_PATH = Path(os.environ.get("PR_REVIEW_COMMAND_PATH", ROOT / "commands/pr-review.md"))
AGENT_PATH = Path(os.environ.get("SPEC_COMPLIANCE_AGENT_PATH", ROOT / "agents/spec-compliance-reviewer.md"))


class PrReviewC4DispatchContractTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.command = COMMAND_PATH.read_text()
    cls.agent = AGENT_PATH.read_text()
    start = cls.command.index("- **`spec-compliance-reviewer`**")
    end = cls.command.index("### Codex Review", start)
    cls.c4 = cls.command[start:end]

  def test_c4_dispatch_uses_one_deterministic_envelope(self):
    self.assertIn("pr-review-c4.py dispatch-envelope", self.c4)
    self.assertIn("single deterministic dispatch envelope", self.c4)
    self.assertIn("four fields copied byte-for-byte from `envelope.agent`", self.c4)
    self.assertIn("envelope.runtime_input", self.c4)
    self.assertIn("single-use permit", self.c4)
    self.assertIn("consumes the current session's permit exactly once", self.c4)
    self.assertIn("field set is exactly those four keys", self.c4)
    self.assertIn("do not add `resume`, `run_in_background`, `isolation`", self.c4)

  def test_source_preflight_precedes_envelope_and_preserves_result_validation(self):
    preflight = self.c4.index("pr-review-c4.py preflight-sources")
    envelope = self.c4.index("pr-review-c4.py dispatch-envelope")
    validation = self.c4.index("pr-review-c4.py validate")
    self.assertLess(preflight, envelope)
    self.assertLess(envelope, validation)
    for marker in (
      "same host-side Git context used by validate",
      "unchanged per-target `targets` map",
      "120,000-byte whole-source limit",
      "issues no envelope or permit",
      "does not replace the later `validate` call",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.c4)

  def test_main_session_has_no_prompt_or_schema_authoring_step(self):
    self.assertIn("does not write, append, summarize, or reinterpret", self.c4)
    self.assertNotIn("Copy that two-line stdout block verbatim", self.c4)
    self.assertNotIn("Instruct each finding's", self.c4)
    self.assertNotIn("Mark all packet text", self.c4)

  def test_runtime_input_reuses_envelope_packet_identity(self):
    self.assertIn("do not reconstruct its dispatch ID, packet, model, or effort fields", self.c4)
    self.assertIn("All six final fields", self.c4)
    self.assertIn("equals the prompt regenerated from `envelope.runtime_input.packet`", self.c4)

  def test_agent_contract_matches_envelope_shape(self):
    for marker in (
      "Do not use tools",
      "Return exactly one JSON object",
      '"contract_accounting"',
      '"findings"',
      '"spec_file_accounting"',
      '"summary"',
      '"errors"',
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.agent)
    self.assertNotIn('"observations"', self.agent)

  def test_web_gpt_axis_collects_the_specified_conversation(self):
    axis_line = next(line for line in self.command.splitlines() if line.startswith("**加選軸"))
    collector = axis_line.split("再用 `", 1)[1].split("` 收", 1)[0]
    self.assertEqual(
      "web-cli chatgpt detail <id> --markdown true -f json",
      collector,
    )
    self.assertNotIn("web-cli chatgpt read --conversation", axis_line)

  def test_web_gpt_axis_never_waits_on_detail_stabilization(self):
    axis_line = next(line for line in self.command.splitlines() if line.startswith("**加選軸"))
    collector = axis_line.split("再用 `", 1)[1].split("` 收", 1)[0]
    self.assertNotIn("--wait true", collector)
    self.assertNotIn("--stable", collector)
    self.assertIn("不要對 detail 用 `--wait true`", axis_line)

  def test_multi_target_packet_is_assembled_from_step_205_state(self):
    for marker in (
      "Step 2.05 preparation state",
      "one `dispatch_id` and one dispatch for the whole set",
      "not multiplied by the number of targets",
      "never enter the reviewer packet",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.c4)

  def test_multi_target_bindings_must_reference_declared_targets(self):
    for marker in (
      "naming one of the targets declared",
      "canonical `target_identity`",
      "per-target",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.c4)

  def test_multi_target_validate_consumes_targets_map_per_target(self):
    for marker in (
      "`targets` map",
      "that target's own `review_root`, `authored_diff_base`, and `review_head`",
      "fails closed",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.c4)

  def test_c4_admission_stamps_target_identity_before_group_routing(self):
    for marker in (
      "exactly one authored code binding target",
      "`C4_CODE_TARGET_AMBIGUOUS`",
      "`group_findings`",
      "`reducer_validated`",
      "main forwards this projection unchanged",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.c4)

  def test_gate_reads_each_target_root_from_preparation_state(self):
    start = self.command.index("## Step 2.65")
    end = self.command.index("## Step 2.7", start)
    gate = self.command[start:end]
    for marker in (
      "$PREPARATION_PATH",
      "canonical `target_identity`",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, gate)

  def test_gate_reducer_input_carries_diff_range_and_declared_reason_codes(self):
    start = self.command.index("## Step 2.65")
    end = self.command.index("## Step 2.7", start)
    gate = self.command[start:end]
    reducer = gate[gate.index("resolve-authority"):]
    for marker in (
      "`authored_diff_base`",
      "`review_head`",
      "reads the repo profile `authority` itself from the review root's origin remote",
      "main passes no glob",
      "required only when the candidate matches `authority.change`",
      "a profile it cannot read counts as no declaration",
      "`C4_CURRENT_AUTHORITY_RESOLVED`",
      "`C4_CHANGE_DELTA_AUTHORITY_RESOLVED`",
      "added or modified in this PR",
      "`C4_AUTHORITY_PATH_NOT_ALLOWED`",
      "matches neither list",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, reducer)

  def test_agent_input_contract_describes_target_qualified_packet(self):
    self.assertIn("a `target_identity` field on every clause", self.agent)
    self.assertIn("mixed qualified／unqualified entries are invalid", self.agent)
    self.assertIn("declared targets", self.agent)
    self.assertIn("its own target's Git context", self.agent)
    self.assertIn("Do not use tools", self.agent)
    for marker in (
      "REVIEW_SELECTION",
      "模型／執行路徑為列、審查角度為欄",
      "初次 reviewer 席位",
      "selected | not-selected | cancelled | unavailable | needs-material",
      "推薦不等於必跑",
      "typescript-reviewer",
      "python-reviewer",
      "code-reviewer",
      "security-reviewer",
      "spec-compliance-reviewer",
      "Codex 中性",
      "Codex 對抗",
      "Gemini Flash",
      "Gemini Pro",
      "web GPT Pro",
      "Formal spec gate",
      "React-doctor",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.command)

  def test_dispatch_uses_only_selected_seats_without_hidden_primary_defaults(self):
    dispatch_start = self.command.index("## Step 3: Dispatch Dual Reviews")
    dispatch_end = self.command.index("## Step 4: Cross-Axis Verification Pass", dispatch_start)
    dispatch = self.command[dispatch_start:dispatch_end]
    for marker in (
      "只對 `REVIEW_SELECTION` 中 `status=selected` 的席位派工",
      "未選定或 cancelled 的席位不得派工",
      "不把 preset 當成使用者選擇",
      "Claude 側席位依 Step 2.98 的推薦與適用條件自動選入，不需要使用者逐席點名",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, dispatch)
    self.assertNotIn("preset 一律含對抗", dispatch)


class PrReviewAutoSelectionContractTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.command = COMMAND_PATH.read_text()
    cls.matrix = cls.between("## Step 2.98: Review Selection Matrix", "### 2.98.1")
    cls.shared = cls.between("#### Shared prompt to primary and general domain CC reviewers", "#### Consolidating CC-side findings")
    cls.baseline = cls.between("## Step 2.8:", "## Step 2.9:")
    cls.dispatch = cls.between("## Step 3: Dispatch Dual Reviews", "### CC Review (Multi-Agent Routing)")
    cls.routing = cls.between("### CC Review (Multi-Agent Routing)", "#### Chunked dispatch")
    cls.language = cls.between("#### Primary Language Reviewer (recommendation only)", "#### Parallel Domain Reviewers")

  @classmethod
  def between(cls, start_marker, end_marker):
    start = cls.command.index(start_marker)
    end = cls.command.index(end_marker, start)
    return cls.command[start:end]

  def test_claude_side_seats_are_selected_from_the_recommendation_without_waiting(self):
    for marker in (
      "矩陣照常列出，作為揭露，不是等回覆的停點",
      "Claude 側席位",
      "照推薦與適用條件直接轉成 `selected`，不等回覆",
      "語言 reviewer",
      "符合 `ANGLE_ELIGIBILITY` 觸發條件的 security-reviewer",
      "`gate=ELIGIBLE` 且 evidence requirements 通過的 spec-compliance-reviewer",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.matrix)
    self.assertNotIn("推薦只在 user 說「照推薦」時轉成 `selected`。未回覆不等於接受推薦。", self.matrix)

  def test_extra_quota_seats_run_only_on_explicit_selection_and_are_disclosed_otherwise(self):
    for marker in (
      "**外部額度席**（Codex 中性、Codex 對抗、Gemini Flash、Gemini Pro、web GPT Pro 與任何 Fable 席）",
      "只在叫用指令或派工前的回覆明確選了才轉成 `selected`",
      "沒選的外部額度席保持 `status: not-selected` 與 `recommendation: recommended`，報告標「推薦但未選」",
      "不新增欄位",
      "之後要補跑，再叫用 `/pr-review` 並在指令點名席位",
      "Step 2.52／4.7",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.matrix)
    self.assertIn("只用 Codex 中性", self.matrix)

  def test_unattended_run_keeps_claude_seats_and_records_skipped_only_when_nothing_dispatches(self):
    for marker in (
      "無人值守且沒有保存的選擇時，Claude 側席位照跑、外部額度席不派，也不記 `REVIEW_SELECTION=SKIPPED`",
      "只有一個席位都派不出才記 `REVIEW_SELECTION=SKIPPED`",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.matrix)
    self.assertNotIn("沒有就標 `REVIEW_SELECTION=SKIPPED`，不派任何 reviewer", self.matrix)

  def test_cancel_or_replace_in_the_invocation_and_late_replies(self):
    for marker in (
      "叫用時明說取消或替換 Claude 側席位就照辦",
      "派出後才到的回覆只影響還沒派出的席位",
      "已派出的席位照常完成，並在報告「這次審查範圍」揭露",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.matrix)
    self.assertIn("派出後才到的回覆只影響還沒派出的席位", self.dispatch)

  def test_saved_selection_from_before_this_change_is_read_as_is(self):
    for marker in (
      "改版前已明確保存的 `REVIEW_SELECTION` 照原格式讀取並照用，schema 不變",
      "status: selected | not-selected | cancelled | unavailable | needs-material",
      "recommendation: recommended | optional",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.matrix)
    fields = [line.strip() for line in self.matrix.split("REVIEW_SELECTION:\n", 1)[1].split("```", 1)[0].splitlines() if line.strip()]
    self.assertEqual(
      [line.split(":", 1)[0].lstrip("- ") for line in fields],
      ["path", "model", "effort", "angle", "status", "recommendation", "reason"],
    )

  def test_dispatch_checklist_and_routing_follow_the_two_layer_authority(self):
    for marker in (
      "Claude 側席位依 Step 2.98 的推薦與適用條件自動選入，不需要使用者逐席點名",
      "外部額度席只在叫用指令或派工前的回覆明確選了才派",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.dispatch)
    self.assertNotIn("含 2.8 baseline", self.dispatch)
    self.assertIn("範圍三欄", self.dispatch)
    self.assertNotIn("not authorization", self.routing)
    self.assertIn("never select an external-quota seat", self.routing)
    self.assertIn("automatic Claude-side selection", self.language)

  def test_shared_prompt_carries_scope_fields_and_a_catalog_pointer_not_the_checklist(self):
    for marker in (
      "審查根目錄",
      "審查對象",
      "比較範圍",
      "由 /pr-review 派出",
      "~/.claude/review-standards/catalog.md",
      "挑選步驟",
      "references/review-dispatch-principles.md",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.shared)
    for gone in (
      "Redundant state",
      "Speculative Generality",
      "Stringly-typed",
      "Hot-path bloat",
      "full Step 2.8 checklist verbatim",
    ):
      with self.subTest(gone=gone):
        self.assertNotIn(gone, self.command)

  def test_comparison_range_reuses_the_base_and_trunk_derivation(self):
    for marker in (
      "origin/$BASE_BRANCH...origin/$PR_BRANCH",
      "PR 自己的 base，不是 trunk",
      "Step 2.55",
      "不另立規則",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.shared)

  def test_range_mode_and_multi_target_fill_the_scope_fields_per_target(self):
    for marker in (
      "範圍模式",
      "`start.sha`",
      "`end.sha`",
      "逐目標",
      "`$PREPARATION_PATH`",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.shared)

  def test_step_2_8_is_a_pointer_to_the_catalog_groups(self):
    for group in (
      "pr-review-baseline-reuse",
      "pr-review-baseline-quality",
      "pr-review-baseline-efficiency",
      "pr-review-baseline-design-decay",
      "pr-review-baseline-dependency-bumps",
    ):
      with self.subTest(group=group):
        self.assertIn(f"`{group}`", self.baseline)
    self.assertIn("由 `/pr-review` 派出時必套", self.baseline)
    self.assertIn("Do NOT inject this checklist into Codex's prompt", self.baseline)
    self.assertLess(len(self.baseline.splitlines()), 20)

  def test_scope_statement_no_longer_claims_to_own_the_baseline(self):
    scope = self.between("**Scope**:", "**報告標籤**")
    self.assertNotIn("IS defined here", scope)
    self.assertNotIn("injected into every selected CC reviewer", scope)
    self.assertIn("review-standards", scope)
    self.assertIn("pr-review-baseline-", scope)
    self.assertIn("must-report.md", scope)
    intro = self.between("Orchestrate a PR review", "**Scope**")
    self.assertNotIn("dispatching only the explicitly selected cells", intro)


if __name__ == "__main__":
  unittest.main()
