#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / 'hooks/pipestatus-zsh-gate.py'
SETTINGS = ROOT / 'settings.json'
PASS = 0


def check(condition, message):
  global PASS
  if not condition:
    raise AssertionError(message)
  PASS += 1
  print(f'PASS: {message}')


def run_hook(command, audit, shell='/bin/zsh'):
  env = {key: value for key, value in os.environ.items() if key != 'SHELL'}
  env['PIPESTATUS_GATE_AUDIT'] = str(audit)
  if shell is not None:
    env['SHELL'] = shell
  result = subprocess.run(
    [sys.executable, str(HOOK)],
    input=json.dumps({
      'session_id': 'pipestatus-test',
      'tool_name': 'Bash',
      'tool_input': {'command': command},
    }),
    capture_output=True,
    text=True,
    env=env,
    check=False,
  )
  check(result.returncode == 0, f'hook exits zero: {command[:40]}')
  return result.stdout.strip()


def assert_deny(output, message):
  check(bool(output), message)
  data = json.loads(output)['hookSpecificOutput']
  check(data['hookEventName'] == 'PreToolUse', f'{message} uses PreToolUse')
  check(data['permissionDecision'] == 'deny', f'{message} denies execution')
  check('PIPESTATUS' in data['permissionDecisionReason'], f'{message} names PIPESTATUS')
  check('bash' in data['permissionDecisionReason'].lower(), f'{message} gives Bash alternative')


def main():
  check(HOOK.exists(), 'PIPESTATUS gate hook exists')
  temp_root = Path(tempfile.mkdtemp(prefix='pipestatus-gate-test.'))
  try:
    audit = temp_root / 'audit.jsonl'

    bad_commands = [
      'test ${PIPESTATUS[0]} -eq 1',
      'grep -q value file | head -1; [ ${PIPESTATUS[0]} -eq 0 ]',
      'cd repo && test $PIPESTATUS -eq 0',
      'echo bash; test ${PIPESTATUS[1]} -eq 0',
      "python3 - <<PY\nprint('${PIPESTATUS[0]}')\nPY",
      "# docs <<'NOPE'\ntest ${PIPESTATUS[0]} -eq 0\nNOPE",
      "cat <<EOF\ntext <<'X'\n${PIPESTATUS[0]}\nX\nEOF",
      "cat <<A <<'B'\n${PIPESTATUS[0]}\nA\nsafe ${PIPESTATUS[0]}\nB",
      "python3 - <<'PY'\nprint('${PIPESTATUS[0]}')\nPY\ntest ${PIPESTATUS[0]} -eq 0",
    ]
    for index, command in enumerate(bad_commands):
      assert_deny(run_hook(command, audit), f'outer-shell PIPESTATUS case {index + 1}')

    good_commands = [
      'grep -q value file || true',
      "bash -lc 'grep -q value file | head -1; test ${PIPESTATUS[0]} -eq 0'",
      "/bin/bash -c 'false | true; test ${PIPESTATUS[0]} -eq 1'",
      "command bash -lc 'false | true; test ${PIPESTATUS[0]} -eq 1'",
      "bash <<'EOF'\nfalse | true\ntest ${PIPESTATUS[0]} -eq 1\nEOF",
      "python3 - <<'PY'\npayload = {'command': 'printf x | cat; echo ${PIPESTATUS[0]}'}\nPY",
    ]
    for index, command in enumerate(good_commands):
      check(run_hook(command, audit) == '', f'explicit Bash or unrelated case {index + 1} stays silent')

    audit_rows = [json.loads(line) for line in audit.read_text().splitlines()]
    check(len(audit_rows) == len(bad_commands), 'audit count matches denied commands')
    check(all(row['action'] == 'deny' for row in audit_rows), 'audit records deny action')
    check(all('command' not in row and 'command_hash' not in row for row in audit_rows), 'audit stores neither command text nor command hash')
    check(all(set(row) == {'ts', 'session', 'action', 'reason', 'shell'} for row in audit_rows), 'audit row fields are ts, session, action, reason, shell')
    check(all(row.get('shell') == '/bin/zsh' for row in audit_rows), 'audit records detected outer shell')

    bash_audit = temp_root / 'bash-audit.jsonl'
    for shell in ['/bin/bash', '/opt/homebrew/bin/bash']:
      for index, command in enumerate(bad_commands):
        check(run_hook(command, bash_audit, shell) == '', f'outer bash {shell} allows PIPESTATUS case {index + 1}')
    check(not bash_audit.exists(), 'outer bash writes no deny audit')

    boundary_audit = temp_root / 'boundary-audit.jsonl'
    for label, shell in [('unset', None), ('empty', ''), ('bash-lookalike', '/usr/local/bin/bashful'), ('sh', '/bin/sh')]:
      output = run_hook(bad_commands[0], boundary_audit, shell)
      assert_deny(output, f'undetectable outer shell ({label}) still denies')
      reason = json.loads(output)['hookSpecificOutput']['permissionDecisionReason']
      check('SHELL=' in reason, f'undetectable outer shell ({label}) reason names detected SHELL')

    zsh_reason = json.loads(run_hook(bad_commands[0], temp_root / 'zsh-reason.jsonl'))['hookSpecificOutput']['permissionDecisionReason']
    check('SHELL=/bin/zsh' in zsh_reason, 'zsh deny reason names detected SHELL value')

    settings = json.loads(SETTINGS.read_text())
    bash_hooks = [
      hook.get('command', '')
      for entry in settings['hooks']['PreToolUse']
      if entry.get('matcher') == 'Bash'
      for hook in entry.get('hooks', [])
    ]
    check(any('pipestatus-zsh-gate.py' in command for command in bash_hooks), 'settings wire PIPESTATUS gate to PreToolUse Bash')
  finally:
    shutil.rmtree(temp_root, ignore_errors=True)

  print(f'All {PASS} checks passed.')


if __name__ == '__main__':
  main()
