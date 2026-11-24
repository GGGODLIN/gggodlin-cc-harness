#!/usr/bin/env python3
# 防漂移型 PreToolUse gate（code-search-root-gate）：
# Threat model：
# - 對誰有效：防誠實但健忘的模型在 Bash 執行搜尋時違反 `code-search.md`：
#   (1) 對 `/`、`~`、`$HOME`、`/Users/<user>`、`~/.claude` 或 `~/.claude*/projects` 等包含兩萬餘份歷史
#       `.jsonl` 的大目錄執行無深度限制的遞迴搜尋（`grep -r/-R`、`rg`、`ag`、`find`、`fd`）卻未排除
#       `projects`／`subagents` 或未加 `-maxdepth 0..2`（含透過 `sh`/`bash`/`zsh` 的 `-c`、heredoc、
#       `cd <大目錄> && ... .` 或 `for d in ~/.claude*/projects; do ... "$d"` 包裝執行）；
#   (2) 執行遞迴 `grep -r/-R` 卻未加 `command grep` 或 `/usr/bin/grep`（避開 CC 的 ugrep `--ignore-files` shim）；
#   (3) 透過內嵌 `python`/`python3`（`-c`、`<<<` 或 heredoc，含串接在 `cd ... &&` 或 `bash -c` 後）對
#       `.claude/projects` 執行跨檔目錄枚舉或對 `.claude` 根目錄執行遞迴掃描（`rglob`、`os.walk`、`fwalk`、
#       `glob(..., recursive=True)`，含 `Path.home().glob('.claude/**/...')` 這種樣式自帶根目錄的寫法）繞過索引掃歷史對話——替代路徑為 `ccsi search "<關鍵詞>" -k 5`
#       與 `ccsi events --session <id>`。
# - 明文不保證：
#   1. 字串與輕量語法比對型 gate 不承諾完整 shell／Python 語意，只認常見入口（例如不解析磁碟上獨立 `.py`
#      腳本檔內容、動態 `eval` 或跨多層變數間接展開）；對 `~/Desktop/projects` 根目錄不要求
#      `--exclude-dir=projects`（避免根目錄同名自排導致空結果），對帶 `-maxdepth 0..2` 的淺層查詢、單一檔案
#      `grep`（無 `-r/-R`），以及內嵌 Python 直接讀取已知單一 `.jsonl` 檔案路徑（無萬用字元與目錄遍歷）或
#      對 `~/.claude` 淺層 `listdir`/`iterdir`／具體子目錄（如 `~/.claude/hooks`）遞迴均放行；字面 `ast.walk(` 視為
#      語法樹走訪放行，但 `from ast import walk` 或別名匯入的 walk 認不出來源，仍當目錄遞迴擋下。
#   2. 字串比對型 gate 也會攔到非單引號 heredoc 內談論該命令的文字（替代路徑：改用 Write/Edit 落檔，或對非
#      shell／非 Python 消費端使用 `<<'EOF'` 單引號 heredoc）。
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
import ast
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import textwrap
import time

LOG_LIMIT = 512 * 1024
SHELL_BINS = frozenset({'sh', 'bash', 'zsh', 'dash', 'ksh'})
PYTHON_BIN_RE = re.compile(r'^python(?:3(?:\.\d+)?)?$')
GIANT_ROOT_RE = re.compile(
  r'^(?:/|~|\$HOME|\$\{HOME\}|/Users/[^/\s]+|/home/[^/\s]+)(?:/\.claude[^\s/]*(?:/projects)?)?/?$'
)
RECURSIVE_FLAG_RE = re.compile(r'^(?:-[A-Za-z]*[rR][A-Za-z]*|--recursive|--dereference-recursive)$')
SHALLOW_DEPTH_RE = re.compile(r'(?:^|\s)(?:-maxdepth\s+[012]\b|--max-depth(?:=|\s+)[012]\b|-d\s+[012]\b)')
PROJECTS_EXCLUDE_RE = re.compile(
  r'(?:--exclude-dir[= ][^\s]*projects|-g\s*[\'"]?!\S*projects|--glob[= ][\'"]?!\S*projects'
  r'|-prune|-not\s+-path\s+\S*projects|!\s+-path\s+\S*projects|--exclude[= ]\S*projects)'
)
ASSIGNMENT_OPS = frozenset({'=', '+=', '-=', '*=', '/=', '//=', ':='})
PY_PROJECTS_PATH_RE = re.compile(
  r'(?:^|[~/\'"\s])\.claude(?:-[A-Za-z0-9_-]+)?/projects(?=$|[/\'"\s*?\[])'
)
PY_CLAUDE_DIR_SEGMENT_RE = re.compile(r'(?:^|[~/])\.claude(?:-[A-Za-z0-9_-]+)?/?$')
# glob 樣式本身從 `.claude` 根直接接 `**`（如 `Path.home().glob('.claude/**/x.db')`）：路徑字串不是根目錄，上一條對不到。
# 只認家目錄起算（`~`、`$HOME`、`/Users/<u>`、f-string 前綴或接收者是家目錄）；專案自己的 `.claude/**` 放行。
PY_HOME_CLAUDE_RECURSIVE_RE = re.compile(r'^(?:~|\$HOME|\$\{HOME\}|/Users/[^/]+|/home/[^/]+)/\.claude[^/]*/\*\*')
PY_EXPR_CLAUDE_RECURSIVE_RE = re.compile(r'^<expr>/\.claude[^/]*/\*\*')
SHELL_CD_HOME_RE = re.compile(r'(?:^|[;&|(\n])\s*(?:cd|pushd)\s+(?:~|\$HOME|\$\{HOME\}|/Users/[^/\s]+|/home/[^/\s]+)/?\s*(?:&&|;|\n|$)')
PY_RELATIVE_CLAUDE_RECURSIVE_RE = re.compile(r'^\.claude[^/]*/\*\*')
PY_HOME_PATH_RE = re.compile(r'^(?:~|\$HOME|\$\{HOME\}|/Users/[^/]+|/home/[^/]+)/?$')
PY_SINGLE_JSONL_FILE_RE = re.compile(
  r'(?:^|[~/])\.claude(?:-[A-Za-z0-9_-]+)?/projects/[^*?\r\n\[\]]+\.jsonl$'
)
PY_WALK_FUNCS = frozenset({
  'glob',
  'iglob',
  'rglob',
  'walk',
  'fwalk',
  'listdir',
  'scandir',
  'iterdir',
})
PY_WALK_CALL_FALLBACK_RE = re.compile(
  r'\b(?:glob|iglob|rglob|walk|fwalk|listdir|scandir|iterdir)\s*\('
)
PY_SAFE_PATH_BUILDERS = frozenset({
  'Path',
  'PosixPath',
  'PurePath',
  'PurePosixPath',
  'expanduser',
  'expandvars',
  'abspath',
  'realpath',
  'normpath',
  'resolve',
  'join',
  'joinpath',
})
PY_SAFE_MODULE_NAMES = frozenset({'os', 'path', 'glob', 'pathlib', 'Path', 'PosixPath', 'PurePath'})
PATTERN_VALUE_FLAGS = frozenset({'-e', '--regexp', '-f', '--file'})
NO_PATTERN_MODE_FLAGS = frozenset({'--files'})
OTHER_VALUE_FLAGS = frozenset({
  '-A',
  '--after-context',
  '-B',
  '--before-context',
  '-C',
  '--context',
  '-m',
  '--max-count',
  '-g',
  '--glob',
  '--iglob',
  '-t',
  '--type',
  '-T',
  '--type-not',
  '--include',
  '--exclude',
  '--exclude-dir',
  '--exclude-from',
  '--max-depth',
  '-d',
  '--depth',
  '--color',
  '--colour',
  '--label',
  '-M',
  '--max-columns',
  '-j',
  '--threads',
})


def extract_search_targets(base, rest):
  if base not in ('grep', 'egrep', 'ugrep', 'rg', 'ag'):
    return rest
  has_explicit_pattern = False
  after_double_dash = False
  positionals = []
  pat_short_chars = ('e',) if base == 'ag' else ('e', 'f')
  idx = 0
  while idx < len(rest):
    token = rest[idx]
    if after_double_dash:
      positionals.append(token)
      idx += 1
      continue
    if token == '--':
      after_double_dash = True
      idx += 1
      continue
    if token in NO_PATTERN_MODE_FLAGS:
      has_explicit_pattern = True
      idx += 1
      continue
    if token in PATTERN_VALUE_FLAGS:
      has_explicit_pattern = True
      idx += 2
      continue
    if token.startswith(('--regexp=', '--file=')):
      has_explicit_pattern = True
      idx += 1
      continue
    if token in OTHER_VALUE_FLAGS:
      idx += 2
      continue
    if token.startswith('--'):
      idx += 1
      continue
    if token.startswith('-') and len(token) > 1:
      short_body = token[1:]
      matched_pos = next((i for i, ch in enumerate(short_body) if ch in pat_short_chars), None)
      if matched_pos is not None:
        has_explicit_pattern = True
        if matched_pos == len(short_body) - 1:
          idx += 2
          continue
      idx += 1
      continue
    positionals.append(token)
    idx += 1
  if has_explicit_pattern:
    return positionals
  return positionals[1:]


def unwrap_command_tokens(tokens):
  idx = 0
  has_command_prefix = False
  while idx < len(tokens):
    tok = tokens[idx]
    if '=' in tok and not tok.startswith(('=', '-')):
      idx += 1
      continue
    base_tok = os.path.basename(tok)
    if base_tok == 'env':
      idx += 1
      while idx < len(tokens):
        env_tok = tokens[idx]
        if '=' in env_tok and not env_tok.startswith(('=', '-')):
          idx += 1
          continue
        if env_tok in ('-i', '-0', '--ignore-environment', '--null'):
          idx += 1
          continue
        if env_tok in ('-u', '--unset', '-C', '--chdir') and idx + 1 < len(tokens):
          idx += 2
          continue
        break
      continue
    if base_tok in ('nohup', 'time'):
      idx += 1
      if base_tok == 'time' and idx < len(tokens) and tokens[idx] == '-p':
        idx += 1
      continue
    if tok == 'command':
      if idx + 1 < len(tokens) and tokens[idx + 1] in ('-v', '-V'):
        return len(tokens), False
      has_command_prefix = True
      idx += 1
      if idx < len(tokens) and tokens[idx] == '-p':
        idx += 1
      continue
    if base_tok == 'uv' and idx + 1 < len(tokens) and tokens[idx + 1] == 'run':
      idx += 2
      while idx < len(tokens) and tokens[idx].startswith('-'):
        uv_flag = tokens[idx]
        if uv_flag in ('--project', '--directory', '--python', '-p', '--with') and idx + 1 < len(tokens):
          idx += 2
        else:
          idx += 1
      continue
    break
  return idx, has_command_prefix


def classify_opener_binary(opener_cmd):
  try:
    tokens = shlex.split(opener_cmd)
  except ValueError:
    tokens = [t.strip('\'"') for t in opener_cmd.split()]
  idx, _ = unwrap_command_tokens(tokens)
  if idx >= len(tokens):
    return 'other'
  base = os.path.basename(tokens[idx])
  if base in SHELL_BINS:
    return 'shell'
  if PYTHON_BIN_RE.match(base):
    return 'python'
  return 'other'


def extract_shell_c_code(tokens, sh_idx):
  idx = sh_idx + 1
  while idx < len(tokens):
    tok = tokens[idx]
    if tok == '--':
      break
    if tok in ('-o', '+o', '--rcfile', '--init-file'):
      idx += 2
      continue
    if tok.startswith('--'):
      idx += 1
      continue
    if tok.startswith('-') and len(tok) > 1:
      flags = tok[1:]
      if 'c' in flags:
        c_pos = flags.index('c')
        if c_pos == len(flags) - 1:
          return tokens[idx + 1] if idx + 1 < len(tokens) else None
        return flags[c_pos + 1 :]
      idx += 2 if flags.endswith('o') else 1
      continue
    if tok.startswith('+') and len(tok) > 1:
      idx += 2 if tok.endswith('o') else 1
      continue
    break
  return None


def extract_python_c_code(tokens, py_idx):
  idx = py_idx + 1
  while idx < len(tokens):
    tok = tokens[idx]
    if tok in ('--', '-', '-m'):
      break
    if tok in ('-W', '-X'):
      idx += 2
      continue
    if tok.startswith('--'):
      idx += 1
      continue
    if tok.startswith('-') and len(tok) > 1:
      flags = tok[1:]
      if 'm' in flags and ('c' not in flags or flags.index('m') < flags.index('c')):
        break
      if 'c' in flags:
        c_pos = flags.index('c')
        if c_pos == len(flags) - 1:
          return tokens[idx + 1] if idx + 1 < len(tokens) else None
        return flags[c_pos + 1 :]
      idx += 2 if flags.endswith(('W', 'X')) else 1
      continue
    break
  return None


def extract_python_herestring(tokens, py_idx):
  for idx in range(py_idx + 1, len(tokens)):
    tok = tokens[idx]
    if tok == '<<<' and idx + 1 < len(tokens):
      return tokens[idx + 1]
    if tok.startswith('<<<') and len(tok) > 3:
      return tok[3:]
  return None


def find_heredoc_on_line(raw_line):
  line = raw_line.rstrip('\r\n')
  n = len(line)
  pos = 0
  in_sq = False
  in_dq = False
  seg_start = 0
  while pos < n:
    ch = line[pos]
    if in_sq:
      if ch == "'":
        in_sq = False
      pos += 1
      continue
    if in_dq:
      if ch == '\\' and pos + 1 < n:
        pos += 2
        continue
      if ch == '"':
        in_dq = False
      pos += 1
      continue
    if ch == '\\' and pos + 1 < n:
      pos += 2
      continue
    if ch == "'":
      in_sq = True
      pos += 1
      continue
    if ch == '"':
      in_dq = True
      pos += 1
      continue
    if ch == '#' and (pos == 0 or line[pos - 1].isspace() or line[pos - 1] in ';&|('):
      break
    if line[pos : pos + 2] in ('&&', '||', '$('):
      pos += 2
      seg_start = pos
      continue
    if ch in ';|`(':
      pos += 1
      seg_start = pos
      continue
    if (
      line[pos : pos + 2] == '<<'
      and (pos == 0 or line[pos - 1] != '<')
      and (pos + 2 >= n or line[pos + 2] != '<')
    ):
      cur = pos + 2
      strip_tabs = False
      if cur < n and line[cur] == '-':
        strip_tabs = True
        cur += 1
      while cur < n and line[cur] in ' \t':
        cur += 1
      if cur >= n:
        return None
      if line[cur] in ('\'', '"'):
        q = line[cur]
        end_q = line.find(q, cur + 1)
        if end_q == -1:
          return None
        delimiter = line[cur + 1 : end_q]
        quote_kind = 'single' if q == "'" else 'double'
        end_pos = end_q + 1
      else:
        end_pos = cur
        while end_pos < n and not line[end_pos].isspace() and line[end_pos] not in ';&|<>()':
          end_pos += 1
        raw_delim = line[cur:end_pos]
        if not raw_delim:
          return None
        quote_kind = 'single' if ('\\' in raw_delim or "'" in raw_delim or '"' in raw_delim) else 'none'
        delimiter = re.sub(r'[\\\'"]', '', raw_delim)
      if not delimiter:
        return None
      tail_end = end_pos
      t_sq = False
      t_dq = False
      while tail_end < n:
        tc = line[tail_end]
        if t_sq:
          if tc == "'":
            t_sq = False
          tail_end += 1
          continue
        if t_dq:
          if tc == '\\' and tail_end + 1 < n:
            tail_end += 2
            continue
          if tc == '"':
            t_dq = False
          tail_end += 1
          continue
        if tc == '\\' and tail_end + 1 < n:
          tail_end += 2
          continue
        if tc == "'":
          t_sq = True
          tail_end += 1
          continue
        if tc == '"':
          t_dq = True
          tail_end += 1
          continue
        if tc == '#' and (tail_end == 0 or line[tail_end - 1].isspace()):
          break
        if line[tail_end : tail_end + 2] in ('&&', '||') or tc in ';|)':
          break
        if tc == '&' and (tail_end == 0 or line[tail_end - 1] not in '<>') and (tail_end + 1 >= n or line[tail_end + 1] != '>'):
          break
        tail_end += 1
      opener_cmd = line[seg_start:pos] + ' ' + line[end_pos:tail_end]
      rewritten_line = line[:pos] + ' ' + line[end_pos:] + raw_line[n:]
      return opener_cmd, strip_tabs, quote_kind, delimiter, rewritten_line
    pos += 1
  return None


def extract_cmd_substitutions_only(text):
  subs = []
  n = len(text)
  idx = 0
  while idx < n:
    if text[idx] == '\\' and idx + 1 < n:
      idx += 2
      continue
    if text[idx : idx + 2] == '$(' and text[idx : idx + 3] != '$((':
      inner, next_idx = consume_dollar_paren(text, idx)
      subs.append(inner)
      idx = next_idx
      continue
    if text[idx] == '`':
      inner, next_idx = consume_backticks(text, idx)
      subs.append(inner)
      idx = next_idx
      continue
    idx += 1
  return subs


def extract_heredocs(command):
  if '<<' not in command:
    return command, [], []
  lines = command.splitlines(keepends=True)
  shell_lines = []
  sub_shell_bodies = []
  python_bodies = []
  idx = 0
  while idx < len(lines):
    info = find_heredoc_on_line(lines[idx])
    if info is None:
      shell_lines.append(lines[idx])
      idx += 1
      continue
    opener_cmd, strip_tabs, quote_kind, delimiter, rewritten_line = info
    term_idx = None
    for cand_idx in range(idx + 1, len(lines)):
      cand = lines[cand_idx].rstrip('\r\n')
      if strip_tabs:
        cand = cand.lstrip('\t')
      if cand == delimiter:
        term_idx = cand_idx
        break
    if term_idx is None:
      shell_lines.append(lines[idx])
      idx += 1
      continue
    shell_lines.append(rewritten_line)
    body = ''.join(lines[idx + 1 : term_idx])
    opener_kind = classify_opener_binary(opener_cmd)
    if opener_kind == 'shell':
      # 外層為 sh/bash/zsh 時 heredoc 內容會當 shell 執行，不可當純文字剝空
      sub_shell_bodies.append(body)
    elif opener_kind == 'python':
      python_bodies.append(body)
      if quote_kind != 'single':
        sub_shell_bodies.extend(extract_cmd_substitutions_only(body))
    else:
      if quote_kind in ('single', 'double'):
        if quote_kind == 'double':
          sub_shell_bodies.extend(extract_cmd_substitutions_only(body))
      else:
        shell_lines.extend(lines[idx + 1 : term_idx])
    idx = term_idx + 1
  return ''.join(shell_lines), sub_shell_bodies, python_bodies


def consume_dollar_paren(text, start):
  n = len(text)
  pos = start + 2
  depth = 1
  in_sq = False
  in_dq = False
  while pos < n:
    ch = text[pos]
    if in_sq:
      if ch == "'":
        in_sq = False
      pos += 1
      continue
    if in_dq:
      if ch == '\\' and pos + 1 < n:
        pos += 2
        continue
      if ch == '"':
        in_dq = False
      pos += 1
      continue
    if ch == '\\' and pos + 1 < n:
      pos += 2
      continue
    if ch == "'":
      in_sq = True
      pos += 1
      continue
    if ch == '"':
      in_dq = True
      pos += 1
      continue
    if ch == '(':
      depth += 1
    elif ch == ')':
      depth -= 1
      if depth == 0:
        return text[start + 2 : pos], pos + 1
    pos += 1
  return text[start + 2 :], n


def consume_backticks(text, start):
  n = len(text)
  pos = start + 1
  chars = []
  while pos < n:
    ch = text[pos]
    if ch == '\\' and pos + 1 < n and text[pos + 1] in ('`', '$', '\\'):
      chars.append(text[pos + 1])
      pos += 2
      continue
    if ch == '`':
      return ''.join(chars), pos + 1
    chars.append(ch)
    pos += 1
  return ''.join(chars), n


def split_shell_segments(text):
  segments = []
  cmd_subs = []
  buf = []
  n = len(text)
  pos = 0
  in_sq = False
  in_dq = False

  def flush():
    seg = ''.join(buf).strip()
    buf.clear()
    if seg:
      segments.append(seg)

  while pos < n:
    ch = text[pos]
    if in_sq:
      buf.append(ch)
      if ch == "'":
        in_sq = False
      pos += 1
      continue
    if in_dq:
      if ch == '\\' and pos + 1 < n:
        buf.append(ch)
        buf.append(text[pos + 1])
        pos += 2
        continue
      if text[pos : pos + 2] == '$(' and text[pos : pos + 3] != '$((':
        inner, pos = consume_dollar_paren(text, pos)
        cmd_subs.append(inner)
        continue
      if ch == '`':
        inner, pos = consume_backticks(text, pos)
        cmd_subs.append(inner)
        continue
      buf.append(ch)
      if ch == '"':
        in_dq = False
      pos += 1
      continue
    if ch == '\\' and pos + 1 < n:
      buf.append(ch)
      buf.append(text[pos + 1])
      pos += 2
      continue
    if ch == "'":
      in_sq = True
      buf.append(ch)
      pos += 1
      continue
    if ch == '"':
      in_dq = True
      buf.append(ch)
      pos += 1
      continue
    if ch == '#' and (not buf or buf[-1].isspace()):
      while pos < n and text[pos] != '\n':
        pos += 1
      continue
    if text[pos : pos + 2] == '$(' and text[pos : pos + 3] != '$((':
      inner, pos = consume_dollar_paren(text, pos)
      cmd_subs.append(inner)
      buf.append('""')
      continue
    if ch == '`':
      inner, pos = consume_backticks(text, pos)
      cmd_subs.append(inner)
      buf.append('""')
      continue
    if text[pos : pos + 2] in ('&&', '||', '|&'):
      flush()
      pos += 2
      continue
    if ch in ';\n|()':
      flush()
      pos += 1
      continue
    if ch == '&' and (pos == 0 or text[pos - 1] not in '<>') and (pos + 1 >= n or text[pos + 1] != '>'):
      flush()
      pos += 1
      continue
    buf.append(ch)
    pos += 1
  flush()
  return segments, cmd_subs


def _call_name(node):
  if isinstance(node.func, ast.Name):
    return node.func.id
  if isinstance(node.func, ast.Attribute):
    return node.func.attr
  return None


def _is_safe_module_expr(node):
  if isinstance(node, ast.Name):
    return node.id in PY_SAFE_MODULE_NAMES
  if isinstance(node, ast.Attribute):
    return node.attr in PY_SAFE_MODULE_NAMES and _is_safe_module_expr(node.value)
  return False


def _is_pure_literal_path(node):
  if isinstance(node, ast.Constant) and isinstance(node.value, str):
    return True
  if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.Add)):
    return _is_pure_literal_path(node.left) and _is_pure_literal_path(node.right)
  if isinstance(node, ast.Call):
    cname = _call_name(node)
    if cname not in PY_SAFE_PATH_BUILDERS or node.keywords:
      return False
    if isinstance(node.func, ast.Attribute):
      if not (_is_safe_module_expr(node.func.value) or _is_pure_literal_path(node.func.value)):
        return False
    return all(_is_pure_literal_path(arg) for arg in node.args)
  return False


def _expr_to_path_str(node, consumed):
  if isinstance(node, ast.Constant) and isinstance(node.value, str):
    consumed.add(id(node))
    return node.value
  if isinstance(node, ast.JoinedStr):
    consumed.add(id(node))
    parts = []
    for val in node.values:
      if isinstance(val, ast.Constant) and isinstance(val.value, str):
        consumed.add(id(val))
        parts.append(val.value)
      else:
        parts.append('<expr>')
    return ''.join(parts)
  if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
    left = _expr_to_path_str(node.left, consumed)
    right = _expr_to_path_str(node.right, consumed)
    if left is not None or right is not None:
      consumed.add(id(node))
      return (left or '<expr>').rstrip('/') + '/' + (right or '<expr>').lstrip('/')
    return None
  if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
    left = _expr_to_path_str(node.left, consumed)
    right = _expr_to_path_str(node.right, consumed)
    if left is not None or right is not None:
      consumed.add(id(node))
      return (left or '<expr>') + (right or '<expr>')
    return None
  if isinstance(node, ast.Call):
    cname = _call_name(node)
    if cname in ('expanduser', 'expandvars', 'abspath', 'realpath', 'normpath', 'resolve'):
      if isinstance(node.func, ast.Attribute) and not node.args:
        inner = _expr_to_path_str(node.func.value, consumed)
        if inner is not None:
          consumed.add(id(node))
        return inner
      if node.args:
        inner = _expr_to_path_str(node.args[0], consumed)
        if inner is not None:
          consumed.add(id(node))
        return inner
    if cname in ('Path', 'PosixPath', 'PurePath', 'PurePosixPath', 'join') and node.args:
      raw_parts = [_expr_to_path_str(arg, consumed) for arg in node.args]
      if any(p is not None for p in raw_parts):
        consumed.add(id(node))
        cleaned_parts = [(p or '<expr>').strip('/') if idx > 0 else (p or '<expr>').rstrip('/') for idx, p in enumerate(raw_parts)]
        return '/'.join(cleaned_parts)
    if cname == 'joinpath' and isinstance(node.func, ast.Attribute):
      recv = _expr_to_path_str(node.func.value, consumed)
      raw_parts = [_expr_to_path_str(arg, consumed) for arg in node.args]
      if recv is not None or any(p is not None for p in raw_parts):
        consumed.add(id(node))
        all_parts = [recv or '<expr>'] + [p or '<expr>' for p in raw_parts]
        cleaned_parts = [p.strip('/') if idx > 0 else p.rstrip('/') for idx, p in enumerate(all_parts)]
        return '/'.join(cleaned_parts)
  return None


def _collect_python_path_strings(tree):
  consumed = set()
  results = []

  def visit(node):
    if id(node) not in consumed:
      path_str = _expr_to_path_str(node, consumed)
      if path_str is not None:
        results.append(path_str)
    for child in ast.iter_child_nodes(node):
      if id(child) not in consumed:
        visit(child)

  visit(tree)
  return results


def _walk_call_can_touch_projects(call_node):
  for sub in ast.walk(call_node):
    if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and '.claude' in sub.value:
      return True
  for kw in call_node.keywords:
    if kw.arg == 'root_dir' and not _is_pure_literal_path(kw.value):
      return True
  if isinstance(call_node.func, ast.Attribute) and not _is_safe_module_expr(call_node.func.value):
    return not _is_pure_literal_path(call_node.func.value)
  if not call_node.args:
    return True
  return not _is_pure_literal_path(call_node.args[0])


def _format_python_projects_deny(snippet):
  compact = ' '.join(snippet.split())
  return (
    'inline-python-projects-scan',
    compact[:80],
    (
      '偵測到內嵌 Python 對 `~/.claude/projects` 執行跨檔 `glob`/`rglob`/`os.walk`/`listdir` 掃描。'
      '該目錄含兩萬餘份歷史對話與 `subagents/` `.jsonl`，全量枚舉會繞過索引並造成逾時；'
      '查對話歷史請改用 `ccsi search "<關鍵詞>" -k 5` 或 `ccsi events --session <id>`，'
      '已知單一對話檔路徑可直接讀取該 `.jsonl` 單檔，若只是寫文件或測試資料請改用 Write/Edit 落檔。觸發片段：`'
      + compact[:60]
      + '`'
    ),
  )


def _is_ast_module_walk(call_node):
  # `ast.walk(tree)` 走的是語法樹、不碰檔案系統；只看函式名會把它當目錄遞迴（審計 681／682 誤擋）。
  # 只認字面 `ast.` 前綴：`from ast import walk` 或別名匯入的 walk 認不出來源，照舊當目錄遞迴擋下。
  func = call_node.func
  return (
    isinstance(func, ast.Attribute)
    and func.attr == 'walk'
    and isinstance(func.value, ast.Name)
    and func.value.id == 'ast'
  )


def _is_recursive_walk_call(call_node):
  cname = _call_name(call_node)
  if cname in ('rglob', 'walk', 'fwalk'):
    return True
  if cname in ('glob', 'iglob'):
    for kw in call_node.keywords:
      if kw.arg == 'recursive' and isinstance(kw.value, ast.Constant) and kw.value.value is True:
        return True
    for arg in call_node.args:
      if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and '**' in arg.value:
        return True
  return False


def _is_home_expr(node):
  if isinstance(node, ast.Call) and _call_name(node) == 'home' and not node.args:
    return True
  path_str = _expr_to_path_str(node, set()) if node is not None else None
  return bool(path_str and PY_HOME_PATH_RE.match(path_str))


def _home_names(tree):
  # `home = os.path.expanduser('~')`／`home = Path.home()` 這類賦值：f-string 或 join 以它開頭時才算家目錄，`{repo}` 不算。
  names = set()
  for node in ast.walk(tree):
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and _is_home_expr(node.value):
      names.add(node.targets[0].id)
  return names


def _leading_expr_is_home(node, home_names):
  if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.FormattedValue):
    lead = node.values[0].value
  elif isinstance(node, ast.Call) and _call_name(node) == 'join' and node.args:
    lead = node.args[0]
  else:
    return False
  return (isinstance(lead, ast.Name) and lead.id in home_names) or _is_home_expr(lead)


def _is_cwd_relative(node):
  # 沒寫起點（`Path('.')`、`Path()`、`Path.cwd()`、標準庫 glob 沒給 root_dir）就跟著 shell 當下目錄走。
  if node is None:
    return True
  if isinstance(node, ast.Call) and _call_name(node) in ('Path', 'PosixPath') and not node.args:
    return True
  if isinstance(node, ast.Call) and _call_name(node) == 'cwd':
    return True
  path_str = _expr_to_path_str(node, set())
  return path_str in ('.', './')


def _home_claude_recursive_glob(call, home_names=frozenset(), cwd_home=False):
  # 只看「樣式自帶 .claude 根再接 **」這一種形狀；變數間接傳入樣式屬檔頭明文不保證。
  cname = _call_name(call)
  if cname not in ('glob', 'iglob', 'rglob'):
    return False
  receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
  is_module_glob = receiver is None or (isinstance(receiver, ast.Name) and receiver.id == 'glob')
  keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}
  pattern_node = call.args[0] if call.args else keywords.get('pattern') or keywords.get('pathname')
  pattern = _expr_to_path_str(pattern_node, set()) if pattern_node is not None else None
  if not pattern:
    return False
  if is_module_glob:
    # 標準庫 glob 沒開 recursive 時 `**` 只等於 `*`，不會往下鑽。
    rec = keywords.get('recursive')
    if not (isinstance(rec, ast.Constant) and rec.value is True):
      return False
    base = keywords.get('root_dir')
  else:
    base = receiver
  if PY_HOME_CLAUDE_RECURSIVE_RE.match(pattern):
    return True
  if PY_EXPR_CLAUDE_RECURSIVE_RE.match(pattern):
    return _leading_expr_is_home(pattern_node, home_names)
  if not PY_RELATIVE_CLAUDE_RECURSIVE_RE.match(pattern):
    return False
  return (base is not None and _is_home_expr(base)) or (cwd_home and _is_cwd_relative(base))


def inspect_python_code(py_source, cwd_home=False):
  if '.claude' not in py_source:
    return None
  try:
    tree = ast.parse(textwrap.dedent(py_source))
  except (SyntaxError, ValueError, RecursionError):
    non_comment = '\n'.join(
      line for line in py_source.splitlines() if not line.lstrip().startswith('#')
    )
    if not PY_WALK_CALL_FALLBACK_RE.search(non_comment):
      return None
    matches = [m.group(0) for m in PY_PROJECTS_PATH_RE.finditer(non_comment)]
    if matches and any(not PY_SINGLE_JSONL_FILE_RE.search(m) for m in matches):
      return _format_python_projects_deny(non_comment)
    return None

  walk_calls = [
    node
    for node in ast.walk(tree)
    if isinstance(node, ast.Call) and _call_name(node) in PY_WALK_FUNCS and not _is_ast_module_walk(node)
  ]
  if not walk_calls:
    return None

  path_strings = _collect_python_path_strings(tree)
  has_claude_root = any(PY_CLAUDE_DIR_SEGMENT_RE.search(s) for s in path_strings)
  if has_claude_root and any(_is_recursive_walk_call(c) and _walk_call_can_touch_projects(c) for c in walk_calls):
    return _format_python_projects_deny(py_source)
  home_names = _home_names(tree)
  if any(_home_claude_recursive_glob(c, home_names, cwd_home) for c in walk_calls):
    return _format_python_projects_deny(py_source)

  projects_refs = [s for s in path_strings if PY_PROJECTS_PATH_RE.search(s)]
  has_claude_root_glob_projects = has_claude_root and any(
    _call_name(c) in ('glob', 'iglob', 'rglob')
    and c.args
    and isinstance(c.args[0], ast.Constant)
    and isinstance(c.args[0].value, str)
    and (
      c.args[0].value == 'projects'
      or c.args[0].value.startswith(('projects/', '**/projects/'))
    )
    for c in walk_calls
  )
  if not projects_refs and not has_claude_root_glob_projects:
    return None

  has_parent_climb = any(
    (isinstance(n, ast.Attribute) and n.attr in ('parent', 'parents'))
    or (isinstance(n, ast.Call) and _call_name(n) == 'dirname')
    for n in ast.walk(tree)
  )
  has_bulk_projects_target = (
    has_claude_root_glob_projects
    or has_parent_climb
    or any(not PY_SINGLE_JSONL_FILE_RE.search(ref.strip()) for ref in projects_refs)
  )
  if not has_bulk_projects_target:
    return None

  if any(_walk_call_can_touch_projects(call) for call in walk_calls):
    return _format_python_projects_deny(py_source)
  return None


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


def _cd_is_home(dest):
  return bool(dest) and bool(PY_HOME_PATH_RE.match(dest))


def inspect_command(command, _depth=0):
  if _depth > 3:
    return None
  cleaned, sub_shell_bodies, python_bodies = extract_heredocs(command)
  heredoc_cwd_home = bool(SHELL_CD_HOME_RE.search(command))
  for py_body in python_bodies:
    finding = inspect_python_code(py_body, cwd_home=heredoc_cwd_home)
    if finding is not None:
      return finding
  for sh_body in sub_shell_bodies:
    finding = inspect_command(sh_body, _depth + 1)
    if finding is not None:
      return finding

  segments, cmd_subs = split_shell_segments(cleaned)
  for sub_cmd in cmd_subs:
    finding = inspect_command(sub_cmd, _depth + 1)
    if finding is not None:
      return finding

  current_cd_giant_root = None
  loop_giant_vars = {}
  for segment in segments:
    seg = segment.strip()
    if not seg or seg.startswith('#'):
      continue
    try:
      tokens = shlex.split(seg)
    except ValueError:
      tokens = [t.strip('\'"') for t in seg.split()]
    while tokens and tokens[0] in ('do', 'then', 'else', 'elif'):
      tokens = tokens[1:]
    if not tokens:
      continue
    if tokens[0] == 'for' and len(tokens) >= 4 and tokens[2] == 'in':
      var_name = tokens[1]
      giant_items = [t for t in tokens[3:] if GIANT_ROOT_RE.match(t.rstrip(';\'"'))]
      if giant_items:
        loop_giant_vars[var_name] = giant_items[0]
      else:
        loop_giant_vars.pop(var_name, None)
      continue
    idx, has_command_prefix = unwrap_command_tokens(tokens)
    if idx >= len(tokens):
      continue
    bin_token = tokens[idx]
    base = os.path.basename(bin_token)
    if base in ('cd', 'pushd'):
      dest = None
      for tok in tokens[idx + 1 :]:
        if tok in ('-P', '-L', '--'):
          continue
        dest = tok
        break
      if dest and GIANT_ROOT_RE.match(dest):
        current_cd_giant_root = dest
      else:
        current_cd_giant_root = None
      continue
    if base in SHELL_BINS:
      sub_cmd = extract_shell_c_code(tokens, idx)
      if sub_cmd:
        finding = inspect_command(sub_cmd, _depth + 1)
        if finding is not None:
          return finding
      continue
    if PYTHON_BIN_RE.match(base):
      py_code = extract_python_c_code(tokens, idx)
      if py_code:
        finding = inspect_python_code(py_code, cwd_home=_cd_is_home(current_cd_giant_root))
        if finding is not None:
          return finding
      py_herestring = extract_python_herestring(tokens, idx)
      if py_herestring:
        finding = inspect_python_code(py_herestring, cwd_home=_cd_is_home(current_cd_giant_root))
        if finding is not None:
          return finding
      continue
    if base not in ('grep', 'egrep', 'ugrep', 'rg', 'ag', 'find', 'fd'):
      continue
    rest = [t.rstrip(')\'"') for t in tokens[idx + 1 :]]
    # 跳過 VAR = ... / VAR += ... 變數賦值誤判，但保留 `rg = ~/.claude` 搜字面 `=` 的攔截
    if (
      not has_command_prefix
      and not bin_token.startswith('/')
      and rest
      and rest[0] in ASSIGNMENT_OPS
      and (rest[0] != '=' or len(rest) < 2 or not GIANT_ROOT_RE.match(rest[1]))
    ):
      continue
    is_recursive_grep = base in ('grep', 'egrep', 'ugrep') and any(RECURSIVE_FLAG_RE.match(t) for t in rest)
    is_tree_walker = is_recursive_grep or base in ('rg', 'ag', 'find', 'fd')
    if is_recursive_grep and base == 'grep' and not has_command_prefix and not bin_token.startswith('/'):
      return (
        'bare-recursive-grep',
        seg[:80],
        (
          '偵測到遞迴 `grep -r/-R` 未使用 `command grep`。在 Claude Code 的 Bash 工具中，裸 `grep` 會被替換為帶 `--ignore-files` 的 ugrep shim 而靜默漏檔；'
          '請改寫為 `command grep -r ...`（或 `/usr/bin/grep -r ...`），若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。觸發片段：`'
          + seg[:60]
          + '`'
        ),
      )
    targets = extract_search_targets(base, rest)
    expanded_targets = []
    for t in targets:
      var_match = re.fullmatch(r'\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?', t)
      if var_match and var_match.group(1) in loop_giant_vars:
        expanded_targets.append(loop_giant_vars[var_match.group(1)])
      elif t in ('.', './') and current_cd_giant_root:
        expanded_targets.append(current_cd_giant_root)
      else:
        expanded_targets.append(t)
    if current_cd_giant_root and (
      not expanded_targets
      or (base in ('find', 'fd') and all(t.startswith('-') for t in expanded_targets[:1]))
    ):
      expanded_targets.append(current_cd_giant_root)
    matched_roots = [t for t in expanded_targets if GIANT_ROOT_RE.match(t)]
    if is_tree_walker and matched_roots:
      if SHALLOW_DEPTH_RE.search(seg) or PROJECTS_EXCLUDE_RE.search(seg):
        continue
      if any(r.rstrip('/').endswith('/projects') and '/.claude' in r for r in matched_roots):
        return (
          'unbounded-giant-root-search',
          seg[:80],
          (
            '偵測到對 `~/.claude/projects` 執行無深度限制的全樹搜尋。該目錄含兩萬餘份歷史對話與 `subagents/` `.jsonl`，全樹掃描會造成 120s–300s 逾時；'
            '查對話歷史請優先改用 `ccsi search "<關鍵詞>" -k 5` 或 `ccsi events --session <id>`，若需列舉檔案請加上 `-maxdepth 2`、`-name subagents -prune` 或直接指定具體專案子目錄（如 `~/.claude/projects/-Users-...`），'
            '若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。觸發片段：`'
            + seg[:60]
            + '`'
          ),
        )
      return (
        'unbounded-giant-root-search',
        seg[:80],
        (
          '偵測到對 `/`、`~` 或 `~/.claude` 根目錄執行無排除條件的遞迴搜尋。`~/.claude/projects/` 含兩萬餘份歷史對話 `.jsonl`，未排除會造成 120s–300s 逾時卡死；'
          '請加上 `--exclude-dir={.git,node_modules,.venv,out,.shopify,projects,cache,plugins,snapshot,jobs,file-history,logs,session-env}`（`rg` 用 `-g \'!projects/**\'`，`find` 用 `-maxdepth 2` 或 `-name projects -prune`；查對話歷史改用 `ccsi search "<關鍵詞>" -k 5`），'
          '或直接指定具體子目錄（如 `~/.claude/hooks`、`~/.claude/skills`），若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。觸發片段：`'
          + seg[:60]
          + '`'
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
