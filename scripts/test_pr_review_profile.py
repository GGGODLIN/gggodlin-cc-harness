#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("pr-review-profile.py")

SAMPLE_YAML = """\
acme/saas:
  trunk: develop
  spec_globs:
    - docs/specs/*-design.md
    - docs/plans/*.md
  conventions_docs:
    - CLAUDE.md
    - docs/domain.md
acme/dashboard:
  trunk: develop
  spec_globs:
    - .scratch/*/spec.md
acme/no-trunk:
  spec_globs:
    - docs/*.md
acme/authored:
  trunk: develop
  authority:
    live: docs/pages/*.md
    change:
      - .scratch/*/spec.md
      - docs/specs/*.md
acme/live-only:
  trunk: develop
  authority:
    live:
      - docs/pages/*.md
"""


def run(remote, yaml_text):
  with tempfile.TemporaryDirectory() as tmp:
    yaml_path = Path(tmp) / "repos.yaml"
    yaml_path.write_text(yaml_text)
    proc = subprocess.run(
      [sys.executable, str(SCRIPT), "--remote", remote, "--profile", str(yaml_path)],
      capture_output=True,
      text=True,
    )
    return proc, str(yaml_path)


NO_AUTHORITY = {"live": [], "change": []}
DEFAULT = {
  "trunk": None,
  "spec_globs": [],
  "conventions_docs": [],
  "authority": NO_AUTHORITY,
  "source": "default",
}


class ProfileResolverTest(unittest.TestCase):
  def test_https_remote_resolves_full_profile(self):
    proc, yaml_path = run("https://github.com/acme/saas.git", SAMPLE_YAML)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout), {
      "trunk": "develop",
      "spec_globs": ["docs/specs/*-design.md", "docs/plans/*.md"],
      "conventions_docs": ["CLAUDE.md", "docs/domain.md"],
      "authority": NO_AUTHORITY,
      "source": yaml_path,
    })
    ssh, _ = run("git@github.com:acme/saas.git", SAMPLE_YAML)
    self.assertEqual(json.loads(ssh.stdout)["trunk"], "develop")

  def test_optional_fields_default_to_empty(self):
    proc, yaml_path = run("https://github.com/acme/dashboard.git", SAMPLE_YAML)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout), {
      "trunk": "develop",
      "spec_globs": [".scratch/*/spec.md"],
      "conventions_docs": [],
      "authority": NO_AUTHORITY,
      "source": yaml_path,
    })

  def test_unknown_remote_returns_default(self):
    proc, _ = run("https://github.com/acme/unknown.git", SAMPLE_YAML)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout), DEFAULT)

  def test_missing_trunk_returns_default(self):
    proc, _ = run("https://github.com/acme/no-trunk.git", SAMPLE_YAML)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout), DEFAULT)

  def test_missing_profile_file_returns_default(self):
    proc = subprocess.run(
      [sys.executable, str(SCRIPT), "--remote", "https://github.com/acme/saas.git",
       "--profile", "/nonexistent/repos.yaml"],
      capture_output=True, text=True,
    )
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout), DEFAULT)

  def test_empty_remote_returns_default(self):
    proc, _ = run("", SAMPLE_YAML)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout), DEFAULT)

  def test_invalid_yaml_exits_nonzero(self):
    proc, _ = run("https://github.com/acme/saas.git", "acme/saas: [unclosed\n  trunk: x\n")
    self.assertNotEqual(proc.returncode, 0)
    self.assertEqual(proc.stdout, "")
    self.assertIn("repos.yaml", proc.stderr)

  def test_scalar_list_field_is_a_clear_error_not_a_traceback(self):
    proc, _ = run("https://github.com/acme/saas.git", "acme/saas:\n  trunk: develop\n  spec_globs: 5\n")
    self.assertNotEqual(proc.returncode, 0)
    self.assertEqual(proc.stdout, "")
    self.assertIn("spec_globs", proc.stderr)
    self.assertNotIn("Traceback", proc.stderr)

  def test_authority_string_and_list_both_resolve_to_lists(self):
    proc, _ = run("https://github.com/acme/authored.git", SAMPLE_YAML)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout)["authority"], {
      "live": ["docs/pages/*.md"],
      "change": [".scratch/*/spec.md", "docs/specs/*.md"],
    })

  def test_authority_with_one_side_missing_defaults_that_side_to_empty(self):
    proc, _ = run("https://github.com/acme/live-only.git", SAMPLE_YAML)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout)["authority"], {"live": ["docs/pages/*.md"], "change": []})

  def test_missing_authority_resolves_to_empty_lists(self):
    proc, _ = run("https://github.com/acme/saas.git", SAMPLE_YAML)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout)["authority"], {"live": [], "change": []})

  def test_numeric_authority_live_is_a_clear_error_not_a_traceback(self):
    proc, _ = run("https://github.com/acme/saas.git", "acme/saas:\n  trunk: develop\n  authority:\n    live: 5\n")
    self.assertNotEqual(proc.returncode, 0)
    self.assertEqual(proc.stdout, "")
    self.assertIn("authority.live", proc.stderr)
    self.assertNotIn("Traceback", proc.stderr)

  def test_non_mapping_authority_is_a_clear_error(self):
    proc, _ = run("https://github.com/acme/saas.git", "acme/saas:\n  trunk: develop\n  authority: 5\n")
    self.assertNotEqual(proc.returncode, 0)
    self.assertEqual(proc.stdout, "")
    self.assertIn("authority", proc.stderr)
    self.assertNotIn("Traceback", proc.stderr)

  def test_local_path_remote_never_matches_a_profile(self):
    proc, _ = run("/Users/me/acme/saas", SAMPLE_YAML)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout), DEFAULT)

  def test_host_is_not_mistaken_for_owner(self):
    proc, _ = run("https://github.com/saas", SAMPLE_YAML)
    self.assertEqual(json.loads(proc.stdout), DEFAULT)

  def test_unreadable_profile_file_is_a_clear_error_not_a_traceback(self):
    # BUG-17: chmod 000 repos.yaml previously crashed with unhandled PermissionError traceback
    with tempfile.TemporaryDirectory() as tmp:
      yaml_path = Path(tmp) / "repos.yaml"
      yaml_path.write_text(SAMPLE_YAML)
      yaml_path.chmod(0o000)
      try:
        proc = subprocess.run(
          [sys.executable, str(SCRIPT), "--remote", "https://github.com/acme/saas.git", "--profile", str(yaml_path)],
          capture_output=True, text=True,
        )
      finally:
        yaml_path.chmod(0o600)
      self.assertNotEqual(proc.returncode, 0)
      self.assertEqual(proc.stdout, "")
      self.assertIn("repos.yaml", proc.stderr)
      self.assertNotIn("Traceback", proc.stderr)

  def test_non_string_list_items_are_rejected_with_clear_error(self):
    # BUG-18: list fields containing null / int / dict were previously coerced via str(item)
    for bad_yaml in (
      "acme/saas:\n  trunk: develop\n  spec_globs: [null]\n",
      "acme/saas:\n  trunk: develop\n  conventions_docs: [5]\n",
      "acme/saas:\n  trunk: develop\n  authority:\n    live: [{a: 1}]\n",
    ):
      proc, _ = run("https://github.com/acme/saas.git", bad_yaml)
      self.assertNotEqual(proc.returncode, 0, f"expected error for:\n{bad_yaml}")
      self.assertEqual(proc.stdout, "")
      self.assertNotIn("Traceback", proc.stderr)

  def test_whitespace_trunk_and_malformed_entry_types(self):
    # BUG-19: whitespace-only trunk returns default; non-dict entry or non-string trunk fails clearly
    ws, _ = run("https://github.com/acme/saas.git", "acme/saas:\n  trunk: '   '\n")
    self.assertEqual(ws.returncode, 0, ws.stderr)
    self.assertEqual(json.loads(ws.stdout), DEFAULT)

    bad_entry, _ = run("https://github.com/acme/saas.git", "acme/saas: develop\n")
    self.assertNotEqual(bad_entry.returncode, 0)
    self.assertEqual(bad_entry.stdout, "")
    self.assertNotIn("Traceback", bad_entry.stderr)

    bad_trunk, _ = run("https://github.com/acme/saas.git", "acme/saas:\n  trunk: 123\n")
    self.assertNotEqual(bad_trunk.returncode, 0)
    self.assertEqual(bad_trunk.stdout, "")
    self.assertNotIn("Traceback", bad_trunk.stderr)

  def test_malformed_remote_urls_and_query_fragments(self):
    # BUG-20: file://localhost must not match; empty repo after .git must not match; query/fragment must strip; non-str must not crash
    import importlib.util
    spec = importlib.util.spec_from_file_location("pr_review_profile_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    self.assertIsNone(mod.remote_to_key(123))
    self.assertIsNone(mod.remote_to_key("file://localhost/Users/me/acme/saas"))
    self.assertIsNone(mod.remote_to_key("https://github.com/acme/.git"))
    self.assertEqual(mod.remote_to_key("https://github.com/acme/saas.git?foo=1#bar"), "acme/saas")
    self.assertEqual(mod.remote_to_key("https://github.com/acme/saas/?foo=1"), "acme/saas")

    proc, _ = run("file://localhost/Users/me/acme/saas", SAMPLE_YAML)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout), DEFAULT)

    qproc, yaml_path = run("https://github.com/acme/saas.git?ref=main#top", SAMPLE_YAML)
    self.assertEqual(qproc.returncode, 0, qproc.stderr)
    self.assertEqual(json.loads(qproc.stdout)["trunk"], "develop")
    self.assertEqual(json.loads(qproc.stdout)["source"], yaml_path)

  def test_non_mapping_top_level_yaml_exits_nonzero(self):
    for bad in ("- item1\n- item2\n", "[]\n", "false\n", "0\n", '""\n', '"just-a-string"\n', "42\n"):
      proc, _ = run("https://github.com/acme/saas.git", bad)
      self.assertNotEqual(proc.returncode, 0, f"expected error for top-level:\n{bad}")
      self.assertEqual(proc.stdout, "")
      self.assertIn("top level must be a mapping", proc.stderr)
      self.assertNotIn("Traceback", proc.stderr)

  def test_dot_segment_remote_and_whitespace_list_items_rejected(self):
    proc, _ = run("https://github.com/acme/..", SAMPLE_YAML)
    self.assertEqual(proc.returncode, 0, proc.stderr)
    self.assertEqual(json.loads(proc.stdout), DEFAULT)

    bad_ws = """acme/saas:
  trunk: main
  spec_globs:
    - "   "
"""
    proc2, _ = run("https://github.com/acme/saas.git", bad_ws)
    self.assertNotEqual(proc2.returncode, 0)
    self.assertIn("non-empty string", proc2.stderr)


if __name__ == "__main__":
  unittest.main()
