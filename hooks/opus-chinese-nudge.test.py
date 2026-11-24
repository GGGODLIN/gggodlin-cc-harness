#!/usr/bin/env python3
# 四件 fixture：known-good（通知＋Opus 注入）、known-bad（人類 prompt／別的模型／別的 event／subagent 不注入）、
# 邊界（model 帶 [1m] 後綴仍算、sidechain 的 model 不算、transcript 沒有 assistant 不注入）、
# 自身生命週期（recovery：env 與 sentinel 關閉；bootstrap／update：settings.json 已註冊本檔）。
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("opus-chinese-nudge.py")
SETTINGS = Path(__file__).resolve().parents[1] / "settings.json"
SESSION = "11111111-2222-3333-4444-555555555555"
NOTIFICATION = (
  "<task-notification>\n<task-id>task-fixture-01</task-id>\n<status>completed</status>\n"
  "<summary>Background command \"Run daily recap wrapper\" completed (exit code 0)</summary>\n</task-notification>"
)
HUMAN = "請問這個功能目前同步完成沒？"


class OpusChineseNudgeTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.transcript = self.root / "session.jsonl"
    self.state = self.root / "state"
    self.state.mkdir()
    self.cache = self.root / "cache"
    self.cache.mkdir()

  def record(self, model="claude-opus-5-5", sidechain=False, text="I'm watching in the background."):
    with self.transcript.open("a") as f:
      f.write(json.dumps({"type": "user", "origin": {"kind": "human"}, "message": {"content": "現在什麼狀況"}}) + "\n")
      row = {"type": "assistant", "message": {"model": model, "content": [{"type": "text", "text": text}]}}
      if sidechain:
        row["isSidechain"] = True
      f.write(json.dumps(row, ensure_ascii=False) + "\n")

  def run_hook(self, prompt=NOTIFICATION, env_extra=None, **fields):
    payload = {
      "hook_event_name": "UserPromptSubmit",
      "session_id": SESSION,
      "transcript_path": str(self.transcript),
      "cwd": str(self.root),
      "prompt": prompt,
      **fields,
    }
    env = dict(os.environ, OPUS_CHINESE_NUDGE_STATE_DIR=str(self.state), OPUS_CHINESE_STOP_MODEL_CACHE_DIR=str(self.cache))
    env.pop("OPUS_CHINESE_NUDGE_OFF", None)
    env.update(env_extra or {})
    result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=10)
    self.assertEqual(result.returncode, 0, result.stderr)
    return json.loads(result.stdout) if result.stdout.strip() else {}

  def context(self, output):
    return output.get("hookSpecificOutput", {}).get("additionalContext", "")

  # known-good
  def test_notification_turn_on_opus_injects_chinese_reminder(self):
    self.record()
    out = self.run_hook()
    self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
    self.assertIn("[opus-chinese-nudge]", self.context(out))
    self.assertIn("繁體中文", self.context(out))

  def test_system_notification_marker_also_counts(self):
    self.record()
    self.assertIn("[opus-chinese-nudge]", self.context(self.run_hook(prompt="[SYSTEM NOTIFICATION - NOT USER INPUT]\n" + NOTIFICATION)))

  # known-bad
  def test_human_prompt_does_not_inject(self):
    self.record()
    self.assertEqual(self.run_hook(prompt=HUMAN), {})

  def test_other_model_does_not_inject(self):
    self.record(model="gpt-6-sol")
    self.assertEqual(self.run_hook(), {})
    self.record(model="claude-fable-5-1")
    self.assertEqual(self.run_hook(), {})

  def test_wrong_event_or_subagent_does_not_inject(self):
    self.record()
    self.assertEqual(self.run_hook(hook_event_name="Stop"), {})
    self.assertEqual(self.run_hook(agent_id="agent-1"), {})

  # 邊界
  def test_model_with_1m_suffix_still_counts(self):
    self.record(model="claude-opus-5-5[1m]")
    self.assertIn("[opus-chinese-nudge]", self.context(self.run_hook()))

  def test_sidechain_model_is_ignored(self):
    self.record()
    self.record(model="claude-sonnet-5-5", sidechain=True)
    self.assertIn("[opus-chinese-nudge]", self.context(self.run_hook()))
    self.transcript.unlink()
    self.record(model="claude-sonnet-5-5")
    self.record(model="claude-opus-5-5", sidechain=True)
    self.assertEqual(self.run_hook(), {})

  def test_no_assistant_record_fails_open_silently(self):
    self.transcript.write_text(json.dumps({"type": "user", "origin": {"kind": "human"}, "message": {"content": "hi"}}) + "\n")
    (self.cache / f"model-{SESSION}.txt").write_text("claude-opus-5-5\n")
    self.assertEqual(self.run_hook(), {})

  def test_missing_transcript_fails_open_silently(self):
    self.assertEqual(self.run_hook(transcript_path=str(self.root / "missing.jsonl")), {})

  def test_conflicting_cache_does_not_inject(self):
    self.record()
    (self.cache / f"model-{SESSION}.txt").write_text("gpt-6-sol\n")
    self.assertEqual(self.run_hook(), {})

  # 自身生命週期：recovery
  def test_env_switch_disables(self):
    self.record()
    self.assertEqual(self.run_hook(env_extra={"OPUS_CHINESE_NUDGE_OFF": "1"}), {})

  def test_sentinel_disables_and_removal_restores(self):
    self.record()
    sentinel = self.state / "opus-chinese-nudge.off"
    sentinel.touch()
    self.assertEqual(self.run_hook(), {})
    sentinel.unlink()
    self.assertIn("[opus-chinese-nudge]", self.context(self.run_hook()))

  # 自身生命週期：bootstrap／update——settings 已掛本檔
  def test_settings_registers_hook_under_user_prompt_submit(self):
    settings = json.loads(SETTINGS.read_text())
    commands = [h.get("command", "") for group in settings["hooks"]["UserPromptSubmit"] for h in group.get("hooks", [])]
    self.assertTrue(any("opus-chinese-nudge.py" in c for c in commands), commands)


if __name__ == "__main__":
  unittest.main()
