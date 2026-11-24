#!/usr/bin/env python3
"""環境變數秘密檔（.env / .dev.env 等）讀取攔截 gate。

0. Threat model：
- 防誠實但健忘的 agent 在查看設定檔時直接呼叫 Read 讀取 .env / .dev.env / .env.local，
  或在 Bash 以 cat / head / 黑名單 sed / 無錨定 grep 印出整檔秘密（避免查看設定時將資料庫密碼或 API 金鑰明文印進對話）。
- 字串比對型 gate：不承諾完整語意，只認常見入口，認不出來就 fail closed。
- 不承諾區分「執行該指令」與「談論該指令的文字」：heredoc 內文、測試 payload、文件段落若含直接讀取
  .env 的指令字樣也會命中；遇到這種誤擋，內容改走 Write／Edit 落檔再執行。
- 不防同一 OS 使用者或刻意構造混淆路徑主動規避。

1. Surface 四分表與 Locked 面自身路徑：
| 類別 | 範圍 |
|---|---|
| Locked | ~/.claude/hooks/dotenv-read-gate.py、~/.claude/hooks/dotenv-read-gate.test.py、~/.claude/settings.json |
| Editable | 一般程式碼、設定範本檔（.env.example/.sample/.template/.dist/.schema/.defaults）、白名單 key 查詢指令 |
| Append-only | ~/.claude/logs/dotenv-read-audit.jsonl（僅記 deny 事件的時間、session、工具與路徑，不記秘密內容） |
| Human-controlled | ~/.claude/hooks/dotenv-read-gate.off（recovery sentinel）、.env 秘密檔本身 |

Locked 面三條自身路徑：
- bootstrap：尚未註冊 settings.json 前以 Write 建立本檔與測試檔，測試全綠後 Edit settings.json 掛載並 git commit。
- update：本 gate 僅攔受保護 .env* 路徑的 Read 與 Bash 讀取；對本檔、測試檔、settings.json 的 Read/Edit/Write
  與執行 `python3 ~/.claude/hooks/dotenv-read-gate.test.py` 均直接放行，留 git commit 稽核痕跡。
- recovery：建立 ~/.claude/hooks/dotenv-read-gate.off sentinel 檔（或設環境變數 DOTENV_READ_GATE_OFF=1）立即放行。

4. 繞行場景表：
1. 直接 Read .env / .dev.env / .env.local → Read 分支由 is_protected_dotenv_path 攔截。
2. 改用 Bash `cat .dev.env` 或黑名單 `sed -E 's/SECRET=.*/***/' .dev.env`（黑名單遮罩易漏）→ Bash 分支因不符合
   「只印 key 名」或「非敏感白名單 key 錨定 grep」而 fail-closed deny。
3. 在合法管線後串接 `; cat .env` 或夾帶 `-A 5` / `-v` 展開相鄰秘密行 → Bash 分支拆解所有子句並禁止上下文與反轉旗標。
4. 餵入損毀 JSON 或觸發執行期例外試圖讓 hook crash 放行 → 最外層 try/except 一律輸出 permissionDecision: "deny"（fail closed）。

Fixture：python3 ~/.claude/hooks/dotenv-read-gate.test.py
"""
from __future__ import annotations

import json
import os
import re
import shlex
import stat
import sys
import time
from pathlib import Path

SENTINEL = Path(os.environ.get('DOTENV_READ_GATE_SENTINEL', '~/.claude/hooks/dotenv-read-gate.off')).expanduser()
LOG_LIMIT = 512 * 1024

SAFE_SUFFIXES = (
  '.example', '.sample', '.template', '.dist', '.schema', '.defaults',
  '.md', '.txt', '.py', '.sh', '.js', '.ts', '.mjs', '.cjs',
  '.json', '.yaml', '.yml', '.toml', '.lock', '.test', '.spec',
)

SENSITIVE_KEY_FRAGMENTS = (
  'PASS', 'SECRET', 'KEY', 'TOKEN', 'CRED', 'AUTH', 'PRIV', 'PWD',
  'DSN', 'CONN', 'COOKIE', 'SALT', 'HASH', 'CERT', 'SIGN', 'BEARER',
  'DATABASE_URL', 'DB_URL', 'REDIS_URL', 'MONGO_URL', 'POSTGRES', 'MYSQL',
  'AMQP', 'BROKER', 'WEBHOOK', 'MNEMONIC', 'SEED',
)

METADATA_COMMANDS = frozenset({
  'test', '[', '[[', 'ls', 'stat', 'wc', 'file', 'rm', 'mv', 'cp', 'touch', 'chmod', 'ln',
})

GIT_SAFE_SUBCOMMANDS = frozenset({
  'status', 'ls-files', 'check-ignore', 'rm', 'mv', 'add', 'restore', 'checkout',
})


CONTROL_BIDI_RE = re.compile(r'[\x00-\x1f\x7f‪-‮⁦-⁩]')
STDERR_REDIRECT_RE = re.compile(r'(?:^|\s)(?:(?:[12&]?>/dev/null)|2>&1)(?=\s|$)')
SAFE_TEXT_HEREDOC_OPENER_RE = re.compile(
  r'^(?P<prefix>\s*[^<#|\r\n`]*\S)\s*(?<!\\)<<(?P<strip_tabs>-)?\s*\'(?P<delimiter>[^\'\r\n]+)\'(?P<suffix>\s*(?:>>?\s*[^\s;&|<>]+)?)\s*$'
)
SAFE_HEREDOC_CMD_RE = re.compile(
  r'^\s*(?:'
  r'git\s+(?:-C\s+\S+\s+)?commit\b.*-F\s*-'
  r'|gh\s+(?:pr|issue)\s+(?:create|edit|comment)\b'
  r'|(?:cat|tee)\s*(?:-a\s+)?(?:>>?\s*(?P<dest>[^\s;&|<>]+))?\s*'
  r')$'
)
SAFE_STREAM_FILTER_HEADS = frozenset({
  'tr', 'sort', 'uniq', 'head', 'tail', 'wc', 'cut', 'paste', 'column',
  'grep', 'egrep', 'rg', 'awk', 'sed',
})
FIND_UNSAFE_FLAGS = frozenset({
  '-exec', '-execdir', '-ok', '-okdir', '-delete', '-fls', '-fprint', '-fprint0', '-fprintf',
})


def append_audit(session_id: str, tool_name: str, target: str) -> None:
  audit_path = Path(
    os.environ.get(
      'DOTENV_READ_GATE_AUDIT',
      str(Path.home() / '.claude/logs/dotenv-read-audit.jsonl'),
    )
  ).expanduser()
  row = {
    'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'session': CONTROL_BIDI_RE.sub('', str(session_id or ''))[:128],
    'tool': CONTROL_BIDI_RE.sub('', str(tool_name or ''))[:32],
    'outcome': 'deny',
    'target': CONTROL_BIDI_RE.sub('', str(target or ''))[:256],
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


def hook_deny(reason: str, session_id: str = '', tool_name: str = '', target: str = '') -> None:
  if tool_name or target:
    append_audit(session_id, tool_name, target)
  clean_reason = CONTROL_BIDI_RE.sub('', reason)
  print(json.dumps({
    'hookSpecificOutput': {
      'hookEventName': 'PreToolUse',
      'permissionDecision': 'deny',
      'permissionDecisionReason': clean_reason,
    }
  }, ensure_ascii=False))


def is_protected_dotenv_path(raw_path: str) -> bool:
  if not raw_path or not isinstance(raw_path, str):
    return False
  cleaned = CONTROL_BIDI_RE.sub('', raw_path).strip().strip('\'"`').rstrip('/')
  if not cleaned:
    return False
  base = os.path.basename(cleaned).lower()
  if not base or any(base.endswith(suf) for suf in SAFE_SUFFIXES):
    return False
  if base == '.env' or base.startswith('.env.'):
    return True
  if re.fullmatch(r'\.[a-z0-9_-]+\.env(?:\.[a-z0-9_-]+)?', base):
    return True
  if re.fullmatch(r'(?:dev|prod|production|staging|local|secret|secrets)\.env(?:\.[a-z0-9_-]+)?', base):
    return True
  return False


def strip_safe_text_heredoc(command: str) -> str:
  if '<<' not in command:
    return command
  lines = command.splitlines(keepends=True)
  out = lines.copy()
  idx = 0
  while idx < len(lines):
    m = SAFE_TEXT_HEREDOC_OPENER_RE.match(lines[idx].rstrip('\r\n'))
    if not m:
      idx += 1
      continue
    prefix = m.group('prefix')
    suffix = (m.group('suffix') or '').strip()
    last_clause = re.split(r'(?:&&|\|\||;)', prefix)[-1].strip()
    if '$(' in last_clause or '`' in last_clause or '|' in last_clause:
      idx += 1
      continue
    if '$(' in suffix or '`' in suffix or '|' in suffix:
      idx += 1
      continue
    cmd_m = SAFE_HEREDOC_CMD_RE.match(last_clause)
    if not cmd_m:
      idx += 1
      continue
    dest = cmd_m.group('dest')
    if dest is None and suffix:
      suf_m = re.match(r'^>>?\s*([^\s;&|<>]+)$', suffix)
      dest = suf_m.group(1) if suf_m else None
    is_cat_or_tee = bool(re.match(r'^\s*(?:cat|tee)\b', last_clause))
    if is_cat_or_tee:
      if dest is None:
        idx += 1
        continue
      clean_dest = dest.strip('\'"')
      if is_protected_dotenv_path(clean_dest) or not clean_dest.lower().endswith(('.md', '.txt')):
        idx += 1
        continue
    elif suffix:
      idx += 1
      continue
    delimiter = m.group('delimiter')
    strip_tabs = bool(m.group('strip_tabs'))
    term_idx = None
    for cand_idx in range(idx + 1, len(lines)):
      cand = lines[cand_idx].rstrip('\r\n')
      if strip_tabs:
        cand = cand.lstrip('\t')
      if cand == delimiter:
        term_idx = cand_idx
        break
    if term_idx is None:
      return command
    for body_idx in range(idx + 1, term_idx):
      out[body_idx] = '\n' if out[body_idx].endswith(('\n', '\r')) else ''
    idx = term_idx + 1
  return ''.join(out)


def extract_dotenv_tokens(text: str) -> list[str]:
  tokens = re.findall(r'[^\s;&|()<>`"\'=，。、；：！？（）「」『』【】〔〕《》—]+', text)
  cleaned_tokens = [tok.rstrip('.,:;!?') for tok in tokens]
  return [tok for tok in cleaned_tokens if tok and is_protected_dotenv_path(tok)]


def strip_benign_stderr_redirects(text: str) -> str:
  return STDERR_REDIRECT_RE.sub(' ', text).strip()


def split_top_level_pipes(clause: str) -> list[str] | None:
  parts: list[str] = []
  buf: list[str] = []
  quote: str | None = None
  escaped = False
  i = 0
  while i < len(clause):
    ch = clause[i]
    if escaped:
      buf.append(ch)
      escaped = False
      i += 1
      continue
    if ch == '\\' and quote != "'":
      buf.append(ch)
      escaped = True
      i += 1
      continue
    if quote is not None:
      if ch == quote:
        quote = None
      buf.append(ch)
      i += 1
      continue
    if ch in ("'", '"'):
      quote = ch
      buf.append(ch)
      i += 1
      continue
    if ch == '|':
      parts.append(''.join(buf).strip())
      buf = []
      i += 1
      continue
    buf.append(ch)
    i += 1
  if quote is not None or escaped:
    return None
  parts.append(''.join(buf).strip())
  return parts


def split_top_level_clauses(command: str) -> list[str] | None:
  clauses: list[str] = []
  buf: list[str] = []
  quote: str | None = None
  escaped = False
  i = 0
  while i < len(command):
    ch = command[i]
    if escaped:
      buf.append(ch)
      escaped = False
      i += 1
      continue
    if ch == '\\' and quote != "'":
      buf.append(ch)
      escaped = True
      i += 1
      continue
    if quote is not None:
      if ch == quote:
        quote = None
      buf.append(ch)
      i += 1
      continue
    if ch in ("'", '"'):
      quote = ch
      buf.append(ch)
      i += 1
      continue
    if command[i : i + 2] in ('&&', '||'):
      seg = ''.join(buf).strip()
      if seg:
        clauses.append(seg)
      buf = []
      i += 2
      continue
    if ch in (';', '\n'):
      seg = ''.join(buf).strip()
      if seg:
        clauses.append(seg)
      buf = []
      i += 1
      continue
    buf.append(ch)
    i += 1
  if quote is not None or escaped:
    return None
  tail = ''.join(buf).strip()
  if tail:
    clauses.append(tail)
  return clauses


def has_unquoted_shell_meta(text: str, allow_subshell: bool = False) -> bool:
  quote: str | None = None
  escaped = False
  i = 0
  n = len(text)
  while i < n:
    ch = text[i]
    if escaped:
      escaped = False
      i += 1
      continue
    if ch == '\\' and quote != "'":
      escaped = True
      i += 1
      continue
    if quote == "'":
      if ch == "'":
        quote = None
      i += 1
      continue
    if quote == '"':
      if ch == '"':
        quote = None
      elif ch == '`':
        return True
      elif not allow_subshell and ch == '$' and i + 1 < n and text[i + 1] == '(':
        return True
      i += 1
      continue
    if ch in ("'", '"'):
      quote = ch
      i += 1
      continue
    if ch in ('<', '>', '`'):
      return True
    if not allow_subshell and ch == '$' and i + 1 < n and text[i + 1] == '(':
      return True
    i += 1
  return quote is not None or escaped


def _parse_grep_args(tokens: list[str], start_idx: int) -> tuple[bool, list[str], bool]:
  """回傳 (ok, file_targets, has_recursive_or_file_pattern)。ok=False 表示語法不可安全分類。"""
  has_pattern_flag = False
  has_unsafe_flag = False
  positionals: list[str] = []
  after_dd = False
  idx = start_idx
  while idx < len(tokens):
    tok = tokens[idx]
    if after_dd:
      positionals.append(tok)
      idx += 1
      continue
    if tok == '--':
      after_dd = True
      idx += 1
      continue
    if tok in ('-e', '--regexp'):
      has_pattern_flag = True
      idx += 2
      continue
    if tok in ('-f', '--file'):
      has_unsafe_flag = True
      idx += 2
      continue
    if tok in ('-m', '--max-count', '-A', '-B', '-C', '--after-context', '--before-context', '--context', '--label', '--color', '--colour', '--include', '--exclude', '--exclude-dir'):
      idx += 2
      continue
    if tok.startswith('--'):
      if tok in ('--recursive', '--dereference-recursive') or tok.startswith(('--file=',)):
        has_unsafe_flag = True
      elif tok.startswith('--regexp='):
        has_pattern_flag = True
      idx += 1
      continue
    if tok.startswith('-') and len(tok) > 1:
      flags = tok[1:]
      if any(ch in flags for ch in ('r', 'R', 'f')):
        has_unsafe_flag = True
      if 'e' in flags:
        has_pattern_flag = True
        if flags.endswith('e'):
          idx += 2
          continue
      idx += 1
      continue
    positionals.append(tok)
    idx += 1
  if has_pattern_flag:
    return (True, positionals, has_unsafe_flag)
  if not positionals:
    return (False, [], has_unsafe_flag)
  return (True, positionals[1:], has_unsafe_flag)


def _is_stdin_only_sed(tokens: list[str], start_idx: int) -> bool:
  has_script_flag = False
  positionals: list[str] = []
  after_dd = False
  idx = start_idx
  while idx < len(tokens):
    tok = tokens[idx]
    if after_dd:
      positionals.append(tok)
      idx += 1
      continue
    if tok == '--':
      after_dd = True
      idx += 1
      continue
    if tok in ('-f', '--file', '-i', '--in-place'):
      return False
    if tok in ('-e', '--expression'):
      has_script_flag = True
      idx += 2
      continue
    if tok.startswith('--'):
      if tok.startswith(('--file=', '--in-place')):
        return False
      if tok.startswith('--expression='):
        has_script_flag = True
      idx += 1
      continue
    if tok.startswith('-') and len(tok) > 1:
      flags = tok[1:]
      if any(ch in flags for ch in ('f', 'i')):
        return False
      if 'e' in flags:
        has_script_flag = True
        if flags.endswith('e'):
          idx += 2
          continue
      idx += 1
      continue
    positionals.append(tok)
    idx += 1
  if has_script_flag:
    return len(positionals) == 0
  return len(positionals) == 1


def is_safe_stream_filter(stage: str) -> bool:
  clean = strip_benign_stderr_redirects(stage)
  if not clean or has_unquoted_shell_meta(clean):
    return False
  try:
    tokens = shlex.split(clean)
  except ValueError:
    return False
  if not tokens:
    return False
  idx = 0
  if tokens[idx] == 'command':
    idx += 1
  if idx >= len(tokens):
    return False
  head = os.path.basename(tokens[idx])
  if head not in SAFE_STREAM_FILTER_HEADS:
    return False
  if not extract_dotenv_tokens(clean):
    return True
  # 下游若提及 .env 字樣，只放行「保證純讀 stdin、無輸入檔案參數」的 grep/egrep/rg/sed
  if head in ('grep', 'egrep', 'rg'):
    ok, targets, has_unsafe = _parse_grep_args(tokens, idx + 1)
    return ok and not has_unsafe and len(targets) == 0
  if head == 'sed':
    return _is_stdin_only_sed(tokens, idx + 1)
  return False


def is_key_stripper_stage(stage: str) -> bool:
  clean = strip_benign_stderr_redirects(stage)
  if re.match(
    r'^cut\s+(?:-[s]\s+)?(?:-d\s*(?:=|\'=\'|"=")|-d=)\s*(?:-[s]\s+)?-f\s*1$',
    clean,
  ):
    return True
  if re.match(r'^awk\s+-F\s*(?:=|\'=\'|"=")\s+\'\{print\s+\$1\}\'$', clean):
    return True
  if re.match(r'^sed\s+(?:-E\s+)?\'s/=\.\*//\'$', clean):
    return True
  return False


def is_count_or_files_only_grep(stage: str) -> bool:
  clean = strip_benign_stderr_redirects(stage)
  try:
    tokens = shlex.split(clean)
  except ValueError:
    return False
  idx = 0
  if idx < len(tokens) and tokens[idx] == 'command':
    idx += 1
  if idx >= len(tokens):
    return False
  base = os.path.basename(tokens[idx])
  if base not in ('grep', 'egrep', 'rg'):
    return False
  has_safe_mode = False
  for tok in tokens[idx + 1 :]:
    if tok == '--':
      break
    if tok in ('--count', '--files-with-matches', '--files-without-match', '--quiet', '--silent'):
      has_safe_mode = True
      continue
    if tok.startswith('--'):
      if tok.startswith(('--context', '--after-context', '--before-context', '--file')):
        return False
      continue
    if tok.startswith('-') and len(tok) > 1:
      flags = tok[1:]
      if any(ch in flags for ch in ('A', 'B', 'C', 'f')):
        return False
      if any(ch in flags for ch in ('c', 'l', 'L', 'q')) and re.fullmatch(r'[EcHilLnqswFx]+', flags):
        has_safe_mode = True
  return has_safe_mode


def is_safe_key_list_pipeline(clause: str) -> bool:
  clean_clause = strip_benign_stderr_redirects(clause)
  if any(ch in clean_clause for ch in ('`', '$(', '<', '>')):
    return False
  parts = split_top_level_pipes(clean_clause)
  if not parts or any(not p for p in parts):
    return False
  first = parts[0]
  only_lhs_grep = re.match(
    r'^(?:command\s+)?(?:grep|egrep|rg)\s+(?=(?:-[oEhIin]+\s+)*-[oEhIin]*o[oEhIin]*\s+)(?:-[oEhIin]+\s+)+[\'"]\^[A-Za-z0-9_-]*(?:\[[A-Za-z0-9_-]+\][\*\+\?]?)+=[\'"]\s+\S+\s*$',
    first,
  )
  if only_lhs_grep or is_count_or_files_only_grep(first):
    return all(is_safe_stream_filter(st) for st in parts[1:])
  if len(parts) < 2:
    return False
  reader, stripper = parts[0], parts[1]
  if not re.match(r'^(?:command\s+)?(?:grep|egrep|rg|cat)\b', reader):
    return False
  if re.search(r'\s-(?:[vABC]|-invert-match|-context|-after-context|-before-context)\b', reader):
    return False
  if not is_key_stripper_stage(stripper):
    return False
  return all(is_safe_stream_filter(st) for st in parts[2:])


def is_safe_allowlist_grep(clause: str) -> bool:
  if '`' in clause or '$(' in clause or '<' in clause:
    return False
  if re.search(r'(?:^|\s)-(?:[A-Za-z]*[vABC][A-Za-z]*|-invert-match|-context|-after-context|-before-context)(?:\s|$)', clause):
    return False
  m = re.match(
    r'^(?:command\s+)?(?:grep|egrep|rg)\s+(?:-[EhIin]+\s+)*[\'"]\^\(?([A-Za-z0-9_|]+)\)?=[\'"]\s+([^\s|;&<>`]+)\s*$',
    clause.strip(),
  )
  if not m:
    return False
  keys = [k for k in m.group(1).split('|') if k]
  if not keys:
    return False
  for k in keys:
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', k):
      return False
    upper_k = k.upper()
    if any(frag in upper_k for frag in SENSITIVE_KEY_FRAGMENTS):
      return False
  return True


def is_safe_jq_json_clause(clause: str) -> bool:
  clean_clause = strip_benign_stderr_redirects(clause)
  if has_unquoted_shell_meta(clean_clause):
    return False
  parts = split_top_level_pipes(clean_clause)
  if not parts or any(not p for p in parts):
    return False
  try:
    tokens = shlex.split(parts[0])
  except ValueError:
    return False
  idx = 0
  if idx < len(tokens) and tokens[idx] == 'command':
    idx += 1
  if idx >= len(tokens) or os.path.basename(tokens[idx]) != 'jq':
    return False
  idx += 1
  positionals: list[str] = []
  after_dd = False
  while idx < len(tokens):
    tok = tokens[idx]
    if after_dd:
      positionals.append(tok)
      idx += 1
      continue
    if tok == '--':
      after_dd = True
      idx += 1
      continue
    if tok in ('-f', '--from-file', '--rawfile', '--slurpfile', '-R', '--raw-input'):
      return False
    if tok in ('--arg', '--argjson'):
      idx += 3
      continue
    if tok in ('--indent',):
      idx += 2
      continue
    if tok.startswith('-'):
      if not tok.startswith('--') and any(ch in tok[1:] for ch in ('f', 'R')):
        return False
      idx += 1
      continue
    positionals.append(tok)
    idx += 1
  if len(positionals) < 2:
    return False
  input_files = positionals[1:]
  if not all(
    not is_protected_dotenv_path(f) and f.lower().endswith(('.json', '.jsonl'))
    for f in input_files
  ):
    return False
  return all(is_safe_stream_filter(st) for st in parts[1:])


def is_safe_grep_non_dotenv_targets(clause: str) -> bool:
  clean_clause = strip_benign_stderr_redirects(clause)
  if has_unquoted_shell_meta(clean_clause):
    return False
  parts = split_top_level_pipes(clean_clause)
  if not parts or any(not p for p in parts):
    return False
  try:
    tokens = shlex.split(parts[0])
  except ValueError:
    return False
  idx = 0
  while idx < len(tokens) and (tokens[idx] == 'command' or re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[idx])):
    idx += 1
  if idx >= len(tokens):
    return False
  head = os.path.basename(tokens[idx])
  if head not in ('grep', 'egrep', 'rg'):
    return False
  ok, targets, has_unsafe = _parse_grep_args(tokens, idx + 1)
  if not ok or has_unsafe or not targets:
    return False
  for target in targets:
    if any(ch in target for ch in ('$', '*', '?', '[')):
      return False
    if is_protected_dotenv_path(target):
      return False
    base = os.path.basename(target.rstrip('/')).lower()
    if not any(base.endswith(suf) for suf in SAFE_SUFFIXES):
      return False
  return all(is_safe_stream_filter(st) for st in parts[1:])


def is_safe_echo_clause(clause: str) -> bool:
  clean_clause = strip_benign_stderr_redirects(clause)
  if has_unquoted_shell_meta(clean_clause, allow_subshell=True):
    return False
  parts = split_top_level_pipes(clean_clause)
  if not parts or any(not p for p in parts):
    return False
  first = parts[0]
  try:
    tokens = shlex.split(first)
  except ValueError:
    return False
  idx = 0
  while idx < len(tokens) and (tokens[idx] == 'command' or re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[idx])):
    idx += 1
  if idx >= len(tokens):
    return False
  head = os.path.basename(tokens[idx])
  if head not in ('echo', 'printf'):
    return False
  if '$(' in first:
    inners: list[str] = []
    pos = 0
    while True:
      start = first.find('$(', pos)
      if start == -1:
        break
      depth = 1
      j = start + 2
      quote: str | None = None
      escaped = False
      while j < len(first) and depth > 0:
        ch = first[j]
        if escaped:
          escaped = False
          j += 1
          continue
        if ch == '\\' and quote != "'":
          escaped = True
          j += 1
          continue
        if quote is not None:
          if ch == quote:
            quote = None
          j += 1
          continue
        if ch in ("'", '"'):
          quote = ch
        elif ch == '(':
          depth += 1
        elif ch == ')':
          depth -= 1
        j += 1
      if depth != 0:
        return False
      inner = first[start + 2 : j - 1].strip()
      if not inner or '$(' in inner or '`' in inner:
        return False
      inners.append(inner)
      pos = j
    for inner in inners:
      if not extract_dotenv_tokens(inner):
        continue
      sub_clauses = split_top_level_clauses(inner)
      if not sub_clauses:
        return False
      for sub in sub_clauses:
        if not extract_dotenv_tokens(sub):
          continue
        if not (
          is_safe_metadata_clause(sub)
          or is_safe_key_list_pipeline(sub)
          or is_safe_allowlist_grep(sub)
          or is_safe_jq_json_clause(sub)
          or is_safe_grep_non_dotenv_targets(sub)
        ):
          return False
  return all(is_safe_stream_filter(st) for st in parts[1:])


def is_safe_metadata_clause(clause: str) -> bool:
  clean_clause = strip_benign_stderr_redirects(clause)
  if has_unquoted_shell_meta(clean_clause):
    return False
  parts = split_top_level_pipes(clean_clause)
  if not parts or any(not p for p in parts):
    return False
  first = parts[0]
  downstream = parts[1:]
  if downstream and not all(is_safe_stream_filter(st) for st in downstream):
    return False
  tokens = [t.strip('\'"') for t in re.findall(r'[^\s]+', first) if t.strip('\'"')]
  if not tokens:
    return not downstream
  idx = 0
  while idx < len(tokens) and (tokens[idx] == 'command' or re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[idx])):
    idx += 1
  if idx >= len(tokens):
    return False
  head = os.path.basename(tokens[idx])
  rest = tokens[idx + 1:]
  if head in METADATA_COMMANDS:
    if downstream and head not in ('ls', 'stat', 'wc', 'file'):
      return False
    return True
  if head == 'find':
    if any(tok in FIND_UNSAFE_FLAGS for tok in rest):
      return False
    return True
  if head == 'cmp' and not downstream:
    return any(flag in rest for flag in ('-s', '--silent', '--quiet'))
  if head == 'git':
    sub_idx = 0
    while sub_idx < len(rest) and rest[sub_idx].startswith('-'):
      if rest[sub_idx] in ('-C', '-c', '--git-dir', '--work-tree'):
        sub_idx += 2
      else:
        sub_idx += 1
    if sub_idx >= len(rest):
      return False
    sub = rest[sub_idx]
    if sub in GIT_SAFE_SUBCOMMANDS:
      return True
    if sub == 'diff' and any(flag in rest for flag in ('--name-only', '--stat', '--numstat', '--shortstat')):
      return True
  return False


def check_bash_command(command: str) -> str | None:
  cleaned = strip_safe_text_heredoc(command)
  dotenv_hits = extract_dotenv_tokens(cleaned)
  if not dotenv_hits:
    return None
  clauses = split_top_level_clauses(cleaned)
  if not clauses:
    return dotenv_hits[0]
  for clause in clauses:
    clause_hits = extract_dotenv_tokens(clause)
    if not clause_hits:
      continue
    if (
      is_safe_metadata_clause(clause)
      or is_safe_echo_clause(clause)
      or is_safe_key_list_pipeline(clause)
      or is_safe_allowlist_grep(clause)
      or is_safe_jq_json_clause(clause)
      or is_safe_grep_non_dotenv_targets(clause)
    ):
      continue
    return clause_hits[0]
  return None


def main() -> int:
  try:
    if os.environ.get('DOTENV_READ_GATE_OFF') == '1' or SENTINEL.exists():
      return 0
    raw = sys.stdin.read()
    if not raw or not raw.strip():
      hook_deny('❌ [dotenv-read-gate] 收到空 payload，安全型 gate 預設拒絕（fail closed）。')
      return 0
    payload = json.loads(raw)
    if not isinstance(payload, dict):
      hook_deny('❌ [dotenv-read-gate] payload 格式非 JSON object，安全型 gate 預設拒絕（fail closed）。')
      return 0
    session_id = str(payload.get('session_id') or '')
    tool_name = payload.get('tool_name', '')
    tool_input = payload.get('tool_input')
    if not isinstance(tool_input, dict):
      hook_deny('❌ [dotenv-read-gate] tool_input 缺失或格式錯誤，安全型 gate 預設拒絕（fail closed）。', session_id, str(tool_name), 'invalid_tool_input')
      return 0

    if tool_name == 'Read':
      file_path = str(tool_input.get('file_path') or '')
      if is_protected_dotenv_path(file_path):
        hook_deny(
          f'❌ [dotenv-read-gate] 禁止直接用 Read 讀取環境變數秘密檔（{file_path}），避免整檔秘密印進 context。'
          f'替代路徑：(1) 只列欄位名：command grep -E "^[A-Za-z_][A-Za-z0-9_]*=" "{file_path}" | cut -d= -f1；'
          f'(2) 只讀非敏感白名單 key：command grep -E "^(PORT|NODE_ENV|API_URL|HOST)=" "{file_path}"。'
          f'若為文件／測試內容誤攔，請改走 Write／Edit 落檔再執行，或由使用者建立 ~/.claude/hooks/dotenv-read-gate.off 暫停。',
          session_id,
          'Read',
          file_path,
        )
      return 0

    if tool_name == 'Bash':
      command = str(tool_input.get('command') or '')
      blocked_target = check_bash_command(command)
      if blocked_target:
        hook_deny(
          f'❌ [dotenv-read-gate] 禁止在 Bash 直接傾印或以黑名單遮罩讀取環境變數秘密檔（{blocked_target}）。'
          f'替代路徑：(1) 只列欄位名（後可接 | tr/grep/sort/wc）：command grep -E "^[A-Za-z_][A-Za-z0-9_]*=" "{blocked_target}" | cut -d= -f1；'
          f'(2) 只讀非敏感白名單 key（禁含 PASS/SECRET/KEY/TOKEN）：command grep -E "^(PORT|NODE_ENV|API_URL|HOST)=" "{blocked_target}"。'
          f'若為 heredoc／文件／測試 payload 談論該指令被誤攔，請改走 Write／Edit 落檔再執行，或由使用者建立 ~/.claude/hooks/dotenv-read-gate.off 暫停。',
          session_id,
          'Bash',
          blocked_target,
        )
      return 0

    return 0
  except Exception as exc:
    hook_deny(f'❌ [dotenv-read-gate] 內部判定例外（{type(exc).__name__}），安全型 gate 預設拒絕（fail closed）。')
    return 0


if __name__ == '__main__':
  sys.exit(main())
