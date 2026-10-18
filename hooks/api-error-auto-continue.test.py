#!/usr/bin/env python3
# 契約測試：python3 ~/.claude/hooks/api-error-auto-continue.test.py
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).with_name("api-error-auto-continue.py")
STREAM_CUT = "API Error: stream error: stream disconnected before completion: stream closed before response.completed"
SESSION = "11111111-2222-3333-4444-555555555555"


def load_hook():
  spec = importlib.util.spec_from_file_location("auto_continue", HOOK)
  mod = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(mod)
  return mod


class Base(unittest.TestCase):
  def setUp(self):
    self.tmp = Path(tempfile.mkdtemp())
    self.state = self.tmp / "state"
    self.logf = self.tmp / "log.jsonl"
    self.calls = self.tmp / "herdr-calls.txt"
    self.agent_json = self.tmp / "agent.json"
    fake = self.tmp / "herdr"
    fake.write_text(
      "#!/bin/bash\n"
      f'printf "%s\\n" "$*" >> "{self.calls}"\n'
      f'if [ "$1 $2" = "agent get" ]; then cat "{self.agent_json}"; fi\n'
    )
    fake.chmod(0o755)
    self.set_agent(SESSION, "idle")
    self.env = {
      "CC_AUTO_CONTINUE_STATE_DIR": str(self.state),
      "CC_AUTO_CONTINUE_LOG": str(self.logf),
      "HERDR_BIN_PATH": str(fake),
      "HERDR_ENV": "1",
      "HERDR_PANE_ID": "w9:p1",
    }
    self.old_env = {k: os.environ.get(k) for k in [*self.env, "CC_AUTO_CONTINUE"]}
    os.environ.update(self.env)
    os.environ.pop("CC_AUTO_CONTINUE", None)
    self.hook = load_hook()
    self.hook.SEND_DELAY_SECONDS = 0
    self.hook.READY_POLL_SECONDS = 2
    self.spawned = []
    self.hook.spawn = lambda args: self.spawned.append(args)

  def tearDown(self):
    for k, v in self.old_env.items():
      if v is None:
        os.environ.pop(k, None)
      else:
        os.environ[k] = v

  def set_agent(self, session, status):
    self.agent_json.write_text(json.dumps({"result": {"agent": {"agent_session": {"value": session}, "agent_status": status}}}))

  def transcript(self, entrypoint="cli"):
    path = self.tmp / "t.jsonl"
    path.write_text(json.dumps({"type": "user", "entrypoint": entrypoint}) + "\n")
    return str(path)

  def payload(self, error="unknown", message=STREAM_CUT, entrypoint="cli"):
    return {"session_id": SESSION, "error": error, "last_assistant_message": message,
            "transcript_path": self.transcript(entrypoint), "hook_event_name": "StopFailure"}

  def actions(self):
    if not self.logf.exists():
      return []
    return [json.loads(l).get("action") for l in self.logf.read_text().splitlines()]

  def herdr_calls(self):
    return self.calls.read_text().splitlines() if self.calls.exists() else []


class Classify(Base):
  def test_stream_cut_schedules_continue(self):
    self.hook.on_failure(self.payload())
    self.assertEqual(self.spawned, [["--send", "w9:p1", SESSION, self.transcript()]])
    self.assertEqual(self.hook.read_count(SESSION), 1)
    self.assertEqual(self.actions(), ["continue_scheduled"])

  def test_server_error_and_overloaded_are_retryable(self):
    for err in ("server_error", "overloaded"):
      self.assertEqual(self.hook.classify({"error": err}), err)

  def test_non_retryable_types_ignored(self):
    for err in ("rate_limit", "authentication_failed", "billing_error", "invalid_request", "max_output_tokens"):
      self.hook.on_failure(self.payload(error=err, message="API Error: whatever"))
    # Claude 訂閱本身的 5h/7d 額度牆也是 error=rate_limit，由 cc-seat-swap 處理，本 hook 不打字
    self.hook.on_failure(self.payload(error="rate_limit", message="You've hit your session limit · resets 8:30pm (Asia/Taipei)"))
    self.assertEqual(self.spawned, [])
    self.assertFalse(self.hook.counter_path(SESSION).exists())

  def test_rate_limit_429_schedules_continue_after_30s(self):
    msg = 'API Error: Request rejected (429) · Google Gemini: 429 Too Many Requests: [{"error":{"code":429}}]'
    self.hook.on_failure(self.payload(error="rate_limit", message=msg))
    self.assertEqual(self.spawned, [["--send", "w9:p1", SESSION, self.transcript(), "30"]])
    self.assertEqual(self.hook.read_count(SESSION), 1)
    self.assertEqual(self.actions(), ["continue_scheduled"])

  def test_rate_limit_delay_honors_magpie_held_until_clock(self):
    from datetime import datetime, timezone, timedelta
    tz8 = timezone(timedelta(hours=8))
    now = datetime(2026, 10, 17, 2, 43, 20, tzinfo=tz8)
    msg = "API Error: Request rejected (429) · Google Gemini: 429 ... (out of its allowance: not asked again before 02:45 UTC+8)"
    # 02:45:00 - 02:43:20 = 100s, + 2s buffer = 102s
    self.assertEqual(self.hook.rate_limit_delay(msg, now=now), 102)
    # 剩不到 30 秒時保底等 30 秒
    near = datetime(2026, 10, 17, 2, 44, 50, tzinfo=tz8)
    self.assertEqual(self.hook.rate_limit_delay(msg, now=near), 30)

  # 邊界：同樣是 unknown，但不是串流斷線那句
  def test_unknown_without_marker_ignored(self):
    self.hook.on_failure(self.payload(message="API Error: API returned an empty or malformed response (HTTP 200)"))
    self.assertEqual(self.spawned, [])
    self.assertEqual(self.actions(), ["ignore"])


class Guards(Base):
  def test_headless_child_never_types(self):
    self.hook.on_failure(self.payload(entrypoint="sdk-cli"))
    self.assertEqual(self.spawned, [])
    self.assertEqual(self.actions(), ["not_interactive"])

  # 第一回合 hook 觸發時對話記錄還沒落檔：先排程，由 send 延遲後再判
  def test_unflushed_transcript_defers_to_send(self):
    p = self.payload()
    p["transcript_path"] = str(self.tmp / "nope.jsonl")
    self.hook.on_failure(p)
    self.assertEqual(self.spawned, [["--send", "w9:p1", SESSION, str(self.tmp / "nope.jsonl")]])

  def test_send_rechecks_entrypoint_and_skips_headless(self):
    self.hook.send("w9:p1", SESSION, self.transcript(entrypoint="sdk-cli"))
    self.hook.send("w9:p1", SESSION, str(self.tmp / "nope.jsonl"))
    self.assertFalse(any(c.startswith("agent") for c in self.herdr_calls()))
    self.assertEqual(self.actions(), ["skip_not_interactive", "skip_not_interactive"])

  def test_outside_herdr_does_nothing(self):
    os.environ.pop("HERDR_PANE_ID")
    self.hook.on_failure(self.payload())
    self.assertEqual(self.spawned, [])
    self.assertEqual(self.actions(), ["no_herdr"])

  def test_cap_reached_notifies_instead_of_typing(self):
    self.hook.write_count(SESSION, 2)
    self.hook.on_failure(self.payload())
    self.assertEqual(self.spawned, [["--notify", SESSION]])
    self.assertEqual(self.hook.read_count(SESSION), 2)

  def test_second_failure_still_continues_third_stops(self):
    for _ in range(3):
      self.hook.on_failure(self.payload())
    self.assertEqual([a[0] for a in self.spawned], ["--send", "--send", "--notify"])


class Send(Base):
  def test_sends_continue_text_when_idle_and_same_session(self):
    self.hook.send("w9:p1", SESSION, self.transcript())
    calls = self.herdr_calls()
    self.assertIn("agent get w9:p1", calls)
    self.assertIn(f"agent prompt w9:p1 {self.hook.CONTINUE_TEXT}", calls)
    self.assertEqual(self.actions(), ["sent"])

  def test_main_send_accepts_explicit_delay_arg(self):
    self.hook.main(["--send", "w9:p1", SESSION, self.transcript(), "0"])
    calls = self.herdr_calls()
    self.assertIn(f"agent prompt w9:p1 {self.hook.CONTINUE_TEXT}", calls)
    self.assertEqual(self.actions(), ["sent"])

  def test_session_mismatch_skips(self):
    self.set_agent("other-session", "idle")
    self.hook.send("w9:p1", SESSION, self.transcript())
    self.assertFalse(any(c.startswith("agent prompt") for c in self.herdr_calls()))
    self.assertEqual(self.actions(), ["skip_session_mismatch"])

  def test_not_ready_skips(self):
    self.set_agent(SESSION, "working")
    self.hook.send("w9:p1", SESSION, self.transcript())
    self.assertFalse(any(c.startswith("agent prompt") for c in self.herdr_calls()))
    self.assertEqual(self.actions(), ["skip_not_ready"])

  def test_notify_calls_herdr_notification(self):
    self.hook.notify(SESSION)
    self.assertTrue(any(c.startswith("notification show") for c in self.herdr_calls()))
    self.assertEqual(self.actions(), ["notified"])


class Lifecycle(Base):
  def test_stop_resets_counter(self):
    self.hook.write_count(SESSION, 2)
    self.hook.on_stop({"session_id": SESSION})
    self.assertFalse(self.hook.counter_path(SESSION).exists())
    self.hook.on_failure(self.payload())
    self.assertEqual(self.spawned, [["--send", "w9:p1", SESSION, self.transcript()]])

  def test_stop_without_counter_is_silent(self):
    self.hook.on_stop({"session_id": SESSION})
    self.assertEqual(self.actions(), [])

  def test_disabled_sentinel(self):
    self.state.mkdir(parents=True)
    (self.state / "DISABLED").touch()
    self.hook.on_failure(self.payload())
    self.assertEqual(self.spawned, [])
    self.assertEqual(self.actions(), ["disabled"])

  def test_disabled_env(self):
    os.environ["CC_AUTO_CONTINUE"] = "0"
    self.hook.on_failure(self.payload())
    self.assertEqual(self.spawned, [])


class Pathological(Base):
  def run_hook(self, stdin, *args):
    return subprocess.run([sys.executable, str(HOOK), *args], input=stdin, capture_output=True, text=True, timeout=10)

  def test_malformed_stdin_exits_zero_silently(self):
    r = self.run_hook("not json")
    self.assertEqual(r.returncode, 0)
    self.assertEqual(r.stdout, "")

  def test_fifo_counter_does_not_hang_or_type(self):
    self.state.mkdir(parents=True)
    os.mkfifo(self.hook.counter_path(SESSION))
    r = self.run_hook(json.dumps(self.payload()))
    self.assertEqual(r.returncode, 0)
    self.assertNotIn("continue_scheduled", self.actions())

  def test_symlink_counter_not_followed(self):
    self.state.mkdir(parents=True)
    target = self.tmp / "elsewhere"
    target.write_text("keep")
    self.hook.counter_path(SESSION).symlink_to(target)
    r = self.run_hook(json.dumps(self.payload()))
    self.assertEqual(r.returncode, 0)
    self.assertEqual(target.read_text(), "keep")
    self.assertNotIn("continue_scheduled", self.actions())

  def test_fifo_log_does_not_hang(self):
    os.mkfifo(self.logf)
    r = self.run_hook(json.dumps(self.payload(error="rate_limit")))
    self.assertEqual(r.returncode, 0)

  def test_symlink_log_not_written_through(self):
    target = self.tmp / "victim"
    target.write_text("keep")
    self.logf.symlink_to(target)
    self.run_hook(json.dumps(self.payload(error="rate_limit")))
    self.assertEqual(target.read_text(), "keep")


if __name__ == "__main__":
  unittest.main(verbosity=1)
