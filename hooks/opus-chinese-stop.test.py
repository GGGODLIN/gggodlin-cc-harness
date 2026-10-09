#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("opus-chinese-stop.py")
SETTINGS = Path(__file__).resolve().parents[1] / "settings.json"
PROMPT = "d3379f3e-fa12-4c5d-bcc8-e79524bd589d"
SESSION = "65a096e9-7231-4128-8792-531142dbd5b2"
ENGLISH = (
  "The switch is done: advisor reminders now show as a dim line in the conversation area. "
  "The judging logic is untouched, and the new mod reads from the inbox. "
  "The old trial says 停用方式, but this does not change the actual behavior."
)
CHINESE = (
  "切換已完成。提醒現在顯示在對話區，判讀邏輯沒有變動。"
  "新 mod 仍從 inbox 讀取紀錄；現有測試已通過。"
)


class OpusChineseStopTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.transcript = self.root / "session.jsonl"
    self.state = self.root / "state"
    self.cache = self.root / "cache"
    self.cache.mkdir()
    self.records("喔懂了，那現在就換吧，然後能查出當初是哪個模型負責這件事嗎？")

  def records(self, prompt, model="claude-opus-5-5", prompt_id=PROMPT, origin="human"):
    with self.transcript.open("a") as f:
      for row in (
        {"type": "user", "promptId": prompt_id, "origin": {"kind": origin}, "message": {"content": prompt}},
        {"type": "assistant", "message": {"model": model, "content": [{"type": "text", "text": "工具前進度"}]}},
      ):
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

  def run_hook(self, text=ENGLISH, **fields):
    payload = {
      "hook_event_name": "Stop",
      "session_id": SESSION,
      "prompt_id": PROMPT,
      "transcript_path": str(self.transcript),
      "last_assistant_message": text,
      "background_tasks": [],
      "session_crons": [],
      **fields,
    }
    env = os.environ.copy()
    env["OPUS_CHINESE_STOP_STATE_DIR"] = str(self.state)
    env["OPUS_CHINESE_STOP_MODEL_CACHE_DIR"] = str(self.cache)
    result = subprocess.run(
      [sys.executable, str(HOOK)], input=json.dumps(payload), text=True,
      capture_output=True, env=env, timeout=5,
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    return json.loads(result.stdout) if result.stdout.strip() else {}

  def test_english_final_gets_one_non_error_reminder(self):
    output = self.run_hook()
    self.assertNotIn("decision", output)
    self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "Stop")
    self.assertIn("繁體中文", output["hookSpecificOutput"]["additionalContext"])
    self.assertEqual(self.run_hook(), {})

  def test_previous_stop_hook_does_not_suppress_first_reminder(self):
    self.assertIn("additionalContext", self.run_hook(stop_hook_active=True)["hookSpecificOutput"])

  def test_background_wait_does_not_prompt_a_new_answer(self):
    self.assertEqual(self.run_hook(background_tasks=[{"status": "running"}]), {})
    self.assertEqual(self.run_hook(session_crons=[{"recurring": False}]), {})
    self.assertEqual(self.run_hook(background_tasks=None), {})
    self.assertEqual(self.run_hook(session_crons=None), {})
    self.assertIn("additionalContext", self.run_hook()["hookSpecificOutput"])

  def test_new_prompt_can_remind_again(self):
    self.run_hook()
    next_prompt = "63495c45-711b-43b6-b1e4-3ff42d8fe0e8"
    self.records("直接結案吧", prompt_id=next_prompt)
    self.assertIn("additionalContext", self.run_hook(prompt_id=next_prompt)["hookSpecificOutput"])

  def notify(self, model="claude-opus-5-5"):
    prompt_id = f"11111111-0000-4000-8000-{len(self.transcript.read_text().splitlines()):012d}"
    self.records("<task-notification>\n<task-id>b1</task-id>", model=model, prompt_id=prompt_id, origin="task-notification")
    return prompt_id

  def test_notification_final_after_background_wait_reminds_once_per_human_prompt(self):
    self.assertEqual(self.run_hook(background_tasks=[{"status": "running"}]), {})
    first = self.notify()
    self.assertIn("additionalContext", self.run_hook(prompt_id=first)["hookSpecificOutput"])
    self.assertEqual(self.run_hook(prompt_id=self.notify()), {})

  def test_notification_after_reminded_human_turn_stays_quiet(self):
    self.assertIn("additionalContext", self.run_hook()["hookSpecificOutput"])
    self.assertEqual(self.run_hook(prompt_id=self.notify()), {})

  def test_notification_uses_latest_human_language_request(self):
    self.transcript.unlink()
    self.records("請用英文回答這個問題")
    self.assertEqual(self.run_hook(prompt_id=self.notify()), {})

  def test_notification_without_human_or_with_other_model_stays_quiet(self):
    self.transcript.unlink()
    self.transcript.touch()
    self.assertEqual(self.run_hook(prompt_id=self.notify()), {})
    self.records("請幫我結案")
    self.assertEqual(self.run_hook(prompt_id=self.notify(model="gpt-6-sol")), {})

  def test_notification_still_waits_for_background_work(self):
    self.assertEqual(self.run_hook(prompt_id=self.notify(), background_tasks=[{"status": "running"}]), {})

  def test_unknown_turn_origin_does_not_trigger(self):
    self.transcript.unlink()
    self.records("請幫我結案")
    self.records("peer message", prompt_id="22222222-0000-4000-8000-000000000001", origin="peer")
    self.assertEqual(self.run_hook(prompt_id="22222222-0000-4000-8000-000000000001"), {})

  def test_short_choices_use_default_chinese(self):
    self.transcript.unlink()
    for index, choice in enumerate(("a", "b", "c", "d", "ok", "1"), start=1):
      prompt_id = f"00000000-0000-4000-8000-{index:012d}"
      self.records(choice, prompt_id=prompt_id)
      with self.subTest(choice=choice):
        self.assertIn("additionalContext", self.run_hook(prompt_id=prompt_id)["hookSpecificOutput"])

  def test_chinese_final_and_english_code_do_not_trigger(self):
    self.assertEqual(self.run_hook(CHINESE), {})
    self.assertEqual(self.run_hook("```python\n" + "print('The switch is done')\n" * 10 + "```"), {})
    self.assertEqual(self.run_hook("中文說明：`PostToolBatch` 和 `last_assistant_message` 是欄位名稱。"), {})

  def test_explicit_english_request_does_not_trigger(self):
    self.transcript.unlink()
    self.records("請用英文回答這個問題")
    self.assertEqual(self.run_hook(), {})
    self.transcript.unlink()
    self.records("不要用中文，請改用英文回答")
    self.assertEqual(self.run_hook(), {})
    self.transcript.unlink()
    self.records("Please answer in English.")
    self.assertEqual(self.run_hook(), {})
    self.transcript.unlink()
    self.records("No Chinese, answer in English.")
    self.assertEqual(self.run_hook(), {})
    self.transcript.unlink()
    self.records("Do not answer in English; answer in Chinese.")
    self.assertIn("additionalContext", self.run_hook()["hookSpecificOutput"])

  def test_do_not_use_english_still_triggers(self):
    self.transcript.unlink()
    self.records("請不要用英文回答，用中文")
    self.assertIn("additionalContext", self.run_hook()["hookSpecificOutput"])
    next_prompt = "63495c45-711b-43b6-b1e4-3ff42d8fe0e8"
    self.records("我希望你不要用英文，用中文回答", prompt_id=next_prompt)
    self.assertIn("additionalContext", self.run_hook(prompt_id=next_prompt)["hookSpecificOutput"])

  def test_other_model_and_subagent_do_not_trigger(self):
    self.transcript.unlink()
    self.records("請幫我結案", model="gpt-6-sol")
    self.assertEqual(self.run_hook(), {})
    self.transcript.unlink()
    self.records("請幫我結案")
    self.assertEqual(self.run_hook(agent_id="agent-123", agent_type="routed-judge"), {})

  def test_unknown_identity_or_missing_user_does_not_trigger(self):
    self.transcript.unlink()
    self.assertEqual(self.run_hook(), {})
    self.assertEqual(self.run_hook(session_id="../other"), {})

  def test_malformed_transcript_metadata_fails_open(self):
    with self.transcript.open("a") as f:
      f.write(json.dumps({"type": "user", "origin": None, "message": {"content": "通知"}}) + "\n")
      f.write(json.dumps(["not an event"]) + "\n")
    self.assertEqual(self.run_hook(), {})

  def test_state_symlink_does_not_write_outside(self):
    elsewhere = self.root / "elsewhere"
    elsewhere.write_text("unchanged")
    self.state.symlink_to(elsewhere)
    self.assertEqual(self.run_hook(), {})
    self.assertEqual(elsewhere.read_text(), "unchanged")

  def test_state_fifo_and_hardlink_do_not_block_or_write_outside(self):
    self.run_hook()
    marker = next(self.state.iterdir())
    marker.unlink()
    os.mkfifo(marker)
    self.assertEqual(self.run_hook(), {})
    marker.unlink()
    elsewhere = self.root / "elsewhere"
    elsewhere.write_text("unchanged")
    os.link(elsewhere, marker)
    self.assertEqual(self.run_hook(), {})
    self.assertEqual(elsewhere.read_text(), "unchanged")

  def test_settings_registers_only_stop(self):
    hooks = json.loads(SETTINGS.read_text())["hooks"]
    commands = [h.get("command", "") for row in hooks["Stop"] for h in row.get("hooks", [])]
    self.assertEqual(sum("opus-chinese-stop.py" in cmd for cmd in commands), 1)
    for event in ("MessageDisplay", "PostToolBatch", "PreToolUse", "PostToolUse"):
      self.assertFalse(any("opus-chinese-stop.py" in h.get("command", "") for row in hooks.get(event, []) for h in row.get("hooks", [])))


if __name__ == "__main__":
  unittest.main()
