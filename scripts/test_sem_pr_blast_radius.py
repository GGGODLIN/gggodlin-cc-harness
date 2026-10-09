#!/usr/bin/env python3

import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCRIPT = ROOT / "sem-pr-blast-radius.sh"
TARGETS_TEST = ROOT / "test_pr_review_targets.py"
FAKE_SEM = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_SEM_LOG"], "a") as handle:
  handle.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1] == "diff":
  print(json.dumps({"changes": [
    {"changeType": "modified", "entityType": "function", "entityId": "in-range",
     "entityName": "inRange", "filePath": "shared.txt"},
    {"changeType": "modified", "entityType": "function", "entityId": "out-of-range",
     "entityName": "outOfRange", "filePath": "side0.txt"},
  ]}))
else:
  print(json.dumps({"dependents": [{"type": "code"}], "tests": []}))
"""


def load_targets_test():
  spec = importlib.util.spec_from_file_location("test_pr_review_targets", TARGETS_TEST)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


class SemBlastRadiusRangeTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.addCleanup(self.tmp.cleanup)
    base = Path(self.tmp.name)
    self.targets_test = load_targets_test()
    self.fx = self.targets_test.MergedFixture(base / "fixture")
    prepared = self.targets_test.run_cli("prepare", self.fx.payload(
      self.fx.saas_inputs(), self.fx.saas_platform(), since=[f"acme/saas={self.fx.c['side']}"]))
    self.assertEqual(prepared["status"], "READY", prepared["failures"])
    self.target = prepared["targets"][0]
    self.targets_test.git(self.fx.saas, "worktree", "add", "-q", "--detach",
                          self.target["review_root"], self.target["end"]["sha"])
    bin_dir = base / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "sem"
    fake.write_text(FAKE_SEM)
    fake.chmod(0o755)
    self.log = base / "sem.log"
    self.env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                "FAKE_SEM_LOG": str(self.log), "SEM_CACHE_DIR": str(base / "cache")}

  def run_script(self, *args):
    proc = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=self.env)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    calls = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
    return proc.stdout, calls

  def diff_from(self, calls):
    diff = next(call for call in calls if call[0] == "diff")
    return diff[diff.index("--from") + 1]

  def test_range_caller_compares_against_start_without_merge_base(self):
    start = self.target["start"]["sha"]
    merge_base = self.targets_test.git(self.fx.saas, "merge-base", start, self.target["end"]["sha"])
    self.assertNotEqual(merge_base, start)
    output, calls = self.run_script(self.target["review_root"], start, self.target["review_diff"]["file"])
    self.assertEqual(self.diff_from(calls), start)
    self.assertIn("inRange", output)
    self.assertNotIn("outOfRange", output)
    print(f"sem range base={self.diff_from(calls)} start={start} merge_base={merge_base}")

  def test_pr_caller_still_resolves_merge_base(self):
    start = self.target["start"]["sha"]
    merge_base = self.targets_test.git(self.fx.saas, "merge-base", start, self.target["end"]["sha"])
    _, calls = self.run_script(self.target["review_root"], start)
    self.assertEqual(self.diff_from(calls), merge_base)


if __name__ == "__main__":
  unittest.main()
