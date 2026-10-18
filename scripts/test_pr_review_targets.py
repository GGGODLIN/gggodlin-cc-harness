#!/usr/bin/env python3

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("pr-review-targets.py")
SAAS_REMOTE = "https://github.com/acme/saas.git"
DASH_REMOTE = "https://github.com/acme/dashboard.git"
SPEC_SHARED = "SHARED-SPEC\nline two\n"
SPEC_PRIVATE = "SAAS-ONLY-SPEC\n"
ROW_KEYS = {"seat", "angle", "primary_material", "extra_context", "shared_bytes"}


def git(root, *args):
  proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
  if proc.returncode != 0:
    raise AssertionError(f"git {' '.join(args)} in {root} failed: {proc.stderr}")
  return proc.stdout.strip()


def run_cli(mode, payload):
  proc = subprocess.run(
    [sys.executable, str(SCRIPT), mode],
    input=json.dumps(payload),
    capture_output=True,
    text=True,
  )
  if not proc.stdout.strip():
    raise AssertionError(f"{mode} produced no stdout; stderr={proc.stderr}")
  return json.loads(proc.stdout)


class Fixture:
  def __init__(self, base):
    self.base = Path(base)
    self.checkouts = self.base / "checkouts"
    self.state_root = self.base / "state"
    self.saas = self.checkouts / "saas"
    self.dashboard = self.checkouts / "dashboard"
    self.checkouts.mkdir(parents=True)
    self.commits = {}
    self._build_saas()
    self._build_dashboard()
    self.profile = self.base / "repos.yaml"
    self.profile.write_text("")

  def _commit(self, repo, name, content):
    (repo / name).write_text(content)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)
    return git(repo, "rev-parse", "HEAD")

  def _init(self, repo, remote):
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/master")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "remote", "add", "origin", remote)

  def _build_saas(self):
    self._init(self.saas, SAAS_REMOTE)
    self.commits["saas_a"] = self._commit(self.saas, "a.txt", "a\n")
    git(self.saas, "checkout", "-q", "-b", "preprod")
    self.commits["saas_b"] = self._commit(self.saas, "b.txt", "b\n")
    git(self.saas, "checkout", "-q", "master")
    git(self.saas, "checkout", "-q", "-b", "feat1")
    self.commits["saas_c"] = self._commit(self.saas, "c.txt", "c\n")
    for name, ref in (("master", "saas_a"), ("preprod", "saas_b"), ("feat1", "saas_c")):
      git(self.saas, "update-ref", f"refs/remotes/origin/{name}", self.commits[ref])
    git(self.saas, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")

  def _build_dashboard(self):
    self._init(self.dashboard, DASH_REMOTE)
    self.commits["dash_a"] = self._commit(self.dashboard, "a.txt", "a\n")
    git(self.dashboard, "update-ref", "refs/remotes/origin/master", self.commits["dash_a"])
    git(self.dashboard, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")

  def platform_ok(self, repo, head, base_ref, base, files, diff_lines, specs, head_ref="feat1", extra=None):
    response = {
      "status": "ok",
      "destination_repo": repo,
      "source_repo": repo,
      "head": head,
      "head_ref": head_ref,
      "base_ref": base_ref,
      "base": base,
      "changed_files": files,
      "diff_lines": diff_lines,
      "specs": specs,
    }
    if extra:
      response.update(extra)
    return response

  def payload(self, inputs, platform, run_id="run-01"):
    return {
      "run_id": run_id,
      "state_root": str(self.state_root),
      "profile_path": str(self.profile),
      "inputs": inputs,
      "current_repo": {"remote": SAAS_REMOTE},
      "repos": {
        "acme/saas": {"checkout": str(self.saas), "remote": SAAS_REMOTE},
        "acme/dashboard": {"checkout": str(self.dashboard), "remote": DASH_REMOTE},
      },
      "platform": platform,
    }

  def inputs_11_12(self):
    return [
      {"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True},
      {"raw": "https://github.com/acme/saas/pull/12", "named_in_conversation": True},
    ]

  def saas_pair_platform(self):
    return {
      "github.com/acme/saas#11": self.platform_ok(
        "acme/saas", self.commits["saas_c"], "master", self.commits["saas_a"],
        ["src/one.ts"], 10,
        [{"path": "docs/design.md", "content": SPEC_SHARED}],
      ),
      "github.com/acme/saas#12": self.platform_ok(
        "acme/saas", self.commits["saas_c"], "preprod", self.commits["saas_b"],
        ["src/two.ts"], 20,
        [{"path": "docs/other.md", "content": SPEC_PRIVATE}],
      ),
    }


class PrReviewTargetsTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.fx = Fixture(self.tmp.name)
    self.recorder = self.fx.base / "dispatch-calls.txt"

  def prepare(self, payload):
    return run_cli("prepare", payload)

  def finalize(self, preparation_path, selection, adjudication=None):
    return run_cli("finalize", {
      "preparation_path": str(preparation_path),
      "selection": selection,
      "adjudication": adjudication or {},
    })

  def authorize(self, preparation_path, confirmation):
    decision = run_cli("authorize-dispatch", {
      "preparation_path": str(preparation_path),
      "confirmation": confirmation,
    })
    if decision["allowed"]:
      with self.recorder.open("a") as sink:
        sink.write("dispatch\n")
    return decision

  def test_explicit_targets_only_with_dedupe_and_correction(self):
    platform = self.fx.saas_pair_platform()
    platform["github.com/acme/saas#11"]["related_prs"] = ["https://github.com/acme/saas/pull/99"]
    duplicated = self.prepare(self.fx.payload([
      {"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True},
      {"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True},
    ], platform))
    self.assertEqual(duplicated["status"], "READY")
    self.assertEqual(
      [target["target_identity"] for target in duplicated["targets"]],
      ["github:github.com/acme/saas#11"],
    )

    empty = self.prepare(self.fx.payload([], platform))
    self.assertEqual(empty["status"], "NEEDS_INPUT")
    self.assertEqual(empty["targets"], [])
    self.assertIn("EMPTY_INPUT", empty["reason_codes"])

    unanchored = self.prepare(self.fx.payload(
      [{"raw": "123", "named_in_conversation": False}], platform,
    ))
    self.assertEqual(unanchored["status"], "NEEDS_INPUT")
    self.assertIn("AMBIGUOUS_INPUT", unanchored["reason_codes"])

    contradictory = self.prepare(self.fx.payload([
      {"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True},
      {"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True,
       "declared_repo": "acme/dashboard"},
    ], platform))
    self.assertEqual(contradictory["status"], "NEEDS_INPUT")
    self.assertIn("CONTRADICTORY_INPUT", contradictory["reason_codes"])

    unsafe_run = self.prepare(self.fx.payload(self.fx.inputs_11_12(), platform, run_id="../escape"))
    self.assertEqual(unsafe_run["status"], "BLOCKED")
    self.assertIn("INVALID_RUN_ID", unsafe_run["reason_codes"])
    self.assertFalse((self.fx.base / "escape.json").exists())

  def test_target_and_set_identity_bind_host_repo_pr_and_ignore_version_order(self):
    platform = self.fx.saas_pair_platform()
    forward = self.prepare(self.fx.payload(self.fx.inputs_11_12(), platform))
    self.assertEqual(forward["status"], "READY")
    first, second = forward["targets"]
    self.assertEqual(first["target_identity"], "github:github.com/acme/saas#11")
    self.assertEqual(second["target_identity"], "github:github.com/acme/saas#12")
    self.assertEqual(first["platform"], "github")
    self.assertEqual(first["host"], "github.com")
    self.assertEqual(first["destination_repo"], "acme/saas")
    self.assertEqual(first["source_repo"], "acme/saas")
    self.assertEqual(first["pr"], "11")
    self.assertEqual(first["head"], self.fx.commits["saas_c"])
    self.assertEqual(first["base"], self.fx.commits["saas_a"])
    self.assertEqual(first["trunk"], "master")
    self.assertEqual(first["authored_diff_base"], self.fx.commits["saas_a"])
    self.assertEqual(second["base"], self.fx.commits["saas_b"])

    reordered = self.prepare(self.fx.payload(list(reversed(self.fx.inputs_11_12())), platform))
    self.assertEqual(reordered["set_identity"], forward["set_identity"])
    self.assertEqual(
      [target["target_identity"] for target in reordered["targets"]],
      [target["target_identity"] for target in forward["targets"]],
    )

    moved = self.fx.saas_pair_platform()
    moved["github.com/acme/saas#12"]["head"] = self.fx.commits["saas_b"]
    moved["github.com/acme/saas#12"]["head_ref"] = "preprod"
    moved["github.com/acme/saas#12"]["base"] = self.fx.commits["saas_a"]
    moved["github.com/acme/saas#12"]["base_ref"] = "master"
    versionless = self.prepare(self.fx.payload(self.fx.inputs_11_12(), moved))
    self.assertEqual(versionless["set_identity"], forward["set_identity"])

    subset = self.prepare(self.fx.payload(self.fx.inputs_11_12()[:1], platform))
    self.assertNotEqual(subset["set_identity"], forward["set_identity"])

    ssh_checkout = self.prepare(self.fx.payload(
      [{"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True}],
      {"github.com/acme/saas#11": self.fx.platform_ok(
        "acme/saas", self.fx.commits["saas_c"], "master", self.fx.commits["saas_a"],
        ["src/one.ts"], 10, [],
      )},
      run_id="run-ssh",
    ))
    self.assertEqual(ssh_checkout["status"], "READY")
    self.assertEqual(ssh_checkout["targets"][0]["host"], "github.com")

  def test_checkout_identity_binds_host_not_just_owner_and_repo(self):
    same_repo_other_host = self.fx.payload(
      [{"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True}],
      {"github.com/acme/saas#11": self.fx.platform_ok(
        "acme/saas", self.fx.commits["saas_c"], "master", self.fx.commits["saas_a"],
        ["src/one.ts"], 10, [],
      )},
    )
    same_repo_other_host["repos"]["acme/saas"]["remote"] = "ssh://git@gitlab.com/acme/saas.git"
    wrong_host = self.prepare(same_repo_other_host)
    self.assertEqual(wrong_host["status"], "BLOCKED")
    self.assertEqual(wrong_host["targets"], [])
    self.assertEqual(
      [failure["reason_code"] for failure in wrong_host["failures"]],
      ["CHECKOUT_IDENTITY_MISMATCH"],
    )

    ssh_remote = self.fx.payload(
      [{"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True}],
      {"github.com/acme/saas#11": self.fx.platform_ok(
        "acme/saas", self.fx.commits["saas_c"], "master", self.fx.commits["saas_a"],
        ["src/one.ts"], 10, [],
      )},
    )
    ssh_remote["repos"]["acme/saas"]["remote"] = "ssh://git@github.com/acme/saas.git"
    accepted = self.prepare(ssh_remote)
    self.assertEqual(accepted["status"], "READY")

    scp_remote = dict(ssh_remote)
    scp_remote["repos"] = {
      "acme/saas": {"checkout": str(self.fx.saas), "remote": "git@github.com:acme/saas.git"},
    }
    self.assertEqual(self.prepare(scp_remote)["status"], "READY")

  def test_same_repo_same_head_different_pr_keep_own_root_and_diff_base(self):
    result = self.prepare(self.fx.payload(self.fx.inputs_11_12(), self.fx.saas_pair_platform()))
    by_pr = {target["pr"]: target for target in result["targets"]}
    self.assertEqual(by_pr["11"]["head"], by_pr["12"]["head"])
    self.assertNotEqual(by_pr["11"]["review_root"], by_pr["12"]["review_root"])
    self.assertNotEqual(by_pr["11"]["base"], by_pr["12"]["base"])
    self.assertEqual(by_pr["11"]["authored_diff_base"], self.fx.commits["saas_a"])
    self.assertEqual(by_pr["12"]["authored_diff_base"], self.fx.commits["saas_a"])
    for pr in ("11", "12"):
      target = by_pr[pr]
      self.assertTrue(target["review_root"].startswith(str(self.fx.saas / ".worktrees")))
      self.assertFalse(Path(target["review_root"]).exists())
      self.assertTrue(Path(target["materials"]["root"]).is_dir())
      self.assertFalse(str(target["review_root"]) in target["materials"]["root"])
      self.assertEqual(
        subprocess.run(
          ["git", "-C", target["checkout"], "cat-file", "-e", f"{target['authored_diff_base']}^{{commit}}"],
          capture_output=True,
        ).returncode,
        0,
      )

    other_run = self.prepare(self.fx.payload(
      self.fx.inputs_11_12(), self.fx.saas_pair_platform(), run_id="run-02",
    ))
    other = {target["pr"]: target for target in other_run["targets"]}
    for pr in ("11", "12"):
      self.assertNotEqual(by_pr[pr]["review_root"], other[pr]["review_root"])
      self.assertNotEqual(by_pr[pr]["materials"]["root"], other[pr]["materials"]["root"])
      self.assertTrue(Path(other[pr]["materials"]["root"]).is_dir())

  def test_shared_material_keeps_sources_rules_and_verbatim_specs(self):
    platform = self.fx.saas_pair_platform()
    platform["github.com/acme/dashboard#707"] = self.fx.platform_ok(
      "acme/dashboard", self.fx.commits["dash_a"], "master", self.fx.commits["dash_a"],
      ["src/three.ts"], 30,
      [{"path": "docs/design.md", "content": SPEC_SHARED}],
      head_ref="master",
    )
    self.fx.profile.write_text(
      "acme/saas:\n  trunk: master\n  spec_globs:\n    - docs/*.md\n  conventions_docs:\n    - CLAUDE.md\n"
    )
    inputs = self.fx.inputs_11_12() + [
      {"raw": "https://github.com/acme/dashboard/pull/707", "named_in_conversation": True},
    ]
    result = self.prepare(self.fx.payload(inputs, platform))
    self.assertEqual(result["status"], "READY")
    manifest = result["material_manifest"]
    shared = [entry for entry in manifest["shared"].values() if entry["content"] == SPEC_SHARED]
    self.assertEqual(len(shared), 1)
    self.assertEqual(
      sorted(shared[0]["source_targets"]),
      ["github:github.com/acme/dashboard#707", "github:github.com/acme/saas#11"],
    )
    self.assertEqual(shared[0]["bytes"], len(SPEC_SHARED.encode("utf-8")))
    self.assertNotEqual(shared[0]["content_sha256"], "")
    self.assertNotIn("dependencies", result)
    self.assertNotIn("dependencies", manifest)

    saas12 = manifest["targets"]["github:github.com/acme/saas#12"]
    self.assertNotIn("content", saas12["specs"][0])
    shared_key = saas12["specs"][0]["shared_key"]
    self.assertEqual(manifest["shared"][shared_key]["content"], SPEC_PRIVATE)
    self.assertEqual(saas12["rules"]["conventions_docs"], ["CLAUDE.md"])
    self.assertEqual(saas12["rules"]["spec_globs"], ["docs/*.md"])
    by_pr = {target["pr"]: target for target in result["targets"]}
    for pr in ("11", "12"):
      written = by_pr[pr]["materials"]["specs"]
      self.assertEqual(len(written), 1)
      self.assertEqual(Path(written[0]["file"]).read_text(), written[0]["content"])
    self.assertEqual(by_pr["12"]["materials"]["specs"][0]["content"], SPEC_PRIVATE)
    self.assertEqual(by_pr["11"]["materials"]["specs"][0]["content"], SPEC_SHARED)

  def test_set_selects_angles_once_and_holds_seats_on_undecided_capacity(self):
    selection = [
      {"seat": "opus/typescript-reviewer", "angle": "context-aware primary"},
      {"seat": "opus/security-reviewer", "angle": "security"},
    ]
    self.fx.profile.write_text("acme/saas:\n  trunk: master\n  conventions_docs:\n    - CLAUDE.md\n")
    small = self.prepare(self.fx.payload(self.fx.inputs_11_12(), self.fx.saas_pair_platform()))
    self.assertEqual(small["status"], "READY")
    self.assertEqual(small["selection_count"], 0)
    self.assertEqual(small["dispatch"]["reason"], "selection-required")

    small = self.finalize(small["preparation_path"], selection)
    self.assertEqual(small["selection_count"], 1)
    self.assertEqual(len(small["dispatch_seats"]), 2)
    self.assertEqual(len(small["division_of_labor"]), 2)
    for row in small["division_of_labor"]:
      self.assertEqual(set(row.keys()), ROW_KEYS)
      self.assertEqual(
        sorted(item["target_identity"] for item in row["primary_material"]),
        ["github:github.com/acme/saas#11", "github:github.com/acme/saas#12"],
      )
      self.assertGreater(row["shared_bytes"], 0)
      self.assertEqual(
        sorted(item["path"] for item in row["extra_context"] if item["kind"] == "conventions"),
        ["CLAUDE.md"],
      )
    self.assertEqual(small["capacity"]["decision"], "within-threshold")
    self.assertFalse(small["capacity"]["adjudication_required"])
    self.assertEqual(small["capacity"]["waiting_seats"], [])
    self.assertTrue(small["dispatch"]["allowed"])
    self.assertEqual(small["dispatch"]["reason"], "claude-seats-auto")

    bulk = self.fx.saas_pair_platform()
    bulk["github.com/acme/saas#12"]["changed_files"] = [f"src/f{index}.ts" for index in range(40)]
    bulk["github.com/acme/saas#12"]["diff_lines"] = 900
    big = self.prepare(self.fx.payload(self.fx.inputs_11_12(), bulk, run_id="run-big"))
    big = self.finalize(big["preparation_path"], selection)
    self.assertEqual(big["capacity"]["decision"], "awaiting-adjudication")
    self.assertTrue(big["capacity"]["adjudication_required"])
    self.assertTrue(big["capacity"]["targets"]["github:github.com/acme/saas#12"]["chunked"])
    self.assertEqual(
      sorted(big["capacity"]["waiting_seats"]),
      ["opus/security-reviewer", "opus/typescript-reviewer"],
    )
    self.assertFalse(big["dispatch"]["allowed"])
    self.assertEqual(big["dispatch"]["reason"], "awaiting-adjudication")

    adjudicated = self.finalize(
      big["preparation_path"], selection,
      {"github:github.com/acme/saas#12": "accept-incomplete",
       "review_set": "accept-incomplete"},
    )
    self.assertEqual(adjudicated["capacity"]["decision"], "adjudicated")
    self.assertFalse(adjudicated["capacity"]["adjudication_required"])
    self.assertEqual(adjudicated["capacity"]["waiting_seats"], [])
    self.assertEqual(adjudicated["capacity"]["adjudication"]["github:github.com/acme/saas#12"],
                     "accept-incomplete")
    self.assertEqual(adjudicated["dispatch"]["reason"], "claude-seats-auto")

    blocked_platform = self.fx.saas_pair_platform()
    blocked_platform["github.com/acme/saas#12"] = {"status": "error", "reason": "not_found"}
    blocked = self.prepare(self.fx.payload(self.fx.inputs_11_12(), blocked_platform, run_id="run-blocked"))
    not_ready = self.finalize(blocked["preparation_path"], selection)
    self.assertEqual(not_ready["status"], "ERROR")
    self.assertIn("PREPARATION_NOT_READY", not_ready["reason_codes"])

  def test_aggregate_set_capacity_requires_adjudication(self):
    selection = [{"seat": "opus/code-reviewer", "angle": "context-aware primary"}]
    platform = self.fx.saas_pair_platform()
    for key in ("github.com/acme/saas#11", "github.com/acme/saas#12"):
      platform[key]["changed_files"] = [f"src/{key[-2:]}-{index}.ts" for index in range(10)]
      platform[key]["diff_lines"] = 500
    prepared = self.prepare(self.fx.payload(
      self.fx.inputs_11_12(), platform, run_id="run-aggregate-capacity",
    ))
    pending = self.finalize(prepared["preparation_path"], selection)
    self.assertFalse(any(item["chunked"] for item in pending["capacity"]["targets"].values()))
    self.assertTrue(pending["capacity"]["review_set"]["chunked"])
    self.assertEqual(20, pending["capacity"]["review_set"]["source_file_count"])
    self.assertEqual(1000, pending["capacity"]["review_set"]["diff_lines"])
    self.assertEqual(["review_set"], pending["capacity"]["unresolved"])
    self.assertTrue(pending["capacity"]["adjudication_required"])
    self.assertEqual("awaiting-adjudication", pending["dispatch"]["reason"])

    accepted = self.finalize(
      pending["preparation_path"], selection, {"review_set": "accept-incomplete"},
    )
    self.assertFalse(accepted["capacity"]["adjudication_required"])
    self.assertEqual([], accepted["capacity"]["unresolved"])
    self.assertEqual("claude-seats-auto", accepted["dispatch"]["reason"])

  def test_any_target_failure_stops_whole_set_and_cancel_only_clears_this_run(self):
    selection = [{"seat": "opus/code-reviewer", "angle": "context-aware primary"}]
    broken = self.fx.saas_pair_platform()
    broken["github.com/acme/saas#12"] = {"status": "error", "reason": "not_found"}
    failed = self.prepare(self.fx.payload(self.fx.inputs_11_12(), broken))
    self.assertEqual(failed["status"], "BLOCKED")
    self.assertEqual(failed["targets"], [])
    self.assertEqual(failed["capacity"]["waiting_seats"], [])
    self.assertEqual(
      sorted(failure["target_identity"] for failure in failed["failures"]),
      ["github:github.com/acme/saas#12"],
    )
    self.assertTrue(all(failure["reason_code"] for failure in failed["failures"]))
    self.assertFalse(failed["dispatch"]["allowed"])
    blocked_authorization = self.authorize(failed["preparation_path"], {"user_message": "照推薦"})
    self.assertFalse(blocked_authorization["allowed"])
    self.assertFalse(self.recorder.exists())

    mismatched = self.fx.saas_pair_platform()
    mismatched["github.com/acme/saas#11"]["destination_repo"] = "acme/other"
    identity = self.prepare(self.fx.payload(self.fx.inputs_11_12(), mismatched))
    self.assertEqual(identity["status"], "BLOCKED")
    self.assertEqual([failure["reason_code"] for failure in identity["failures"]], ["TARGET_IDENTITY_MISMATCH"])

    missing = self.fx.saas_pair_platform()
    missing["github.com/acme/saas#12"]["base"] = self.fx.commits["dash_a"]
    version = self.prepare(self.fx.payload(self.fx.inputs_11_12(), missing))
    self.assertEqual(version["status"], "BLOCKED")
    self.assertEqual(
      [failure["reason_code"] for failure in version["failures"]],
      ["TARGET_VERSION_MISMATCH"],
    )

    kept = self.prepare(self.fx.payload(self.fx.inputs_11_12(), self.fx.saas_pair_platform()))
    kept = self.finalize(kept["preparation_path"], selection)
    kept_roots = sorted(target["review_root"] for target in kept["targets"])
    for target in kept["targets"]:
      Path(target["review_root"]).mkdir(parents=True, exist_ok=True)
      Path(target["review_root"], "checkout.txt").write_text("this run\n")
    other_session = self.fx.saas / ".worktrees" / "review-pr-11"
    other_session.mkdir(parents=True, exist_ok=True)
    (other_session / "material.txt").write_text("other session\n")

    cancelled = run_cli("cancel", {"preparation_path": kept["preparation_path"]})
    self.assertTrue(cancelled["cancelled"])
    self.assertEqual(
      sorted(target["materials"]["root"] for target in kept["targets"]),
      sorted(cancelled["removed"]),
    )
    self.assertEqual(sorted(cancelled["left_to_step7"]), kept_roots)
    for target in kept["targets"]:
      self.assertFalse(Path(target["materials"]["root"]).exists())
      self.assertTrue(Path(target["review_root"], "checkout.txt").is_file())
    self.assertTrue((other_session / "material.txt").is_file())

    after_cancel = self.authorize(kept["preparation_path"], {"user_message": "照推薦"})
    self.assertFalse(after_cancel["allowed"])
    self.assertEqual(after_cancel["reason"], "cancelled")
    self.assertFalse(self.recorder.exists())

  def test_cancel_refuses_tampered_state_and_never_touches_outside_paths(self):
    kept = self.prepare(self.fx.payload(self.fx.inputs_11_12(), self.fx.saas_pair_platform()))
    state_file = Path(kept["preparation_path"])
    sentinel = self.fx.base / "sentinel"
    sentinel.mkdir()
    (sentinel / "keep.txt").write_text("do not delete\n")

    tampered = json.loads(state_file.read_text())
    tampered["targets"][0]["materials"] = {"root": str(sentinel), "specs": []}
    state_file.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True))
    refused = run_cli("cancel", {"preparation_path": str(state_file)})
    self.assertFalse(refused["cancelled"])
    self.assertEqual(refused["reason_codes"], ["STATE_MATERIALS_OUT_OF_SCOPE"])
    self.assertEqual(refused["removed"], [])
    self.assertTrue((sentinel / "keep.txt").is_file())

    escape = self.fx.base / "escape"
    escape.mkdir()
    (escape / "keep.txt").write_text("do not delete\n")
    (self.fx.state_root / "evil.json").write_text(json.dumps({
      "run_id": "real-run",
      "targets": [{"materials": {"root": str(escape)}, "review_root": str(escape)}],
    }))
    mismatched = run_cli("cancel", {"preparation_path": str(self.fx.state_root / "evil.json")})
    self.assertFalse(mismatched["cancelled"])
    self.assertEqual(mismatched["reason_codes"], ["STATE_RUN_ID_MISMATCH"])
    self.assertTrue((escape / "keep.txt").is_file())

    unknown = run_cli("cancel", {"preparation_path": str(self.fx.base / "nope.json")})
    self.assertFalse(unknown["cancelled"])
    self.assertEqual(unknown["reason_codes"], ["PREPARATION_NOT_FOUND"])

  def test_single_target_path_keeps_profile_and_error_handling(self):
    self.fx.profile.write_text(
      "acme/saas:\n  trunk: preprod\n  conventions_docs:\n    - CLAUDE.md\n"
    )
    single = self.prepare(self.fx.payload(
      [{"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True}],
      {"github.com/acme/saas#11": self.fx.platform_ok(
        "acme/saas", self.fx.commits["saas_c"], "master", self.fx.commits["saas_a"],
        ["src/one.ts"], 10, [{"path": "docs/design.md", "content": SPEC_SHARED}],
      )},
    ))
    self.assertEqual(single["status"], "READY")
    self.assertEqual(len(single["targets"]), 1)
    target = single["targets"][0]
    self.assertEqual(target["trunk"], "preprod")
    self.assertTrue(target["trunk_source"].startswith("profile "))
    self.assertEqual(target["authored_diff_base"], self.fx.commits["saas_a"])
    self.assertEqual(
      Path(target["review_root"]),
      self.fx.saas / ".worktrees" / "review-pr-11",
    )
    self.assertEqual(target["rules"]["conventions_docs"], ["CLAUDE.md"])
    self.assertTrue(Path(target["materials"]["root"]).is_dir())
    self.assertFalse(Path(target["review_root"]).exists())
    self.assertEqual(Path(single["preparation_path"]), self.fx.state_root / "run-01.json")

    no_platform = self.prepare(self.fx.payload(
      [{"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True}], {},
    ))
    self.assertEqual(no_platform["status"], "BLOCKED")
    self.assertEqual(no_platform["failures"][0]["reason_code"], "TARGET_FETCH_FAILED")
    self.assertEqual(no_platform["targets"], [])

    missing_checkout = self.fx.payload(
      [{"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True}],
      {"github.com/acme/saas#11": self.fx.platform_ok(
        "acme/saas", self.fx.commits["saas_c"], "master", self.fx.commits["saas_a"],
        ["src/one.ts"], 10, [],
      )},
    )
    missing_checkout["repos"]["acme/saas"]["checkout"] = str(self.fx.base / "nope")
    gone = self.prepare(missing_checkout)
    self.assertEqual(gone["status"], "BLOCKED")
    self.assertEqual(gone["failures"][0]["reason_code"], "CHECKOUT_MISSING")

    wrong_version = self.fx.payload(
      [{"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True}],
      {"github.com/acme/saas#11": self.fx.platform_ok(
        "acme/saas", self.fx.commits["saas_c"], "master", self.fx.commits["saas_a"],
        ["src/one.ts"], 10, [],
      )},
    )
    wrong_version["platform"]["github.com/acme/saas#11"]["head_ref"] = "preprod"
    revision = self.prepare(wrong_version)
    self.assertEqual(revision["status"], "BLOCKED")
    self.assertEqual(revision["failures"][0]["reason_code"], "TARGET_VERSION_MISMATCH")

  def test_dispatch_authorization_requires_explicit_confirmation(self):
    selection = [
      {"seat": "opus/code-reviewer", "angle": "context-aware primary"},
      {"seat": "codex", "angle": "Codex 中性"},
    ]
    prepared = self.prepare(self.fx.payload(self.fx.inputs_11_12(), self.fx.saas_pair_platform()))
    self.assertEqual(prepared["status"], "READY")

    unselected = self.authorize(prepared["preparation_path"], {"user_message": "照推薦，開始"})
    self.assertFalse(unselected["allowed"])
    self.assertEqual(unselected["reason"], "selection-required")
    self.assertFalse(self.recorder.exists())

    prepared = self.finalize(prepared["preparation_path"], selection)
    awaiting = self.authorize(prepared["preparation_path"], None)
    self.assertFalse(awaiting["allowed"])
    self.assertEqual(awaiting["reason"], "awaiting-confirmation")
    self.assertFalse(self.recorder.exists())

    confirmed = self.authorize(prepared["preparation_path"], {"user_message": "照推薦，開始"})
    self.assertTrue(confirmed["allowed"])
    self.assertEqual(self.recorder.read_text().count("dispatch"), 1)

    bulk = self.fx.saas_pair_platform()
    bulk["github.com/acme/saas#12"]["changed_files"] = [f"src/f{index}.ts" for index in range(40)]
    bulk["github.com/acme/saas#12"]["diff_lines"] = 900
    gapped = self.prepare(self.fx.payload(self.fx.inputs_11_12(), bulk, run_id="run-gap"))
    gapped = self.finalize(gapped["preparation_path"], selection)
    gap_decision = self.authorize(gapped["preparation_path"], {"user_message": "照推薦，開始"})
    self.assertFalse(gap_decision["allowed"])
    self.assertEqual(gap_decision["reason"], "awaiting-adjudication")
    self.assertEqual(self.recorder.read_text().count("dispatch"), 1)

  def claude_state(self, run_id, selection, platform=None):
    prepared = self.prepare(self.fx.payload(
      self.fx.inputs_11_12(), platform or self.fx.saas_pair_platform(), run_id=run_id,
    ))
    self.assertEqual(prepared["status"], "READY")
    return self.finalize(prepared["preparation_path"], selection)

  def rewrite_state(self, path, mutate):
    state = json.loads(Path(path).read_text())
    mutate(state)
    Path(path).write_text(json.dumps(state, ensure_ascii=False, sort_keys=True))

  def test_claude_only_selection_without_capacity_gap_needs_no_confirmation(self):
    selection = [
      {"seat": "opus/typescript-reviewer", "angle": "context-aware primary"},
      {"seat": "opus/security-reviewer", "angle": "security"},
      {"seat": "opus/spec-compliance-reviewer", "angle": "formal spec"},
    ]
    state = self.claude_state("run-claude-only", selection)
    self.assertTrue(state["dispatch"]["allowed"])
    self.assertEqual(state["dispatch"]["reason"], "claude-seats-auto")

    decision = self.authorize(state["preparation_path"], None)
    self.assertTrue(decision["allowed"])
    self.assertEqual(decision["reason"], "claude-seats-auto")
    self.assertEqual(self.recorder.read_text().count("dispatch"), 1)

    confirmed = self.authorize(state["preparation_path"], {"user_message": "照推薦，開始"})
    self.assertTrue(confirmed["allowed"])
    self.assertEqual(confirmed["reason"], "confirmed")

    for model in ("opus", "claude-opus-4-7"):
      with self.subTest(model=model):
        pinned = self.claude_state(
          f"run-pinned-{model}", [{**selection[0], "model": model}],
        )
        self.assertTrue(pinned["dispatch"]["allowed"])

  def test_extra_quota_seat_in_selection_still_awaits_confirmation(self):
    claude = {"seat": "opus/code-reviewer", "angle": "context-aware primary"}
    external_cells = {
      "codex-neutral": {"seat": "codex", "angle": "Codex 中性"},
      "codex-adversarial": {"seat": "codex", "angle": "Codex 對抗"},
      "gemini": {"seat": "agy", "angle": "Gemini Pro"},
      "web-gpt": {"seat": "web-gpt", "angle": "web GPT Pro"},
      "fable-on-claude-row": {**claude, "model": "fable"},
      "fable-versioned": {**claude, "model": "claude-fable-1"},
      "other-model": {**claude, "model": "gpt-6-astra"},
    }
    control = self.claude_state("run-ext-control", [claude])
    self.assertTrue(control["dispatch"]["allowed"])
    for name, cell in external_cells.items():
      with self.subTest(external=name):
        state = self.claude_state(f"run-ext-{name}", [claude, cell])
        self.assertFalse(state["dispatch"]["allowed"])
        self.assertEqual(state["dispatch"]["reason"], "awaiting-confirmation")
        awaiting = self.authorize(state["preparation_path"], None)
        self.assertFalse(awaiting["allowed"])
        self.assertEqual(awaiting["reason"], "awaiting-confirmation")
        confirmed = self.authorize(state["preparation_path"], {"user_message": "加選，開始"})
        self.assertTrue(confirmed["allowed"])
        self.assertEqual(confirmed["reason"], "confirmed")
    self.assertEqual(self.recorder.read_text().count("dispatch"), len(external_cells))

    only_external = self.claude_state("run-only-external", [external_cells["gemini"]])
    self.assertEqual(only_external["dispatch"]["reason"], "awaiting-confirmation")

  def test_claude_only_selection_waits_for_capacity_adjudication(self):
    selection = [
      {"seat": "opus/typescript-reviewer", "angle": "context-aware primary"},
      {"seat": "opus/security-reviewer", "angle": "security"},
    ]
    bulk = self.fx.saas_pair_platform()
    bulk["github.com/acme/saas#12"]["changed_files"] = [f"src/f{index}.ts" for index in range(40)]
    bulk["github.com/acme/saas#12"]["diff_lines"] = 900
    gapped = self.claude_state("run-claude-gap", selection, bulk)
    self.assertEqual(
      sorted(gapped["capacity"]["waiting_seats"]),
      ["opus/security-reviewer", "opus/typescript-reviewer"],
    )
    self.assertEqual(gapped["dispatch"]["reason"], "awaiting-adjudication")
    for confirmation in (None, {"user_message": "照推薦，開始"}):
      decision = self.authorize(gapped["preparation_path"], confirmation)
      self.assertFalse(decision["allowed"])
      self.assertEqual(decision["reason"], "awaiting-adjudication")
    self.assertFalse(self.recorder.exists())

    adjudicated = self.finalize(
      gapped["preparation_path"], selection,
      {"github:github.com/acme/saas#12": "accept-incomplete", "review_set": "accept-incomplete"},
    )
    self.assertEqual(adjudicated["capacity"]["waiting_seats"], [])
    self.assertTrue(self.authorize(adjudicated["preparation_path"], None)["allowed"])

  def test_only_known_adjudication_values_settle_capacity(self):
    selection = [{"seat": "opus/typescript-reviewer", "angle": "context-aware primary"}]
    bulk = self.fx.saas_pair_platform()
    bulk["github.com/acme/saas#12"]["changed_files"] = [f"src/f{index}.ts" for index in range(40)]
    bulk["github.com/acme/saas#12"]["diff_lines"] = 900
    for name, value in (("null", None), ("empty", ""), ("unknown", "please-ask")):
      with self.subTest(value=name):
        gapped = self.claude_state(f"run-adj-{name}", selection, bulk)
        state = self.finalize(
          gapped["preparation_path"], selection,
          {"github:github.com/acme/saas#12": value, "review_set": value},
        )
        self.assertTrue(state["capacity"]["unresolved"])
        for confirmation in (None, {"user_message": "照推薦，開始"}):
          decision = self.authorize(state["preparation_path"], confirmation)
          self.assertFalse(decision["allowed"])
          self.assertEqual(decision["reason"], "awaiting-adjudication")
    self.assertFalse(self.recorder.exists())

  def test_matrix_cells_not_selected_do_not_block_claude_auto_dispatch(self):
    claude = {"seat": "opus/code-reviewer", "angle": "context-aware primary", "status": "selected"}
    skipped = [
      {"seat": "codex", "angle": "Codex 中性", "status": "not-selected"},
      {"seat": "agy", "angle": "Gemini Pro", "status": "cancelled"},
      {"seat": "web-gpt", "angle": "web GPT Pro", "status": "unavailable"},
    ]
    state = self.claude_state("run-matrix-cells", [claude, *skipped])
    self.assertEqual(state["dispatch"]["reason"], "claude-seats-auto")
    nothing_selected = self.claude_state(
      "run-matrix-none", [{**claude, "status": "not-selected"}, *skipped],
    )
    self.assertEqual(nothing_selected["dispatch"]["reason"], "awaiting-confirmation")

  def test_model_names_that_only_start_with_opus_are_not_claude_seats(self):
    cell = {"seat": "opus/code-reviewer", "angle": "context-aware primary"}
    for model in ("opus-gpt-6", "opus.codex", "opus_via_proxy"):
      with self.subTest(model=model):
        state = self.claude_state(f"run-model-{model}", [{**cell, "model": model}])
        self.assertEqual(state["dispatch"]["reason"], "awaiting-confirmation")
    for model in ("opus-5-5", "claude-opus-5-5"):
      with self.subTest(model=model):
        state = self.claude_state(f"run-model-{model}", [{**cell, "model": model}])
        self.assertEqual(state["dispatch"]["reason"], "claude-seats-auto")

  def test_state_written_before_this_change_is_never_released_for_missing_data(self):
    selection = [{"seat": "opus/code-reviewer", "angle": "context-aware primary"}]
    state = self.claude_state("run-old-state", selection)
    path = Path(state["preparation_path"])
    pristine = path.read_text()
    self.assertTrue(self.authorize(path, None)["allowed"])

    def drop_selection(value):
      del value["selection"]

    def drop_angle(value):
      value["selection"] = [{"seat": cell["seat"]} for cell in value["selection"]]

    def drop_capacity(value):
      del value["capacity"]

    def drop_adjudication_flag(value):
      del value["capacity"]["adjudication_required"]

    variants = {
      "selection-key-missing": drop_selection,
      "selection-empty-with-count": lambda value: value.update(selection=[]),
      "selection-not-a-list": lambda value: value.update(selection="opus/code-reviewer"),
      "cell-is-a-string": lambda value: value.update(selection=["opus/code-reviewer"]),
      "cell-without-angle": drop_angle,
      "seat-unhashable": lambda value: value.update(selection=[{"seat": ["x"], "angle": "security"}]),
      "capacity-missing": drop_capacity,
      "capacity-null": lambda value: value.update(capacity=None),
      "capacity-string": lambda value: value.update(capacity="within-threshold"),
      "capacity-flag-missing": drop_adjudication_flag,
      "external-seat-with-claude-angle": lambda value: value.update(
        selection=[{"seat": "codex", "angle": "context-aware primary"}]),
      "claude-seat-with-external-angle": lambda value: value.update(
        selection=[{"seat": "opus/code-reviewer", "angle": "Codex 中性"}]),
      "pair-mismatch": lambda value: value.update(
        selection=[{"seat": "opus/security-reviewer", "angle": "context-aware primary"}]),
      "unknown-claude-looking-seat": lambda value: value.update(
        selection=[{"seat": "opus/unknown-reviewer", "angle": "context-aware primary"}]),
      "seat-case-variant": lambda value: value.update(
        selection=[{"seat": "Opus/code-reviewer", "angle": "context-aware primary"}]),
      "legacy-fixture-seat": lambda value: value.update(
        selection=[{"seat": "cc-primary", "angle": "context-aware primary"}]),
    }
    for name, mutate in variants.items():
      with self.subTest(variant=name):
        path.write_text(pristine)
        self.rewrite_state(path, mutate)
        decision = self.authorize(path, None)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "awaiting-confirmation")
        confirmed = self.authorize(path, {"user_message": "照推薦，開始"})
        self.assertTrue(confirmed["allowed"])
        self.assertEqual(confirmed["reason"], "confirmed")

  def test_cancel_and_unready_states_still_refuse_claude_only_selection(self):
    selection = [{"seat": "opus/code-reviewer", "angle": "context-aware primary"}]
    state = self.claude_state("run-claude-cancel", selection)
    path = Path(state["preparation_path"])
    self.assertTrue(self.authorize(path, None)["allowed"])
    pristine = path.read_text()

    for status, reason in (("BLOCKED", "preparation-blocked"),
                           ("NEEDS_INPUT", "preparation-blocked"),
                           ("NO_NET_DIFF", "no-net-diff")):
      with self.subTest(status=status):
        path.write_text(pristine)
        self.rewrite_state(path, lambda value: value.update(status=status))
        decision = self.authorize(path, None)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], reason)

    path.write_text(pristine)
    cleared = self.finalize(path, [])
    self.assertEqual(cleared["dispatch"]["reason"], "selection-required")
    self.assertEqual(self.authorize(path, None)["reason"], "selection-required")

    path.write_text(pristine)
    cancelled = run_cli("cancel", {"preparation_path": str(path)})
    self.assertTrue(cancelled["cancelled"])
    for confirmation in (None, {"user_message": "照推薦，開始"}):
      decision = self.authorize(path, confirmation)
      self.assertFalse(decision["allowed"])
      self.assertEqual(decision["reason"], "cancelled")

    missing = self.authorize(self.fx.base / "state" / "no-such-run.json", None)
    self.assertFalse(missing["allowed"])
    self.assertEqual(missing["reason"], "preparation-not-found")


ERRORS_REMOTE = "https://github.com/acme/errors.git"
RENAMED_BODY = "".join(f"line {index}\n" for index in range(20))


def pr_url(repo, pr):
  return {"raw": f"https://github.com/{repo}/pull/{pr}", "named_in_conversation": True}


def merged_response(repo, merge, head, base_ref="master", author="alice"):
  return {
    "status": "ok",
    "destination_repo": repo,
    "base_ref": base_ref,
    "head": head,
    "merge_commit": merge,
    "author": author,
  }


class MergedFixture:
  def __init__(self, base):
    self.base = Path(base)
    self.checkouts = self.base / "checkouts"
    self.state_root = self.base / "state"
    self.checkouts.mkdir(parents=True)
    self.profile = self.base / "repos.yaml"
    self.profile.write_text("")
    self.reports = self.base / "pr-review-reports"
    self.c = {}
    self.saas = self._init("saas", SAAS_REMOTE)
    self.dashboard = self._init("dashboard", DASH_REMOTE)
    self.errors = self._init("errors", ERRORS_REMOTE)
    self._build_saas()
    self._build_dashboard()
    self._build_errors()

  def _init(self, name, remote):
    repo = self.checkouts / name
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/master")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "remote", "add", "origin", remote)
    return repo

  def change(self, repo, message, write=None, remove=(), move=()):
    for name, content in (write or {}).items():
      (repo / name).write_text(content)
      git(repo, "add", name)
    for name in remove:
      git(repo, "rm", "-q", name)
    for old, new in move:
      git(repo, "mv", old, new)
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")

  def merge(self, repo, branch):
    git(repo, "merge", "--no-ff", "-q", "-m", f"merge {branch}", branch)
    return git(repo, "rev-parse", "HEAD")

  def publish(self, repo, branch="master"):
    git(repo, "update-ref", f"refs/remotes/origin/{branch}", git(repo, "rev-parse", branch))

  def _build_saas(self):
    repo = self.saas
    self.c["c0"] = self.change(repo, "base", write={
      "keep.txt": "keep\n", "old.txt": RENAMED_BODY, "gone.txt": "gone\n", "shared.txt": "s0\n",
    })
    git(repo, "checkout", "-q", "-b", "side")
    self.c["side"] = self.change(repo, "side work", write={
      **{f"side{index}.txt": f"side {index}\n" for index in range(8)},
      "shared.txt": "side-version\n",
    })
    git(repo, "checkout", "-q", "master")
    git(repo, "checkout", "-q", "-b", "f30")
    self.c["head30"] = self.change(repo, "pr30", write={"new.txt": "new\n", "shared.txt": "s1\n"})
    git(repo, "checkout", "-q", "master")
    self.c["m30"] = self.merge(repo, "f30")
    git(repo, "checkout", "-q", "-b", "f21")
    self.c["head21"] = self.change(repo, "pr21", remove=["gone.txt"], move=[("old.txt", "renamed.txt")])
    git(repo, "checkout", "-q", "master")
    self.c["m21"] = self.merge(repo, "f21")
    self.c["tail"] = self.change(repo, "unrelated", write={"other.txt": "other\n"})
    self.publish(repo)

  def _build_dashboard(self):
    repo = self.dashboard
    self.c["d0"] = self.change(repo, "base", write={"x.txt": "x0\n"})
    git(repo, "checkout", "-q", "-b", "f5")
    self.c["head5"] = self.change(repo, "pr5", write={"x.txt": "x1\n"})
    git(repo, "checkout", "-q", "master")
    self.c["m5"] = self.merge(repo, "f5")
    self.c["d_revert"] = self.change(repo, "revert x", write={"x.txt": "x0\n"})
    self.publish(repo)

  def _build_errors(self):
    repo = self.errors
    self.c["e0"] = self.change(repo, "base", write={"a.txt": "a\n"})
    git(repo, "checkout", "-q", "-b", "fa")
    self.c["headA"] = self.change(repo, "pr41", write={"fa.txt": "fa\n"})
    git(repo, "checkout", "-q", "master")
    self.c["squash"] = self.change(repo, "squash pr41", write={"fa.txt": "fa\n"})
    git(repo, "checkout", "-q", "-b", "fb")
    self.c["headB"] = self.change(repo, "pr42", write={"fb.txt": "fb\n"})
    git(repo, "checkout", "-q", "master")
    self.c["mB"] = self.merge(repo, "fb")
    git(repo, "checkout", "-q", "-b", "other")
    git(repo, "checkout", "-q", "-b", "fc")
    self.c["headC"] = self.change(repo, "pr43", write={"fc.txt": "fc\n"})
    git(repo, "checkout", "-q", "other")
    self.c["mC"] = self.merge(repo, "fc")
    git(repo, "checkout", "-q", "master")
    self.c["u1"] = self.change(repo, "u1", write={"u.txt": "u1\n"})
    self.c["u2"] = self.change(repo, "u2", write={"u.txt": "u2\n"})
    self.publish(repo)

  def saas_platform(self):
    return {
      "github.com/acme/saas#30": merged_response("acme/saas", self.c["m30"], self.c["head30"], author="alice"),
      "github.com/acme/saas#21": merged_response("acme/saas", self.c["m21"], self.c["head21"], author="bob"),
    }

  def payload(self, inputs, platform, since=None, run_id="merged-01", repos=None, start_report=None):
    return {
      "run_id": run_id,
      "state_root": str(self.state_root),
      "profile_path": str(self.profile),
      "merged": True,
      "since": since or [],
      "reports_root": str(self.reports),
      "start_report": start_report or [],
      "inputs": inputs,
      "current_repo": {"remote": SAAS_REMOTE},
      "repos": repos or {
        "acme/saas": {"checkout": str(self.saas), "remote": SAAS_REMOTE},
        "acme/dashboard": {"checkout": str(self.dashboard), "remote": DASH_REMOTE},
        "acme/errors": {"checkout": str(self.errors), "remote": ERRORS_REMOTE},
      },
      "platform": platform,
    }

  def saas_inputs(self):
    return [pr_url("acme/saas", "21"), pr_url("acme/saas", "30")]

  def report(self, folder, pr, repo, source_sha, binding="verified"):
    path = self.reports / folder / f"pr-{pr}-review.audit.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
      f"# PR #{pr} Code Review 比較報告 · SHA {source_sha[:7]}\n\n"
      "**Report projection schema**: 2\n\n"
      f"**PR**: [{repo}#{pr}](https://github.com/{repo}/pull/{pr})\n"
      "**作者**: alice\n"
      f"**Review input basis**: source repo `R_kgDOHNiw_Q` + source SHA `{source_sha}`；"
      f"destination repo `R_kgDOHNiw_Q` + destination SHA `{'d' * 40}`；`input_binding: {binding}`\n"
      f"**worktree HEAD**: `{source_sha}`\n"
    )
    return str(path.resolve())


def entries_by_path(target):
  return {entry["path"]: entry for entry in target["entry_files"]}


class MergedRangePreparationTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    self.fx = MergedFixture(self.tmp.name)

  def prepare(self, payload):
    return run_cli("prepare", payload)

  def failure_codes(self, result):
    return sorted(failure["reason_code"] for failure in result["failures"])

  def test_same_repo_merged_prs_become_one_range_target(self):
    result = self.prepare(self.fx.payload(self.fx.saas_inputs(), self.fx.saas_platform()))
    self.assertEqual(result["status"], "READY", result["failures"])
    self.assertEqual(len(result["targets"]), 1)
    target = result["targets"][0]
    self.assertEqual(target["kind"], "range")
    self.assertEqual(target["platform"], "github")
    self.assertEqual(target["host"], "github.com")
    self.assertEqual(target["destination_repo"], "acme/saas")
    self.assertEqual(target["target_branch"], "master")
    self.assertEqual(target["start"]["sha"], self.fx.c["c0"])
    self.assertEqual(target["end"]["sha"], self.fx.c["tail"])
    self.assertRegex(target["start"]["sha"], r"^[0-9a-f]{40}$")
    self.assertRegex(target["end"]["sha"], r"^[0-9a-f]{40}$")
    self.assertEqual(
      [(pr["pr"], pr["merge_commit"], pr["head"], pr["author"]) for pr in target["related_prs"]],
      [("30", self.fx.c["m30"], self.fx.c["head30"], "alice"),
       ("21", self.fx.c["m21"], self.fx.c["head21"], "bob")],
    )
    self.assertEqual(sorted(entries_by_path(target)), ["gone.txt", "new.txt", "renamed.txt", "shared.txt"])
    diff = Path(target["review_diff"]["file"]).read_bytes()
    self.assertEqual({"file", "bytes", "lines"}, set(target["review_diff"]))
    self.assertEqual(target["review_diff"]["bytes"], len(diff))
    self.assertGreater(target["review_diff"]["lines"], 0)
    self.assertNotIn(b"other.txt", diff)
    state = json.loads(Path(result["preparation_path"]).read_text())
    self.assertEqual(state["targets"][0]["review_diff"], target["review_diff"])

  def test_end_is_pinned_when_target_branch_advances_after_preparation(self):
    result = self.prepare(self.fx.payload(self.fx.saas_inputs(), self.fx.saas_platform()))
    self.assertEqual(result["status"], "READY", result["failures"])
    pinned = result["targets"][0]
    pinned_diff = Path(pinned["review_diff"]["file"]).read_bytes()
    advanced = self.fx.change(self.fx.saas, "after prep", write={"shared.txt": "moved on\n"})
    self.fx.publish(self.fx.saas)
    self.assertNotEqual(advanced, pinned["end"]["sha"])

    finalized = run_cli("finalize", {
      "preparation_path": result["preparation_path"],
      "selection": [{"seat": "opus/code-reviewer", "angle": "primary"}],
      "adjudication": {},
    })
    target = finalized["targets"][0]
    self.assertEqual(target["end"]["sha"], self.fx.c["tail"])
    self.assertEqual(target["review_diff"], pinned["review_diff"])
    diff = Path(target["review_diff"]["file"]).read_bytes()
    self.assertEqual(pinned_diff, diff)
    self.assertNotIn(b"moved on", diff)

  def test_since_sets_start_and_resolution_failures_never_fall_back(self):
    explicit = self.prepare(self.fx.payload(
      self.fx.saas_inputs(), self.fx.saas_platform(), since=[f"acme/saas={self.fx.c['side']}"],
    ))
    self.assertEqual(explicit["status"], "READY", explicit["failures"])
    self.assertEqual(explicit["targets"][0]["start"]["sha"], self.fx.c["side"])
    self.assertEqual(explicit["targets"][0]["start"]["source"], "since")

    platform = {
      **self.fx.saas_platform(),
      "github.com/acme/dashboard#5": merged_response("acme/dashboard", self.fx.c["m5"], self.fx.c["head5"]),
    }
    inputs = [*self.fx.saas_inputs(), pr_url("acme/dashboard", "5")]
    for label, since in (
      ("missing-repo-mapping", [f"acme/saas={self.fx.c['side']}"]),
      ("bare-sha-across-repos", [self.fx.c["side"]]),
    ):
      with self.subTest(case=label):
        result = self.prepare(self.fx.payload(inputs, platform, since=since, run_id=f"since-{label}"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("SINCE_REPO_MAPPING_REQUIRED", self.failure_codes(result))
        self.assertEqual(result["targets"], [])

    for label, value in (("unknown-sha", "e" * 40), ("branch-name", "master")):
      with self.subTest(case=label):
        result = self.prepare(self.fx.payload(
          self.fx.saas_inputs(), self.fx.saas_platform(), since=[f"acme/saas={value}"],
          run_id=f"since-{label}",
        ))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self.failure_codes(result), ["SINCE_UNRESOLVED"])
        self.assertEqual(result["targets"], [])

  def test_fallback_start_is_first_parent_of_topologically_earliest_merge(self):
    result = self.prepare(self.fx.payload(self.fx.saas_inputs(), self.fx.saas_platform()))
    self.assertEqual(result["status"], "READY", result["failures"])
    start = result["targets"][0]["start"]
    self.assertEqual(start["source"], "earliest-merge-first-parent")
    self.assertEqual(start["pr"], "30")
    self.assertEqual(start["merge_commit"], self.fx.c["m30"])
    self.assertEqual(start["sha"], git(self.fx.saas, "rev-parse", f"{self.fx.c['m30']}^1"))
    self.assertNotEqual(start["sha"], git(self.fx.saas, "rev-parse", f"{self.fx.c['m21']}^1"))

  def test_entry_files_are_landed_files_within_two_dot_range_diff(self):
    result = self.prepare(self.fx.payload(
      self.fx.saas_inputs(), self.fx.saas_platform(), since=[f"acme/saas={self.fx.c['side']}"],
    ))
    self.assertEqual(result["status"], "READY", result["failures"])
    target = result["targets"][0]
    self.assertEqual(sorted(entries_by_path(target)), ["gone.txt", "new.txt", "renamed.txt", "shared.txt"])
    self.assertEqual(sorted(target["changed_files"]), ["gone.txt", "new.txt", "renamed.txt", "shared.txt"])
    diff = Path(target["review_diff"]["file"]).read_text()
    self.assertIn("-side-version", diff)
    self.assertIn("+s1", diff)
    self.assertNotIn("-s0", diff)
    for outside in ("side0.txt", "side7.txt", "other.txt", "keep.txt"):
      self.assertNotIn(outside, diff)
      self.assertNotIn(outside, target["changed_files"])
    names = git(self.fx.saas, "diff", "--name-only", self.fx.c["side"], self.fx.c["tail"]).splitlines()
    self.assertGreaterEqual(len(names), 12)

  def test_added_renamed_and_deleted_entries_carry_their_kind(self):
    result = self.prepare(self.fx.payload(self.fx.saas_inputs(), self.fx.saas_platform()))
    self.assertEqual(result["status"], "READY", result["failures"])
    target = result["targets"][0]
    entries = entries_by_path(target)
    self.assertEqual(entries["new.txt"]["status"], "added")
    self.assertEqual(entries["shared.txt"]["status"], "modified")
    self.assertEqual(entries["gone.txt"]["status"], "deleted")
    self.assertEqual(entries["renamed.txt"]["status"], "renamed")
    self.assertEqual(entries["renamed.txt"]["old_path"], "old.txt")
    self.assertNotIn("mode", result)
    self.assertNotIn("landed_files", target["related_prs"][1])
    self.assertFalse({"trunk", "trunk_source"} & set(target))
    self.assertIn("rules", target)
    diff = Path(target["review_diff"]["file"]).read_text()
    self.assertIn("rename from old.txt", diff)
    self.assertIn("deleted file mode", diff)
    self.assertIn("new file mode", diff)

  def test_unsupported_topology_and_missing_merge_objects_fail_explicitly(self):
    c = self.fx.c
    good = ("42", merged_response("acme/errors", c["mB"], c["headB"]))
    cases = (
      ("squash", [("41", merged_response("acme/errors", c["squash"], c["headA"]))],
       "MERGE_TOPOLOGY_UNSUPPORTED"),
      ("second-parent-is-not-head", [("42", merged_response("acme/errors", c["mB"], c["headA"]))],
       "MERGE_TOPOLOGY_UNSUPPORTED"),
      ("merged-into-another-branch",
       [good, ("43", merged_response("acme/errors", c["mC"], c["headC"], base_ref="other"))],
       "MERGED_BRANCH_MISMATCH"),
      ("merge-not-in-target", [("43", merged_response("acme/errors", c["mC"], c["headC"]))],
       "MERGE_NOT_IN_TARGET"),
      ("merge-object-missing", [("44", merged_response("acme/errors", "d" * 40, c["headA"]))],
       "MERGE_COMMIT_UNAVAILABLE"),
      ("merge-oid-absent", [("45", merged_response("acme/errors", None, c["headA"]))],
       "MERGE_COMMIT_UNAVAILABLE"),
    )
    for label, prs, code in cases:
      with self.subTest(case=label):
        result = self.prepare(self.fx.payload(
          [pr_url("acme/errors", pr) for pr, _ in prs],
          {f"github.com/acme/errors#{pr}": response for pr, response in prs},
          run_id=f"err-{label}",
        ))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn(code, self.failure_codes(result))
        self.assertEqual(result["targets"], [])

    broken = self.fx.base / "broken"
    shutil.copytree(self.fx.errors, broken)
    middle = c["u1"]
    (broken / ".git" / "objects" / middle[:2] / middle[2:]).unlink()
    result = self.prepare(self.fx.payload(
      [pr_url("acme/errors", "42")], {"github.com/acme/errors#42": good[1]},
      run_id="err-ancestry", repos={"acme/errors": {"checkout": str(broken), "remote": ERRORS_REMOTE}},
    ))
    self.assertEqual(result["status"], "BLOCKED")
    self.assertEqual(self.failure_codes(result), ["ANCESTRY_CHECK_FAILED"])
    self.assertEqual(result["targets"], [])

  def test_zero_net_repo_is_recorded_and_all_zero_set_has_nothing_to_review(self):
    platform = {
      **self.fx.saas_platform(),
      "github.com/acme/dashboard#5": merged_response("acme/dashboard", self.fx.c["m5"], self.fx.c["head5"]),
    }
    mixed = self.prepare(self.fx.payload(
      [*self.fx.saas_inputs(), pr_url("acme/dashboard", "5")], platform,
    ))
    self.assertEqual(mixed["status"], "READY", mixed["failures"])
    self.assertEqual([target["destination_repo"] for target in mixed["targets"]], ["acme/saas"])
    self.assertEqual(len(mixed["no_net_diff"]), 1)
    quiet = mixed["no_net_diff"][0]
    self.assertEqual(quiet["destination_repo"], "acme/dashboard")
    self.assertEqual(quiet["status"], "no-net-diff")
    self.assertEqual(quiet["entry_files"], [])
    self.assertEqual(quiet["excluded_files"], [{"path": "x.txt", "reason": "no-net-diff-in-range"}])
    self.assertEqual([pr["pr"] for pr in quiet["related_prs"]], ["5"])
    self.assertNotIn("acme/dashboard", json.dumps(mixed["material_manifest"]["targets"]))

    only = self.prepare(self.fx.payload([pr_url("acme/dashboard", "5")], platform, run_id="merged-quiet"))
    self.assertEqual(only["status"], "NO_NET_DIFF")
    self.assertEqual(only["targets"], [])
    self.assertEqual(only["failures"], [])
    self.assertEqual(only["dispatch"], {"allowed": False, "reason": "no-net-diff"})
    decision = run_cli("authorize-dispatch", {
      "preparation_path": only["preparation_path"], "confirmation": {"user_message": "開始"},
    })
    self.assertEqual(decision, {"allowed": False, "reason": "no-net-diff"})

  def test_merged_mode_accepts_only_github_targets(self):
    result = self.prepare(self.fx.payload(
      [{"raw": "https://bitbucket.org/acme/saas/pull-requests/7", "named_in_conversation": True}],
      {"bitbucket.org/acme/saas#7": merged_response("acme/saas", self.fx.c["m30"], self.fx.c["head30"])},
    ))
    self.assertEqual(result["status"], "BLOCKED")
    self.assertEqual(self.failure_codes(result), ["MERGED_PLATFORM_UNSUPPORTED"])

  def test_fallback_start_refuses_merges_without_a_single_earliest(self):
    repo = self.fx._init("parallel", "https://github.com/acme/parallel.git")
    self.fx.change(repo, "base", write={"p.txt": "p\n"})
    git(repo, "checkout", "-q", "-b", "line")
    git(repo, "checkout", "-q", "-b", "g1")
    head1 = self.fx.change(repo, "pr1", write={"g1.txt": "g1\n"})
    git(repo, "checkout", "-q", "line")
    merge1 = self.fx.merge(repo, "g1")
    git(repo, "checkout", "-q", "master")
    git(repo, "checkout", "-q", "-b", "g2")
    head2 = self.fx.change(repo, "pr2", write={"g2.txt": "g2\n"})
    git(repo, "checkout", "-q", "master")
    merge2 = self.fx.merge(repo, "g2")
    self.fx.merge(repo, "line")
    self.fx.publish(repo)
    platform = {
      "github.com/acme/parallel#1": merged_response("acme/parallel", merge1, head1),
      "github.com/acme/parallel#2": merged_response("acme/parallel", merge2, head2),
    }
    repos = {"acme/parallel": {"checkout": str(repo), "remote": "https://github.com/acme/parallel.git"}}
    inputs = [pr_url("acme/parallel", "1"), pr_url("acme/parallel", "2")]
    fallback = self.prepare(self.fx.payload(inputs, platform, repos=repos))
    self.assertEqual(fallback["status"], "BLOCKED")
    self.assertEqual(self.failure_codes(fallback), ["MERGE_ORDER_AMBIGUOUS"])
    explicit = self.prepare(self.fx.payload(
      inputs, platform, since=[f"acme/parallel={git(repo, 'rev-parse', f'{merge2}^1')}"],
      repos=repos, run_id="parallel-since",
    ))
    self.assertEqual(explicit["status"], "READY", explicit["failures"])


  def test_verified_prior_report_is_listed_as_start_candidate(self):
    path = self.fx.report("saas", "12", "acme/saas", self.fx.c["m30"])
    result = self.prepare(self.fx.payload(self.fx.saas_inputs(), self.fx.saas_platform()))
    self.assertEqual(result["status"], "READY", result["failures"])
    self.assertEqual(result["targets"][0]["start_candidates"],
                     [{"path": path, "sha": self.fx.c["m30"]}])

  def test_prior_report_candidate_is_not_adopted_without_binding(self):
    self.fx.report("saas", "12", "acme/saas", self.fx.c["m30"])
    result = self.prepare(self.fx.payload(self.fx.saas_inputs(), self.fx.saas_platform()))
    self.assertEqual(result["status"], "READY", result["failures"])
    self.assertEqual(len(result["targets"][0]["start_candidates"]), 1)
    start = result["targets"][0]["start"]
    self.assertEqual(start["source"], "earliest-merge-first-parent")
    self.assertEqual(start["sha"], self.fx.c["c0"])

  def test_bound_prior_report_sets_start_to_its_source_sha(self):
    path = self.fx.report("saas", "12", "acme/saas", self.fx.c["m30"])
    result = self.prepare(self.fx.payload(
      self.fx.saas_inputs(), self.fx.saas_platform(), start_report=[path],
    ))
    self.assertEqual(result["status"], "READY", result["failures"])
    target = result["targets"][0]
    self.assertEqual(target["start"]["sha"], self.fx.c["m30"])
    self.assertEqual(target["start"]["source"], "prior-report")
    self.assertEqual(target["start"]["report"], path)
    self.assertIn(path, target["start"]["detail"])
    self.assertEqual(sorted(entries_by_path(target)), ["gone.txt", "renamed.txt"])

  def test_bound_report_that_is_not_a_candidate_blocks_the_run(self):
    path = self.fx.report("saas", "12", "acme/dashboard", self.fx.c["m30"])
    result = self.prepare(self.fx.payload(
      self.fx.saas_inputs(), self.fx.saas_platform(), start_report=[path],
    ))
    self.assertEqual(result["status"], "BLOCKED")
    self.assertEqual(self.failure_codes(result), ["START_REPORT_NOT_CANDIDATE"])
    self.assertIn(path, result["failures"][0]["detail"])
    self.assertEqual(result["targets"], [])

  def test_unverified_unresolvable_or_other_repo_reports_are_not_candidates(self):
    self.fx.report("saas", "1", "acme/saas", self.fx.c["m30"], binding="unverified")
    self.fx.report("saas", "2", "acme/saas", self.fx.c["m30"][:12])
    self.fx.report("saas", "3", "acme/saas", "e" * 40)
    self.fx.report("saas", "4", "acme/dashboard", self.fx.c["m30"])
    kept = self.fx.report("saas", "5", "acme/saas", self.fx.c["m30"])
    result = self.prepare(self.fx.payload(self.fx.saas_inputs(), self.fx.saas_platform()))
    self.assertEqual(result["status"], "READY", result["failures"])
    self.assertEqual([candidate["path"] for candidate in result["targets"][0]["start_candidates"]], [kept])

  def test_missing_or_empty_reports_dir_falls_back_without_error(self):
    missing = self.prepare(self.fx.payload(self.fx.saas_inputs(), self.fx.saas_platform()))
    self.fx.reports.mkdir()
    empty = self.prepare(self.fx.payload(self.fx.saas_inputs(), self.fx.saas_platform(), run_id="merged-empty"))
    for label, result in (("missing", missing), ("empty", empty)):
      with self.subTest(case=label):
        self.assertEqual(result["status"], "READY", result["failures"])
        self.assertEqual(result["targets"][0]["start_candidates"], [])
        self.assertEqual(result["targets"][0]["start"]["source"], "earliest-merge-first-parent")

  def test_since_takes_priority_over_bound_prior_report(self):
    path = self.fx.report("saas", "12", "acme/saas", self.fx.c["m30"])
    result = self.prepare(self.fx.payload(
      self.fx.saas_inputs(), self.fx.saas_platform(),
      since=[f"acme/saas={self.fx.c['c0']}"], start_report=[path],
    ))
    self.assertEqual(result["status"], "READY", result["failures"])
    start = result["targets"][0]["start"]
    self.assertEqual(start["source"], "since")
    self.assertEqual(start["sha"], self.fx.c["c0"])
    self.assertEqual(result["targets"][0]["start_candidates"][0]["path"], path)

  def test_since_repo_key_matches_case_insensitively(self):
    repo = "Acme/SaaS"
    inputs = [pr_url(repo, "21"), pr_url(repo, "30")]
    platform = {
      f"github.com/{repo}#30": merged_response(repo, self.fx.c["m30"], self.fx.c["head30"], author="alice"),
      f"github.com/{repo}#21": merged_response(repo, self.fx.c["m21"], self.fx.c["head21"], author="bob"),
    }
    repos = {repo: {"checkout": str(self.fx.saas), "remote": "https://github.com/Acme/SaaS.git"}}
    result = self.prepare(self.fx.payload(
      inputs, platform, since=[f"acme/saas={self.fx.c['side']}"], repos=repos, run_id="since-case",
    ))
    self.assertEqual(result["status"], "READY", result["failures"])
    self.assertEqual(result["targets"][0]["start"]["source"], "since")
    self.assertEqual(result["targets"][0]["start"]["sha"], self.fx.c["side"])

if __name__ == "__main__":
  unittest.main()