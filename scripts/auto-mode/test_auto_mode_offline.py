import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


AUTO_MODE_DIR = Path(
  os.environ.get("AUTO_MODE_DIR") or Path(__file__).resolve().parent
).resolve()
DECISION_SCRIPT = AUTO_MODE_DIR / "decision.py"
MODE_SCRIPT = AUTO_MODE_DIR / "mode.py"
RECORDS_SCRIPT = AUTO_MODE_DIR / "records.py"

VALID_SESSION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PERSONAL_PREFLIGHT = {
  "status": "ok",
  "workspaceId": "test-personal",
  "workspaceName": "Personal",
  "planType": "pro",
  "devspace": "available",
}


def load_module(name, path):
  spec = importlib.util.spec_from_file_location(name, path)
  if spec is None or spec.loader is None:
    raise ImportError(f"cannot load module {name} from {path}")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def make_human_event(session, text, **metadata):
  return {
    "type": "user",
    "sessionId": session,
    "uuid": str(uuid.uuid4()),
    "origin": {"kind": "human"},
    "turnOrigin": "human",
    "message": {"role": "user", "content": text},
    **metadata,
  }


def snapshot_tree(root):
  entries = {}
  for path in sorted(root.rglob("*")):
    rel = str(path.relative_to(root))
    if path.is_symlink():
      entries[rel] = ("symlink", os.readlink(path))
    elif path.is_dir():
      entries[rel] = ("dir", None)
    else:
      entries[rel] = ("file", path.read_bytes())
  return entries


class AutoModeOfflineTests(unittest.TestCase):
  def setUp(self):
    tmp = tempfile.TemporaryDirectory()
    self.addCleanup(tmp.cleanup)
    self.home = Path(tmp.name).resolve()
    self.env = dict(os.environ)
    self.env["HOME"] = str(self.home)
    for var in ("HC_TERMINAL_ID", "CLAUDE_SESSION_ID", "CLAUDE_AGENT_ID", "CLAUDE_CONFIG_DIR"):
      self.env.pop(var, None)
    self.modes_dir = self.home / ".claude" / "logs" / "auto-mode" / "modes"
    self.records_dir = self.home / ".claude" / "logs" / "auto-mode" / "records"

  def run_cli(self, script, *args, terminal=None, stdin_text=None, preexec_fn=None, env_overrides=None):
    env = dict(self.env)
    if terminal is not None:
      env["HC_TERMINAL_ID"] = terminal
    if env_overrides:
      env.update(env_overrides)
    return subprocess.run(
      [sys.executable, "-IB", str(script), *args],
      env=env,
      input=stdin_text,
      capture_output=True,
      text=True,
      timeout=10,
      preexec_fn=preexec_fn,
    )

  def load_isolated(self, name, path):
    # Ensure module-level Path.home() constants bind to self.home, never real ~/.claude.
    with mock.patch.dict(os.environ, self.env, clear=True):
      module = load_module(name, path)
    if hasattr(module, "STATE_DIR"):
      self.assertEqual(module.STATE_DIR, self.modes_dir)
    if hasattr(module, "RECORDS_DIR"):
      self.assertEqual(module.RECORDS_DIR, self.records_dir)
    return module

  # 1. AUTO-01
  def test_standalone_mode_and_records_without_pi_subtask(self):
    with tempfile.TemporaryDirectory() as pkg_tmp:
      isolated = Path(pkg_tmp) / "scripts" / "auto-mode"
      isolated.mkdir(parents=True)
      for source in (MODE_SCRIPT, RECORDS_SCRIPT):
        shutil.copy2(source, isolated / source.name)
      self.assertFalse((Path(pkg_tmp) / "scripts" / "pi-subtask" / "mode.py").exists())

      mode_res = self.run_cli(isolated / "mode.py", "status", "--session", VALID_SESSION)
      self.assertEqual(mode_res.returncode, 0, mode_res.stderr or mode_res.stdout)
      mode_payload = json.loads(mode_res.stdout)
      self.assertEqual(mode_payload["key"], f"session-{VALID_SESSION}")
      self.assertIs(mode_payload["enabled"], False)

      records_res = self.run_cli(isolated / "records.py", "stats", "--session", VALID_SESSION)
      self.assertEqual(records_res.returncode, 0, records_res.stderr or records_res.stdout)
      records_payload = json.loads(records_res.stdout)
      self.assertEqual(records_payload["followed"], 0)
      self.assertEqual(records_payload["downweighted_reopened"], 0)

      term_mode_res = self.run_cli(isolated / "mode.py", "status", terminal="standalone/term-1")
      self.assertEqual(term_mode_res.returncode, 0, term_mode_res.stderr or term_mode_res.stdout)
      self.assertEqual(json.loads(term_mode_res.stdout)["key"], "terminal-standalone%2Fterm-1")

  # 2. AUTO-02
  def test_decision_whitespace_and_case_cannot_bypass_downweight(self):
    decision_mod = self.load_isolated("auto_mode_decision_02", DECISION_SCRIPT)
    decide = decision_mod.decide

    downweighted_variants = (
      " git-force-push ",
      "git-force-push\n",
      "GIT-FORCE-PUSH",
      "  company-repo-push\t",
    )
    for action in downweighted_variants:
      for preflight in (None, PERSONAL_PREFLIGHT):
        with self.subTest(action=action, preflight=bool(preflight)):
          result = decide(
            stop_kind="authorization",
            has_recommendation=True,
            has_default=False,
            action=action,
            enabled=True,
            preflight=preflight,
          )
          self.assertNotEqual(result, "allow-auto")
          self.assertEqual(result, "downweight")

    for action in (" web-gpt-pro ", "WEB-GPT-PRO"):
      for preflight in (None, PERSONAL_PREFLIGHT):
        with self.subTest(action=action, preflight=bool(preflight)):
          result = decide(
            stop_kind="authorization",
            has_recommendation=True,
            has_default=False,
            action=action,
            enabled=True,
            preflight=preflight,
          )
          self.assertNotEqual(result, "allow-auto")
          self.assertEqual(result, "downweight")

    for untrimmed_local in (" local-decision ", "local-decision\n", "\tlocal-decision"):
      for choice in (
        {"has_recommendation": True, "has_default": False},
        {"has_recommendation": False, "has_default": True},
      ):
        with self.subTest(action=untrimmed_local, choice=choice):
          result = decide(
            stop_kind="authorization",
            action=untrimmed_local,
            enabled=True,
            preflight=None,
            **choice,
          )
          self.assertNotEqual(result, "allow-auto")
          self.assertEqual(result, "require-human")

    # Sanity check canonical forms still behave as documented.
    self.assertEqual(
      decide(
        stop_kind="authorization",
        has_recommendation=True,
        has_default=False,
        action="web-gpt-pro",
        enabled=True,
        preflight=PERSONAL_PREFLIGHT,
      ),
      "allow-auto",
    )

  # 3. AUTO-03
  def test_decision_rejects_abnormal_types_and_nan_cli(self):
    decision_mod = self.load_isolated("auto_mode_decision_03", DECISION_SCRIPT)
    decide = decision_mod.decide

    abnormal_flag_cases = (
      ("yes", False, "local-decision"),
      ("yes", True, "local-decision"),
      ("yes", False, "git-force-push"),
      (1, False, "local-decision"),
      (1, True, "local-decision"),
      (1, False, "git-force-push"),
      (0, True, "git-force-push"),
      (False, [], "local-decision"),
      (True, [], "local-decision"),
      (False, [], "git-force-push"),
      (True, 1, "local-decision"),
      (None, True, "local-decision"),
    )
    for has_rec, has_def, action in abnormal_flag_cases:
      with self.subTest(has_recommendation=has_rec, has_default=has_def, action=action):
        self.assertEqual(
          decide(
            stop_kind="authorization",
            has_recommendation=has_rec,
            has_default=has_def,
            action=action,
            enabled=True,
          ),
          "require-human",
        )

    abnormal_control_cases = (
      {"enabled": 1, "stop_kind": "authorization"},
      {"enabled": "true", "stop_kind": "authorization"},
      {"enabled": None, "stop_kind": "authorization"},
      {"enabled": True, "stop_kind": 123},
      {"enabled": True, "stop_kind": "  "},
      {"enabled": True, "stop_kind": ""},
      {"enabled": True, "stop_kind": None},
    )
    for controls in abnormal_control_cases:
      for action in ("local-decision", "git-force-push"):
        with self.subTest(action=action, **controls):
          self.assertEqual(
            decide(
              has_recommendation=True,
              has_default=False,
              action=action,
              **controls,
            ),
            "require-human",
          )

    cli_invalid_inputs = (
      '{"stop_kind": "authorization", "has_recommendation": NaN, "has_default": false, "action": "local-decision", "enabled": true}',
      '{"stop_kind": "authorization", "has_recommendation": true, "has_default": false, "action": "web-gpt-pro", "enabled": true, "preflight": {"status": "ok", "workspaceId": "w", "workspaceName": "Personal", "planType": "pro", "devspace": "available", "extra": NaN}}',
      '{"stop_kind": "authorization", "has_recommendation": true, "has_default": false, "action": "local-decision", "enabled": true, "preflight": Infinity}',
      "NaN",
      "[]",
      '"x"',
      "null",
      "123",
      "{}",
      '{"stop_kind": "authorization", "has_recommendation": true, "has_default": false, "action": "local-decision"}',
      '{"stop_kind": "authorization", "has_recommendation": true, "has_default": false, "enabled": true}',
      "{not valid json",
    )
    for raw_stdin in cli_invalid_inputs:
      with self.subTest(stdin=raw_stdin):
        res = self.run_cli(DECISION_SCRIPT, "decide", stdin_text=raw_stdin)
        self.assertEqual(res.returncode, 2, res.stderr or res.stdout)
        self.assertEqual(
          json.loads(res.stdout),
          {"decision": "require-human", "context_mode": None},
        )

  # 4. AUTO-04
  def test_mode_latest_toggle_survives_corrupt_utf8_and_deep_nesting(self):
    projects = self.home / ".claude" / "projects" / "test-project"
    projects.mkdir(parents=True)
    transcript = projects / f"{VALID_SESSION}.jsonl"

    valid_on = make_human_event(VALID_SESSION, "/auto-on")
    deep_nesting = ("[" * 2000 + "]" * 2000 + "\n").encode("utf-8")
    transcript.write_bytes(
      b"\xff\xfe bad\n"
      b'{"type":\n'
      + deep_nesting
      + (json.dumps(valid_on) + "\n").encode("utf-8")
    )

    sync_res = self.run_cli(MODE_SCRIPT, "sync", "--session", VALID_SESSION)
    self.assertEqual(sync_res.returncode, 0, sync_res.stderr or sync_res.stdout)
    sync_payload = json.loads(sync_res.stdout)
    self.assertIs(sync_payload["enabled"], True)
    self.assertEqual(sync_payload["source_event"], valid_on["uuid"])

    status_res = self.run_cli(MODE_SCRIPT, "status", "--session", VALID_SESSION)
    self.assertEqual(status_res.returncode, 0, status_res.stderr or status_res.stdout)
    status_payload = json.loads(status_res.stdout)
    self.assertIs(status_payload["enabled"], True)
    self.assertEqual(status_payload["source_event"], valid_on["uuid"])

  # 5. Path traversal and state_key type safety
  def test_mode_session_and_terminal_path_safety(self):
    decoy_home = self.home / "evil.json"
    decoy_home.write_text(
      json.dumps({"enabled": True, "applied_events": [VALID_SESSION]}),
      encoding="utf-8",
    )
    decoy_home.chmod(0o600)

    decoy_parent = self.home / ".claude" / "logs" / "auto-mode"
    decoy_parent.mkdir(parents=True, mode=0o700)
    decoy_parent_file = decoy_parent / "evil.json"
    decoy_parent_file.write_text(
      json.dumps([
        {
          "id": "D1", "task": "t", "stop": "s", "recommendation": "r",
          "adopted": "a", "disposition": "followed", "reason": "ok",
          "undo": "u", "reply": "unreviewed", "changed_value": None,
        }
      ]),
      encoding="utf-8",
    )
    decoy_parent_file.chmod(0o600)

    before_tree = snapshot_tree(self.home)

    malicious_cli_sessions = ("../evil", "../../etc/passwd", "a/b", "", "not-a-uuid")
    for bad_session in malicious_cli_sessions:
      for script, cmd in ((MODE_SCRIPT, "status"), (RECORDS_SCRIPT, "stats")):
        with self.subTest(script=script.name, bad_session=bad_session):
          res = self.run_cli(script, cmd, "--session", bad_session)
          self.assertNotEqual(res.returncode, 0)
          self.assertNotIn("Traceback", res.stderr)
          self.assertEqual(snapshot_tree(self.home), before_tree)

    malicious_terminals = ("../evil", "a..b", "term with space", "a" * 73, ";rm")
    for bad_terminal in malicious_terminals:
      for script, cmd in ((MODE_SCRIPT, "status"), (RECORDS_SCRIPT, "stats")):
        with self.subTest(script=script.name, bad_terminal=bad_terminal):
          res = self.run_cli(script, cmd, "--session", VALID_SESSION, terminal=bad_terminal)
          self.assertNotEqual(res.returncode, 0)
          self.assertNotIn("Traceback", res.stderr)
          self.assertEqual(snapshot_tree(self.home), before_tree)

    # POSIX execve forbids NUL in argv, so exercise "foo\x00bar" in-process via main() and state_key().
    mode_mod = self.load_isolated("auto_mode_mode_05", MODE_SCRIPT)
    records_mod = self.load_isolated("auto_mode_records_05", RECORDS_SCRIPT)
    pi = mode_mod.load_pi_mode()

    with self.assertRaises(pi.UsageError):
      mode_mod.state_key(pi, VALID_SESSION, terminal=123)

    with self.assertRaises(pi.UsageError):
      mode_mod.state_key(pi, "foo\x00bar", terminal="")

    for mod, cmd in ((mode_mod, "status"), (records_mod, "stats")):
      with self.subTest(in_process=mod.__name__, cmd=cmd):
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with (
          mock.patch.dict(os.environ, self.env, clear=True),
          mock.patch.object(sys, "argv", [mod.__name__, cmd, "--session", "foo\x00bar"]),
          redirect_stdout(out_buf),
          redirect_stderr(err_buf),
        ):
          rc = mod.main()
        self.assertNotEqual(rc, 0)
        self.assertNotIn("Traceback", err_buf.getvalue())
        self.assertEqual(snapshot_tree(self.home), before_tree)

  # 6. AUTO-05
  def test_mode_lock_state_restrictive_umask(self):
    terminal = "umask-term"
    res = self.run_cli(
      MODE_SCRIPT,
      "on",
      "--source",
      "button",
      terminal=terminal,
      preexec_fn=lambda: os.umask(0o177),
    )
    self.assertEqual(res.returncode, 0, res.stderr or res.stdout)
    payload = json.loads(res.stdout)
    self.assertIs(payload["enabled"], True)

    lock_path = self.modes_dir / f"terminal-{terminal}.lock"
    state_path = self.modes_dir / f"terminal-{terminal}.json"
    self.assertTrue(lock_path.exists())
    self.assertTrue(state_path.exists())
    self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)
    self.assertEqual(stat.S_IMODE(state_path.stat().st_mode), 0o600)

    status_res = self.run_cli(MODE_SCRIPT, "status", terminal=terminal)
    self.assertEqual(status_res.returncode, 0, status_res.stderr or status_res.stdout)
    self.assertIs(json.loads(status_res.stdout)["enabled"], True)

    off_res = self.run_cli(MODE_SCRIPT, "off", "--source", "button", terminal=terminal)
    self.assertEqual(off_res.returncode, 0, off_res.stderr or off_res.stdout)
    self.assertIs(json.loads(off_res.stdout)["enabled"], False)

  # 7. Multiprocess concurrency stress
  def test_records_multiprocess_concurrent_append_review_closeout(self):
    terminal = "conc/term-1"
    expected_key = "terminal-conc%2Fterm-1"
    barrier = threading.Barrier(8, timeout=5)

    def do_append(index):
      barrier.wait()
      res = self.run_cli(
        RECORDS_SCRIPT,
        "append",
        "--session", VALID_SESSION,
        "--task", "conc-task",
        "--stop", "commit",
        "--recommendation", "run tests",
        "--adopted", "run tests",
        "--disposition", "followed",
        "--reason", f"concurrent reason {index}",
        "--undo", "revert",
        terminal=terminal,
      )
      self.assertEqual(res.returncode, 0, res.stderr or res.stdout)
      return json.loads(res.stdout)

    with ThreadPoolExecutor(max_workers=8) as pool:
      appended = list(pool.map(do_append, range(8)))

    self.assertEqual(sorted(row["id"] for row in appended), [f"D{i}" for i in range(1, 9)])
    record_file = self.records_dir / f"{expected_key}.json"
    rows = json.loads(record_file.read_text(encoding="utf-8"))
    self.assertEqual(len(rows), 8)
    self.assertEqual([row["id"] for row in rows], [f"D{i}" for i in range(1, 9)])
    self.assertEqual({row["reason"] for row in rows}, {f"concurrent reason {i}" for i in range(8)})
    self.assertEqual([p for p in self.records_dir.iterdir() if p.name.endswith(".tmp")], [])

    ops = [
      ("review", "--id", "D1", "--reply", "kept"),
      ("review", "--id", "D2", "--reply", "kept"),
      ("review", "--id", "D3", "--reply", "kept"),
      ("review", "--id", "D4", "--reply", "kept"),
      ("review", "--id", "D5", "--reply", "changed", "--changed-value", "new choice"),
      ("review", "--id", "D6", "--reply", "changed", "--changed-value", "alt choice"),
      ("closeout", "--task", "conc-task"),
      ("stats",),
    ]
    op_barrier = threading.Barrier(len(ops), timeout=5)

    def do_op(cli_args):
      op_barrier.wait()
      res = self.run_cli(RECORDS_SCRIPT, *cli_args, "--session", VALID_SESSION, terminal=terminal)
      self.assertEqual(res.returncode, 0, res.stderr or res.stdout)
      return cli_args[0], json.loads(res.stdout)

    with ThreadPoolExecutor(max_workers=8) as pool:
      op_results = list(pool.map(do_op, ops))

    for kind, data in op_results:
      if kind == "closeout":
        self.assertEqual(len(data), 8)
      elif kind == "stats":
        self.assertEqual(data["followed"], 8)
        self.assertEqual(data["unreviewed"] + data["kept"] + data["changed"], 8)

    final_stats = self.run_cli(RECORDS_SCRIPT, "stats", "--session", VALID_SESSION, terminal=terminal)
    self.assertEqual(final_stats.returncode, 0, final_stats.stderr or final_stats.stdout)
    self.assertEqual(
      json.loads(final_stats.stdout),
      {
        "followed": 8,
        "unreviewed": 2,
        "kept": 4,
        "changed": 2,
        "kept_rate": {"numerator": 4, "denominator": 6, "display": "66.67%"},
        "reviewed_coverage": {"numerator": 6, "denominator": 8, "display": "75.00%"},
        "downweighted_reopened": 0,
      },
    )
    self.assertEqual([p for p in self.records_dir.iterdir() if p.name.endswith(".tmp")], [])

  # 8. AUTO-06
  def test_records_mutate_review_enforces_valid_record(self):
    mode_mod = self.load_isolated("auto_mode_mode_08", MODE_SCRIPT)
    records_mod = self.load_isolated("auto_mode_records_08", RECORDS_SCRIPT)
    pi = mode_mod.load_pi_mode()

    self.records_dir.mkdir(parents=True, mode=0o700)
    key = f"session-{VALID_SESSION}"
    filename = f"{key}.json"
    record_file = self.records_dir / filename
    initial_rows = [
      {
        "id": "D1",
        "task": "task-a",
        "stop": "發布",
        "recommendation": "採用 A",
        "adopted": "採用 A",
        "disposition": "followed",
        "reason": "變更可復原。",
        "undo": "還原選項",
        "reply": "unreviewed",
        "changed_value": None,
      }
    ]
    dirfd = os.open(self.records_dir, os.O_RDONLY)
    try:
      invalid_reviews = (
        SimpleNamespace(command="review", id="D1", reply="changed", changed_value="   "),
        SimpleNamespace(command="review", id="D1", reply="changed", changed_value=None),
        SimpleNamespace(command="review", id="D1", reply="kept", changed_value="oops"),
        SimpleNamespace(command="review", id="D1", reply="invalid-reply", changed_value=None),
      )
      for bad_args in invalid_reviews:
        with self.subTest(reply=bad_args.reply, changed_value=bad_args.changed_value):
          mode_mod.write_json(dirfd, filename, initial_rows)
          before_bytes = record_file.read_bytes()
          with self.assertRaises(ValueError):
            records_mod.mutate(mode_mod, pi, dirfd, key, filename, bad_args)
          self.assertEqual(record_file.read_bytes(), before_bytes)
    finally:
      os.close(dirfd)

  # 9. Corrupt files, schema violations, and symlink resistance
  def test_records_corrupt_and_symlink_resistance(self):
    self.records_dir.mkdir(parents=True, mode=0o700)
    record_file = self.records_dir / f"session-{VALID_SESSION}.json"

    valid_row = {
      "id": "D1",
      "task": "task-a",
      "stop": "發布",
      "recommendation": "選 A",
      "adopted": "選 A",
      "disposition": "followed",
      "reason": "安全。",
      "undo": "還原",
      "reply": "unreviewed",
      "changed_value": None,
    }
    corrupt_payloads = (
      ("truncated", b'[{"id": "D1"'),
      ("non_list", json.dumps(valid_row).encode("utf-8")),
      ("non_contiguous_id", json.dumps([{**valid_row, "id": "D2"}]).encode("utf-8")),
      ("multiline_reason", json.dumps([{**valid_row, "reason": "line1\nline2"}]).encode("utf-8")),
    )

    commands = (
      ("stats",),
      ("closeout", "--task", "task-a"),
      (
        "append", "--task", "task-a", "--stop", "確認", "--recommendation", "選 A",
        "--adopted", "選 A", "--disposition", "followed", "--reason", "安全。",
      ),
      ("review", "--id", "D1", "--reply", "kept"),
    )

    for label, payload in corrupt_payloads:
      record_file.write_bytes(payload)
      record_file.chmod(0o600)
      for cmd in commands:
        with self.subTest(case=label, cmd=cmd[0]):
          res = self.run_cli(RECORDS_SCRIPT, *cmd, "--session", VALID_SESSION)
          self.assertEqual(res.returncode, 1, res.stderr or res.stdout)
          self.assertNotIn("Traceback", res.stderr)
          self.assertEqual(res.stdout, "")
          self.assertEqual(record_file.read_bytes(), payload)

    # Multi-line reason rejected on append when no corrupt file exists.
    record_file.unlink()
    ml_res = self.run_cli(
      RECORDS_SCRIPT,
      "append",
      "--session", VALID_SESSION,
      "--task", "task-a",
      "--stop", "確認",
      "--recommendation", "選 A",
      "--adopted", "選 A",
      "--disposition", "followed",
      "--reason", "line1\nline2",
    )
    self.assertEqual(ml_res.returncode, 1, ml_res.stderr or ml_res.stdout)
    self.assertNotIn("Traceback", ml_res.stderr)
    self.assertEqual(ml_res.stdout, "")
    self.assertFalse(record_file.exists())

    # Symlinked record file must not be followed or overwritten.
    outside_target = self.home / "outside_target.json"
    outside_bytes = json.dumps([valid_row]).encode("utf-8")
    outside_target.write_bytes(outside_bytes)
    outside_target.chmod(0o600)
    record_file.symlink_to(outside_target)

    for cmd in commands:
      with self.subTest(case="symlink", cmd=cmd[0]):
        res = self.run_cli(RECORDS_SCRIPT, *cmd, "--session", VALID_SESSION)
        self.assertEqual(res.returncode, 1, res.stderr or res.stdout)
        self.assertNotIn("Traceback", res.stderr)
        self.assertEqual(res.stdout, "")
        self.assertTrue(record_file.is_symlink())
        self.assertEqual(outside_target.read_bytes(), outside_bytes)

  # 10. Mutant M15: corrupt-state recovery does not replay when broken_at == timestamp
  def test_corrupt_state_recovery_exact_equal_timestamp_not_replayed(self):
    self.modes_dir.mkdir(parents=True, mode=0o700)
    state_path = self.modes_dir / "terminal-recovery.json"
    state_path.write_text('{"enabled":', encoding="utf-8")
    state_path.chmod(0o600)
    target_epoch = 1700000000
    os.utime(state_path, (target_epoch, target_epoch))
    broken_at = datetime.fromtimestamp(state_path.stat().st_mtime, timezone.utc)

    projects = self.home / ".claude" / "projects" / "test-project"
    projects.mkdir(parents=True)
    transcript = projects / f"{VALID_SESSION}.jsonl"
    on_event = make_human_event(VALID_SESSION, "/auto-on", timestamp=broken_at.isoformat())
    transcript.write_text(json.dumps(on_event) + "\n", encoding="utf-8")

    res = self.run_cli(MODE_SCRIPT, "sync", "--session", VALID_SESSION, terminal="recovery")
    self.assertEqual(res.returncode, 0, res.stderr or res.stdout)
    payload = json.loads(res.stdout)
    self.assertIs(payload["enabled"], False)
    self.assertIsNone(payload["source_event"])

  # 11. Mutant M17: button on/off without HC_TERMINAL_ID is rejected
  def test_button_on_off_without_terminal_rejected(self):
    for cmd in ("on", "off"):
      with self.subTest(cmd=cmd):
        res = self.run_cli(MODE_SCRIPT, cmd, "--source", "button", "--session", VALID_SESSION)
        self.assertEqual(res.returncode, 1, res.stderr or res.stdout)
        payload = json.loads(res.stdout)
        self.assertIs(payload["enabled"], False)
        self.assertEqual(payload["error"], "button-source-and-terminal-required-for-direct-write")
    self.assertFalse(self.modes_dir.exists())

  # 12. Mutant M18: sync when CLAUDE_SESSION_ID differs from --session is rejected
  def test_sync_mismatched_active_session_env_rejected(self):
    projects = self.home / ".claude" / "projects" / "test-project"
    projects.mkdir(parents=True)
    transcript = projects / f"{VALID_SESSION}.jsonl"
    transcript.write_text(json.dumps(make_human_event(VALID_SESSION, "/auto-on")) + "\n", encoding="utf-8")

    other_session = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    res = self.run_cli(
      MODE_SCRIPT,
      "sync",
      "--session",
      VALID_SESSION,
      env_overrides={"CLAUDE_SESSION_ID": other_session},
    )
    self.assertEqual(res.returncode, 1, res.stderr or res.stdout)
    payload = json.loads(res.stdout)
    self.assertIs(payload["enabled"], False)
    self.assertEqual(payload["error"], "transcript-session-mismatch")

  # 13. Mutant M14: state JSON with extra unexpected key is treated as corrupt
  def test_extra_key_in_state_json_treated_as_corrupt(self):
    self.modes_dir.mkdir(parents=True, mode=0o700)
    state_path = self.modes_dir / f"session-{VALID_SESSION}.json"
    state_path.write_text(
      json.dumps({"enabled": True, "applied_events": [], "extra": 1}),
      encoding="utf-8",
    )
    state_path.chmod(0o600)

    res = self.run_cli(MODE_SCRIPT, "status", "--session", VALID_SESSION)
    self.assertEqual(res.returncode, 0, res.stderr or res.stdout)
    payload = json.loads(res.stdout)
    self.assertIs(payload["enabled"], False)
    self.assertIsNone(payload["source_event"])


if __name__ == "__main__":
  unittest.main(verbosity=2)
