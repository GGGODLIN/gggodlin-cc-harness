#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HOOK = Path(__file__).with_name("personal-main-closeout.py")

CLOSEOUT_ACTION = "請執行 `/git-closeout` 處理以上 Git 狀態，再開始新工作。"

WORK_NOTE = "（公司 repo · 只報告，處置一律等你決定）"

GIT_ENV = {
  "GIT_AUTHOR_NAME": "Fixture",
  "GIT_AUTHOR_EMAIL": "fixture@example.com",
  "GIT_COMMITTER_NAME": "Fixture",
  "GIT_COMMITTER_EMAIL": "fixture@example.com",
  "GIT_CONFIG_GLOBAL": os.devnull,
  "GIT_CONFIG_SYSTEM": os.devnull,
  "GIT_CONFIG_NOSYSTEM": "1",
}


def git(cwd, *args):
  return subprocess.run(
    ["git", "-C", str(cwd), *args],
    capture_output=True,
    check=True,
    env={**os.environ, **GIT_ENV},
    text=True,
  )


def write_commit(repo, name, message):
  (Path(repo) / name).write_text(f"{name}\n", encoding="utf-8")
  git(repo, "add", "--all")
  git(repo, "commit", "-m", message)


class HookCase(unittest.TestCase):
  def setUp(self):
    self.home = Path(tempfile.mkdtemp(prefix="closeout-home-"))
    self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
    (self.home / "Desktop" / "projects").mkdir(parents=True)
    (self.home / "origins").mkdir()

  def make_repo(self, relative, branch="main", origin=True):
    repo = self.home / relative
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-b", branch)
    write_commit(repo, "seed.txt", "init")
    if origin:
      bare = self.home / "origins" / f"{repo.name}.git"
      subprocess.run(
        ["git", "init", "--bare", "-b", branch, str(bare)],
        capture_output=True,
        check=True,
        env={**os.environ, **GIT_ENV},
        text=True,
      )
      git(repo, "remote", "add", "origin", str(bare))
      git(repo, "push", "-u", "origin", branch)
      git(repo, "remote", "set-head", "origin", branch)
    return repo

  def run_hook(self, cwd, source="startup", raw=None, extra_env=None):
    payload = json.dumps(
      {"hook_event_name": "SessionStart", "cwd": str(cwd), "source": source}
    )
    return subprocess.run(
      [sys.executable, str(HOOK)],
      capture_output=True,
      check=False,
      env={**os.environ, **GIT_ENV, "HOME": str(self.home), **(extra_env or {})},
      input=payload if raw is None else raw,
      text=True,
    )

  def message_of(self, result):
    self.assertEqual(result.returncode, 0)
    self.assertEqual(result.stderr, "")
    payload = json.loads(result.stdout)
    self.assertIn("systemMessage", payload)
    return payload["systemMessage"]

  def assert_silent(self, result):
    self.assertEqual(result.returncode, 0)
    self.assertEqual(result.stdout, "")
    self.assertEqual(result.stderr, "")


class UnmergedBranchTest(HookCase):
  def test_unmerged_branch_is_named(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/alpha")
    write_commit(repo, "alpha.txt", "alpha work")
    git(repo, "checkout", "main")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("feat/alpha", message)
    self.assertEqual(message.count(CLOSEOUT_ACTION), 1)
    self.assertEqual(message.splitlines()[1], CLOSEOUT_ACTION)

  def test_merged_branch_is_silent(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/alpha")
    write_commit(repo, "alpha.txt", "alpha work")
    git(repo, "checkout", "main")
    git(repo, "merge", "--no-ff", "-m", "merge alpha", "feat/alpha")
    git(repo, "push", "origin", "main")
    self.assert_silent(self.run_hook(repo))

  def test_squash_merged_branch_is_still_named(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/squash")
    write_commit(repo, "squash.txt", "squash work")
    git(repo, "checkout", "main")
    git(repo, "merge", "--squash", "feat/squash")
    git(repo, "commit", "-m", "squashed alpha")
    git(repo, "push", "origin", "main")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("feat/squash", message)


class StashTest(HookCase):
  def test_each_stash_entry_is_listed(self):
    repo = self.make_repo("Desktop/projects/alpha")
    for name in ("first", "second"):
      (repo / "seed.txt").write_text(f"{name}\n", encoding="utf-8")
      git(repo, "stash", "push", "-m", f"stash {name}")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("stash 尚未處理", message)
    self.assertIn("stash {0}".format("first"), message)
    self.assertIn("stash {0}".format("second"), message)


class UncommittedTest(HookCase):
  def test_dirty_off_trunk_is_reported(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/dirty")
    (repo / "draft.txt").write_text("draft\n", encoding="utf-8")
    (repo / "seed.txt").write_text("changed\n", encoding="utf-8")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("未 commit 變更", message)
    self.assertIn("feat/dirty：2 項", message)

  def test_dirty_on_trunk_is_silent(self):
    repo = self.make_repo("Desktop/projects/alpha")
    (repo / "draft.txt").write_text("draft\n", encoding="utf-8")
    self.assert_silent(self.run_hook(repo))

  def test_linked_worktree_is_checked_on_its_own(self):
    repo = self.make_repo("Desktop/projects/alpha")
    linked = self.home / "Desktop" / "projects" / "alpha-wt"
    git(repo, "worktree", "add", "-b", "feat/linked", str(linked))
    (linked / "draft.txt").write_text("draft\n", encoding="utf-8")
    message = self.message_of(self.run_hook(linked))
    self.assertIn("feat/linked：1 項", message)


class UnpushedTrunkTest(HookCase):
  def test_ahead_of_origin_has_its_own_wording_and_no_unmerged_duplicate(self):
    repo = self.make_repo("Desktop/projects/alpha")
    write_commit(repo, "one.txt", "one")
    write_commit(repo, "two.txt", "two")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("main 領先 origin 2 個 commit", message)
    self.assertNotIn("未合併進", message)
    self.assertNotIn("  - main", message)

  def test_single_commit_ahead_is_reported_without_threshold(self):
    repo = self.make_repo("Desktop/projects/alpha")
    write_commit(repo, "one.txt", "one")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("main 領先 origin 1 個 commit", message)


class TrunkResolutionTest(HookCase):
  def test_master_repo_uses_master_as_trunk(self):
    repo = self.make_repo("Desktop/projects/legacy", branch="master")
    git(repo, "checkout", "-b", "feat/legacy")
    write_commit(repo, "legacy.txt", "legacy work")
    git(repo, "checkout", "master")
    write_commit(repo, "ahead.txt", "ahead")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("未合併進 master 的本機 branch", message)
    self.assertIn("feat/legacy", message)
    self.assertIn("master 領先 origin 1 個 commit", message)

  def test_empty_repo_is_silent(self):
    repo = self.home / "Desktop" / "projects" / "blank"
    repo.mkdir(parents=True)
    git(repo, "init", "-b", "main")
    self.assert_silent(self.run_hook(repo))

  def test_repo_without_origin_skips_unpushed_check(self):
    repo = self.make_repo("Desktop/projects/solo", origin=False)
    git(repo, "checkout", "-b", "feat/solo")
    write_commit(repo, "solo.txt", "solo work")
    git(repo, "checkout", "main")
    write_commit(repo, "ahead.txt", "ahead")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("feat/solo", message)
    self.assertNotIn("領先", message)


class ScopeTest(HookCase):
  def dirty_branch(self, repo, branch, base="main"):
    git(repo, "checkout", "-b", branch)
    write_commit(repo, f"{branch.replace('/', '-')}.txt", "work")
    git(repo, "checkout", base)

  def test_company_repo_is_silent(self):
    repo = self.make_repo("Desktop/work/acme")
    self.dirty_branch(repo, "feat/acme")
    self.assert_silent(self.run_hook(repo))

  def test_company_repo_worktree_under_personal_path_is_silent(self):
    repo = self.make_repo("Desktop/work/acme")
    self.dirty_branch(repo, "feat/acme")
    linked = self.home / "Desktop" / "projects" / "acme-wt"
    git(repo, "worktree", "add", "-b", "feat/sneaky", str(linked))
    (linked / "draft.txt").write_text("draft\n", encoding="utf-8")
    self.assert_silent(self.run_hook(linked))

  def test_company_repo_reached_through_symlinked_personal_path_is_silent(self):
    repo = self.make_repo("Desktop/work/acme")
    self.dirty_branch(repo, "feat/acme")
    link = self.home / "Desktop" / "projects" / "acme-link"
    link.symlink_to(repo)
    self.assert_silent(self.run_hook(link))

  def test_dot_claude_repo_is_in_scope(self):
    repo = self.make_repo(".claude")
    self.dirty_branch(repo, "feat/claude")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("feat/claude", message)

  def test_code_social_info_repo_is_in_scope(self):
    repo = self.make_repo("code/social-info")
    self.dirty_branch(repo, "feat/social")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("feat/social", message)

  def test_unrelated_personal_repo_outside_scope_is_silent(self):
    repo = self.make_repo("Downloads/scratchpad")
    self.dirty_branch(repo, "feat/scratch")
    self.assert_silent(self.run_hook(repo))

  def test_projects_parent_directory_is_silent(self):
    parent = self.make_repo("Desktop/projects")
    self.dirty_branch(parent, "feat/parent")
    self.assert_silent(self.run_hook(parent))


class SessionSourceTest(HookCase):
  def setUp(self):
    super().setUp()
    self.repo = self.make_repo("Desktop/projects/alpha")
    git(self.repo, "checkout", "-b", "feat/alpha")
    write_commit(self.repo, "alpha.txt", "alpha work")
    git(self.repo, "checkout", "main")

  def test_startup_reminds(self):
    self.assertIn("feat/alpha", self.message_of(self.run_hook(self.repo)))

  def test_resume_reminds(self):
    message = self.message_of(self.run_hook(self.repo, source="resume"))
    self.assertIn("feat/alpha", message)

  def test_compact_is_silent(self):
    self.assert_silent(self.run_hook(self.repo, source="compact"))

  def test_clear_is_silent(self):
    self.assert_silent(self.run_hook(self.repo, source="clear"))


class MessageShapeTest(HookCase):
  def test_stable_text_leads_and_dynamic_list_follows(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/alpha")
    write_commit(repo, "alpha.txt", "alpha work")
    git(repo, "checkout", "main")
    lines = self.message_of(self.run_hook(repo)).splitlines()
    self.assertEqual(lines[0], "個人 repo 收尾檢查：以下項目請確認是否需要處理。")
    self.assertEqual(lines[1], CLOSEOUT_ACTION)
    self.assertEqual(lines[2], f"repo：{Path(repo).resolve()}")
    self.assertEqual(lines[-1], "  - feat/alpha")

  def test_no_leak_wording(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/alpha")
    write_commit(repo, "alpha.txt", "alpha work")
    git(repo, "checkout", "main")
    message = self.message_of(self.run_hook(repo))
    self.assertNotIn("漏件", message)
    self.assertIn("請確認", message)

  def test_more_than_ten_branches_are_truncated(self):
    repo = self.make_repo("Desktop/projects/alpha")
    for index in range(12):
      git(repo, "checkout", "-b", f"feat/b{index:02d}", "main")
      write_commit(repo, f"b{index:02d}.txt", f"work {index}")
    git(repo, "checkout", "main")
    message = self.message_of(self.run_hook(repo))
    listed = [line for line in message.splitlines() if line.startswith("  - ")]
    self.assertEqual(len(listed), 10)
    self.assertIn("  另有 2 項", message)


class IgnoreListTest(HookCase):
  def write_ignore(self, *lines):
    path = self.home / ".claude" / "policies" / "personal-main-closeout" / "ignore.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path

  def entry(self, identity, ref, tip=None):
    record = {
      "identity": identity,
      "ref": ref,
      "reason": "已在 PR #1 合併",
      "date": "2026-08-17",
    }
    if tip is not None:
      record["tip"] = tip
    return json.dumps(record, ensure_ascii=False)

  def branch_repo(self, url, *branches):
    repo = self.make_repo("Desktop/projects/alpha")
    for branch in branches:
      git(repo, "checkout", "-b", branch, "main")
      write_commit(repo, f"{branch.replace('/', '-')}.txt", "work")
    git(repo, "checkout", "main")
    git(repo, "remote", "set-url", "origin", url)
    return repo

  def tip_of(self, repo, branch):
    return git(repo, "rev-parse", f"refs/heads/{branch}").stdout.strip()

  def test_listed_branch_is_silent(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha")
    self.write_ignore(self.entry("github.com/me/alpha", "refs/heads/feat/alpha"))
    self.assert_silent(self.run_hook(repo))

  def test_unlisted_branch_is_still_reported(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha", "feat/beta")
    self.write_ignore(self.entry("github.com/me/alpha", "refs/heads/feat/alpha"))
    message = self.message_of(self.run_hook(repo))
    self.assertIn("feat/beta", message)
    self.assertNotIn("feat/alpha", message)

  def test_entry_for_another_repo_does_not_silence(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha")
    self.write_ignore(self.entry("github.com/me/other", "refs/heads/feat/alpha"))
    self.assertIn("feat/alpha", self.message_of(self.run_hook(repo)))

  def test_ssh_origin_matches_https_entry(self):
    repo = self.branch_repo("git@github.com:me/alpha.git", "feat/alpha")
    self.write_ignore(self.entry("https://github.com/me/alpha.git", "refs/heads/feat/alpha"))
    self.assert_silent(self.run_hook(repo))

  def test_https_origin_with_credentials_matches_ssh_entry(self):
    repo = self.branch_repo("https://user:token@github.com/me/alpha.git?ref=main", "feat/alpha")
    self.write_ignore(self.entry("git@github.com:me/alpha.git", "refs/heads/feat/alpha"))
    self.assert_silent(self.run_hook(repo))

  def test_repo_without_origin_uses_directory_name_as_identity(self):
    repo = self.make_repo("Desktop/projects/solo", origin=False)
    git(repo, "checkout", "-b", "feat/solo")
    write_commit(repo, "solo.txt", "solo work")
    git(repo, "checkout", "main")
    self.write_ignore(self.entry("solo", "refs/heads/feat/solo"))
    self.assert_silent(self.run_hook(repo))

  def dirty_solo_repo(self, name):
    repo = self.make_repo(f"Desktop/projects/{name}", origin=False)
    git(repo, "checkout", "-b", "feat/wip")
    write_commit(repo, "wip.txt", "wip")
    (repo / "loose.txt").write_text("uncommitted", encoding="utf-8")
    return repo

  def test_whole_repo_entry_silences_every_finding(self):
    repo = self.dirty_solo_repo("handed-off")
    self.write_ignore(self.entry("handed-off", "*"))
    self.assert_silent(self.run_hook(repo))

  def test_whole_repo_entry_for_another_repo_does_not_silence(self):
    repo = self.dirty_solo_repo("still-mine")
    self.write_ignore(self.entry("handed-off", "*"))
    self.assertIn("feat/wip", self.message_of(self.run_hook(repo)))

  def test_whole_repo_entry_is_skipped_in_parent_scan(self):
    self.dirty_solo_repo("handed-off")
    self.dirty_solo_repo("still-mine")
    self.write_ignore(self.entry("handed-off", "*"))
    message = self.message_of(self.run_hook(self.home / "Desktop" / "projects"))
    self.assertIn("still-mine", message)
    self.assertNotIn("handed-off", message)

  def test_matching_tip_stays_silent(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha")
    tip = self.tip_of(repo, "feat/alpha")
    self.write_ignore(self.entry("github.com/me/alpha", "refs/heads/feat/alpha", tip=tip))
    self.assert_silent(self.run_hook(repo))

  def test_clean_pinned_checkout_is_silent(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha")
    tip = self.tip_of(repo, "feat/alpha")
    self.write_ignore(self.entry("github.com/me/alpha", "refs/heads/feat/alpha", tip=tip))
    git(repo, "checkout", "feat/alpha")
    before_status = git(repo, "status", "--porcelain").stdout
    self.assert_silent(self.run_hook(repo))
    self.assertEqual(git(repo, "status", "--porcelain").stdout, before_status)
    self.assertEqual(self.tip_of(repo, "feat/alpha"), tip)

  def test_unpinned_checkout_still_reports(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha")
    self.write_ignore(self.entry("github.com/me/alpha", "refs/heads/feat/alpha"))
    git(repo, "checkout", "feat/alpha")
    self.assertIn("目前 checkout 在 feat/alpha", self.message_of(self.run_hook(repo)))

  def test_stale_pinned_checkout_still_reports(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha")
    stale = self.tip_of(repo, "feat/alpha")
    git(repo, "checkout", "feat/alpha")
    write_commit(repo, "more.txt", "more work")
    self.write_ignore(self.entry("github.com/me/alpha", "refs/heads/feat/alpha", tip=stale))
    self.assertIn("目前 checkout 在 feat/alpha", self.message_of(self.run_hook(repo)))

  def test_dirty_pinned_checkout_still_reports(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha")
    tip = self.tip_of(repo, "feat/alpha")
    self.write_ignore(self.entry("github.com/me/alpha", "refs/heads/feat/alpha", tip=tip))
    git(repo, "checkout", "feat/alpha")
    (repo / "draft.txt").write_text("draft\n", encoding="utf-8")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("未 commit 變更", message)
    self.assertIn("目前 checkout 在 feat/alpha", message)

  def test_stale_tip_restores_the_reminder(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha")
    stale = self.tip_of(repo, "feat/alpha")
    git(repo, "checkout", "feat/alpha")
    write_commit(repo, "more.txt", "more work")
    git(repo, "checkout", "main")
    self.write_ignore(self.entry("github.com/me/alpha", "refs/heads/feat/alpha", tip=stale))
    message = self.message_of(self.run_hook(repo))
    self.assertIn("feat/alpha", message)
    self.assertNotIn("已在 PR #1 合併", message)

  def test_broken_lines_are_skipped_and_valid_entries_apply(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha", "feat/beta")
    self.write_ignore(
      "{not json",
      json.dumps({"ref": "refs/heads/feat/beta"}),
      json.dumps({"identity": "github.com/me/alpha"}),
      json.dumps(["github.com/me/alpha", "refs/heads/feat/beta"]),
      "",
      self.entry("github.com/me/alpha", "refs/heads/feat/alpha"),
    )
    message = self.message_of(self.run_hook(repo))
    self.assertIn("feat/beta", message)
    self.assertNotIn("feat/alpha", message)

  def test_missing_ignore_file_keeps_baseline_behaviour(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha")
    self.assertFalse(
      (self.home / ".claude" / "policies" / "personal-main-closeout" / "ignore.jsonl").exists()
    )
    self.assertIn("feat/alpha", self.message_of(self.run_hook(repo)))

  def test_listed_branch_does_not_silence_other_findings(self):
    repo = self.branch_repo("https://github.com/me/alpha.git", "feat/alpha")
    (repo / "seed.txt").write_text("stashed\n", encoding="utf-8")
    git(repo, "stash", "push", "-m", "stash keep")
    self.write_ignore(self.entry("github.com/me/alpha", "refs/heads/feat/alpha"))
    message = self.message_of(self.run_hook(repo))
    self.assertIn("stash keep", message)
    self.assertNotIn("feat/alpha", message)


class ParentDirectoryTest(HookCase):
  def setUp(self):
    super().setUp()
    self.parent = self.home / "Desktop" / "projects"

  def dirty_repo(self, relative, branch):
    repo = self.make_repo(relative)
    git(repo, "checkout", "-b", branch)
    write_commit(repo, f"{branch.replace('/', '-')}.txt", "work")
    git(repo, "checkout", "main")
    return repo

  def test_each_reporting_child_repo_gets_its_own_section(self):
    self.dirty_repo("Desktop/projects/alpha", "feat/alpha")
    self.dirty_repo("Desktop/projects/beta", "feat/beta")
    self.make_repo("Desktop/projects/quiet")
    message = self.message_of(self.run_hook(self.parent))
    self.assertEqual(message.count("個人 repo 收尾檢查"), 1)
    self.assertIn("feat/alpha", message)
    self.assertIn("feat/beta", message)
    self.assertNotIn("quiet", message)
    headings = [line for line in message.splitlines() if line.startswith("repo：")]
    self.assertEqual(len(headings), 2)
    self.assertEqual(message.count(CLOSEOUT_ACTION), 1)
    self.assertEqual(message.splitlines()[1], CLOSEOUT_ACTION)

  def test_exhausted_budget_truncates_and_counts_the_rest(self):
    for name in ("alpha", "beta", "gamma"):
      self.dirty_repo(f"Desktop/projects/{name}", f"feat/{name}")
    message = self.message_of(
      self.run_hook(
        self.parent,
        extra_env={"PERSONAL_MAIN_CLOSEOUT_BUDGET_SECONDS": "0.000001"},
      )
    )
    headings = [line for line in message.splitlines() if line.startswith("repo：")]
    self.assertEqual(len(headings), 1)
    self.assertIn("feat/alpha", message)
    self.assertIn("其餘 2 個未掃", message)
    self.assertEqual(message.count(CLOSEOUT_ACTION), 1)
    self.assertEqual(message.splitlines()[1], CLOSEOUT_ACTION)

  def test_full_scan_does_not_mention_unscanned_repos(self):
    self.dirty_repo("Desktop/projects/alpha", "feat/alpha")
    self.dirty_repo("Desktop/projects/beta", "feat/beta")
    message = self.message_of(self.run_hook(self.parent))
    self.assertNotIn("未掃", message)

  def test_invalid_budget_env_falls_back_to_default(self):
    self.dirty_repo("Desktop/projects/alpha", "feat/alpha")
    self.dirty_repo("Desktop/projects/beta", "feat/beta")
    message = self.message_of(
      self.run_hook(
        self.parent,
        extra_env={"PERSONAL_MAIN_CLOSEOUT_BUDGET_SECONDS": "not-a-number"},
      )
    )
    self.assertIn("feat/alpha", message)
    self.assertIn("feat/beta", message)

  def test_company_worktree_mixed_into_parent_is_silent(self):
    repo = self.make_repo("Desktop/work/acme")
    git(repo, "checkout", "-b", "feat/acme")
    write_commit(repo, "acme.txt", "work")
    git(repo, "checkout", "main")
    linked = self.parent / "acme-wt"
    git(repo, "worktree", "add", "-b", "feat/sneaky", str(linked))
    (linked / "draft.txt").write_text("draft\n", encoding="utf-8")
    self.assert_silent(self.run_hook(self.parent))

  def test_all_children_quiet_produces_no_message(self):
    self.make_repo("Desktop/projects/alpha")
    self.make_repo("Desktop/projects/beta")
    self.assert_silent(self.run_hook(self.parent))

  def test_empty_parent_directory_is_silent(self):
    self.assert_silent(self.run_hook(self.parent))

  def test_plain_directory_child_is_skipped(self):
    (self.parent / "notes").mkdir()
    (self.parent / "notes" / "todo.txt").write_text("todo\n", encoding="utf-8")
    self.assert_silent(self.run_hook(self.parent))

  def test_hidden_child_repo_is_skipped(self):
    self.dirty_repo("Desktop/projects/.worktrees", "feat/hidden")
    self.assert_silent(self.run_hook(self.parent))

  def test_nested_grandchild_repo_is_not_scanned(self):
    self.dirty_repo("Desktop/projects/outer/inner", "feat/inner")
    self.assert_silent(self.run_hook(self.parent))

  def test_linked_worktree_beside_its_repo_is_reported_once(self):
    repo = self.make_repo("Desktop/projects/alpha")
    linked = self.parent / "alpha-wt"
    git(repo, "worktree", "add", "-b", "feat/linked", str(linked))
    (linked / "draft.txt").write_text("draft\n", encoding="utf-8")
    message = self.message_of(self.run_hook(self.parent))
    headings = [line for line in message.splitlines() if line.startswith("repo：")]
    self.assertEqual(len(headings), 1)
    self.assertIn("feat/linked：1 項", message)

  def test_parent_is_silent_when_only_out_of_scope_children_report(self):
    repo = self.make_repo("Desktop/work/acme")
    git(repo, "checkout", "-b", "feat/acme")
    write_commit(repo, "acme.txt", "work")
    git(repo, "checkout", "main")
    link = self.parent / "acme-link"
    link.symlink_to(repo)
    self.assert_silent(self.run_hook(self.parent))


class RobustnessTest(HookCase):
  def test_malformed_json_is_silent(self):
    self.assert_silent(self.run_hook(self.home, raw="{not json"))

  def test_empty_stdin_is_silent(self):
    self.assert_silent(self.run_hook(self.home, raw=""))

  def test_non_dict_payload_is_silent(self):
    self.assert_silent(self.run_hook(self.home, raw="[1, 2, 3]"))

  def test_missing_cwd_is_silent(self):
    self.assert_silent(self.run_hook(self.home, raw=json.dumps({"source": "startup"})))

  def test_non_string_cwd_is_silent(self):
    self.assert_silent(self.run_hook(self.home, raw=json.dumps({"cwd": 42})))

  def test_nonexistent_cwd_is_silent(self):
    self.assert_silent(self.run_hook(self.home / "Desktop" / "projects" / "gone"))

  def test_non_git_directory_is_silent(self):
    plain = self.home / "Desktop" / "projects" / "plain"
    plain.mkdir(parents=True)
    self.assert_silent(self.run_hook(plain))

  def test_corrupt_git_directory_is_silent(self):
    repo = self.make_repo("Desktop/projects/broken")
    shutil.rmtree(repo / ".git" / "refs")
    (repo / ".git" / "HEAD").write_text("garbage\n", encoding="utf-8")
    self.assert_silent(self.run_hook(repo))


class CheckoutPositionTest(HookCase):
  def test_clean_merged_branch_checkout_is_reported(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/alpha")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("目前 checkout 在 feat/alpha", message)
    self.assertIn("main", message)

  def test_detached_head_checkout_is_reported(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "--detach")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("目前 checkout 在 detached HEAD", message)

  def test_parked_clean_linked_worktree_is_silent(self):
    repo = self.make_repo("Desktop/projects/alpha")
    linked = self.home / "Desktop" / "projects" / "alpha-wt"
    git(repo, "worktree", "add", "-b", "feat/parked", str(linked))
    self.assert_silent(self.run_hook(repo))

  def test_checkout_on_trunk_stays_silent(self):
    repo = self.make_repo("Desktop/projects/alpha")
    self.assert_silent(self.run_hook(repo))


class NoWorktreeNudgeTest(HookCase):
  def test_non_trunk_checkout_has_system_message_only(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/alpha")
    payload = json.loads(self.run_hook(repo).stdout)
    self.assertIn("systemMessage", payload)
    self.assertIn(CLOSEOUT_ACTION, payload["systemMessage"])
    self.assertNotIn("hookSpecificOutput", payload)

  def test_dirty_repo_without_trunk_ref_is_silent(self):
    repo = self.make_repo("Desktop/projects/alpha", branch="develop", origin=False)
    (repo / "draft.txt").write_text("draft\n", encoding="utf-8")
    self.assert_silent(self.run_hook(repo))

  def test_other_clean_worktree_is_silent(self):
    repo = self.make_repo("Desktop/projects/alpha")
    linked = self.home / "Desktop" / "projects" / "alpha-wt"
    git(repo, "worktree", "add", "-b", "feat/linked", str(linked))
    self.assert_silent(self.run_hook(repo))

  def test_entering_clean_linked_worktree_is_silent(self):
    repo = self.make_repo("Desktop/projects/alpha")
    linked = self.home / "Desktop" / "projects" / "alpha-wt"
    git(repo, "worktree", "add", "-b", "feat/linked", str(linked))
    self.assert_silent(self.run_hook(linked))

  def test_disable_env_keeps_system_message_without_context(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/alpha")
    result = self.run_hook(repo, extra_env={"GIT_CLOSEOUT_DISABLE": "1"})
    payload = json.loads(result.stdout)
    self.assertIn("systemMessage", payload)
    self.assertIn(CLOSEOUT_ACTION, payload["systemMessage"])
    self.assertNotIn("hookSpecificOutput", payload)

  def test_disable_sentinel_keeps_system_message_without_context(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/alpha")
    sentinel = self.home / ".claude" / "hooks" / ".git-closeout-disabled"
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.touch()
    payload = json.loads(self.run_hook(repo).stdout)
    self.assertIn("systemMessage", payload)
    self.assertIn(CLOSEOUT_ACTION, payload["systemMessage"])
    self.assertNotIn("hookSpecificOutput", payload)

  def test_dirty_main_remains_unchanged(self):
    repo = self.make_repo("Desktop/projects/alpha")
    (repo / "draft.txt").write_text("draft\n", encoding="utf-8")
    before_status = git(repo, "status", "--porcelain").stdout
    before_head = git(repo, "rev-parse", "HEAD").stdout
    self.assert_silent(self.run_hook(repo))
    self.assertEqual(git(repo, "status", "--porcelain").stdout, before_status)
    self.assertEqual(git(repo, "rev-parse", "HEAD").stdout, before_head)


class WorkScopeTest(HookCase):
  def setUp(self):
    super().setUp()
    (self.home / "Desktop" / "work" / "acme").mkdir(parents=True)

  def make_acme_repo(self, name, branch="stage"):
    return self.make_repo(f"Desktop/work/acme/{name}", branch=branch)

  def make_acme_parent(self):
    parent = self.home / "Desktop" / "work" / "acme"
    git(parent, "init", "-b", "main")
    write_commit(parent, "governance.md", "init")
    return parent

  def test_acme_child_repo_is_reported(self):
    repo = self.make_acme_repo("dashboard")
    git(repo, "checkout", "-b", "feat/stray")
    write_commit(repo, "stray.txt", "stray work")
    git(repo, "checkout", "stage")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("feat/stray", message)

  def test_report_is_marked_as_work_repo(self):
    repo = self.make_acme_repo("dashboard")
    git(repo, "checkout", "-b", "feat/stray")
    write_commit(repo, "stray.txt", "stray work")
    git(repo, "checkout", "stage")
    message = self.message_of(self.run_hook(repo))
    self.assertIn(WORK_NOTE, message)

  def test_personal_report_is_not_marked_as_work(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/alpha")
    write_commit(repo, "alpha.txt", "alpha work")
    git(repo, "checkout", "main")
    message = self.message_of(self.run_hook(repo))
    self.assertNotIn(WORK_NOTE, message)

  def test_work_repo_outside_acme_stays_silent(self):
    repo = self.make_repo("Desktop/work/acme")
    git(repo, "checkout", "-b", "feat/stray")
    write_commit(repo, "stray.txt", "stray work")
    git(repo, "checkout", "main")
    self.assert_silent(self.run_hook(repo))

  def test_stage_is_preferred_over_origin_head(self):
    repo = self.make_acme_repo("dashboard", branch="main")
    git(repo, "checkout", "-b", "stage")
    write_commit(repo, "stage.txt", "stage work")
    git(repo, "push", "-u", "origin", "stage")
    git(repo, "checkout", "-b", "feat/merged-into-stage")
    write_commit(repo, "feature.txt", "feature work")
    git(repo, "checkout", "stage")
    git(repo, "merge", "--no-ff", "-m", "merge feature", "feat/merged-into-stage")
    git(repo, "push", "origin", "stage")
    self.assert_silent(self.run_hook(repo))

  def test_branch_off_stage_is_reported(self):
    repo = self.make_acme_repo("dashboard", branch="main")
    git(repo, "checkout", "-b", "stage")
    write_commit(repo, "stage.txt", "stage work")
    git(repo, "push", "-u", "origin", "stage")
    git(repo, "checkout", "-b", "feat/not-merged")
    write_commit(repo, "feature.txt", "feature work")
    git(repo, "checkout", "stage")
    message = self.message_of(self.run_hook(repo))
    self.assertIn("feat/not-merged", message)

  def test_pinned_work_checkout_still_reports(self):
    repo = self.make_acme_repo("dashboard")
    git(repo, "checkout", "-b", "feat/preserved")
    write_commit(repo, "feature.txt", "feature work")
    tip = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "remote", "set-url", "origin", "https://github.com/acmeInc/dashboard.git")
    policy = self.home / ".claude" / "policies" / "personal-main-closeout" / "ignore.jsonl"
    policy.parent.mkdir(parents=True)
    policy.write_text(json.dumps({"identity": "github.com/acmeInc/dashboard", "ref": "refs/heads/feat/preserved", "tip": tip}) + "\n", encoding="utf-8")
    self.assertIn("目前 checkout 在 feat/preserved", self.message_of(self.run_hook(repo)))

  def test_acme_parent_scans_children(self):
    parent = self.make_acme_parent()
    repo = self.make_acme_repo("dashboard")
    git(repo, "checkout", "-b", "feat/stray")
    write_commit(repo, "stray.txt", "stray work")
    git(repo, "checkout", "stage")
    message = self.message_of(self.run_hook(parent))
    self.assertIn("feat/stray", message)
    self.assertEqual(message.count(CLOSEOUT_ACTION), 1)

  def test_acme_parent_includes_itself(self):
    parent = self.make_acme_parent()
    git(parent, "checkout", "-b", "docs/private")
    write_commit(parent, "notes.md", "private notes")
    git(parent, "checkout", "main")
    message = self.message_of(self.run_hook(parent))
    self.assertIn("docs/private", message)

  def test_projects_parent_is_unaffected(self):
    repo = self.make_repo("Desktop/projects/alpha")
    git(repo, "checkout", "-b", "feat/alpha")
    write_commit(repo, "alpha.txt", "alpha work")
    git(repo, "checkout", "main")
    message = self.message_of(self.run_hook(self.home / "Desktop" / "projects"))
    self.assertIn("feat/alpha", message)
    self.assertNotIn(WORK_NOTE, message)

  def test_work_repo_is_not_mutated(self):
    repo = self.make_acme_repo("dashboard")
    git(repo, "checkout", "-b", "feat/stray")
    write_commit(repo, "stray.txt", "stray work")
    (repo / "draft.txt").write_text("draft\n", encoding="utf-8")
    before_status = git(repo, "status", "--porcelain").stdout
    before_head = git(repo, "rev-parse", "HEAD").stdout
    before_branches = git(repo, "for-each-ref", "--format=%(refname)", "refs/heads").stdout
    self.message_of(self.run_hook(repo))
    self.assertEqual(git(repo, "status", "--porcelain").stdout, before_status)
    self.assertEqual(git(repo, "rev-parse", "HEAD").stdout, before_head)
    self.assertEqual(
      git(repo, "for-each-ref", "--format=%(refname)", "refs/heads").stdout,
      before_branches,
    )


if __name__ == "__main__":
  unittest.main()
