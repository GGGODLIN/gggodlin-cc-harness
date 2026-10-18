#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1]
STUB = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as log:
  log.write(json.dumps({"bin": Path(sys.argv[0]).name, "args": args}) + "\\n")

def emit(value):
  print(json.dumps(value))

worker = os.environ.get("STUB_WORKER_NAME", "demo")
worker_pane = os.environ.get("STUB_WORKER_PANE", "w1:p2")
worker_session = os.environ.get("STUB_WORKER_SESSION", "worker-first")
main_session = os.environ.get("STUB_MAIN_SESSION", "main-first")

def worker_session_value(value):
  if os.environ.get("STUB_WORKER_SESSION_NULL"):
    return None
  if os.environ.get("STUB_PI"):
    return {"agent": "pi", "kind": "path", "source": "herdr:pi", "value": value}
  if os.environ.get("STUB_CODEX"):
    return {"agent": "codex", "kind": "id", "source": "herdr:codex", "value": value}
  return {"value": value}

if args[:2] == ["pane", "get"]:
  emit({"result": {"pane": {"pane_id": "w1:p1", "workspace_id": "w1"}}})
elif args[:2] == ["tab", "create"]:
  emit({"result": {"root_pane": {"pane_id": "w1:p2"}, "tab": {"tab_id": "w1:t2"}}})
elif args[:2] == ["agent", "start"]:
  emit({"ok": True})
elif args[:2] == ["agent", "list"]:
  emit({"result": {"agents": [{"name": worker, "pane_id": worker_pane, "agent_session": {"value": worker_session}}, {"name": "main", "pane_id": "w1:p1", "agent_session": {"value": main_session}}]}})
elif args[:2] == ["agent", "get"]:
  target = args[2]
  if target == "w1:p1" and os.environ.get("STUB_MAIN_LOOKUP_FAIL"):
    sys.exit(1)
  if target != "w1:p1" and os.environ.get("STUB_WORKER_LOOKUP_FAIL"):
    sys.exit(1)
  if target == "w1:p1":
    emit({"result": {"agent": {"name": "main", "pane_id": "w1:p1", "agent_session": {"value": main_session}}}})
  else:
    current = {"pane_id": worker_pane, "agent_session": worker_session_value(worker_session)}
    if not os.environ.get("STUB_WORKER_NAMELESS"):
      current["name"] = worker
    emit({"result": {"agent": current}})
elif args[:2] == ["agent", "wait"]:
  if os.environ.get("STUB_WAIT_FAIL"):
    emit({"ok": False, "error": {"code": "agent_not_found"}})
    sys.exit(1)
  if os.environ.get("STUB_WAIT_NAME_INVALID") and args[2] != worker_pane:
    emit({"ok": False, "error": {"code": "agent_not_found"}})
    sys.exit(1)
  emit({"result": {"agent": {"name": worker, "pane_id": worker_pane, "agent_status": "done", "agent_session": worker_session_value(worker_session)}}})
elif args[:2] == ["agent", "prompt"]:
  if args[2] == "w1:p1" and os.environ.get("STUB_PROMPT_FAIL"):
    sys.exit(1)
  emit({"ok": True})
elif args[:2] == ["notification", "show"]:
  emit({"ok": True})
else:
  sys.exit(2)
'''


class HerdrWatcherIdentityTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.root = Path(self.temp.name)
    self.bin = self.root / "bin"
    self.bin.mkdir()
    path = self.bin / "herdr"
    path.write_text(STUB)
    path.chmod(0o755)
    self.stub_log = self.root / "stub.jsonl"
    self.log = self.root / "watch.log"
    self.brief = self.root / "brief.md"
    self.brief.write_text("A fixture worker brief\n")
    self.env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "STUB_LOG": str(self.stub_log), "HERDR_ENV": "1", "HERDR_PANE_ID": "w1:p1", "HERDR_WORKSPACE_ID": "w1", "CLAUDE_CODE_SESSION_ID": "main-first"}

  def start_worker(self):
    return subprocess.run(["bash", str(SCRIPTS / "start-worker.sh"), "demo", str(self.root), str(self.brief), "--no-watch"], env=self.env, capture_output=True, text=True, timeout=10)

  def watch(self, env=None, session="worker-first"):
    return subprocess.run(["bash", str(SCRIPTS / "agent-watch.sh"), "herdr", "demo", "w1:p1", str(self.log), session, str(self.root), "main-first", "w1:p2"], env=env or self.env, capture_output=True, text=True, timeout=10)

  def calls(self, command=None):
    if not self.stub_log.exists():
      return []
    rows = [json.loads(line) for line in self.stub_log.read_text().splitlines()]
    return [row for row in rows if command is None or row["args"][:len(command)] == command]

  def main_prompts(self):
    return [row["args"][3] for row in self.calls(["agent", "prompt", "w1:p1"])]

  def test_receipt_captures_original_main_and_worker_sessions(self):
    result = self.start_worker()
    self.assertEqual(result.returncode, 0, result.stderr)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["session_id"], "worker-first")
    self.assertEqual(receipt["pane_id"], "w1:p2")
    self.assertEqual(receipt["parent_id"], "w1:p1")
    self.assertEqual(receipt["parent_session_id"], "main-first")

  def test_matching_sessions_send_only_normal_status(self):
    result = self.watch()
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("stopped, status=done", self.main_prompts()[0])
    self.assertNotIn("未驗證", self.main_prompts()[0])

  def test_worker_mismatch_sends_only_anomaly_without_completion(self):
    result = self.watch({**self.env, "STUB_WORKER_SESSION": "worker-replaced"})
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("異常", self.main_prompts()[0])
    self.assertNotIn("completed", self.main_prompts()[0])
    self.assertNotIn("stopped, status=done", self.main_prompts()[0])

  def test_worker_pane_mismatch_sends_anomaly(self):
    result = self.watch({**self.env, "STUB_WORKER_PANE": "w1:p3"})
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("異常", self.main_prompts()[0])
    self.assertNotIn("stopped, status=done", self.main_prompts()[0])

  def test_operator_name_can_be_absent_or_renamed_without_false_anomaly(self):
    for changed in ({"STUB_WORKER_NAMELESS": "1"}, {"STUB_WORKER_NAME": "other"}):
      with self.subTest(changed=changed):
        self.stub_log.unlink(missing_ok=True)
        result = self.watch({**self.env, **changed})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.main_prompts()), 1)
        self.assertIn("stopped, status=done", self.main_prompts()[0])

  def test_renamed_worker_before_wait_uses_recorded_pane(self):
    result = self.watch({**self.env, "STUB_WAIT_NAME_INVALID": "1", "STUB_WORKER_NAME": "other"})
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.calls(["agent", "wait"])[0]["args"][2], "w1:p2")
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("stopped, status=done", self.main_prompts()[0])

  def test_missing_worker_before_wait_warns_verified_main(self):
    result = self.watch({**self.env, "STUB_WAIT_FAIL": "1"})
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("未驗證", self.main_prompts()[0])
    self.assertNotIn("stopped, status=done", self.main_prompts()[0])
    self.assertEqual(self.calls(["notification", "show"]), [])

  def test_unknown_worker_identity_warns_verified_main(self):
    result = self.watch({**self.env, "STUB_WORKER_LOOKUP_FAIL": "1"})
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("未驗證", self.main_prompts()[0])
    self.assertNotIn("stopped, status=done", self.main_prompts()[0])

  def test_manual_rehang_without_worker_pane_warns_original_main(self):
    result = subprocess.run(["bash", str(SCRIPTS / "agent-watch.sh"), "herdr", "demo", "w1:p1", str(self.log), "worker-first", str(self.root)], env=self.env, capture_output=True, text=True, timeout=10)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("未驗證", self.main_prompts()[0])
    self.assertNotIn("stopped, status=done", self.main_prompts()[0])

  def test_replaced_main_is_not_prompted_and_event_is_logged(self):
    result = self.watch({**self.env, "STUB_MAIN_SESSION": "main-replaced"})
    self.assertNotEqual(result.returncode, 0)
    self.assertEqual(self.main_prompts(), [])
    self.assertIn("未送達", self.log.read_text())
    self.assertEqual(self.calls(["notification", "show"]), [])

  def test_failed_prompt_is_logged_as_undelivered(self):
    result = self.watch({**self.env, "STUB_PROMPT_FAIL": "1"})
    self.assertNotEqual(result.returncode, 0)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("未送達", self.log.read_text())
    self.assertEqual(self.calls(["notification", "show"]), [])

  UUID = "019f3a2c-7d41-7b8e-9c10-5a2e4f6b8d90"

  def codex_env(self, **extra):
    return {**self.env, "STUB_CODEX": "1", "STUB_WORKER_SESSION": self.UUID, **extra}

  def test_codex_matching_uuid_sends_normal_status(self):
    result = self.watch(self.codex_env(), session=self.UUID)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("stopped, status=done", self.main_prompts()[0])
    self.assertNotIn("異常", self.main_prompts()[0])

  def test_codex_replaced_uuid_sends_anomaly(self):
    result = self.watch(self.codex_env(STUB_WORKER_SESSION="019f3a2c-0000-7000-8000-000000000000"), session=self.UUID)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("異常", self.main_prompts()[0])
    self.assertNotIn("stopped, status=done", self.main_prompts()[0])

  def test_codex_null_session_at_stop_is_unverified_not_complete(self):
    result = self.watch(self.codex_env(STUB_WORKER_SESSION_NULL="1"), session=self.UUID)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("未驗證", self.main_prompts()[0])
    self.assertNotIn("stopped, status=done", self.main_prompts()[0])

  PI_PATH = "/stub/.pi/agent/sessions/--w--/2026-10-18T00-00-00-000Z_" + UUID + ".jsonl"

  def pi_env(self, live=PI_PATH):
    return {**self.env, "STUB_PI": "1", "STUB_WORKER_SESSION": live}

  def test_pi_receipt_uuid_matches_live_session_path(self):
    result = self.watch(self.pi_env(), session=self.UUID)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("stopped, status=done", self.main_prompts()[0])
    self.assertNotIn("異常", self.main_prompts()[0])

  def test_pi_full_path_as_session_still_matches(self):
    result = self.watch(self.pi_env(), session=self.PI_PATH)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("stopped, status=done", self.main_prompts()[0])

  def test_pi_live_path_of_another_uuid_sends_anomaly(self):
    other = "/stub/.pi/agent/sessions/--w--/2026-10-18T00-00-00-000Z_019f3a2c-0000-7000-8000-000000000000.jsonl"
    result = self.watch(self.pi_env(other), session=self.UUID)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.main_prompts()), 1)
    self.assertIn("異常", self.main_prompts()[0])
    self.assertNotIn("stopped, status=done", self.main_prompts()[0])

  def test_pi_uuid_must_be_the_whole_filename_suffix(self):
    near = "/stub/.pi/agent/sessions/--w--/2026-10-18T00-00-00-000Z_x" + self.UUID + ".jsonl.bak"
    result = self.watch(self.pi_env(near), session=self.UUID)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn("異常", self.main_prompts()[0])
    self.assertNotIn("stopped, status=done", self.main_prompts()[0])


if __name__ == "__main__":
  unittest.main()
