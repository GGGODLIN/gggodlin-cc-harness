#!/usr/bin/env python3
# 防漂移型提示 gate：
# 1. 字串比對 $PIPESTATUS（外層 shell 非 bash 時 deny）；
# 2. 掃描單引號 `python3 -c '...'` 內含 `\"` 的腳本並以 `ast.parse` 驗證語法，若因反斜線跳脫雙引號觸發 SyntaxError 則 deny；
# 3. 掃描測試／型別檢查／建置命令（pytest、unittest、vitest、jest、tsc、cargo/go/bun/npm/pnpm test 或 build）直接 `| tail`／`| head` 且未設 `pipefail` 或 `PIPESTATUS` 的吞錯寫法並 deny；
# 4. 掃描測試／型別檢查／建置命令後段以分號 `;` 直接尾接 `ls`、`echo`、`printf`、`true`、`pwd`、`date` 等無條件成功指令覆蓋退出碼的吞錯寫法並 deny。
# 不承諾完整 shell 語意，也會攔到只是談論該指令的文字（替代路徑：改用 Write/Edit 落檔或 `python3 - <<'PY'` 單引號 heredoc）。
# Surface table: Locked = 本 gate 與測試檔；Editable = 待檢 Bash 指令；Append-only = 審計 JSONL；Human-controlled = settings.json hooks 註冊。
# Locked lifecycle: bootstrap 由 settings.json 掛載；update 直接編輯本檔並跑 pipestatus-zsh-gate.test.py；recovery 從 settings.json 移除或改用落檔執行。
import ast
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time

PIPESTATUS_USE = re.compile(r'\$(?:\{PIPESTATUS(?:\[[^\]]+\])?\}|PIPESTATUS\b)')
BASH_PREFIX = re.compile(
  r'^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:command\s+)?(?:/[^\s]*/)?bash\s+(?:-[A-Za-z]*c\b|<<)'
)
PYTHON_C_SINGLE_QUOTED = re.compile(
  r'(?:^|[;&|()\s"])(?:/[^\s;()|&"]*/)?python(?:3(?:\.\d+)?)?\s+(?:-[IubBdEJsSOqVv]+\s+)*-c\s+\'(?P<code>[^\']*)\''
)
TEST_PIPE_SWALLOW = re.compile(
  r'(?:^|[;&()\n]|&&|\|\|)\s*'
  r'(?:env\s+(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|\'[^\']*\'|\S+)\s+)*|(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|\'[^\']*\'|\S+)\s+)+)?'
  r'(?:(?:uv|poetry|pipenv)\s+run\s+|(?:npx|pnpm|yarn|bunx)\s+(?:--no-install\s+|-[sS]\s+|--silent\s+)*)?'
  r'(?P<runner>'
  r'(?:[^\s;|&\n]*/)?(?:pytest|py\.test|vitest|jest|tsc)\b'
  r'|(?:[^\s;|&\n]*/)?python(?:3(?:\.\d+)?)?\s+(?:-[IubBdEJsSOqVv]+\s+)*-m\s+(?:pytest|unittest)\b'
  r'|(?:[^\s;|&\n]*/)?node\s+(?:[^\n;|&\s]+\s+)*(?:--test|--check)\b'
  r'|(?:[^\s;|&\n]*/)?(?:bash|sh)\s+[^\n;|&\s]*\.(?:test|spec)\.sh\b'
  r'|(?:bun|npm|pnpm|yarn|cargo|go)\s+(?:-[sS]\s+|--silent\s+)*(?:run\s+)?(?:-[sS]\s+|--silent\s+)*(?:test(?::[^\s;|&]+)?|typecheck|lint|check|build)\b'
  r'|(?:[^\s;|&\n]*/)?claude\s+plugin\s+(?:test|validate)\b'
  r')'
  r'(?:[^;&|\n]|(?<=>)&|\|(?!\|)[ \t]*(?!(?:[^\s;|&\n]*/)?(?:tail|head)\b))*\|(?!\|)[ \t]*(?:[^\s;|&\n]*/)?(?P<sink>tail|head)\b'
)
TEST_TRAILING_MASK = re.compile(
  r'(?:^|[;&()\n]|&&|\|\|)\s*'
  r'(?:env\s+(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|\'[^\']*\'|\S+)\s+)*|(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|\'[^\']*\'|\S+)\s+)+)?'
  r'(?:(?:uv|poetry|pipenv)\s+run\s+|(?:npx|pnpm|yarn|bunx)\s+(?:--no-install\s+|-[sS]\s+|--silent\s+)*)?'
  r'(?P<runner>'
  r'(?:[^\s;|&\n]*/)?(?:pytest|py\.test|vitest|jest|tsc|prettier)\b'
  r'|(?:[^\s;|&\n]*/)?python(?:3(?:\.\d+)?)?\s+(?:-[IubBdEJsSOqVv]+\s+)*-m\s+(?:pytest|unittest)\b'
  r'|(?:[^\s;|&\n]*/)?node\s+(?:[^\n;|&\s]+\s+)*(?:--test|--check)\b'
  r'|(?:[^\s;|&\n]*/)?(?:bash|sh)\s+[^\n;|&\s]*\.(?:test|spec)\.sh\b'
  r'|(?:bun|npm|pnpm|yarn|cargo|go)\s+(?:-[sS]\s+|--silent\s+)*(?:run\s+)?(?:-[sS]\s+|--silent\s+)*(?:test(?::[^\s;|&]+)?|typecheck|lint|check|build)\b'
  r'|(?:[^\s;|&\n]*/)?claude\s+plugin\s+(?:test|validate)\b'
  r')'
  r'[^\n;]*;\s*(?P<mask>(?:/[^\s;|&\n]*/)?(?:ls|echo|printf|true|pwd|date|cat)\b[^\n;]*)(?:;|\s*$)'
)
PIPEFAIL_GUARD = re.compile(r'\b(?:set\s+-[A-Za-z]*o\s+pipefail|PIPESTATUS|pipestatus)\b')
BARE_TIMEOUT_PREFIX = re.compile(
  r'(?:^|[;&()\n]|&&|\|\|)\s*'
  r'(?:env\s+(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|\'[^\']*\'|\S+)\s+)*|(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|\'[^\']*\'|\S+)\s+)+)?'
  r'(?P<cmd>timeout\s+(?:-[A-Za-z0-9-]+\s+)*\d+(?:\.\d+)?[smhd]?\s+\S+)'
)
SAFE_QUOTED_HEREDOC = re.compile(
  r'^(?P<prefix>\s*[^<#\r\n]*\S)\s*(?<!\\)<<(?P<strip_tabs>-)?\s*'
  r'(?P<quote>[\'\"])(?P<delimiter>[^\'\"\r\n]+)(?P=quote)\s*$'
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


def read_payload():
  try:
    payload = json.load(sys.stdin)
  except json.JSONDecodeError:
    return None
  return payload if isinstance(payload, dict) else None


def outer_shell():
  return os.environ.get('SHELL', '')


def outer_shell_is_bash(shell):
  return os.path.basename(shell.strip()) == 'bash'


def append_audit(command, session, shell, reason='outer-zsh-pipestatus'):
  path = Path(os.environ.get('PIPESTATUS_GATE_AUDIT', os.path.expanduser('~/.claude/logs/pipestatus-zsh-gate-audit.jsonl')))
  row = {
    'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'session': session,
    'action': 'deny',
    'reason': reason,
    'shell': shell,
  }
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
      handle.write(json.dumps(row, ensure_ascii=False) + '\n')
  except OSError as error:
    print(f'[pipestatus-zsh-gate] audit write failed: {error}', file=sys.stderr)


def find_python_c_escaped_quote_error(command):
  for match in PYTHON_C_SINGLE_QUOTED.finditer(command):
    code = match.group('code')
    if '\\"' not in code:
      continue
    try:
      ast.parse(code)
    except SyntaxError as err:
      return err.msg or 'SyntaxError'
  return None


def find_unprotected_test_pipe(command):
  if PIPEFAIL_GUARD.search(command):
    return None
  match = TEST_PIPE_SWALLOW.search(command)
  if not match:
    return None
  return f"{match.group('runner').strip()} | {match.group('sink')}"


def find_trailing_test_mask(command):
  match = TEST_TRAILING_MASK.search(command)
  if not match:
    return None
  mask_cmd = match.group('mask').strip().split()[0]
  return f"{match.group('runner').strip()} ...; {mask_cmd}"


def find_missing_bare_timeout(command):
  search_path = os.environ.get('PIPESTATUS_TIMEOUT_PATH', os.environ.get('PATH', ''))
  if shutil.which('timeout', path=search_path) is not None:
    return None
  match = BARE_TIMEOUT_PREFIX.search(command)
  if not match:
    return None
  return match.group('cmd').strip()


def main():
  payload = read_payload()
  if payload is None:
    return
  if payload.get('tool_name', 'Bash') != 'Bash':
    return
  tool_input = payload.get('tool_input')
  if not isinstance(tool_input, dict):
    return
  command = tool_input.get('command', '')
  if not isinstance(command, str):
    return
  scan_command = strip_safe_single_quoted_heredoc(command)
  shell = outer_shell()
  py_err = find_python_c_escaped_quote_error(scan_command)
  if py_err is not None:
    append_audit(command, payload.get('session_id', ''), shell, reason='python-c-escaped-quote-syntax-error')
    reason = (
      f'單引號 `python3 -c \'...\'` 內含 `\\"` 且無法通過 Python AST 語法解析（{py_err}）。'
      '在單引號腳本的雙引號 f-string 表達式內寫 `\\"` 會直接觸發 SyntaxError；'
      '請改用 `python3 - <<\'PY\'` 多行單引號 heredoc、在 f-string 內改用單引號（或 Python 3.12+ 直接不加反斜線），或先抽為局部變數。'
    )
    print(json.dumps({
      'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
      }
    }, ensure_ascii=False))
    return
  swallowed = find_unprotected_test_pipe(scan_command)
  if swallowed is not None:
    append_audit(command, payload.get('session_id', ''), shell, reason='unprotected-test-pipe-tail-head')
    reason = (
      f'偵測到測試／檢查命令直接 pipe 給 tail/head（`{swallowed}`），但未設定 `set -o pipefail`。'
      '這會讓 tail/head 的 exit 0 吞掉上游測試或編譯失敗的退出碼；'
      '請在實際執行該管線的 shell 內加上 `set -o pipefail;`（若管線包在 `bash -c` 內，須加在內層 shell，或先執行測試保存退出碼再處理輸出；直接移除 `| tail`／`| head` 亦可），若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。'
    )
    print(json.dumps({
      'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
      }
    }, ensure_ascii=False))
    return
  trailing_mask = find_trailing_test_mask(scan_command)
  if trailing_mask is not None:
    append_audit(command, payload.get('session_id', ''), shell, reason='trailing-command-masks-test-exit')
    reason = (
      f'偵測到測試／檢查命令後段直接用分號 `;` 尾接無條件成功指令（`{trailing_mask}`）。'
      '即使前段已設 `set -o pipefail`，尾段的 `ls`／`echo`／`true` 仍會把整個 shell 的退出碼覆蓋為 0（吞掉測試紅燈）；'
      '請改用 `&&` 串接、拆成獨立呼叫，或顯式保存 `rc=$?; ...; exit $rc`，若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。'
    )
    print(json.dumps({
      'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
      }
    }, ensure_ascii=False))
    return
  missing_timeout = find_missing_bare_timeout(scan_command)
  if missing_timeout is not None:
    append_audit(command, payload.get('session_id', ''), shell, reason='missing-gnu-timeout-command')
    reason = (
      f'偵測到命令使用裸 `timeout` 前綴（`{missing_timeout}`），但目前 macOS 環境 PATH 未安裝 GNU `timeout`（執行會報 Exit 127 command not found）。'
      '若需要「到期強制終止子程序」，請改用該命令自帶的限時旗標（如 `curl -m`）或 `python3 -I -c "import subprocess; subprocess.run([\'...\'], timeout=N, check=True)"`；'
      '若只需設定「前景等待上限」（注意：Bash 工具的 `timeout` 參數逾時後會將命令轉入背景繼續執行，不會自動終止子程序），請改填 Bash 工具的 `timeout` 參數，若只是寫文件或測試資料請改用 Write/Edit 落檔或 `<<\'EOF\'` 單引號 heredoc。'
    )
    print(json.dumps({
      'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'deny',
        'permissionDecisionReason': reason,
      }
    }, ensure_ascii=False))
    return
  if not PIPESTATUS_USE.search(scan_command):
    return
  if BASH_PREFIX.search(scan_command):
    return
  if outer_shell_is_bash(shell):
    return

  append_audit(command, payload.get('session_id', ''), shell)
  reason = (
    'PIPESTATUS 是 Bash 專屬變數，但偵測不到 Bash tool 的外層 shell 是 bash（多半是 zsh），這條指令會失敗。'
    '請改用明確的 if 分支保存 exit code，或把整段指令包進 `bash -lc`／`/bin/bash -c` 後重試。'
    f'偵測值 SHELL={shell or "(未設定)"}'
  )
  print(json.dumps({
    'hookSpecificOutput': {
      'hookEventName': 'PreToolUse',
      'permissionDecision': 'deny',
      'permissionDecisionReason': reason,
    }
  }, ensure_ascii=False))


if __name__ == '__main__':
  main()
