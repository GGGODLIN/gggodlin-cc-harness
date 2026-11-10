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
    self.hc_calls_file = self.tmp / "hc-calls.txt"
    self.hc_term_json = self.tmp / "hc-term.json"
    self.app_data = self.tmp / "herdr-app-data"
    fake = self.tmp / "herdr"
    fake.write_text(
      "#!/bin/bash\n"
      f'printf "%s\\n" "$*" >> "{self.calls}"\n'
      f'if [ "$1 $2" = "agent get" ]; then cat "{self.agent_json}"; fi\n'
    )
    fake.chmod(0o755)
    fake_hc = self.tmp / "hc"
    fake_hc.write_text(
      "#!/bin/bash\n"
      f'printf "%s\\n" "$*" >> "{self.hc_calls_file}"\n'
      f'if [ "$1" = "get" ]; then cat "{self.hc_term_json}"; fi\n'
    )
    fake_hc.chmod(0o755)
    self.set_agent(SESSION, "idle")
    self.set_hc_term("idle")
    self.env = {
      "CC_AUTO_CONTINUE_STATE_DIR": str(self.state),
      "CC_AUTO_CONTINUE_LOG": str(self.logf),
      "HERDR_BIN_PATH": str(fake),
      "HC_BIN_PATH": str(fake_hc),
      "HERDR_APP_DATA_DIR": str(self.app_data),
      "HERDR_ENV": "1",
      "HERDR_PANE_ID": "w9:p1",
    }
    self.old_env = {k: os.environ.get(k) for k in [*self.env, "CC_AUTO_CONTINUE", "HC_TERMINAL_ID"]}
    os.environ.update(self.env)
    os.environ.pop("CC_AUTO_CONTINUE", None)
    os.environ.pop("HC_TERMINAL_ID", None)
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

  def set_hc_term(self, state, app="claude-code"):
    self.hc_term_json.write_text(json.dumps({"address": "t13", "state": "live", "status": {"app": app, "state": state}}))

  def set_cc_status(self, term, session):
    d = self.app_data / "cc-status"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{term.replace('/', '_')}.json").write_text(json.dumps({"terminal": term, "session_id": session}))

  def set_cc_controls(self, term, session):
    d = self.app_data / "cc-controls"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{term.replace('/', '_')}.json").write_text(json.dumps({"terminal": term, "sessionId": session}))

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

  def hc_calls(self):
    if not self.hc_calls_file.exists():
      return []
    with open(self.hc_calls_file, "r", encoding="utf-8", newline="\n") as f:
      return [line[:-1] if line.endswith("\n") else line for line in f]


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

  def test_invalid_hc_terminal_id_rejected_without_fallback(self):
    os.environ["HC_TERMINAL_ID"] = "bad;id"
    self.hook.on_failure(self.payload())
    self.assertEqual(self.spawned, [])
    self.assertEqual(self.actions(), ["no_herdr"])

  def test_hc_terminal_id_schedules_with_hc_prefix(self):
    os.environ["HC_TERMINAL_ID"] = "t13"
    os.environ.pop("HERDR_ENV", None)
    os.environ.pop("HERDR_PANE_ID", None)
    self.hook.on_failure(self.payload())
    self.assertEqual(self.spawned, [["--send", "hc:t13", SESSION, self.transcript()]])
    self.assertEqual(self.actions(), ["continue_scheduled"])

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

  def test_notify_skips_herdr_in_hc_mode(self):
    self.hook.notify(SESSION, "hc:t13")
    self.assertEqual(self.herdr_calls(), [])
    self.assertEqual(self.actions(), ["skip_hc_notify"])
    os.environ["HC_TERMINAL_ID"] = "t13"
    self.hook.notify(SESSION)
    self.assertEqual(self.herdr_calls(), [])
    self.assertEqual(self.actions(), ["skip_hc_notify", "skip_hc_notify"])

  def test_verify_hc_session_matches_requires_positive_match(self):
    self.assertEqual(self.hook._verify_hc_session_matches("t13", ""), "match")
    self.assertEqual(self.hook._verify_hc_session_matches("t13", SESSION), "pending")
    self.set_cc_status("t13", SESSION)
    self.assertEqual(self.hook._verify_hc_session_matches("t13", SESSION), "match")
    self.set_cc_controls("t13", "other-session")
    self.assertEqual(self.hook._verify_hc_session_matches("t13", SESSION), "mismatch")
    self.set_cc_controls("t13", SESSION)
    self.assertEqual(self.hook._verify_hc_session_matches("t13", SESSION), "match")

  def test_hc_sends_continue_text_when_idle_and_same_session(self):
    self.set_cc_status("t13", SESSION)
    self.hook.send("hc:t13", SESSION, self.transcript())
    calls = self.hc_calls()
    self.assertIn("get t13", calls)
    self.assertIn(f"send t13 {self.hook.CONTINUE_TEXT}\r", calls)
    self.assertEqual(self.actions(), ["sent"])

  def test_hc_missing_session_files_polls_then_skips(self):
    self.hook.READY_POLL_SECONDS = 0.05
    orig_sleep = self.hook.time.sleep
    self.hook.time.sleep = lambda _s: None
    try:
      self.hook.send("hc:t13", SESSION, self.transcript())
    finally:
      self.hook.time.sleep = orig_sleep
      self.hook.READY_POLL_SECONDS = 15
    self.assertFalse(any(c.startswith("send ") for c in self.hc_calls()))
    self.assertEqual(self.actions(), ["skip_session_mismatch"])

  def test_hc_waits_for_delayed_session_file_then_sends(self):
    sleeps = 0
    orig_sleep = self.hook.time.sleep
    def fake_sleep(_s):
      nonlocal sleeps
      sleeps += 1
      if sleeps >= 2:
        self.set_cc_status("t13", SESSION)
    self.hook.time.sleep = fake_sleep
    try:
      self.hook.send("hc:t13", SESSION, self.transcript())
    finally:
      self.hook.time.sleep = orig_sleep
    self.assertIn(f"send t13 {self.hook.CONTINUE_TEXT}\r", self.hc_calls())
    self.assertEqual(self.actions(), ["sent"])

  def test_hc_session_mismatch_in_cc_controls_skips(self):
    self.set_cc_controls("t13", "other-session")
    self.hook.send("hc:t13", SESSION, self.transcript())
    self.assertFalse(any(c.startswith("send ") for c in self.hc_calls()))
    self.assertEqual(self.actions(), ["skip_session_mismatch"])

  # 2026-11-02～03 實際踩過：hc 在 API 錯誤後回報 state=error，舊條件只認 idle/done，8 次送字 6 次 skip_not_ready
  def test_hc_sends_when_terminal_in_error_state_after_api_failure(self):
    self.set_hc_term("error")
    self.set_cc_status("t13", SESSION)
    self.hook.send("hc:t13", SESSION, self.transcript())
    self.assertIn(f"send t13 {self.hook.CONTINUE_TEXT}\r", self.hc_calls())
    self.assertEqual(self.actions(), ["sent"])

  def test_hc_error_state_with_other_session_still_skips(self):
    self.set_hc_term("error")
    self.set_cc_controls("t13", "other-session")
    self.hook.send("hc:t13", SESSION, self.transcript())
    self.assertFalse(any(c.startswith("send ") for c in self.hc_calls()))
    self.assertEqual(self.actions(), ["skip_session_mismatch"])

  def test_hc_working_state_does_not_send(self):
    self.hook.READY_POLL_SECONDS = 0.05
    self.set_hc_term("working")
    self.set_cc_status("t13", SESSION)
    orig_sleep = self.hook.time.sleep
    self.hook.time.sleep = lambda _s: None
    try:
      self.hook.send("hc:t13", SESSION, self.transcript())
    finally:
      self.hook.time.sleep = orig_sleep
    self.assertFalse(any(c.startswith("send ") for c in self.hc_calls()))
    self.assertEqual(self.actions(), ["skip_not_ready"])

  def test_hc_non_claude_app_skips_as_mismatch(self):
    self.set_hc_term("idle", app="zsh")
    self.hook.send("hc:t13", SESSION, self.transcript())
    self.assertFalse(any(c.startswith("send ") for c in self.hc_calls()))
    self.assertEqual(self.actions(), ["skip_session_mismatch"])

  def test_send_aborts_if_disabled_during_sleep(self):
    def disable_on_sleep(_delay):
      self.state.mkdir(parents=True, exist_ok=True)
      (self.state / "DISABLED").touch()
    orig_sleep = self.hook.time.sleep
    self.hook.time.sleep = disable_on_sleep
    try:
      rc = self.hook.send("w9:p1", SESSION, self.transcript())
    finally:
      self.hook.time.sleep = orig_sleep
    self.assertEqual(rc, 0)
    self.assertEqual(self.herdr_calls(), [])
    self.assertEqual(self.actions(), ["disabled"])


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
