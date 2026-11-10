#!/usr/bin/env python3
# 防漂移型 PreToolUse gate（code-search-root-gate）：
# Threat model：
# - 對誰有效：防誠實但健忘的模型在 Bash 執行搜尋時違反 `code-search.md`：(1) 對 `~`、`$HOME`、`/Users/<user>`
#   或 `~/.claude` 等直接包含 `projects/`（兩萬餘份歷史 `.jsonl`）的根目錄執行無深度限制的遞迴搜尋
#   （`grep -r/-R`、`rg`、`find`、`fd`）卻未排除 `projects`；(2) 執行遞迴 `grep -r/-R` 卻未加 `command grep`
#   或 `/usr/bin/grep`（避開 CC 的 ugrep `--ignore-files` shim）。
# - 明文不保證：
#   1. 字串比對型 gate 不承諾完整 shell 語意，只認常見搜尋命令結構；對 `~/Desktop/projects` 根目錄不要求
#      `--exclude-dir=projects`（避免根目錄同名自排導致空結果），對帶 `-maxdepth 1..2` 的淺層查詢與單一檔案
#      `grep`（無 `-r/-R`）亦放行。
#   2. 字串比對型 gate 也會攔到非單引號 heredoc 內談論該命令的文字（替代路徑：改用 Write/Edit 落檔或 `<<'EOF'` 單引號 heredoc）。
# Surface 四分表：
# - Locked: ~/.claude/hooks/code-search-root-gate.py 與 ~/.claude/hooks/code-search-root-gate.test.py
# - Editable: 待檢 Bash `tool_input.command`
# - Append-only: ~/.claude/logs/code-search-root-gate-audit.jsonl
# - Human-controlled: ~/.claude/settings.json hooks 註冊
# 自身生命週期三路徑：
# - bootstrap: 掛上 settings.json 前先建立本檔與測試檔並跑通契約測試
# - update: 直接以 Edit/Write 修改本檔與跑測試（執行測試命令本身不含無排除大目錄搜尋）
# - recovery: 設環境變數 CODE_SEARCH_GATE_DISABLE=1 或從 ~/.claude/settings.json 移除本 hook
# 本檔在契約測試底下：python3 ~/.claude/hooks/code-search-root-gate.test.py
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import time

LOG_LIMIT = 512 * 1024
SAFE_QUOTED_HEREDOC = re.compile(
  r'^(?P<prefix>\s*[^<#\r\n]*\S)\s*(?<!\\)<<(?P<strip_tabs>-)?\s*'
  r'(?P<quote>[\'\"])(?P<delimiter>[^\'\"\r\n]+)(?P=quote)\s*$'
)
PYTHON_INLINE_RE = re.compile(r'^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:/[^\s]*/)?python(?:3(?:\.\d+)?)?\b')
GIANT_ROOT_RE = re.compile(
  r'^(?:/|~|\$HOME|\$\{HOME\}|/Users/[^/\s]+|/home/[^/\s]+)(?:/\.claude(?:/projects)?)?/?$'
)
SEARCH_TOOL_RE = re.compile(
  r'^(?:(?P<prefix>command)\s+)?(?P<bin>(?:/[^\s]*/)?(?:grep|egrep|ugrep|rg|ag|find|fd))$'
)
RECURSIVE_FLAG_RE = re.compile(r'^(?:-[A-Za-z]*[rR][A-Za-z]*|--recursive|--dereference-recursive)$')
SHALLOW_DEPTH_RE = re.compile(r'(?:^|\s)(?:-maxdepth\s+[012]\b|--max-depth(?:=|\s+)[012]\b|-d\s+[012]\b)')
PROJECTS_EXCLUDE_RE = re.compile(
  r'(?:--exclude-dir[= ][^\s]*projects|-g\s*[\'"]?!\S*projects|--glob[= ][\'"]?!\S*projects'
  r'|-prune|-not\s+-path\s+\S*projects|!\s+-path\s+\S*projects|--exclude[= ]\S*projects)'
)


def strip_safe_single_quoted_heredoc(command):
  if command.count('<<') != 1:
    return command
  lines = command.splitlines(keepends=True)
  for opener_index, line in enumerate(lines):
    match = SAFE_QUOTED_HEREDOC.match(line.rstrip('\r\n'))
    if not match:
      continue
    delimiter = match.group('delimiter')
    strip_tabs = bool(match.group('strip_tabs'))
    for terminator_index in range(opener_index + 1, len(lines)):
      candidate = lines[terminator_index].rstrip('\r\n')
      if strip_tabs:
        candidate = candidate.lstrip('\t')
      if candidate != delimiter:
        continue
      output = lines.copy()
      for body_index in range(opener_index + 1, terminator_index):
        output[body_index] = '\n' if output[body_index].endswith(('\n', '\r')) else ''
      return ''.join(output)
    return command
  return command


def append_audit(session_id, reason, detail):
  audit_path = Path(
    os.environ.get(
      'CODE_SEARCH_GATE_AUDIT',
      str(Path.home() / '.claude/logs/code-search-root-gate-audit.jsonl'),
    )
  )
  row = {
    'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'session': session_id,
    'action': 'deny',
    'reason': reason,
    'detail': detail[:80],
  }
  try:
    audit_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_info = audit_path.parent.lstat()
    if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid():
      return
    fd = os.open(
      audit_path,
      os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
      0o600,
    )
    with os.fdopen(fd, 'a', encoding='utf-8') as handle:
      info = os.fstat(handle.fileno())
      if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_size > LOG_LIMIT
      ):
        return
      handle.write(json.dumps(row, ensure_ascii=False) + '\n')
  except OSError:
    return


def inspect_command(command):
  cleaned = strip_safe_single_quoted_heredoc(command)
  if PYTHON_INLINE_RE.match(cleaned):
    return None
  for segment in re.split(r'\|\||&&|;|\n|\|(?!\|)|\$\(|`', cleaned):
    seg = segment.strip()
    if not seg or seg.startswith('#'):
      continue
    try:
      tokens = shlex.split(seg)
    except ValueError:
      tokens = [t.strip('\'"') for t in seg.split()]
    idx = 0
    while idx < len(tokens) and '=' in tokens[idx] and not tokens[idx].startswith('-'):
      idx += 1
    has_command_prefix = False
    if idx < len(tokens) and tokens[idx] == 'command':
      has_command_prefix = True
      idx += 1
    if idx >= len(tokens):
      continue
    bin_token = tokens[idx]
    base = os.path.basename(bin_token)
    if base not in ('grep', 'egrep', 'ugrep', 'rg', 'ag', 'find', 'fd'):
      continue
    rest = [t.rstrip(')\'"') for t in tokens[idx + 1 :]]
    is_recursive_grep = base in ('grep', 'egrep', 'ugrep') and any(RECURSIVE_FLAG_RE.match(t) for t in rest)
    is_tree_walker = is_recursive_grep or base in ('rg', 'ag', 'find', 'fd')
    if is_recursive_grep and base == 'grep' and not has_command_prefix and not bin_token.startswith('/'):
      return (
        'bare-recursive-grep',
        seg[:80],
        (
          '偵測到遞迴 `grep -r/-R` 未使用 `command grep`（`'
          + seg[:60]
          + '`）。在 Claude Code 的 Bash 工具中，裸 `grep` 會被替換為帶 `--ignore-files` 的 ugrep shim 而靜默漏檔；'
          '請改寫為 `command grep -r ...`（或 `/usr/bin/grep -r ...`），若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。'
        ),
      )
    if is_tree_walker and any(GIANT_ROOT_RE.match(t) for t in rest):
      if SHALLOW_DEPTH_RE.search(seg) or PROJECTS_EXCLUDE_RE.search(seg):
        continue
      return (
        'unbounded-giant-root-search',
        seg[:80],
        (
          '偵測到對 `~` 或 `~/.claude` 根目錄執行無排除條件的遞迴搜尋（`'
          + seg[:60]
          + '`）。該目錄下的 `projects/` 含兩萬餘份歷史對話 `.jsonl`，未排除會造成 120s–300s 逾時卡死；'
          '請加上 `--exclude-dir={.git,node_modules,.venv,out,.shopify,projects,cache,plugins,snapshot,jobs}`（`rg` 用 `-g \'!projects/**\'`，`find` 用 `-maxdepth 2` 或 `-name projects -prune`），'
          '或直接指定具體子目錄（如 `~/.claude/hooks`、`~/.claude/skills`），若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。'
        ),
      )
  return None


def main():
  if os.environ.get('CODE_SEARCH_GATE_DISABLE') == '1':
    return
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, OSError):
    return
  if not isinstance(payload, dict):
    return
  if payload.get('tool_name', 'Bash') != 'Bash':
    return
  tool_input = payload.get('tool_input')
  if not isinstance(tool_input, dict):
    return
  command = tool_input.get('command', '')
  if not isinstance(command, str) or not command.strip():
    return
  finding = inspect_command(command)
  if finding is None:
    return
  reason_code, detail, message = finding
  append_audit(str(payload.get('session_id', '')), reason_code, detail)
  print(
    json.dumps(
      {
        'hookSpecificOutput': {
          'hookEventName': 'PreToolUse',
          'permissionDecision': 'deny',
          'permissionDecisionReason': message,
        }
      },
      ensure_ascii=False,
    )
  )


if __name__ == '__main__':
  main()
