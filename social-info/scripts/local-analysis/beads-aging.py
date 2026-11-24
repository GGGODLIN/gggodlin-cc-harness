#!/usr/bin/env python3

import argparse
import json
import math
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_ROOTS = (
  Path.home() / "Desktop" / "work",
  Path.home() / "Desktop" / "projects",
)
SKIP_DIRS = {".git", "node_modules", "dist", "build", "out", ".shopify", ".stryker-tmp", ".worktrees"}
ACTIVE_STATUSES = "open,in_progress,blocked,deferred"
DEFAULT_TIMEZONE = "Asia/Taipei"


def parse_day(value, tz):
  if value is None:
    return None
  if not isinstance(value, str):
    raise ValueError("date value must be a string")
  raw = value.strip()
  if not raw:
    return None
  if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
    return date.fromisoformat(raw)
  parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
  localized = parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)
  return localized.astimezone(tz).date()


def parse_moment(value, tz):
  if not isinstance(value, str):
    raise ValueError("timestamp value must be a string")
  raw = value.strip()
  if not raw:
    raise ValueError("timestamp value must not be empty")
  if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
    return datetime.combine(date.fromisoformat(raw), datetime.min.time(), tz)
  parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
  localized = parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)
  return localized.astimezone(tz)


def discover_repos(roots):
  repos = set()
  visited = set()
  for root in roots:
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
      continue
    if (root / ".beads").is_dir():
      repos.add(str(root))
    for current, dirs, _files in os.walk(root, followlinks=True):
      try:
        stat = os.stat(current)
      except OSError:
        dirs.clear()
        continue
      key = (stat.st_dev, stat.st_ino)
      if key in visited:
        dirs.clear()
        continue
      visited.add(key)
      dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
      if ".beads" not in dirs:
        continue
      repos.add(str(Path(current).resolve()))
      dirs.remove(".beads")
  return sorted(repos)


def validate_issue(issue, repo, index, tz=None):
  if not isinstance(issue, dict):
    raise RuntimeError(f"bd list issue {index} for {repo} must be an object")
  for field in ("id", "title"):
    if not isinstance(issue.get(field), str) or not issue[field].strip():
      raise RuntimeError(f"bd list issue {index} for {repo} has invalid {field}")
  priority = issue.get("priority")
  if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 4:
    raise RuntimeError(f"bd list issue {index} for {repo} has invalid priority")
  effective_tz = tz if tz is not None else ZoneInfo(DEFAULT_TIMEZONE)
  try:
    parse_moment(issue.get("updated_at"), effective_tz)
  except (ValueError, OverflowError) as error:
    raise RuntimeError(f"bd list issue {issue['id']} for {repo} has invalid updated_at") from error
  for field in ("due_at", "due", "defer_until"):
    if issue.get(field) is None:
      continue
    try:
      parse_day(issue[field], effective_tz)
    except (ValueError, OverflowError) as error:
      raise RuntimeError(f"bd list issue {issue['id']} for {repo} has invalid {field}") from error
  return issue


def load_issues(repo, bd_bin, timeout, tz=None):
  command = [
    bd_bin,
    "-C",
    repo,
    "list",
    "--json",
    "--readonly",
    "--limit",
    "0",
    "--status",
    ACTIVE_STATUSES,
  ]
  try:
    result = subprocess.run(command, capture_output=True, timeout=timeout)
  except subprocess.TimeoutExpired as error:
    raise RuntimeError(f"bd list timed out after {timeout:g}s for {repo}") from error
  stdout = result.stdout.decode("utf-8", errors="replace")
  stderr = result.stderr.decode("utf-8", errors="replace")
  if result.returncode != 0:
    detail = stderr.strip() or stdout.strip() or f"exit {result.returncode}"
    raise RuntimeError(f"bd list failed for {repo}: {detail}")
  try:
    data = json.loads(stdout)
  except json.JSONDecodeError as error:
    raise RuntimeError(f"bd list returned invalid JSON for {repo}: {error}") from error
  if not isinstance(data, list):
    raise RuntimeError(f"bd list returned non-array JSON for {repo}")
  return [validate_issue(issue, repo, index, tz) for index, issue in enumerate(data)]


def classify(issue, analysis_day, tz):
  raw_due_at = issue.get("due_at")
  due_value = raw_due_at if (isinstance(raw_due_at, str) and raw_due_at.strip()) else issue.get("due")
  due = parse_day(due_value, tz)
  deferred = parse_day(issue.get("defer_until"), tz)
  updated = parse_moment(issue.get("updated_at"), tz)
  updated_day = updated.date()
  age_days = max(0, (analysis_day - updated_day).days)

  if deferred and deferred > analysis_day:
    return None
  if due and due < analysis_day:
    days = (analysis_day - due).days
    return 0, due, f"逾期 {days} 天", age_days, due, deferred, updated
  if due and (days := (due - analysis_day).days) <= 7:
    reason = "今天到期" if days == 0 else f"{days} 天內到期"
    return 1, due, reason, age_days, due, deferred, updated
  if deferred and deferred <= analysis_day:
    days = (analysis_day - deferred).days
    return 2, deferred, f"defer 已到 {days} 天", age_days, due, deferred, updated
  if age_days >= 30:
    return 3, updated_day, f"{age_days} 天未更新", age_days, due, deferred, updated
  return None


def collect_candidates(repos, bd_bin, analysis_day, tz, timeout):
  candidates = []
  failures = []
  for repo in repos:
    try:
      issues = load_issues(repo, bd_bin, timeout, tz)
    except RuntimeError as error:
      failures.append({"repo": repo, "error": str(error)})
      continue
    for issue in issues:
      classified = classify(issue, analysis_day, tz)
      if classified is None:
        continue
      category, urgency, reason, age_days, due, deferred, updated = classified
      priority = int(issue.get("priority", 4))
      candidates.append({
        "repo": repo,
        "id": str(issue.get("id", "")),
        "title": str(issue.get("title", "")),
        "priority": priority,
        "reason": reason,
        "age_days": age_days,
        "due": due,
        "defer": deferred,
        "sort": (category, urgency, priority, updated, repo, str(issue.get("id", ""))),
      })
  return sorted(candidates, key=lambda item: item["sort"]), failures


def display_day(value):
  return value.isoformat() if value else "—"


def render(candidates, analysis_day, repo_count, limit, failures):
  if not candidates and not failures:
    return "__SILENT__"
  shown = candidates[:limit]
  lines = [
    f"# Beads Aging Weekly — {analysis_day.isoformat()}",
    "",
    f"scanned_projects: {repo_count}",
    f"candidates: {len(candidates)}",
    f"shown: {len(shown)}",
    f"remaining: {max(0, len(candidates) - len(shown))}",
  ]
  if failures:
    lines.extend(["", f"## ⚠️ 掃描失敗 repo（{len(failures)}，本輪不在候選分母內）"])
    for item in failures:
      lines.append(f"- `{item['repo']}`：{item['error']}")
  for index, item in enumerate(shown, 1):
    lines.extend([
      "",
      f"## B{index}",
      f"- repo: `{item['repo']}`",
      f"- id: `{item['id']}`",
      f"- reason: {item['reason']}",
      f"- priority: P{item['priority']}",
      f"- due: {display_day(item['due'])}",
      f"- defer: {display_day(item['defer'])}",
      f"- age_days: {item['age_days']}",
      f"- title: {item['title']}",
    ])
  return "\n".join(lines)


def write_output(path, content):
  if path == "-":
    print(content)
    return
  target = Path(path).expanduser()
  target.parent.mkdir(parents=True, exist_ok=True)
  target.write_text(content + "\n")


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--date", required=True)
  parser.add_argument("--out", required=True)
  parser.add_argument("--root", action="append")
  parser.add_argument("--bd-bin", default="bd")
  parser.add_argument("--bd-timeout", type=float, default=30)
  parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
  parser.add_argument("--limit", type=int, default=2)
  args = parser.parse_args()

  if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
    raise SystemExit("--date must be YYYY-MM-DD")
  if args.limit < 1:
    raise SystemExit("--limit must be at least 1")
  if not math.isfinite(args.bd_timeout) or args.bd_timeout <= 0:
    raise SystemExit("--bd-timeout must be greater than 0")
  try:
    analysis_tz = ZoneInfo(args.timezone)
  except ZoneInfoNotFoundError as error:
    raise SystemExit(f"unknown timezone: {args.timezone}") from error

  analysis_day = date.fromisoformat(args.date)
  repos = discover_repos(args.root or DEFAULT_ROOTS)
  candidates, failures = collect_candidates(repos, args.bd_bin, analysis_day, analysis_tz, args.bd_timeout)
  write_output(args.out, render(candidates, analysis_day, len(repos), args.limit, failures))


if __name__ == "__main__":
  try:
    main()
  except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
    print(str(error), file=sys.stderr)
    raise SystemExit(1)
