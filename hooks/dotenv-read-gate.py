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


def extract_dotenv_tokens(text: str) -> list[str]:
  tokens = re.findall(r'[^\s;&|()<>`"\'=]+', text)
  return [tok for tok in tokens if is_protected_dotenv_path(tok)]


def is_safe_key_list_pipeline(clause: str) -> bool:
  if any(ch in clause for ch in ('`', '$(', '<')):
    return False
  parts = [p.strip() for p in clause.split('|')]
  if len(parts) == 1:
    single = parts[0]
    m = re.match(
      r'^(?:command\s+)?(?:grep|egrep|rg)\s+(?:-[oE]+\s+)+[\'"]\^\[A-Za-z_\]\[A-Za-z0-9_\]\*=[\'"]\s+\S+\s*$',
      single,
    )
    return bool(m)
  if len(parts) != 2:
    return False
  reader, stripper = parts
  if not re.match(r'^(?:command\s+)?(?:grep|egrep|rg|cat)\b', reader):
    return False
  if re.search(r'\s-(?:[vABC]|-invert-match|-context|-after-context|-before-context)\b', reader):
    return False
  if re.match(r'^cut\s+(?:-d\s*(?:=|\'=\'|"=") |-d=)\s*-f\s*1$', stripper) or re.match(
    r'^cut\s+(?:-d\s*(?:=|\'=\'|"=")|-d=)\s+-f\s*1$', stripper
  ):
    return True
  if re.match(r'^awk\s+-F\s*(?:=|\'=\'|"=")\s+\'\{print\s+\$1\}\'$', stripper):
    return True
  if re.match(r'^sed\s+(?:-E\s+)?\'s/=\.\*//\'$', stripper):
    return True
  return False


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


def is_safe_metadata_clause(clause: str) -> bool:
  if '|' in clause or '`' in clause or '$(' in clause or '<' in clause:
    return False
  tokens = [t.strip('\'"') for t in re.findall(r'[^\s]+', clause.strip()) if t.strip('\'"')]
  if not tokens:
    return True
  idx = 0
  while idx < len(tokens) and (tokens[idx] == 'command' or re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', tokens[idx])):
    idx += 1
  if idx >= len(tokens):
    return True
  head = os.path.basename(tokens[idx])
  rest = tokens[idx + 1:]
  if head in METADATA_COMMANDS:
    return True
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
  dotenv_hits = extract_dotenv_tokens(command)
  if not dotenv_hits:
    return None
  clauses = [c.strip() for c in re.split(r'(?:&&|\|\||;|\n)+', command) if c.strip()]
  if not clauses:
    return dotenv_hits[0]
  for clause in clauses:
    clause_hits = extract_dotenv_tokens(clause)
    if not clause_hits:
      continue
    if is_safe_metadata_clause(clause) or is_safe_key_list_pipeline(clause) or is_safe_allowlist_grep(clause):
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
          f'替代路徑：(1) 只列欄位名：command grep -E "^[A-Za-z_][A-Za-z0-9_]*=" "{blocked_target}" | cut -d= -f1；'
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
