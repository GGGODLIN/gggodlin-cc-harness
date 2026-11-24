#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "pr-review-cc-group-flow.py"
GROUP_SCRIPT = ROOT / "pr-review-group-report.py"
TARGETS_TEST = ROOT / "test_pr_review_targets.py"
SAAS = "github:github.com/acme/saas#11"
DASH = "github:github.com/acme/dashboard#707"


def load_module():
  spec = importlib.util.spec_from_file_location("pr_review_cc_group_flow", SCRIPT)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def load_targets_test():
  spec = importlib.util.spec_from_file_location("test_pr_review_targets", TARGETS_TEST)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def run_flow(mode, payload):
  proc = subprocess.run([sys.executable, str(SCRIPT), mode], input=json.dumps(payload),
                        capture_output=True, text=True)
  if not proc.stdout.strip():
    raise AssertionError(f"{mode} produced no stdout; stderr={proc.stderr}")
  return json.loads(proc.stdout)


def range_state(base):
  targets_test = load_targets_test()
  fx = targets_test.MergedFixture(base)
  prepared = targets_test.run_cli("prepare", fx.payload(
    fx.saas_inputs(), fx.saas_platform(), since=[f"acme/saas={fx.c['side']}"]))
  assert prepared["status"] == "READY", json.dumps(prepared, ensure_ascii=False)
  finalized = targets_test.run_cli("finalize", {
    "preparation_path": prepared["preparation_path"], "selection": selection(), "adjudication": {},
  })
  whole = targets_test.git(fx.saas, "diff", f"{fx.c['side']}..{fx.c['tail']}")
  return fx, prepared, finalized, whole


def set_identity(targets):
  value = "\n".join(sorted(target["target_identity"] for target in targets))
  return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def target(identity, repo, files):
  return {
    "target_identity": identity,
    "destination_repo": repo,
    "review_root": f"/reviews/{repo.replace('/', '-')}",
    "head": ("a" if identity == SAAS else "b") * 40,
    "base": ("c" if identity == SAAS else "d") * 40,
    "authored_diff_base": ("e" if identity == SAAS else "f") * 40,
    "changed_files": list(files),
    "rules": {"trunk": "master", "spec_globs": ["openspec/**/*.md"],
              "conventions_docs": ["CLAUDE.md"]},
    "materials": {"root": f"/materials/{repo.replace('/', '-')}",
                  "specs": [{"path": "openspec/spec.md", "content_sha256": "1" * 64}]},
  }


def selection():
  return [
    {"seat": "cc-primary", "angle": "context-aware primary", "status": "selected"},
    {"seat": "cc-security", "angle": "security", "status": "selected"},
  ]


def state(base, targets=None, selected=None):
  targets = targets or [target(SAAS, "acme/saas", ["src/a.ts"]),
                        target(DASH, "acme/dashboard", ["src/b.ts"])]
  selected = selection() if selected is None else selected
  preparation = Path(base) / "run-01.json"
  result = {
    "status": "READY",
    "run_id": "run-01",
    "preparation_path": str(preparation),
    "cancelled": False,
    "selection": selected,
    "selection_count": 1 if selected else 0,
    "dispatch_seats": sorted({cell["seat"] for cell in selected}),
    "capacity": {"adjudication_required": False, "decision": "within-threshold"},
    "targets": targets,
    "set_identity": set_identity(targets),
    "division_of_labor": [
      {"seat": cell["seat"], "angle": cell["angle"],
       "primary_material": [{"target_identity": item["target_identity"],
                             "changed_files": item["changed_files"]} for item in targets],
       "extra_context": [], "shared_bytes": 0}
      for cell in selected
    ],
  }
  preparation.write_text(json.dumps(result))
  return result


class Recorder:
  def __init__(self, responses):
    self.responses = list(responses)
    self.calls = []

  def __call__(self, request):
    self.calls.append(request)
    response = self.responses.pop(0)
    if isinstance(response, BaseException):
      raise response
    return response


class CcGroupFlowTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.module = load_module()

  def test_repo_distribution_does_not_multiply_selected_dispatches(self):
    split = state(self.tmp.name)
    redistributed_targets = [
      target(SAAS, "acme/saas", ["src/a.ts"]),
      target(DASH, "acme/saas", ["src/b.ts"]),
    ]
    redistributed = state(self.tmp.name, targets=redistributed_targets)
    split_plan = self.module.plan_dispatch(split, selection(), True)
    redistributed_plan = self.module.plan_dispatch(redistributed, selection(), True)
    self.assertEqual(len(split_plan["dispatches"]), 2)
    self.assertEqual(len(redistributed_plan["dispatches"]), 2)
    for plan in (split_plan, redistributed_plan):
      for dispatch in plan["dispatches"]:
        self.assertEqual({item["target_identity"] for item in dispatch["targets"]}, {SAAS, DASH})
        self.assertEqual(len(dispatch["file_ownership"]), 2)

  def test_non_cc_selected_cells_never_enter_the_cc_ledger(self):
    current = state(self.tmp.name)
    mixed = [
      *selection(),
      {"seat": "opus/spec-compliance-reviewer", "angle": "formal spec", "status": "selected"},
      {"seat": "codex", "angle": "Codex 中性", "status": "selected"},
      {"seat": "agy", "angle": "Gemini Pro", "status": "selected"},
      {"seat": "web-gpt", "angle": "web GPT Pro", "status": "selected"},
    ]
    plan = self.module.plan_dispatch(current, mixed, True)
    self.assertEqual(
      [("cc-primary", "context-aware primary"), ("cc-security", "security")],
      [(item["seat"], item["angle"]) for item in plan["dispatches"]],
    )

  def test_new_interface_uses_one_existing_responsibility_seat(self):
    current = state(self.tmp.name)
    responses = [
      {"status": "ok", "findings": [], "new_interfaces": [
        {"interface_id": "bridge", "target_identity": DASH, "description": "dashboard calls saas"},
      ]},
      {"status": "ok", "findings": []},
      {"status": "ok", "findings": [], "checks": [
        {"interface_id": "bridge", "status": "completed", "evidence": "src/b.ts:4"},
      ]},
    ]
    recorder = Recorder(responses)
    result = self.module.run_group_review({
      "state": current, "selection": selection(), "confirmation": True,
      "repair_seat": "cc-primary",
    }, recorder)
    self.assertEqual(len(recorder.calls), 3)
    self.assertEqual(recorder.calls[-1]["phase"], "repair")
    self.assertEqual(recorder.calls[-1]["seat"], "cc-primary")
    self.assertEqual(result["new_interface_checks"][0]["status"], "completed")
    self.assertEqual(result["repair_rounds"], 1)

    unverified = Recorder(responses[:2] + [{"status": "ok", "findings": [], "checks": []}])
    result = self.module.run_group_review({
      "state": current, "selection": selection(), "confirmation": True,
      "repair_seat": "cc-primary",
    }, unverified)
    self.assertEqual(result["new_interface_checks"][0]["status"], "unverified")

  def test_missed_files_and_new_interfaces_share_one_repair_round(self):
    current = state(self.tmp.name)
    recorder = Recorder([
      {"status": "ok", "findings": [], "missed_files": [
        {"target_identity": SAAS, "file": "src/a.ts"}], "new_interfaces": [
        {"interface_id": "bridge", "target_identity": DASH, "description": "new bridge"}]},
      {"status": "ok", "findings": []},
      {"status": "ok", "findings": [], "accounted_files": [
        {"target_identity": SAAS, "file": "src/a.ts"}], "checks": [
        {"interface_id": "bridge", "status": "completed", "evidence": "src/b.ts:4"}]},
    ])
    result = self.module.run_group_review({
      "state": current, "selection": selection(), "confirmation": True,
      "repair_seat": "cc-primary",
    }, recorder)
    repairs = [call for call in recorder.calls if call["phase"] == "repair"]
    self.assertEqual(len(repairs), 1)
    self.assertEqual(len(repairs[0]["missed_files"]), 1)
    self.assertEqual(len(repairs[0]["new_interfaces"]), 1)
    self.assertEqual(result["coverage"]["unverified"], [])

    no_cc = state(self.tmp.name, selected=[
      {"seat": "codex-neutral", "angle": "neutral", "status": "selected"}])
    no_calls = Recorder([])
    skipped = self.module.run_group_review({
      "state": no_cc, "selection": [], "confirmation": True,
      "repair_seat": None,
    }, no_calls)
    self.assertEqual(skipped["status"], "SKIPPED")
    self.assertEqual(len(no_calls.calls), 0)
    self.assertEqual(skipped["coverage"]["state"], "UNVERIFIED")

  def test_blocked_cancelled_failure_and_timeout_never_rerun_by_repo(self):
    blocked = state(self.tmp.name)
    blocked["capacity"]["adjudication_required"] = True
    no_calls = Recorder([])
    result = self.module.run_group_review({
      "state": blocked, "selection": selection(), "confirmation": True,
    }, no_calls)
    self.assertEqual(result["status"], "BLOCKED")
    self.assertEqual(len(no_calls.calls), 0)

    cancelled = state(self.tmp.name)
    cancelled["cancelled"] = True
    result = self.module.run_group_review({
      "state": cancelled, "selection": selection(), "confirmation": True,
    }, no_calls)
    self.assertEqual(result["reason"], "cancelled")
    self.assertEqual(len(no_calls.calls), 0)

    recorder = Recorder([
      RuntimeError("failed"),
      {"status": "ok", "findings": [{
        "target_identity": DASH, "file": "src/b.ts", "line": 3,
        "anchor": "b", "root_cause": "broken guard", "source": "cc",
      }]},
    ])
    result = self.module.run_group_review({
      "state": state(self.tmp.name), "selection": selection(), "confirmation": True,
    }, recorder)
    self.assertEqual(len(recorder.calls), 2)
    self.assertEqual(len(result["failed_seats"]), 1)
    self.assertEqual(len(result["group_payload"]["findings"]), 1)
    self.assertEqual(result["status"], "PARTIAL")

    timeout = Recorder([TimeoutError("timeout"), {"status": "ok", "findings": []}])
    result = self.module.run_group_review({
      "state": state(self.tmp.name), "selection": selection(), "confirmation": True,
    }, timeout)
    self.assertEqual(len(timeout.calls), 2)
    self.assertEqual(result["failed_seats"][0]["status"], "TIMEOUT")

  def test_versions_rules_specs_and_multi_locations_reach_group_report(self):
    current = state(self.tmp.name)
    recorder = Recorder([
      {"status": "ok", "findings": [{
        "target_identity": SAAS, "file": "src/a.ts", "line": 2,
        "anchor": "guard", "root_cause": "missing guard", "source": "cc",
        "failure_chain_id": "chain-1",
      }]},
      {"status": "ok", "findings": [{
        "target_identity": DASH, "file": "src/b.ts", "line": 4,
        "anchor": "guard", "root_cause": "missing guard", "source": "cc",
        "failure_chain_id": "chain-1",
      }]},
    ])
    result = self.module.run_group_review({
      "state": current, "selection": selection(), "confirmation": True,
    }, recorder)
    dispatch = result["dispatch_ledger"][0]
    self.assertIn("rules", dispatch["targets"][0])
    self.assertIn("materials", dispatch["targets"][0])
    payload = result["group_payload"]
    self.assertEqual({item["target_identity"] for item in payload["targets"]}, {SAAS, DASH})
    rendered = subprocess.run(
      [sys.executable, str(GROUP_SCRIPT), "render"],
      input=json.dumps(payload), capture_output=True, text=True,
    )
    self.assertEqual(rendered.returncode, 0, rendered.stderr)
    self.assertIn("## 跨目標位置", rendered.stdout)
    self.assertIn(SAAS, rendered.stdout)
    self.assertIn(DASH, rendered.stdout)

    legacy = state(self.tmp.name, targets=[target(SAAS, "acme/saas", ["src/a.ts"])])
    no_calls = Recorder([])
    legacy_result = self.module.run_group_review({
      "state": legacy, "selection": selection(), "confirmation": True,
    }, no_calls)
    self.assertEqual(legacy_result["mode"], "legacy-single-target")
    self.assertEqual(len(no_calls.calls), 0)


class CcGroupRangeTargetTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.fx, self.prepared, self.finalized, self.whole = range_state(self.tmp.name)
    self.range_target = self.prepared["targets"][0]

  def test_single_range_target_plans_the_range_flow_with_the_prepared_diff(self):
    plan = run_flow("plan", {"preparation_path": self.finalized["preparation_path"],
                             "confirmation": True})
    self.assertNotEqual(plan["mode"], "legacy-single-target")
    self.assertEqual(plan["mode"], "range")
    self.assertEqual(plan["status"], "READY")
    self.assertEqual(len(plan["dispatches"]), 2)
    expected = Path(self.range_target["review_diff"]["file"]).read_bytes()
    self.assertNotEqual(self.whole.encode("utf-8"), expected)
    self.assertIn("side0.txt", self.whole)
    for dispatch in plan["dispatches"]:
      material = dispatch["targets"][0]
      self.assertEqual(material["kind"], "range")
      self.assertEqual(material["start"]["sha"], self.fx.c["side"])
      self.assertEqual(material["end"]["sha"], self.fx.c["tail"])
      self.assertEqual(material["review_diff"], self.range_target["review_diff"])
      received = Path(material["review_diff"]["file"]).read_bytes()
      self.assertEqual(received, expected)
      self.assertNotIn(b"side0.txt", received)
      for field in ("head", "base", "authored_diff_base"):
        self.assertIsNone(material.get(field))
    print(f"cc-plan diff file={material['review_diff']['file']} bytes={len(expected)}")

  def test_reviewer_without_file_accounting_is_not_complete(self):
    reduced = run_flow("reduce", {
      "preparation_path": self.finalized["preparation_path"], "confirmation": True,
      "selection": selection(), "responses": [{"status": "ok", "findings": []}, {"status": "ok", "findings": []}],
    })
    self.assertNotEqual(reduced["coverage"]["state"], "COMPLETE")
    self.assertNotEqual(reduced["status"], "COMPLETE")
    identity = self.range_target["target_identity"]
    self.assertEqual(
      sorted((item["target_identity"], item["file"]) for item in reduced["coverage"]["unverified"]),
      sorted((identity, path) for path in self.range_target["changed_files"]),
    )
    accounted = [{"target_identity": identity, "file": path}
                 for path in self.range_target["changed_files"]]
    complete = run_flow("reduce", {
      "preparation_path": self.finalized["preparation_path"], "confirmation": True,
      "selection": selection(), "responses": [{"status": "ok", "findings": [], "accounted_files": accounted},
                    {"status": "ok", "findings": [], "accounted_files": accounted}],
    })
    self.assertEqual(complete["coverage"]["state"], "COMPLETE")
    self.assertEqual(complete["coverage"]["unverified"], [])
    print(f"cc-reduce no-accounting coverage={reduced['coverage']['state']} "
          f"unverified={len(reduced['coverage']['unverified'])}")

  def reduce_with(self, responses, repair_seat=None):
    return run_flow("reduce", {
      "preparation_path": self.finalized["preparation_path"], "confirmation": True,
      "selection": selection(), "responses": responses, "repair_seat": repair_seat,
    })

  def test_reduce_counts_reviewed_skipped_and_unaccounted(self):
    identity = self.range_target["target_identity"]
    self.assertEqual(sorted(self.range_target["changed_files"]),
                     ["gone.txt", "new.txt", "renamed.txt", "shared.txt"])
    primary = {"status": "ok", "findings": [], "accounted_files": [
      {"target_identity": identity, "file": "gone.txt"},
      {"target_identity": identity, "file": "new.txt", "disposition": "skipped"},
      {"target_identity": identity, "file": "renamed.txt", "disposition": "skipped"},
    ]}
    security = {"status": "ok", "findings": [], "accounted_files": [
      {"target_identity": identity, "file": "renamed.txt", "disposition": "reviewed"},
    ]}
    unrepaired = self.reduce_with([primary, security, {"status": "ok", "findings": []}],
                                  repair_seat="cc-primary")
    self.assertEqual(unrepaired["coverage"]["counts"],
                     {"total": 4, "reviewed": 2, "skipped": 1, "unaccounted": 1})
    self.assertEqual(unrepaired["status"], "PARTIAL")

    repaired = self.reduce_with([primary, security, {"status": "ok", "findings": [], "accounted_files": [
      {"target_identity": identity, "file": "shared.txt", "disposition": "skipped"}]}],
      repair_seat="cc-primary")
    self.assertEqual(repaired["coverage"]["counts"],
                     {"total": 4, "reviewed": 2, "skipped": 2, "unaccounted": 0})
    self.assertEqual(repaired["coverage"]["state"], "COMPLETE")
    print(f"cc-reduce counts unrepaired={unrepaired['coverage']['counts']} "
          f"repaired={repaired['coverage']['counts']}")

  def test_unknown_disposition_is_not_counted_as_reviewed(self):
    identity = self.range_target["target_identity"]
    files = self.range_target["changed_files"]
    primary = {"status": "ok", "findings": [], "accounted_files": [
      {"target_identity": identity, "file": files[0], "disposition": "SKIPPED"},
      *({"target_identity": identity, "file": path} for path in files[1:]),
    ]}
    reduced = self.reduce_with([primary])
    self.assertEqual(reduced["coverage"]["counts"],
                     {"total": 4, "reviewed": 3, "skipped": 0, "unaccounted": 1})

  def test_reply_without_status_ok_stays_failed(self):
    identity = self.range_target["target_identity"]
    accounted = [{"target_identity": identity, "file": path}
                 for path in self.range_target["changed_files"]]
    reduced = self.reduce_with([{"findings": [], "accounted_files": accounted},
                                {"status": "ok", "findings": [], "accounted_files": accounted}])
    self.assertEqual([item["status"] for item in reduced["failed_seats"]], ["FAILED"])
    self.assertEqual(reduced["status"], "PARTIAL")
    self.assertEqual(reduced["coverage"]["counts"]["reviewed"], 4)
    print(f"cc-reduce missing-status failed_seats={reduced['failed_seats']}")


class CcGroupFlowChaosTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.module = load_module()
    self.fx, self.prepared, self.finalized, self.whole = range_state(self.tmp.name)
    self.range_target = self.prepared["targets"][0]

  def reduce_with(self, responses, repair_seat=None):
    return run_flow("reduce", {
      "preparation_path": self.finalized["preparation_path"], "confirmation": True,
      "selection": selection(), "responses": responses, "repair_seat": repair_seat,
    })

  def test_unknown_disposition_in_initial_and_repair_keeps_status_partial_and_coverage_unverified(self):
    # BUG-12: unknown disposition in initial or repair accounted_files must not yield COMPLETE status/coverage
    identity = self.range_target["target_identity"]
    files = self.range_target["changed_files"]
    initial_ok_with_unknown = {"status": "ok", "findings": [], "accounted_files": [
      {"target_identity": identity, "file": files[0], "disposition": "SKIPPED"},
      *({"target_identity": identity, "file": path} for path in files[1:]),
    ]}
    # Both seats succeed, but files[0] only has unknown disposition "SKIPPED"
    reduced = self.reduce_with([initial_ok_with_unknown, initial_ok_with_unknown])
    self.assertEqual(reduced["coverage"]["counts"], {"total": 4, "reviewed": 3, "skipped": 0, "unaccounted": 1})
    self.assertEqual(reduced["coverage"]["state"], "UNVERIFIED")
    self.assertEqual(reduced["status"], "PARTIAL")
    self.assertEqual([(item["target_identity"], item["file"]) for item in reduced["coverage"]["unverified"]],
                     [(identity, files[0])])

    # Repair returning unknown disposition must also stay UNVERIFIED and PARTIAL
    repair_bad = {"status": "ok", "findings": [], "accounted_files": [
      {"target_identity": identity, "file": files[0], "disposition": "BOGUS"},
    ]}
    repaired_bad = self.reduce_with([initial_ok_with_unknown, initial_ok_with_unknown, repair_bad],
                                    repair_seat="cc-primary")
    self.assertEqual(repaired_bad["repair_rounds"], 1)
    self.assertEqual(repaired_bad["coverage"]["counts"]["unaccounted"], 1)
    self.assertEqual(repaired_bad["coverage"]["state"], "UNVERIFIED")
    self.assertEqual(repaired_bad["status"], "PARTIAL")

    # Repair returning valid disposition completes coverage cleanly
    repair_good = {"status": "ok", "findings": [], "accounted_files": [
      {"target_identity": identity, "file": files[0], "disposition": "skipped"},
    ]}
    repaired_good = self.reduce_with([initial_ok_with_unknown, initial_ok_with_unknown, repair_good],
                                     repair_seat="cc-primary")
    self.assertEqual(repaired_good["coverage"]["counts"], {"total": 4, "reviewed": 3, "skipped": 1, "unaccounted": 0})
    self.assertEqual(repaired_good["coverage"]["state"], "COMPLETE")
    self.assertEqual(repaired_good["status"], "COMPLETE")

  def test_malformed_stdin_and_preparation_and_response_structures_fail_cleanly(self):
    # BUG-13: non-dict stdin JSON, non-dict preparation_path, non-list responses, unhashable disposition, non-dict items
    for raw in ("[]", "null", "123", '"hello"'):
      proc = subprocess.run([sys.executable, str(SCRIPT), "plan"], input=raw, capture_output=True, text=True)
      self.assertEqual(proc.returncode, 1, f"expected exit 1 for stdin={raw}, stderr={proc.stderr}")
      body = json.loads(proc.stdout)
      self.assertEqual(body["status"], "ERROR")
      self.assertIn("INVALID_INPUT_JSON", body["reason_codes"])

    # Non-dict preparation_path JSON must not crash with AttributeError
    bad_prep = Path(self.tmp.name) / "bad-prep.json"
    bad_prep.write_text("[]")
    proc = subprocess.run([sys.executable, str(SCRIPT), "plan"],
                          input=json.dumps({"preparation_path": str(bad_prep), "confirmation": True}),
                          capture_output=True, text=True)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout)["status"], "BLOCKED")

    # Non-list responses in reduce must fail cleanly with JSON error
    proc = subprocess.run([sys.executable, str(SCRIPT), "reduce"],
                          input=json.dumps({"preparation_path": self.finalized["preparation_path"],
                                            "confirmation": True, "selection": selection(), "responses": 123}),
                          capture_output=True, text=True)
    self.assertEqual(proc.returncode, 1, proc.stderr)
    self.assertEqual(json.loads(proc.stdout)["status"], "ERROR")

    # Unhashable disposition (list) and non-dict accounted_files entry must not crash
    identity = self.range_target["target_identity"]
    files = self.range_target["changed_files"]
    unhashable = {"status": "ok", "findings": [], "accounted_files": [
      {"target_identity": identity, "file": files[0], "disposition": ["reviewed"]},
      *({"target_identity": identity, "file": path} for path in files[1:]),
    ]}
    reduced = self.reduce_with([unhashable, unhashable])
    self.assertEqual(reduced["coverage"]["counts"]["unaccounted"], 1)
    self.assertEqual(reduced["coverage"]["state"], "UNVERIFIED")
    self.assertEqual(reduced["status"], "PARTIAL")

    malformed_reply = {"status": "ok", "findings": [], "accounted_files": ["not-a-dict"]}
    reduced_bad = self.reduce_with([malformed_reply, {"status": "ok", "findings": []}])
    self.assertEqual(len(reduced_bad["failed_seats"]), 1)
    self.assertEqual(reduced_bad["status"], "PARTIAL")

  def test_duplicate_missed_files_and_new_interfaces_are_deduplicated(self):
    # BUG-14: both seats reporting identical missed_file and new_interface must not duplicate entries
    current = state(self.tmp.name)
    dup_missed = {"target_identity": SAAS, "file": "src/a.ts"}
    dup_iface = {"interface_id": "bridge", "target_identity": DASH, "description": "dup bridge"}
    recorder = Recorder([
      {"status": "ok", "findings": [], "missed_files": [dup_missed, dup_missed], "new_interfaces": [dup_iface]},
      {"status": "ok", "findings": [], "missed_files": [dup_missed], "new_interfaces": [dup_iface]},
      {"status": "ok", "findings": [], "accounted_files": [], "checks": []},
    ])
    result = self.module.run_group_review({
      "state": current, "selection": selection(), "confirmation": True, "repair_seat": "cc-primary",
    }, recorder)
    repair_call = [c for c in recorder.calls if c["phase"] == "repair"][0]
    self.assertEqual(len(repair_call["missed_files"]), 1)
    self.assertEqual(len(repair_call["new_interfaces"]), 1)
    self.assertEqual(len(result["coverage"]["unverified"]), 1)
    self.assertEqual(len(result["new_interface_checks"]), 1)

  def test_empty_targets_is_blocked_and_never_dispatches(self):
    # BUG-15: READY state with targets=[] must not dispatch reviewers
    empty_state = state(self.tmp.name, targets=[])
    empty_state["targets"] = []
    recorder = Recorder([])
    result = self.module.run_group_review({
      "state": empty_state, "selection": selection(), "confirmation": True,
    }, recorder)
    self.assertEqual(result["status"], "BLOCKED")
    self.assertEqual(len(recorder.calls), 0)

  def test_cross_target_same_filename_accounting_does_not_collide(self):
    # Two range targets sharing the exact same changed filename "shared.ts" stay isolated by target_identity
    t1 = {**self.range_target, "target_identity": SAAS, "changed_files": ["shared.ts"]}
    t2 = {**self.range_target, "target_identity": DASH, "changed_files": ["shared.ts"]}
    st = state(self.tmp.name, targets=[t1, t2])
    recorder = Recorder([
      {"status": "ok", "findings": [], "accounted_files": [
        {"target_identity": SAAS, "file": "shared.ts", "disposition": "reviewed"},
      ]},
      {"status": "ok", "findings": []},
    ])
    result = self.module.run_group_review({
      "state": st, "selection": selection(), "confirmation": True,
    }, recorder)
    self.assertEqual(result["coverage"]["counts"], {"total": 2, "reviewed": 1, "skipped": 0, "unaccounted": 1})
    self.assertEqual([(i["target_identity"], i["file"]) for i in result["coverage"]["unverified"]], [(DASH, "shared.ts")])
    self.assertEqual(result["status"], "PARTIAL")

  def test_interface_check_requires_evidence_and_ledger_rejects_path_traversal(self):
    # Completed interface check without evidence must remain unverified
    checks = self.module.interface_checks(
      [{"interface_id": "bridge", "target_identity": DASH}],
      {"checks": [{"interface_id": "bridge", "status": "completed", "evidence": ""}]},
    )
    self.assertEqual(checks[0]["status"], "unverified")

    # ledger_path must reject traversal or unsafe run_id values
    prep = Path(self.tmp.name) / "prep.json"
    for bad_run_id in ("../escape", "a/b", "..", ".hidden", ""):
      self.assertIsNone(self.module.ledger_path({"run_id": bad_run_id, "preparation_path": str(prep)}))


if __name__ == "__main__":
  unittest.main()
