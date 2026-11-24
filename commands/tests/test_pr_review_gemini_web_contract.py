#!/usr/bin/env python3

import os
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMAND_PATH = Path(os.environ.get("PR_REVIEW_COMMAND_PATH", ROOT / "commands/pr-review.md"))


class PrReviewGeminiWebContractTest(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.command = COMMAND_PATH.read_text()

  def section(self, start_marker, end_marker):
    start = self.command.index(start_marker)
    end = self.command.index(end_marker, start)
    return self.command[start:end]

  def gemini_multi(self):
    return self.section("#### 多目標整組材料（Step 2.05", "🔌 接線點：ChatGPT 網頁版席位 — 見 WIRING.md")

  def web_multi(self):
    return self.section("🔌 接線點：ChatGPT 網頁版席位 — 見 WIRING.md", "## Step 4: Cross-Axis Verification Pass")

  def test_multi_target_sections_live_inside_the_gemini_block_before_step4(self):
    gemini_block = self.section("### Gemini Pro / Flash Review", "## Step 4: Cross-Axis Verification Pass")
    self.assertIn("#### 多目標整組材料", gemini_block)
    self.assertIn("🔌 接線點：ChatGPT 網頁版席位 — 見 WIRING.md", gemini_block)
    self.assertLess(
      self.command.index("#### 多目標整組材料"),
      self.command.index("## Step 4: Cross-Axis Verification Pass"),
    )

  def test_gemini_multi_target_keeps_one_execution_with_every_root_and_version(self):
    step = self.gemini_multi()
    self.assertIn("多目標才跑；單輸入沿上方既有 Gemini 段", step)
    self.assertIn("以一次執行取得整組", step)
    self.assertIn("**每一個目標**的 `review_root`", step)
    self.assertIn("authored_diff_base", step)
    self.assertIn("不按 PR 或 repo 數量拆成多次完整審查", step)
    self.assertIn("scripts/pr-review-gemini-web.py materials", step)

  def test_gemini_multi_target_keeps_selected_role_and_model(self):
    step = self.gemini_multi()
    self.assertIn("只保留該 cell 的 selected 角色、requested model", step)
    self.assertIn("不新增通道、不偷換模型", step)

  def test_capacity_gate_holds_dispatch_before_adjudication(self):
    step = self.gemini_multi()
    self.assertIn("**容量裁決閘**", step)
    self.assertIn("NEEDS_DECISION", step)
    self.assertIn("executor 呼叫 0", step)
    self.assertIn("不截斷材料、不把 skipped 算通過", step)
    self.assertIn("NOT_DISPATCHABLE", step)
    self.assertIn("先過閘、後構材料", step)

  def test_dispatch_gate_reuses_target_authorize_decision(self):
    step = self.gemini_multi()
    self.assertIn("dispatch_decision", step)
    self.assertIn("selection 確實含對應 seat+angle", step)
    self.assertIn("confirmation", step)
    self.assertIn("seat-not-selected", step)
    self.assertIn("awaiting-confirmation", step)
    self.assertIn("selection-required", step)

  def test_gemini_keeps_the_prompt_in_the_packet_and_opens_with_a_brief_file(self):
    step = self.gemini_multi()
    self.assertIn("packet 是唯一持久材料 receipt", step)
    self.assertIn("完整 prompt 保留在 packet 的 execution", step)
    self.assertIn("不另寫 `*-prompt.txt`", step)
    self.assertIn("`<brief-file>`", step)

  def test_multi_target_gemini_failure_does_not_dispatch_a_fallback(self):
    step = self.gemini_multi()
    self.assertIn("`pr-review-gemini-pro`／`pr-review-gemini-flash`", step)
    self.assertIn("`role: primary`", step)
    self.assertIn("`reply.output`／`reply.model`", step)
    for marker in ("`role: fallback`", "agy", "`run_if`"):
      with self.subTest(marker=marker):
        self.assertFalse(marker in step, f"多目標 Gemini 不應指示備援：{marker}")
    self.assertIn("開席、執行或收席檢查失敗時，依上方步驟 4 處理", step)

  def test_selected_gemini_uses_seat_result_and_keeps_the_findings_envelope(self):
    block = self.section("### Gemini Pro / Flash Review", "#### 多目標整組材料")
    opening = self.section("**開席與收席**", "2. 依「單席交接（新路）」等待")
    self.assertIn("1. 逐軸核對 `REVIEW_SELECTION` 與 `$EXTRA_AXES`；只有 `status=selected` 的軸才開席。", opening)
    for marker in ("pr-review-gemini-pro", "pr-review-gemini-flash", "open-seat.py", "worker-turns.py",
                   "--turn 1", "hc wait", "hc kill", "hc rm", "不自動重送",
                   '"line_start": <int>', '"anchor":', "If no findings, return []."):
      with self.subTest(marker=marker):
        self.assertIn(marker, block)
    # 拿掉「解析失敗就重試一次」
    for forbidden in ("retry 1 次", "以相同 id 另開新席", "解析失敗只以同一席位 id 重試一次"):
      self.assertNotIn(forbidden, block)
      self.assertNotIn(forbidden, self.gemini_multi())

  def test_migration_keeps_the_three_codex_executors_as_exceptions(self):
    codex = self.section("### Codex Review", "### Gemini Pro / Flash Review")
    verification = self.section("## Step 4.2:", "## Step 4.3:")
    for section, marker in ((codex, "codex review"), (codex, "adversarial-review"), (verification, "task --fresh")):
      with self.subTest(marker=marker):
        self.assertIn(marker, section)
    # Gate 10 結論為否：多目標留在舊路並於文件寫明原因
    self.assertIn("finish-seat.py", self.gemini_multi())
    self.assertIn("Gate 10", self.gemini_multi())

  def test_single_target_gemini_uses_catalog_permissions_and_fails_without_headless(self):
    block = self.section("### Gemini Pro / Flash Review", "#### 多目標整組材料")
    self.assertIn('open-seat.py" "$SEAT_ID"', block)
    # 權限與白名單只放在席位目錄；指令再帶一份會蓋過目錄，日後改目錄就靜默失效。
    for duplicate in ("--permission-mode", "--allow-tool"):
      self.assertFalse(duplicate in block, f"單目標範例不該再帶 {duplicate}")
    self.assertIn("啟動唯讀鎖", block)
    failure = "如果席位開不起來、執行出錯、逾時或回件未交付，就保留原因並標該軸 `FAILED`，不自動重送、不改跑 `agy` 或其他無頭指令。"
    self.assertTrue(failure in block, "缺少開席、執行、收件失敗時標 FAILED 的規則")
    self.assertFalse("agy" in block.replace(failure, "", 1),
                     "單目標 Gemini 只有禁止備援規則可提到 agy")

  def test_matrix_rows_for_gemini_seats_name_no_fallback(self):
    rows = [line for line in self.command.splitlines() if line.startswith("| `pr-review-gemini-")]
    self.assertEqual(2, len(rows), "矩陣應各有一列 Pro、Flash 唯讀單席")
    for row in rows:
      self.assertFalse("備援" in row or "agy" in row, f"矩陣列不該再寫備援：{row[:60]}")

  def test_single_target_parse_failure_marks_failed_and_preserves_raw_without_retry(self):
    block = self.section("**Parse 與失敗處置**", "**標記** finding source")
    self.assertIn("標示該席失敗並保留原文，不自動重送", block)
    self.assertIn("其他已有效的回件照常收", block)
    self.assertFalse("agy" in block, "解析失敗處置不應指示 agy 備援")

  def test_head_marker_and_exam_list_register_the_ninth_exam(self):
    head = self.command[:self.command.index("## Step 1: Parse Input")]
    self.assertIn("test_pr_review_gemini_web_contract.py", head)
    self.assertGreaterEqual(head.count("test_pr_review_gemini_web_contract.py"), 3)

  def test_ambiguous_locations_are_never_guessed(self):
    step = self.gemini_multi()
    self.assertIn("**定位回映**", step)
    self.assertIn("不猜 PR", step)
    self.assertIn("unmapped_findings", step)
    self.assertIn("web 通道 findings 缺 target label 同樣標 unmapped", step)

  def test_fixed_failure_kinds_stay_unverified_and_other_channels_survive(self):
    step = self.gemini_multi()
    self.assertIn("**失敗處置**", step)
    self.assertIn("model-mismatch", step)
    self.assertIn("timeout", step)
    self.assertIn("parse-failure", step)
    self.assertIn("unverified", step)
    self.assertIn("其他 selected seat 的有效結果照常進 Step 4／4.8", step)
    self.assertIn("reported_model", step)
    self.assertIn("不冒稱 runtime 模型驗證", step)

  def test_gemini_findings_flow_into_the_common_group_report(self):
    step = self.gemini_multi()
    self.assertIn("**共同報告**", step)
    self.assertIn("source: gemini", step)
    self.assertIn("Step 4.8", step)
    self.assertIn("不得以 CC 或其他通道結果代替", step)
    self.assertIn("未實跑的通道明列未驗", step)

  def test_head_contract_note_lists_the_ninth_exam(self):
    head = self.command[:self.command.index("## Step 1: Parse Input")]
    self.assertIn("test_pr_review_gemini_web_contract.py", head)
    self.assertIn("十一套都要跑", head)


if __name__ == "__main__":
  unittest.main()
