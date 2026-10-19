#!/usr/bin/env python3
"""Unit tests for prepare_merge_review.py."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "prepare_merge_review.py"


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
  env = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
  }
  return subprocess.run(
    ["git", "-C", str(repo), *args],
    capture_output=True,
    text=True,
    check=check,
    env=env,
  )


class PrepareMergeReviewTests(unittest.TestCase):
  def setUp(self) -> None:
    self.tmp = tempfile.TemporaryDirectory(prefix="test-prepare-merge-review-")
    self.root = Path(self.tmp.name)
    self.repo = self.root / "repo"
    self.repo.mkdir()
    git(self.repo, "init", "-q", "-b", "main")

  def tearDown(self) -> None:
    self.tmp.cleanup()

  def write_and_stage(self, rel: str, content: str) -> None:
    target = self.repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    git(self.repo, "add", "--", rel)

  def run_helper(self, *extra_args: str) -> tuple[int, dict[str, object], str]:
    out_file = self.root / "bundle.txt"
    res = subprocess.run(
      ["python3", str(SCRIPT), "--repo", str(self.repo), "--out", str(out_file), "--json", *extra_args],
      capture_output=True,
      text=True,
      check=False,
    )
    data = json.loads(res.stdout) if res.returncode == 0 else {}
    bundle = out_file.read_text(encoding="utf-8") if out_file.exists() else ""
    return res.returncode, data, bundle

  def test_version_only_manifest_is_exempt_but_script_change_requires_review(self) -> None:
    self.write_and_stage(
      "package.json",
      '{\n  "name": "demo",\n  "version": "1.0.0",\n  "scripts": {\n    "test": "bun test"\n  }\n}\n',
    )
    self.write_and_stage(
      "web/package.json",
      '{\n  "name": "demo-web",\n  "version": "1.0.0",\n  "scripts": {\n    "test": "vitest"\n  }\n}\n',
    )
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "upstream")
    self.write_and_stage(
      "package.json",
      '{\n  "name": "demo",\n  "version": "1.1.0",\n  "scripts": {\n    "test": "bun test"\n  }\n}\n',
    )
    self.write_and_stage(
      "web/package.json",
      '{\n  "name": "demo-web",\n  "version": "1.1.0",\n  "scripts": {\n    "test": "vitest --run"\n  }\n}\n',
    )
    git(self.repo, "commit", "-q", "-m", "upstream 1.1.0")

    git(self.repo, "checkout", "-q", "main")
    self.write_and_stage(
      "package.json",
      '{\n  "name": "demo",\n  "version": "2.0.0",\n  "scripts": {\n    "test": "bun test"\n  }\n}\n',
    )
    self.write_and_stage(
      "web/package.json",
      '{\n  "name": "demo-web",\n  "version": "2.0.0",\n  "scripts": {\n    "test": "vitest"\n  }\n}\n',
    )
    git(self.repo, "commit", "-q", "-m", "fork 2.0.0")

    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    self.write_and_stage(
      "package.json",
      '{\n  "name": "demo",\n  "version": "2.0.0",\n  "scripts": {\n    "test": "bun test"\n  }\n}\n',
    )
    self.write_and_stage(
      "web/package.json",
      '{\n  "name": "demo-web",\n  "version": "2.0.0",\n  "scripts": {\n    "test": "vitest"\n  }\n}\n',
    )

    rc, summary, bundle = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    exempt_paths = [item["path"] for item in summary["mechanical_exempt"]]
    self.assertEqual(exempt_paths, ["package.json"])
    self.assertEqual(summary["review_files"], ["web/package.json"])
    self.assertIn("================ FILE: web/package.json ================", bundle)

    git(self.repo, "commit", "-q", "-m", "merge upstream")
    rc2, summary2, _ = self.run_helper("--commit", "HEAD")
    self.assertEqual(rc2, 0)
    self.assertEqual([item["path"] for item in summary2["mechanical_exempt"]], ["package.json"])
    self.assertEqual(summary2["review_files"], ["web/package.json"])

  def test_dictionary_and_changelog_verification(self) -> None:
    base_dict = "\n".join([f'  "k{i}": "v{i}",' for i in range(12)]) + "\n"
    self.write_and_stage("dict.ts", f"export const d = {{\n{base_dict}}};\n")
    self.write_and_stage(
      "CHANGELOG.md",
      "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- **Base fix.** Detail.\n",
    )
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "upstream")
    theirs_dict = base_dict.replace('"k5": "v5",', '"k5": "v5-up",\n  "k_up": "up",')
    self.write_and_stage("dict.ts", f"export const d = {{\n{theirs_dict}}};\n")
    self.write_and_stage(
      "CHANGELOG.md",
      "# Changelog\n\n## [Unreleased]\n\n## [1.1.0] - 2026-10-19\n\n### Fixed\n\n- **Upstream fix.** Detail.\n- **Base fix.** Detail.\n",
    )
    git(self.repo, "commit", "-q", "-m", "upstream")

    git(self.repo, "checkout", "-q", "main")
    ours_dict = base_dict.replace('"k5": "v5",', '"k5": "v5",\n  "k_fork": "fork",')
    self.write_and_stage("dict.ts", f"export const d = {{\n{ours_dict}}};\n")
    self.write_and_stage(
      "CHANGELOG.md",
      "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- **Fork fix.** Detail.\n\n## [2.0.0] - 2026-10-18\n\n### Fixed\n\n- **Base fix.** Detail.\n",
    )
    git(self.repo, "commit", "-q", "-m", "fork")

    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    merged_dict = base_dict.replace(
      '"k5": "v5",',
      '"k5": "v5-up",\n  "k_fork": "fork",\n  "k_up": "up",',
    )
    self.write_and_stage("dict.ts", f"export const d = {{\n{merged_dict}}};\n")
    self.write_and_stage(
      "CHANGELOG.md",
      "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- **Fork fix.** Detail.\n- **Upstream fix.** Detail.\n\n## [2.0.0] - 2026-10-18\n\n### Fixed\n\n- **Base fix.** Detail.\n",
    )
    git(self.repo, "commit", "-q", "-m", "merge clean")

    rc, summary, _ = self.run_helper("--commit", "HEAD")
    self.assertEqual(rc, 0)
    self.assertEqual(summary["review_files"], [])
    self.assertEqual(len(summary["mechanical_exempt"]), 2)


if __name__ == "__main__":
  unittest.main()
