#!/usr/bin/env python3

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


HOOK = Path(__file__).with_name("pr-review-c4-dispatch-gate.py")
ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "scripts/test_pr_review_c4.py"
SPEC = importlib.util.spec_from_file_location("c4_tests", TESTS)
C4_TESTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(C4_TESTS)
ENVELOPE = C4_TESTS.MODULE.dispatch_envelope(C4_TESTS.packet())


def payload(tool_input, session="session-c4-gate-001", tool_use="tool-c4-gate-001"):
  return {
    "session_id": session,
    "tool_use_id": tool_use,
    "tool_name": "Agent",
    "tool_input": tool_input,
  }


def agent_text(tool_input):
  return json.dumps(tool_input, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_state(runtime, session, tool_input, **overrides):
  runtime.mkdir(mode=0o700, exist_ok=True)
  now = datetime.now(timezone.utc)
  state = {
    "version": 1,
    "permit_id": "a" * 32,
    "session_id": session,
    "issued_at": now.isoformat().replace("+00:00", "Z"),
    "expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
    "consumed": False,
    "agent_text": agent_text(tool_input),
    **overrides,
  }
  path = runtime / f"{session}.json"
  path.write_text(json.dumps(state, ensure_ascii=False))
  path.chmod(0o600)
  return path


def run_hook(value, runtime, home):
  env = {**os.environ, "HOME": str(home), "PR_REVIEW_C4_RUNTIME_DIR": str(runtime)}
  result = subprocess.run(
    [sys.executable, str(HOOK)],
    input=json.dumps(value, ensure_ascii=False),
    capture_output=True,
    text=True,
    check=False,
    env=env,
  )
  return result.returncode, json.loads(result.stdout or "{}")


def issue(envelope, runtime, home, session="session-c4-gate-001"):
  env = {
    **os.environ,
    "HOME": str(home),
    "PR_REVIEW_C4_RUNTIME_DIR": str(runtime),
    "CLAUDE_CODE_SESSION_ID": session,
  }
  result = subprocess.run(
    [sys.executable, str(C4_TESTS.MODULE_PATH), "dispatch-envelope"],
    input=json.dumps({"packet": envelope["runtime_input"]["packet"]}, ensure_ascii=False),
    capture_output=True,
    text=True,
    check=False,
    env=env,
  )
  return result.returncode, json.loads(result.stdout or "{}")


class C4DispatchGateTest(unittest.TestCase):
  def setUp(self):
    self.root = tempfile.TemporaryDirectory()
    self.home = Path(self.root.name, "home")
    self.home.mkdir()
    self.runtime = Path(self.root.name, "runtime")

  def tearDown(self):
    self.root.cleanup()

  def agent_input(self, envelope=None):
    value = ENVELOPE if envelope is None else envelope
    return dict(value["agent"])

  def issue(self, session="session-c4-gate-001"):
    code, envelope = issue(ENVELOPE, self.runtime, self.home, session=session)
    self.assertEqual(0, code)
    return envelope

  def test_allows_exact_envelope_agent_input(self):
    envelope = self.issue()
    code, result = run_hook(payload(self.agent_input(envelope)), self.runtime, self.home)
    self.assertEqual(0, code)
    self.assertEqual("allow", result["hookSpecificOutput"]["permissionDecision"])

  def test_denies_packet_mutation_after_envelope(self):
    value = self.agent_input(self.issue())
    value["prompt"] = value["prompt"].replace(
      '"connected_guard_binding_ids":[]',
      '"connected_guard_binding_ids":["C4-BIND-999"]',
      1,
    )
    code, result = run_hook(payload(value), self.runtime, self.home)
    self.assertEqual(0, code)
    self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])
    self.assertIn("altered after preparation", result["hookSpecificOutput"]["permissionDecisionReason"])

  def test_denies_extra_schema_instruction(self):
    value = self.agent_input(self.issue())
    value["prompt"] += "\nAdd observations key."
    _, result = run_hook(payload(value), self.runtime, self.home)
    self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])

  def test_denies_wrong_model_or_description(self):
    for index, (key, value) in enumerate((("model", "sonnet"), ("description", "C4 review with extra rules"))):
      with self.subTest(key=key):
        session = f"session-c4-gate-wrong-{index}"
        tool_input = self.agent_input(self.issue(session=session))
        tool_input[key] = value
        _, result = run_hook(payload(tool_input, session=session), self.runtime, self.home)
        self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])

  def test_denies_coherent_packet_reissue_without_original_permit(self):
    original = self.issue()
    changed = C4_TESTS.packet()
    changed["clauses"][0]["changed_flow_hint"]["precondition"] = "state=ATTACKER_SELECTED"
    env = {
      **os.environ,
      "HOME": str(self.home),
      "PR_REVIEW_C4_RUNTIME_DIR": str(self.runtime),
      "CLAUDE_CODE_SESSION_ID": "other-session-c4-gate-001",
    }
    result = subprocess.run(
      [sys.executable, str(C4_TESTS.MODULE_PATH), "dispatch-envelope"],
      input=json.dumps({"packet": changed}, ensure_ascii=False),
      capture_output=True,
      text=True,
      check=False,
      env=env,
    )
    self.assertEqual(0, result.returncode)
    changed_envelope = json.loads(result.stdout)
    _, denied = run_hook(payload(self.agent_input(changed_envelope)), self.runtime, self.home)
    self.assertEqual("deny", denied["hookSpecificOutput"]["permissionDecision"])
    _, allowed = run_hook(payload(self.agent_input(original)), self.runtime, self.home)
    self.assertEqual("allow", allowed["hookSpecificOutput"]["permissionDecision"])

  def test_consumes_permit_exactly_once(self):
    envelope = self.issue()
    _, first = run_hook(payload(self.agent_input(envelope)), self.runtime, self.home)
    _, second = run_hook(payload(self.agent_input(envelope), tool_use="tool-c4-gate-002"), self.runtime, self.home)
    self.assertEqual("allow", first["hookSpecificOutput"]["permissionDecision"])
    self.assertEqual("deny", second["hookSpecificOutput"]["permissionDecision"])

  def test_denies_extra_agent_control_fields(self):
    for index, (key, value) in enumerate((("resume", "attacker-agent"), ("run_in_background", True), ("isolation", "worktree"))):
      with self.subTest(key=key):
        session = f"session-c4-gate-extra-{index}"
        tool_input = self.agent_input(self.issue(session=session))
        tool_input[key] = value
        _, result = run_hook(payload(tool_input, session=session), self.runtime, self.home)
        self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])

  def test_denies_task_alias_for_agent_permit(self):
    envelope = self.issue()
    value = payload(self.agent_input(envelope))
    value["tool_name"] = "Task"
    _, result = run_hook(value, self.runtime, self.home)
    self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])

  def test_cannot_reissue_after_permit_file_deletion(self):
    envelope = self.issue()
    Path(self.runtime, "session-c4-gate-001.json").unlink()
    code, result = issue(ENVELOPE, self.runtime, self.home)
    self.assertEqual(1, code)
    self.assertEqual("FAILED", result["status"])
    self.assertEqual("C4_DISPATCH_PERMIT_EXISTS", result["reason_code"])
    _, denied = run_hook(payload(self.agent_input(envelope)), self.runtime, self.home)
    self.assertEqual("deny", denied["hookSpecificOutput"]["permissionDecision"])

  def test_allows_when_dispatched_text_equals_stored_text_and_consumes_once(self):
    session = "session-c4-gate-text-001"
    tool_input = self.agent_input()
    path = write_state(self.runtime, session, tool_input)
    _, first = run_hook(payload(tool_input, session=session), self.runtime, self.home)
    self.assertEqual("allow", first["hookSpecificOutput"]["permissionDecision"])
    self.assertTrue(json.loads(path.read_text())["consumed"])
    _, second = run_hook(payload(tool_input, session=session, tool_use="tool-c4-gate-text-002"), self.runtime, self.home)
    self.assertEqual("deny", second["hookSpecificOutput"]["permissionDecision"])

  def test_denies_any_single_byte_difference_as_altered_after_preparation(self):
    session = "session-c4-gate-bytes-001"
    prepared = self.agent_input()
    prompt = prepared["prompt"]
    variants = {
      "prompt first byte": {**prepared, "prompt": "X" + prompt[1:]},
      "prompt middle byte": {**prepared, "prompt": prompt[: len(prompt) // 2] + "~" + prompt[len(prompt) // 2 + 1 :]},
      "prompt last byte": {**prepared, "prompt": prompt[:-1] + "]"},
      "prompt trailing newline": {**prepared, "prompt": prompt + "\n"},
      "description": {**prepared, "description": prepared["description"] + "."},
      "model": {**prepared, "model": "opu5"},
    }
    for name, tool_input in variants.items():
      with self.subTest(name=name):
        self.assertNotEqual(prepared, tool_input)
        write_state(self.runtime, session, prepared)
        _, result = run_hook(payload(tool_input, session=session), self.runtime, self.home)
        self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])
        self.assertIn("altered after preparation", result["hookSpecificOutput"]["permissionDecisionReason"])

  def test_denied_alteration_does_not_consume_the_permit(self):
    session = "session-c4-gate-bytes-002"
    prepared = self.agent_input()
    path = write_state(self.runtime, session, prepared)
    run_hook(payload({**prepared, "prompt": prepared["prompt"] + " "}, session=session), self.runtime, self.home)
    self.assertFalse(json.loads(path.read_text())["consumed"])
    _, result = run_hook(payload(prepared, session=session), self.runtime, self.home)
    self.assertEqual("allow", result["hookSpecificOutput"]["permissionDecision"])

  def test_expired_or_consumed_permit_is_not_reported_as_alteration(self):
    prepared = self.agent_input()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    for name, overrides in (("expired", {"expires_at": past}), ("consumed", {"consumed": True})):
      with self.subTest(name=name):
        session = f"session-c4-gate-{name}-001"
        write_state(self.runtime, session, prepared, **overrides)
        _, result = run_hook(payload(prepared, session=session), self.runtime, self.home)
        self.assertEqual("deny", result["hookSpecificOutput"]["permissionDecision"])
        self.assertNotIn("altered after preparation", result["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn(name, result["hookSpecificOutput"]["permissionDecisionReason"])

  def test_issued_state_stores_prepared_text_and_no_digest_fields(self):
    envelope = self.issue()
    state = json.loads(Path(self.runtime, "session-c4-gate-001.json").read_text())
    self.assertEqual(agent_text(envelope["agent"]), state["agent_text"])
    self.assertEqual(["agent_text", "consumed", "expires_at", "issued_at", "permit_id", "session_id", "version"], sorted(state))
    self.assertEqual(["agent", "permit_id", "reason_code", "runtime_input", "status"], sorted(envelope))
    tombstone = Path(self.home, ".claude/logs/pr-review-c4-dispatch-issued/session-c4-gate-001.json")
    self.assertEqual(["session_id"], sorted(json.loads(tombstone.read_text())))

  def test_leaves_other_agents_unchanged(self):
    code, result = run_hook(payload({
      "description": "Review code",
      "prompt": "Review this diff",
      "subagent_type": "code-reviewer",
    }), self.runtime, self.home)
    self.assertEqual(0, code)
    self.assertEqual({}, result)


if __name__ == "__main__":
  unittest.main()
