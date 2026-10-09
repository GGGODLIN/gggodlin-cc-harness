#!/usr/bin/env python3
"""工具升級注意事項 gate。

Threat model：防誠實但健忘的 agent 在已獲「全升」授權後，漏掉個別工具的釘版配套。只掃 Bash command 的常見
uv tool／brew／npm -g／cargo install 入口，不承諾完整 shell 語意，也不防同一 OS 使用者主動繞過。字串比對會把
heredoc 或文件裡的升級指令也當成執行；遇到這種誤擋，改用 Write／Edit 落檔。命中 pinned 工具但讀不到註冊檔、
釘版檔或目標 SHA／npm 版本時 fail closed；未登記工具照常放行。npm 僅支援 npx 設定中的明確 x.y.z 版本，
多份設定必須一致；hold_until 含當日拒絕更新。本 gate 不攔 npx 啟動或設定檔編輯，不取代 npm 的發布冷卻期。

Surface：Locked＝本檔、tool-upgrade-notes.json、釘版來源；Editable＝升級指令；Append-only＝無；
Human-controlled＝新增釘版規則、改 EXPECTED_COMMIT、tool-upgrade-guard.off。bootstrap 用 settings Edit；update 用
Edit 後跑 fixture；recovery 建 sentinel，或從 Claude Code 外的 terminal 升級。這支 gate 不保證升級後測試真的執行，
只把 verify_command 注入當前 turn；釘版工具的安裝版本一致性才是硬擋。

Fixture：bash ~/.claude/hooks/tool-upgrade-guard.test.sh；python3 ~/.claude/hooks/tool-upgrade-guard-npm.test.py
"""
import json
import os
import re
import shlex
import stat
import sys
from pathlib import Path
from datetime import date

REGISTRY = Path(os.environ.get('TOOL_UPGRADE_NOTES', '~/.claude/references/tool-upgrade-notes.json')).expanduser()
SENTINEL = Path(os.environ.get('TOOL_UPGRADE_GUARD_OFF', '~/.claude/hooks/tool-upgrade-guard.off')).expanduser()
UPGRADE_PATTERNS = (
  re.compile(r'\buv\s+tool\s+(?:install|upgrade)\b', re.I),
  re.compile(r'\bbrew\s+(?:install|upgrade)\b', re.I),
  re.compile(r'\bnpm\s+(?:install|i|update)\b[^\n;&|]*(?:\s-g\b|--global\b)', re.I),
  re.compile(r'\bnpm\b[^\n;&|]*(?:\s-g\b|--global\b)[^\n;&|]*\b(?:install|i|update)\b', re.I),
  re.compile(r'\bcargo\s+install\b', re.I),
)


def hook_output(decision=None, reason=None, context=None):
  body = {'hookEventName': 'PreToolUse'}
  if decision:
    body['permissionDecision'] = decision
    body['permissionDecisionReason'] = reason
  if context:
    body['additionalContext'] = context
  print(json.dumps({'hookSpecificOutput': body}, ensure_ascii=False))


def regular_single_link(path):
  try:
    info = path.lstat()
  except OSError:
    return False
  return stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink()


def load_json(path):
  if not regular_single_link(path):
    raise ValueError(f'註冊檔不存在或不是單一 regular file：{path}')
  value = json.loads(path.read_text())
  if not isinstance(value, dict) or value.get('schema_version') != 1 or not isinstance(value.get('tools'), dict):
    raise ValueError('註冊檔 schema 無效')
  for name, tool in value['tools'].items():
    if not isinstance(name, str) or not name or not isinstance(tool, dict):
      raise ValueError('工具條目 schema 無效')
    aliases = tool.get('aliases')
    if not isinstance(aliases, list) or not aliases or not all(isinstance(alias, str) and alias for alias in aliases):
      raise ValueError(f'{name} aliases 必須是非空字串陣列')
    mode = tool.get('mode')
    if mode not in ('pinned', 'nudge'):
      raise ValueError(f'{name} mode 必須是 pinned 或 nudge')
    if 'hold_until' in tool:
      hold = tool['hold_until']
      if not isinstance(hold, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', hold):
        raise ValueError(f'{name} hold_until 必須是 YYYY-MM-DD')
      date.fromisoformat(hold)
    if mode == 'pinned':
      pin_type = tool.get('pin_type', 'git')
      if pin_type not in ('git', 'npm'):
        raise ValueError(f'{name} pin_type 必須是 git 或 npm')
      if pin_type == 'npm':
        for field in ('package', 'server'):
          if not isinstance(tool.get(field), str) or not tool[field]:
            raise ValueError(f'{name} {field} 必須是非空字串')
        paths = tool.get('pin_files')
        if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
          raise ValueError(f'{name} pin_files 必須是非空路徑陣列')
        continue
      for field in ('source_url', 'pin_file', 'pin_pattern'):
        if not isinstance(tool.get(field), str) or not tool[field]:
          raise ValueError(f'{name} {field} 必須是非空字串')
      pattern = re.compile(tool['pin_pattern'])
      if pattern.groups < 1:
        raise ValueError(f'{name} pin_pattern 必須有 capture group')
  return value['tools']


def is_upgrade(command):
  return any(pattern.search(command) for pattern in UPGRADE_PATTERNS)


def upgrades_all_uv_tools(command):
  return bool(re.search(r'\buv\s+tool\s+upgrade\b[^\n;&|]*\s--all\b', command, re.I))


def mentions(command, aliases):
  for alias in aliases:
    pattern = r'(?<![A-Za-z0-9_-])' + re.escape(alias) + r'(?![A-Za-z0-9_-])'
    if re.search(pattern, command, re.I):
      return True
  return False


def read_pin(tool):
  path = Path(tool['pin_file']).expanduser()
  if not regular_single_link(path):
    raise ValueError(f'釘版來源不存在或不是單一 regular file：{path}')
  match = re.search(tool['pin_pattern'], path.read_text(), re.M)
  if not match:
    raise ValueError(f'釘版來源讀不到完整 40 碼 SHA：{path}')
  value = match.group(1)
  if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}', value):
    raise ValueError(f'釘版來源讀不到完整 40 碼 SHA：{path}')
  return path, value.lower()


def verify_npm_pin(tool, command):
  package = tool['package']
  versions = set()
  for filename in tool['pin_files']:
    path = Path(filename).expanduser()
    if not regular_single_link(path):
      raise ValueError(f'釘版來源不存在或不是單一 regular file：{path}')
    config = json.loads(path.read_text())
    server = config['mcpServers'][tool['server']]
    args = server['args']
    if server.get('command') != 'npx' or not isinstance(args, list):
      raise ValueError(f'npm 釘版來源不是 npx args：{path}')
    matches = [arg for arg in args if isinstance(arg, str) and arg.startswith(package + '@')]
    if len(matches) != 1 or not re.fullmatch(re.escape(package) + r'@\d+\.\d+\.\d+', matches[0]):
      raise ValueError(f'npm 釘版來源須有唯一明確版本：{path}')
    versions.add(matches[0])
  if len(versions) != 1:
    raise ValueError('npm 釘版來源的版本不一致')
  expected = next(iter(versions))
  targets = [part for part in shlex.split(command) if part == package or part.startswith(package + '@')]
  if not targets or any(target != expected for target in targets):
    raise ValueError(f'npm 升級指令須與設定釘版一致：{expected}')


def target_sha(command, source_url):
  pattern = re.escape(source_url) + r'(?:\?rev=|@)([0-9a-fA-F]{7,40})(?![0-9a-fA-F])'
  match = re.search(pattern, command)
  return match.group(1).lower() if match else None


def main():
  try:
    payload = json.load(sys.stdin)
    if not isinstance(payload, dict) or not isinstance(payload.get('tool_input'), dict):
      raise ValueError('hook input schema 無效')
  except (ValueError, json.JSONDecodeError, TypeError):
    hook_output('deny', '[tool-upgrade-guard] 無法解析 hook input；升級 gate fail closed。')
    return 0
  command = str((payload.get('tool_input') or {}).get('command') or '')
  if SENTINEL.exists() or not is_upgrade(command):
    return 0
  try:
    tools = load_json(REGISTRY)
  except (OSError, ValueError, json.JSONDecodeError) as error:
    hook_output('deny', f'[tool-upgrade-guard] 無法讀取工具升級注意事項：{error}。修復註冊檔，或由人建立 {SENTINEL} 暫停 gate。')
    return 0
  if upgrades_all_uv_tools(command):
    pinned = [name for name, tool in tools.items() if tool['mode'] == 'pinned']
    if pinned:
      hook_output('deny', f'[tool-upgrade-guard] uv tool upgrade --all 會改到釘版工具：{", ".join(pinned)}。改成逐工具升級；釘版工具先改釘版來源，再用完整 40 碼 SHA 重裝。')
      return 0
  matched = [(name, tool) for name, tool in tools.items() if mentions(command, tool['aliases'])]
  if not matched:
    return 0
  notices = []
  for name, tool in matched:
    note = str(tool.get('report_note') or f'{name} 有升級注意事項')
    hold = tool.get('hold_until')
    if hold is not None and date.today() <= date.fromisoformat(hold):
      hook_output('deny', f'[tool-upgrade-guard] {name} 暫緩至 {hold}（含當日）：{tool.get("hold_reason", "依既有暫緩決策")}。不更動釘版或冷卻期。')
      return 0
    if tool.get('mode') != 'pinned':
      notices.append(note)
      continue
    if tool.get('pin_type') == 'npm':
      try:
        verify_npm_pin(tool, command)
      except (KeyError, OSError, ValueError, TypeError) as error:
        hook_output('deny', f'[tool-upgrade-guard] {name} 的 npm 釘版規則無法驗證：{error}。文件或 heredoc 請改用 Write／Edit 落檔。')
        return 0
      verify = str(tool.get('verify_command') or '')
      notices.append(f'{note}。安裝後執行：{verify}' if verify else note)
      continue
    try:
      pin_file, expected = read_pin(tool)
    except (KeyError, OSError, ValueError, re.error) as error:
      hook_output('deny', f'[tool-upgrade-guard] {name} 的釘版規則無法驗證：{error}。修復規則，或由人建立 {SENTINEL} 暫停 gate。')
      return 0
    target = target_sha(command, str(tool.get('source_url') or ''))
    if not target or len(target) != 40:
      hook_output('deny', f'[tool-upgrade-guard] {name} 是釘版工具；升級指令必須帶來源 URL 與完整 40 碼 SHA，且先把 {pin_file} 的 EXPECTED_COMMIT 改成同一值。現在核准 SHA：{expected}。文件或 heredoc 請改用 Write／Edit 落檔。')
      return 0
    if target != expected:
      hook_output('deny', f'[tool-upgrade-guard] {name} 目標 SHA {target} 與 {pin_file} 的 EXPECTED_COMMIT {expected} 不一致。先用 Edit 更新釘版來源，再重送同一條完整 SHA 安裝指令。')
      return 0
    verify = str(tool.get('verify_command') or '')
    notices.append(f'{note}。安裝後執行：{verify}' if verify else note)
  hook_output(context='[tool-upgrade-guard] ' + '\n'.join(notices))
  return 0


if __name__ == '__main__':
  try:
    raise SystemExit(main())
  except Exception as error:
    hook_output('deny', f'[tool-upgrade-guard] gate 內部錯誤，fail closed：{type(error).__name__}: {str(error)[:160]}')
    raise SystemExit(0)
