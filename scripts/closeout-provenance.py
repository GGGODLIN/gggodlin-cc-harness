#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
BASH_WRITE_MARKERS = ("open(", ".write(", "write_text(", "write_bytes(", ">>", "> ", "tee ", "sed -i", "cp ", "mv ")
CD_TOKEN = re.compile(r"(?:^|&&|;|\|\||\n)\s*cd\s+([^\s;&|]+)")
# Bash 寫入只認「路徑是寫入構造的目標」：`sed -n … > /tmp/x` 這種唯讀指令帶重導向，
# 以前因為指令裡同時出現 repo 路徑與 `> ` 就被當成寫入者，造成假的 co_written（2026-10-09 實證兩例）
WRITE_TARGET_PATTERNS = (
  re.compile(r"(?<![<>])>{1,2}\s*['\"]?([^\s'\"|;&<>]+)"),
  re.compile(r"\btee\s+(?:-a\s+)?['\"]?([^\s'\"|;&]+)"),
  re.compile(r"\bsed\s+-i(?:\s+'')?(?:\s+-e\s+(?:'[^']*'|\"[^\"]*\"|\S+)|\s+(?:'[^']*'|\"[^\"]*\"))*\s+['\"]?([^\s'\"|;&]+)"),
  re.compile(r"\b(?:cp|mv)\s+(?:-\S+\s+)*(?:\S+\s+)+['\"]?([^\s'\"|;&]+)"),
  re.compile(r"open\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][wa]"),
  re.compile(r"Path\(\s*['\"]([^'\"]+)['\"]\s*\)"),
)
# 共用集合：每個 session 都在寫的帳本，self-closeout 整組收成 checkpoint、不看作者；
# 清單與 commands/self-closeout.md 第 2 步同步，改一邊要改另一邊。
SHARED_REPOS = tuple(
  Path(p).expanduser() for p in os.environ["CLOSEOUT_SHARED_REPOS"].split(":") if p
) if os.environ.get("CLOSEOUT_SHARED_REPOS") else (Path.home() / ".claude", Path.home() / "Desktop" / "projects" / ".claude")
SHARED_PREFIXES = ("memory/", "trials/", "friction/")
SHARED_EXACT = ("references/failure-mode-taxonomy.md", "settings.json")
SHARED_BASENAMES = ("friction-log.md",)
# claude.ai 同步輪搬進來的 vendor skill 副本，不是自撰內容，收進歷史只會每輪同步再報一次
VENDOR_MANAGED_PREFIXES = ("skills/.trash/", "skills/synced/")
BASH_PATH_TOKEN = re.compile(r"(?:~|/Users/[A-Za-z0-9_.-]+)(?:/[^\s'\"`;|<>()&]+)+")
PROJECTS_DIR = Path.home() / ".claude" / "projects"
CODEX_SESSIONS = Path.home() / ".codex" / "sessions"


def run_git(repo, *args):
  result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
  return result.stdout if result.returncode == 0 else ""


def repo_toplevel(path):
  path = Path(path)
  if path.is_file():
    path = path.parent
  top = run_git(path, "rev-parse", "--show-toplevel").strip()
  if not top:
    return None
  top = Path(top).resolve()
  # 多帳號 config dir（~/.claude-team-*）的 .git 是 ~/.claude/.git 的 symlink，
  # 操作一律回正本，否則同一個 repo 會被列兩次、而且替代目錄相對 HEAD 有數千個假 D
  dot_git = top / ".git"
  if dot_git.is_symlink():
    top = dot_git.resolve().parent
  return top


def dirty_paths(repo):
  out = run_git(repo, "status", "--porcelain=v1", "--untracked-files=all", "-z")
  entries = [e for e in out.split("\0") if e]
  paths = []
  skip_next = False
  for entry in entries:
    if skip_next:
      skip_next = False
      continue
    code = entry[:2]
    rel = entry[3:]
    if "R" in code or "C" in code:
      skip_next = True
    paths.append((code, (repo / rel).resolve()))
  return paths


def staged_paths(repo):
  out = run_git(repo, "diff", "--cached", "--name-only", "-z")
  return [(repo / p).resolve() for p in out.split("\0") if p]


def unstaged_paths(repo):
  out = run_git(repo, "diff", "--name-only", "-z")
  return [(repo / p).resolve() for p in out.split("\0") if p]


def is_shared_repo(repo):
  # 共用集合只存在於兩個固定 repo；普通專案自己的 memory/ 或 settings.json 不是使用者的共用帳本，
  # 不能因為路徑同名就被整組 checkpoint
  resolved = Path(repo).resolve()
  return any(resolved == shared.resolve() for shared in SHARED_REPOS if shared.exists())


def is_shared(repo, rel):
  if not is_shared_repo(repo):
    return False
  return rel.startswith(SHARED_PREFIXES) or rel in SHARED_EXACT or rel.rsplit("/", 1)[-1] in SHARED_BASENAMES


def is_vendor_managed(rel):
  return rel.startswith(VENDOR_MANAGED_PREFIXES)


def bash_path_tokens(command):
  for match in BASH_PATH_TOKEN.finditer(command):
    yield Path(match.group(0)).expanduser()


def bash_write_targets(command):
  targets = set()
  for pattern in WRITE_TARGET_PATTERNS:
    for match in pattern.finditer(command):
      targets.add(match.group(1).strip("'\""))
  return targets


def last_commit_ts(repo, path):
  out = run_git(repo, "log", "-1", "--format=%ct", "--", str(path)).strip()
  return int(out) if out else None


def iter_events(jsonl_path):
  with open(jsonl_path, "r", encoding="utf-8", errors="replace") as handle:
    for line in handle:
      try:
        obj = json.loads(line)
      except json.JSONDecodeError:
        continue
      message = obj.get("message")
      if not isinstance(message, dict):
        continue
      content = message.get("content")
      if not isinstance(content, list):
        continue
      ts = obj.get("timestamp")
      for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
          continue
        payload = block.get("input") or {}
        if block.get("name") == "Bash":
          command = payload.get("command") or ""
          if any(marker in command for marker in BASH_WRITE_MARKERS):
            yield ts, ("bash", command)
          continue
        if block.get("name") not in WRITE_TOOLS:
          continue
        file_path = payload.get("file_path") or payload.get("notebook_path")
        if file_path:
          yield ts, ("tool", file_path)


def parse_ts(ts):
  if not ts:
    return None
  try:
    return int(time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))) - time.timezone
  except ValueError:
    return None


def session_files(days):
  cutoff = time.time() - days * 86400
  for project_dir in PROJECTS_DIR.iterdir():
    if not project_dir.is_dir():
      continue
    for jsonl in project_dir.glob("*.jsonl"):
      if jsonl.stat().st_mtime >= cutoff:
        yield jsonl.stem, project_dir.name, jsonl
    for session_dir in project_dir.iterdir():
      if not session_dir.is_dir():
        continue
      for sub in session_dir.rglob("*.jsonl"):
        if sub.stat().st_mtime >= cutoff:
          yield session_dir.name, project_dir.name, sub


def session_last_active(session_id):
  newest = 0
  for project_dir in PROJECTS_DIR.iterdir():
    main = project_dir / f"{session_id}.jsonl"
    if main.exists():
      newest = max(newest, main.stat().st_mtime)
    sub_dir = project_dir / session_id
    if sub_dir.is_dir():
      for sub in sub_dir.rglob("*.jsonl"):
        newest = max(newest, sub.stat().st_mtime)
  return int(newest) if newest else None


def collect_writers(targets, days):
  wanted = {str(p): p for p in targets}
  writers = {str(p): {} for p in targets}
  needle_root = os.path.commonpath([str(p) for p in targets]) if len(targets) > 1 else str(next(iter(targets)))
  for session_id, project_name, jsonl in session_files(days):
    try:
      raw = jsonl.read_bytes()
    except OSError:
      continue
    if needle_root.encode() not in raw:
      continue
    for ts, (kind, value) in iter_events(jsonl):
      hits = []
      if kind == "tool":
        resolved = str(Path(value).expanduser().resolve())
        if resolved in wanted:
          hits.append((resolved, "tool"))
      else:
        # 絕對路徑直接比；`cd <dir> && … <相對路徑>` 的寫法把每個 cd 目標都當基準比一次
        cd_dirs = [Path(m.group(1).strip("'\"")).expanduser() for m in CD_TOKEN.finditer(value)]
        targets = bash_write_targets(value)
        for key in wanted:
          forms = {key, key.replace(str(Path.home()), "~")}
          for base in cd_dirs:
            try:
              forms.add(str(Path(key).relative_to(base.resolve())))
            except (ValueError, OSError):
              continue
          home = str(Path.home())
          if any(t in forms or (t.startswith("~/") and home + t[1:] in forms) for t in targets):
            hits.append((key, "bash"))
      epoch = parse_ts(ts)
      for key, how in hits:
        slot = writers[key].setdefault(session_id, {"session": session_id, "cwd_dir": project_name, "last_write": None, "writes": 0, "bash_only": True})
        slot["writes"] += 1
        if how == "tool":
          slot["bash_only"] = False
        if epoch and (slot["last_write"] is None or epoch > slot["last_write"]):
          slot["last_write"] = epoch
  return writers


def codex_touched(targets, days):
  if not CODEX_SESSIONS.exists():
    return set()
  cutoff = time.time() - days * 86400
  touched = set()
  names = {str(p).encode(): str(p) for p in targets}
  for rollout in CODEX_SESSIONS.rglob("rollout-*.jsonl"):
    try:
      if rollout.stat().st_mtime < cutoff:
        continue
      raw = rollout.read_bytes()
    except OSError:
      continue
    for needle, path in names.items():
      if needle in raw:
        touched.add(path)
  return touched


def iso(epoch):
  return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch)) if epoch else None


def self_session_id(explicit):
  return explicit or os.environ.get("CLAUDE_CODE_SESSION_ID")


def self_touched_repos(session_id, days):
  repos = set()
  for sid, _project, jsonl in session_files(days):
    if sid != session_id:
      continue
    for _ts, (kind, value) in iter_events(jsonl):
      # Bash 事件只在 iter_events 已確認含寫入標記時才會出現；路徑從指令字面抓，
      # 用相對路徑加 cd 的寫法會漏，那是已知邊界。
      candidates = [Path(value).expanduser()] if kind == "tool" else list(bash_path_tokens(value))
      for candidate in candidates:
        if not candidate.exists():
          candidate = candidate.parent
        # session log 目錄自己是巢狀 repo，但它從來不是收尾對象；查紀錄的 grep 會一直提到它
        if candidate.exists() and candidate.resolve().is_relative_to(PROJECTS_DIR.resolve()):
          continue
        top = repo_toplevel(candidate) if candidate.exists() else None
        if top:
          repos.add(str(top))
  for shared in SHARED_REPOS:
    if shared.is_dir():
      top = repo_toplevel(shared)
      if top:
        repos.add(str(top))
  return sorted(repos)


def build_report(repo, days, session_id):
  dirty = dirty_paths(repo)
  targets = [p for _code, p in dirty]
  if not targets:
    return {"repo": str(repo), "dirty": [], "staged_foreign": [], "self_session": session_id}
  writers = collect_writers(targets, days)
  codex_hits = codex_touched(targets, days)
  staged = set(str(p) for p in staged_paths(repo))
  unstaged = set(str(p) for p in unstaged_paths(repo))
  rows = []
  for code, path in dirty:
    key = str(path)
    candidates = sorted(writers[key].values(), key=lambda c: c["last_write"] or 0, reverse=True)
    commit_ts = last_commit_ts(repo, path)
    candidates = [c for c in candidates if commit_ts is None or (c["last_write"] or 0) > commit_ts]
    for candidate in candidates:
      candidate["session_last_active"] = iso(session_last_active(candidate["session"]))
      candidate["last_write"] = iso(candidate["last_write"])
    self_candidate = next((c for c in candidates if c["session"] == session_id), None) if session_id else None
    others = [c for c in candidates if c["session"] != session_id]
    self_owned = bool(
      self_candidate
      and not self_candidate["bash_only"]
      and not others
      and key not in codex_hits
    )
    self_bash_only = bool(self_candidate and self_candidate["bash_only"] and not others and key not in codex_hits)
    rel = os.path.relpath(key, repo)
    rows.append({
      "path": rel,
      "status": code,
      "staged": key in staged,
      "staged_differs": key in staged and key in unstaged,
      "shared": is_shared(repo, rel),
      "vendor_managed": is_vendor_managed(rel),
      "last_commit": iso(commit_ts),
      "candidates": candidates,
      "codex_touched": key in codex_hits,
      "co_written": len(candidates) > 1 or (bool(candidates) and key in codex_hits),
      "self_owned": self_owned,
      "self_bash_only": self_bash_only,
      "uncovered_sources": ["hook/script writes", "bash-edited files"] + ([] if CODEX_SESSIONS.exists() else ["codex sessions"]),
    })
  return {
    "repo": str(repo),
    "self_session": session_id,
    "dirty": rows,
    "staged_foreign": [r["path"] for r in rows if r["staged"] and not r["self_owned"]],
  }


def print_table(report):
  print(f"repo: {report['repo']}")
  print(f"self session: {report['self_session'] or '(none)'}")
  if not report["dirty"]:
    print("dirty: 0")
    return
  print(f"{'path':60} {'st':3} {'self':5} {'co':3} {'codex':5} {'shared':6} {'writers (session · last write · session last active · via)'}")
  for row in report["dirty"]:
    writers = "; ".join(
      f"{c['session'][:8]} · {c['last_write']} · active {c['session_last_active']} · {'bash' if c['bash_only'] else 'tool'}" for c in row["candidates"]
    ) or "(no CC writer found)"
    self_flag = 'yes' if row['self_owned'] else ('bash' if row['self_bash_only'] else 'no')
    shared_flag = 'vendor' if row['vendor_managed'] else ('hold' if row['staged_differs'] else ('yes' if row['shared'] else 'no'))
    print(f"{row['path'][:60]:60} {row['status']:3} {self_flag:5} {'yes' if row['co_written'] else 'no':3} {'yes' if row['codex_touched'] else 'no':5} {shared_flag:6} {writers}")
  if report["staged_foreign"]:
    print("staged but not self-owned: " + ", ".join(report["staged_foreign"]))


def main():
  parser = argparse.ArgumentParser(description="Map dirty files in a git repo to the Claude Code sessions that wrote them.")
  parser.add_argument("--repo", help="repo path (default: cwd)")
  parser.add_argument("--session", help="session id to treat as self (default: $CLAUDE_CODE_SESSION_ID)")
  parser.add_argument("--days", type=int, default=3, help="how many days of session logs to scan")
  parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
  parser.add_argument("--self-repos", action="store_true", help="list every git repo the self session has edited (Edit/Write or Bash with write markers) plus the fixed shared repos, then exit")
  args = parser.parse_args()
  session_id = self_session_id(args.session)
  if args.self_repos:
    if not session_id:
      print("no session id", file=sys.stderr)
      return 2
    for repo in self_touched_repos(session_id, args.days):
      print(repo)
    return 0
  repo = repo_toplevel(Path(args.repo or os.getcwd()).resolve())
  if not repo:
    print("not a git repo", file=sys.stderr)
    return 2
  report = build_report(repo, args.days, session_id)
  if args.json:
    print(json.dumps(report, ensure_ascii=False, indent=2))
  else:
    print_table(report)
  return 0


if __name__ == "__main__":
  sys.exit(main())
