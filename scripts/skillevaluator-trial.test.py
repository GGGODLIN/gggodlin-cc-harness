#!/usr/bin/env python3
import json
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import os
from pathlib import Path
import re
import runpy
import socket
import subprocess
from socketserver import BaseRequestHandler, ThreadingTCPServer
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from urllib.error import HTTPError
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name("skillevaluator-trial.py")
APPROVED_COMMIT = "4dcbe371f562a8ac4bca63fce81370228a7579c7"
MAX_JSON_BYTES = 16 * 1024 * 1024


class EmbeddingHandler(BaseHTTPRequestHandler):
  def do_POST(self):
    if self.path != "/v1/embeddings":
      self.send_error(404)
      return
    length = int(self.headers.get("Content-Length", "0"))
    request_data = json.loads(self.rfile.read(length))
    self.server.record_request(request_data)
    response_data = self.server.response_data if self.server.response_data is not None else {"data": [{"index": 0, "embedding": self.server.vector}]}
    body = self.server.response_body if self.server.response_body is not None else json.dumps(response_data).encode()
    content_length = self.server.response_content_length if self.server.response_content_length is not None else len(body)
    self.send_response(200)
    self.send_header("Content-Type", "application/json")
    if not self.server.omit_content_length:
      self.send_header("Content-Length", str(content_length))
    self.end_headers()
    try:
      self.wfile.write(body)
    except OSError:
      pass

  def log_message(self, format_string, *args):
    return


class EmbeddingServer(ThreadingHTTPServer):
  daemon_threads = True

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.vector = [0.25, -0.5]
    self.response_data = None
    self.response_body = None
    self.response_content_length = None
    self.omit_content_length = False
    self.request_count = 0
    self.request_payloads = []
    self.request_lock = threading.Lock()

  def record_request(self, request_data):
    with self.request_lock:
      self.request_count += 1
      self.request_payloads.append(request_data)

  def reset_request_count(self):
    with self.request_lock:
      self.request_count = 0
      self.request_payloads = []


class MalformedHTTPHandler(BaseRequestHandler):
  def handle(self):
    self.request.recv(4096)
    self.request.sendall(b"NOTHTTP\\r\\n")


class MalformedHTTPServer(ThreadingTCPServer):
  allow_reuse_address = True


class SkillEvaluatorTrialTest(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.root = Path(self.temp.name)
    self.policy = self.root / "internal-policy.yaml"
    self.policy.write_text("profile: internal-local\nseverity_overrides:\n  SCHEMA.author_missing: low\n  PII.personal_paths: low\n  PII.emails: low\n")
    self.skill = self.root / "skills" / "fixture"
    self.skill.mkdir(parents=True)
    (self.skill / "SKILL.md").write_text("---\nname: fixture\ndescription: Fixture skill.\n---\n\n# Fixture\n")
    (self.skill / "evals").mkdir()
    (self.skill / "evals" / "evals.json").write_text(json.dumps([{"id": "fixture-001", "question": "Run fixture."}]))
    self.embedding_server = EmbeddingServer(("127.0.0.1", 0), EmbeddingHandler)
    self.embedding_thread = threading.Thread(target=self.embedding_server.serve_forever, daemon=True)
    self.embedding_thread.start()
    embedding_base = f"http://127.0.0.1:{self.embedding_server.server_address[1]}/v1"
    self.keys = self.root / "keys.env"
    self.secret = "fixture-secret-value"
    self.keys.write_text(
      f"CLIPROXY_BASE_URL=http://127.0.0.1:8317\n"
      f"CLIPROXY_KEY_ADMIN={self.secret}\n"
      f"SKILL_EVAL_EMBEDDING_BASE_URL={embedding_base}\n"
      "SKILL_EVAL_EMBEDDING_MODEL=nomic-embed-text\n"
    )
    self.keys.chmod(0o600)
    self.tool = self.root / "tool"
    self.fake = self.tool / "bin" / "skillevaluator"
    self.fake.parent.mkdir(parents=True)
    self.metadata = self.tool / "lib" / "python3.13" / "site-packages" / "skillevaluator-0.3.0.dist-info" / "direct_url.json"
    self.metadata.parent.mkdir(parents=True)
    self.metadata.write_text(json.dumps({
      "url": "https://github.com/NVIDIA/SkillEvaluator.git",
      "vcs_info": {
        "vcs": "git",
        "commit_id": APPROVED_COMMIT,
        "requested_revision": APPROVED_COMMIT,
      },
    }))
    self.fake.write_text("""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import time

args = sys.argv[1:]
if args == ["--version"]:
  side_effect_path = os.environ.get("SKILLEVALUATOR_TEST_VERSION_SIDE_EFFECT")
  if side_effect_path:
    Path(side_effect_path).write_text("version invoked")
  print("skillevaluator, version " + os.environ.get("SKILLEVALUATOR_TEST_VERSION", "0.3.0"))
  raise SystemExit(0)
command = args[0]
if args[:2] == ["tier3", "evaluate"]:
  target_path = Path(args[2])
  results = Path(args[args.index("--results-dir") + 1])
  status = os.environ.get("SKILLEVALUATOR_TEST_TIER3", "pass")
  if status == "sleep":
    time.sleep(10)
  if status == "spawn-child":
    subprocess.Popen([sys.executable, "-c", "import os,time; from pathlib import Path; time.sleep(0.5); Path(os.environ['SKILLEVALUATOR_TEST_LATE_PATH']).write_text(os.environ.get('OPENAI_API_KEY',''))"])
    time.sleep(10)
  if status in {"pass", "complete-nonzero", "zero-attempt", "incomplete-secret", "boolean-attempt"}:
    run = results / target_path.name / "run-fixture"
    (run / "codex" / "with-skill").mkdir(parents=True)
    (run / "codex" / "without-skill").mkdir(parents=True)
    expected = 0 if status == "zero-attempt" else 2
    scored = 0 if status in {"zero-attempt", "incomplete-secret"} else 2
    execution = "failed" if status == "incomplete-secret" else "succeeded"
    result_packet = {
      "execution_status": execution,
      "report_status": "complete",
      "expected_attempts": expected,
      "scored_attempts": scored,
      "agents": {"codex": {"conditions": {
        "with_skill": {"execution_status": execution, "expected_attempts": expected // 2, "scored_attempts": scored // 2},
        "without_skill": {"execution_status": execution, "expected_attempts": expected // 2, "scored_attempts": scored // 2},
      }}},
    }
    if status == "incomplete-secret":
      result_packet["leaked"] = os.environ.get("OPENAI_API_KEY")
    if status == "boolean-attempt":
      result_packet["expected_attempts"] = 1
      result_packet["scored_attempts"] = True
      for condition in result_packet["agents"]["codex"]["conditions"].values():
        condition["expected_attempts"] = 1
        condition["scored_attempts"] = True
    (run / "result.json").write_text(json.dumps(result_packet))
    (run / "report.html").write_text("<html>fixture</html>")
    summary = {"execution_status": execution, "expected_attempts": 1, "scored_attempts": True} if status == "boolean-attempt" else {"execution_status": execution, "expected_attempts": expected // 2, "scored_attempts": scored // 2}
    (run / "codex" / "with-skill" / "summary.json").write_text(json.dumps(summary))
    (run / "codex" / "without-skill" / "summary.json").write_text(json.dumps(summary))
    if status in {"pass", "complete-nonzero"}:
      for arm in ("with-skill", "without-skill"):
        trial = run / "codex" / arm / "trials" / f"case-{arm}"
        trial.mkdir(parents=True)
        (trial / "result.json").write_text("{}")
  log = Path(os.environ["SKILLEVALUATOR_TEST_LOG"])
  with log.open("a") as handle:
    handle.write(json.dumps({"args": args, "has_openai_key": bool(os.environ.get("OPENAI_API_KEY"))}) + "\\n")
  raise SystemExit(0 if status == "pass" else 1)
output = Path(args[args.index("-o") + 1])
output.mkdir(parents=True, exist_ok=True)
target_path = Path(args[1])
target = target_path.name
if command == "validate" and os.environ.get("SKILLEVALUATOR_TEST_MUTATE_SKILL") == "1":
  skill_file = target_path / "SKILL.md"
  skill_file.write_text(skill_file.read_text() + "\\nmutated during run\\n")
if command == "validate":
  status = "fail" if target == "tier1-fail" else os.environ.get("SKILLEVALUATOR_TEST_T1", "pass")
elif command == "similarity-check":
  status = os.environ.get("SKILLEVALUATOR_TEST_INTER", "pass")
else:
  status = "finding" if target == "intra-duplicate" else "structured-provider" if target == "provider-fail" else os.environ.get("SKILLEVALUATOR_TEST_T2", "pass")
if status == "sleep":
  time.sleep(10)
if status == "oversized":
  (output / "skillevaluator-output-fixture.json").write_bytes(b"x" * (16 * 1024 * 1024 + 1))
elif status != "infra":
  passed = status in {"pass", "pass-nonzero", "minimal-pass", "zero-check-pass", "pass-with-errors", "legacy-provider", "legacy-rate-limit"}
  if status == "structured-provider":
    findings = [{"category": "CONTENT_DEDUP", "check_name": "embedding_error"}]
  elif status in {"pass", "pass-nonzero", "minimal-pass", "report-infra", "legacy-provider", "legacy-rate-limit", "zero-check-pass", "pass-with-errors", "failed-no-findings"}:
    findings = []
  else:
    findings = [{"category": "DUPLICATE"}]
  report = {
    "overall_passed": passed,
    "overall_status": "passed" if passed else "failed",
    "incomplete_scans": [],
    "results": [{
      "findings": findings,
      "summary": {
        "checks_performed": 0 if status in {"report-infra", "zero-check-pass"} else 1,
        "errors": 1 if status in {"report-infra", "structured-provider", "pass-with-errors", "fail-with-error-count"} else 0,
      },
      "legacy": {"errors": [
        "Context Deduplication failed: Error code: 429 - {'error': {'type': 'usage_limit_reached'}}"
        if status == "legacy-rate-limit"
        else "Context Deduplication failed: provider unavailable"
      ] if status in {"report-infra", "legacy-provider", "legacy-rate-limit"} else []},
    }],
  }
  if status == "leak":
    report["leaked"] = os.environ.get("SKILL_EVAL_LLM_API_KEY")
  ambient_name = os.environ.get("SKILLEVALUATOR_TEST_ECHO_AMBIENT")
  if ambient_name:
    report["ambient"] = os.environ.get(ambient_name)
  if status == "minimal-pass":
    report = {"overall_passed": True}
  (output / "skillevaluator-output-fixture.json").write_text(json.dumps(report))
if status == "leak":
  print(os.environ.get("SKILL_EVAL_LLM_API_KEY"))
  print(os.environ.get("SKILL_EVAL_LLM_API_KEY"), file=sys.stderr)
log = Path(os.environ["SKILLEVALUATOR_TEST_LOG"])
with log.open("a") as handle:
  handle.write(json.dumps({
    "args": args,
    "has_llm_key": bool(os.environ.get("SKILL_EVAL_LLM_API_KEY")),
    "has_embedding_key": bool(os.environ.get("SKILL_EVAL_EMBEDDING_API_KEY")),
  }) + "\\n")
raise SystemExit(0 if status in {"pass", "legacy-provider", "legacy-rate-limit", "zero-check-pass", "pass-with-errors"} else 1)
""")
    self.fake.chmod(0o755)
    self.state = self.root / "state"
    self.artifacts = self.root / "artifacts"
    self.log = self.root / "fake-log.jsonl"
    self.env = {
      **os.environ,
      "SKILLEVALUATOR_BIN": str(self.fake),
      "SKILLEVALUATOR_KEYS_FILE": str(self.keys),
      "SKILLEVALUATOR_INTERNAL_POLICY": str(self.policy),
      "SKILLEVALUATOR_TRIAL_STATE_ROOT": str(self.state),
      "SKILLEVALUATOR_TRIAL_ARTIFACT_ROOT": str(self.artifacts),
      "SKILLEVALUATOR_TEST_LOG": str(self.log),
    }

  def tearDown(self):
    self.embedding_server.shutdown()
    self.embedding_server.server_close()
    self.embedding_thread.join(timeout=1)
    self.temp.cleanup()

  def create_skill(self, collection, name):
    skill = collection / name
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Fixture {name}.\n---\n")
    return skill

  def run_cli(self, *args, env=None, stdin=None):
    return subprocess.run(
      [sys.executable, str(SCRIPT), *args],
      capture_output=True,
      text=True,
      env={**self.env, **(env or {})},
      input=stdin,
      check=False,
      timeout=5,
    )

  def run_hook(self, payload):
    return self.run_cli(
      "hook",
      stdin=json.dumps(payload),
      env={"SKILLEVALUATOR_TRIAL_FALLBACK_ROOT": str(self.root / "fallback")},
    )

  def open_pending_edit(self, session):
    skill_file = self.skill / "SKILL.md"
    result = self.run_hook({
      "hook_event_name": "PostToolUse",
      "session_id": session,
      "tool_name": "Edit",
      "tool_input": {"file_path": str(skill_file)},
    })
    self.assertEqual(result.returncode, 0, result.stderr)
    pending = list((self.state / "pending").glob("*/*.json"))
    self.assertEqual(len(pending), 1)
    return json.loads(pending[0].read_text())["edit_epoch_ns"]

  def stop_decision(self, session):
    result = self.run_hook({"hook_event_name": "Stop", "session_id": session})
    self.assertEqual(result.returncode, 0, result.stderr)
    return json.loads(result.stdout) if result.stdout.strip() else {}

  def run_pending_skill(self, session, edit_epoch_ns, env=None):
    return self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      "--session",
      session,
      env=env,
    )

  def test_stop_gate_accepts_fresh_receipt(self):
    edit_epoch_ns = self.open_pending_edit("session-stop")
    self.assertEqual(self.stop_decision("session-stop")["decision"], "block")
    result = self.run_pending_skill("session-stop", edit_epoch_ns)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.stop_decision("session-stop"), {})

  def test_stop_gate_invalidates_receipt_when_skill_changed_after_run(self):
    edit_epoch_ns = self.open_pending_edit("session-stale")
    self.assertEqual(self.run_pending_skill("session-stale", edit_epoch_ns).returncode, 0)
    skill_file = self.skill / "SKILL.md"
    skill_file.write_text(skill_file.read_text() + "\nedited after the run\n")
    decision = self.stop_decision("session-stale")
    self.assertEqual(decision["decision"], "block")
    self.assertIn("stale receipt", decision["reason"])

  def test_human_permit_binds_by_identity_without_digest(self):
    session = "session-permit"
    edit_epoch_ns = self.open_pending_edit(session)
    receipt = json.loads(self.run_pending_skill(session, edit_epoch_ns, env={"SKILLEVALUATOR_TEST_T1": "fail"}).stdout)
    self.assertEqual(receipt["status"], "tier1_failed")
    waiting = self.stop_decision(session)
    approval_id = re.search(r"SkillEvaluator 放行 ([0-9a-f]{24})", waiting["systemMessage"]).group(1)
    issued = self.run_hook({
      "hook_event_name": "UserPromptSubmit",
      "session_id": session,
      "prompt": f"SkillEvaluator 放行 {approval_id}",
    })
    self.assertEqual(issued.returncode, 0, issued.stderr)
    permits = list((self.state / "permits").glob(f"*/{approval_id}.json"))
    self.assertEqual(len(permits), 1)
    permit = json.loads(permits[0].read_text())
    self.assertEqual(sorted(permit), ["approval_id", "consumed", "edit_epoch_ns", "expires_at", "issued_at", "kind", "receipt_path", "schema_version", "session", "skill_path", "tier1_artifact_path"])
    self.assertEqual(permit["session"], session)
    self.assertEqual(permit["skill_path"], str(self.skill.resolve()))
    self.assertEqual(permit["edit_epoch_ns"], edit_epoch_ns)
    self.assertEqual(permit["receipt_path"], receipt["receipt_path"])
    self.assertEqual(permit["tier1_artifact_path"], receipt["tier1"]["artifact_path"])
    self.assertEqual(self.stop_decision(session).get("decision"), None)
    spent = list((self.state / "spent-permits").glob(f"*/{approval_id}.json"))
    self.assertEqual(len(spent), 1)

  def test_run_skill_pass_writes_bound_secret_free_receipt(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      "--session",
      "session-1",
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["status"], "passed")
    self.assertEqual(receipt["skill_path"], str(self.skill.resolve()))
    self.assertEqual(receipt["edit_epoch_ns"], edit_epoch_ns)
    self.assertEqual(receipt["tool_version"], "0.3.0")
    self.assertEqual(receipt["tier1"]["status"], "passed")
    self.assertEqual(receipt["tier2"]["status"], "passed")
    self.assertTrue(Path(receipt["receipt_path"]).is_file())
    self.assertTrue(Path(receipt["tier1"]["artifact_path"]).is_file())
    self.assertTrue(Path(receipt["tier2"]["artifact_path"]).is_file())
    self.assertEqual(sorted(receipt), ["edit_epoch_ns", "kind", "latency_ms", "reason", "receipt_path", "run_ended_at", "run_ended_ns", "run_started_at", "run_started_ns", "schema_version", "session", "skill_path", "status", "tier1", "tier2", "tool_version"])
    combined = "\n".join(path.read_text(errors="replace") for path in [*self.state.rglob("*"), *self.artifacts.rglob("*")] if path.is_file())
    self.assertNotIn(self.secret, combined)
    calls = [json.loads(line) for line in self.log.read_text().splitlines()]
    self.assertEqual([call["args"][0] for call in calls], ["validate", "context-optimization-check"])
    self.assertEqual(calls[0]["args"][calls[0]["args"].index("--profile") + 1], "external")
    self.assertEqual(calls[0]["args"][calls[0]["args"].index("--policy") + 1], str(self.policy.resolve()))
    self.assertFalse(calls[0]["has_llm_key"] or calls[0]["has_embedding_key"])
    self.assertTrue(calls[1]["has_llm_key"] and calls[1]["has_embedding_key"])

  def test_receipts_are_isolated_by_session_and_edit(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    first = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      "--session",
      "session-a",
    )
    second = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns + 1),
      "--session",
      "session-b",
    )
    self.assertEqual(first.returncode, 0, first.stderr)
    self.assertEqual(second.returncode, 0, second.stderr)
    first_receipt = json.loads(first.stdout)
    second_receipt = json.loads(second.stdout)
    self.assertNotEqual(first_receipt["receipt_path"], second_receipt["receipt_path"])
    self.assertTrue(Path(first_receipt["receipt_path"]).is_file())
    self.assertTrue(Path(second_receipt["receipt_path"]).is_file())

  def test_runner_rejects_version_prefix_collision(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_VERSION": "0.2.10"},
    )
    self.assertEqual(result.returncode, 3)
    self.assertEqual(json.loads(result.stdout)["status"], "infrastructure_failure")

  def test_runner_rejects_unapproved_git_commit_before_version_side_effect(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    rejected_commit = ("0" if APPROVED_COMMIT[0] != "0" else "1") + APPROVED_COMMIT[1:]
    self.metadata.write_text(json.dumps({
      "url": "https://github.com/NVIDIA/SkillEvaluator.git",
      "vcs_info": {
        "vcs": "git",
        "commit_id": rejected_commit,
        "requested_revision": rejected_commit,
      },
    }))
    side_effect = self.root / "version-side-effect"
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_VERSION_SIDE_EFFECT": str(side_effect)},
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["status"], "infrastructure_failure")
    self.assertIn("Git commit", receipt["tier1"]["reason"])
    self.assertFalse(side_effect.exists())
    self.assertFalse(self.log.exists())

  def test_runner_revalidates_provenance_before_each_evaluator_execution(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_VERSION_SIDE_EFFECT": str(self.metadata)},
    )
    self.assertEqual(result.returncode, 3)
    self.assertNotIn("Traceback", result.stderr)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["status"], "infrastructure_failure")
    self.assertIn("metadata", receipt["tier1"]["reason"])
    self.assertFalse(self.log.exists())

  def test_weekly_provenance_failure_writes_structured_packet_and_summary(self):
    rejected_commit = ("0" if APPROVED_COMMIT[0] != "0" else "1") + APPROVED_COMMIT[1:]
    self.metadata.write_text(json.dumps({
      "url": "https://github.com/NVIDIA/SkillEvaluator.git",
      "vcs_info": {
        "vcs": "git",
        "commit_id": rejected_commit,
        "requested_revision": rejected_commit,
      },
    }))
    collection = self.root / "weekly-provenance-failure"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-provenance-failure.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
    )
    self.assertEqual(result.returncode, 3)
    self.assertNotIn("Traceback", result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertIn("Git commit", packet["reason"])
    self.assertEqual(packet["tier1"], {"passed": 0, "failed": 0, "infrastructure_failure": 0})
    self.assertEqual(packet["tier2_preflight"]["status"], "infrastructure_failure")
    self.assertEqual(packet["tier2_preflight"]["attempts"], 0)
    self.assertEqual(packet["provider_failures"], [])
    self.assertEqual(packet["non_provider_failures"][0]["scope"], "provenance")
    self.assertIn("Git commit", packet["non_provider_failures"][0]["reason"])
    self.assertTrue(Path(packet["result_path"]).is_file())
    self.assertTrue(summary.is_file())
    self.assertIn("infrastructure_failure", summary.read_text())
    self.assertIn("Git commit", summary.read_text())
    self.assertFalse(self.log.exists())

  def test_weekly_missing_binary_preserves_actual_failure_scope_and_reason(self):
    collection = self.root / "weekly-missing-binary"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-missing-binary.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      env={"SKILLEVALUATOR_BIN": str(self.root / "missing-skillevaluator")},
    )
    self.assertEqual(result.returncode, 3)
    self.assertNotIn("Traceback", result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "skillevaluator binary is unavailable")
    self.assertEqual(packet["provider_failures"], [])
    self.assertEqual(packet["non_provider_failures"][0]["scope"], "evaluator")
    self.assertEqual(packet["non_provider_failures"][0]["reason"], "skillevaluator binary is unavailable")
    self.assertNotIn("weekly_provider_failure", json.dumps(packet))
    self.assertNotIn("provenance", json.dumps(packet))
    summary_text = summary.read_text()
    self.assertIn("skillevaluator binary is unavailable", summary_text)
    self.assertNotIn("provenance", summary_text)

  def test_run_skill_propagates_configured_models(self):
    self.keys.write_text(
      f"CLIPROXY_BASE_URL=http://127.0.0.1:8317\n"
      f"CLIPROXY_KEY_ADMIN={self.secret}\n"
      "SKILL_EVAL_EMBEDDING_MODEL=fixture-embedding-model\n"
      "SKILL_EVAL_LLM_MODEL=fixture-chat-model\n"
    )
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    calls = [json.loads(line) for line in self.log.read_text().splitlines()]
    tier2 = next(call for call in calls if call["args"][0] == "context-optimization-check")
    args = tier2["args"]
    self.assertEqual(args[args.index("--model") + 1], "fixture-embedding-model")
    self.assertEqual(args[args.index("--llm-model") + 1], "fixture-chat-model")

  def test_production_internal_policy_does_not_lower_external_severity(self):
    policy = SCRIPT.with_name("skillevaluator-internal-policy.yaml").read_text()
    self.assertNotIn("PII.emails", policy)

  def test_internal_policy_pathologies_fail_closed_before_tier1(self):
    missing = self.root / "missing-policy.yaml"
    symlink = self.root / "policy-symlink.yaml"
    symlink.symlink_to(self.policy)
    hardlink_source = self.root / "policy-hardlink-source.yaml"
    hardlink_source.write_text(self.policy.read_text())
    hardlink = self.root / "policy-hardlink.yaml"
    os.link(hardlink_source, hardlink)
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    for label, path in (("missing", missing), ("symlink", symlink), ("hardlink", hardlink)):
      with self.subTest(label=label):
        if self.log.exists():
          self.log.unlink()
        result = self.run_cli(
          "run-skill",
          "--skill",
          str(self.skill),
          "--edit-epoch-ns",
          str(edit_epoch_ns),
          env={"SKILLEVALUATOR_INTERNAL_POLICY": str(path)},
        )
        self.assertEqual(result.returncode, 3)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "infrastructure_failure")
        self.assertIn("internal policy", receipt["tier1"]["reason"])
        self.assertFalse(self.log.exists())

  def test_tier1_failure_is_blocking_and_distinct(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T1": "fail"},
    )
    self.assertEqual(result.returncode, 2)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["status"], "tier1_failed")
    self.assertEqual(receipt["tier1"]["status"], "failed")
    self.assertEqual(receipt["tier2"]["status"], "passed")

  def test_tier1_finding_count_is_not_mislabeled_as_infrastructure_error(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T1": "fail-with-error-count"},
    )
    self.assertEqual(result.returncode, 2)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["status"], "tier1_failed")
    self.assertEqual(receipt["tier1"]["status"], "failed")

  def test_tier2_finding_is_advisory(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T2": "finding"},
    )
    self.assertEqual(result.returncode, 0)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["status"], "passed")
    self.assertEqual(receipt["tier2"]["status"], "findings")
    self.assertEqual(receipt["tier2"]["finding_count"], 1)

  def test_missing_provider_still_runs_deterministic_tier1(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_KEYS_FILE": str(self.root / "missing-keys.env")},
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["tier1"]["status"], "passed")
    self.assertEqual(receipt["tier2"]["status"], "infrastructure_failure")
    calls = [json.loads(line) for line in self.log.read_text().splitlines()]
    self.assertEqual([call["args"][0] for call in calls], ["validate"])

  def test_private_keys_store_rejects_symlink_and_fifo(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    symlink = self.root / "keys-symlink.env"
    symlink.symlink_to(self.keys)
    symlink_result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_KEYS_FILE": str(symlink)},
    )
    self.assertEqual(symlink_result.returncode, 3)
    fifo = self.root / "keys-fifo.env"
    os.mkfifo(fifo)
    fifo_result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_KEYS_FILE": str(fifo)},
    )
    self.assertEqual(fifo_result.returncode, 3)

  def test_private_keys_store_rejects_insecure_permissions(self):
    self.keys.chmod(0o644)
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["tier2"]["status"], "infrastructure_failure")

  def test_provider_failure_does_not_create_success_receipt(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T2": "infra"},
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["status"], "infrastructure_failure")
    self.assertEqual(receipt["tier2"]["status"], "infrastructure_failure")

  def test_passed_report_with_nonzero_exit_fails_closed(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T1": "pass-nonzero"},
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["tier1"]["status"], "infrastructure_failure")

  def test_minimal_pass_report_does_not_create_success_receipt(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T2": "minimal-pass"},
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["tier2"]["status"], "infrastructure_failure")

  def test_zero_check_tier1_report_is_infrastructure_failure(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T1": "zero-check-pass"},
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["tier1"]["status"], "infrastructure_failure")

  def test_structured_tier2_provider_finding_is_infrastructure_failure(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T2": "structured-provider"},
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["tier2"]["status"], "infrastructure_failure")
    self.assertEqual(receipt["tier2"]["failure_kind"], "provider")

  def test_evaluator_timeout_returns_structured_infrastructure_receipt(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={
        "SKILLEVALUATOR_TEST_T1": "sleep",
        "SKILLEVALUATOR_COMMAND_TIMEOUT_SECONDS": "0.1",
      },
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["tier1"]["status"], "infrastructure_failure")
    self.assertIn("timeout", receipt["tier1"]["reason"])

  def test_oversized_evaluator_json_returns_structured_infrastructure_receipt(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T1": "oversized"},
    )
    self.assertEqual(result.returncode, 3)
    self.assertNotIn("Traceback", result.stderr)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["status"], "infrastructure_failure")
    self.assertEqual(receipt["tier1"]["status"], "infrastructure_failure")
    self.assertEqual(receipt["tier1"]["reason"], "tier1_report_invalid")

  def test_non_finite_timeout_returns_structured_failure(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_COMMAND_TIMEOUT_SECONDS": "nan"},
    )
    self.assertEqual(result.returncode, 3)
    self.assertEqual(json.loads(result.stdout)["status"], "infrastructure_failure")

  def test_provider_error_report_is_not_mislabeled_as_advisory_finding(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T2": "report-infra"},
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["tier2"]["status"], "infrastructure_failure")

  def test_passed_report_with_execution_errors_fails_closed(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T1": "pass-with-errors"},
    )
    self.assertEqual(result.returncode, 3)
    self.assertEqual(json.loads(result.stdout)["tier1"]["status"], "infrastructure_failure")

  def test_failed_report_without_findings_fails_closed(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T2": "failed-no-findings"},
    )
    self.assertEqual(result.returncode, 3)
    self.assertEqual(json.loads(result.stdout)["tier2"]["status"], "infrastructure_failure")

  def test_stale_edit_timestamp_fails_closed_before_execution(self):
    edit_epoch_ns = (self.skill / "SKILL.md").stat().st_mtime_ns - 1
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["status"], "infrastructure_failure")
    self.assertEqual(receipt["tier1"]["reason"], "stale_edit_timestamp")
    self.assertFalse(self.log.exists())

  def test_skill_changed_during_run_invalidates_receipt(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_MUTATE_SKILL": "1"},
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["status"], "infrastructure_failure")
    self.assertEqual(receipt["reason"], "skill_changed_during_run")

  def test_secret_in_native_artifact_is_removed_and_fails_closed(self):
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={"SKILLEVALUATOR_TEST_T2": "leak"},
    )
    self.assertEqual(result.returncode, 3)
    receipt = json.loads(result.stdout)
    self.assertEqual(receipt["tier2"]["reason"], "secret_detected_in_artifacts")
    combined = "\n".join(path.read_text(errors="replace") for path in [*self.state.rglob("*"), *self.artifacts.rglob("*")] if path.is_file())
    self.assertNotIn(self.secret, combined)
    self.assertNotIn(self.secret, result.stdout)
    self.assertNotIn(self.secret, result.stderr)

  def test_subprocess_does_not_inherit_unapproved_ambient_credentials(self):
    ambient_secret = "ambient-credential-sentinel"
    edit_epoch_ns = max(time.time_ns(), (self.skill / "SKILL.md").stat().st_mtime_ns)
    result = self.run_cli(
      "run-skill",
      "--skill",
      str(self.skill),
      "--edit-epoch-ns",
      str(edit_epoch_ns),
      env={
        "ANTHROPIC_AUTH_TOKEN": ambient_secret,
        "SKILLEVALUATOR_TEST_ECHO_AMBIENT": "ANTHROPIC_AUTH_TOKEN",
      },
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    receipt = json.loads(result.stdout)
    combined = "\n".join(path.read_text(errors="replace") for path in self.artifacts.rglob("*") if path.is_file())
    self.assertNotIn(ambient_secret, combined)
    self.assertTrue(Path(receipt["tier1"]["artifact_path"]).is_file())

  def test_weekly_collection_returns_stateless_structured_advisory_result(self):
    collection = self.root / "weekly-skills"
    collection.mkdir()
    self.create_skill(collection, "unique")
    self.create_skill(collection, "intra-duplicate")
    self.create_skill(collection, "tier1-fail")
    self.create_skill(collection, "provider-fail")
    linked_target = self.create_skill(self.root, "linked-target")
    (collection / "linked-alias").symlink_to(linked_target, target_is_directory=True)
    summary = self.root / "weekly-summary.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      "--workers",
      "2",
      env={"SKILLEVALUATOR_TEST_INTER": "finding"},
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["kind"], "weekly")
    self.assertEqual(packet["skill_count"], 5)
    self.assertEqual(packet["tier1"], {"passed": 4, "failed": 1, "infrastructure_failure": 0})
    self.assertEqual(packet["tier2_intra"]["passed"], 3)
    self.assertEqual(packet["tier2_intra"]["findings"], 1)
    self.assertEqual(packet["tier2_intra"]["infrastructure_failure"], 1)
    self.assertEqual(packet["tier2_inter"]["status"], "findings")
    self.assertEqual(len(packet["skills"]), 5)
    self.assertIn("linked-alias", [item["skill_name"] for item in packet["skills"]])
    self.assertEqual(len(packet["provider_failures"]), 1)
    self.assertTrue(summary.is_file())
    self.assertIn("stateless", summary.read_text())
    self.assertTrue(Path(packet["result_path"]).is_file())
    self.assertTrue(all(item["tier1"]["artifact_path"] for item in packet["skills"]))
    self.assertTrue(all(item["tier2_intra"]["artifact_path"] for item in packet["skills"] if item["skill_name"] != "provider-fail"))
    calls = [json.loads(line) for line in self.log.read_text().splitlines()]
    tier1_calls = [call for call in calls if call["args"][0] == "validate"]
    self.assertEqual(len(tier1_calls), 5)
    self.assertTrue(all(call["args"][call["args"].index("--profile") + 1] == "external" for call in tier1_calls))
    self.assertTrue(all(call["args"][call["args"].index("--policy") + 1] == str(self.policy.resolve()) for call in tier1_calls))
    similarity = next(call for call in calls if call["args"][0] == "similarity-check")
    self.assertNotEqual(Path(similarity["args"][1]), collection)
    self.assertEqual(Path(similarity["args"][1]).name, "canonical-collection")
    self.assertNotIn("previous", json.dumps(packet))

  def test_weekly_rejects_non_date_artifact_segment(self):
    collection = self.root / "weekly-date"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-date.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "../../escaped",
      "--summary",
      str(summary),
    )
    self.assertEqual(result.returncode, 2)
    self.assertFalse((self.root / "escaped").exists())

  def test_weekly_provider_outage_keeps_tier1_and_records_tier2_failures(self):
    collection = self.root / "weekly-outage"
    collection.mkdir()
    self.create_skill(collection, "one")
    self.create_skill(collection, "two")
    summary = self.root / "weekly-outage.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      env={"SKILLEVALUATOR_KEYS_FILE": str(self.root / "missing-keys.env")},
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["tier1"], {"passed": 2, "failed": 0, "infrastructure_failure": 0})
    self.assertEqual(packet["tier2_intra"]["infrastructure_failure"], 2)
    self.assertEqual(packet["tier2_inter"]["status"], "infrastructure_failure")
    self.assertEqual(len(packet["provider_failures"]), 3)
    self.assertEqual(packet["non_provider_failures"], [])
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertIn("missing-keys.env", packet["reason"])
    summary_text = summary.read_text()
    self.assertNotIn("Status：completed", summary_text)
    self.assertNotIn("Reason：none", summary_text)
    self.assertIn("infrastructure_failure", summary_text)
    self.assertIn("missing-keys.env", summary_text)

  def test_weekly_content_dedup_provider_failure_is_provider_failure(self):
    collection = self.root / "weekly-content-dedup-provider-failure"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-content-dedup-provider-failure.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      env={"SKILLEVALUATOR_TEST_T2": "structured-provider"},
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "weekly_provider_failure")
    self.assertEqual(packet["tier2_preflight"]["status"], "passed")
    self.assertEqual(packet["tier2_intra"]["infrastructure_failure"], 1)
    self.assertEqual(packet["tier2_inter"]["status"], "passed")
    self.assertEqual(packet["non_provider_failures"], [])
    self.assertEqual(packet["provider_failures"][0]["scope"], "tier2-intra")
    self.assertEqual(packet["provider_failures"][0]["reason"], "tier2_execution_or_report_incomplete")
    self.assertEqual(packet["skills"][0]["tier2_intra"]["failure_kind"], "provider")
    summary_text = summary.read_text()
    self.assertNotIn("Status：completed", summary_text)
    self.assertNotIn("Reason：none", summary_text)
    self.assertIn("weekly_provider_failure", summary_text)
    self.assertIn("tier2_execution_or_report_incomplete", summary_text)

  def test_weekly_legacy_provider_error_is_provider_failure(self):
    collection = self.root / "weekly-legacy-provider-failure"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-legacy-provider-failure.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      env={"SKILLEVALUATOR_TEST_T2": "legacy-provider"},
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "weekly_provider_failure")
    self.assertEqual(packet["skills"][0]["tier2_intra"]["failure_kind"], "provider")
    self.assertEqual(packet["provider_failures"][0]["scope"], "tier2-intra")
    self.assertEqual(packet["provider_failures"][0]["reason"], "tier2_execution_or_report_incomplete")
    self.assertEqual(packet["non_provider_failures"], [])
    self.assertIn("tier2_execution_or_report_incomplete", summary.read_text())

  def test_weekly_legacy_rate_limit_is_provider_failure(self):
    collection = self.root / "weekly-legacy-rate-limit"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-legacy-rate-limit.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      env={"SKILLEVALUATOR_TEST_T2": "legacy-rate-limit"},
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "weekly_provider_failure")
    self.assertEqual(packet["skills"][0]["tier2_intra"]["failure_kind"], "provider")
    self.assertEqual(packet["provider_failures"][0]["scope"], "tier2-intra")
    self.assertEqual(packet["non_provider_failures"], [])

  def test_weekly_tier1_missing_report_is_non_provider_failure(self):
    collection = self.root / "weekly-tier1-missing-report"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-tier1-missing-report.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      env={"SKILLEVALUATOR_TEST_T1": "infra"},
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "tier1_report_missing_or_ambiguous")
    self.assertEqual(packet["provider_failures"], [])
    self.assertEqual(packet["non_provider_failures"][0]["scope"], "tier1")
    self.assertEqual(packet["non_provider_failures"][0]["reason"], "tier1_report_missing_or_ambiguous")
    self.assertEqual(packet["skills"][0]["tier1"]["failure_kind"], "non_provider")
    summary_text = summary.read_text()
    self.assertIn("tier1_report_missing_or_ambiguous", summary_text)
    self.assertIn("## Non-provider failures", summary_text)

  def test_weekly_skill_changed_during_run_is_infrastructure_failure(self):
    collection = self.root / "weekly-mutating"
    collection.mkdir()
    self.create_skill(collection, "mutating")
    summary = self.root / "weekly-mutating.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      env={"SKILLEVALUATOR_TEST_MUTATE_SKILL": "1"},
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "skill_changed_during_weekly_run")
    self.assertEqual(packet["tier1"]["infrastructure_failure"], 1)
    self.assertEqual(packet["skills"][0]["tier1"]["reason"], "skill_changed_during_weekly_run")
    self.assertEqual(packet["provider_failures"], [])
    self.assertEqual(len(packet["non_provider_failures"]), 2)
    self.assertTrue(all(failure["scope"] in {"tier1", "tier2-intra"} for failure in packet["non_provider_failures"]))
    self.assertTrue(all(failure["reason"] == "skill_changed_during_weekly_run" for failure in packet["non_provider_failures"]))
    summary_text = summary.read_text()
    self.assertIn("skill_changed_during_weekly_run", summary_text)
    self.assertIn("infrastructure failures 1", summary_text)
    self.assertNotIn("provider failures 1", summary_text)

  def test_weekly_evaluator_timeout_is_non_provider_failure(self):
    collection = self.root / "weekly-evaluator-timeout"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-evaluator-timeout.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      env={
        "SKILLEVALUATOR_TEST_T1": "sleep",
        "SKILLEVALUATOR_COMMAND_TIMEOUT_SECONDS": "0.1",
      },
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertNotIn("Traceback", result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "tier1_timeout")
    self.assertEqual(packet["provider_failures"], [])
    self.assertEqual(packet["non_provider_failures"][0]["scope"], "tier1")
    self.assertEqual(packet["non_provider_failures"][0]["reason"], "tier1_timeout")
    summary_text = summary.read_text()
    self.assertIn("tier1_timeout", summary_text)
    self.assertIn("## Non-provider failures", summary_text)

  def test_weekly_secret_detection_writes_structured_failure_packet_and_summary(self):
    collection = self.root / "weekly-secret-artifact"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-secret-artifact.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      env={"SKILLEVALUATOR_TEST_T2": "leak"},
    )
    self.assertEqual(result.returncode, 3)
    self.assertNotIn("Traceback", result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "secret_detected_in_artifacts")
    self.assertEqual(packet["provider_failures"], [])
    self.assertEqual(packet["non_provider_failures"][0]["target"], packet["artifact_root"])
    self.assertTrue(Path(packet["result_path"]).is_file())
    self.assertTrue(summary.is_file())
    summary_text = summary.read_text()
    self.assertIn("secret_detected_in_artifacts", summary_text)
    self.assertNotIn(self.secret, result.stdout)
    self.assertNotIn(self.secret, result.stderr)
    self.assertNotIn(self.secret, summary_text)
    artifact_files = [path for path in Path(packet["artifact_root"]).rglob("*") if path.is_file()]
    self.assertEqual({path.name for path in artifact_files}, {"weekly-result.json"})

  def test_weekly_secret_scan_failure_returns_structured_failure(self):
    collection = self.root / "weekly-secret-scan-failure"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-secret-scan-failure.md"
    module = runpy.run_path(str(SCRIPT))
    args = SimpleNamespace(collection=str(collection), date="2026-08-27", summary=str(summary), workers=1)
    output = io.StringIO()
    def fail_scan(*args, **kwargs):
      raise OSError("scan failure")
    runtime_globals = module["run_weekly"].__globals__
    with patch.dict(os.environ, self.env), patch.dict(runtime_globals, {"contains_secret": fail_scan}), redirect_stdout(output):
      returncode = module["run_weekly"](args)
    self.assertEqual(returncode, 3)
    packet = json.loads(output.getvalue())
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "secret_scan_failed")
    self.assertEqual(packet["provider_failures"], [])
    self.assertEqual(packet["non_provider_failures"][0]["scope"], "security")
    self.assertEqual(packet["non_provider_failures"][0]["reason"], "secret_scan_failed")
    self.assertEqual(packet["non_provider_failures"][0]["target"], packet["artifact_root"])
    self.assertTrue(summary.is_file())
    self.assertIn("secret_scan_failed", summary.read_text())
    self.assertNotIn(self.secret, output.getvalue())
    self.assertNotIn(self.secret, summary.read_text())

  def test_weekly_secret_cleanup_failure_uses_independent_sanitized_output(self):
    collection = self.root / "weekly-secret-cleanup-failure"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-secret-cleanup-failure.md"
    module = runpy.run_path(str(SCRIPT))
    args = SimpleNamespace(collection=str(collection), date="2026-08-27", summary=str(summary), workers=1)
    output = io.StringIO()
    environment = {**self.env, "SKILLEVALUATOR_TEST_T2": "leak"}
    def fail_rmtree(*args, **kwargs):
      return None
    runtime_globals = module["run_weekly"].__globals__
    with patch.dict(os.environ, environment), patch.dict(runtime_globals, {"shutil": SimpleNamespace(rmtree=fail_rmtree)}), redirect_stdout(output):
      returncode = module["run_weekly"](args)
    self.assertEqual(returncode, 3)
    packet = json.loads(output.getvalue())
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "secret_artifact_cleanup_failed")
    self.assertEqual(packet["provider_failures"], [])
    self.assertEqual(packet["non_provider_failures"][0]["scope"], "security")
    self.assertEqual(packet["non_provider_failures"][0]["reason"], "secret_artifact_cleanup_failed")
    independent_summary = Path(packet["summary_path"])
    independent_root = Path(packet["artifact_root"])
    cleanup_target = Path(packet["non_provider_failures"][0]["target"])
    self.assertNotEqual(cleanup_target, independent_root)
    self.assertTrue(cleanup_target.exists())
    self.assertNotEqual(independent_summary, summary)
    self.assertTrue(Path(packet["result_path"]).is_file())
    self.assertTrue(independent_summary.is_file())
    self.assertNotIn(self.secret, output.getvalue())
    self.assertNotIn(self.secret, independent_summary.read_text())
    safe_files = [path for path in independent_root.rglob("*") if path.is_file()]
    self.assertTrue(safe_files)
    self.assertTrue(all(self.secret not in path.read_text(errors="replace") for path in safe_files))
    weekly_parent = self.artifacts / "weekly" / args.date
    contaminated_roots = [path for path in weekly_parent.iterdir() if path.is_dir() and path != independent_root]
    self.assertTrue(contaminated_roots)
    contaminated_files = [path for root in contaminated_roots for path in root.rglob("*") if path.is_file()]
    self.assertTrue(any(self.secret in path.read_text(errors="replace") for path in contaminated_files))

  def test_weekly_embedding_preflights_once(self):
    collection = self.root / "weekly-embedding-preflight"
    collection.mkdir()
    for index in range(85):
      self.create_skill(collection, f"skill-{index:02d}")
    embedding_base = f"http://127.0.0.1:{self.embedding_server.server_address[1]}/v1"
    self.keys.write_text(
      f"CLIPROXY_BASE_URL=http://127.0.0.1:8317\n"
      f"CLIPROXY_KEY_ADMIN={self.secret}\n"
      f"SKILL_EVAL_EMBEDDING_BASE_URL={embedding_base}\n"
      "SKILL_EVAL_EMBEDDING_MODEL=fixture-weekly-embedding-model\n"
    )
    self.embedding_server.reset_request_count()
    summary = self.root / "weekly-embedding-preflight.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      "--workers",
      "8",
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["tier2_preflight"]["status"], "passed")
    self.assertEqual(packet["tier2_preflight"]["attempts"], 1)
    self.assertEqual(self.embedding_server.request_count, 1)
    self.assertEqual(self.embedding_server.request_payloads[0]["input"], ["SkillEvaluator preflight"])
    self.assertEqual(self.embedding_server.request_payloads[0]["encoding_format"], "float")
    self.assertEqual(self.embedding_server.request_payloads[0]["model"], "fixture-weekly-embedding-model")
    calls = [json.loads(line) for line in self.log.read_text().splitlines()]
    intra_calls = [call for call in calls if call["args"][0] == "context-optimization-check"]
    self.assertTrue(intra_calls)
    self.assertTrue(all(call["args"][call["args"].index("--model") + 1] == "fixture-weekly-embedding-model" for call in intra_calls))
    similarity = next(call for call in calls if call["args"][0] == "similarity-check")
    self.assertEqual(similarity["args"][similarity["args"].index("--model") + 1], "fixture-weekly-embedding-model")

  def test_weekly_embedding_preflight_rejects_invalid_vectors(self):
    invalid_vectors = ([0.0], ["0.0"], [float("nan")], [float("inf")], [10**400])
    for index, vector in enumerate(invalid_vectors):
      with self.subTest(vector=repr(vector)):
        self.embedding_server.vector = vector
        self.embedding_server.reset_request_count()
        if self.log.exists():
          self.log.unlink()
        collection = self.root / f"weekly-invalid-embedding-{index}"
        collection.mkdir()
        self.create_skill(collection, "one")
        summary = self.root / f"weekly-invalid-embedding-{index}.md"
        result = self.run_cli(
          "weekly",
          "--collection",
          str(collection),
          "--date",
          "2026-08-27",
          "--summary",
          str(summary),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["tier2_preflight"]["status"], "infrastructure_failure")
        self.assertEqual(packet["tier2_preflight"]["reason"], "embedding_probe_invalid_response")
        self.assertEqual(packet["tier2_intra"], {"passed": 0, "findings": 0, "infrastructure_failure": 1, "finding_count": 0})
        self.assertEqual(packet["tier2_inter"]["status"], "infrastructure_failure")
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([call for call in calls if call["args"][0] != "validate"], [])
        self.assertEqual(self.embedding_server.request_count, 1)

  def test_weekly_embedding_preflight_rejects_response_contract_violations(self):
    invalid_responses = (
      {"data": []},
      {"data": [{"index": 0, "embedding": [0.25]}, {"index": 1, "embedding": [0.5]}]},
      {"data": [{"index": 1, "embedding": [0.25]}]},
      {"data": [{"index": True, "embedding": [0.25]}]},
      {"data": [{"index": 0, "embedding": [sys.float_info.max]}]},
      {"data": [{"index": 0, "embedding": [0.25] * 65537}]},
    )
    for index, response_data in enumerate(invalid_responses):
      with self.subTest(response=index):
        self.embedding_server.response_data = response_data
        self.embedding_server.reset_request_count()
        if self.log.exists():
          self.log.unlink()
        collection = self.root / f"weekly-invalid-response-{index}"
        collection.mkdir()
        self.create_skill(collection, "one")
        summary = self.root / f"weekly-invalid-response-{index}.md"
        result = self.run_cli(
          "weekly",
          "--collection",
          str(collection),
          "--date",
          "2026-08-27",
          "--summary",
          str(summary),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        packet = json.loads(result.stdout)
        self.assertEqual(packet["tier2_preflight"]["status"], "infrastructure_failure")
        self.assertEqual(packet["tier2_preflight"]["reason"], "embedding_probe_invalid_response")
        self.assertEqual(packet["tier2_intra"], {"passed": 0, "findings": 0, "infrastructure_failure": 1, "finding_count": 0})
        self.assertEqual(packet["tier2_inter"]["status"], "infrastructure_failure")
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([call for call in calls if call["args"][0] != "validate"], [])
        self.assertEqual(self.embedding_server.request_count, 1)

  def test_weekly_embedding_endpoint_unreachable_preflights_once(self):
    collection = self.root / "weekly-embedding-unreachable"
    collection.mkdir()
    for index in range(85):
      self.create_skill(collection, f"skill-{index:02d}")
    with socket.socket() as probe_socket:
      probe_socket.bind(("127.0.0.1", 0))
      refused_port = probe_socket.getsockname()[1]
    self.keys.write_text(
      f"CLIPROXY_BASE_URL=http://127.0.0.1:8317\n"
      f"CLIPROXY_KEY_ADMIN={self.secret}\n"
      f"SKILL_EVAL_EMBEDDING_BASE_URL=http://127.0.0.1:{refused_port}/v1\n"
      "SKILL_EVAL_EMBEDDING_MODEL=nomic-embed-text\n"
    )
    summary = self.root / "weekly-embedding-unreachable.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
      "--workers",
      "8",
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "embedding_endpoint_unreachable")
    self.assertEqual(packet["tier2_preflight"]["status"], "infrastructure_failure")
    self.assertEqual(packet["tier2_preflight"]["attempts"], 1)
    self.assertEqual(packet["tier2_preflight"]["reason"], "embedding_endpoint_unreachable")
    self.assertEqual(packet["tier2_intra"], {"passed": 0, "findings": 0, "infrastructure_failure": 85, "finding_count": 0})
    self.assertEqual(packet["tier2_inter"]["status"], "infrastructure_failure")
    self.assertEqual(packet["tier2_inter"]["finding_count"], 0)
    calls = [json.loads(line) for line in self.log.read_text().splitlines()]
    self.assertEqual(len([call for call in calls if call["args"][0] == "validate"]), 85)
    self.assertEqual(
      [call for call in calls if call["args"][0] in {"context-optimization-check", "similarity-check"}],
      [],
    )
    summary_text = summary.read_text()
    self.assertNotIn("Status：completed", summary_text)
    self.assertNotIn("Reason：none", summary_text)
    self.assertIn("embedding_endpoint_unreachable", summary_text)

  def test_weekly_embedding_preflight_bad_status_is_structured_failure(self):
    malformed_server = MalformedHTTPServer(("127.0.0.1", 0), MalformedHTTPHandler)
    malformed_thread = threading.Thread(target=malformed_server.serve_forever, daemon=True)
    malformed_thread.start()
    try:
      self.keys.write_text(
        f"CLIPROXY_BASE_URL=http://127.0.0.1:8317\n"
        f"CLIPROXY_KEY_ADMIN={self.secret}\n"
        f"SKILL_EVAL_EMBEDDING_BASE_URL=http://127.0.0.1:{malformed_server.server_address[1]}/v1\n"
        "SKILL_EVAL_EMBEDDING_MODEL=nomic-embed-text\n"
      )
      collection = self.root / "weekly-bad-status-embedding"
      collection.mkdir()
      self.create_skill(collection, "one")
      summary = self.root / "weekly-bad-status-embedding.md"
      result = self.run_cli(
        "weekly",
        "--collection",
        str(collection),
        "--date",
        "2026-08-27",
        "--summary",
        str(summary),
      )
      self.assertEqual(result.returncode, 0, result.stderr)
      self.assertNotIn("Traceback", result.stderr)
      packet = json.loads(result.stdout)
      self.assertEqual(packet["status"], "infrastructure_failure")
      self.assertEqual(packet["reason"], "embedding_probe_http_error")
      self.assertEqual(packet["tier1"], {"passed": 1, "failed": 0, "infrastructure_failure": 0})
      self.assertEqual(packet["tier2_intra"]["infrastructure_failure"], 1)
      self.assertEqual(packet["tier2_inter"]["status"], "infrastructure_failure")
      self.assertIn("embedding_probe_http_error", summary.read_text())
      calls = [json.loads(line) for line in self.log.read_text().splitlines()]
      self.assertEqual([call for call in calls if call["args"][0] != "validate"], [])
    finally:
      malformed_server.shutdown()
      malformed_server.server_close()
      malformed_thread.join(timeout=1)

  def test_weekly_embedding_preflight_malformed_url_is_structured_failure(self):
    self.keys.write_text(
      f"CLIPROXY_BASE_URL=http://127.0.0.1:8317\n"
      f"CLIPROXY_KEY_ADMIN={self.secret}\n"
      "SKILL_EVAL_EMBEDDING_BASE_URL=http://[::1\n"
      "SKILL_EVAL_EMBEDDING_MODEL=nomic-embed-text\n"
    )
    collection = self.root / "weekly-malformed-embedding-url"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-malformed-embedding-url.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertNotIn("Traceback", result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["tier1"], {"passed": 1, "failed": 0, "infrastructure_failure": 0})
    self.assertEqual(packet["tier2_preflight"]["status"], "infrastructure_failure")
    self.assertEqual(packet["tier2_intra"]["infrastructure_failure"], 1)
    self.assertEqual(packet["tier2_inter"]["status"], "infrastructure_failure")
    self.assertIn("infrastructure_failure", summary.read_text())
    self.assertIn("embedding", summary.read_text())
    calls = [json.loads(line) for line in self.log.read_text().splitlines()]
    self.assertEqual([call for call in calls if call["args"][0] != "validate"], [])

  def test_embedding_preflight_closes_http_error_response(self):
    module = runpy.run_path(str(SCRIPT))

    class ClosableResponse:
      def __init__(self):
        self.closed = False

      def close(self):
        self.closed = True

    response = ClosableResponse()
    error = HTTPError("http://127.0.0.1:8317/v1/embeddings", 503, "unavailable", {}, response)

    def raise_error(*args, **kwargs):
      raise error

    module["embedding_preflight"].__globals__["urlopen"] = raise_error
    result = module["embedding_preflight"]({
      "SKILL_EVAL_EMBEDDING_BASE_URL": "http://127.0.0.1:8317/v1",
      "SKILL_EVAL_EMBEDDING_MODEL": "nomic-embed-text",
      "SKILL_EVAL_EMBEDDING_API_KEY": "local-no-key",
    })
    self.assertEqual(result["status"], "infrastructure_failure")
    self.assertEqual(result["reason"], "embedding_endpoint_http_error")
    self.assertTrue(response.closed)

  def test_weekly_embedding_preflight_oversize_response_is_structured_failure(self):
    self.embedding_server.response_body = b"x" * (MAX_JSON_BYTES + 1)
    self.embedding_server.reset_request_count()
    collection = self.root / "weekly-oversize-embedding-response"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-oversize-embedding-response.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertNotIn("Traceback", result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "embedding_probe_response_too_large")
    self.assertEqual(packet["tier1"], {"passed": 1, "failed": 0, "infrastructure_failure": 0})
    self.assertEqual(packet["tier2_intra"]["infrastructure_failure"], 1)
    self.assertEqual(packet["tier2_inter"]["status"], "infrastructure_failure")
    self.assertEqual(self.embedding_server.request_count, 1)
    self.assertIn("embedding_probe_response_too_large", summary.read_text())
    calls = [json.loads(line) for line in self.log.read_text().splitlines()]
    self.assertEqual([call for call in calls if call["args"][0] != "validate"], [])

  def test_weekly_embedding_preflight_bounds_oversize_response_without_content_length(self):
    self.embedding_server.response_body = b"x" * (MAX_JSON_BYTES + 1)
    self.embedding_server.omit_content_length = True
    self.embedding_server.reset_request_count()
    collection = self.root / "weekly-oversize-embedding-response-without-length"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-oversize-embedding-response-without-length.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertNotIn("Traceback", result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "embedding_probe_response_too_large")
    self.assertEqual(packet["tier1"], {"passed": 1, "failed": 0, "infrastructure_failure": 0})
    self.assertEqual(packet["tier2_intra"]["infrastructure_failure"], 1)
    self.assertEqual(packet["tier2_inter"]["status"], "infrastructure_failure")
    self.assertEqual(self.embedding_server.request_count, 1)
    self.assertIn("embedding_probe_response_too_large", summary.read_text())
    calls = [json.loads(line) for line in self.log.read_text().splitlines()]
    self.assertEqual([call for call in calls if call["args"][0] != "validate"], [])

  def test_embedding_preflight_uses_bounded_read_without_content_length(self):
    module = runpy.run_path(str(SCRIPT))

    class BoundedResponse:
      def __init__(self):
        self.headers = {}
        self.read_size = None

      def __enter__(self):
        return self

      def __exit__(self, *args):
        return False

      def read(self, size=-1):
        self.read_size = size
        return b"x" * (size + 1) if size >= 0 else b"{}"

    response = BoundedResponse()
    module["embedding_preflight"].__globals__["urlopen"] = lambda *args, **kwargs: response
    result = module["embedding_preflight"]({
      "SKILL_EVAL_EMBEDDING_BASE_URL": "http://127.0.0.1:8317/v1",
      "SKILL_EVAL_EMBEDDING_MODEL": "nomic-embed-text",
      "SKILL_EVAL_EMBEDDING_API_KEY": "local-no-key",
    })
    self.assertEqual(result["status"], "infrastructure_failure")
    self.assertEqual(result["reason"], "embedding_probe_response_too_large")
    self.assertEqual(response.read_size, MAX_JSON_BYTES + 1)

  def test_weekly_embedding_preflight_incomplete_response_is_structured_failure(self):
    self.embedding_server.response_body = b"{\"data\": []}"
    self.embedding_server.response_content_length = len(self.embedding_server.response_body) + 1
    self.embedding_server.reset_request_count()
    collection = self.root / "weekly-incomplete-embedding-response"
    collection.mkdir()
    self.create_skill(collection, "one")
    summary = self.root / "weekly-incomplete-embedding-response.md"
    result = self.run_cli(
      "weekly",
      "--collection",
      str(collection),
      "--date",
      "2026-08-27",
      "--summary",
      str(summary),
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertNotIn("Traceback", result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "infrastructure_failure")
    self.assertEqual(packet["reason"], "embedding_probe_incomplete_response")
    self.assertEqual(packet["tier1"], {"passed": 1, "failed": 0, "infrastructure_failure": 0})
    self.assertEqual(packet["tier2_intra"]["infrastructure_failure"], 1)
    self.assertEqual(packet["tier2_inter"]["status"], "infrastructure_failure")
    self.assertEqual(self.embedding_server.request_count, 1)
    self.assertIn("embedding_probe_incomplete_response", summary.read_text())
    calls = [json.loads(line) for line in self.log.read_text().splitlines()]
    self.assertEqual([call for call in calls if call["args"][0] != "validate"], [])

  def test_tier3_requires_exactly_one_eval_case(self):
    (self.skill / "evals" / "evals.json").write_text(json.dumps([
      {"id": "fixture-001", "question": "One."},
      {"id": "fixture-002", "question": "Two."},
    ]))
    result = self.run_cli("tier3", "--skill", str(self.skill), "--results-dir", str(self.root / "tier3-two-cases"))
    self.assertEqual(result.returncode, 3)
    self.assertIn("exactly one eval case", json.loads(result.stdout)["reason"])

  def test_tier3_manual_runner_fixes_parameters_and_returns_artifact_pointers(self):
    results_dir = self.root / "tier3-results"
    result = self.run_cli("tier3", "--skill", str(self.skill), "--results-dir", str(results_dir))
    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["kind"], "tier3")
    self.assertEqual(packet["status"], "completed")
    self.assertEqual(packet["verdict"], "not_a_skill_verdict")
    self.assertTrue(Path(packet["result_path"]).is_file())
    self.assertTrue(Path(packet["html_path"]).is_file())
    self.assertEqual(len(packet["harbor_summary_paths"]), 2)
    call = json.loads(self.log.read_text().splitlines()[-1])
    args = call["args"]
    self.assertEqual(args[:3], ["tier3", "evaluate", str(self.skill.resolve())])
    self.assertTrue(call["has_openai_key"])
    self.assertIn("--agents", args)
    self.assertEqual(args[args.index("--agents") + 1], "codex")
    self.assertEqual(args[args.index("--env-mode") + 1], "local")
    self.assertEqual(args[args.index("--n-attempts") + 1], "1")
    self.assertEqual(args[args.index("--n-concurrent") + 1], "1")
    self.assertEqual(args[args.index("--max-agents") + 1], "1")
    self.assertNotIn("--skip-baseline", args)
    self.assertNotIn("--llm-verify", args)
    rejected = self.run_cli("tier3", "--skill", str(self.skill), "--llm-verify")
    self.assertEqual(rejected.returncode, 2)

  def test_tier3_propagates_configured_llm_model(self):
    self.keys.write_text(
      f"CLIPROXY_BASE_URL=http://127.0.0.1:8317\n"
      f"CLIPROXY_KEY_ADMIN={self.secret}\n"
      "SKILL_EVAL_LLM_MODEL=fixture-tier3-model\n"
    )
    result = self.run_cli(
      "tier3",
      "--skill",
      str(self.skill),
      "--results-dir",
      str(self.root / "tier3-configured-model"),
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    call = json.loads(self.log.read_text().splitlines()[-1])
    args = call["args"]
    self.assertEqual(args[args.index("--model") + 1], "fixture-tier3-model")
    self.assertEqual(args[args.index("--agent-model") + 1], "codex=fixture-tier3-model")

  def test_tier3_complete_result_can_normalize_upstream_nonzero_exit(self):
    result = self.run_cli(
      "tier3",
      "--skill",
      str(self.skill),
      "--results-dir",
      str(self.root / "tier3-complete-nonzero"),
      env={"SKILLEVALUATOR_TEST_TIER3": "complete-nonzero"},
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    packet = json.loads(result.stdout)
    self.assertEqual(packet["status"], "completed")
    self.assertEqual(packet["upstream_exit_code"], 1)

  def test_tier3_zero_attempt_result_is_not_complete(self):
    results_dir = self.root / "tier3-zero-attempt"
    result = self.run_cli(
      "tier3",
      "--skill",
      str(self.skill),
      "--results-dir",
      str(results_dir),
      env={"SKILLEVALUATOR_TEST_TIER3": "zero-attempt"},
    )
    self.assertEqual(result.returncode, 3)
    self.assertEqual(json.loads(result.stdout)["status"], "infrastructure_failure")

  def test_tier3_boolean_attempt_result_is_not_complete(self):
    result = self.run_cli(
      "tier3",
      "--skill",
      str(self.skill),
      "--results-dir",
      str(self.root / "tier3-boolean-attempt"),
      env={"SKILLEVALUATOR_TEST_TIER3": "boolean-attempt"},
    )
    self.assertEqual(result.returncode, 3)
    self.assertEqual(json.loads(result.stdout)["status"], "infrastructure_failure")

  def test_tier3_incomplete_secret_artifact_is_removed(self):
    results_dir = self.root / "tier3-incomplete-secret"
    result = self.run_cli(
      "tier3",
      "--skill",
      str(self.skill),
      "--results-dir",
      str(results_dir),
      env={"SKILLEVALUATOR_TEST_TIER3": "incomplete-secret"},
    )
    self.assertEqual(result.returncode, 3)
    combined = "\n".join(path.read_text(errors="replace") for path in results_dir.rglob("*") if path.is_file())
    self.assertNotIn(self.secret, combined)
    self.assertFalse(any(path.name == "run-fixture" for path in results_dir.rglob("*")))

  def test_tier3_timeout_returns_infrastructure_failure(self):
    result = self.run_cli(
      "tier3",
      "--skill",
      str(self.skill),
      "--results-dir",
      str(self.root / "tier3-timeout"),
      env={
        "SKILLEVALUATOR_TEST_TIER3": "sleep",
        "SKILLEVALUATOR_TIER3_TIMEOUT_SECONDS": "0.1",
      },
    )
    self.assertEqual(result.returncode, 3)
    self.assertIn("timeout", json.loads(result.stdout)["reason"])

  def test_tier3_timeout_terminates_child_process_group(self):
    late_path = self.root / "late-secret.txt"
    result = self.run_cli(
      "tier3",
      "--skill",
      str(self.skill),
      "--results-dir",
      str(self.root / "tier3-child-timeout"),
      env={
        "SKILLEVALUATOR_TEST_TIER3": "spawn-child",
        "SKILLEVALUATOR_TEST_LATE_PATH": str(late_path),
        "SKILLEVALUATOR_TIER3_TIMEOUT_SECONDS": "0.1",
      },
    )
    self.assertEqual(result.returncode, 3)
    time.sleep(0.7)
    self.assertFalse(late_path.exists())

  def test_tier3_failure_does_not_report_completion(self):
    result = self.run_cli(
      "tier3",
      "--skill",
      str(self.skill),
      "--results-dir",
      str(self.root / "tier3-failure"),
      env={"SKILLEVALUATOR_TEST_TIER3": "infra"},
    )
    self.assertEqual(result.returncode, 3)
    self.assertEqual(json.loads(result.stdout)["status"], "infrastructure_failure")


if __name__ == "__main__":
  unittest.main()
