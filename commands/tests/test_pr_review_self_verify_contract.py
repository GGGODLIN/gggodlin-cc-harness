#!/usr/bin/env python3

import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
# 以本檔所在 checkout 為預設，worktree 內跑測試才會讀到被改的那一份，而不是 ~/.claude 的現役檔。
COMMAND_PATH = Path(os.environ.get("PR_REVIEW_COMMAND_PATH", ROOT / "commands/pr-review.md"))
AUDITOR_PATH = Path(os.environ.get("SKILL_VERIFY_AUDITOR_PATH", ROOT / "agents/skill-verify-auditor.md"))
FILE_MODE_MARKER = "AUDIT_INPUT_MODE: FILE_SNAPSHOT"


class PrReviewSelfVerifyContractTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.command = COMMAND_PATH.read_text()
    cls.auditor = AUDITOR_PATH.read_text()
    step_six = cls.command.index("## Step 6: Output")
    cls.step_six = cls.command[step_six:cls.command.index("## Error Handling", step_six)]

  def test_self_verify_runs_once_between_draft_and_projection(self):
    step_six = self.command.index("## Step 6: Output")
    error_handling = self.command.index("## Error Handling", step_six)
    output = self.command[step_six:error_handling]
    draft = output.index("pr-<number>-review.audit.draft.md")
    marker = output.index("skill-verify:pr-review", draft)
    helper = output.index("pr-review-report-projection.py", marker)
    self.assertLess(draft, marker)
    self.assertLess(marker, helper)
    self.assertEqual(1, output.count("skill-verify:pr-review"))
    self.assertEqual(1, output.count("subagent_type: skill-verify-auditor"))
    self.assertNotIn("skill-verify:bitbucket-pr-review", self.command)

  def test_self_verify_is_read_only_and_report_bounded(self):
    self.assertIn("subagent_type: skill-verify-auditor", self.command)
    self.assertIn("不得重新審查 diff、API、Git 或 transcript", self.command)
    self.assertIn("草稿快照", self.step_six)
    self.assertIn("固定 rubric 全文", self.command)

  def test_self_verify_rubric_covers_report_proof_obligations(self):
    for marker in (
      "review input 綁定",
      "審查軸狀態",
      "逐檔覆蓋",
      "C4／spec 狀態",
      "finding UID／action",
      "條件式 N-A",
      "失敗軸",
      "沒做的部分",
      "零 finding",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.command)

  def test_auditor_output_requires_complete_consistent_rubric(self):
    for marker in (
      "必須恰好含 R1–R10 各一行",
      "缺行、重複、順序錯、狀態不合法",
      "FAIL 集合不一致",
      "只有 verdict 無逐條證據",
      "不得只信最後一行",
    ):
      with self.subTest(marker=marker):
        self.assertIn(marker, self.command)

  def test_agent_error_is_advisory_and_disclosed(self):
    step_six = self.command.index("## Step 6: Output")
    error_handling = self.command.index("## Error Handling", step_six)
    output = self.command[step_six:error_handling]
    self.assertIn("Self-Verify: SKIPPED (agent error)", output)
    self.assertIn("照常執行投影 helper 發布", output)
    self.assertIn("本報告未經獨立稽查", output)
    self.assertNotIn("BLOCKED (agent error)", output)
    self.assertNotIn("不得執行投影 helper", output)

  def test_failures_are_repaired_without_claiming_reverification(self):
    self.assertIn("有執行證據就補寫", self.command)
    self.assertIn("沒有執行證據就補跑", self.command)
    self.assertIn("修正後不重派 auditor", self.command)
    self.assertIn("未經第二次獨立稽查", self.command)


  def test_auditor_file_mode_is_opt_in_and_default_stays_embedded(self):
    self.assertIn("被審的交付物必須以全文內嵌在 prompt 裡。給一個檔案路徑不算數", self.auditor)
    self.assertIn(FILE_MODE_MARKER, self.auditor)
    self.assertIn("沒有這一行就不是讀檔模式", self.auditor)
    self.assertIn("SNAPSHOT_PATH:", self.auditor)
    self.assertIn("SNAPSHOT_TOTAL_LINES:", self.auditor)
    self.assertIn("rubric 仍必須全文內嵌", self.auditor)

  def test_auditor_file_mode_cannot_be_compliant_without_reaching_last_line(self):
    self.assertIn("READ_RANGE:", self.auditor)
    self.assertIn("分段 Read", self.auditor)
    self.assertIn("沒讀到第 N 行或任何一次 Read 失敗", self.auditor)
    self.assertIn("不得輸出 `VERDICT: COMPLIANT`", self.auditor)

  def test_step_six_uses_file_mode_with_read_only_snapshot_and_line_count(self):
    self.assertIn(FILE_MODE_MARKER, self.step_six)
    self.assertIn("pr-<number>-review.audit.snapshot.md", self.step_six)
    self.assertIn("chmod 444", self.step_six)
    self.assertIn("SNAPSHOT_TOTAL_LINES", self.step_six)
    self.assertIn("READ_RANGE", self.step_six)
    self.assertIn("不得記 `Self-Verify: COMPLIANT`", self.step_six)
    self.assertNotIn("prompt 只內嵌：(a) 完整證據草稿全文", self.step_six)
    self.assertIn("Self-Verify: FIXED_AFTER_AUDIT", self.step_six)
    self.assertIn("未經第二次獨立稽查", self.step_six)


if __name__ == "__main__":
  unittest.main()
