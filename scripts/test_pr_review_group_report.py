#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("pr-review-group-report.py")
MUTATION_CORE = (
  Path(__file__).resolve().parents[1]
  / "skills/bitbucket-pr-mutation/scripts/bitbucket_pr_workflow/core.py"
)
SAAS_11 = "github:github.com/acme/saas#11"
DASH_707 = "github:github.com/acme/dashboard#707"


def canonical_set_identity(targets):
  joined = "\n".join(sorted(target["target_identity"] for target in targets))
  return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


TARGETS = [
  {"target_identity": SAAS_11, "head": "b" * 40, "base": "c" * 40, "version_state": "current"},
  {"target_identity": DASH_707, "head": "d" * 40, "base": "e" * 40, "version_state": "current"},
]
SET_IDENTITY = canonical_set_identity(TARGETS)


def load_module():
  spec = importlib.util.spec_from_file_location("pr_review_group_report", SCRIPT)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def load_mutation_core():
  spec = importlib.util.spec_from_file_location("bitbucket_pr_workflow_core", MUTATION_CORE)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def run_cli(mode, payload):
  proc = subprocess.run(
    [sys.executable, str(SCRIPT), mode],
    input=json.dumps(payload),
    capture_output=True,
    text=True,
  )
  if mode == "render":
    if not proc.stdout.strip():
      raise AssertionError(f"render produced no stdout; stderr={proc.stderr}")
    return proc.stdout
  return json.loads(proc.stdout)


def finding(target, file, anchor, root_cause, source="cc", line=1, strict_liability=False, **extra):
  return {
    "target_identity": target,
    "file": file,
    "line": line,
    "anchor": anchor,
    "root_cause": root_cause,
    "source": source,
    "strict_liability": strict_liability,
    **extra,
  }


class GroupReportTest(unittest.TestCase):
  def setUp(self):
    self.module = load_module()
    self.mutation = load_mutation_core()
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)

  def reconcile(self, payload):
    merged = {"set_identity": SET_IDENTITY, "targets": TARGETS}
    merged.update(payload)
    return run_cli("reconcile", merged)

  def render(self, payload):
    merged = {"set_identity": SET_IDENTITY, "targets": TARGETS}
    merged.update(payload)
    return run_cli("render", merged)

  def test_dedupe_is_target_qualified_and_chain_id_gated(self):
    no_chain = self.reconcile({"findings": [
      finding(SAAS_11, "src/a.ts", "return value", "missing   guard"),
      finding(DASH_707, "src/a.ts", "return value", "missing guard"),
    ]})
    self.assertEqual(len(no_chain["groups"]), 2)
    self.assertEqual(
      sorted(group["locations"][0]["target_identity"] for group in no_chain["groups"]),
      [DASH_707, SAAS_11],
    )

    chained = self.reconcile({"findings": [
      {**finding(SAAS_11, "src/a.ts", "return value", "missing   guard"), "failure_chain_id": "chain-1"},
      {**finding(DASH_707, "src/a.ts", "return value", "missing guard"), "failure_chain_id": "chain-1"},
    ]})
    self.assertEqual(len(chained["groups"]), 1)
    self.assertEqual(
      sorted(location["target_identity"] for location in chained["groups"][0]["locations"]),
      [DASH_707, SAAS_11],
    )

    divergent_chain = self.reconcize = self.reconcile({"findings": [
      {**finding(SAAS_11, "src/a.ts", "return value", "missing guard"), "failure_chain_id": "chain-2"},
      {**finding(DASH_707, "src/a.ts", "return value", "guard runs after the write"), "failure_chain_id": "chain-2"},
    ]})
    self.assertEqual(len(divergent_chain["groups"]), 2)

    same_target_other_file = self.reconcile({"findings": [
      finding(SAAS_11, "src/a.ts", "return value", "missing guard", source="cc"),
      finding(SAAS_11, "src/other.ts", "return value", "missing guard", source="codex"),
    ]})
    self.assertEqual(len(same_target_other_file["groups"]), 2)
    self.assertEqual(
      sorted(group["locations"][0]["file"] for group in same_target_other_file["groups"]),
      ["src/a.ts", "src/other.ts"],
    )

    divergent = self.reconcile({"findings": [
      finding(SAAS_11, "src/a.ts", "return value", "missing guard"),
      finding(SAAS_11, "src/a.ts", "return value", "guard runs after the write"),
    ]})
    self.assertEqual(len(divergent["groups"]), 2)

  def test_group_uid_extends_legacy_hash_while_single_pr_uid_stays_byte_for_byte(self):
    for cause in ("missing guard", "guard   missing", "spaced  cause "):
      self.assertEqual(
        self.module.single_pr_finding_uid("src/a.ts", "return value", cause),
        self.mutation.make_finding_uid("src/a.ts", "return value", cause),
      )
    self.assertEqual(
      self.module.single_pr_finding_uid("src/a.ts", "return value", "missing guard"),
      "d89f3e4c04c3c406541b",
    )
    legacy = self.module.single_pr_finding_uid("src/a.ts", "return value", "missing guard")
    grouped = self.module.finding_uid("src/a.ts", "return value", "missing guard", SAAS_11)
    self.assertNotEqual(legacy, grouped)
    self.assertEqual(
      grouped,
      hashlib.sha256(
        "\0".join((SAAS_11, "src/a.ts", "return value", "missing guard")).encode("utf-8")
      ).hexdigest()[:20],
    )

  def test_routing_follows_existing_rules_without_copying_a_seat_per_repo(self):
    mixed = self.reconcile({"findings": [
      {**finding(SAAS_11, "src/a.ts", "return value", "missing guard", source="cc"),
       "failure_chain_id": "chain-x", "suggestion": "Must Fix", "action": "auto-fix",
       "action_reason": "修法明確", "comment": "cc 的修法"},
      {**finding(DASH_707, "src/a.ts", "return value", "missing guard", source="codex"),
       "failure_chain_id": "chain-x", "suggestion": "Should Fix", "action": "ask-user",
       "action_reason": "涉及取捨", "comment": "codex 的修法"},
    ]})
    self.assertEqual(mixed["groups"][0]["routed_to"], "baseline_check")
    self.assertEqual(len(mixed["groups"]), 1)
    self.assertEqual(sorted(mixed["groups"][0]["sources"]), ["cc", "codex"])

    perspectives = mixed["groups"][0]["perspectives"]
    self.assertEqual(len(perspectives), 2)
    by_source = {item["source"]: item for item in perspectives}
    self.assertEqual(by_source["cc"]["suggestion"], "Must Fix")
    self.assertEqual(by_source["cc"]["action"], "auto-fix")
    self.assertEqual(by_source["cc"]["comment"], "cc 的修法")
    self.assertEqual(by_source["codex"]["suggestion"], "Should Fix")
    self.assertEqual(by_source["codex"]["action"], "ask-user")
    self.assertEqual(by_source["codex"]["comment"], "codex 的修法")

    rendered = self.render({"findings": [
      {**finding(SAAS_11, "src/a.ts", "return value", "missing guard", source="cc"),
       "failure_chain_id": "chain-x", "suggestion": "Must Fix", "action": "auto-fix",
       "action_reason": "修法明確", "comment": "cc 的修法"},
      {**finding(DASH_707, "src/a.ts", "return value", "missing guard", source="codex"),
       "failure_chain_id": "chain-x", "suggestion": "Should Fix", "action": "ask-user",
       "action_reason": "涉及取捨", "comment": "codex 的修法"},
    ]})
    self.assertIn("## 來源與分歧", rendered)
    self.assertIn("cc 的修法", rendered)
    self.assertIn("codex 的修法", rendered)
    self.assertIn("Should Fix", rendered)

    section = rendered.split("## 來源與分歧")[1].split("## 發現總覽")[0]
    expected_uids = {SAAS_11: "52ee6bbc502eb02eb880", DASH_707: "ceaa505148b2f2e34379"}
    checked = 0
    for line in section.splitlines():
      if not line.startswith("|") or "finding_uid" in line or "---" in line:
        continue
      uid, target = [cell.strip() for cell in line.strip("|").split("|")][:2]
      self.assertEqual(uid, expected_uids[target])
      checked += 1
    self.assertEqual(checked, 2)

    cc_only = self.reconcile({"findings": [
      finding(SAAS_11, "src/a.ts", "return value", "missing guard", source="cc"),
    ]})
    self.assertEqual(cc_only["groups"][0]["routed_to"], "independent_recheck")

    secret = self.reconcile({"findings": [
      finding(SAAS_11, "src/a.ts", "const apiKey = 'x'", "hardcoded secret", strict_liability=True),
    ]})
    self.assertEqual(secret["groups"][0]["routed_to"], "stand")

    unvalidated = self.reconcile({"findings": [
      finding(SAAS_11, "src/a.ts", "return value", "spec clause breach", source="spec-compliance"),
    ]})
    self.assertEqual(unvalidated["groups"], [])
    self.assertEqual(
      [entry["reason_code"] for entry in unvalidated["refused"]],
      ["C4_NOT_VALIDATED"],
    )
    validated = self.reconcile({"findings": [
      {**finding(SAAS_11, "src/a.ts", "return value", "spec clause breach", source="spec-compliance"),
       "reducer_validated": True},
    ]})
    self.assertEqual(validated["groups"][0]["routed_to"], "independent_recheck")

    undeclared = self.reconcile({"findings": [
      finding("github:github.com/acme/saas#99", "src/x.ts", "anchor", "cause"),
    ]})
    self.assertEqual(
      [entry["reason_code"] for entry in undeclared["refused"]],
      ["UNDECLARED_TARGET"],
    )

  def source_rows(self, rendered):
    section = rendered.split("## 來源與分歧")[1].split("## 發現總覽")[0]
    rows = []
    for line in section.splitlines():
      if not line.startswith("|") or "finding_uid" in line or "---" in line:
        continue
      rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows

  def test_same_repo_two_locations_bind_each_source_row_to_its_own_location_uid(self):
    rendered = self.render({"findings": [
      {**finding(SAAS_11, "src/api/generated/types.gen.ts", "ownRecentHistory", "missing field",
                 source="codex", line=1089), "failure_chain_id": "chain-own"},
      {**finding(SAAS_11, "src/statusReasons.ts", "ownRecentHistory", "missing field",
                 source="cc", line=156), "failure_chain_id": "chain-own"},
    ]})
    expected = {
      "codex": self.module.finding_uid("src/api/generated/types.gen.ts", "ownRecentHistory",
                                       "missing field", SAAS_11),
      "cc": self.module.finding_uid("src/statusReasons.ts", "ownRecentHistory",
                                    "missing field", SAAS_11),
    }
    self.assertNotEqual(expected["codex"], expected["cc"])
    rows = self.source_rows(rendered)
    self.assertEqual(len(rows), 2)
    self.assertEqual({row[2]: row[0] for row in rows}, expected)

  def test_single_location_group_source_rows_keep_their_existing_bytes(self):
    rendered = self.render({"findings": [
      {**finding(SAAS_11, "src/a.ts", "return value", "missing guard", source="cc"),
       "suggestion": "Must Fix", "action": "auto-fix", "action_reason": "修法明確", "comment": "cc 的修法"},
      {**finding(SAAS_11, "src/a.ts", "return value", "missing guard", source="codex"),
       "suggestion": "Should Fix", "action": "ask-user", "action_reason": "涉及取捨", "comment": "codex 的修法"},
    ]})
    section = rendered.split("## 來源與分歧")[1].split("## 發現總覽")[0]
    self.assertIn(
      f"| 52ee6bbc502eb02eb880 | {SAAS_11} | cc |  |  |  |  |  | Must Fix | `auto-fix` | 修法明確 | cc 的修法 |",
      section,
    )
    self.assertIn(
      f"| 52ee6bbc502eb02eb880 | {SAAS_11} | codex |  |  |  |  |  | Should Fix | `ask-user` | 涉及取捨 | codex 的修法 |",
      section,
    )

  def test_verification_and_severity_corrections_survive_group_routing_and_rendering(self):
    findings = [
      finding(
        SAAS_11,
        "src/a.ts",
        "return value",
        "missing guard",
        source="cc",
        severity="HIGH",
        codex_verdict="REFUTED",
        codex_evidence="src/guard.ts:9 already rejects it",
        corrected_severity="LOW",
        severity_reason="framework guard limits the impact",
      ),
      finding(
        DASH_707,
        "src/b.ts",
        "return result",
        "missing result check",
        source="codex",
        severity="MEDIUM",
        cc_verdict="CONFIRMED",
        cc_evidence="src/b.ts:21 has no upstream check",
        corrected_severity="HIGH",
        severity_reason="state corruption reaches persistence",
      ),
    ]

    reconciled = self.reconcile({"findings": findings})
    perspectives = {
      item["source"]: item
      for group in reconciled["groups"]
      for item in group["perspectives"]
    }
    self.assertEqual(perspectives["cc"]["verification_verdict"], "REFUTED")
    self.assertEqual(
      perspectives["cc"]["verification_evidence"],
      "src/guard.ts:9 already rejects it",
    )
    self.assertEqual(perspectives["cc"]["original_severity"], "HIGH")
    self.assertEqual(perspectives["cc"]["corrected_severity"], "LOW")
    self.assertEqual(
      perspectives["cc"]["severity_reason"],
      "framework guard limits the impact",
    )
    self.assertEqual(perspectives["codex"]["verification_verdict"], "CONFIRMED")
    self.assertEqual(
      perspectives["codex"]["verification_evidence"],
      "src/b.ts:21 has no upstream check",
    )

    rendered = self.render({"findings": findings})
    self.assertIn("| 驗證裁決 | 驗證證據 | 原始 severity | 校正 severity | severity 理由 |", rendered)
    self.assertIn("src/guard.ts:9 already rejects it", rendered)
    self.assertIn("framework guard limits the impact", rendered)
    self.assertIn("src/b.ts:21 has no upstream check", rendered)
    self.assertIn("state corruption reaches persistence", rendered)

  def test_render_emits_schema_three_markdown_with_set_and_target_binding(self):
    rendered = self.render({"findings": [
      {**finding(SAAS_11, "src/a.ts", "return value", "missing guard", source="cc",
                 suggestion="Must Fix", action="auto-fix", action_reason="修法明確"),
       "failure_chain_id": "chain-render"},
      finding(DASH_707, "src/a.ts", "return value", "missing guard", source="codex",
              failure_chain_id="chain-render"),
    ]})
    self.assertEqual(rendered.count("**Report projection schema**: 3"), 1)
    self.assertIn("**Review set identity**: " + SET_IDENTITY, rendered)
    self.assertIn(SAAS_11, rendered)
    self.assertIn(DASH_707, rendered)
    self.assertIn("## 跨目標位置", rendered)
    self.assertIn("| group_id | finding_uid | target_identity | file | line | source |", rendered)
    self.assertIn("52ee6bbc502eb02eb880", rendered)
    self.assertIn("ceaa505148b2f2e34379", rendered)
    self.assertIn("F-01 finding_uid: ", rendered)
    self.assertIn("| # | 問題 | 最終建議 | Action | Action 理由 |", rendered)
    self.assertNotIn('{"set_identity"', rendered)

    reconciled = self.reconcile({"findings": [
      {**finding(SAAS_11, "src/a.ts", "return value", "missing guard"), "failure_chain_id": "chain-render"},
      {**finding(DASH_707, "src/a.ts", "return value", "missing guard"), "failure_chain_id": "chain-render"},
    ]})
    self.assertEqual(len(reconciled["groups"]), 1)
    location_uids = sorted(
      location["finding_uid"] for location in reconciled["groups"][0]["locations"]
    )
    self.assertEqual(location_uids, ["52ee6bbc502eb02eb880", "ceaa505148b2f2e34379"])
    group_id = reconciled["groups"][0]["group_id"]
    self.assertNotIn(group_id, location_uids)
    self.assertIn(f"F-01 finding_uid: {group_id} action=", rendered)

  def test_history_pairs_by_target_identity_and_never_auto_resolves(self):
    prior = {
      "set_identity": SET_IDENTITY,
      "findings": [
        {"target_identity": SAAS_11, "file": "src/a.ts", "anchor": "return value",
         "root_cause": "missing   guard", "action": "auto-fix", "finding_uid": "d89f3e4c04c3c406541b"},
        {"target_identity": DASH_707, "file": "src/b.ts", "anchor": "return x",
         "root_cause": "guard dropped", "action": "no-op", "finding_uid": "0" * 20},
        {"target_identity": "github:github.com/acme/saas#99", "file": "src/c.ts",
         "anchor": "return y", "root_cause": "gone target", "action": "ask-user",
         "finding_uid": "1" * 20},
      ],
    }
    group_uid = self.module.finding_uid("src/a.ts", "return value", "missing guard", SAAS_11)
    result = self.reconcile({
      "prior_report": prior,
      "recheck_responses": {
        group_uid: {"status": "STILL_OPEN", "evidence": "src/a.ts:12 still returns early"},
      },
      "findings": [finding(SAAS_11, "src/a.ts", "return value", "missing guard")],
    })
    history = result["history"]
    rows = {row["target_identity"]: row for row in history["rows"]}
    self.assertEqual(history["continuity"], "checked")
    self.assertEqual(rows[SAAS_11]["status"], "STILL_OPEN")
    self.assertTrue(rows[SAAS_11]["rediscovered"])
    self.assertEqual(rows[SAAS_11]["finding_uid"], group_uid)
    self.assertEqual(rows[SAAS_11]["legacy_uid"], "d89f3e4c04c3c406541b")
    self.assertNotIn(DASH_707, rows)
    self.assertEqual(rows["github:github.com/acme/saas#99"]["status"], "STALE")
    self.assertEqual(rows["github:github.com/acme/saas#99"]["finding_uid"], "1" * 20)
    self.assertEqual(history["tally"]["STILL_OPEN"], 1)
    self.assertEqual(history["tally"]["STALE"], 1)
    self.assertEqual(history["tally"]["FIXED"], 0)
    self.assertEqual(history["prior_inputs"], [])
    self.assertEqual(history["expanded_targets"], [])

    missing_evidence = self.reconcize_if = self.reconcile({"prior_report": prior, "findings": []})
    statuses = {row["target_identity"]: row["status"] for row in missing_evidence["history"]["rows"]}
    self.assertEqual(statuses[SAAS_11], "STALE")
    self.assertEqual(missing_evidence["history"]["tally"]["FIXED"], 0)

    fixed_without_evidence = self.reconcile({
      "prior_report": prior,
      "recheck_responses": {group_uid: {"status": "FIXED", "evidence": ""}},
      "findings": [],
    })
    fixed_row = {row["target_identity"]: row for row in fixed_without_evidence["history"]["rows"]}[SAAS_11]
    self.assertEqual(fixed_row["status"], "STALE")

    legacy = self.reconcile({"prior_report": {"findings": prior["findings"][:1]}})
    legacy_row = legacy["history"]["rows"][0]
    self.assertEqual(legacy["history"]["scope"], "legacy")
    self.assertEqual(legacy_row["legacy_uid"], "d89f3e4c04c3c406541b")

    stale_set = self.reconcile({"prior_report": {"set_identity": "sha256:" + "b2" * 32,
                                                 "findings": prior["findings"][:1]}})
    self.assertEqual(stale_set["history"]["scope"], "stale-set")
    self.assertEqual(stale_set["history"]["rows"][0]["status"], "STALE")

    unloadable = self.reconcile({"prior_report": {
      "findings": [{"target_identity": SAAS_11, "file": "src/a.ts", "action": "auto-fix"}],
    }})
    self.assertEqual(unloadable["history"]["continuity"], "skipped")

  def test_version_drift_and_incomplete_targets_only_change_evidence_state(self):
    drifted = self.reconcile({
      "targets": [
        {"target_identity": SAAS_11, "head": "e" * 40, "base": "c" * 40, "version_state": "drifted"},
        {"target_identity": DASH_707, "head": "d" * 40, "base": "e" * 40, "version_state": "current"},
      ],
      "findings": [finding(SAAS_11, "src/a.ts", "return value", "missing guard")],
    })
    self.assertEqual(drifted["groups"][0]["locations"][0]["finding_uid"], "52ee6bbc502eb02eb880")
    self.assertEqual(drifted["completeness"], "COMPLETE")
    self.assertEqual(
      {target["target_identity"]: target["version_state"] for target in drifted["targets"]},
      {SAAS_11: "drifted", DASH_707: "current"},
    )

    incomplete = self.reconcile({
      "targets": [
        {"target_identity": SAAS_11, "head": "b" * 40, "base": "c" * 40, "version_state": "current"},
        {"target_identity": DASH_707, "head": None, "base": None, "version_state": "unavailable"},
      ],
      "findings": [],
    })
    self.assertEqual(incomplete["completeness"], "INCOMPLETE")
    self.assertEqual(incomplete["incomplete_targets"], [DASH_707])
    self.assertEqual(incomplete["groups"], [])

  def test_report_grants_no_write_authority_and_cleanup_spares_kept_and_other_runs(self):
    result = self.reconcile({"findings": [
      finding(SAAS_11, "src/a.ts", "return value", "missing guard"),
    ]})
    self.assertFalse(result["grants"]["modify_code"])
    self.assertFalse(result["grants"]["comment_on_prs"])
    self.assertFalse(result["grants"]["multi_target_fanout"])

    state_root = Path(self.tmp.name) / "state"
    run_root = state_root / "materials" / "run-01"
    run_root.mkdir(parents=True)
    (run_root / "spec-1.md").write_text("spec\n")
    (run_root / "user-copy.md").write_text("user asked to keep\n")
    other_run = state_root / "materials" / "run-02"
    other_run.mkdir(parents=True)
    (other_run / "spec-2.md").write_text("other run\n")

    kept = run_cli("cleanup", {
      "state_root": str(state_root), "run_id": "run-01", "keep": ["user-copy.md"],
    })
    self.assertEqual(kept["reason_codes"], ["MATERIALS_PARTIALLY_RETAINED"])
    self.assertEqual(kept["kept"], ["user-copy.md"])
    self.assertFalse((run_root / "spec-1.md").exists())
    self.assertTrue((run_root / "user-copy.md").is_file())
    self.assertTrue((other_run / "spec-2.md").is_file())

    outside = run_cli("cleanup", {
      "state_root": str(state_root), "run_id": "run-01", "run_root": str(Path(self.tmp.name)),
    })
    self.assertEqual(outside["reason_codes"], ["CLEANUP_ROOT_OUT_OF_SCOPE"])
    self.assertEqual(outside["removed"], [])
    self.assertTrue((other_run / "spec-2.md").is_file())
    self.assertTrue((run_root / "user-copy.md").is_file())

    missing = run_cli("cleanup", {"state_root": str(state_root), "run_id": "run-99"})
    self.assertEqual(missing["reason_codes"], ["CLEANUP_NOT_FOUND"])

    unsafe = run_cli("cleanup", {"state_root": str(state_root), "run_id": "../escape"})
    self.assertEqual(unsafe["reason_codes"], ["CLEANUP_NOT_FOUND"])

    (run_root / "user-copy.md").unlink()
    cleared = run_cli("cleanup", {"state_root": str(state_root), "run_id": "run-01"})
    self.assertEqual(cleared["reason_codes"], [])
    self.assertFalse(run_root.exists())
    self.assertTrue((other_run / "spec-2.md").is_file())

    escape_root = state_root / "materials"
    (escape_root / "spec-outer.md").write_text("outer\n")
    escape = run_cli("cleanup", {"state_root": str(state_root), "run_id": ".."})
    self.assertEqual(escape["reason_codes"], ["CLEANUP_NOT_FOUND"])
    self.assertEqual(escape["removed"], [])
    self.assertTrue((escape_root / "spec-outer.md").is_file())
    self.assertTrue((other_run / "spec-2.md").is_file())

    dotted = run_cli("cleanup", {"state_root": str(state_root), "run_id": "abc..def"})
    self.assertEqual(dotted["reason_codes"], ["CLEANUP_NOT_FOUND"])
    self.assertEqual(dotted["removed"], [])
    self.assertTrue((escape_root / "spec-outer.md").is_file())
    self.assertTrue((other_run / "spec-2.md").is_file())

    (state_root / "materials" / "run-link").symlink_to(other_run)
    (other_run / "sentinel.md").write_text("keep\n")
    linked = run_cli("cleanup", {"state_root": str(state_root), "run_id": "run-link"})
    self.assertEqual(linked["removed"], [])
    self.assertEqual(linked["reason_codes"], ["CLEANUP_ROOT_OUT_OF_SCOPE"])
    self.assertTrue((other_run / "sentinel.md").is_file())
    self.assertTrue((other_run / "spec-2.md").is_file())

    outside = state_root / "outside"
    outside.mkdir()
    (outside / "precious.md").write_text("precious\n")
    (state_root / "materials" / "run-external-link").symlink_to(outside)
    linked = run_cli("cleanup", {"state_root": str(state_root), "run_id": "run-external-link"})
    self.assertEqual(linked["removed"], [])
    self.assertEqual(linked["reason_codes"], ["CLEANUP_ROOT_OUT_OF_SCOPE"])
    self.assertTrue((outside / "precious.md").is_file())

    (state_root / "materials" / "run-03").mkdir()
    (state_root / "materials" / "run-03" / "spec-3.md").write_text("three\n")
    tampered = run_cli("cleanup", {
      "state_root": str(state_root), "run_id": "run-01", "run_root": str(other_run),
    })
    self.assertEqual(tampered["reason_codes"], ["CLEANUP_ROOT_OUT_OF_SCOPE"])
    self.assertEqual(tampered["removed"], [])
    self.assertTrue((other_run / "spec-2.md").is_file())


SAAS_RANGE = "range:github:github.com/acme/saas@stage"
DASH_RANGE = "range:github:github.com/acme/dashboard@stage"
SAAS_R = "1" * 40
SAAS_T = "2" * 40
DASH_R = "3" * 40
DASH_T = "4" * 40
COMMIT_A = "a1" * 20
COMMIT_B = "b2" * 20


def range_target(identity, repo, prs, start, end, source="since", detail=None, entry_files=None):
  return {
    "kind": "range",
    "target_identity": identity,
    "platform": "github",
    "host": "github.com",
    "destination_repo": repo,
    "target_branch": "stage",
    "start": {"sha": start, "source": source, "detail": detail or f"--since {start}"},
    "end": {"sha": end, "ref": "refs/remotes/origin/stage"},
    "related_prs": [
      {"target_identity": f"github:github.com/{repo}#{pr}", "pr": pr, "author": "alice",
       "base_ref": "stage", "merge_commit": "9" * 40}
      for pr in prs
    ],
    "entry_files": entry_files if entry_files is not None else [{"path": "src/a.ts", "status": "modified"}],
    "review_diff": {"bytes": 10, "lines": 2},
  }


def range_payload(targets=None, no_net_diff=None, findings=None, **extra):
  return {
    "targets": targets if targets is not None else [
      range_target(SAAS_RANGE, "acme/saas", [11, 12], SAAS_R, SAAS_T),
      range_target(DASH_RANGE, "acme/dashboard", [707], DASH_R, DASH_T,
                   source="earliest-merge-first-parent", detail="first parent of the earliest merge (PR 707)"),
    ],
    "no_net_diff": no_net_diff or [],
    "findings": findings or [],
    **extra,
  }


def section_of(rendered, title):
  return rendered.split(f"## {title}")[1].split("\n## ")[0]


class RangeReportTest(unittest.TestCase):
  def test_range_case_identity_is_distinct_and_survives_end_advancing(self):
    result = run_cli("reconcile", range_payload())
    self.assertEqual(result["status"], "OK")
    self.assertEqual(result["mode"], "merged-range")
    tokens = sorted([
      f"{SAAS_RANGE}+prs:11,12+scope:{result['scope_rule']}",
      f"{DASH_RANGE}+prs:707+scope:{result['scope_rule']}",
    ])
    expected = "sha256:" + hashlib.sha256("\n".join(tokens).encode("utf-8")).hexdigest()
    self.assertEqual(result["set_identity"], expected)
    self.assertEqual(result["stable_id"], expected[7:19])
    self.assertEqual(result["report_stem"], f"set-{expected[7:19]}-review")

    pr_set = canonical_set_identity([
      {"target_identity": "github:github.com/acme/saas#11"},
      {"target_identity": "github:github.com/acme/saas#12"},
      {"target_identity": "github:github.com/acme/dashboard#707"},
    ])
    self.assertNotEqual(result["set_identity"], pr_set)
    self.assertNotEqual(result["report_stem"], f"set-{pr_set[7:19]}-review")
    self.assertNotEqual(result["report_stem"], "pr-11-review")
    self.assertNotEqual(result["set_identity"], canonical_set_identity(
      [{"target_identity": SAAS_RANGE}, {"target_identity": DASH_RANGE}]))

    advanced = run_cli("reconcile", range_payload(targets=[
      range_target(SAAS_RANGE, "acme/saas", [12, 11], SAAS_R, "5" * 40),
      range_target(DASH_RANGE, "acme/dashboard", [707], "6" * 40, DASH_T,
                   entry_files=[{"path": "src/b.ts", "status": "added"}]),
    ]))
    self.assertEqual(advanced["set_identity"], result["set_identity"])
    self.assertEqual(advanced["report_stem"], result["report_stem"])
    runs = {target["target_identity"]: target for target in result["targets"]}
    advanced_runs = {target["target_identity"]: target for target in advanced["targets"]}
    self.assertNotEqual(runs[SAAS_RANGE]["head"], advanced_runs[SAAS_RANGE]["head"])
    for run in (*runs.values(), *advanced_runs.values()):
      self.assertEqual([], [key for key in run if "sha256" in key])

    other_prs = run_cli("reconcile", range_payload(targets=[
      range_target(SAAS_RANGE, "acme/saas", [11], SAAS_R, SAAS_T),
      range_target(DASH_RANGE, "acme/dashboard", [707], DASH_R, DASH_T),
    ]))
    self.assertNotEqual(other_prs["set_identity"], result["set_identity"])

    mixed = run_cli("reconcile", {**range_payload(), "targets": [
      range_target(SAAS_RANGE, "acme/saas", [11], SAAS_R, SAAS_T), TARGETS[0],
    ]})
    self.assertEqual(mixed["status"], "ERROR")

  def test_range_header_carries_mode_and_full_start_end_and_start_source(self):
    rendered = run_cli("render", range_payload(findings=[
      finding(SAAS_RANGE, "src/a.ts", "return value", "missing guard", suggestion="Must Fix",
              action="auto-fix", action_reason="修法明確"),
    ]))
    header = rendered.split("\n## ")[0]
    self.assertIn("**Review mode**: merged-range", header)
    self.assertIn(f"{SAAS_RANGE}=R:{SAAS_R}|T:{SAAS_T}|T-ref:refs/remotes/origin/stage", header)
    self.assertIn(f"{DASH_RANGE}=R:{DASH_R}|T:{DASH_T}|T-ref:refs/remotes/origin/stage", header)
    self.assertIn(f"{SAAS_RANGE}=since（--since {SAAS_R}）", header)
    self.assertIn(f"{DASH_RANGE}=earliest-merge-first-parent（first parent of the earliest merge (PR 707)）", header)
    scope_line = next(line for line in header.splitlines() if line.startswith("**Range scope**"))
    self.assertIn(f"{SAAS_RANGE}=prs:#11,#12|entry-files:1|net-diff:yes", scope_line)
    self.assertNotIn("sha256", scope_line)

  def test_every_range_finding_renders_three_attribution_columns_listing_every_pr(self):
    payload = range_payload(findings=[
      finding(SAAS_RANGE, "src/a.ts", "return value", "guard runs after the write", line=40,
              code_source=[{"commit": COMMIT_A, "prs": [
                {"pr": 11, "author": "alice", "base_ref": "stage"},
                {"pr": 12, "author": "bob", "base_ref": "stage"},
              ]}],
              introduction={"status": "confirmed", "commit": COMMIT_A, "pr": 12,
                            "evidence": "PR 12 moved the guard below the write"}),
    ])
    location = run_cli("reconcile", payload)["groups"][0]["locations"][0]
    attribution = location["attribution"]
    self.assertEqual(attribution["current_location"], {"file": "src/a.ts", "line": 40, "commit": SAAS_T})
    self.assertEqual([pr["pr"] for pr in attribution["code_source"][0]["prs"]], [11, 12])
    self.assertEqual(attribution["introduction"]["status"], "confirmed")
    self.assertEqual(attribution["introduction"]["pr"], 12)

    rendered = run_cli("render", payload)
    section = section_of(rendered, "歸因三欄")
    self.assertIn("| finding_uid | target_identity | 目前問題位置 | 相關程式來源 | 缺陷引入歸因 |", section)
    row = [line for line in section.splitlines() if location["finding_uid"] in line]
    self.assertEqual(len(row), 1)
    self.assertIn("src/a.ts:40", row[0])
    self.assertIn("#11 @alice", row[0])
    self.assertIn("#12 @bob", row[0])
    self.assertIn("已確認", row[0])

  def test_missing_type_finding_never_names_a_responsible_author_or_changes_the_recommendation(self):
    def missing(author):
      return finding(SAAS_RANGE, "src/a.ts", "export function save", "no rate limit on save",
                     suggestion="Should Fix", action="ask-user", action_reason="涉及取捨",
                     missing=True,
                     code_source=[{"commit": COMMIT_B, "prs": [{"pr": 11, "author": author}]}],
                     introduction={"status": "confirmed", "commit": COMMIT_B, "pr": 11, "author": author})

    first = run_cli("reconcile", range_payload(findings=[missing("carol")]))
    second = run_cli("reconcile", range_payload(findings=[missing("dave")]))
    attribution = first["groups"][0]["locations"][0]["attribution"]
    self.assertEqual(attribution["introduction"]["status"], "unconfirmed")
    self.assertNotIn("carol", json.dumps(attribution["introduction"], ensure_ascii=False))
    self.assertEqual(attribution["code_source"][0]["prs"][0]["author"], "carol")
    for field in ("group_id", "suggestion", "action", "action_reason", "routed_to"):
      self.assertEqual(first["groups"][0][field], second["groups"][0][field])
    self.assertEqual(first["groups"][0]["locations"][0]["finding_uid"],
                     second["groups"][0]["locations"][0]["finding_uid"])

    rendered = run_cli("render", range_payload(findings=[missing("carol")]))
    row = section_of(rendered, "歸因三欄")
    cells = [cell.strip() for cell in row.split("|")]
    self.assertIn(f"附近程式，僅供定位：{COMMIT_B[:12]} → #11 @carol", cells)
    self.assertIn("未確認", cells[-2])
    self.assertNotIn("carol", cells[-2])

  def test_deleted_code_finding_keeps_start_side_evidence_and_marks_end_side_impact(self):
    payload = range_payload(findings=[
      finding(SAAS_RANGE, "src/caller.ts", "validate(input)", "validation module was deleted", line=8,
              r_evidence={"file": "src/validate.ts", "line": 3}),
    ])
    attribution = run_cli("reconcile", payload)["groups"][0]["locations"][0]["attribution"]
    self.assertEqual(attribution["current_location"]["r_evidence"],
                     {"file": "src/validate.ts", "line": 3, "commit": SAAS_R})
    row = section_of(run_cli("render", payload), "歸因三欄")
    self.assertIn("src/caller.ts:8", row)
    self.assertIn(f"src/validate.ts:3 @ {SAAS_R}", row)

  def test_code_source_pr_on_another_branch_is_marked(self):
    payload = range_payload(findings=[
      finding(SAAS_RANGE, "src/a.ts", "return value", "missing guard",
              code_source=[{"commit": COMMIT_A, "prs": [
                {"pr": 11, "author": "alice", "base_ref": "stage"},
                {"pr": 30, "author": "erin", "base_ref": "hotfix"},
              ]}]),
    ])
    prs = run_cli("reconcile", payload)["groups"][0]["locations"][0]["attribution"]["code_source"][0]["prs"]
    self.assertEqual([pr.get("target_branch_match") for pr in prs], [True, False])
    row = section_of(run_cli("render", payload), "歸因三欄")
    self.assertIn("#30 @erin（目的分支不符）", row)
    self.assertNotIn("#11 @alice（目的分支不符）", row)

  def test_confirmed_introduction_without_full_commit_is_downgraded(self):
    payload = range_payload(findings=[
      finding(SAAS_RANGE, "src/a.ts", "return value", "missing guard",
              introduction={"status": "confirmed", "commit": "abc123", "pr": 11}),
    ])
    introduction = run_cli("reconcile", payload)["groups"][0]["locations"][0]["attribution"]["introduction"]
    self.assertEqual(introduction["status"], "unconfirmed")

  def test_prior_open_findings_are_reconciled_even_for_a_repo_without_net_diff(self):
    base = run_cli("reconcile", range_payload())
    dash_no_diff = {key: value for key, value in range_target(
      DASH_RANGE, "acme/dashboard", [707], DASH_R, DASH_T, entry_files=[]).items()
      if key not in ("kind", "review_diff")}
    dash_no_diff["status"] = "no-net-diff"
    prior = {"set_identity": base["set_identity"], "findings": [
      {"target_identity": DASH_RANGE, "file": "src/b.ts", "anchor": "return x", "root_cause": "stale total",
       "action": "auto-fix", "finding_uid": "2" * 20},
      {"target_identity": SAAS_RANGE, "file": "src/a.ts", "anchor": "return y", "root_cause": "leak",
       "action": "ask-user", "finding_uid": "3" * 20},
    ]}
    load = load_module()
    dash_uid = load.finding_uid("src/b.ts", "return x", "stale total", DASH_RANGE)
    result = run_cli("reconcile", range_payload(
      targets=[range_target(SAAS_RANGE, "acme/saas", [11, 12], SAAS_R, SAAS_T)],
      no_net_diff=[dash_no_diff], prior_report=prior,
      recheck_responses={dash_uid: {"status": "STILL_OPEN", "evidence": "src/b.ts:4 unchanged at T"}},
    ))
    self.assertEqual(result["set_identity"], base["set_identity"])
    history = result["history"]
    self.assertEqual(history["scope"], "set")
    rows = {row["target_identity"]: row for row in history["rows"]}
    self.assertEqual(rows[DASH_RANGE]["status"], "STILL_OPEN")
    self.assertEqual(rows[SAAS_RANGE]["status"], "STALE")
    self.assertEqual(rows[SAAS_RANGE]["evidence"], "no independent recheck evidence")

    rendered = run_cli("render", range_payload(
      targets=[range_target(SAAS_RANGE, "acme/saas", [11, 12], SAAS_R, SAAS_T)],
      no_net_diff=[dash_no_diff], prior_report=prior,
      recheck_responses={dash_uid: {"status": "STILL_OPEN", "evidence": "src/b.ts:4 unchanged at T"}},
    ))
    continuity = section_of(rendered, "上一輪 findings 對帳")
    self.assertIn(dash_uid, continuity)
    self.assertIn("STILL_OPEN", continuity)
    self.assertIn("net-diff:no", rendered.split("\n## ")[0])


if __name__ == "__main__":
  unittest.main()