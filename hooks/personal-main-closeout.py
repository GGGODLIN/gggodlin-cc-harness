#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import time


HEADER = "個人 repo 收尾檢查：以下項目請確認是否需要處理。"

CLOSEOUT_ACTION = "請執行 `/git-closeout` 處理以上 Git 狀態，再開始新工作。"

MAX_LISTED = 10

BUDGET_ENV = "PERSONAL_MAIN_CLOSEOUT_BUDGET_SECONDS"

DEFAULT_BUDGET_SECONDS = 5.0

SILENT_SOURCES = ("compact", "clear")

TRUNK_FALLBACKS = (
  "refs/remotes/origin/main",
  "refs/remotes/origin/master",
  "refs/heads/main",
  "refs/heads/master",
)

WORK_TRUNK_FALLBACKS = (
  "refs/remotes/origin/stage",
  "refs/remotes/origin/main",
  "refs/remotes/origin/master",
  "refs/heads/main",
  "refs/heads/master",
)

WORK_PARENTS = (("Desktop", "work", "acme"),)

WORK_NOTE = "（公司 repo · 只報告，處置一律等你決定）"


def home_directory():
  value = os.environ.get("HOME")
  return Path(value) if value else Path.home()


def resolved(path):
  return Path(path).resolve()


def personal_roots():
  home = home_directory()
  return (
    resolved(home / "Desktop" / "projects"),
    resolved(home / ".claude"),
    resolved(home / "code" / "social-info"),
  )


def contained(path, root):
  return path == root or root in path.parents


def work_parents():
  home = home_directory()
  return tuple(resolved(home.joinpath(*parts)) for parts in WORK_PARENTS)


def repo_scope(repo):
  if contained(repo, resolved(home_directory() / "Desktop" / "work")):
    if any(contained(repo, parent) for parent in work_parents()):
      return "work"
    return None
  if repo == resolved(home_directory() / "Desktop" / "projects"):
    return None
  if any(contained(repo, root) for root in personal_roots()):
    return "personal"
  return None


def personal_repo(repo):
  return repo_scope(repo) == "personal"


def run_git(cwd, *args):
  return subprocess.run(
    ["git", "-C", str(cwd), *args],
    capture_output=True,
    check=False,
    env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    text=True,
  )


def git_lines(cwd, *args):
  result = run_git(cwd, *args)
  if result.returncode != 0:
    return []
  return [line for line in result.stdout.splitlines() if line.strip()]


def git_value(cwd, *args):
  result = run_git(cwd, *args)
  if result.returncode != 0:
    return None
  return result.stdout.strip() or None


def ref_exists(cwd, ref):
  return run_git(cwd, "show-ref", "--verify", "--quiet", ref).returncode == 0


def trunk_ref(cwd, scope="personal"):
  if scope == "work":
    for ref in WORK_TRUNK_FALLBACKS:
      if ref_exists(cwd, ref):
        return ref
    return None
  head = git_value(cwd, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
  if head is not None and ref_exists(cwd, head):
    return head
  for ref in TRUNK_FALLBACKS:
    if ref_exists(cwd, ref):
      return ref
  return None


def trunk_name(ref):
  for prefix in ("refs/remotes/origin/", "refs/heads/"):
    if ref.startswith(prefix):
      return ref[len(prefix):]
  return ref


def unmerged_branches(cwd, ref, trunk):
  found = []
  for branch in git_lines(cwd, "for-each-ref", "--format=%(refname:short)", "refs/heads"):
    if branch == trunk:
      continue
    if run_git(cwd, "merge-base", "--is-ancestor", branch, ref).returncode == 1:
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


def worktree_entries(cwd):
  entries = []
  for line in git_lines(cwd, "worktree", "list", "--porcelain"):
    key, _, value = line.partition(" ")
    if key == "worktree":
      entries.append({"path": Path(value), "branch": None})
    elif key == "branch" and entries:
      entries[-1]["branch"] = trunk_name(value)
  return entries


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


def ignore_file():
  return home_directory() / ".claude" / "policies" / "personal-main-closeout" / "ignore.jsonl"


def normalized_identity(url):
  text = url.strip().split("?", 1)[0].split("#", 1)[0]
  scheme = "://" in text
  if scheme:
    text = text.split("://", 1)[1]
  if "@" in text:
    text = text.split("@", 1)[1]
  if not scheme and ":" in text:
    host, _, tail = text.partition(":")
    text = f"{host}/{tail.lstrip('/')}"
  text = text.rstrip("/")
  if text.endswith(".git"):
    text = text[: -len(".git")]
  return text


def repo_identity(cwd, repo):
  url = git_value(cwd, "config", "--get", "remote.origin.url")
  if url is None:
    return repo.name
  return normalized_identity(url) or repo.name


def branch_of_ref(ref):
  return ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref


def ignore_entries():
  try:
    content = ignore_file().read_text(encoding="utf-8")
  except (OSError, ValueError):
    return []
  entries = []
  for line in content.splitlines():
    if not line.strip():
      continue
    try:
      record = json.loads(line)
    except ValueError:
      continue
    if not isinstance(record, dict):
      continue
    identity = record.get("identity")
    ref = record.get("ref")
    if not isinstance(identity, str) or not isinstance(ref, str):
      continue
    tip = record.get("tip")
    entries.append(
      {
        "identity": normalized_identity(identity),
        "branch": branch_of_ref(ref),
        "tip": tip if isinstance(tip, str) else None,
      }
    )
  return entries


# `"ref": "*"` 把整個 repo 交給別的工具或 agent 管（例如 Codex 做到一半的專案），
# 收尾檢查對它一律不報；只有使用者明確核准才寫進 ignore.jsonl。
def repo_excluded(identity):
  return any(entry["branch"] == "*" and entry["identity"] == identity for entry in ignore_entries())


def ignored_branches(cwd, identity):
  ignored = set()
  pinned = set()
  for entry in ignore_entries():
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


def source_repo(cwd):
  value = git_value(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
  if value is None:
    return None
  common = resolved(value)
  return common.parent if common.name == ".git" else common


def inspect_repo(path):
  repo = source_repo(path)
  scope = repo_scope(repo) if repo is not None else None
  if scope is None:
    return None
  ref = trunk_ref(path, scope)
  if ref is None:
    return None
  trunk = trunk_name(ref)
  identity = repo_identity(path, repo)
  if repo_excluded(identity):
    return None
  ignored, pinned = ignored_branches(path, identity)
  return {
    "repo": repo,
    "scope": scope,
    "trunk": trunk,
    "unmerged": [
      branch for branch in unmerged_branches(path, ref, trunk) if branch not in ignored
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


def child_repositories(parent):
  children = []
  for child in sorted(parent.iterdir()):
    if child.name.startswith(".") or not child.is_dir():
      continue
    if (child / ".git").exists():
      children.append(child)
  return children


def inspect_quietly(path):
  try:
    return inspect_repo(path)
  except (OSError, ValueError, subprocess.SubprocessError):
    return None


def scan_targets(parent):
  children = child_repositories(parent)
  if (parent / ".git").exists():
    return [parent, *children]
  return children


def scan_parent(parent):
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
    report = inspect_quietly(child)
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
    if here in parents:
      message = scan_parent(here)
    else:
      report = inspect_repo(Path(cwd))
      message = format_report(report) if report is not None else None
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
