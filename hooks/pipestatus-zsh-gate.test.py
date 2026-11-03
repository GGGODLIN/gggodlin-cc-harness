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

    py_audit = temp_root / 'py-audit.jsonl'
    py_bad_commands = [
      'python3 -c \'import json; d={"id": 1}; print(f"{d.get(\\"id\\")}")\'',
      'python3 -I -c \'d={"k": "v"}; print(f"val={d[\\"k\\"]}")\'',
      'cd /tmp && /usr/bin/python3.14 -u -c \'print(f"{\\"a\\"}")\'',
    ]
    for index, command in enumerate(py_bad_commands):
      for shell in ['/bin/zsh', '/bin/bash']:
        out = run_hook(command, py_audit, shell)
        check(bool(out), f'python -c escaped quote SyntaxError case {index + 1} ({shell}) denies')
        data = json.loads(out)['hookSpecificOutput']
        check(data['permissionDecision'] == 'deny', f'python -c case {index + 1} ({shell}) decision is deny')
        check('SyntaxError' in data['permissionDecisionReason'], f'python -c case {index + 1} ({shell}) names SyntaxError')
        check("<<'PY'" in data['permissionDecisionReason'], f'python -c case {index + 1} ({shell}) suggests heredoc')
        check('-I - <<' not in data['permissionDecisionReason'], f'python -c case {index + 1} ({shell}) does not force -I')

    py_good_commands = [
      'python3 -c \'print("hello \\"world\\"")\'',
      'python3 -I -c \'import json; d={"id": 1}; print(f"{d.get(\'id\' if False else \\"x\\" if False else 1)}")\'' if False else 'python3 -I -c \'import json; d={"id": 1}; print(f"{d.get(\\"id\\")}" if False else "ok")\'',
      'python3 -c \'d={"id": 1}; print(f"{d.get("id")}")\'',
      "python3 - <<'PY'\npython3 -c 'print(f\"{\\\"id\\\"}\")'\nPY",
      f'{sys.executable} {HOOK} < /dev/null',
    ]
    # Remove any syntactically invalid command from py_good_commands and test true good ones
    py_good_commands = [
      'python3 -c \'print("hello \\"world\\"")\'',
      'python3 -I -c \'d={"id": 1}; print(f"{d.get(\\"id\\" if False else "id")}")\'' if False else 'python3 -I -c \'d={"id": 1}; print(d.get("id"), "\\\"")\'',
      'python3 -c \'d={"id": 1}; print(f"{d.get("id")}")\'',
      "python3 - <<'PY'\n# heredoc body mentioning python3 -c 'print(f\"{\\\"id\\\"}\")'\nprint('ok')\nPY",
      f'{sys.executable} {HOOK} < /dev/null',
    ]
    for index, command in enumerate(py_good_commands):
      check(run_hook(command, py_audit, '/bin/zsh') == '', f'valid python -c or heredoc case {index + 1} stays silent')

    py_audit_rows = [json.loads(line) for line in py_audit.read_text().splitlines()]
    check(len(py_audit_rows) == len(py_bad_commands) * 2, 'py_audit count matches denied python -c commands')
    check(all(row['reason'] == 'python-c-escaped-quote-syntax-error' for row in py_audit_rows), 'py_audit records python-c reason')

    pipe_audit = temp_root / 'pipe-audit.jsonl'
    pipe_bad_commands = [
      'npx tsc --noEmit 2>&1 | tail -20',
      '.venv/bin/pytest tests/test_capture.py 2>&1 | tail -25',
      'PYTHONPATH=tests /opt/homebrew/bin/python3 -m unittest discover -s tests 2>&1 | tail -20',
      'cd /tmp/relay-kit && npm ci --ignore-scripts 2>&1 | tail -2 && npm run build 2>&1 | tail -3',
      'uv run pytest -q | head -n 30',
    ]
    for index, command in enumerate(pipe_bad_commands):
      out = run_hook(command, pipe_audit, '/bin/zsh')
      check(bool(out), f'unprotected test pipe case {index + 1} denies')
      data = json.loads(out)['hookSpecificOutput']
      check(data['permissionDecision'] == 'deny', f'unprotected test pipe case {index + 1} decision is deny')
      check('pipefail' in data['permissionDecisionReason'], f'unprotected test pipe case {index + 1} names pipefail')
      check('Write/Edit' in data['permissionDecisionReason'], f'unprotected test pipe case {index + 1} names fallback')

    pipe_good_commands = [
      'set -o pipefail; npx tsc --noEmit 2>&1 | tail -20',
      'set -euo pipefail && .venv/bin/pytest tests/test_capture.py 2>&1 | tail -25',
      "bash -lc 'npx tsc --noEmit 2>&1 | tail -20; test ${PIPESTATUS[0]} -eq 0'",
      'pytest tests/test_capture.py && tail -n 20 test.log',
      'lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | head',
      "python3 - <<'PY'\n# heredoc mentioning npx tsc --noEmit 2>&1 | tail -20\nprint('ok')\nPY",
      f'{sys.executable} {Path(__file__).resolve()}',
    ]
    for index, command in enumerate(pipe_good_commands):
      check(run_hook(command, pipe_audit, '/bin/zsh') == '', f'protected or non-test pipe case {index + 1} stays silent')

    pipe_audit_rows = [json.loads(line) for line in pipe_audit.read_text().splitlines()]
    check(len(pipe_audit_rows) == len(pipe_bad_commands), 'pipe_audit count matches denied test pipe commands')
    check(all(row['reason'] == 'unprotected-test-pipe-tail-head' for row in pipe_audit_rows), 'pipe_audit records test-pipe reason')

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
