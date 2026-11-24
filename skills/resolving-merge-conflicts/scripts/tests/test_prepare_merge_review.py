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

  def write_bytes_and_stage(self, rel: str, data: bytes) -> None:
    target = self.repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    git(self.repo, "add", "--", rel)

  def run_helper_raw(self, *extra_args: str, out_path: Path | None = None) -> tuple[int, str, str, str]:
    out_file = out_path if out_path is not None else (self.root / "bundle.txt")
    res = subprocess.run(
      ["python3", str(SCRIPT), "--repo", str(self.repo), "--out", str(out_file), "--json", *extra_args],
      capture_output=True,
      text=True,
      check=False,
    )
    bundle = out_file.read_text(encoding="utf-8") if out_file.is_file() else ""
    return res.returncode, res.stdout, res.stderr, bundle

  def run_helper(self, *extra_args: str) -> tuple[int, dict[str, object], str]:
    rc, stdout, _, bundle = self.run_helper_raw(*extra_args)
    data = json.loads(stdout) if rc == 0 else {}
    return rc, data, bundle

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

  def test_binary_and_non_utf8_conflicted_files_do_not_crash(self) -> None:
    self.write_bytes_and_stage("asset.png", b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x01")
    self.write_bytes_and_stage("latin1.txt", b"base\n")
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "upstream")
    self.write_bytes_and_stage("asset.png", b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x02")
    self.write_bytes_and_stage("latin1.txt", b"na\xefve\n")
    git(self.repo, "commit", "-q", "-m", "upstream")

    git(self.repo, "checkout", "-q", "main")
    self.write_bytes_and_stage("asset.png", b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x03")
    self.write_bytes_and_stage("latin1.txt", b"caf\xe9\n")
    git(self.repo, "commit", "-q", "-m", "main")

    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    self.write_bytes_and_stage("asset.png", b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x03")
    self.write_bytes_and_stage("latin1.txt", b"caf\xe9 + na\xefve\n")

    rc, summary, bundle = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    self.assertEqual(summary["review_files"], ["asset.png", "latin1.txt"])
    self.assertIn("================ FILE: asset.png ================", bundle)
    self.assertIn("================ FILE: latin1.txt ================", bundle)

  def test_non_ascii_and_leading_space_filenames_keep_exact_paths_and_diffs(self) -> None:
    p_nonascii = "文件/note.txt"
    p_space = " lead.txt"
    self.write_and_stage(p_nonascii, "base\n")
    self.write_and_stage(p_space, "base\n")
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "upstream")
    self.write_and_stage(p_nonascii, "upstream line\n")
    self.write_and_stage(p_space, "upstream space\n")
    git(self.repo, "commit", "-q", "-m", "upstream")

    git(self.repo, "checkout", "-q", "main")
    self.write_and_stage(p_nonascii, "ours line\n")
    self.write_and_stage(p_space, "ours space\n")
    git(self.repo, "commit", "-q", "-m", "main")

    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    self.write_and_stage(p_nonascii, "ours line\nupstream line\n")
    self.write_and_stage(p_space, "ours space\nupstream space\n")

    rc, summary, bundle = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    self.assertEqual(summary["review_files"], [p_space, p_nonascii])
    self.assertIn(f"================ FILE: {p_nonascii} ================", bundle)
    self.assertIn("+ours line", bundle)
    self.assertIn("+upstream line", bundle)
    self.assertIn(f"================ FILE: {p_space} ================", bundle)
    self.assertIn("+ours space", bundle)
    self.assertIn("+upstream space", bundle)

  def test_fatal_merge_tree_failure_is_not_an_empty_review(self) -> None:
    self.write_and_stage("file.txt", "base\n")
    git(self.repo, "commit", "-qm", "base")
    git(self.repo, "checkout", "-qb", "upstream")
    self.write_and_stage("file.txt", "upstream\n")
    git(self.repo, "commit", "-qm", "upstream")
    git(self.repo, "checkout", "-q", "main")
    self.write_and_stage("file.txt", "fork\n")
    git(self.repo, "commit", "-qm", "fork")
    self.assertEqual(git(self.repo, "merge", "--no-commit", "upstream", check=False).returncode, 1)
    self.write_and_stage("file.txt", "resolution\n")

    real_git = subprocess.check_output(["which", "git"], text=True).strip()
    stub = self.root / "git"
    stub.write_text(
      '#!/bin/sh\n'
      'subcommand=${3:-}\n'
      '[ "$subcommand" != -c ] || subcommand=${5:-}\n'
      'if [ "$subcommand" = merge-tree ]; then\n'
      '  [ -z "$MERGE_TREE_ERROR" ] || printf "%s\\n" "$MERGE_TREE_ERROR" >&2\n'
      '  exit 128\n'
      'fi\n'
      'exec "$REAL_GIT" "$@"\n',
      encoding="utf-8",
    )
    stub.chmod(0o700)
    out = self.root / "bundle.txt"
    for diagnostic in ("fixture merge-tree failure", ""):
      with self.subTest(diagnostic=diagnostic):
        result = subprocess.run(
          ["python3", str(SCRIPT), "--repo", str(self.repo), "--staged", "--out", str(out), "--json"],
          capture_output=True, text=True, check=False,
          env={**os.environ, "PATH": f"{self.root}:{os.environ['PATH']}",
               "REAL_GIT": real_git, "MERGE_TREE_ERROR": diagnostic},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(diagnostic or "128", result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse(out.exists())

  def test_pathless_split_directory_rename_conflict_fails_loudly(self) -> None:
    self.write_and_stage("old/a.txt", "a\n")
    self.write_and_stage("old/b.txt", "b\n")
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "upstream")
    self.write_and_stage("old/c.txt", "c\n")
    git(self.repo, "commit", "-q", "-m", "upstream adds old/c.txt")

    git(self.repo, "checkout", "-q", "main")
    (self.repo / "new1").mkdir(parents=True, exist_ok=True)
    (self.repo / "new2").mkdir(parents=True, exist_ok=True)
    git(self.repo, "mv", "old/a.txt", "new1/a.txt")
    git(self.repo, "mv", "old/b.txt", "new2/b.txt")
    git(self.repo, "commit", "-q", "-m", "main splits old dir")

    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    git(self.repo, "add", "-A")
    git(self.repo, "commit", "-q", "-m", "resolved split dir rename")

    rc, _, stderr, _ = self.run_helper_raw("--commit", "HEAD")
    self.assertEqual(rc, 2)
    self.assertIn("error:", stderr)

  def test_octopus_merge_is_rejected(self) -> None:
    self.write_and_stage("f.txt", "base\n")
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "b1")
    self.write_and_stage("b1.txt", "1\n")
    git(self.repo, "commit", "-q", "-m", "b1")

    git(self.repo, "checkout", "-q", "main")
    git(self.repo, "checkout", "-q", "-b", "b2")
    self.write_and_stage("b2.txt", "2\n")
    git(self.repo, "commit", "-q", "-m", "b2")

    git(self.repo, "checkout", "-q", "main")
    self.write_and_stage("m.txt", "m\n")
    git(self.repo, "commit", "-q", "-m", "main")

    git(self.repo, "merge", "--no-commit", "b1", "b2")
    rc_staged, _, stderr_staged, _ = self.run_helper_raw("--staged")
    self.assertEqual(rc_staged, 2)
    self.assertIn("error:", stderr_staged)

    git(self.repo, "commit", "-q", "-m", "octopus")
    rc, _, stderr, _ = self.run_helper_raw("--commit", "HEAD")
    self.assertEqual(rc, 2)
    self.assertIn("error:", stderr)

  def test_rejected_manifest_does_not_fall_through_to_dictionary_exemption(self) -> None:
    base_pkg = {
      "name": "demo",
      "version": "1.0.0",
      "description": "d",
      "main": "index.js",
      "license": "MIT",
      "author": "a",
      "private": True,
      "type": "module",
      "scripts": {"dev": "vite", "build": "tsc"},
      "dependencies": {"c": "1.0.0"},
    }
    self.write_and_stage("package.json", json.dumps(base_pkg, indent=2) + "\n")
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "upstream")
    up_pkg = json.loads(json.dumps(base_pkg))
    up_pkg["version"] = "1.1.0"
    up_pkg["dependencies"]["c"] = "1.1.0"
    up_pkg["dependencies"]["up_dep"] = "1.0.0"
    self.write_and_stage("package.json", json.dumps(up_pkg, indent=2) + "\n")
    git(self.repo, "commit", "-q", "-m", "upstream")

    git(self.repo, "checkout", "-q", "main")
    ours_pkg = json.loads(json.dumps(base_pkg))
    ours_pkg["scripts"]["dev"] = "vite --port 4000"
    ours_pkg["dependencies"]["fork_dep"] = "1.0.0"
    self.write_and_stage("package.json", json.dumps(ours_pkg, indent=2) + "\n")
    git(self.repo, "commit", "-q", "-m", "ours")

    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    broken_pkg = json.loads(json.dumps(ours_pkg))
    broken_pkg["version"] = "1.1.0"
    broken_pkg["dependencies"]["c"] = "1.1.0"
    broken_pkg["scripts"]["up_dep"] = "1.0.0"
    self.write_and_stage("package.json", json.dumps(broken_pkg, indent=2) + "\n")

    rc, summary, _ = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    self.assertEqual(summary["mechanical_exempt"], [])
    self.assertEqual(summary["review_files"], ["package.json"])

  def test_dictionary_rejects_duplicate_keys_without_markers(self) -> None:
    base_lines = [f'  "k{i}": "v{i}",' for i in range(12)]
    base_dup = '  "dup": "base1",\n' + "\n".join(base_lines) + '\n  "dup": "base2",\n'
    self.write_and_stage("dup.ts", f"export const d = {{\n{base_dup}}};\n")
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "upstream")
    self.write_and_stage("dup.ts", f"export const d = {{\n{base_dup.replace('base1', 'up1')}}};\n")
    git(self.repo, "commit", "-q", "-m", "upstream")

    git(self.repo, "checkout", "-q", "main")
    self.write_and_stage("dup.ts", f"export const d = {{\n{base_dup.replace('base1', 'ours1')}}};\n")
    git(self.repo, "commit", "-q", "-m", "ours")

    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    self.write_and_stage("dup.ts", f"export const d = {{\n{base_dup.replace('base1', 'ours1')}}};\n")

    rc, summary, _ = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    self.assertEqual(summary["mechanical_exempt"], [])
    self.assertEqual(summary["review_files"], ["dup.ts"])

  def test_dictionary_rejects_conflict_markers_and_broken_json(self) -> None:
    base_lines = [f'  "k{i}": "v{i}",' for i in range(12)]
    base_ts = "\n".join(base_lines) + "\n"
    self.write_and_stage("markers.ts", f"export const d = {{\n{base_ts}}};\n")

    base_json = "{\n" + "\n".join(base_lines[:-1]) + f'\n  "k11": "v11"\n}}\n'
    self.write_and_stage("bad.json", base_json)
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "upstream")
    self.write_and_stage("markers.ts", f"export const d = {{\n{base_ts.replace('v0', 'up0')}}};\n")
    self.write_and_stage("bad.json", base_json.replace('"k11": "v11"', '"k11": "v11",\n  "k_up": "up"'))
    git(self.repo, "commit", "-q", "-m", "upstream")

    git(self.repo, "checkout", "-q", "main")
    self.write_and_stage("markers.ts", f"export const d = {{\n{base_ts.replace('v0', 'ours0')}}};\n")
    self.write_and_stage("bad.json", base_json.replace('"k11": "v11"', '"k11": "v11",\n  "k_ours": "ours"'))
    git(self.repo, "commit", "-q", "-m", "ours")

    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    broken_markers = (
      "<<<<<<< HEAD\n"
      + f"export const d = {{\n{base_ts.replace('v0', 'ours0')}}};\n"
      + "=======\n"
      + f"export const d = {{\n{base_ts.replace('v0', 'up0')}}};\n"
      + ">>>>>>> upstream\n"
    )
    self.write_and_stage("markers.ts", broken_markers)
    # Invalid JSON syntax (dangling trailing comma) even though all KV lines match
    self.write_and_stage(
      "bad.json",
      "{\n" + "\n".join(base_lines) + '\n  "k_ours": "ours",\n  "k_up": "up",\n}\n',
    )

    rc, summary, _ = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    self.assertEqual(summary["mechanical_exempt"], [])
    self.assertEqual(summary["review_files"], ["bad.json", "markers.ts"])

  def _setup_changelog_conflict(self) -> None:
    self.write_and_stage("CHANGELOG.md", "# Changelog\n\n---\n\n- **Base.** Detail.\n")
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "upstream")
    self.write_and_stage(
      "CHANGELOG.md",
      "# Changelog\n\n---\n\n- **Upstream.** CRITICAL SECURITY DETAIL.\n- **Base.** Detail.\n",
    )
    git(self.repo, "commit", "-q", "-m", "upstream")

    git(self.repo, "checkout", "-q", "main")
    self.write_and_stage(
      "CHANGELOG.md",
      "# Changelog\n\n---\n\n- **Fork.** Detail.\n- **Base.** Detail.\n",
    )
    git(self.repo, "commit", "-q", "-m", "ours")

  def test_changelog_rejects_conflict_markers(self) -> None:
    self._setup_changelog_conflict()
    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    self.write_and_stage(
      "CHANGELOG.md",
      "# Changelog\n\n---\n\n- **Fork.** Detail.\n<<<<<<< HEAD\n- **Upstream.**\n=======\n>>>>>>> upstream\n- **Base.** Detail.\n",
    )
    rc, summary, _ = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    self.assertEqual(summary["mechanical_exempt"], [])
    self.assertEqual(summary["review_files"], ["CHANGELOG.md"])

  def test_changelog_rejects_truncated_bullet_without_markers(self) -> None:
    self._setup_changelog_conflict()
    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    self.write_and_stage(
      "CHANGELOG.md",
      "# Changelog\n\n---\n\n- **Fork.** Detail.\n- **Upstream.**\n- **Base.** Detail.\n",
    )
    rc, summary, _ = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    self.assertEqual(summary["mechanical_exempt"], [])
    self.assertEqual(summary["review_files"], ["CHANGELOG.md"])

  def test_changelog_rejects_deleted_hr_without_markers(self) -> None:
    self._setup_changelog_conflict()
    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    self.write_and_stage(
      "CHANGELOG.md",
      "# Changelog\n\n- **Fork.** Detail.\n- **Upstream.** CRITICAL SECURITY DETAIL.\n- **Base.** Detail.\n",
    )
    rc, summary, _ = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    self.assertEqual(summary["mechanical_exempt"], [])
    self.assertEqual(summary["review_files"], ["CHANGELOG.md"])

  def test_changelog_rejects_dropped_nonbold_bullet(self) -> None:
    self._setup_changelog_conflict()
    git(self.repo, "checkout", "-q", "upstream")
    self.write_and_stage(
      "CHANGELOG.md",
      "# Changelog\n\n---\n\n- Upstream critical fix\n- **Base.** Detail.\n",
    )
    git(self.repo, "commit", "-q", "--amend", "-m", "upstream nonbold")
    git(self.repo, "checkout", "-q", "main")
    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    self.write_and_stage(
      "CHANGELOG.md",
      "# Changelog\n\n---\n\n- **Fork.** Detail.\n- **Base.** Detail.\n",
    )
    rc, summary, _ = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    self.assertEqual(summary["mechanical_exempt"], [])
    self.assertEqual(summary["review_files"], ["CHANGELOG.md"])

  def test_stage_like_filename_prefix_works_in_staged_mode(self) -> None:
    fname = "1:dir/package.json"
    self.write_and_stage(fname, '{\n  "name": "demo",\n  "version": "1.0.0"\n}\n')
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "upstream")
    self.write_and_stage(fname, '{\n  "name": "demo",\n  "version": "1.1.0"\n}\n')
    git(self.repo, "commit", "-q", "-m", "upstream")

    git(self.repo, "checkout", "-q", "main")
    self.write_and_stage(fname, '{\n  "name": "demo",\n  "version": "2.0.0"\n}\n')
    git(self.repo, "commit", "-q", "-m", "ours")

    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    self.write_and_stage(fname, '{\n  "name": "demo",\n  "version": "2.0.0"\n}\n')

    rc, summary, _ = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    self.assertEqual([item["path"] for item in summary["mechanical_exempt"]], [fname])
    self.assertEqual(summary["review_files"], [])

  def test_out_handles_directory_error_cleanly_and_does_not_overwrite_symlink_target(self) -> None:
    self.write_and_stage("f.txt", "base\n")
    git(self.repo, "commit", "-q", "-m", "base")
    git(self.repo, "checkout", "-q", "-b", "upstream")
    self.write_and_stage("f.txt", "up\n")
    git(self.repo, "commit", "-q", "-m", "up")
    git(self.repo, "checkout", "-q", "main")
    self.write_and_stage("f.txt", "ours\n")
    git(self.repo, "commit", "-q", "-m", "ours")
    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    self.write_and_stage("f.txt", "ours\nup\n")

    out_dir = self.root / "out_is_dir"
    out_dir.mkdir()
    rc, _, stderr, _ = self.run_helper_raw("--staged", out_path=out_dir)
    self.assertEqual(rc, 2)
    self.assertIn("error:", stderr)
    self.assertNotIn("Traceback", stderr)

    target = self.root / "real_target.txt"
    target.write_text("KEEP_ME", encoding="utf-8")
    link = self.root / "out_link.txt"
    link.symlink_to(target)
    rc2, _, _, _ = self.run_helper_raw("--staged", out_path=link)
    self.assertEqual(rc2, 0)
    self.assertEqual(target.read_text(encoding="utf-8"), "KEEP_ME")

  def test_manifest_does_not_exempt_nested_dependency_version_changes(self) -> None:
    base_cargo = '[package]\nname = "demo"\nversion = "1.0.0"\n\n[dependencies.serde]\nversion = "1.0.100"\n'
    self.write_and_stage("Cargo.toml", base_cargo)
    git(self.repo, "commit", "-q", "-m", "base")

    git(self.repo, "checkout", "-q", "-b", "upstream")
    self.write_and_stage("Cargo.toml", base_cargo.replace('version = "1.0.100"', 'version = "2.0.0"'))
    git(self.repo, "commit", "-q", "-m", "upstream serde 2.0.0")

    git(self.repo, "checkout", "-q", "main")
    ours_cargo = base_cargo.replace('version = "1.0.100"', 'version = "1.0.150"')
    self.write_and_stage("Cargo.toml", ours_cargo)
    git(self.repo, "commit", "-q", "-m", "ours serde 1.0.150")

    git(self.repo, "merge", "--no-commit", "upstream", check=False)
    self.write_and_stage("Cargo.toml", ours_cargo)

    rc, summary, _ = self.run_helper("--staged")
    self.assertEqual(rc, 0)
    self.assertEqual(summary["mechanical_exempt"], [])
    self.assertEqual(summary["review_files"], ["Cargo.toml"])


if __name__ == "__main__":
  unittest.main()
