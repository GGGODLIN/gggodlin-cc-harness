#!/usr/bin/env python3
from datetime import datetime, timezone
import json
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
BASH_WRITE_PREFILTER = (">", "tee", "sed", "cp", "mv", "--out", "open(", ".write(", "write_text", "write_bytes")
GIT_RM_RESULT_LINE_RE = re.compile(r"^rm '(.+)'$")
GITHUB_ORIGIN_RE = re.compile(
  r"^(?:https?://github\.com/|ssh://git@github\.com/|git@github\.com:)([^/\s]+)/([^/\s]+?)(?:\.git)?/?$"
)
SHELL_LEAD_WORDS = frozenset({"do", "then", "else", "elif", "if", "while", "until", "command", "builtin", "env"})
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
PYTHON_CMD_RE = re.compile(r"^python(?:\d+(?:\.\d+)*)?$")
PYTHON_WRITE_PATTERNS = (
  re.compile(r"open\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"][wa]"),
  re.compile(r"Path\(\s*['\"]([^'\"]+)['\"]\s*\)\.(?:write_text|write_bytes|open\(\s*['\"][wa])"),
)
_GIT_UNESCAPE_MAP = {
  "a": b"\a",
  "b": b"\b",
  "t": b"\t",
  "n": b"\n",
  "v": b"\v",
  "f": b"\f",
  "r": b"\r",
  "\\": b"\\",
  '"': b'"',
}
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
PROJECTS_DIR = Path(os.environ.get("CLOSEOUT_PROJECTS_DIR", str(Path.home() / ".claude" / "projects"))).expanduser()
CODEX_SESSIONS = Path(os.environ.get("CLOSEOUT_CODEX_SESSIONS", str(Path.home() / ".codex" / "sessions"))).expanduser()


def safe_resolve(path):
  try:
    s = str(path)
    if "\x00" in s:
      return None
    return Path(s).resolve()
  except (ValueError, OSError):
    return None


def normalize_target_path(raw_path, base=None):
  raw_str = str(raw_path)
  if not raw_str or "\x00" in raw_str:
    return None
  try:
    p = Path(raw_str).expanduser()
    if not p.is_absolute():
      if base is None:
        return None
      base_str = str(base)
      if not base_str or "\x00" in base_str:
        return None
      base_p = Path(base_str).expanduser()
      if not base_p.is_absolute():
        return None
      p = base_p / p
    p = Path(os.path.normpath(str(p)))
    if p == p.parent:
      return p
    # 只解析父目錄而不解開末端 symlink，避免 /tmp -> /private/tmp 失效同時防止 repo 內檔案 symlink 逃逸或碰撞
    return p.parent.resolve() / p.name
  except (ValueError, OSError):
    return None


def encoded_needles(text):
  needles = {text.encode("utf-8")}
  for ensure_ascii in (True, False):
    needles.add(json.dumps(text, ensure_ascii=ensure_ascii)[1:-1].encode("utf-8"))
  return needles


def unescape_git_quoted_path(raw):
  if not (len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"'):
    return raw
  inner = raw[1:-1]
  buf = bytearray()
  i = 0
  n = len(inner)
  while i < n:
    ch = inner[i]
    if ch == "\\" and i + 1 < n:
      nxt = inner[i + 1]
      if nxt in _GIT_UNESCAPE_MAP:
        buf.extend(_GIT_UNESCAPE_MAP[nxt])
        i += 2
        continue
      if i + 3 < n and all(c in "01234567" for c in inner[i + 1 : i + 4]):
        buf.append(int(inner[i + 1 : i + 4], 8))
        i += 4
        continue
    buf.extend(ch.encode("utf-8"))
    i += 1
  return buf.decode("utf-8", errors="replace")


def run_git(repo, *args):
  result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
  return result.stdout if result.returncode == 0 else ""


# 含 bare、worktree 或 [include]/[includeIf]（可能從外部展開 bare/worktree）時退回 git rev-parse
_GIT_CONFIG_BARE_OR_WT_RE = re.compile(rb"(?im)^\s*(?:bare\s*=\s*(?:true|yes|on|1)|worktree\s*=|\[\s*include(?:if)?\b)")


def _fast_standard_git_root(anchor_str):
  # 標準本地 repo（.git 為實體目錄、非 symlink、具 HEAD 且非 bare／自訂 worktree）直接回傳根目錄，省去 git rev-parse 子程序
  dot_git = os.path.join(anchor_str, ".git")
  try:
    if os.path.islink(dot_git) or not os.path.isdir(dot_git):
      return None
    if not os.path.isfile(os.path.join(dot_git, "HEAD")):
      return None
    cfg_path = os.path.join(dot_git, "config")
    if os.path.isfile(cfg_path):
      with open(cfg_path, "rb") as fh:
        cfg = fh.read()
      if _GIT_CONFIG_BARE_OR_WT_RE.search(cfg):
        return None
    return Path(anchor_str)
  except OSError:
    return None


def repo_toplevel(path, _cache=None):
  try:
    s = str(path)
    if not s or "\x00" in s:
      return None
    probe = Path(s).expanduser()
    # 指向合法目錄的活 symlink（如 /tmp/link-repo -> /real/repo）應跟隨；檔案 symlink 與 broken symlink 才往上爬
    if probe.is_symlink() and probe.is_dir():
      probe = probe.resolve()
    while probe != probe.parent and (not probe.is_dir() or (probe.is_symlink() and not probe.is_dir())):
      probe = probe.parent
    if probe.is_symlink() and probe.is_dir():
      probe = probe.resolve()
    if not probe.is_dir():
      return None
  except (ValueError, OSError):
    return None
  probe_str = str(probe)
  if _cache is not None and probe_str in _cache:
    return _cache[probe_str]
  anchor_str = None
  if (
    "GIT_DIR" not in os.environ
    and "GIT_WORK_TREE" not in os.environ
    and "GIT_CEILING_DIRECTORIES" not in os.environ
  ):
    try:
      real_probe = os.path.realpath(probe_str)
    except OSError:
      real_probe = probe_str
    if "/.git/" not in (real_probe + "/") and not real_probe.endswith("/.git"):
      cur = real_probe
      while True:
        if os.path.lexists(os.path.join(cur, ".git")):
          anchor_str = cur
          break
        parent = os.path.dirname(cur)
        if parent == cur:
          if _cache is not None:
            _cache[probe_str] = None
          return None
        cur = parent
      if _cache is not None and anchor_str in _cache:
        top_path = _cache[anchor_str]
        _cache[probe_str] = top_path
        return top_path
      fast_top = _fast_standard_git_root(anchor_str)
      if fast_top is not None:
        if _cache is not None:
          _cache[probe_str] = fast_top
          _cache[anchor_str] = fast_top
        return fast_top
  top = run_git(anchor_str or probe, "rev-parse", "--show-toplevel").strip()
  if not top:
    if _cache is not None:
      _cache[probe_str] = None
      if anchor_str is not None:
        _cache[anchor_str] = None
    return None
  try:
    top_path = Path(top).resolve()
    # 多帳號 config dir（~/.claude-team-*）的 .git 是 ~/.claude/.git 的 symlink，
    # 操作一律回正本，否則同一個 repo 會被列兩次、而且替代目錄相對 HEAD 有數千個假 D
    dot_git = top_path / ".git"
    if dot_git.is_symlink():
      top_path = dot_git.resolve().parent
  except (ValueError, OSError):
    return None
  if _cache is not None:
    _cache[probe_str] = top_path
    if anchor_str is not None:
      _cache[anchor_str] = top_path
  return top_path


def repo_logical_path(repo, rel):
  return Path(os.path.normpath(str(repo / rel)))


def dirty_paths(repo):
  out = run_git(repo, "status", "--porcelain=v1", "--untracked-files=all", "-z")
  entries = [e for e in out.split("\0") if e]
  raw_items = []
  skip_next = False
  for entry in entries:
    if skip_next:
      skip_next = False
      continue
    code = entry[:2]
    rel = entry[3:]
    if "R" in code or "C" in code:
      skip_next = True
    raw_items.append((code, repo_logical_path(repo, rel)))
  staged_deleted = {p for code, p in raw_items if code.startswith("D")}
  return [(code, p) for code, p in raw_items if not (code == "??" and p in staged_deleted)]


def staged_paths(repo):
  out = run_git(repo, "diff", "--cached", "--name-only", "-z")
  return [repo_logical_path(repo, p) for p in out.split("\0") if p]


def unstaged_paths(repo):
  out = run_git(repo, "diff", "--name-only", "-z")
  return [repo_logical_path(repo, p) for p in out.split("\0") if p]


def is_shared_repo(repo):
  # 共用集合只存在於兩個固定 repo；普通專案自己的 memory/ 或 settings.json 不是使用者的共用帳本，
  # 不能因為路徑同名就被整組 checkpoint
  resolved = safe_resolve(repo)
  if resolved is None:
    return False
  for shared in SHARED_REPOS:
    try:
      if shared.exists() and resolved == shared.resolve():
        return True
    except (ValueError, OSError):
      continue
  return False


def is_shared(repo, rel):
  if not is_shared_repo(repo):
    return False
  return rel.startswith(SHARED_PREFIXES) or rel in SHARED_EXACT or rel.rsplit("/", 1)[-1] in SHARED_BASENAMES


def is_vendor_managed(rel):
  return rel.startswith(VENDOR_MANAGED_PREFIXES)


def is_scratch_path(rel):
  norm = rel.replace(os.sep, "/")
  return norm == ".scratch" or norm.startswith(".scratch/")


def repo_visibility(repo, origin_url):
  # 公開或可見性無法確認的遠端 repo 必須攔下 .scratch/，避免本機路徑與 session 紀錄外流
  override = os.environ.get("CLOSEOUT_REPO_VISIBILITY", "").strip().upper()
  if override:
    return override
  m = GITHUB_ORIGIN_RE.match(origin_url.strip())
  if not m:
    return "UNKNOWN"
  owner, name = m.group(1), m.group(2)
  env = os.environ.copy()
  try:
    if owner.lower() == "example-owner":
      tok = subprocess.run(
        ["gh", "auth", "token", "-u", "example-owner"],
        capture_output=True,
        text=True,
        timeout=3,
      )
      if tok.returncode == 0 and tok.stdout.strip():
        env["GH_TOKEN"] = tok.stdout.strip()
    res = subprocess.run(
      ["gh", "repo", "view", f"{owner}/{name}", "--json", "visibility"],
      capture_output=True,
      text=True,
      env=env,
      timeout=5,
    )
    if res.returncode != 0:
      return "UNKNOWN"
    vis = json.loads(res.stdout).get("visibility")
    return vis.strip().upper() if isinstance(vis, str) and vis.strip() else "UNKNOWN"
  except (OSError, subprocess.SubprocessError, ValueError):
    return "UNKNOWN"


def _parse_heredoc_specs(line, in_single, in_double, escaped):
  specs = []
  i = 0
  n = len(line)
  while i < n:
    ch = line[i]
    if escaped:
      escaped = False
      i += 1
      continue
    if in_single:
      if ch == "'":
        in_single = False
      i += 1
      continue
    if in_double:
      if ch == "\\":
        escaped = True
      elif ch == '"':
        in_double = False
      i += 1
      continue
    if ch == "\\":
      escaped = True
      i += 1
      continue
    if ch == "'":
      in_single = True
      i += 1
      continue
    if ch == '"':
      in_double = True
      i += 1
      continue
    if ch == "#" and (i == 0 or line[i - 1] in " \t;&|()<>"):
      break
    if ch == "<" and i + 1 < n and line[i + 1] == "<":
      if i + 2 < n and line[i + 2] == "<":
        i += 3
        continue
      j = i + 2
      strip_tabs = False
      if j < n and line[j] == "-":
        strip_tabs = True
        j += 1
      while j < n and line[j] in " \t":
        j += 1
      tag_chars = []
      while j < n and line[j] not in " \t;&|()<>#\r\n":
        c = line[j]
        if c == "'":
          j += 1
          while j < n and line[j] != "'":
            tag_chars.append(line[j])
            j += 1
          if j < n:
            j += 1
        elif c == '"':
          j += 1
          while j < n and line[j] != '"':
            if line[j] == "\\" and j + 1 < n:
              tag_chars.append(line[j + 1])
              j += 2
            else:
              tag_chars.append(line[j])
              j += 1
          if j < n:
            j += 1
        elif c == "\\" and j + 1 < n:
          tag_chars.append(line[j + 1])
          j += 2
        else:
          tag_chars.append(c)
          j += 1
      tag = "".join(tag_chars)
      if tag:
        specs.append((tag, strip_tabs))
      i = j
      continue
    i += 1
  return specs, in_single, in_double, escaped


def split_heredocs(command):
  if "<<" not in command:
    return command, []
  shell_lines = []
  heredocs = []
  queue = []
  in_single = False
  in_double = False
  escaped = False
  for line in command.splitlines():
    if queue:
      cmd_line, tag, strip_tabs, body_lines = queue[0]
      candidate = line.lstrip("\t") if strip_tabs else line
      if candidate == tag:
        heredocs.append((cmd_line, "\n".join(body_lines)))
        queue.pop(0)
      else:
        body_lines.append(line)
      continue
    shell_lines.append(line)
    specs, in_single, in_double, escaped = _parse_heredoc_specs(line, in_single, in_double, escaped)
    # 行尾反斜線只轉義換行字元，不可帶到下一行誤吃首字元
    escaped = False
    for tag, strip_tabs in specs:
      queue.append([line, tag, strip_tabs, []])
  for cmd_line, _tag, _strip_tabs, body_lines in queue:
    heredocs.append((cmd_line, "\n".join(body_lines)))
  return "\n".join(shell_lines), heredocs


_TOK_PLAIN_RE = re.compile(r"[^\\\'\" \t\r#;&|\n()<>]+")
_TOK_SQUOTE_RE = re.compile(r"[^']+")
_TOK_DQUOTE_RE = re.compile(r'[^\\"]+')
_REDIR_OPS = ("<<<", "<<-", "<<", "<&", "<>", ">>", ">&", ">|")


def tokenize_shell(command):
  tokens = []
  buf = []
  has_word = False
  had_quote = False
  in_single = False
  in_double = False
  i = 0
  n = len(command)
  plain_m = _TOK_PLAIN_RE.match
  sq_m = _TOK_SQUOTE_RE.match
  dq_m = _TOK_DQUOTE_RE.match
  startswith = command.startswith

  while i < n:
    if in_single:
      m = sq_m(command, i)
      if m is not None:
        buf.append(m.group(0))
        i = m.end()
      if i < n and command[i] == "'":
        in_single = False
        i += 1
      continue
    if in_double:
      m = dq_m(command, i)
      if m is not None:
        buf.append(m.group(0))
        i = m.end()
        if i >= n:
          break
      ch = command[i]
      if ch == "\\":
        if i + 1 < n:
          nxt = command[i + 1]
          if nxt in ('"', "\\", "$", "`"):
            buf.append(nxt)
            i += 2
            continue
          if nxt == "\n":
            i += 2
            continue
        buf.append("\\")
        i += 1
        continue
      if ch == '"':
        in_double = False
        i += 1
        continue
      buf.append(ch)
      i += 1
      continue
    m = plain_m(command, i)
    if m is not None:
      buf.append(m.group(0))
      has_word = True
      i = m.end()
      if i >= n:
        break
    ch = command[i]
    if ch in " \t\r":
      if has_word:
        tokens.append(("".join(buf), False, False))
        buf.clear()
        has_word = False
        had_quote = False
      i += 1
      continue
    if ch == "\\":
      if i + 1 < n:
        nxt = command[i + 1]
        if nxt == "\n":
          i += 2
          continue
        buf.append(nxt)
        has_word = True
        had_quote = True
        i += 2
        continue
      i += 1
      continue
    if ch == "'":
      in_single = True
      has_word = True
      had_quote = True
      i += 1
      continue
    if ch == '"':
      in_double = True
      has_word = True
      had_quote = True
      i += 1
      continue
    if ch == "#":
      if not has_word:
        nl = command.find("\n", i + 1)
        i = n if nl < 0 else nl
      else:
        buf.append("#")
        i += 1
      continue
    if ch == "&" and i + 1 < n and command[i + 1] == ">":
      if has_word:
        tokens.append(("".join(buf), False, False))
        buf.clear()
        has_word = False
        had_quote = False
      if i + 2 < n and command[i + 2] == ">":
        tokens.append(("&>>", False, True))
        i += 3
      else:
        tokens.append(("&>", False, True))
        i += 2
      continue
    if ch in ";|&\n()":
      if has_word:
        tokens.append(("".join(buf), False, False))
        buf.clear()
        has_word = False
        had_quote = False
      if ch in ";|&" and i + 1 < n and command[i + 1] == ch:
        tokens.append((ch + ch, True, False))
        i += 2
      else:
        tokens.append((ch, True, False))
        i += 1
      continue
    if ch in "<>":
      fd_prefix = ""
      if has_word and not had_quote:
        word = "".join(buf)
        if word.isascii() and word.isdigit():
          fd_prefix = word
          buf.clear()
          has_word = False
        else:
          tokens.append((word, False, False))
          buf.clear()
          has_word = False
          had_quote = False
      elif has_word:
        tokens.append(("".join(buf), False, False))
        buf.clear()
        has_word = False
        had_quote = False
      op = None
      for cand in _REDIR_OPS:
        if startswith(cand, i):
          op = cand
          break
      if op is None:
        op = ch
      tokens.append((fd_prefix + op, False, True))
      i += len(op)
      continue
    buf.append(ch)
    has_word = True
    i += 1
  if has_word:
    tokens.append(("".join(buf), False, False))
  return tokens


def iter_shell_segments(shell_cmd):
  cur = []
  for text, is_ctrl, is_redir in tokenize_shell(shell_cmd):
    if is_ctrl:
      if cur:
        yield cur, None
        cur = []
      if text in ("(", ")"):
        yield None, text
    else:
      cur.append((text, is_redir))
  if cur:
    yield cur, None


def clean_segment_tokens(seg_tokens):
  non_redir = []
  idx = 0
  while idx < len(seg_tokens):
    tok, is_redir = seg_tokens[idx]
    if is_redir:
      idx += 2
    else:
      non_redir.append(tok)
      idx += 1
  start = 0
  while start < len(non_redir) and (non_redir[start] in SHELL_LEAD_WORDS or ENV_ASSIGN_RE.match(non_redir[start])):
    start += 1
  return non_redir[start:]


def parse_cd_target(toks):
  if not toks:
    return None
  cmd_name = Path(toks[0]).name if "/" in toks[0] else toks[0]
  if cmd_name != "cd":
    return None
  i = 1
  while i < len(toks):
    t = toks[i]
    if t == "--":
      i += 1
      break
    if t in ("-L", "-P", "-e", "-@"):
      i += 1
      continue
    if t.startswith("-") and t != "-":
      return None
    break
  if i >= len(toks):
    return None
  target = toks[i]
  if not target or target == "-" or "\x00" in target:
    return None
  try:
    return Path(target).expanduser()
  except (ValueError, OSError):
    return None


def apply_cd(seg_cwd, cd_target):
  if cd_target.is_absolute():
    return cd_target
  if seg_cwd is not None:
    return seg_cwd / cd_target
  return None


def _is_python_interpreter(cmd_name):
  return bool(PYTHON_CMD_RE.match(cmd_name))


def _heredoc_is_interpreter(cmd_line):
  for seg_tokens, _scope in iter_shell_segments(cmd_line):
    if seg_tokens is None:
      continue
    toks = clean_segment_tokens(seg_tokens)
    if not toks:
      continue
    cmd_name = Path(toks[0]).name if "/" in toks[0] else toks[0]
    if _is_python_interpreter(cmd_name) or cmd_name in ("node", "nodejs"):
      return True
  return False


def _extract_python_writes(text):
  targets = []
  for pattern in PYTHON_WRITE_PATTERNS:
    for match in pattern.finditer(text):
      targets.append(match.group(1))
  return targets


def _parse_cp_mv_tokens(toks):
  cmd_name = Path(toks[0]).name if "/" in toks[0] else toks[0]
  target_dir_opt = None
  is_recursive = False
  pos = []
  after_dd = False
  j = 1
  while j < len(toks):
    t = toks[j]
    if not after_dd:
      if t == "--":
        after_dd = True
        j += 1
        continue
      if t in ("-t", "--target-directory") and j + 1 < len(toks):
        target_dir_opt = toks[j + 1]
        j += 2
        continue
      if t.startswith("--target-directory="):
        target_dir_opt = t.split("=", 1)[1]
        j += 1
        continue
      if t in ("-S", "--suffix") and j + 1 < len(toks):
        j += 2
        continue
      if t in ("--recursive", "--archive"):
        if cmd_name == "cp":
          is_recursive = True
        j += 1
        continue
      if t.startswith("-") and t != "-":
        if cmd_name == "cp" and not t.startswith("--") and any(c in t[1:] for c in ("r", "R", "a")):
          is_recursive = True
        j += 1
        continue
    pos.append(t)
    j += 1
  if target_dir_opt is not None and pos:
    return (pos, target_dir_opt, is_recursive, True)
  if len(pos) >= 2:
    return (pos[:-1], pos[-1], is_recursive, False)
  return None


def analyze_bash_command(command, initial_cwd=None):
  shell_cmd, heredocs = split_heredocs(command)
  return _analyze_bash_parsed(shell_cmd, heredocs, initial_cwd=initial_cwd)


def _analyze_bash_parsed(shell_cmd, heredocs, initial_cwd=None):
  write_targets = []
  cp_mv_ops = []
  out_ops = []
  cd_dirs = []
  seg_cwd = initial_cwd
  cwd_stack = []
  last_python_cwd = initial_cwd
  heredoc_idx = 0

  for seg_tokens, scope in iter_shell_segments(shell_cmd):
    if scope == "(":
      cwd_stack.append(seg_cwd)
      continue
    if scope == ")":
      seg_cwd = cwd_stack.pop() if cwd_stack else seg_cwd
      continue
    for idx, (tok, is_redir) in enumerate(seg_tokens):
      if is_redir and idx + 1 < len(seg_tokens):
        nxt_text, nxt_redir = seg_tokens[idx + 1]
        if nxt_redir or not nxt_text:
          continue
        op = tok.lstrip("0123456789")
        if op in ("<<", "<<-") and heredoc_idx < len(heredocs):
          hd_cmd_line, hd_body = heredocs[heredoc_idx]
          heredoc_idx += 1
          if _heredoc_is_interpreter(hd_cmd_line):
            for target in _extract_python_writes(hd_body):
              write_targets.append((target, seg_cwd))
          continue
        if nxt_text == "/dev/null":
          continue
        if op in (">", ">>", ">|", "&>", "&>>"):
          write_targets.append((nxt_text, seg_cwd))
        elif op == ">&" and nxt_text != "-" and not nxt_text.isdigit() and not nxt_text.startswith("&"):
          write_targets.append((nxt_text, seg_cwd))
    toks = clean_segment_tokens(seg_tokens)
    if not toks:
      continue
    cd_target = parse_cd_target(toks)
    if cd_target is not None:
      next_cwd = apply_cd(seg_cwd, cd_target)
      if next_cwd is not None:
        seg_cwd = next_cwd
        cd_dirs.append(next_cwd)
      elif cd_target.is_absolute():
        cd_dirs.append(cd_target)
      continue
    cmd_name = Path(toks[0]).name if "/" in toks[0] else toks[0]
    if cmd_name == "tee":
      after_dd = False
      for t in toks[1:]:
        if not after_dd:
          if t == "--":
            after_dd = True
            continue
          if t.startswith("-") and t != "-":
            continue
        if t != "-":
          write_targets.append((t, seg_cwd))
    elif cmd_name == "sed":
      has_inplace = False
      seen_script_opt = False
      pos = []
      j = 1
      while j < len(toks):
        t = toks[j]
        if t == "--":
          pos.extend(toks[j + 1:])
          break
        if t == "-i" or t.startswith("-i"):
          has_inplace = True
          if t == "-i" and j + 1 < len(toks) and toks[j + 1] == "":
            j += 2
            continue
          j += 1
          continue
        if t == "--in-place" or t.startswith("--in-place="):
          has_inplace = True
          j += 1
          continue
        if t in ("-e", "-f", "--expression", "--file") and j + 1 < len(toks):
          seen_script_opt = True
          j += 2
          continue
        if t.startswith(("-e", "-f", "--expression=", "--file=")):
          seen_script_opt = True
          j += 1
          continue
        if t.startswith("-") and t != "-":
          j += 1
          continue
        pos.append(t)
        j += 1
      if has_inplace:
        files = pos if seen_script_opt else pos[1:]
        for f in files:
          write_targets.append((f, seg_cwd))
    elif cmd_name in ("cp", "mv"):
      parsed = _parse_cp_mv_tokens(toks)
      if parsed is not None:
        sources, dest, is_recursive, is_target_dir_opt = parsed
        cp_mv_ops.append((sources, dest, seg_cwd, is_recursive, is_target_dir_opt))
        write_targets.append((dest, seg_cwd))
    j = 1
    while j < len(toks):
      t = toks[j]
      if t in ("--out", "--output") and j + 1 < len(toks):
        out_val = toks[j + 1]
        write_targets.append((out_val, seg_cwd))
        out_ops.append((out_val, seg_cwd))
        j += 2
        continue
      if t.startswith(("--out=", "--output=")):
        out_val = t.split("=", 1)[1]
        write_targets.append((out_val, seg_cwd))
        out_ops.append((out_val, seg_cwd))
        j += 1
        continue
      j += 1
    if any(_is_python_interpreter(Path(t).name if "/" in t else t) for t in toks if t and not t.startswith("-")):
      last_python_cwd = seg_cwd
      for t in toks:
        for target in _extract_python_writes(t):
          write_targets.append((target, seg_cwd))
  for cmd_line, body in heredocs[heredoc_idx:]:
    if _heredoc_is_interpreter(cmd_line):
      for target in _extract_python_writes(body):
        write_targets.append((target, last_python_cwd))
  return {
    "shell_cmd": shell_cmd,
    "write_targets": write_targets,
    "cp_mv_ops": cp_mv_ops,
    "out_ops": out_ops,
    "cd_dirs": cd_dirs,
  }


def _has_bash_prefilter_token(command):
  return (
    ">" in command
    or "tee" in command
    or "sed" in command
    or "cp" in command
    or "mv" in command
    or "--out" in command
    or "open(" in command
    or ".write(" in command
    or "write_text" in command
    or "write_bytes" in command
  )


def has_bash_write_marker(command):
  if not _has_bash_prefilter_token(command):
    return False
  shell_cmd, heredocs = split_heredocs(command)
  info = _analyze_bash_parsed(shell_cmd, heredocs)
  if info["write_targets"] or info["cp_mv_ops"] or info["out_ops"]:
    return True
  if ".write(" in shell_cmd:
    return True
  return any(_heredoc_is_interpreter(cl) and ".write(" in body for cl, body in heredocs)


def parse_cp_mv_ops(command, initial_cwd=None):
  return analyze_bash_command(command, initial_cwd=initial_cwd)["cp_mv_ops"]


def parse_git_subcmd(toks, seg_cwd):
  cmd_name = Path(toks[0]).name if "/" in toks[0] else toks[0]
  if cmd_name != "git":
    return None, [], seg_cwd, None
  eff_base = seg_cwd
  work_tree = None
  git_dir = None
  i = 1
  while i < len(toks):
    t = toks[i]
    if t == "-C" and i + 1 < len(toks):
      try:
        dp = Path(toks[i + 1]).expanduser()
        eff_base = dp if dp.is_absolute() else ((eff_base / dp) if eff_base is not None else None)
      except (ValueError, OSError):
        pass
      i += 2
    elif t.startswith("-C") and len(t) > 2:
      try:
        dp = Path(t[2:]).expanduser()
        eff_base = dp if dp.is_absolute() else ((eff_base / dp) if eff_base is not None else None)
      except (ValueError, OSError):
        pass
      i += 1
    elif t == "--work-tree" and i + 1 < len(toks):
      try:
        wt = Path(toks[i + 1]).expanduser()
        work_tree = wt if wt.is_absolute() else ((eff_base / wt) if eff_base is not None else None)
      except (ValueError, OSError):
        pass
      i += 2
    elif t.startswith("--work-tree="):
      try:
        wt = Path(t.split("=", 1)[1]).expanduser()
        work_tree = wt if wt.is_absolute() else ((eff_base / wt) if eff_base is not None else None)
      except (ValueError, OSError):
        pass
      i += 1
    elif t == "--git-dir" and i + 1 < len(toks):
      try:
        gd = Path(toks[i + 1]).expanduser()
        git_dir = gd if gd.is_absolute() else ((eff_base / gd) if eff_base is not None else None)
      except (ValueError, OSError):
        pass
      i += 2
    elif t.startswith("--git-dir="):
      try:
        gd = Path(t.split("=", 1)[1]).expanduser()
        git_dir = gd if gd.is_absolute() else ((eff_base / gd) if eff_base is not None else None)
      except (ValueError, OSError):
        pass
      i += 1
    elif t in ("-c", "--namespace", "--config-env") and i + 1 < len(toks):
      i += 2
    elif t.startswith("-"):
      i += 1
    else:
      final_base = work_tree if work_tree is not None else eff_base
      return t, toks[i + 1:], final_base, (git_dir if work_tree is None else None)
  return None, [], (work_tree if work_tree is not None else eff_base), (git_dir if work_tree is None else None)


def parse_git_rm_ops(command, initial_cwd=None):
  shell_cmd, _heredocs = split_heredocs(command)
  ops = []
  seg_cwd = initial_cwd
  cwd_stack = []
  for seg_tokens, scope in iter_shell_segments(shell_cmd):
    if scope == "(":
      cwd_stack.append(seg_cwd)
      continue
    if scope == ")":
      seg_cwd = cwd_stack.pop() if cwd_stack else seg_cwd
      continue
    toks = clean_segment_tokens(seg_tokens)
    if not toks:
      continue
    cd_target = parse_cd_target(toks)
    if cd_target is not None:
      next_cwd = apply_cd(seg_cwd, cd_target)
      if next_cwd is not None:
        seg_cwd = next_cwd
      continue
    subcmd, rest_toks, eff_base, git_dir = parse_git_subcmd(toks, seg_cwd)
    if subcmd != "rm":
      continue
    dry_run = False
    recursive = False
    quiet = False
    operands = []
    after_dd = False
    j = 0
    while j < len(rest_toks):
      t = rest_toks[j]
      if not after_dd:
        if t == "--":
          after_dd = True
          j += 1
          continue
        if t == "--dry-run":
          dry_run = True
          j += 1
          continue
        if t == "--no-dry-run":
          dry_run = False
          j += 1
          continue
        if t == "--quiet":
          quiet = True
          j += 1
          continue
        if t == "--no-quiet":
          quiet = False
          j += 1
          continue
        if t == "--recursive":
          recursive = True
          j += 1
          continue
        if t == "--pathspec-from-file" and j + 1 < len(rest_toks):
          j += 2
          continue
        if t.startswith("--"):
          j += 1
          continue
        if t.startswith("-") and t != "-":
          flags = t[1:]
          if "n" in flags:
            dry_run = True
          if "r" in flags or "R" in flags:
            recursive = True
          if "q" in flags:
            quiet = True
          j += 1
          continue
      operands.append(t)
      j += 1
    if not dry_run and operands:
      ops.append({"operands": operands, "recursive": recursive, "quiet": quiet, "base": eff_base, "git_dir": git_dir})
  return ops


def parse_git_mv_ops(command, initial_cwd=None):
  shell_cmd, _heredocs = split_heredocs(command)
  ops = []
  seg_cwd = initial_cwd
  cwd_stack = []
  for seg_tokens, scope in iter_shell_segments(shell_cmd):
    if scope == "(":
      cwd_stack.append(seg_cwd)
      continue
    if scope == ")":
      seg_cwd = cwd_stack.pop() if cwd_stack else seg_cwd
      continue
    toks = clean_segment_tokens(seg_tokens)
    if not toks:
      continue
    cd_target = parse_cd_target(toks)
    if cd_target is not None:
      next_cwd = apply_cd(seg_cwd, cd_target)
      if next_cwd is not None:
        seg_cwd = next_cwd
      continue
    subcmd, rest_toks, eff_base, git_dir = parse_git_subcmd(toks, seg_cwd)
    if subcmd != "mv":
      continue
    dry_run = False
    pos = []
    after_dd = False
    j = 0
    while j < len(rest_toks):
      t = rest_toks[j]
      if not after_dd:
        if t == "--":
          after_dd = True
          j += 1
          continue
        if t == "--dry-run":
          dry_run = True
          j += 1
          continue
        if t == "--no-dry-run":
          dry_run = False
          j += 1
          continue
        if t.startswith("--"):
          j += 1
          continue
        if t.startswith("-") and t != "-":
          if "n" in t[1:]:
            dry_run = True
          j += 1
          continue
      pos.append(t)
      j += 1
    if not dry_run and len(pos) >= 2:
      ops.append({"sources": pos[:-1], "dest": pos[-1], "base": eff_base, "git_dir": git_dir})
  return ops


def bash_path_tokens(command):
  shell_cmd, _heredocs = split_heredocs(command)
  for match in BASH_PATH_TOKEN.finditer(shell_cmd):
    tok = match.group(0)
    if "\x00" not in tok:
      try:
        yield Path(tok).expanduser()
      except (ValueError, OSError):
        continue


def bash_write_targets(command):
  return {t for t, _cwd in analyze_bash_command(command)["write_targets"]}


_GIT_PATHSPEC_MAGIC_CHARS = frozenset("*?[:")


def last_commit_ts(repo, path):
  out = run_git(repo, "log", "-1", "--format=%ct", "--", str(path)).strip()
  return int(out) if out else None


def _stream_linear_commit_ts(repo, rel_to_key):
  # 單次 git log --no-renames --name-only -z 串流回溯線性歷史；
  # 一旦遇到 merge commit（多父節點，history simplification 可能在多路徑聯集下改變剪枝結果）即中止並將剩餘路徑交給精確逐檔查詢
  found = {}
  remaining = dict(rel_to_key)
  if not remaining:
    return found, remaining, False
  cmd = [
    "git", "-C", str(repo),
    "log", "--no-renames", "--format=%x1e%ct%x1f%P", "-z", "--name-only",
    "--", *remaining.keys(),
  ]
  proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
  hit_merge = False
  stopped_early = False
  cur_ts = None
  expect_first_file = False
  buf = b""
  try:
    assert proc.stdout is not None
    while remaining and not hit_merge:
      chunk = proc.stdout.read(65536)
      if not chunk:
        break
      buf += chunk
      parts = buf.split(b"\x00")
      buf = parts.pop()
      for token in parts:
        if not token:
          continue
        if token.startswith(b"\x1e"):
          body = token[1:]
          sep = body.find(b"\x1f")
          if sep < 0:
            continue
          ts_bytes = body[:sep]
          parents_bytes = body[sep + 1:]
          if b" " in parents_bytes:
            hit_merge = True
            stopped_early = True
            break
          try:
            cur_ts = int(ts_bytes)
          except ValueError:
            cur_ts = None
          expect_first_file = True
          continue
        if expect_first_file and token.startswith(b"\n"):
          token = token[1:]
          expect_first_file = False
        else:
          expect_first_file = False
        if cur_ts is None:
          continue
        rel = token.decode("utf-8", errors="surrogateescape")
        key = remaining.pop(rel, None)
        if key is not None:
          found[key] = cur_ts
          if not remaining:
            stopped_early = True
            break
    if not stopped_early and buf and not hit_merge and remaining:
      token = buf
      if expect_first_file and token.startswith(b"\n"):
        token = token[1:]
      if cur_ts is not None and not token.startswith(b"\x1e"):
        rel = token.decode("utf-8", errors="surrogateescape")
        key = remaining.pop(rel, None)
        if key is not None:
          found[key] = cur_ts
  finally:
    if stopped_early:
      try:
        proc.terminate()
      except OSError:
        pass
    if proc.stdout is not None:
      try:
        proc.stdout.close()
      except OSError:
        pass
    proc.wait()
  failed = (not stopped_early) and proc.returncode != 0
  return found, remaining, hit_merge or failed


def batch_last_commit_ts(repo, paths):
  if not paths:
    return {}
  if len(paths) == 1:
    p = paths[0]
    return {str(p): last_commit_ts(repo, p)}
  repo_str = str(repo)
  result = {}
  fallback_paths = []
  normal_items = []
  for p in paths:
    key = str(p)
    try:
      rel = os.path.relpath(key, repo_str).replace(os.sep, "/")
    except ValueError:
      fallback_paths.append(p)
      continue
    if rel == "." or rel.startswith("../") or any(c in _GIT_PATHSPEC_MAGIC_CHARS for c in rel):
      fallback_paths.append(p)
      continue
    normal_items.append((rel, key, p))
  # 分批上限 500 避開 ARG_MAX
  chunk_size = 500
  unborn_checked = False
  is_unborn = False
  for start in range(0, len(normal_items), chunk_size):
    chunk = normal_items[start : start + chunk_size]
    rel_to_key = {rel: key for rel, key, _p in chunk}
    rel_to_path = {rel: p for rel, _key, p in chunk}
    found, remaining, needs_fallback = _stream_linear_commit_ts(repo, rel_to_key)
    result.update(found)
    if not remaining:
      continue
    if not needs_fallback:
      for key in remaining.values():
        result[key] = None
      continue
    if not unborn_checked:
      unborn_checked = True
      is_unborn = not bool(run_git(repo, "rev-parse", "--verify", "-q", "HEAD").strip())
    if is_unborn:
      for key in remaining.values():
        result[key] = None
    else:
      for rel in remaining:
        fallback_paths.append(rel_to_path[rel])
  if fallback_paths:
    workers = min(8, len(fallback_paths))
    if workers <= 1:
      for p in fallback_paths:
        result[str(p)] = last_commit_ts(repo, p)
    else:
      from concurrent.futures import ThreadPoolExecutor
      with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [(str(p), pool.submit(last_commit_ts, repo, p)) for p in fallback_paths]
        for key, fut in futs:
          result[key] = fut.result()
  return result


def extract_tool_result_text(content):
  if isinstance(content, str):
    return content
  if isinstance(content, list):
    return "\n".join(
      b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)
    )
  return ""


def _loads_json_line(raw_line):
  try:
    return json.loads(raw_line)
  except (json.JSONDecodeError, UnicodeDecodeError):
    try:
      return json.loads(raw_line.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
      return None


def _drain_pending_tool_results(raw_lines, start_idx, end_idx, pending_git_ops):
  for idx in range(start_idx, end_idx):
    if not pending_git_ops:
      return
    raw_line = raw_lines[idx]
    if b'"tool_result"' not in raw_line:
      continue
    obj = _loads_json_line(raw_line)
    if not isinstance(obj, dict):
      continue
    message = obj.get("message")
    if not isinstance(message, dict):
      continue
    content = message.get("content")
    if not isinstance(content, list):
      continue
    ts = obj.get("timestamp")
    for block in content:
      if not isinstance(block, dict) or block.get("type") != "tool_result":
        continue
      tid = block.get("tool_use_id")
      if isinstance(tid, str) and tid in pending_git_ops:
        use_ts, cmd, rm_ops, mv_ops = pending_git_ops.pop(tid)
        if not block.get("is_error"):
          text = extract_tool_result_text(block.get("content"))
          if rm_ops:
            removed = [
              unescape_git_quoted_path(m.group(1))
              for raw_ln in text.splitlines()
              for m in (GIT_RM_RESULT_LINE_RE.match(raw_ln.strip()),)
              if m
            ]
            if removed or any(op["quiet"] for op in rm_ops):
              yield (ts or use_ts), ("git_rm", (cmd, rm_ops, removed))
          if mv_ops:
            yield (ts or use_ts), ("git_mv", (cmd, mv_ops))


def _classify_bash_command(command):
  is_write = _has_bash_prefilter_token(command) and has_bash_write_marker(command)
  rm_ops = []
  mv_ops = []
  if "git" in command and ("rm" in command or "mv" in command):
    shell_cmd, _heredocs = split_heredocs(command)
    if "git" in shell_cmd and ("rm" in shell_cmd or "mv" in shell_cmd):
      rm_ops = parse_git_rm_ops(command)
      mv_ops = parse_git_mv_ops(command)
  return is_write, rm_ops, mv_ops


def iter_events(jsonl_path, raw_bytes=None, _bash_cache=None, _noop_tails=None):
  pending_git_ops = {}
  if raw_bytes is None:
    try:
      with open(jsonl_path, "rb") as handle:
        raw_bytes = handle.read()
    except OSError:
      return
  if b'"tool_use"' not in raw_bytes:
    return
  raw_lines = raw_bytes.splitlines()
  noop_tails = _noop_tails if _noop_tails is not None else set()
  tu_entries = []
  for idx, ln in enumerate(raw_lines):
    p1 = ln.find(b'"tool_use"')
    if p1 < 0:
      continue
    ni = ln.find(b'"name"', p1 + 10)
    if ni > 0 and ln.find(b'"tool_use"', p1 + 10) < 0:
      tail = ln[ni:]
      if tail in noop_tails:
        prefix = ln[:ni]
        # 嚴格保證 prefix 不含任何提前的 input、tool_result 或 unicode 跳脫，才可安全跳過 json.loads
        if b'"input"' not in prefix and b'"tool_result"' not in prefix and b"\\u" not in prefix:
          continue
      tu_entries.append((idx, ln, tail, ni))
    else:
      tu_entries.append((idx, ln, None, -1))
  if not tu_entries:
    return
  # 整檔 tool_use 行合併為單一 JSON 陣列交給 C 層 _json 一次解析；若含壞行則無縫退回逐行容錯解析
  try:
    objs = json.loads(b"[" + b",".join(e[1] for e in tu_entries) + b"]")
    if type(objs) is not list or len(objs) != len(tu_entries):
      objs = None
  except (json.JSONDecodeError, UnicodeDecodeError):
    objs = None
  if objs is None:
    objs = [_loads_json_line(e[1]) for e in tu_entries]

  bash_cache = _bash_cache if _bash_cache is not None else {}
  prev_idx = -1
  for (idx, ln, tail, ni), obj in zip(tu_entries, objs):
    if pending_git_ops and idx > prev_idx + 1:
      yield from _drain_pending_tool_results(raw_lines, prev_idx + 1, idx, pending_git_ops)
    prev_idx = idx
    if type(obj) is not dict:
      continue
    message = obj.get("message")
    if type(message) is not dict:
      continue
    content = message.get("content")
    if type(content) is not list:
      continue
    ts = obj.get("timestamp")
    can_mark_noop = (
      tail is not None
      and len(content) == 1
      and not pending_git_ops
      and b'"type"' not in tail
    )
    emitted = False
    for block in content:
      if type(block) is not dict:
        continue
      btype = block.get("type")
      if btype == "tool_result" and pending_git_ops:
        tid = block.get("tool_use_id")
        if type(tid) is str and tid in pending_git_ops:
          use_ts, cmd, rm_ops, mv_ops = pending_git_ops.pop(tid)
          if not block.get("is_error"):
            text = extract_tool_result_text(block.get("content"))
            if rm_ops:
              removed = [
                unescape_git_quoted_path(m.group(1))
                for raw_ln in text.splitlines()
                for m in (GIT_RM_RESULT_LINE_RE.match(raw_ln.strip()),)
                if m
              ]
              if removed or any(op["quiet"] for op in rm_ops):
                yield (ts or use_ts), ("git_rm", (cmd, rm_ops, removed))
            if mv_ops:
              yield (ts or use_ts), ("git_mv", (cmd, mv_ops))
        continue
      if btype != "tool_use":
        continue
      bname = block.get("name")
      if bname == "Bash":
        payload = block.get("input")
        if type(payload) is not dict:
          continue
        command = payload.get("command")
        if type(command) is not str or not command:
          continue
        # 純函式結果在單次掃描內 memoize，重複的唯讀 Bash 指令 O(1) 跳過
        classified = bash_cache.get(command)
        if classified is None:
          classified = _classify_bash_command(command)
          bash_cache[command] = classified
        is_write, rm_ops, mv_ops = classified
        if is_write:
          emitted = True
          yield ts, ("bash", command)
        if rm_ops or mv_ops:
          emitted = True
          tid = block.get("id")
          if type(tid) is str and tid:
            pending_git_ops[tid] = (ts, command, rm_ops, mv_ops)
        continue
      if bname not in WRITE_TOOLS:
        continue
      payload = block.get("input")
      if type(payload) is not dict:
        continue
      file_path = payload.get("file_path")
      if type(file_path) is not str or not file_path:
        file_path = payload.get("notebook_path")
      if type(file_path) is str and file_path and "\x00" not in file_path:
        emitted = True
        yield ts, ("tool", file_path)
    if can_mark_noop and not emitted:
      prefix = ln[:ni]
      if b'"input"' not in prefix and b'"tool_result"' not in prefix and b"\\u" not in prefix:
        noop_tails.add(tail)
  if pending_git_ops and prev_idx + 1 < len(raw_lines):
    yield from _drain_pending_tool_results(raw_lines, prev_idx + 1, len(raw_lines), pending_git_ops)


def parse_ts(ts):
  if not isinstance(ts, str) or not ts.strip():
    return None
  s = ts.strip()
  if s.endswith(("Z", "z")):
    s = s[:-1] + "+00:00"
  try:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
      dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())
  except (ValueError, TypeError, OverflowError):
    return None


def _safe_iterdir(directory):
  try:
    return list(directory.iterdir())
  except OSError:
    return []


def _safe_glob(directory, pattern, recursive=False):
  try:
    return list(directory.rglob(pattern) if recursive else directory.glob(pattern))
  except OSError:
    return []


def _safe_is_dir(path):
  try:
    return path.is_dir()
  except OSError:
    return False


def _safe_mtime(path):
  try:
    st = os.stat(path)
    if not stat.S_ISREG(st.st_mode):
      return None
    return st.st_mtime
  except OSError:
    return None


def _iter_jsonl_recursive(dir_path):
  # os.scandir 單趟遞迴，對齊 Path.rglob("*.jsonl")：不追蹤子目錄 symlink，但檔案 stat 追蹤 symlink
  stack = [dir_path]
  while stack:
    cur = stack.pop()
    try:
      it = os.scandir(cur)
    except OSError:
      continue
    with it:
      for entry in it:
        try:
          if entry.is_dir(follow_symlinks=False):
            stack.append(entry.path)
            continue
        except OSError:
          continue
        if not entry.name.endswith(".jsonl"):
          continue
        try:
          st = entry.stat(follow_symlinks=True)
          if stat.S_ISREG(st.st_mode):
            yield entry.path, st.st_mtime
        except OSError:
          continue


def session_files(days, only_session=None, active_out=None):
  cutoff = time.time() - days * 86400
  try:
    proj_it = os.scandir(PROJECTS_DIR)
  except OSError:
    return
  with proj_it:
    for proj_entry in proj_it:
      try:
        if not proj_entry.is_dir(follow_symlinks=True):
          continue
      except OSError:
        continue
      proj_name = proj_entry.name
      proj_path = proj_entry.path
      if only_session:
        main_path = os.path.join(proj_path, f"{only_session}.jsonl")
        mtime = _safe_mtime(main_path)
        if mtime is not None:
          if active_out is not None and mtime > active_out.get(only_session, 0):
            active_out[only_session] = mtime
          if mtime >= cutoff:
            yield only_session, proj_name, Path(main_path)
        sub_dir = os.path.join(proj_path, only_session)
        for sub_path, sm in _iter_jsonl_recursive(sub_dir):
          if active_out is not None and sm > active_out.get(only_session, 0):
            active_out[only_session] = sm
          if sm >= cutoff:
            yield only_session, proj_name, Path(sub_path)
        continue
      try:
        child_it = os.scandir(proj_path)
      except OSError:
        continue
      with child_it:
        for entry in child_it:
          try:
            is_dir = entry.is_dir(follow_symlinks=True)
          except OSError:
            continue
          if is_dir:
            sid = entry.name
            for sub_path, sm in _iter_jsonl_recursive(entry.path):
              if active_out is not None and sm > active_out.get(sid, 0):
                active_out[sid] = sm
              if sm >= cutoff:
                yield sid, proj_name, Path(sub_path)
          elif entry.name.endswith(".jsonl"):
            try:
              st = entry.stat(follow_symlinks=True)
              if not stat.S_ISREG(st.st_mode):
                continue
              mtime = st.st_mtime
            except OSError:
              continue
            ename = entry.name
            sid = ename[:-6] if len(ename) > 6 else ename
            if active_out is not None and mtime > active_out.get(sid, 0):
              active_out[sid] = mtime
            if mtime >= cutoff:
              yield sid, proj_name, Path(entry.path)


def session_last_active(session_id):
  try:
    proj_it = os.scandir(PROJECTS_DIR)
  except OSError:
    return None
  newest = 0
  main_name = f"{session_id}.jsonl"
  with proj_it:
    for proj_entry in proj_it:
      try:
        if not proj_entry.is_dir(follow_symlinks=True):
          continue
      except OSError:
        continue
      proj_path = proj_entry.path
      mtime = _safe_mtime(os.path.join(proj_path, main_name))
      if mtime is not None and mtime > newest:
        newest = mtime
      for _sub_path, sm in _iter_jsonl_recursive(os.path.join(proj_path, session_id)):
        if sm > newest:
          newest = sm
  return int(newest) if newest else None


def resolve_git_op_base(base, repo_root, repo_project_match, git_dir=None):
  if git_dir is not None:
    gd = safe_resolve(git_dir)
    if gd is None:
      return None, False
    repo_gd_out = run_git(repo_root, "rev-parse", "--absolute-git-dir").strip()
    repo_gd = safe_resolve(repo_gd_out) if repo_gd_out else safe_resolve(repo_root / ".git")
    if repo_gd is None or gd != repo_gd:
      return None, False
  if base is not None:
    if "\x00" in str(base):
      return None, False
    try:
      bp = Path(str(base)).expanduser()
      if not bp.is_absolute():
        return None, False
      rb = bp.resolve()
    except (ValueError, OSError):
      return None, False
    probe = rb
    try:
      while probe != probe.parent and (probe.is_symlink() or not probe.exists()):
        probe = probe.parent
      in_repo = not probe.is_symlink() and probe.exists() and repo_toplevel(probe) == repo_root
    except (ValueError, OSError):
      return None, False
    return rb, in_repo
  return (repo_root if repo_project_match else None), repo_project_match


def resolve_in_repo(raw_path, resolved_base, base_in_repo, repo_root):
  if not raw_path or "\x00" in str(raw_path):
    return None
  try:
    p = Path(raw_path).expanduser()
  except (ValueError, OSError):
    return None
  if p.is_absolute():
    rp = normalize_target_path(p)
  elif resolved_base is not None and base_in_repo:
    rp = normalize_target_path(p, resolved_base)
  else:
    return None
  if rp is None:
    return None
  if rp == repo_root or rp.is_relative_to(repo_root):
    return rp
  return None


def _resolve_move_dest_targets(sources, dest_raw, rp, repo_root, wanted, is_recursive=False, force_dir=False):
  exact = set()
  prefixes = []
  if rp == repo_root:
    for raw_src in sources:
      bname = Path(raw_src.rstrip("/")).name
      if bname and bname not in (".", "..") and not any(ch in bname for ch in "*?[$"):
        landed = normalize_target_path(repo_root / bname)
        if landed is not None and landed != repo_root and landed.is_relative_to(repo_root):
          exact.add(str(landed))
          prefixes.append(str(landed) + "/")
    return exact, prefixes
  if is_recursive:
    exact.add(str(rp))
    prefixes.append(str(rp) + "/")
    return exact, prefixes
  try:
    rp_is_dir = not rp.is_symlink() and rp.is_dir()
  except OSError:
    rp_is_dir = False
  if dest_raw.endswith("/") or force_dir or len(sources) > 1:
    for raw_src in sources:
      bname = Path(raw_src.rstrip("/")).name
      if bname in (".", ".."):
        continue
      if not bname or any(ch in bname for ch in "*?[$"):
        prefixes.append(str(rp) + "/")
        continue
      landed = normalize_target_path(rp / bname)
      if landed is not None and landed != repo_root and landed.is_relative_to(repo_root):
        exact.add(str(landed))
        prefixes.append(str(landed) + "/")
    return exact, prefixes
  if rp_is_dir and len(sources) == 1:
    bname = Path(sources[0].rstrip("/")).name
    if bname and bname not in (".", "..") and not any(ch in bname for ch in "*?[$"):
      landed = normalize_target_path(rp / bname)
      if landed is not None and landed != repo_root and landed.is_relative_to(repo_root):
        l_str = str(landed)
        l_pref = l_str + "/"
        try:
          landed_exists = landed.is_symlink() or landed.exists()
        except OSError:
          landed_exists = False
        if landed_exists or any(k == l_str or k.startswith(l_pref) for k in wanted):
          exact.add(l_str)
          prefixes.append(l_pref)
          return exact, prefixes
  exact.add(str(rp))
  prefixes.append(str(rp) + "/")
  return exact, prefixes


def collect_writers(targets, days, repo=None, status_by_key=None, only_session=None, active_out=None):
  wanted = {str(p): p for p in targets}
  writers = {str(p): {} for p in targets}
  repo_root = safe_resolve(repo) if repo else (repo_toplevel(targets[0]) if targets else None)
  home_str = str(Path.home())
  home_resolved_str = str(Path.home().resolve())
  encoded_repo = ("-" + re.sub(r"[^A-Za-z0-9]", "-", str(repo_root).lstrip("/"))) if repo_root else None
  needle_root = os.path.commonpath([str(p) for p in targets]) if len(targets) > 1 else str(repo_root or targets[0].parent)
  raw_needles = {needle_root}
  if repo_root:
    rr_str = str(repo_root)
    raw_needles.add(rr_str)
    if rr_str.startswith("/private/"):
      raw_needles.add(rr_str[len("/private"):])
    if rr_str.startswith(home_resolved_str + "/"):
      raw_needles.add("~" + rr_str[len(home_resolved_str):])
    if rr_str.startswith(home_str + "/"):
      raw_needles.add("~" + rr_str[len(home_str):])
  repo_needles = set()
  for s in raw_needles:
    repo_needles.update(encoded_needles(s))
  repo_needles = tuple(repo_needles)
  basenames_set = set()
  for p in targets:
    basenames_set.update(encoded_needles(p.name))
  basenames = tuple(basenames_set)
  bash_cache = {}
  noop_tails = set()
  for session_id, project_name, jsonl in session_files(days, only_session=only_session, active_out=active_out):
    try:
      with open(jsonl, "rb") as fh:
        raw = fh.read()
    except OSError:
      continue
    repo_project_match = bool(
      encoded_repo and (project_name == encoded_repo or project_name.startswith(encoded_repo + "-"))
    )
    if not repo_project_match and not any(n in raw for n in repo_needles) and not any(b in raw for b in basenames):
      continue
    for ts, (kind, value) in iter_events(jsonl, raw_bytes=raw, _bash_cache=bash_cache, _noop_tails=noop_tails):
      hits = []
      if kind == "tool":
        norm = normalize_target_path(value)
        if norm is not None:
          resolved = str(norm)
          if resolved in wanted:
            hits.append((resolved, "tool"))
      elif kind == "git_rm" and repo_root:
        _cmd, rm_ops, removed = value
        removed_set = set(removed)
        for op in rm_ops:
          resolved_base, base_in_repo = resolve_git_op_base(
            op["base"], repo_root, repo_project_match, git_dir=op.get("git_dir")
          )
          op_exact = set()
          op_prefixes = []
          for raw_arg in op["operands"]:
            is_glob_children = raw_arg.endswith("/*")
            cleaned = raw_arg[:-2] if is_glob_children else raw_arg
            if not cleaned:
              continue
            rp = resolve_in_repo(cleaned, resolved_base, base_in_repo, repo_root)
            if rp is not None and rp != repo_root:
              if not is_glob_children:
                op_exact.add(str(rp))
              if op["recursive"] or is_glob_children:
                op_prefixes.append(str(rp) + "/")
          prefix_tuple = tuple(op_prefixes)
          for key in wanted:
            rel = os.path.relpath(key, repo_root).replace(os.sep, "/")
            if not op["quiet"] and rel not in removed_set:
              continue
            if key in op_exact or (prefix_tuple and key.startswith(prefix_tuple)):
              hits.append((key, "git_rm"))
      elif kind == "git_mv" and repo_root:
        _cmd, mv_ops = value
        mv_src_exact, mv_dst_exact = set(), set()
        mv_src_prefixes, mv_dst_prefixes = [], []
        for op in mv_ops:
          resolved_base, base_in_repo = resolve_git_op_base(
            op["base"], repo_root, repo_project_match, git_dir=op.get("git_dir")
          )
          for raw_src in op["sources"]:
            src_rp = resolve_in_repo(raw_src, resolved_base, base_in_repo, repo_root)
            if src_rp is not None and src_rp != repo_root:
              mv_src_exact.add(str(src_rp))
              mv_src_prefixes.append(str(src_rp) + "/")
          dst_rp = resolve_in_repo(op["dest"], resolved_base, base_in_repo, repo_root)
          if dst_rp is not None:
            ex, prefs = _resolve_move_dest_targets(
              op["sources"], op["dest"], dst_rp, repo_root, wanted, is_recursive=False
            )
            mv_dst_exact.update(ex)
            mv_dst_prefixes.extend(prefs)
        src_prefix_tuple = tuple(mv_src_prefixes)
        dst_prefix_tuple = tuple(mv_dst_prefixes)
        for key in wanted:
          if key in mv_dst_exact or (dst_prefix_tuple and key.startswith(dst_prefix_tuple)):
            hits.append((key, "git_mv_dst"))
          elif key in mv_src_exact or (src_prefix_tuple and key.startswith(src_prefix_tuple)):
            if status_by_key is None or "D" in status_by_key.get(key, "D"):
              hits.append((key, "git_rm"))
      else:
        initial_cwd = repo_root if (repo_root and repo_project_match) else None
        info = analyze_bash_command(value, initial_cwd=initial_cwd)
        dir_exact = set()
        dir_prefixes = []
        if repo_root:
          for sources, dest, seg_cwd, is_recursive, is_target_dir_opt in info["cp_mv_ops"]:
            if "\x00" in dest:
              continue
            try:
              dest_path = Path(dest).expanduser()
            except (ValueError, OSError):
              continue
            rp = normalize_target_path(dest_path) if dest_path.is_absolute() else (
              normalize_target_path(dest_path, seg_cwd) if seg_cwd is not None else None
            )
            if rp is not None and (rp == repo_root or rp.is_relative_to(repo_root)):
              ex, prefs = _resolve_move_dest_targets(
                sources,
                dest,
                rp,
                repo_root,
                wanted,
                is_recursive=is_recursive,
                force_dir=is_target_dir_opt,
              )
              dir_exact.update(ex)
              dir_prefixes.extend(prefs)
          for out_raw, seg_cwd in info["out_ops"]:
            if "\x00" in out_raw:
              continue
            try:
              out_path = Path(out_raw).expanduser()
            except (ValueError, OSError):
              continue
            rp = normalize_target_path(out_path) if out_path.is_absolute() else (
              normalize_target_path(out_path, seg_cwd) if seg_cwd is not None else None
            )
            if rp is not None and rp != repo_root and rp.is_relative_to(repo_root):
              try:
                is_dir = not rp.is_symlink() and rp.is_dir()
              except OSError:
                is_dir = False
              if is_dir or out_raw.endswith("/"):
                dir_prefixes.append(str(rp) + "/")
        normalized_write_targets = set()
        for target_str, seg_cwd in info["write_targets"]:
          if not target_str or "\x00" in target_str:
            continue
          try:
            tp = Path(target_str).expanduser()
          except (ValueError, OSError):
            continue
          norm = normalize_target_path(tp) if tp.is_absolute() else (
            normalize_target_path(tp, seg_cwd) if seg_cwd is not None else None
          )
          if norm is not None:
            normalized_write_targets.add(str(norm))
        dir_prefix_tuple = tuple(dir_prefixes)
        if dir_prefix_tuple:
          for key in wanted:
            if key in dir_exact or key.startswith(dir_prefix_tuple) or key in normalized_write_targets:
              hits.append((key, "bash"))
        else:
          for key in dir_exact:
            if key in wanted:
              hits.append((key, "bash"))
          for key in normalized_write_targets:
            if key in wanted and key not in dir_exact:
              hits.append((key, "bash"))
      epoch = parse_ts(ts)
      for key, how in hits:
        slot = writers[key].setdefault(
          session_id,
          {
            "session": session_id,
            "cwd_dir": project_name,
            "last_write": None,
            "writes": 0,
            "bash_only": True,
            "git_rm_confirmed": False,
            "git_mv_confirmed": False,
            "last_tool_write": None,
            "last_git_rm": None,
            "last_git_mv": None,
          },
        )
        slot["writes"] += 1
        t_val = epoch or 0
        if how == "tool":
          slot["bash_only"] = False
          if slot["last_tool_write"] is None or t_val > slot["last_tool_write"]:
            slot["last_tool_write"] = t_val
        elif how == "git_rm":
          slot["git_rm_confirmed"] = True
          if slot["last_git_rm"] is None or t_val > slot["last_git_rm"]:
            slot["last_git_rm"] = t_val
        elif how == "git_mv_dst":
          slot["git_mv_confirmed"] = True
          if slot["last_git_mv"] is None or t_val > slot["last_git_mv"]:
            slot["last_git_mv"] = t_val
        if epoch and (slot["last_write"] is None or epoch > slot["last_write"]):
          slot["last_write"] = epoch
  return writers


def is_strictly_readonly_codex_rollout(raw):
  # 保守排除：只有整份 rollout 每一行 JSON 皆可解析、具備明確唯讀證據（所有 turn_context 的
  # sandbox_policy.type 均為 read-only，或全程處於 EnteredReviewMode..ExitedReviewMode 唯讀審查）、
  # 且無寫檔工具事件時，才確認為純唯讀審查並排除；其餘一律保留 codex_touched。
  try:
    text = raw.decode("utf-8")
  except UnicodeDecodeError:
    return False
  seen_turn_context = False
  seen_entered_review = False
  seen_exited_review = False
  for line in text.splitlines():
    if not line.strip():
      continue
    try:
      obj = json.loads(line)
    except json.JSONDecodeError:
      return False
    if not isinstance(obj, dict):
      return False
    kind = obj.get("type")
    payload = obj.get("payload")
    if not isinstance(payload, dict):
      continue
    if kind == "turn_context":
      seen_turn_context = True
      policy = payload.get("sandbox_policy")
      if not isinstance(policy, dict) or policy.get("type") != "read-only":
        return False
    elif kind == "response_item":
      if payload.get("name") in ("apply_patch", "write_file", "edit_file"):
        return False
    elif kind == "event_msg":
      item = payload.get("item")
      if isinstance(item, dict):
        item_type = item.get("type")
        if item_type in ("FileChange", "PatchApply"):
          return False
        if item_type == "EnteredReviewMode":
          seen_entered_review = True
        elif item_type == "ExitedReviewMode":
          seen_exited_review = True
  return seen_turn_context or (seen_entered_review and seen_exited_review)


def codex_touched(targets, days):
  try:
    if not CODEX_SESSIONS.exists():
      return set()
  except OSError:
    return set()
  cutoff = time.time() - days * 86400
  touched = set()
  names = []
  for p in targets:
    p_str = str(p)
    for needle in encoded_needles(p_str):
      names.append((needle, p_str))
  for rollout_path, sm in _iter_jsonl_recursive(str(CODEX_SESSIONS)):
    if sm < cutoff or not os.path.basename(rollout_path).startswith("rollout-"):
      continue
    try:
      with open(rollout_path, "rb") as fh:
        raw = fh.read()
    except OSError:
      continue
    matched = {path for needle, path in names if needle in raw}
    if not matched:
      continue
    if is_strictly_readonly_codex_rollout(raw):
      continue
    touched.update(matched)
  return touched


def iso(epoch):
  return time.strftime("%Y-%m-%d %H:%M", time.localtime(epoch)) if epoch else None


def self_session_id(explicit):
  return explicit or os.environ.get("CLAUDE_CODE_SESSION_ID")


def _extract_git_cmd_paths(cmd):
  shell_cmd, _heredocs = split_heredocs(cmd)
  paths = list(bash_path_tokens(shell_cmd))
  seg_cwd = None
  cwd_stack = []
  for seg_tokens, scope in iter_shell_segments(shell_cmd):
    if scope == "(":
      cwd_stack.append(seg_cwd)
      continue
    if scope == ")":
      seg_cwd = cwd_stack.pop() if cwd_stack else seg_cwd
      continue
    toks = clean_segment_tokens(seg_tokens)
    if not toks:
      continue
    cd_target = parse_cd_target(toks)
    if cd_target is not None:
      next_cwd = apply_cd(seg_cwd, cd_target)
      if next_cwd is not None:
        seg_cwd = next_cwd
        paths.append(next_cwd)
      elif cd_target.is_absolute():
        paths.append(cd_target)
      continue
    subcmd, _rest, eff_base, _git_dir = parse_git_subcmd(toks, seg_cwd)
    if subcmd and eff_base is not None:
      paths.append(eff_base)
  return paths


def self_touched_repos(session_id, days):
  repos = set()
  proj_resolved = safe_resolve(PROJECTS_DIR)
  toplevel_cache = {}
  seen_candidates = set()
  bash_cache = {}
  noop_tails = set()
  for _sid, _project, jsonl in session_files(days, only_session=session_id):
    for _ts, (kind, value) in iter_events(jsonl, _bash_cache=bash_cache, _noop_tails=noop_tails):
      if kind == "tool":
        if "\x00" in value:
          candidates = []
        else:
          try:
            candidates = [Path(value).expanduser()]
          except (ValueError, OSError):
            candidates = []
      elif kind == "git_rm":
        cmd, rm_ops, _removed = value
        candidates = _extract_git_cmd_paths(cmd)
        for op in rm_ops:
          if op["base"] is not None:
            candidates.append(op["base"])
      elif kind == "git_mv":
        cmd, mv_ops = value
        candidates = _extract_git_cmd_paths(cmd)
        for op in mv_ops:
          if op["base"] is not None:
            candidates.append(op["base"])
      else:
        info = analyze_bash_command(value)
        candidates = list(bash_path_tokens(info["shell_cmd"]))
        candidates.extend(info["cd_dirs"])
        for target_str, seg_cwd in info["write_targets"]:
          if not target_str or "\x00" in target_str:
            continue
          try:
            tp = Path(target_str).expanduser()
          except (ValueError, OSError):
            continue
          if tp.is_absolute():
            candidates.append(tp)
          elif seg_cwd is not None:
            candidates.append(seg_cwd / tp)
      for candidate in candidates:
        try:
          cand_str = str(candidate)
          if "\x00" in cand_str or cand_str in seen_candidates:
            continue
          seen_candidates.add(cand_str)
          if candidate.is_symlink() and candidate.is_dir():
            candidate = candidate.resolve()
          while candidate != candidate.parent and (not candidate.exists() or (candidate.is_symlink() and not candidate.is_dir())):
            candidate = candidate.parent
          if candidate.is_symlink() and candidate.is_dir():
            candidate = candidate.resolve()
          if not candidate.exists() or (candidate.is_symlink() and not candidate.is_dir()):
            continue
          # session log 目錄自己是巢狀 repo，但它從來不是收尾對象；查紀錄的 grep 會一直提到它
          cand_resolved = safe_resolve(candidate)
          if proj_resolved and cand_resolved and cand_resolved.is_relative_to(proj_resolved):
            continue
          top = repo_toplevel(candidate, _cache=toplevel_cache)
          if top:
            repos.add(str(top))
        except (ValueError, OSError):
          continue
  for shared in SHARED_REPOS:
    try:
      if shared.is_dir():
        top = repo_toplevel(shared, _cache=toplevel_cache)
        if top:
          repos.add(str(top))
    except (ValueError, OSError):
      continue
  return sorted(repos)


def _staged_foreign_paths(rows):
  # 共用集合白名單內且無工作樹差異、非 vendor 同步的暫存檔，由 Step 3 先收進共用 checkpoint 清空 index，不當外來暫存擋路
  return [
    r["path"] for r in rows
    if r["staged"]
    and not r["self_owned"]
    and not r["self_staged_rm"]
    and not r["self_staged_mv"]
    and not (r["shared"] and not r["staged_differs"] and not r["vendor_managed"])
  ]


def build_report(repo, days, session_id, plan_only=False):
  dirty = dirty_paths(repo)
  targets = [p for _code, p in dirty]
  if not targets:
    return {"repo": str(repo), "dirty": [], "staged_foreign": [], "self_session": session_id}
  status_by_key = {str(p): code for code, p in dirty}
  # git status --porcelain=v1 的 XY 兩欄已完整對應 diff --cached（X）與 diff（Y），省去兩次 git diff subprocess
  staged = {str(p) for code, p in dirty if code[0] not in (" ", "?")}
  unstaged = {str(p) for code, p in dirty if code[1] not in (" ", "?")}
  shared_repo_flag = is_shared_repo(repo)
  uncovered = ["hook/script writes", "bash-edited files"] + ([] if CODEX_SESSIONS.exists() else ["codex sessions"])
  commit_ts_cache = {}
  # 非共用大型髒倉在 self-closeout --plan 下若本場零寫入候選，直接短路全機 JSONL／Codex／逐檔 git log -1 掃描，避免逾時
  if plan_only and session_id and not shared_repo_flag:
    self_writers = collect_writers(targets, days, repo, status_by_key=status_by_key, only_session=session_id)
    has_post_commit_self_write = False
    for code, path in dirty:
      key = str(path)
      self_cand = self_writers[key].get(session_id)
      if not self_cand:
        continue
      cts = last_commit_ts(repo, path)
      commit_ts_cache[key] = cts
      if cts is None or (self_cand["last_write"] or 0) > cts:
        has_post_commit_self_write = True
        break
    if not has_post_commit_self_write:
      rows = []
      for code, path in dirty:
        key = str(path)
        rel = os.path.relpath(key, repo)
        rows.append({
          "path": rel,
          "status": code,
          "staged": key in staged,
          "staged_differs": key in staged and key in unstaged,
          "shared": False,
          "vendor_managed": is_vendor_managed(rel),
          "last_commit": None,
          "candidates": [],
          "codex_touched": False,
          "co_written": False,
          "self_owned": False,
          "self_bash_only": False,
          "self_staged_rm": False,
          "self_staged_mv": False,
          "uncovered_sources": list(uncovered),
        })
      return {
        "repo": str(repo),
        "self_session": session_id,
        "dirty": rows,
        "staged_foreign": _staged_foreign_paths(rows),
      }
  active_index = {}
  missing_ts_paths = [path for _code, path in dirty if str(path) not in commit_ts_cache]
  # codex 掃描與批次 git log 均為獨立 I/O／子程序，與主執行緒的 collect_writers 重疊執行以隱藏等待時間
  from concurrent.futures import ThreadPoolExecutor
  with ThreadPoolExecutor(max_workers=2) as pool:
    f_codex = pool.submit(codex_touched, targets, days)
    f_cts = pool.submit(batch_last_commit_ts, repo, missing_ts_paths) if missing_ts_paths else None
    writers = collect_writers(targets, days, repo, status_by_key=status_by_key, active_out=active_index)
    codex_hits = f_codex.result()
    if f_cts is not None:
      commit_ts_cache.update(f_cts.result())
  rows = []
  for code, path in dirty:
    key = str(path)
    candidates = sorted(writers[key].values(), key=lambda c: c["last_write"] or 0, reverse=True)
    commit_ts = commit_ts_cache[key] if key in commit_ts_cache else last_commit_ts(repo, path)
    candidates = [c for c in candidates if commit_ts is None or (c["last_write"] or 0) > commit_ts]
    for candidate in candidates:
      ltw = candidate.pop("last_tool_write", None)
      lrm = candidate.pop("last_git_rm", None)
      lmv = candidate.pop("last_git_mv", None)
      # 跨 commit 隔離：只採計晚於 commit_ts 的 Write/Edit、git rm、git mv 證據，避免舊 commit 前的 Write 把新 Bash 誤標成 self_owned
      candidate["bash_only"] = not (ltw is not None and (commit_ts is None or ltw > commit_ts))
      candidate["git_rm_confirmed"] = bool(lrm is not None and (commit_ts is None or lrm > commit_ts))
      candidate["git_mv_confirmed"] = bool(lmv is not None and (commit_ts is None or lmv > commit_ts))
      act = active_index.get(candidate["session"])
      candidate["session_last_active"] = iso(int(act) if act else None)
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
    staged_differs = key in staged and key in unstaged
    self_staged_rm = bool(
      (self_owned or self_bash_only)
      and self_candidate
      and self_candidate.get("git_rm_confirmed")
      and code.startswith("D")
      and not staged_differs
    )
    self_staged_mv = bool(
      (self_owned or self_bash_only)
      and self_candidate
      and self_candidate.get("git_mv_confirmed")
      and code[:1] in ("R", "A")
      and not staged_differs
    )
    rel = os.path.relpath(key, repo)
    shared_flag = shared_repo_flag and (
      rel.startswith(SHARED_PREFIXES) or rel in SHARED_EXACT or rel.rsplit("/", 1)[-1] in SHARED_BASENAMES
    )
    rows.append({
      "path": rel,
      "status": code,
      "staged": key in staged,
      "staged_differs": staged_differs,
      "shared": shared_flag,
      "vendor_managed": is_vendor_managed(rel),
      "last_commit": iso(commit_ts),
      "candidates": candidates,
      "codex_touched": key in codex_hits,
      "co_written": len(candidates) > 1 or (bool(candidates) and key in codex_hits),
      "self_owned": self_owned,
      "self_bash_only": self_bash_only,
      "self_staged_rm": self_staged_rm,
      "self_staged_mv": self_staged_mv,
      "uncovered_sources": list(uncovered),
    })
  return {
    "repo": str(repo),
    "self_session": session_id,
    "dirty": rows,
    "staged_foreign": _staged_foreign_paths(rows),
  }


def _utf8_prefix(text, max_bytes):
  return text.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")


def _utf8_suffix(text, max_bytes):
  return text.encode("utf-8")[-max_bytes:].decode("utf-8", errors="ignore")


def safe_plan_slug(repo, out_dir):
  # 單射編碼避免 a_b 與 a/b 碰撞；超長路徑改用頭尾截斷＋序號避開 ENAMETOOLONG 與互覆，不引入內容雜湊
  raw_slug = str(repo).strip("/").replace("%", "%25").replace("_", "%5F").replace("/", "_")
  if not raw_slug:
    raw_slug = "root"
  if len(raw_slug.encode("utf-8")) > 180:
    raw_slug = f"{_utf8_prefix(raw_slug, 80)}__{_utf8_suffix(raw_slug, 80)}"
  repo_str = str(repo)
  candidate = raw_slug
  idx = 2
  while True:
    existing = out_dir / f"{candidate}.json"
    if not existing.exists():
      return candidate
    try:
      old = json.loads(existing.read_text(encoding="utf-8"))
      if isinstance(old, dict) and old.get("repo") == repo_str:
        return candidate
    except (OSError, json.JSONDecodeError):
      pass
    candidate = f"{raw_slug}_{idx}"
    idx += 1


def build_plan(report, repo, out_dir, _git_meta=None):
  # 完整報告動輒上百 KB（大多是別的 session 的檔），讀進 context 只為了被判成「未收」；
  # 分欄在這裡做完，context 只拿得到要動手的路徑與異常
  out_dir.mkdir(parents=True, exist_ok=True)
  slug = safe_plan_slug(repo, out_dir)
  detail = out_dir / f"{slug}.json"
  if _git_meta is not None:
    detail.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    origin_url, branch_name, has_upstream = _git_meta
  else:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
      f_origin = pool.submit(run_git, repo, "remote", "get-url", "origin")
      f_branch = pool.submit(run_git, repo, "branch", "--show-current")
      f_upstream = pool.submit(run_git, repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
      detail.write_text(json.dumps(report, ensure_ascii=False, indent=2))
      origin_url = f_origin.result().strip()
      branch_name = f_branch.result().strip() or None
      has_upstream = bool(f_upstream.result().strip())
  has_origin = bool(origin_url)
  has_scratch_candidates = any(
    not r["vendor_managed"] and not r["staged_differs"] and is_scratch_path(r["path"])
    for r in report["dirty"]
  )
  hold_scratch = (
    has_origin
    and not is_shared_repo(repo)
    and has_scratch_candidates
    and repo_visibility(repo, origin_url) != "PRIVATE"
  )
  held, held_scratch, shared, self_owned, bash_only, staged_deletions = [], [], [], [], [], []
  unclaimed = 0
  for row in report["dirty"]:
    if row["vendor_managed"]:
      continue
    if row["staged_differs"]:
      held.append(row["path"])
    elif hold_scratch and is_scratch_path(row["path"]):
      held_scratch.append(row["path"])
    elif row["shared"]:
      shared.append(row["path"])
    elif row["self_owned"]:
      self_owned.append(row["path"])
      if row.get("self_staged_rm"):
        staged_deletions.append(row["path"])
    elif row["self_bash_only"]:
      bash_only.append(row["path"])
      if row.get("self_staged_rm"):
        staged_deletions.append(row["path"])
    else:
      unclaimed += 1
  shared_file = out_dir / f"{slug}.shared.txt"
  shared_file.write_text("".join(f"{p}\n" for p in sorted(shared)))
  return {
    "repo": report["repo"],
    "branch": branch_name,
    "has_origin": has_origin,
    "has_upstream": has_upstream,
    "detail": str(detail),
    "shared": {"count": len(shared), "pathspec_file": str(shared_file)},
    "self_owned": sorted(self_owned),
    "self_bash_only": sorted(bash_only),
    "staged_deletions": sorted(staged_deletions),
    "held_staged_differs": sorted(held),
    "held_public_scratch": sorted(held_scratch),
    "held_vendor_managed": sum(1 for r in report["dirty"] if r["vendor_managed"]),
    "staged_foreign": report["staged_foreign"],
    "unclaimed": unclaimed,
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
  import argparse
  parser = argparse.ArgumentParser(description="Map dirty files in a git repo to the Claude Code sessions that wrote them.")
  parser.add_argument("--repo", help="repo path (default: cwd)")
  parser.add_argument("--session", help="session id to treat as self (default: $CLAUDE_CODE_SESSION_ID)")
  parser.add_argument("--days", type=int, default=3, help="how many days of session logs to scan")
  parser.add_argument("--json", action="store_true", help="emit JSON instead of a table")
  parser.add_argument("--self-repos", action="store_true", help="list every git repo the self session has edited (Edit/Write or Bash with write markers) plus the fixed shared repos, then exit")
  parser.add_argument("--plan", metavar="OUT_DIR", help="apply the self-closeout column rules and print a compact summary; full report and the shared-checkpoint pathspec file go to OUT_DIR")
  args = parser.parse_args()
  session_id = self_session_id(args.session)
  if args.self_repos:
    if not session_id:
      print("no session id", file=sys.stderr)
      return 2
    for repo in self_touched_repos(session_id, args.days):
      print(repo)
    return 0
  raw_repo = args.repo or os.getcwd()
  raw_repo_path = Path(raw_repo).expanduser()
  if raw_repo_path.is_symlink() and raw_repo_path.is_dir():
    repo_input = safe_resolve(raw_repo_path) or raw_repo_path
  else:
    repo_input = normalize_target_path(raw_repo, base=os.getcwd()) or raw_repo
  repo = repo_toplevel(repo_input)
  if not repo:
    print("not a git repo", file=sys.stderr)
    return 2
  if args.plan:
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
      f_origin = pool.submit(run_git, repo, "remote", "get-url", "origin")
      f_branch = pool.submit(run_git, repo, "branch", "--show-current")
      f_upstream = pool.submit(run_git, repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
      report = build_report(repo, args.days, session_id, plan_only=True)
      git_meta = (
        f_origin.result().strip(),
        f_branch.result().strip() or None,
        bool(f_upstream.result().strip()),
      )
    print(json.dumps(build_plan(report, repo, Path(args.plan).expanduser(), _git_meta=git_meta), ensure_ascii=False, indent=2))
  else:
    report = build_report(repo, args.days, session_id, plan_only=False)
    if args.json:
      print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
      print_table(report)
  return 0


if __name__ == "__main__":
  sys.exit(main())
