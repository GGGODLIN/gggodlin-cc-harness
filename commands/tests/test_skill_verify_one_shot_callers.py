#!/usr/bin/env python3
"""每個 Self-Verify caller 的 one-shot 契約。

只查**可執行的 Self-Verify 分支**：marker 位置、四態 canonical token、不得重派或
續問。不做全檔禁字——caller 文件裡談 deterministic test 重跑、reviewer 重派、
codex retry 都是正當內容，全檔掃 `retry` 會把它們一起誤殺。

分母來自本檔的 CALLERS 常數（受檢對象之外的清單），不從檔案內容反推。
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CALLERS = {
  "pr-review": "commands/pr-review.md",
  "rules-slim": "commands/rules-slim.md",
  "save-session": "commands/save-session.md",
  "absorb-pack": "skills/absorb-pack/SKILL.md",
  "auto-choice": "skills/auto-choice/SKILL.md",
  "bitbucket-pr-mutation": "skills/bitbucket-pr-mutation/SKILL.md",
  "check-my-stack": "skills/check-my-stack/SKILL.md",
  "e2e-explore-then-batch": "skills/e2e-explore-then-batch/SKILL.md",
  "explain-diff": "skills/explain-diff/SKILL.md",
  "github-repo-research": "skills/github-repo-research/SKILL.md",
  "model-onboard": "skills/model-onboard/SKILL.md",
  "mutation-testing": "skills/mutation-testing/SKILL.md",
  "pr-explain": "skills/pr-explain/SKILL.md",
  "research-before-answer": "skills/research-before-answer/SKILL.md",
  "wayfinder": "skills/wayfinder/SKILL.md",
}

GATE = "hooks/skill-verify-once-gate.py"
TEMPLATE = "skills/skill-creator/SKILL.md"

STATES = ("COMPLIANT", "FIXED_AFTER_AUDIT", "FAILED", "SKIPPED")

ONE_SHOT_RE = re.compile(r"(只有一次 auditor 額度|one auditor attempt per turn|不重派 auditor)")
NO_SENDMESSAGE_RE = re.compile(r"(SendMessage 續問|continue the first one over `SendMessage`)")

# 被移除的舊 retry 措辭。出現任一句 = 這個 caller 還在教模型再驗一次。
BANNED = (
  "修 draft 後重新派一次 auditor",
  "第二次仍有 FAIL",
  "Fix FAIL and rerun",
  "補齊重派",
  "修完重驗",
)


def read(rel):
  return (ROOT / rel).read_text(encoding="utf-8")


class MarkerPlacement(unittest.TestCase):
  def test_every_caller_declares_its_own_marker(self):
    for name, rel in CALLERS.items():
      with self.subTest(caller=name):
        self.assertIn(f"skill-verify:{name}", read(rel), f"{rel} 沒有自己的 marker 字串")

  def test_marker_is_documented_as_a_description_field(self):
    """gate 從 description 取 skill 名；prompt-only 是舊接線。"""
    for name, rel in CALLERS.items():
      with self.subTest(caller=name):
        text = read(rel)
        line = next(
          (l for l in text.splitlines() if f"skill-verify:{name}" in l and re.search(r"description|marker", l)),
          None,
        )
        self.assertIsNotNone(line, f"{rel} 沒有一行同時講 description/marker 與 skill-verify:{name}")
        self.assertRegex(line, r"description", f"{rel} 的 marker 行沒有指名 description：{line.strip()}")

  def test_model_onboard_no_longer_wires_marker_prompt_only(self):
    text = read(CALLERS["model-onboard"])
    self.assertIn("prompt-only 是舊寫法", text, "model-onboard 要明說 prompt-only 不再是正式接線")


class OneShotContract(unittest.TestCase):
  def test_every_caller_states_the_single_attempt_rule(self):
    for name, rel in CALLERS.items():
      with self.subTest(caller=name):
        self.assertRegex(read(rel), ONE_SHOT_RE, f"{rel} 沒寫明本回合只有一次 auditor")

  def test_every_caller_forbids_continuing_the_auditor(self):
    for name, rel in CALLERS.items():
      with self.subTest(caller=name):
        self.assertRegex(read(rel), NO_SENDMESSAGE_RE, f"{rel} 沒擋 SendMessage 續問")

  def test_no_caller_keeps_a_retry_branch(self):
    for name, rel in CALLERS.items():
      text = read(rel)
      for phrase in BANNED:
        with self.subTest(caller=name, phrase=phrase):
          self.assertNotIn(phrase, text, f"{rel} 仍留著 retry 措辭：{phrase}")


class FourStates(unittest.TestCase):
  def test_every_caller_lands_all_four_states(self):
    for name, rel in CALLERS.items():
      text = read(rel)
      for state in STATES:
        with self.subTest(caller=name, state=state):
          self.assertIn(state, text, f"{rel} 缺 {state} 分支")

  def test_fixed_after_audit_always_discloses_the_missing_second_audit(self):
    for name, rel in CALLERS.items():
      with self.subTest(caller=name):
        text = read(rel)
        self.assertRegex(
          text,
          r"(未經第二次獨立稽查|no second independent audit)",
          f"{rel} 的 FIXED_AFTER_AUDIT 沒要求揭露未經第二次稽查",
        )

  def test_failed_state_requires_deleting_or_narrowing_the_claim(self):
    """FAILED 不能只是貼個標籤就照原樣交付——撐不住的東西要拿掉或降級。"""
    remediation = re.compile(
      r"(刪除或收窄|刪除或降級|移除或降級|整列刪除|整段移除|移回 survived"
      r"|never present the proposal as approvable"
      r"|不得把它當成已完成|不得當成已驗證)",
      re.IGNORECASE,
    )
    for name, rel in CALLERS.items():
      with self.subTest(caller=name):
        self.assertRegex(read(rel), remediation, f"{rel} 的 FAILED 分支沒要求刪掉、降級或收窄撐不住的主張")

  def test_skipped_state_names_a_reason(self):
    for name, rel in CALLERS.items():
      with self.subTest(caller=name):
        text = read(rel)
        self.assertRegex(
          text,
          r"SKIPPED\s*\(",
          f"{rel} 的 SKIPPED 沒帶原因括號",
        )


class DownstreamDifferencesSurvive(unittest.TestCase):
  """統一四態不得抹掉各 caller 既有的下游差異。"""

  def test_bitbucket_still_blocks_approval_without_a_pass(self):
    text = read(CALLERS["bitbucket-pr-mutation"])
    self.assertIn("never create approval", text)
    self.assertIn("human approval", text)

  def test_pr_review_keeps_advisory_skip_and_per_rule_consistency(self):
    text = read(CALLERS["pr-review"])
    self.assertIn("Self-Verify: SKIPPED (agent error)", text)
    self.assertIn("照常執行投影 helper 發布", text)
    self.assertIn("FAIL 集合不一致", text)

  def test_wayfinder_moved_completeness_check_before_dispatch(self):
    text = read(CALLERS["wayfinder"])
    self.assertIn("派工前的 completeness check", text)
    self.assertIn("不要重派", text)

  def test_research_before_answer_narrows_unsupported_claims(self):
    text = read(CALLERS["research-before-answer"])
    self.assertIn("把不實或佐證不足的主張從 draft 刪除或收窄", text)


class TemplateAndGateStayWired(unittest.TestCase):
  def test_skill_creator_template_teaches_the_four_states(self):
    text = read(TEMPLATE)
    for state in STATES:
      with self.subTest(state=state):
        self.assertIn(state, text)
    self.assertIn("一個回合、一個 skill、一次 auditor", text)
    self.assertIn("marker 一定放 description", text)

  def test_template_exempts_deterministic_checks(self):
    self.assertIn("deterministic test、lint、build 這類不是 auditor 的檢查不受此限", read(TEMPLATE))

  def test_gate_exists_and_is_registered_for_all_three_hook_points(self):
    import json

    self.assertTrue((ROOT / GATE).is_file(), f"{GATE} 不存在")
    hooks = json.loads(read("settings.json"))["hooks"]
    seen = set()
    for event, blocks in hooks.items():
      for block in blocks:
        for hook in block.get("hooks", []):
          if "skill-verify-once-gate.py" in hook.get("command", ""):
            seen.add((event, block.get("matcher")))
    self.assertEqual(
      seen,
      {("PreToolUse", "Agent"), ("PreToolUse", "SendMessage"), ("PostToolUse", "Agent")},
      f"gate 的三個掛點沒接齊，實際：{sorted(seen)}",
    )


if __name__ == "__main__":
  unittest.main(verbosity=2)
