#!/usr/bin/env python3

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TARGETS_SCRIPT = ROOT / "pr-review-targets.py"
GROUP_SCRIPT = ROOT / "pr-review-group-report.py"
SCRIPT = ROOT / "pr-review-gemini-web.py"
TARGETS_TEST = ROOT / "test_pr_review_targets.py"
SAAS_REMOTE = "https://github.com/acme/saas.git"
DASH_REMOTE = "https://github.com/acme/dashboard.git"
SPEC_SHARED = "SHARED-SPEC\nline two\n"


def git(root, *args):
  proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
  if proc.returncode != 0:
    raise AssertionError(f"git {' '.join(args)} in {root} failed: {proc.stderr}")
  return proc.stdout.strip()


def run_cli(path, mode, payload):
  proc = subprocess.run(
    [sys.executable, str(path), mode],
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
    self.commits["saas_a"] = self._commit(self.saas, "a.ts", "const a = 1\n")
    git(self.saas, "checkout", "-q", "-b", "feat11")
    self.commits["saas_11"] = self._commit(self.saas, "a.ts", "const a = 1\nconst b = 2\n")
    git(self.saas, "checkout", "-q", "-b", "feat12")
    self.commits["saas_12"] = self._commit(self.saas, "shared.ts", "export const shared = 1\n")
    for name, ref in (("master", "saas_a"), ("feat11", "saas_11"), ("feat12", "saas_12")):
      git(self.saas, "update-ref", f"refs/remotes/origin/{name}", self.commits[ref])
    git(self.saas, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")

  def _build_dashboard(self):
    self._init(self.dashboard, DASH_REMOTE)
    self.commits["dash_a"] = self._commit(self.dashboard, "shared.ts", "export const shared = 0\n")
    git(self.dashboard, "checkout", "-q", "-b", "feat707")
    self.commits["dash_707"] = self._commit(self.dashboard, "shared.ts", "export const shared = 2\n")
    git(self.dashboard, "update-ref", "refs/remotes/origin/master", self.commits["dash_a"])
    git(self.dashboard, "update-ref", "refs/remotes/origin/feat707", self.commits["dash_707"])
    git(self.dashboard, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")

  def platform_ok(self, repo, head, base_ref, base, files, diff_lines, specs, head_ref, extra=None):
    entry = {
      "status": "ok", "destination_repo": repo, "source_repo": repo,
      "head": head, "head_ref": head_ref, "base_ref": base_ref, "base": base,
      "changed_files": files, "diff_lines": diff_lines,
      "specs": [{"path": path, "content": content} for path, content in (specs or [])],
    }
    if extra:
      entry.update(extra)
    return entry

  def payload(self, inputs, platform, run_id="run-01"):
    return {
      "run_id": run_id,
      "state_root": str(self.state_root),
      "profile_path": str(self.profile),
      "inputs": inputs,
      "current_repo": {"remote": SAAS_REMOTE},
      "repos": {"acme/saas": {"checkout": str(self.saas), "remote": SAAS_REMOTE},
                "acme/dashboard": {"checkout": str(self.dashboard), "remote": DASH_REMOTE}},
      "platform": platform,
    }

  def inputs(self):
    return [
      {"raw": "https://github.com/acme/saas/pull/11", "named_in_conversation": True},
      {"raw": "https://github.com/acme/dashboard/pull/707", "named_in_conversation": True},
    ]

  def platform(self):
    return {
      "github.com/acme/saas#11": self.platform_ok(
        "acme/saas", self.commits["saas_11"], "master", self.commits["saas_a"],
        ["a.ts"], 4, [], head_ref="feat11",
      ),
      "github.com/acme/dashboard#707": self.platform_ok(
        "acme/dashboard", self.commits["dash_707"], "master", self.commits["dash_a"],
        ["shared.ts"], 4, [], head_ref="feat707",
      ),
    }

  def prepare(self, run_id="run-01"):
    result = run_cli(TARGETS_SCRIPT, "prepare", self.payload(self.inputs(), self.platform(), run_id))
    assert result["status"] == "READY", json.dumps(result, ensure_ascii=False)
    return result


def load_targets_test():
  spec = importlib.util.spec_from_file_location("test_pr_review_targets", TARGETS_TEST)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


class RangeTargetMaterialsTest(unittest.TestCase):
  def setUp(self):
    self._tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self._tmp.cleanup)
    targets_test = load_targets_test()
    self.fx = targets_test.MergedFixture(self._tmp.name)
    self.prepared = targets_test.run_cli("prepare", self.fx.payload(
      self.fx.saas_inputs(), self.fx.saas_platform(), since=[f"acme/saas={self.fx.c['side']}"]))
    self.assertEqual(self.prepared["status"], "READY", self.prepared["failures"])
    self.target = self.prepared["targets"][0]
    self.whole = git(self.fx.saas, "diff", f"{self.fx.c['side']}..{self.fx.c['tail']}")

  def finalized(self, seat, angle):
    return run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": seat, "angle": angle}], "adjudication": {},
    })

  def test_web_inlines_exactly_the_prepared_range_diff(self):
    finalized = self.finalized("web-gpt", "web GPT Pro")
    result = run_cli(SCRIPT, "materials", {
      "preparation_path": finalized["preparation_path"], "channel": "web-gpt", "confirmation": True})
    self.assertEqual(result["status"], "OK", result)
    prompt = result["executions"][0]["prompt"]
    blocks = re.findall(r"```diff\n(.*?)\n```", prompt, re.S)
    self.assertEqual(len(blocks), 1)
    received = blocks[0] + "\n"
    expected = Path(self.target["review_diff"]["file"]).read_text()
    self.assertEqual(received, expected)
    self.assertNotEqual(self.whole, expected)
    self.assertIn("side0.txt", self.whole)
    self.assertNotIn("side0.txt", prompt)
    self.assertNotIn("other.txt", prompt)
    self.assertIn(self.fx.c["side"], prompt)
    self.assertIn(self.fx.c["tail"], prompt)
    self.assertNotIn("authored_diff_base", prompt)
    print(f"web diff bytes={len(received.encode('utf-8'))} prepared={self.target['review_diff']['file']}")

  def test_gemini_points_at_exactly_the_prepared_range_diff(self):
    finalized = self.finalized("agy", "Gemini Pro")
    result = run_cli(SCRIPT, "materials", {
      "preparation_path": finalized["preparation_path"], "channel": "gemini-pro", "confirmation": True})
    self.assertEqual(result["status"], "OK", result)
    execution = result["executions"][0]
    prompt = execution["prompt"]
    diff_file = self.target["review_diff"]["file"]
    self.assertIn(diff_file, prompt)
    self.assertNotIn("sha256", prompt)
    add_dirs = [execution["argv"][index + 1] for index, arg in enumerate(execution["argv"])
                if arg == "--add-dir"]
    self.assertIn(str(Path(diff_file).parent), add_dirs)
    self.assertIn(self.target["review_root"], add_dirs)
    self.assertIn(self.fx.c["side"], prompt)
    self.assertIn(self.fx.c["tail"], prompt)
    self.assertNotIn("authored_diff_base", prompt)
    packet = json.loads(Path(result["packet_path"]).read_text())
    self.assertEqual(packet["targets"][0]["review_diff"], self.target["review_diff"])
    print(f"gemini diff file={diff_file}")

  def test_gemini_range_boundary_matches_the_spec_review_boundary(self):
    finalized = self.finalized("agy", "Gemini Pro")
    result = run_cli(SCRIPT, "materials", {
      "preparation_path": finalized["preparation_path"], "channel": "gemini-pro", "confirmation": True})
    self.assertEqual(result["status"], "OK", result)
    prompt = result["executions"][0]["prompt"]
    self.assertNotIn("review only the files it touches", prompt)
    for needle in (
      "the review_diff file is the authoritative scoped diff",
      "Start from the files the review_diff touches",
      "unchanged code in affected flows may be reported together with its relationship to the change",
      "check output → type → consumer",
      "never run git diff or merge-base yourself",
    ):
      with self.subTest(needle=needle):
        self.assertIn(needle, prompt)

  def test_unreadable_review_diff_for_the_web_channel_is_a_structured_error(self):
    finalized = self.finalized("web-gpt", "web GPT Pro")
    Path(self.target["review_diff"]["file"]).unlink()
    proc = subprocess.run(
      [sys.executable, str(SCRIPT), "materials"],
      input=json.dumps({"preparation_path": finalized["preparation_path"], "channel": "web-gpt",
                        "confirmation": True}),
      capture_output=True, text=True,
    )
    self.assertNotIn("Traceback", proc.stderr)
    self.assertEqual(proc.returncode, 1)
    self.assertEqual(json.loads(proc.stdout), {"status": "ERROR", "reason_codes": ["INVALID_INPUT_JSON"]})


class PrReviewGeminiWebTest(unittest.TestCase):
  def setUp(self):
    self._tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self._tmp.cleanup)
    self.fx = Fixture(self._tmp.name)
    self.prepared = self.fx.prepare()

  def target(self, pr):
    return next(item for item in self.prepared["targets"] if item["pr"] == pr)

  def channel_payload(self, channel, **extra):
    payload = {"preparation_path": self.prepared["preparation_path"], "channel": channel}
    payload.update(extra)
    return payload

  def finalized_flash(self):
    return run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "agy", "angle": "Gemini Flash"}],
    })

  def test_gemini_one_execution_carries_every_root_and_its_version(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "agy", "angle": "Gemini Pro"}],
    })
    result = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-pro", preparation_path=finalized["preparation_path"], confirmation=True))
    self.assertEqual(result["status"], "OK")
    self.assertEqual(len(result["executions"]), 1)
    execution = result["executions"][0]
    self.assertEqual(execution["command"], "agy")
    argv = execution["argv"]
    print_args = [arg for arg in argv if str(arg).startswith("--print=")]
    self.assertEqual(len(print_args), 1)
    prompt_value = print_args[0].split("=", 1)[1]
    self.assertIn("DO NOT ASK FOR CONFIRMATION", prompt_value)
    self.assertFalse(prompt_value.endswith(".txt"))
    for target in self.prepared["targets"]:
      self.assertIn(target["target_identity"], prompt_value)
      self.assertIn(target["head"], prompt_value)
      self.assertIn(target["base"], prompt_value)
      self.assertIn(target["review_root"], prompt_value)
    add_dir_values = [argv[index + 1] for index, arg in enumerate(argv) if arg == "--add-dir"]
    self.assertEqual(
      sorted(add_dir_values),
      sorted(target["review_root"] for target in self.prepared["targets"]),
    )
    self.assertTrue(any(arg == "--dangerously-skip-permissions" for arg in argv))
    model_arg = next(arg for arg in argv if str(arg).startswith("--model"))
    self.assertEqual(model_arg.split("=", 1)[1], "Gemini 4 Argon (High)")
    self.assertEqual(execution["requested_model"], "Gemini 4 Argon (High)")
    self.assertEqual(execution["stdin"], "/dev/null")
    self.assertEqual(execution["prompt"], prompt_value)
    self.assertNotIn("prompt_file", execution)
    self.assertNotIn("prompt_file", result)
    packet_path = Path(result["packet_path"])
    packet = json.loads(packet_path.read_text())
    self.assertEqual(packet["executions"][0]["prompt"], prompt_value)
    self.assertEqual(list(packet_path.parent.glob("*-prompt.txt")), [])
    self.assertEqual(len(result["targets"]), 2)

  def test_unselected_channel_dispatches_zero(self):
    result = run_cli(SCRIPT, "materials", self.channel_payload("gemini-pro", confirmation=True))
    self.assertEqual(result["status"], "NOT_DISPATCHABLE")
    self.assertEqual(result["reason"], "selection-required")
    self.assertEqual(result["executions"], [])
    self.assertEqual(result["dispatch_call_count"], 0)

  def test_selected_without_confirmation_dispatches_zero(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "agy", "angle": "Gemini Pro"}],
    })
    result = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-pro", preparation_path=finalized["preparation_path"]))
    self.assertEqual(result["status"], "NOT_DISPATCHABLE")
    self.assertEqual(result["reason"], "awaiting-confirmation")
    self.assertEqual(result["executions"], [])
    self.assertEqual(result["dispatch_call_count"], 0)

  def test_selected_with_confirmation_dispatches_once(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "agy", "angle": "Gemini Pro"}],
    })
    result = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-pro", preparation_path=finalized["preparation_path"], confirmation=True))
    self.assertEqual(result["status"], "OK")
    self.assertEqual(result["dispatch_call_count"], 1)

  def test_other_seat_selected_does_not_unlock_this_channel(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "opus/code-reviewer", "angle": "context-aware primary"}],
    })
    result = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-pro", preparation_path=finalized["preparation_path"], confirmation=True))
    self.assertEqual(result["status"], "NOT_DISPATCHABLE")
    self.assertEqual(result["reason"], "seat-not-selected")
    self.assertEqual(result["executions"], [])
    self.assertEqual(result["dispatch_call_count"], 0)

  def test_flash_without_model_is_model_unavailable(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "agy", "angle": "Gemini Flash"}],
    })
    saved = os.environ.pop("GEMINI_FLASH_MODEL", None)
    try:
      result = run_cli(SCRIPT, "materials", self.channel_payload(
        "gemini-flash", preparation_path=finalized["preparation_path"], confirmation=True))
    finally:
      if saved is not None:
        os.environ["GEMINI_FLASH_MODEL"] = saved
    self.assertEqual(result["status"], "MODEL_UNAVAILABLE")
    self.assertEqual(result["executions"], [])
    self.assertEqual(result["dispatch_call_count"], 0)

  def test_web_one_send_carries_labeled_full_text_diff_without_local_paths(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "web-gpt", "angle": "web GPT Pro"}],
    })
    result = run_cli(SCRIPT, "materials", self.channel_payload(
      "web-gpt", preparation_path=finalized["preparation_path"], confirmation=True))
    self.assertEqual(result["status"], "OK")
    self.assertEqual(len(result["executions"]), 1)
    execution = result["executions"][0]
    self.assertEqual(execution["command"], "web-cli")
    self.assertFalse(execution["local_paths_available"])
    prompt = execution["prompt"]
    for target in self.prepared["targets"]:
      self.assertIn(target["target_identity"], prompt)
    diff = git(self.fx.dashboard, "diff", f"{self.target('707')['authored_diff_base']}..{self.target('707')['head']}")
    self.assertIn(diff, prompt)
    self.assertIn("-export const shared = 0", prompt)
    self.assertIn("+export const shared = 2", prompt)
    self.assertNotIn('"--add-dir"', json.dumps(execution["argv"]))
    fetch_argv = execution["fetch_argv"]
    self.assertIn("<conversation-id>", fetch_argv)
    self.assertEqual(fetch_argv.index("<conversation-id>"), fetch_argv.index("detail") + 1)
    self.assertIn("--markdown", fetch_argv)

  def test_undecided_capacity_stops_before_dispatch_with_zero_executions(self):
    bulk = self.fx.platform()
    bulk["github.com/acme/saas#11"]["changed_files"] = [f"src/f{index}.ts" for index in range(40)]
    bulk["github.com/acme/saas#11"]["diff_lines"] = 900
    prepared = run_cli(TARGETS_SCRIPT, "prepare", self.fx.payload(self.fx.inputs(), bulk, run_id="run-big"))
    self.assertEqual(prepared["status"], "READY")
    selection = [{"seat": "agy", "angle": "Gemini Pro"}]
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": prepared["preparation_path"], "selection": selection,
    })
    self.assertEqual(finalized["capacity"]["decision"], "awaiting-adjudication")
    result = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-pro", preparation_path=finalized["preparation_path"], confirmation=True))
    self.assertEqual(result["status"], "NEEDS_DECISION")
    self.assertEqual(result["executions"], [])
    self.assertEqual(result["dispatch_call_count"], 0)
    self.assertIn("Gemini Pro", result["waiting_angles"])
    adjudicated = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": prepared["preparation_path"],
      "adjudication": {
        "github:github.com/acme/saas#11": "accept-incomplete",
        "review_set": "accept-incomplete",
      },
    })
    result = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-pro", preparation_path=adjudicated["preparation_path"], confirmation=True))
    self.assertEqual(result["status"], "OK")
    self.assertEqual(len(result["executions"]), 1)

  def test_selection_and_model_are_kept_and_no_extra_channel_appears(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "agy", "angle": "Gemini Flash"}],
    })
    result = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-flash", preparation_path=finalized["preparation_path"],
      model="gemini-3.8-flash-high", confirmation=True))
    self.assertEqual(result["status"], "OK")
    self.assertEqual(result["channel"], "gemini-flash")
    self.assertEqual(result["angle"], "Gemini Flash")
    self.assertEqual(result["seat"], "agy")
    self.assertEqual(result["model"], "gemini-3.8-flash-high")
    execution = result["executions"][0]
    model_arg = next(arg for arg in execution["argv"] if str(arg).startswith("--model"))
    self.assertEqual(model_arg.split("=", 1)[1], "gemini-3.8-flash-high")
    commands = {item["command"] for item in result["executions"]}
    self.assertEqual(commands, {"agy"})

  def test_findings_map_uniquely_across_targets_and_ambiguity_is_never_guessed(self):
    saas_root = self.target("11")["review_root"]
    dash_root = self.target("707")["review_root"]
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "agy", "angle": "Gemini Pro"}],
    })
    packet = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-pro", preparation_path=finalized["preparation_path"], confirmation=True))
    reply = {"status": "ok", "model": "gemini-4-argon-high", "output": json.dumps([
      {"severity": "HIGH", "file": f"{dash_root}/shared.ts", "line": 1, "line_end": 1,
       "title": "value dropped", "body": "shared value collides across targets",
       "confidence": 0.8, "anchor": "export const shared = 2"},
      {"severity": "LOW", "file": "shared.ts", "line": 1, "line_end": 1,
       "title": "ambiguous file", "body": "same name in two targets", "confidence": 0.9,
       "anchor": "export const shared = 2"},
      {"severity": "MEDIUM", "target": "github:github.com/acme/saas#11", "file": f"{dash_root}/shared.ts",
       "line": 1, "title": "cross label mismatch", "body": "absolute path under another root",
       "confidence": 0.9, "anchor": "export const shared = 2"},
    ])}
    result = run_cli(SCRIPT, "collect", {"packet_path": packet["packet_path"], "reply": reply})
    self.assertEqual(result["status"], "OK")
    self.assertEqual(len(result["findings"]), 1)
    self.assertEqual(result["findings"][0]["target_identity"], "github:github.com/acme/dashboard#707")
    self.assertEqual(result["findings"][0]["file"], "shared.ts")
    self.assertEqual(result["findings"][0]["source"], "gemini")
    unmapped_files = sorted(item["file"] for item in result["unmapped_findings"])
    self.assertEqual(unmapped_files, sorted(["shared.ts", f"{dash_root}/shared.ts"]))
    for item in result["unmapped_findings"]:
      self.assertNotIn("target_identity", item)

  def test_web_labels_map_and_unlabeled_findings_stay_unmapped(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "web-gpt", "angle": "web GPT Pro"}],
    })
    packet = run_cli(SCRIPT, "materials", self.channel_payload(
      "web-gpt", preparation_path=finalized["preparation_path"], confirmation=True))
    reply = {"status": "ok", "model": "web-gpt-pro", "output": json.dumps([
      {"severity": "HIGH", "target": "github:github.com/acme/saas#11", "file": "a.ts",
       "line": 2, "title": "guard missing", "body": "no null guard", "confidence": 0.9,
       "anchor": "const b = 2"},
      {"severity": "MEDIUM", "file": "a.ts", "line": 2, "title": "no label",
       "body": "unclear target", "confidence": 0.7, "anchor": "const b = 2"},
    ])}
    result = run_cli(SCRIPT, "collect", {"packet_path": packet["packet_path"], "reply": reply})
    self.assertEqual(result["status"], "OK")
    self.assertEqual(result["findings"][0]["target_identity"], "github:github.com/acme/saas#11")
    self.assertEqual(result["findings"][0]["source"], "web")
    self.assertEqual(len(result["unmapped_findings"]), 1)

  def test_fixed_failure_replies_report_unverified_and_keep_other_channels(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "agy", "angle": "Gemini Pro"}],
    })
    packet = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-pro", preparation_path=finalized["preparation_path"], confirmation=True))
    mismatch = run_cli(SCRIPT, "collect", {
      "packet_path": packet["packet_path"],
      "reply": {"status": "ok", "model": "gemini-3.8-flash-high", "output": "[]"},
    })
    self.assertEqual(mismatch["status"], "FAILED")
    self.assertEqual(mismatch["reason"], "model-mismatch")
    self.assertEqual(mismatch["findings"], [])
    self.assertFalse(mismatch["verified"])
    self.assertEqual(mismatch["unverified"], True)

    timeout = run_cli(SCRIPT, "collect", {
      "packet_path": packet["packet_path"],
      "reply": {"status": "error", "reason": "timeout", "model": "gemini-4-argon-high", "output": ""},
    })
    self.assertEqual(timeout["status"], "FAILED")
    self.assertEqual(timeout["reason"], "timeout")

    packet_flash = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-flash", model="gemini-3.8-flash-high", confirmation=True,
      preparation_path=self.finalized_flash()["preparation_path"]))
    parse_fail = run_cli(SCRIPT, "collect", {
      "packet_path": packet_flash["packet_path"],
      "reply": {"status": "ok", "model": "gemini-3.8-flash-high",
                "output": "I have some prose findings, trust me."},
    })
    self.assertEqual(parse_fail["status"], "FAILED")
    self.assertEqual(parse_fail["reason"], "parse-failure")
    self.assertTrue(parse_fail["raw_output"])
    combined = run_cli(SCRIPT, "merge", {"channel_results": [parse_fail]})
    self.assertEqual(combined["findings"], [])
    self.assertEqual(
      [item["channel"] for item in combined["failed_channels"]], ["gemini-flash"],
    )

  def test_collect_findings_feed_the_common_group_report(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "agy", "angle": "Gemini Pro"}],
    })
    packet = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-pro", preparation_path=finalized["preparation_path"], confirmation=True))
    reply = {"status": "ok", "model": "gemini-4-argon-high", "output": json.dumps([
      {"severity": "HIGH", "file": f"{self.target('11')['review_root']}/a.ts", "line": 2,
       "line_end": 2, "title": "no guard", "body": "b is added without a guard",
       "confidence": 0.9, "anchor": "const b = 2"},
    ])}
    result = run_cli(SCRIPT, "collect", {"packet_path": packet["packet_path"], "reply": reply})
    rendered = subprocess.run(
      [sys.executable, str(GROUP_SCRIPT), "render"],
      input=json.dumps({
        "set_identity": self.prepared["set_identity"],
        "targets": [{"target_identity": target["target_identity"], "head": target["head"],
                     "base": target["base"], "version_state": "current"}
                    for target in self.prepared["targets"]],
        "findings": result["findings"],
      }),
      capture_output=True, text=True,
    )
    self.assertEqual(rendered.returncode, 0, rendered.stderr)
    draft = rendered.stdout
    self.assertIn("github:github.com/acme/saas#11", draft)
    self.assertIn("| gemini |", draft)
    self.assertIn("F-01", draft)

  def test_reports_never_claim_runtime_model_verification(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "agy", "angle": "Gemini Pro"}],
    })
    packet = run_cli(SCRIPT, "materials", self.channel_payload(
      "gemini-pro", preparation_path=finalized["preparation_path"], confirmation=True))
    reply = {"status": "ok", "model": "gemini-4-argon-high", "output": "[]"}
    result = run_cli(SCRIPT, "collect", {"packet_path": packet["packet_path"], "reply": reply})
    self.assertNotIn("observed_model", json.dumps(result))
    self.assertIn("reported_model", json.dumps(result))

  def test_incompatible_interface_is_reported_before_dispatch(self):
    finalized = run_cli(TARGETS_SCRIPT, "finalize", {
      "preparation_path": self.prepared["preparation_path"],
      "selection": [{"seat": "web-gpt", "angle": "web GPT Pro"}],
    })
    result = run_cli(SCRIPT, "materials", self.channel_payload(
      "web-gpt", preparation_path=finalized["preparation_path"], confirmation=True, interface={
        "web-cli_chatgpt_ask": False,
      }))
    self.assertEqual(result["status"], "INCOMPATIBLE_INTERFACE")
    self.assertEqual(result["executions"], [])


if __name__ == "__main__":
  unittest.main()
