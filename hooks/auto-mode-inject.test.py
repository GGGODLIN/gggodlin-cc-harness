import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("auto-mode-inject.py")
MODE = HOOK.parents[1] / "scripts" / "auto-mode" / "mode.py"
sys.path.insert(0, str(MODE.parent))
from decision import DOWNWEIGHTED_ACTIONS, WEB_GPT_PRO  # noqa: E402
SESSION = "11111111-1111-4111-8111-111111111111"
EVENT = "22222222-2222-4222-8222-222222222222"


class InjectionTests(unittest.TestCase):
  def setUp(self):
    tmp = tempfile.TemporaryDirectory()
    self.addCleanup(tmp.cleanup)
    self.home = Path(tmp.name).resolve()
    self.env = {"HOME": str(self.home), "PATH": os.defpath, "CLAUDE_CODE_ENTRYPOINT": "cli"}
    self.root = self.home / ".claude"
    transcript = self.root / "projects" / "fixture" / f"{SESSION}.jsonl"
    transcript.parent.mkdir(parents=True)
    self.payload = {
      "hook_event_name": "UserPromptSubmit", "session_id": SESSION,
      "transcript_path": str(transcript), "prompt": "接著處理下一個停點",
    }

  def set_mode(self, enabled):
    command = "on" if enabled else "off"
    if "HC_TERMINAL_ID" in self.env:
      args = [command, "--source", "button"]
    else:
      row = {
        "type": "user", "sessionId": SESSION, "uuid": EVENT,
        "origin": {"kind": "human"}, "turnOrigin": "human", "promptSource": "typed",
        "message": {"role": "user", "content": f"/auto-{command}"},
      }
      Path(self.payload["transcript_path"]).write_text(json.dumps(row) + "\n", encoding="utf-8")
      args = ["sync"]
    result = subprocess.run(
      [sys.executable, "-IB", str(MODE), *args, "--session", SESSION],
      env=self.env, text=True, capture_output=True, timeout=5, check=True,
    )
    self.assertIs(json.loads(result.stdout)["enabled"], enabled)

  def submit(self, *, metadata=None, env=None):
    result = subprocess.run(
      [sys.executable, "-IB", str(HOOK)], input=json.dumps({**self.payload, **(metadata or {})}),
      env={**self.env, **(env or {})}, text=True, capture_output=True, timeout=5,
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(result.stderr, "")
    if not result.stdout:
      return ""
    output = json.loads(result.stdout)["hookSpecificOutput"]
    self.assertEqual(output["hookEventName"], "UserPromptSubmit")
    return output["additionalContext"]

  def test_injects_while_on_and_is_silent_while_off(self):
    self.assertEqual(self.submit(), "")
    self.set_mode(True)
    context = self.submit()
    for text in (
        "自動模式已開啟", "decision.py decide", "選單標示的推薦", "既有的『沒回覆就走 X』預設",
        "兩者皆無就照一般模式問", "壓低清單優先", "留本機分支", "Codex Astra",
        "預檢確認個人工作區", "records.py append", "同回合批次", "結案前", "records.py closeout",
        "呼叫 review-spec Tier 3 finalize 時帶 --task <本任務 task>", "壓低在前", "records.py stats",
        WEB_GPT_PRO, *DOWNWEIGHTED_ACTIONS,
    ):
      self.assertIn(text, context)
    self.env["HC_TERMINAL_ID"] = "fixture-terminal"
    self.set_mode(True)
    self.assertEqual(self.submit(), context)
    self.set_mode(False)
    self.assertEqual(self.submit(), "")

  def test_override_only_for_recommendation_or_default_not_downweighted(self):
    self.set_mode(True)
    context = self.submit()
    self.assertIn("只限依推薦或預設處理且未壓低的停點", context)
    for text in ("照推薦不算授權", "沉默不授權", "需使用者明選", "其他停點照舊", "ADR 0012"):
      self.assertIn(text, context)

  def test_corrupt_or_unreadable_state_is_silent(self):
    self.set_mode(True)
    self.assertIn("自動模式已開啟", self.submit())
    state = self.root / "logs" / "auto-mode" / "modes" / f"session-{SESSION}.json"
    for corrupt in ('{"enabled":true,', '{"enabled":"true","applied_events":[]}'):
      with self.subTest(corrupt=corrupt):
        state.write_text(corrupt, encoding="utf-8")
        self.assertEqual(self.submit(), "")
    state.write_text('{"enabled":true,"applied_events":[]}', encoding="utf-8")
    state.chmod(0o644)
    self.assertEqual(self.submit(), "")

  def test_main_session_notification_turns_inject_while_on(self):
    self.set_mode(True)
    context = self.submit()
    self.assertIn("自動模式已開啟", context)
    for metadata in (
        {"promptSource": "task-notification"},
        {"origin": {"kind": "task-notification"}, "turnOrigin": "task-notification",
         "isMeta": True, "prompt": "<task-notification>fixture</task-notification>"},
        {"promptSource": "system", "prompt": "[SYSTEM NOTIFICATION fixture]"},
    ):
      with self.subTest(metadata=metadata):
        self.assertEqual(self.submit(metadata=metadata), context)

  def test_subagent_and_sdk_turns_do_not_inject(self):
    self.env["HC_TERMINAL_ID"] = "fixture-terminal"
    self.set_mode(True)
    self.assertIn("自動模式已開啟", self.submit(metadata={"agent_type": "custom-main"}))
    notification = {"promptSource": "task-notification"}
    for env in (
        {"CLAUDE_AGENT_ID": "fixture-child"}, {"CLAUDE_CODE_AGENT_ID": "fixture-child"},
        {"PI_SUBTASK_JOB_ID": "fixture-job"}, {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"},
    ):
      with self.subTest(env=env):
        self.assertEqual(self.submit(env=env), "")
        self.assertEqual(self.submit(metadata=notification, env=env), "")
    for metadata in (
        {"agent_id": "fixture-child"}, {"isSidechain": True},
        {"transcript_path": str(self.root / "projects" / "fixture" / "subagents" / "agent-child.jsonl")},
        {"origin": {"kind": "sdk"}}, {"turnOrigin": "sdk"}, {"promptSource": "sdk"},
    ):
      with self.subTest(metadata=metadata):
        self.assertEqual(self.submit(metadata=metadata), "")
        self.assertEqual(self.submit(metadata={**notification, **metadata}), "")


if __name__ == "__main__":
  suite = unittest.defaultTestLoader.loadTestsFromTestCase(InjectionTests)
  result = unittest.TextTestRunner(verbosity=2).run(suite)
  if not result.wasSuccessful():
    sys.exit(1)
  print("AUTO_MODE_INJECTION_CONTRACT_OK")
