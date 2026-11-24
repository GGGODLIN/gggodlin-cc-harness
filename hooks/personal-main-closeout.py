#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import time

# resolve()：多帳號設定目錄的 hooks 是指回 ~/.claude 的 symlink，共用模組只在正本旁邊。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

from closeout_repos import (  # noqa: E402
  declared_trunk,
  git_lines,
  git_value,
  home_directory,
  ignore_entries,
  level_with_remote,
  pushed_equal_enabled,
  read_policy,
  ref_exists,
  repo_excluded,
  repo_identity,
  repo_scope,
  resolved,
  run_git,
  scan_targets,
  source_repo,
  trunk_name,
  trunk_ref,
  work_parents,
  worktree_entries,
)


HEADER = "個人 repo 收尾檢查：以下項目請確認是否需要處理。"

CLOSEOUT_ACTION = "請執行 `/git-closeout` 處理以上 Git 狀態，再開始新工作。"

MAX_LISTED = 10

BUDGET_ENV = "PERSONAL_MAIN_CLOSEOUT_BUDGET_SECONDS"

DEFAULT_BUDGET_SECONDS = 5.0

SILENT_SOURCES = ("compact", "clear")

WORK_NOTE = "（公司 repo · 只報告，處置一律等你決定）"


def policy_note(bad_lines):
  if not bad_lines:
    return None
  numbers = "、".join(str(number) for number in bad_lines[:MAX_LISTED])
  return f"政策檔 ignore.jsonl 有 {len(bad_lines)} 行讀不懂（第 {numbers} 行），已略過；其餘登記照常生效。"


def unmerged_branches(cwd, refs, trunk):
  """Local branches that are an ancestor of none of `refs`."""
  found = []
  for branch in git_lines(cwd, "for-each-ref", "--format=%(refname:short)", "refs/heads"):
    if branch == trunk:
      continue
    if all(run_git(cwd, "merge-base", "--is-ancestor", branch, ref).returncode == 1 for ref in refs):
      found.append(branch)
  return found


def unpushed_count(cwd, ref, trunk):
  if not ref.startswith("refs/remotes/origin/"):
    return 0
  local = f"refs/heads/{trunk}"
  if not ref_exists(cwd, local):
    return 0
  value = git_value(cwd, "rev-list", "--count", f"{ref}..{local}")
  return int(value) if value is not None and value.isdigit() else 0


def uncommitted_counts(cwd, trunk):
  counts = []
  for entry in worktree_entries(cwd):
    branch = entry["branch"]
    if branch == trunk or not entry["path"].is_dir():
      continue
    count = len(git_lines(entry["path"], "status", "--porcelain"))
    if count:
      counts.append(f"{branch or entry['path'].name}：{count} 項")
  return counts


def ignored_branches(cwd, identity, entries):
  ignored = set()
  pinned = set()
  for entry in entries:
    if entry["identity"] != identity:
      continue
    branch = entry["branch"]
    if entry["tip"] is not None:
      current = git_value(cwd, "rev-parse", f"refs/heads/{branch}")
      if current != entry["tip"]:
        continue
      pinned.add(branch)
    ignored.add(branch)
  return ignored, pinned


def checked_out_off_trunk(cwd, repo, trunk, pinned):
  toplevel = git_value(cwd, "rev-parse", "--show-toplevel")
  if toplevel is None or resolved(toplevel) != repo:
    return None
  branch = git_value(cwd, "symbolic-ref", "--quiet", "--short", "HEAD")
  if branch is None:
    return "detached HEAD"
  if branch in pinned:
    status = run_git(cwd, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode == 0 and not status.stdout:
      return None
  return None if branch == trunk else branch


def inspect_repo(path, records):
  repo = source_repo(path)
  scope = repo_scope(repo) if repo is not None else None
  if scope is None:
    return None
  identity = repo_identity(path, repo)
  entries = ignore_entries(records)
  if repo_excluded(identity, entries):
    return None
  # 公司 repo 的主幹與待處理清單不吃個人政策：那邊的處置一律等使用者決定。
  personal = scope == "personal"
  ref = trunk_ref(path, scope, declared_trunk(identity, records) if personal else None)
  if ref is None:
    return None
  trunk = trunk_name(ref)
  # 宣告了別條主幹的 repo，預設主幹通常是發版線（例如 main 帶有 dev 不會有的發版 commit）。
  # 已併進發版線的 branch 在宣告前不會被列出，宣告後也不該冒出來，所以兩條都算「已整合」。
  declared = declared_trunk(identity, records) if personal else None
  default_ref = trunk_ref(path, scope) if declared else None
  merged_into = [ref] if default_ref in (None, ref) else [ref, default_ref]
  ignored, pinned = ignored_branches(path, identity, entries)
  skip_level = personal and pushed_equal_enabled(identity, records)
  return {
    "repo": repo,
    "scope": scope,
    "trunk": trunk,
    "unmerged": [
      branch
      for branch in unmerged_branches(path, merged_into, trunk)
      if branch not in ignored and not (skip_level and level_with_remote(path, branch))
    ],
    "stash": git_lines(path, "stash", "list"),
    "uncommitted": uncommitted_counts(path, trunk),
    "unpushed": unpushed_count(path, ref, trunk),
    "checked_out": checked_out_off_trunk(path, repo, trunk, pinned if scope == "personal" else set()),
  }


def listed(items):
  lines = [f"  - {item}" for item in items[:MAX_LISTED]]
  remaining = len(items) - MAX_LISTED
  if remaining > 0:
    lines.append(f"  另有 {remaining} 項")
  return lines


def report_lines(report):
  sections = []
  if report["unmerged"]:
    sections.append(f"未合併進 {report['trunk']} 的本機 branch，請確認：")
    sections.extend(listed(report["unmerged"]))
  if report["stash"]:
    sections.append("stash 尚未處理，請確認：")
    sections.extend(listed(report["stash"]))
  if report["uncommitted"]:
    sections.append("未 commit 變更，請確認：")
    sections.extend(listed(report["uncommitted"]))
  if report["unpushed"]:
    sections.append(
      f"{report['trunk']} 領先 origin {report['unpushed']} 個 commit，請確認是否要 push。"
    )
  if report["checked_out"]:
    sections.append(
      f"目前 checkout 在 {report['checked_out']}、非主幹 {report['trunk']}，請確認是否切回。"
    )
  if not sections:
    return None
  label = f"repo：{report['repo']}"
  if report.get("scope") == "work":
    label = f"{label}{WORK_NOTE}"
  return [label, *sections]


def format_report(report):
  lines = report_lines(report)
  if lines is None:
    return None
  return "\n".join([HEADER, CLOSEOUT_ACTION, *lines])


def budget_seconds():
  try:
    value = float(os.environ[BUDGET_ENV])
  except (KeyError, TypeError, ValueError):
    return DEFAULT_BUDGET_SECONDS
  return value if value > 0 else DEFAULT_BUDGET_SECONDS


def with_policy_note(message, bad_lines):
  note = policy_note(bad_lines)
  if note is None:
    return message
  if message:
    return f"{message}\n{note}"
  return "\n".join([HEADER, note])


def inspect_quietly(path, records):
  try:
    return inspect_repo(path, records)
  except (OSError, ValueError, subprocess.SubprocessError):
    return None


def scan_parent(parent, records):
  children = scan_targets(parent)
  budget = budget_seconds()
  start = time.monotonic()
  blocks = []
  seen = set()
  skipped = 0
  for index, child in enumerate(children):
    if index and time.monotonic() - start >= budget:
      skipped = len(children) - index
      break
    report = inspect_quietly(child, records)
    if report is None or report["repo"] in seen:
      continue
    seen.add(report["repo"])
    lines = report_lines(report)
    if lines is not None:
      blocks.append(lines)
  if not blocks:
    return None
  sections = []
  for lines in blocks:
    if sections:
      sections.append("")
    sections.extend(lines)
  if skipped:
    sections.append(f"其餘 {skipped} 個未掃，本次時間預算已用完。")
  return "\n".join([HEADER, CLOSEOUT_ACTION, *sections])


def main():
  try:
    payload = json.load(sys.stdin)
  except (OSError, ValueError):
    return 0
  if not isinstance(payload, dict):
    return 0
  if payload.get("source") in SILENT_SOURCES:
    return 0
  cwd = payload.get("cwd")
  if not isinstance(cwd, str):
    return 0
  try:
    here = resolved(cwd)
    parents = (resolved(home_directory() / "Desktop" / "projects"), *work_parents())
    records, bad_lines = read_policy()
    if here in parents:
      message = with_policy_note(scan_parent(here, records), bad_lines)
    else:
      report = inspect_repo(Path(cwd), records)
      # 範圍外或整個交給其他工具的 repo 維持完全安靜，政策檔的問題不在那裡提。
      message = with_policy_note(format_report(report), bad_lines) if report is not None else None
  except (OSError, ValueError, subprocess.SubprocessError):
    return 0
  output = {}
  if message:
    output["systemMessage"] = message
  if output:
    sys.stdout.write(json.dumps(output, ensure_ascii=False))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
