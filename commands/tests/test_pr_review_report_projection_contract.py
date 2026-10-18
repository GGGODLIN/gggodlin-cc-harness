#!/usr/bin/env python3

import os
import re
import unittest
from pathlib import Path


COMMAND_PATH = Path(os.environ.get("PR_REVIEW_COMMAND_PATH", Path.home() / ".claude/commands/pr-review.md"))


class PrReviewReportProjectionContractTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.command = COMMAND_PATH.read_text()
    start = cls.command.index("### Report Structure")
    opening = cls.command.index("````markdown", start)
    closing = cls.command.index("\n````", opening + len("````markdown"))
    cls.report_structure = cls.command[opening:closing]

  def test_step_five_defines_audit_as_canonical_and_main_as_projection(self):
    self.assertIn("拍板主報告＋完整證據副檔", self.command)
    self.assertIn("完整證據副檔是 Step 5 完整報告的 canonical copy", self.command)
    self.assertIn("**Report projection schema**: 2", self.report_structure)
    self.assertIn("**Report generation**: <YYYY-MM-DDTHH:MM:SSZ>", self.command)
    self.assertIn("F-01 finding_uid: <20-hex> action=<action>", self.report_structure)
    self.assertIn("inline=none", self.report_structure)
    self.assertIn("主報告只能由 deterministic projection helper 產生", self.command)
    self.assertIn("主報告保留 header（含 coverage／C4／axis state）", self.command)
    self.assertIn("Spec 依據完整內容只留在完整證據副檔", self.command)
    self.assertIn("不得新增模型呼叫", self.command)

  def test_step_six_transactionally_publishes_audit_and_main_from_draft(self):
    self.assertIn("唯一權威來源", self.command)
    self.assertIn("pr-<number>-review.audit.draft.md", self.command)
    self.assertIn("pr-<number>-review.audit.md", self.command)
    self.assertIn("pr-review-report-projection.py", self.command)
    step_six = self.command.index("## Step 6: Output")
    draft = self.command.index("pr-<number>-review.audit.draft.md", step_six)
    helper = self.command.index("pr-review-report-projection.py", draft)
    audit = self.command.index("pr-<number>-review.audit.md", helper)
    main = self.command.index("pr-<number>-review.md", audit)
    self.assertLess(draft, helper)
    self.assertLess(helper, audit)
    self.assertLess(audit, main)

  def test_no_op_comment_payloads_stay_in_audit_only(self):
    self.assertIn("`action=no-op` 的 inline-comment block 只留在完整證據副檔", self.command)
    self.assertIn("發現總覽仍保留所有 finding", self.command)

  def test_fable_shadow_trial_wiring_is_retired(self):
    self.assertIn("Model comparison trials do not run inside `/pr-review`", self.command)
    self.assertNotIn("#### 🔬 Fable 影子對照", self.command)
    self.assertNotIn("## Fable/opus 影子對照", self.command)
    self.assertNotIn("fable-shadow-ledger.jsonl", self.command)
    self.assertNotIn("skipped-chunked", self.command)
    self.assertNotRegex(self.command, re.compile(r'["\']?model["\']?\s*:\s*["\']?fable["\']?', re.IGNORECASE))

  def test_report_is_projected_from_the_selected_set(self):
    for marker in (
      "只投影 `REVIEW_SELECTION` 中 `status=selected` 的席位",
      "cancelled、not-selected、unavailable、needs-material 不得列為 PASS 或必須完成",
      "失敗席位保留 `FAILED`，不得改寫成 PASS、成功或另一個模型",
      "只有選定的初次模型／角度才進入審查工具、Reviewer models 與發現總覽欄",
      "selected set",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.command)

  def test_report_preserves_conditional_qualification_and_single_seat_state(self):
    for marker in (
      "Formal spec gate 的 `gate=ELIGIBLE` 與 evidence requirements",
      "所有初次結果仍須既有查證與 Main 裁決",
      "選定單席就以單席報告",
      "取消初次 reviewer 不算未完成，也不算已完成",
      "模型識別未知就寫 `UNAVAILABLE`",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.command)


  def test_report_ends_with_a_scope_section_that_states_the_floor(self):
    headings = re.findall(r"^## .+$", self.report_structure, flags=re.MULTILINE)
    self.assertEqual(headings[-1], "## 這次審查範圍")
    self.assertEqual(headings[-2], "## 沒做的部分（結案對帳）")
    scope = self.report_structure[self.report_structure.index("## 這次審查範圍"):]
    for marker in (
      "套用的標準",
      "相關但沒套用",
      "證據不足",
      "沒完成",
      "底線：已完成 | 底線未完成：<原因>",
      "語言 reviewer 停審、沒回來、方法組沒載入都寫底線未完成",
      "只做註解清掃",
      "推薦但未選",
      "references/review-dispatch-principles.md",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, scope)

  def test_scope_section_c4_part_is_composed_by_the_main_session_from_existing_accounting(self):
    scope = self.report_structure[self.report_structure.index("## 這次審查範圍"):]
    for marker in (
      "C4 部分由主 session 從 spec-compliance-reviewer 既有的 `contract_accounting`／`spec_file_accounting` 整理",
      "不改 C4 的輸出契約",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, scope)
    agent = (Path(__file__).resolve().parents[2] / "agents/spec-compliance-reviewer.md").read_text()
    self.assertNotIn("這次審查範圍", agent)

  def test_late_replies_and_unselected_external_seats_are_disclosed_in_the_scope_section(self):
    scope = self.report_structure[self.report_structure.index("## 這次審查範圍"):]
    self.assertIn("派出後才到的回覆", scope)
    self.assertIn("已派出的席位照常完成", scope)
    self.assertIn("不算未完成", scope)

  def test_external_cost_is_never_reported_as_zero(self):
    scope = self.report_structure[self.report_structure.index("## 這次審查範圍"):]
    self.assertIn("Step 4.2 的驗證仍用 Codex 額度", scope)
    self.assertIn("不得把「外部額度席沒選」寫成外部成本為零", scope)
    start = self.command.index("### Step 4.2: Codex Verification Pass on CC First-Pass Findings")
    end = self.command.index("## Step 4.3:", start)
    step = self.command[start:end]
    self.assertIn("仍用 Codex 額度", step)
    self.assertIn("不得把「外部額度席沒選」寫成外部成本為零", step)
    for unchanged in (
      "codex-companion.mjs",
      "--model gpt-6.1-sol --effort xhigh",
      "**Batch 是唯一選項**",
      "every non-strict-liability finding from a selected CC source cell",
    ):
      with self.subTest(unchanged=unchanged):
        self.assertIn(unchanged, step)

  def test_report_checklist_gates_the_scope_section(self):
    start = self.command.index("### Step 5.0:")
    end = self.command.index("### Report Structure", start)
    checklist = self.command[start:end]
    for marker in (
      "「這次審查範圍」",
      "底線完成與否",
      "推薦但未選",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, checklist)
    self.assertIn("**Review selection**:", self.report_structure)
    self.assertIn("Claude 側席位自動選入", self.report_structure)


if __name__ == "__main__":
  unittest.main()
