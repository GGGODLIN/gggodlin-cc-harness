#!/usr/bin/env python3
# 防漂移型提示 gate：只認常見入口（字串比對 $PIPESTATUS），不承諾完整語意，也會攔到只是談論該變數的文字。
# 外層 shell 以 hook 行程繼承的 SHELL 判定（CC 的 settings env.SHELL 同時決定 Bash tool 用哪個 shell）：
# basename 是 bash 才放行；zsh、未設定或判不出來時照舊 deny（2026-09-23 使用者拍板）。
import json
import os
from pathlib import Path
import re
import sys
import time

PIPESTATUS_USE = re.compile(r'\$(?:\{PIPESTATUS(?:\[[^\]]+\])?\}|PIPESTATUS\b)')
BASH_PREFIX = re.compile(
  r'^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:command\s+)?(?:/[^\s]*/)?bash\s+(?:-[A-Za-z]*c\b|<<)'
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


def append_audit(command, session, shell):
  path = Path(os.environ.get('PIPESTATUS_GATE_AUDIT', os.path.expanduser('~/.claude/logs/pipestatus-zsh-gate-audit.jsonl')))
  row = {
    'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'session': session,
    'action': 'deny',
    'reason': 'outer-zsh-pipestatus',
    'shell': shell,
  }
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
      handle.write(json.dumps(row, ensure_ascii=False) + '\n')
  except OSError as error:
    print(f'[pipestatus-zsh-gate] audit write failed: {error}', file=sys.stderr)


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
  if not PIPESTATUS_USE.search(scan_command):
    return
  if BASH_PREFIX.search(scan_command):
    return
  shell = outer_shell()
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
