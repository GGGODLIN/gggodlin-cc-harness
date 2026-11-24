import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODE = Path(__file__).with_name("mode.py")


def event(session, text, **metadata):
  return {
    "type": "user", "sessionId": session, "uuid": str(uuid.uuid4()),
    "origin": {"kind": "human"}, "turnOrigin": "human",
    "message": {"role": "user", "content": text}, **metadata,
  }


class ToggleTests(unittest.TestCase):
  def setUp(self):
    tmp = tempfile.TemporaryDirectory()
    self.addCleanup(tmp.cleanup)
    self.home = Path(tmp.name).resolve()
    self.env = {**os.environ, "HOME": str(self.home)}
    for name in ("HC_TERMINAL_ID", "CLAUDE_SESSION_ID", "CLAUDE_AGENT_ID", "CLAUDE_CONFIG_DIR"):
      self.env.pop(name, None)
    self.session = str(uuid.uuid4())
    self.projects = self.home / ".claude" / "projects" / "test-project"
    self.projects.mkdir(parents=True)
    self.state = self.home / ".claude" / "logs" / "auto-mode" / "modes" / f"session-{self.session}.json"

  def transcript(self, *events, session=None):
    path = self.projects / f"{session or self.session}.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in events), encoding="utf-8")

  def cli(self, *args, terminal=None, child=False, session=None, denied=False):
    argv = [sys.executable, "-IB", str(MODE), *args]
    if session != "":
      argv += ["--session", session or self.session]
    env = dict(self.env)
    if terminal is not None:
      env["HC_TERMINAL_ID"] = terminal
    if child:
      env["CLAUDE_AGENT_ID"] = "test-child"
    result = subprocess.run(argv, env=env, text=True, capture_output=True, timeout=5)
    self.assertEqual(result.returncode, 1 if denied else 0, result.stderr or result.stdout)
    return json.loads(result.stdout)

  def status(self, enabled, **kwargs):
    self.assertIs(self.cli("status", **kwargs)["enabled"], enabled)

  def test_human_toggle(self):
    on = event(self.session, "/auto-on")
    self.transcript(on)
    self.assertEqual(self.cli("sync"), {
      "key": f"session-{self.session}", "enabled": True, "source_event": on["uuid"],
    })
    off = event(self.session, "<command-message>auto-off</command-message>\n"
                "<command-name>/auto-off</command-name>\n<command-args></command-args>")
    self.transcript(on, off)
    self.assertEqual(self.cli("sync")["source_event"], off["uuid"])
    self.status(False)

  def test_nonhuman_toggle(self):
    on = event(self.session, "/auto-on")
    off = event(self.session, "/auto-off")
    def nonhuman(text):
      return [
        event(self.session, text, origin={"kind": "task-notification"}),
        event(self.session, text, turnOrigin="sdk"),
        event(self.session, text, isCompactSummary=True),
        event(self.session, text, type="assistant", message={"role": "assistant", "content": text}),
      ]
    self.transcript(off, *nonhuman("/auto-on"))
    self.assertEqual(self.cli("sync")["source_event"], off["uuid"])
    self.transcript(*nonhuman("/auto-on"))
    self.status(False)
    self.assertIs(self.cli("sync")["enabled"], False)
    self.transcript(on, *nonhuman("/auto-off"))
    self.assertEqual(self.cli("sync")["source_event"], on["uuid"])
    self.transcript(*nonhuman("/auto-off"))
    self.assertIs(self.cli("sync")["enabled"], True)

  def test_toggle_command_is_rejected_by_argparse(self):
    result = subprocess.run(
      [sys.executable, "-IB", str(MODE), "toggle", "--source", "button"],
      env={**self.env, "HC_TERMINAL_ID": "fixture-terminal"}, text=True, capture_output=True, timeout=5,
    )
    self.assertEqual(result.returncode, 2, result.stderr or result.stdout)
    self.assertIn("invalid choice: 'toggle'", result.stderr)

  def test_button_off_replay(self):
    self.transcript(event(self.session, "/auto-on"))
    terminal = "terminal/1"
    applied = self.cli("sync", terminal=terminal)
    self.assertIs(applied["enabled"], True)
    self.assertEqual(self.cli("off", "--source", "button", terminal=terminal, session=""),
                     {**applied, "enabled": False})
    self.assertEqual(self.cli("sync", terminal=terminal), {**applied, "enabled": False})

  def test_invalid_state_is_off(self):
    self.status(False)
    self.transcript(event(self.session, "/auto-on"))
    self.cli("sync")
    self.status(True)
    for invalid in (b'{"enabled":', b'{"enabled":"yes","applied_events":[]}', b'[]', b'\xff'):
      with self.subTest(invalid=invalid):
        self.state.write_bytes(invalid)
        self.status(False)
        self.assertEqual(self.state.read_bytes(), invalid)
    self.state.unlink()
    self.status(False)

  def corrupt_terminal_state(self):
    self.state.parent.mkdir(mode=0o700, parents=True)
    path = self.state.with_name("terminal-recovery.json")
    path.write_text('{"enabled":', encoding="utf-8")
    path.chmod(0o600)
    return path

  def test_button_on_rebuilds_corrupt_state(self):
    path = self.corrupt_terminal_state()
    self.status(False, terminal="recovery")
    self.cli("on", "--source", "button", terminal="recovery", child=True, denied=True)
    self.assertEqual(path.read_text(encoding="utf-8"), '{"enabled":')
    self.assertIs(self.cli("on", "--source", "button", terminal="recovery")["enabled"], True)
    self.status(True, terminal="recovery")

  def test_sync_ignores_pre_recovery_toggle_and_applies_new_toggle(self):
    self.corrupt_terminal_state()
    old = event(self.session, "/auto-on", timestamp=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    self.transcript(old)
    self.cli("off", "--source", "button", terminal="recovery")
    self.assertEqual(self.cli("sync", terminal="recovery"), {
      "key": "terminal-recovery", "enabled": False, "source_event": None,
    })
    new = event(self.session, "/auto-on", timestamp=datetime.now(timezone.utc).isoformat())
    self.transcript(old, new)
    self.assertEqual(self.cli("sync", terminal="recovery"), {
      "key": "terminal-recovery", "enabled": True, "source_event": new["uuid"],
    })
    self.status(True, terminal="recovery")

  def test_human_sync_can_rebuild_corrupt_state_without_replaying(self):
    path = self.corrupt_terminal_state()
    old = event(self.session, "/auto-on", timestamp=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    self.transcript({**old, "turnOrigin": "sdk"})
    self.assertIs(self.cli("sync", terminal="recovery")["enabled"], False)
    self.assertEqual(path.read_text(encoding="utf-8"), '{"enabled":')
    self.transcript(old)
    self.assertIs(self.cli("sync", terminal="recovery")["enabled"], False)
    self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["enabled"], False)
    new = event(self.session, "/auto-on", timestamp=datetime.now(timezone.utc).isoformat())
    self.transcript(old, new)
    self.assertEqual(self.cli("sync", terminal="recovery")["source_event"], new["uuid"])
    self.status(True, terminal="recovery")

  def test_first_sync_applies_toggle_typed_after_state_broke(self):
    path = self.corrupt_terminal_state()
    broken_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    os.utime(path, (broken_at.timestamp(), broken_at.timestamp()))
    before = event(self.session, "/auto-on", timestamp=(broken_at - timedelta(minutes=1)).isoformat())
    after = event(self.session, "/auto-on", timestamp=datetime.now(timezone.utc).isoformat())
    self.transcript(before, after)
    self.assertEqual(self.cli("sync", terminal="recovery"), {
      "key": "terminal-recovery", "enabled": True, "source_event": after["uuid"],
    })
    self.assertEqual(self.cli("sync", terminal="recovery")["source_event"], after["uuid"])
    self.status(True, terminal="recovery")

  def test_terminal_and_session_keys(self):
    other_session = str(uuid.uuid4())
    terminal = "terminal/1"
    self.transcript(event(self.session, "/auto-on"))
    self.cli("sync", terminal=terminal)
    self.status(True, terminal=terminal, session=other_session)
    self.status(False, terminal="terminal_1", session=other_session)
    self.status(False)
    self.cli("sync")
    self.status(True)
    self.status(False, session=other_session)

  def test_maximum_encoded_terminal_name_fits_atomic_write(self):
    terminal = "/" * 72
    expected = {"key": "terminal-" + "%2F" * 72, "enabled": True, "source_event": None}
    self.assertEqual(self.cli("on", "--source", "button", terminal=terminal, session=""), expected)
    self.assertEqual(self.cli("status", terminal=terminal), expected)
    self.assertEqual(self.cli("on", "--source", "button", terminal="a" * 73, denied=True),
                     {"enabled": False, "error": "bad-terminal"})
    self.assertEqual({item.name for item in self.state.parent.iterdir()},
                     {expected["key"] + ".json", expected["key"] + ".lock"})

  def test_active_session_environment_and_explicit_session_route_separately(self):
    other_session = str(uuid.uuid4())
    on = event(self.session, "/auto-on")
    self.transcript(on)
    self.env["CLAUDE_SESSION_ID"] = self.session
    self.assertEqual(self.cli("sync", session=""), {
      "key": f"session-{self.session}", "enabled": True, "source_event": on["uuid"],
    })
    self.assertEqual(self.cli("status", session=other_session), {
      "key": f"session-{other_session}", "enabled": False, "source_event": None,
    })
    self.assertEqual(self.cli("status", session="")["source_event"], on["uuid"])

  def test_subagent_can_only_read(self):
    on = event(self.session, "/auto-on")
    off = event(self.session, "/auto-off")
    terminal = "terminal/1"
    self.transcript(on)
    old = self.cli("sync", terminal=terminal)
    self.transcript(on, off)
    for args in (("sync",), ("on", "--source", "button"), ("off", "--source", "button")):
      self.assertEqual(self.cli(*args, terminal=terminal, child=True, denied=True)["error"], "child-caller")
      self.assertEqual(self.cli("status", terminal=terminal, child=True), old)
    self.assertIs(self.cli("sync", terminal=terminal)["enabled"], False)
    self.assertIs(self.cli("on", "--source", "button", terminal=terminal)["enabled"], True)
    self.assertIs(self.cli("off", "--source", "button", terminal=terminal)["enabled"], False)

  def test_button_and_sync_are_serializable(self):
    on = event(self.session, "/auto-on")
    self.transcript(on)
    with ThreadPoolExecutor(max_workers=2) as pool:
      for attempt in range(8):
        with self.subTest(attempt=attempt):
          terminal = f"terminal/{attempt}"
          sync_future = pool.submit(self.cli, "sync", terminal=terminal)
          button_future = pool.submit(self.cli, "off", "--source", "button", terminal=terminal)
          sync, button = sync_future.result(), button_future.result()
          self.assertEqual((sync["enabled"], sync["source_event"]), (True, on["uuid"]))
          self.assertIn((button["enabled"], button["source_event"]), ((False, None), (False, on["uuid"])))
          final = {**sync, "enabled": button["source_event"] is None}
          self.assertEqual(self.cli("status", terminal=terminal), final)
          self.assertEqual(self.cli("sync", terminal=terminal), final)


if __name__ == "__main__":
  if not unittest.main(verbosity=2, exit=False).result.wasSuccessful():
    sys.exit(1)
  print("AUTO_MODE_TOGGLE_CONTRACT_OK")
