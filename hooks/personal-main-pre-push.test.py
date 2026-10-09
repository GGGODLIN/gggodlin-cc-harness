#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "hooks" / "personal-main-pre-push.py"
INSTALLER = ROOT / "scripts" / "install-personal-main-pre-push.sh"
TOKEN = "PERSONAL_MAIN_PRE_PUSH_TEST_PASS"
GIT = "/usr/bin/git"
ZERO_OID = "0" * 40
SHA256_ZERO_OID = "0" * 64

GIT_ENV = {
  "GIT_AUTHOR_NAME": "Fixture",
  "GIT_AUTHOR_EMAIL": "fixture@example.com",
  "GIT_COMMITTER_NAME": "Fixture",
  "GIT_COMMITTER_EMAIL": "fixture@example.com",
  "GIT_CONFIG_GLOBAL": os.devnull,
  "GIT_CONFIG_SYSTEM": os.devnull,
  "GIT_CONFIG_NOSYSTEM": "1",
}

OLD_MANAGED_WRAPPER = """#!/bin/sh
# personal-main-pre-push managed wrapper v1
set -eu

GIT_BIN=/usr/bin/git
unset GIT_DIR GIT_WORK_TREE GIT_COMMON_DIR GIT_INDEX_FILE GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES 2>/dev/null || true
TOPLEVEL=$(/usr/bin/git rev-parse --show-toplevel 2>/dev/null) || {
  printf '%s\\n' 'personal-main-pre-push: DENY: cannot resolve invoking worktree' >&2
  exit 1
}
HELPER=$TOPLEVEL/hooks/personal-main-pre-push.py
if [ -L \"$HELPER\" ] || [ ! -f \"$HELPER\" ] || [ ! -x \"$HELPER\" ]; then
  printf '%s\\n' 'personal-main-pre-push: DENY: tracked helper is missing or not executable' >&2
  exit 1
fi
exec \"$HELPER\" \"$@\"
"""


class PrePushCase(unittest.TestCase):
  def setUp(self):
    self.root = Path(tempfile.mkdtemp(prefix="personal-main-pre-push-"))
    self.home = self.root / "home"
    self.home.mkdir()
    self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

  def env(self, extra=None):
    return {
      **os.environ,
      **GIT_ENV,
      "HOME": str(self.home),
      "PERSONAL_MAIN_PRE_PUSH_TEST_MODE": "1",
      "PERSONAL_MAIN_PRE_PUSH_TEST_AUDIT_HOME": str(self.home),
      **(extra or {}),
    }

  def git(self, cwd, *args, check=True, extra_env=None, input=None):
    result = subprocess.run(
      [GIT, "-C", str(cwd), *args],
      capture_output=True,
      check=False,
      env=self.env(extra_env),
      input=input,
      text=True,
    )
    if check and result.returncode != 0:
      self.fail(
        f"git failed ({result.returncode}): {args}\nstdout={result.stdout}\nstderr={result.stderr}"
      )
    return result

  def run_process(self, argv, cwd=None, extra_env=None, input=None, timeout=10):
    return subprocess.run(
      argv,
      capture_output=True,
      check=False,
      cwd=cwd,
      env=self.env(extra_env),
      input=input,
      text=True,
      timeout=timeout,
    )

  def commit(self, repo, name, content, message):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    self.git(repo, "add", "--all")
    self.git(repo, "commit", "-m", message)
    return self.git(repo, "rev-parse", "HEAD").stdout.strip()

  def copy_helper(self, repo):
    target = Path(repo) / "hooks" / HELPER.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HELPER, target)
    target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return target

  def make_repo(self, name="repo", install=False, object_format="sha1"):
    repo = self.root / name
    repo.mkdir()
    init_args = ["init"]
    if object_format != "sha1":
      init_args.extend(["--object-format", object_format])
    init_args.extend(["-b", "main"])
    self.git(repo, *init_args)
    self.copy_helper(repo)
    self.commit(repo, "seed.txt", "seed\n", "seed")
    bare = self.root / f"{name}.git"
    bare_args = ["init", "--bare"]
    if object_format != "sha1":
      bare_args.extend(["--object-format", object_format])
    bare_args.append(str(bare))
    self.git(self.root, *bare_args)
    self.git(repo, "remote", "add", "origin", str(bare))
    self.git(repo, "push", "-u", "origin", "main")
    self.git(self.root, "--git-dir", str(bare), "symbolic-ref", "HEAD", "refs/heads/main")
    if install:
      self.install(repo)
    return repo, bare

  def install(self, cwd, *args, check=True, extra_env=None):
    result = self.run_process([str(INSTALLER), *args], cwd=cwd, extra_env=extra_env)
    if check and result.returncode != 0:
      self.fail(f"installer failed: stdout={result.stdout}\nstderr={result.stderr}")
    return result

  def hooks_path(self, repo):
    value = self.git(repo, "rev-parse", "--path-format=absolute", "--git-path", "hooks").stdout
    return Path(value[:-1] if value.endswith("\n") else value)

  def installed_helper(self, repo):
    return self.hooks_path(repo) / HELPER.name

  def object_format(self, repo):
    value = self.git(repo, "rev-parse", "--show-object-format").stdout
    return value[:-1] if value.endswith("\n") else value

  def zero_oid_for(self, repo):
    return "0" * (64 if self.object_format(repo) == "sha256" else 40)

  def helper_module(self):
    spec = importlib.util.spec_from_file_location("personal_main_pre_push_test_helper", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

  def worktree(self, repo, name, branch=None, start="main", detach=False):
    path = self.root / name
    args = ["worktree", "add"]
    if detach:
      args.append("--detach")
    elif branch:
      args.extend(["-b", branch])
    args.extend([str(path), start])
    self.git(repo, *args)
    return path

  def run_helper(self, cwd, remote_name, remote_location, line, extra_env=None, timeout=10):
    return self.run_process(
      [sys.executable, str(HELPER), remote_name, remote_location],
      cwd=cwd,
      extra_env=extra_env,
      input=f"{line}\n",
      timeout=timeout,
    )

  def push(self, cwd, *args, extra_env=None, timeout=15):
    return self.run_process(
      [GIT, "-C", str(cwd), "push", *args],
      extra_env=extra_env,
      timeout=timeout,
    )

  def main_line(self, local_oid, remote_oid, remote_ref="refs/heads/main"):
    return f"refs/heads/candidate {local_oid} {remote_ref} {remote_oid}"

  def assert_denied(self, result, text=None):
    self.assertNotEqual(result.returncode, 0)
    self.assertIn("DENY", result.stderr)
    if text:
      self.assertIn(text, result.stderr)

  def assert_allowed(self, result):
    self.assertEqual(result.returncode, 0, result.stderr)


class ArtifactAndWiringTest(PrePushCase):
  def test_tracked_artifacts_exist_and_are_executable(self):
    self.assertTrue(HELPER.is_file())
    self.assertTrue(INSTALLER.is_file())
    self.assertTrue(os.access(HELPER, os.X_OK))
    self.assertTrue(os.access(INSTALLER, os.X_OK))

  def test_closeout_docs_name_native_gate_bypass_boundaries(self):
    command = (ROOT / "commands" / "git-closeout.md").read_text(encoding="utf-8")
    workflow = (ROOT / "rules" / "common" / "git-workflow.md").read_text(encoding="utf-8")
    helper = HELPER.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")
    bypass = "安裝後另設 worktree-specific core.hooksPath 會繞過，/git-closeout 要查"
    command_override = "命令列 -c core.hooksPath 也會繞過"
    for text in (command, workflow, helper, installer):
      self.assertIn("--no-verify", text)
      self.assertIn("force push 仍須既有 human confirm", text)
      self.assertIn("/git-closeout", text)
      self.assertIn("remote API", text)
      self.assertIn("final-read race", text)
      self.assertIn(bypass, text)
      self.assertIn(command_override, text)


class NativePushBehaviorTest(PrePushCase):
  def test_known_good_candidate_with_local_and_remote_ancestors_is_allowed(self):
    repo, _ = self.make_repo(install=True)
    candidate = self.worktree(repo, "candidate", branch="feature/good")
    local_main = self.git(repo, "rev-parse", "refs/heads/main").stdout.strip()
    new_oid = self.commit(candidate, "good.txt", "good\n", "good")
    result = self.push(candidate, "-u", "origin", "HEAD:refs/heads/main")
    self.assert_allowed(result)
    self.assertEqual(self.git(repo, "rev-parse", "refs/heads/main").stdout.strip(), local_main)
    self.assertEqual(self.git(repo, "rev-parse", "refs/remotes/origin/main").stdout.strip(), new_oid)

  def test_stale_candidate_missing_current_local_main_is_denied(self):
    repo, _ = self.make_repo(install=True)
    candidate = self.worktree(repo, "candidate", branch="feature/stale")
    self.commit(repo, "main.txt", "main\n", "advance main")
    stale_oid = self.commit(candidate, "stale.txt", "stale\n", "stale")
    before_remote = self.git(repo, "rev-parse", "refs/remotes/origin/main").stdout.strip()
    result = self.push(candidate, "origin", "HEAD:refs/heads/main")
    self.assert_denied(result, "local main")
    self.assertNotEqual(self.git(repo, "rev-parse", "refs/heads/main").stdout.strip(), stale_oid)
    self.assertEqual(self.git(repo, "rev-parse", "refs/remotes/origin/main").stdout.strip(), before_remote)

  def test_no_verify_explicitly_bypasses_native_gate(self):
    repo, _ = self.make_repo(install=True)
    candidate = self.worktree(repo, "candidate", branch="feature/no-verify")
    self.commit(repo, "main.txt", "main\n", "advance main")
    candidate_oid = self.commit(candidate, "stale.txt", "stale\n", "stale")
    result = self.push(candidate, "--no-verify", "origin", "HEAD:refs/heads/main")
    self.assert_allowed(result)
    self.assertEqual(self.git(repo, "rev-parse", "refs/remotes/origin/main").stdout.strip(), candidate_oid)

  def test_command_scoped_hooks_path_explicitly_bypasses_native_gate(self):
    repo, _ = self.make_repo(install=True)
    candidate = self.worktree(repo, "candidate", branch="feature/command-hooks")
    self.commit(repo, "main.txt", "main\n", "advance main")
    candidate_oid = self.commit(candidate, "stale.txt", "stale\n", "stale")
    custom = self.root / "command-hooks"
    custom.mkdir()
    result = self.run_process(
      [
        GIT,
        "-C",
        str(candidate),
        "-c",
        f"core.hooksPath={custom}",
        "push",
        "origin",
        "HEAD:refs/heads/main",
      ]
    )
    self.assert_allowed(result)
    self.assertEqual(self.git(repo, "rev-parse", "refs/remotes/origin/main").stdout.strip(), candidate_oid)

  def test_dirty_live_worktree_does_not_affect_committed_ref_gate(self):
    repo, _ = self.make_repo(install=True)
    candidate = self.worktree(repo, "candidate", branch="feature/dirty")
    (repo / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")
    self.commit(candidate, "candidate.txt", "candidate\n", "candidate")
    result = self.push(candidate, "origin", "HEAD:refs/heads/main")
    self.assert_allowed(result)

  def test_detached_candidate_is_allowed_when_refs_are_ancestors(self):
    repo, _ = self.make_repo(install=True)
    candidate = self.worktree(repo, "candidate", detach=True)
    self.commit(candidate, "detached.txt", "detached\n", "detached")
    result = self.push(candidate, "origin", "HEAD:refs/heads/main")
    self.assert_allowed(result)

  def test_other_refs_are_allowed_without_main_gate(self):
    repo, _ = self.make_repo(install=True)
    candidate = self.worktree(repo, "candidate", branch="feature/other")
    self.commit(candidate, "other.txt", "other\n", "other")
    result = self.push(candidate, "origin", "HEAD:refs/heads/feature/other")
    self.assert_allowed(result)

  def test_multiple_refs_gate_main_and_allow_other_ref_together(self):
    repo, bare = self.make_repo(install=True)
    candidate = self.worktree(repo, "candidate", branch="feature/multiple")
    new_oid = self.commit(candidate, "multiple.txt", "multiple\n", "multiple")
    result = self.push(
      candidate,
      "origin",
      "HEAD:refs/heads/main",
      "HEAD:refs/heads/feature/multiple",
    )
    self.assert_allowed(result)
    remote = self.git(self.root, "--git-dir", str(bare), "rev-parse", "refs/heads/feature/multiple")
    self.assertEqual(remote.stdout.strip(), new_oid)

  def test_compound_shell_push_uses_native_hook(self):
    repo, _ = self.make_repo(install=True)
    candidate = self.worktree(repo, "candidate", branch="feature/shell")
    self.commit(candidate, "shell.txt", "shell\n", "shell")
    result = self.run_process(
      ["/bin/sh", "-c", f"{GIT} -C \"$1\" push origin HEAD:refs/heads/main", "push", str(candidate)]
    )
    self.assert_allowed(result)

  def test_main_deletion_is_denied(self):
    repo, _ = self.make_repo(install=True)
    result = self.push(repo, "origin", ":refs/heads/main")
    self.assert_denied(result, "deletion")

  def test_force_non_ff_push_is_denied(self):
    repo, bare = self.make_repo(install=True)
    candidate = self.worktree(repo, "candidate", branch="feature/non-ff")
    candidate_oid = self.commit(candidate, "candidate.txt", "candidate\n", "candidate")
    updater = self.root / "updater"
    self.git(self.root, "clone", str(bare), str(updater))
    divergent_oid = self.commit(updater, "divergent.txt", "divergent\n", "divergent")
    self.git(updater, "push", "origin", "main")
    result = self.push(candidate, "--force", "origin", f"{candidate_oid}:refs/heads/main")
    self.assert_denied(result, "remote old")
    self.assertNotEqual(divergent_oid, candidate_oid)

  def test_actual_push_u_to_missing_remote_main_is_denied(self):
    repo, _ = self.make_repo(install=True)
    empty = self.root / "empty.git"
    self.git(self.root, "init", "--bare", str(empty))
    self.git(repo, "remote", "add", "empty", str(empty))
    result = self.push(repo, "-u", "empty", "main:refs/heads/main")
    self.assert_denied(result, "remote old")


class DirectHelperValidationTest(PrePushCase):
  def test_missing_remote_old_oid_is_denied(self):
    repo, _ = self.make_repo()
    local_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    result = self.run_helper(
      repo,
      "origin",
      "unused",
      self.main_line(local_oid, self.zero_oid_for(repo)),
    )
    self.assert_denied(result, "remote old")

  def test_remote_old_not_ancestor_is_denied(self):
    repo, bare = self.make_repo()
    base = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    candidate_oid = self.commit(repo, "candidate.txt", "candidate\n", "candidate")
    updater = self.root / "updater"
    self.git(self.root, "clone", str(bare), str(updater))
    divergent_oid = self.commit(updater, "divergent.txt", "divergent\n", "divergent")
    self.git(updater, "push", "origin", "main")
    result = self.run_helper(
      repo,
      "origin",
      "unused",
      self.main_line(candidate_oid, divergent_oid),
    )
    self.assert_denied(result, "remote old")
    self.assertNotEqual(base, divergent_oid)

  def test_unrelated_candidate_is_denied_with_real_replace_ref(self):
    repo, _ = self.make_repo()
    base = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    main_oid = self.commit(repo, "main.txt", "main\n", "advance main")
    candidate = self.worktree(repo, "candidate", branch="feature/replaced", start=base)
    candidate_oid = self.commit(candidate, "candidate.txt", "candidate\n", "unrelated candidate")
    candidate_tree = self.git(repo, "rev-parse", f"{candidate_oid}^{{tree}}").stdout.strip()
    replacement_oid = self.git(
      repo,
      "commit-tree",
      candidate_tree,
      "-p",
      main_oid,
      "-m",
      "replacement",
    ).stdout.strip()
    self.git(repo, "update-ref", f"refs/replace/{candidate_oid}", replacement_oid)
    replacement_control = self.git(
      repo,
      "merge-base",
      "--is-ancestor",
      main_oid,
      candidate_oid,
      check=False,
    )
    self.assertEqual(replacement_control.returncode, 0)
    result = self.run_helper(repo, "origin", "unused", self.main_line(candidate_oid, base))
    self.assert_denied(result, "local main")

  def test_zero_new_oid_is_denied(self):
    repo, _ = self.make_repo()
    old_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    result = self.run_helper(
      repo,
      "origin",
      "unused",
      self.main_line(self.zero_oid_for(repo), old_oid),
    )
    self.assert_denied(result, "deletion")

  def test_non_commit_new_oid_is_denied(self):
    repo, _ = self.make_repo()
    old_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    tree_oid = self.git(repo, "rev-parse", "HEAD^{tree}").stdout.strip()
    result = self.run_helper(repo, "origin", "unused", self.main_line(tree_oid, old_oid))
    self.assert_denied(result, "commit")

  def test_malformed_main_input_is_denied(self):
    repo, _ = self.make_repo()
    result = self.run_helper(repo, "origin", "unused", "main too-short")
    self.assert_denied(result, "input")

  def test_non_main_ref_is_allowed(self):
    repo, _ = self.make_repo()
    oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    result = self.run_helper(
      repo,
      "origin",
      "unused",
      self.main_line(oid, ZERO_OID, remote_ref="refs/heads/feature")
    )
    self.assert_allowed(result)

  def test_untrusted_git_environment_override_is_ignored(self):
    repo, _ = self.make_repo()
    old_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    result = self.run_helper(
      repo,
      "origin",
      "unused",
      self.main_line(old_oid, old_oid),
      extra_env={"PERSONAL_MAIN_PRE_PUSH_GIT": "/does/not/exist"},
    )
    self.assert_allowed(result)

  def test_trailing_space_in_worktree_path_is_preserved(self):
    repo, _ = self.make_repo(name="repo with space ")
    local_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    result = self.run_helper(repo, "origin", "unused", self.main_line(local_oid, local_oid))
    self.assert_allowed(result)

  def test_grafts_file_is_denied_before_ref_evidence(self):
    repo, _ = self.make_repo()
    local_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    grafts = repo / ".git" / "info" / "grafts"
    grafts.parent.mkdir(parents=True, exist_ok=True)
    grafts.write_text("invalid graft\n", encoding="utf-8")
    result = self.run_helper(repo, "origin", "unused", self.main_line(local_oid, local_oid))
    self.assert_denied(result, "grafts")


class Sha256NativeTest(PrePushCase):
  def test_sha256_known_good_push_is_allowed(self):
    repo, _ = self.make_repo(install=True, object_format="sha256")
    self.assertEqual(self.object_format(repo), "sha256")
    candidate = self.worktree(repo, "candidate", branch="feature/sha256")
    new_oid = self.commit(candidate, "sha256.txt", "sha256\n", "sha256")
    self.assertEqual(len(new_oid), 64)
    result = self.push(candidate, "origin", "HEAD:refs/heads/main")
    self.assert_allowed(result)

  def test_sha256_zero_oid_is_denied(self):
    repo, _ = self.make_repo(object_format="sha256")
    self.assertEqual(self.object_format(repo), "sha256")
    local_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    self.assertEqual(len(local_oid), 64)
    result = self.run_helper(repo, "origin", "unused", self.main_line(local_oid, SHA256_ZERO_OID))
    self.assert_denied(result, "remote old")

  def test_sha256_rejects_wrong_length_oid(self):
    repo, _ = self.make_repo(object_format="sha256")
    local_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    result = self.run_helper(repo, "origin", "unused", self.main_line(ZERO_OID, local_oid))
    self.assert_denied(result, "OID")


class RaceAndAuditTest(PrePushCase):
  def audit_path(self):
    return self.home / ".claude" / "logs" / "personal-main-pre-push.jsonl"

  def test_local_main_advance_between_reads_is_denied_by_injected_test_dependency(self):
    helper = self.helper_module()
    repo, _ = self.make_repo()
    local_oid = self.git(repo, "rev-parse", "refs/heads/main").stdout.strip()
    candidate_oid = self.commit(repo, "candidate.txt", "candidate\n", "candidate")
    race_source = self.root / "race-source"
    self.git(repo, "worktree", "add", "--detach", str(race_source), local_oid)
    advanced_oid = self.commit(race_source, "advanced.txt", "advanced\n", "advanced")
    update = {
      "local_ref": "refs/heads/candidate",
      "local_oid": candidate_oid,
      "remote_ref": "refs/heads/main",
      "remote_oid": local_oid,
    }

    def advance(_repo, _deadline=None):
      self.git(repo, "update-ref", "refs/heads/main", advanced_oid)

    with self.assertRaises(helper.GateError) as context:
      helper.check_main_updates(repo, [update], after_first_read=advance)
    self.assertIn("changed", str(context.exception))

  def test_production_has_no_environment_executable_race_seam(self):
    text = HELPER.read_text(encoding="utf-8")
    self.assertNotIn("PERSONAL_MAIN_PRE_PUSH_TEST_RACE", text)

  def test_relative_home_is_not_used_for_audit_path(self):
    helper = self.helper_module()
    original = os.environ.get("HOME")
    try:
      os.environ["HOME"] = "relative-home"
      self.assertEqual(helper.audit_path(), helper.canonical_home() / ".claude" / "logs")
      self.assertTrue(helper.audit_path().is_absolute())
    finally:
      if original is None:
        os.environ.pop("HOME", None)
      else:
        os.environ["HOME"] = original

  def test_git_environment_disables_replacement_trace_config_and_prompt_controls(self):
    helper = self.helper_module()
    names = {
      "GIT_TRACE",
      "GIT_TRACE2",
      "GIT_TRACE_PACKET",
      "GIT_TRACE_PERFORMANCE",
      "GIT_CONFIG_COUNT",
      "GIT_CONFIG_KEY_0",
      "GIT_CONFIG_VALUE_0",
      "GIT_CONFIG_PARAMETERS",
      "GIT_CONFIG_GLOBAL",
      "GIT_CONFIG_SYSTEM",
      "GIT_CONFIG_NOSYSTEM",
      "GIT_ASKPASS",
      "SSH_ASKPASS",
      "GIT_TERMINAL_PROMPT",
      "GIT_EDITOR",
      "GIT_SEQUENCE_EDITOR",
    }
    original = {name: os.environ.get(name) for name in names}
    try:
      os.environ.update({name: "injected" for name in names})
      environment = helper.git_environment()
      self.assertEqual(environment["GIT_NO_REPLACE_OBJECTS"], "1")
      self.assertTrue(all(name not in environment for name in names))
    finally:
      for name, value in original.items():
        if value is None:
          os.environ.pop(name, None)
        else:
          os.environ[name] = value

  def test_git_timeout_cleans_process_group(self):
    helper = self.helper_module()
    calls = []

    class HangingProcess:
      pid = 12345

      def communicate(self, timeout=None):
        calls.append(timeout)
        if len(calls) == 1:
          raise subprocess.TimeoutExpired([GIT], timeout)
        return b"", b""

    signals = []
    with mock.patch.object(helper.subprocess, "Popen", return_value=HangingProcess()):
      with mock.patch.object(helper.os, "killpg", side_effect=lambda pid, value: signals.append((pid, value))):
        with self.assertRaises(helper.GateError) as context:
          helper.run_git(self.root, "status", deadline=time.monotonic() + 1)
    self.assertIn("timed out", str(context.exception))
    self.assertIn((12345, signal.SIGTERM), signals)

  def test_unwritable_audit_does_not_change_allow_decision(self):
    repo, _ = self.make_repo()
    local_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    path = self.audit_path()
    path.parent.mkdir(parents=True)
    path.mkdir()
    result = self.run_helper(repo, "origin", "unused", self.main_line(local_oid, local_oid))
    self.assert_allowed(result)
    self.assertIn("WARN", result.stderr)

  def test_audit_symlink_is_not_followed(self):
    repo, _ = self.make_repo()
    local_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    path = self.audit_path()
    path.parent.mkdir(parents=True)
    target = self.root / "outside.jsonl"
    target.write_text("sentinel\n", encoding="utf-8")
    path.symlink_to(target)
    result = self.run_helper(repo, "origin", "unused", self.main_line(local_oid, local_oid))
    self.assert_allowed(result)
    self.assertEqual(target.read_text(encoding="utf-8"), "sentinel\n")

  def test_audit_fifo_does_not_block_or_change_decision(self):
    repo, _ = self.make_repo()
    local_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    path = self.audit_path()
    path.parent.mkdir(parents=True)
    os.mkfifo(path)
    result = self.run_helper(
      repo,
      "origin",
      "unused",
      self.main_line(local_oid, local_oid),
      timeout=3,
    )
    self.assert_allowed(result)

  def test_audit_record_has_only_allowed_fields_and_no_command(self):
    repo, _ = self.make_repo()
    local_oid = self.git(repo, "rev-parse", "HEAD").stdout.strip()
    result = self.run_helper(repo, "origin", "/tmp/remote", self.main_line(local_oid, local_oid))
    self.assert_allowed(result)
    record = json.loads(self.audit_path().read_text(encoding="utf-8").splitlines()[-1])
    self.assertEqual(
      set(record),
      {"timestamp", "outcome", "reason", "remote_name", "remote_ref", "local_oid", "remote_oid"},
    )
    self.assertNotIn("command", record)
    self.assertEqual(record["remote_name"], "origin")
    self.assertEqual(record["remote_ref"], "refs/heads/main")


class InstallerLifecycleTest(PrePushCase):
  def pre_push(self, repo):
    return self.hooks_path(repo) / "pre-push"

  def test_fresh_install_check_and_idempotent_rerun(self):
    repo, _ = self.make_repo()
    first = self.install(repo)
    self.assertEqual(first.returncode, 0)
    hook = self.pre_push(repo)
    installed = self.installed_helper(repo)
    self.assertTrue(hook.is_file())
    self.assertFalse(hook.is_symlink())
    self.assertTrue(os.access(hook, os.X_OK))
    self.assertTrue(installed.is_file())
    self.assertFalse(installed.is_symlink())
    self.assertTrue(os.access(installed, os.X_OK))
    self.assertEqual(installed.read_bytes(), HELPER.read_bytes())
    first_bytes = hook.read_bytes()
    second = self.install(repo)
    self.assertEqual(second.returncode, 0)
    self.assertEqual(hook.read_bytes(), first_bytes)
    self.assertEqual(installed.read_bytes(), HELPER.read_bytes())
    checked = self.install(repo, "--check")
    self.assertEqual(checked.returncode, 0, checked.stderr)
    self.assertIn("managed", checked.stdout)
    self.assertIn("bypass", checked.stdout)

  def test_linked_worktrees_share_fixed_helper_and_ignore_candidate_tamper(self):
    repo, _ = self.make_repo()
    candidate = self.worktree(repo, "candidate", branch="feature/fixed-helper")
    self.install(candidate)
    self.assertEqual(self.hooks_path(repo), self.hooks_path(candidate))
    self.assertEqual(self.pre_push(repo), self.pre_push(candidate))
    installed = self.installed_helper(repo)
    source_bytes = HELPER.read_bytes()
    self.assertEqual(installed.read_bytes(), source_bytes)
    self.commit(repo, "main.txt", "main\n", "advance main")
    self.commit(candidate, "candidate.txt", "candidate\n", "candidate")
    helper = candidate / "hooks" / HELPER.name
    helper.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    helper.chmod(0o700)
    result = self.push(candidate, "origin", "HEAD:refs/heads/main")
    self.assert_denied(result, "local main")
    self.assertEqual(installed.read_bytes(), source_bytes)

  def test_check_rejects_installed_helper_bytes_and_non_executable(self):
    repo, _ = self.make_repo()
    self.install(repo)
    installed = self.installed_helper(repo)
    installed.write_bytes(b"tampered helper\n")
    tampered = self.install(repo, "--check", check=False)
    self.assertNotEqual(tampered.returncode, 0)
    installed.write_bytes(HELPER.read_bytes())
    installed.chmod(0o644)
    non_executable = self.install(repo, "--check", check=False)
    self.assertNotEqual(non_executable.returncode, 0)

  def test_check_rejects_installed_helper_symlink(self):
    repo, _ = self.make_repo()
    self.install(repo)
    installed = self.installed_helper(repo)
    target = self.root / "outside-helper.py"
    target.write_bytes(HELPER.read_bytes())
    target.chmod(0o700)
    installed.unlink()
    installed.symlink_to(target)
    checked = self.install(repo, "--check", check=False)
    self.assertNotEqual(checked.returncode, 0)

  def test_check_rejects_wrapper_bytes(self):
    repo, _ = self.make_repo()
    self.install(repo)
    hook = self.pre_push(repo)
    hook.write_bytes(hook.read_bytes() + b"tamper\n")
    checked = self.install(repo, "--check", check=False)
    self.assertNotEqual(checked.returncode, 0)

  def test_disable_refuses_tampered_managed_wrapper(self):
    repo, _ = self.make_repo()
    self.install(repo)
    hook = self.pre_push(repo)
    hook.write_bytes(hook.read_bytes() + b"tamper\n")
    disabled = self.install(repo, "--disable", check=False)
    self.assertNotEqual(disabled.returncode, 0)
    self.assertTrue(hook.exists())

  def test_check_rejects_non_executable_wrapper(self):
    repo, _ = self.make_repo()
    self.install(repo)
    hook = self.pre_push(repo)
    hook.chmod(0o644)
    checked = self.install(repo, "--check", check=False)
    self.assertNotEqual(checked.returncode, 0)

  def test_check_rejects_wrapper_symlink(self):
    repo, _ = self.make_repo()
    self.install(repo)
    hook = self.pre_push(repo)
    target = self.root / "outside-pre-push"
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    target.chmod(0o700)
    hook.unlink()
    hook.symlink_to(target)
    checked = self.install(repo, "--check", check=False)
    self.assertNotEqual(checked.returncode, 0)

  def test_existing_foreign_hook_is_not_overwritten(self):
    repo, _ = self.make_repo()
    hook = self.pre_push(repo)
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o700)
    before = hook.read_bytes()
    result = self.install(repo, check=False)
    self.assertNotEqual(result.returncode, 0)
    self.assertEqual(hook.read_bytes(), before)

  def test_custom_hooks_path_fails_closed_without_writing(self):
    repo, _ = self.make_repo()
    custom = self.root / "custom-hooks"
    self.git(repo, "config", "core.hooksPath", str(custom))
    result = self.install(repo, check=False)
    self.assertNotEqual(result.returncode, 0)
    self.assertFalse((custom / "pre-push").exists())
    checked = self.install(repo, "--check", check=False)
    self.assertNotEqual(checked.returncode, 0)

  def test_custom_hooks_path_in_any_linked_worktree_fails_install_and_check(self):
    repo, _ = self.make_repo()
    candidate = self.worktree(repo, "candidate", branch="feature/custom-hooks")
    self.git(repo, "config", "extensions.worktreeConfig", "true")
    custom = self.root / "linked-custom-hooks"
    self.git(candidate, "config", "--worktree", "core.hooksPath", str(custom))
    result = self.install(repo, check=False)
    self.assertNotEqual(result.returncode, 0)
    self.assertFalse(self.pre_push(repo).exists())
    checked = self.install(candidate, "--check", check=False)
    self.assertNotEqual(checked.returncode, 0)

  def test_old_managed_wrapper_is_atomically_upgraded(self):
    repo, _ = self.make_repo()
    hook = self.pre_push(repo)
    old = OLD_MANAGED_WRAPPER
    hook.write_text(old, encoding="utf-8")
    hook.chmod(0o700)
    result = self.install(repo)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertNotEqual(hook.read_text(encoding="utf-8"), old)
    self.assertEqual(self.installed_helper(repo).read_bytes(), HELPER.read_bytes())
    checked = self.install(repo, "--check")
    self.assertEqual(checked.returncode, 0, checked.stderr)

  def test_unknown_managed_marker_is_treated_as_foreign(self):
    repo, _ = self.make_repo()
    hook = self.pre_push(repo)
    foreign = "#!/bin/sh\n# personal-main-pre-push managed wrapper v99\nexit 0\n"
    hook.write_text(foreign, encoding="utf-8")
    hook.chmod(0o700)
    result = self.install(repo, check=False)
    self.assertNotEqual(result.returncode, 0)
    self.assertEqual(hook.read_text(encoding="utf-8"), foreign)

  def test_installed_helper_missing_makes_wrapper_deny(self):
    repo, _ = self.make_repo()
    self.install(repo)
    installed = self.installed_helper(repo)
    installed.unlink()
    result = self.push(repo, "origin", "main:refs/heads/main")
    self.assert_denied(result, "helper")

  def test_candidate_helper_missing_after_install_does_not_break_wrapper(self):
    repo, _ = self.make_repo()
    self.install(repo)
    candidate = self.worktree(repo, "candidate", branch="feature/source-missing")
    helper = candidate / "hooks" / HELPER.name
    helper.unlink()
    self.commit(candidate, "candidate.txt", "candidate\n", "candidate")
    result = self.push(candidate, "origin", "HEAD:refs/heads/main")
    self.assert_allowed(result)

  def test_production_helper_path_override_is_ignored(self):
    repo, _ = self.make_repo()
    self.install(repo)
    candidate = self.worktree(repo, "candidate", branch="feature/override")
    self.commit(repo, "main.txt", "main\n", "advance main")
    self.commit(candidate, "stale.txt", "stale\n", "stale")
    fake = self.root / "fake-helper.sh"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o700)
    result = self.push(
      candidate,
      "origin",
      "HEAD:refs/heads/main",
      extra_env={"PERSONAL_MAIN_PRE_PUSH_HELPER": str(fake)},
    )
    self.assert_denied(result, "local main")

  def test_disable_removes_only_managed_hook_and_foreign_hook_survives(self):
    repo, _ = self.make_repo()
    self.install(repo)
    hook = self.pre_push(repo)
    self.assertTrue(hook.exists())
    disabled = self.install(repo, "--disable")
    self.assertEqual(disabled.returncode, 0, disabled.stderr)
    self.assertFalse(hook.exists())
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o700)
    before = hook.read_bytes()
    result = self.install(repo, "--disable", check=False)
    self.assertNotEqual(result.returncode, 0)
    self.assertEqual(hook.read_bytes(), before)

  def test_managed_hook_symlink_is_not_deleted(self):
    repo, _ = self.make_repo()
    target = self.root / "foreign-hook"
    target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook = self.pre_push(repo)
    hook.symlink_to(target)
    result = self.install(repo, "--disable", check=False)
    self.assertNotEqual(result.returncode, 0)
    self.assertTrue(hook.is_symlink())
    self.assertEqual(target.read_text(encoding="utf-8"), "#!/bin/sh\nexit 0\n")


if __name__ == "__main__":
  suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
  result = unittest.TextTestRunner(verbosity=1).run(suite)
  if result.wasSuccessful():
    print(TOKEN)
  raise SystemExit(0 if result.wasSuccessful() else 1)
