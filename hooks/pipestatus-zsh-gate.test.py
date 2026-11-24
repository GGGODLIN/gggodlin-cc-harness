#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

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
      'ssh example-host "python3 -c \'import json; d={\"id\": 1}; print(f\"{d.get(\\\"id\\\")}\")\'"',
      "S=/tmp/demo; python3 -I -c '\nimport json\nrows=json.load(open(\"'$S'/demo.json\"))\nprint(f\"x={r.get(\\\"k\\\")}\")\n'",
      "S=/tmp/demo; python3 -I -Wignore -c 'p=\"'${S}'/a.json\"; print(f\"x={d[\\\"k\\\"]}\")'",
      "S=/tmp/demo; python3 -c 'p=\"'\"$S\"'/a.json\"; print(f\"x={d[\\\"k\\\"]}\")'",
      "python3 -c 'd={\"k\":1}; print('\\''v'\\'', f\"{d[\\\"k\\\"]}\")'",
      'python3 -c \'print("a\\"b"); print(\'"f\\"{\\\\\\"a\\\\\\"}\\""\')\'',
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
      "S=/tmp/demo; python3 -I -c 'rows=open(\"'$S'/demo.json\").read(); print(\"say \\\"OK\\\"\")'",
      'python3 -c \'print(\'"\'"\'hello world\'"\'"\'); print("say \\"OK\\"")\'',
      'python3 -c \'print("a\\"b")\'"; print(1)"',
      'bash -c "python3 -c \'print(1)\'" && echo "\'a \\" b\'"',
      'python3 -c \'print("a\\"b"); \'$DYNAMIC_STMT',
      'python3 -c \'print("ok")\'; echo \'a \\" b\'',
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
      'cd ~/.claude/workflows && node --test tests/daily-topic-hardening-blockers.test.mjs 2>&1 | tail -15',
      'yarn -s test:integration pending-jobs --maxWorkers=2 2>&1 | tail -25',
      'npm run -s typecheck 2>&1 | tail -5',
      'bash ~/.claude/hooks/fable-gate.test.sh | tail -n 10',
      'pytest tests/test_capture.py 2>&1 | grep -v SKIP | tail -20',
      'set +o pipefail; pytest tests/test_capture.py | tail -15',
      'claude plugin test . 2>&1 | head -n 30',
      'pnpm exec tsc --noEmit 2>&1 | tail -5; echo "tsc exit=$?"',
      'node --test tests/devin-pool-usage.test.mjs 2>&1 | command grep -E "pass|fail"',
      'node /fixture/prismantis/scripts/test.mjs 2>&1 | tail -n 15',
      'npx prettier --check src/index.ts 2>&1 | tail -1',
      'pnpm exec eslint src 2>&1 | tail -20',
      'npx stylelint "src/**/*.css" 2>&1 | head -n 20',
      'bunx biome check . 2>&1 | tail -10',
      'python3 -I session-audit.test.py 2>&1 | tail -5',
      'python3 tests/test_capture.py | head -20',
      '/opt/homebrew/bin/python3 scripts/retro_store_test.py 2>&1 | grep -E "FAIL|OK"',
      'npx -y react-doctor@latest web --no-score --json 2>&1 | tail -20',
      'herdr-app check 2>&1 | tail -3',
      # 回歸案例：變數 runner、time 前綴、大括號群組、playwright test、test-*.sh 命名。
      'PY=/opt/py/bin/python3.9; $PY -B -m unittest test_explorer test_controller 2>&1 | tail -15',
      'git rev-parse HEAD && (time npm run typecheck) 2>&1 | tail -5 && (time npm test) 2>&1 | tail -25',
      'pgrep -f "vitest|jest" >/dev/null && echo busy || { yarn test:e2e test/terms/ --maxWorkers=3 2>&1 | tail -60; }',
      'npm ci 2>&1 | tail -1 && (npx playwright test 2>&1 | tail -15)',
      'bash tests/test-skill-source.sh | tail -n 2',
      '"$PY" -m pytest -q 2>&1 | tail -20',
      '"${PY}" -m unittest discover 2>&1 | tail -5',
      'sh "tests/test-smoke.sh" | head -5',
      # 回歸案例：openspec validate、tdd-policy.mjs、pack-clean-archive.sh 接 tail。
      'cd ~/.claude && openspec validate demo-change --strict 2>&1 | tail -15; echo "validate rc=$?"',
      'MATT_TDD_ROOT=$(mktemp -d) node skills/implement/scripts/tdd-policy.mjs init --tickets "$T" 2>&1 | tail -12',
      'bash ~/.claude/skills/devin-cloud-sandbox/scripts/pack-clean-archive.sh /tmp/repo /tmp/out.tar.gz --ref abc123 2>&1 | tail -3',
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
      'set -o pipefail; npx prettier --check src/index.ts 2>&1 | tail -1',
      'set -euo pipefail && pnpm exec eslint src 2>&1 | tail -20',
      'set -o pipefail; npx stylelint "src/**/*.css" 2>&1 | head -n 20',
      'set -o pipefail; bunx biome check . 2>&1 | tail -10',
      'npx eslint src && npx stylelint "src/**/*.css" && bunx biome check .',
      'set -euo pipefail && .venv/bin/pytest tests/test_capture.py 2>&1 | tail -25',
      "bash -lc 'npx tsc --noEmit 2>&1 | tail -20; test ${PIPESTATUS[0]} -eq 0'",
      'pytest tests/test_capture.py && tail -n 20 test.log',
      'lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null | head',
      "python3 - <<'PY'\n# heredoc mentioning npx tsc --noEmit 2>&1 | tail -20\nprint('ok')\nPY",
      f'{sys.executable} {Path(__file__).resolve()}',
      'set -o pipefail; python3 -I session-audit.test.py 2>&1 | tail -5',
      'set -o pipefail; npx -y react-doctor@latest web --json 2>&1 | tail -20',
      'python3 scripts/build_index.py | tail -5',
      'python3 my_test_helper.py | tail -5',
      # 同名但不是在跑測試：安裝瀏覽器、變數指向的建置腳本、非 test 命名的檢查腳本。
      'npx playwright install chromium webkit 2>&1 | tail -3',
      'PY=/opt/py/bin/python3.9; $PY scripts/build_app.py 2>&1 | tail -5',
      'bash scripts/check-index.sh 2>&1 | tail -1',
      'set -o pipefail; (time npm test) 2>&1 | tail -25',
      '{ echo start; ls; } | tail -3',
      'bash test_smoke.sh | tail -5',
      'set -o pipefail; openspec validate demo-change --strict 2>&1 | tail -15',
      'openspec list | head -5',
      "node -p 'process.argv[1]' scripts/ui-check/check_ui.mjs | head -1",
      'node scripts/check_ui.mjs.bak | head -1',
    ]
    for index, command in enumerate(pipe_good_commands):
      check(run_hook(command, pipe_audit, '/bin/zsh') == '', f'protected or non-test pipe case {index + 1} stays silent')

    pipe_audit_rows = [json.loads(line) for line in pipe_audit.read_text().splitlines()]
    check(len(pipe_audit_rows) == len(pipe_bad_commands), 'pipe_audit count matches denied test pipe commands')
    check(all(row['reason'] == 'unprotected-test-pipe-tail-head' for row in pipe_audit_rows), 'pipe_audit records test-pipe reason')

    mask_audit = temp_root / 'mask-audit.jsonl'
    mask_bad_commands = [
      'set -o pipefail; python3 -m unittest discover -s tests 2>&1 | tail -6; ls -la',
      'npx prettier --check docs/guide.md; echo "prettier exit=$?"',
      'pytest tests/test_capture.py; true',
      'npm test 2>&1; printf "done\\n"',
      'set -o pipefail; cd ~/.claude && python3 -m pytest -q scripts/test_semble_docs_retirement.py 2>&1 | tail -3; echo "pytest exit=$?"; bash hooks/config-dir-symlink-check.test.sh 2>&1 | tail -2; echo "symlink test exit=$?"',
      'npx jest tests/api.test.ts > receipt.txt 2>&1; cat receipt.txt',
      'set -o pipefail; pnpm vitest run 2>&1 | tail -30; npx eslint src && npx prettier --check src',
      'set -o pipefail; pnpm exec tsc --noEmit | tail -5; pnpm exec eslint src',
      'python3 -I session-retro.test.py; echo "exit=$?"',
      'herdr-app check; echo done',
      'set -e; pytest tests/test_capture.py || true; echo done',
      'cd repo; set -e; pytest -q; echo done',
      # 回歸案例：else 分支、換行分隔（失敗後仍往下執行）、尾接指令後還有下一行。
      'if pgrep -f jest >/dev/null; then echo busy; else NODE_ENV=test npx jest src/a.spec.ts > ../run.log 2>&1; echo "rc=$?"; fi',
      '.venv/bin/pytest tests -v\necho "=== GREP VERIFY ==="\ncommand grep -rn PATTERN src || echo none',
      'python3 tests/seat-harness.test.py\necho "---"\ngit status --short',
      'pytest -q; echo done\ngit status --short',
      # 前一段豁免後，被當成 mask 的那一行本身是下一段檢查。
      'pytest -q || exit $?\nnpx prettier --check .\necho done',
      # 回歸案例：check_ui.mjs 與 python3 -I -W ignore / -Wignore session-retro.py validate 尾接 echo。
      'node ~/.claude/scripts/ui-check/check_ui.mjs http://localhost:4333/tier/ --out /tmp/out ; echo "EXIT=$?"',
      'python3 -I -W ignore scripts/local-analysis/session-retro.py validate --plan /tmp/plan.json --stage verify ; echo "exit=$?"',
      'python3 -I -Wignore "scripts/local-analysis/session-retro.py" validate --plan /tmp/plan.json --stage verify ; echo "exit=$?"',
    ]
    for index, command in enumerate(mask_bad_commands):
      out = run_hook(command, mask_audit, '/bin/zsh')
      check(bool(out), f'trailing status mask case {index + 1} denies')
      data = json.loads(out)['hookSpecificOutput']
      check(data['permissionDecision'] == 'deny', f'trailing status mask case {index + 1} decision is deny')
      check('退出碼覆蓋為 0' in data['permissionDecisionReason'], f'trailing status mask case {index + 1} explains exit code masking')
      check('Write/Edit' in data['permissionDecisionReason'], f'trailing status mask case {index + 1} names fallback')

    mask_good_commands = [
      'set -o pipefail; python3 -m unittest discover -s tests 2>&1 | tail -6 && ls -la',
      'pytest tests/test_capture.py; rc=$?; ls -la; exit $rc',
      "bash -lc 'npx tsc --noEmit 2>&1 | tail -20; test ${PIPESTATUS[0]} -eq 0'",
      'npx prettier --check docs/guide.md',
      "python3 - <<'PY'\n# heredoc mentioning pytest tests/test_capture.py; ls -la\nprint('ok')\nPY",
      f'{sys.executable} {HOOK} < /dev/null',
      'set -o pipefail; pnpm vitest run | tail -30 && npx eslint src && npx prettier --check src',
      'pnpm exec tsc --noEmit; rc=$?; pnpm exec eslint src; exit $rc',
      'node scripts/test.mjs > test.log 2>&1; rc=$?; cat test.log; exit $rc',
      'set -e; pytest tests/test_capture.py; echo done',
      'set -euo pipefail; python3 -m unittest discover -s tests 2>&1 | tail -6; ls -la',
      'set -o errexit\nnpm test; printf "done\\n"',
      # 換行但失敗走不到下一行：已接 `|| exit`、行尾 `&&`、頂層 set -e、先存退出碼。
      'pytest -q || exit $?\necho done',
      'pytest -q &&\necho done',
      'set -e\npytest -q\necho done',
      'pytest -q\nrc=$?\necho "rc=$rc"\nexit $rc',
      'set -e\npytest -q\ncat test.log || echo "no log"',
      '# smoke tests\nset -e\npytest -q\necho done',
      'pytest -q && # only print on success\necho done',
      'node ~/.claude/scripts/ui-check/check_ui.mjs http://localhost:4333/tier/ --out /tmp/out && echo "ok"',
      'python3 -I -W ignore scripts/local-analysis/session-retro.py inventory --out /tmp/inv ; echo "done"',
    ]
    for index, command in enumerate(mask_good_commands):
      check(run_hook(command, mask_audit, '/bin/zsh') == '', f'non-masking trailing command case {index + 1} stays silent')

    mask_audit_rows = [json.loads(line) for line in mask_audit.read_text().splitlines()]
    check(len(mask_audit_rows) == len(mask_bad_commands), 'mask_audit count matches denied trailing-mask commands')
    check(all(row['reason'] == 'trailing-command-masks-test-exit' for row in mask_audit_rows), 'mask_audit records trailing-mask reason')

    ortrue_audit = temp_root / 'ortrue-audit.jsonl'
    ortrue_bad_commands = [
      '(claude plugin test . > out.txt 2>&1 || true) && python3 parse_results.py',
      'pytest tests/ || true',
      'npm test || :',
      'npx vitest run 2>&1 || true',
      'pytest -q ||\ntrue',
      'if [ -f report.txt ]; then cat report.txt; else pytest -q || true; fi',
    ]
    for index, command in enumerate(ortrue_bad_commands):
      out = run_hook(command, ortrue_audit, '/bin/zsh')
      check(bool(out), f'test or-true swallow case {index + 1} denies')
      data = json.loads(out)['hookSpecificOutput']
      check(data['permissionDecision'] == 'deny', f'test or-true swallow case {index + 1} decision is deny')
      check('|| true' in data['permissionDecisionReason'], f'test or-true swallow case {index + 1} names || true')
      check('Write/Edit' in data['permissionDecisionReason'], f'test or-true swallow case {index + 1} names fallback')

    # 管線末端才容錯的診斷寫法、非測試命令與保存退出碼的寫法皆放行。
    ortrue_good_commands = [
      "set -o pipefail; claude plugin test . 2>&1 | command grep -E '(fail)' || true",
      'grep -q value file || true',
      'pytest tests/; rc=$?; exit $rc',
      'pytest tests/ || exit 1',
      'pytest -q || true-fallback',
      'npx prettier --write src || true',
      'npm run build || true',
      'bash ~/.claude/skills/devin-cloud-sandbox/scripts/pack-clean-archive.sh /tmp/repo /tmp/out.tar.gz --ref abc123 || true',
    ]
    for index, command in enumerate(ortrue_good_commands):
      check(run_hook(command, ortrue_audit, '/bin/zsh') == '', f'non-swallowing or-true case {index + 1} stays silent')

    ortrue_audit_rows = [json.loads(line) for line in ortrue_audit.read_text().splitlines()]
    check(len(ortrue_audit_rows) == len(ortrue_bad_commands), 'ortrue_audit count matches denied or-true commands')
    check(all(row['reason'] == 'test-or-true-swallow' for row in ortrue_audit_rows), 'ortrue_audit records or-true reason')

    timeout_audit = temp_root / 'timeout-audit.jsonl'
    piped_timeout = "printf 'x\\n' | timeout 60 ./bin/worker --text-only 2>&1 | cut -c1-300 | head -5"
    os.environ['PIPESTATUS_TIMEOUT_PATH'] = '/nonexistent'
    try:
      out_timeout = run_hook('timeout 15 python3 probe.py', timeout_audit, '/bin/bash')
      check(bool(out_timeout), 'missing gnu timeout denies when timeout not in PATH')
      timeout_data = json.loads(out_timeout)['hookSpecificOutput']
      check(timeout_data['permissionDecision'] == 'deny', 'missing gnu timeout decision is deny')
      check('轉入背景繼續執行' in timeout_data['permissionDecisionReason'], 'missing gnu timeout explains foreground vs process kill difference')
      out_piped = run_hook(piped_timeout, timeout_audit, '/bin/bash')
      check(bool(out_piped), 'missing gnu timeout after a single pipe denies')
      check('timeout' in json.loads(out_piped)['hookSpecificOutput']['permissionDecisionReason'], 'piped timeout reason names timeout')
    finally:
      os.environ.pop('PIPESTATUS_TIMEOUT_PATH', None)
    fake_bin = temp_root / 'fake-bin'
    fake_bin.mkdir()
    fake_timeout = fake_bin / 'timeout'
    fake_timeout.write_text('#!/bin/sh\nexit 0\n')
    fake_timeout.chmod(0o755)
    os.environ['PIPESTATUS_TIMEOUT_PATH'] = str(fake_bin)
    try:
      check(run_hook(piped_timeout, timeout_audit, '/bin/bash') == '', 'piped timeout stays silent when timeout is on PATH')
    finally:
      os.environ.pop('PIPESTATUS_TIMEOUT_PATH', None)

    # 效能回歸案例：重疊的 regex 分支讓這幾種長指令讓 hook 卡超過 3 秒；每次 Bash 呼叫都會等這支 hook。
    slow_audit = temp_root / 'slow-audit.jsonl'
    long_inputs = [
      'time env ' + ' '.join(f'FLAG_{i}="on"' for i in range(22)) + ' printf ok\n:',
      'time pytest -q' + ' | cat' * 22 + '\n:',
      'pytest -q' + ' | cat' * 22 + '\n:',
      'env ' + ' '.join(f'FLAG_{i}="on"' for i in range(22)) + ' printf ok | timeout_wrapper\n:',
      'python3 -W ' * 60 + 'ignore -c "pass"',
      "python3 -c ''${ " * 60,
    ]
    for index, command in enumerate(long_inputs):
      started = time.monotonic()
      run_hook(command, slow_audit, '/bin/zsh')
      check(time.monotonic() - started < 2.0, f'long input case {index + 1} returns within 2 seconds')

    # 回歸案例：npm --prefix test、bash wrapper node --test、pnpm install 與 e2e runner 接 pipe。
    retro20_audit = temp_root / 'retro20-audit.jsonl'
    for idx, bad_cmd in enumerate([
      'npm --prefix /tmp/wt-demo test 2>&1 | tail -n 30 || true',
      "bash /tmp/stryker-demo/run-node.sh node --test --test-reporter=tap scripts/readme.test.mjs | grep -E '^(ok|not ok)'",
      'pnpm install --frozen-lockfile 2>&1 | tail -15',
      'node /tmp/scratch/run-sample-e2e.cjs /tmp/e2e.log | tail -1',
      'node scripts/e2e-smoke.mjs 2>&1 | tail -n 25',
      'node e2e.mjs | head -n 10',
      'yarn --cwd /tmp/app test | head -n 20',
      'npm --prefix=/tmp/wt-demo test || true',
    ], 1):
      out = run_hook(bad_cmd, retro20_audit, '/bin/bash')
      check(out != '', f'retro20 known-bad case {idx} denies')
      if out:
        payload = json.loads(out)
        check(payload['hookSpecificOutput']['permissionDecision'] == 'deny', f'retro20 known-bad case {idx} decision is deny')

    for idx, good_cmd in enumerate([
      'set -o pipefail; npm --prefix /tmp/wt-demo test 2>&1 | tail -n 30',
      "set -o pipefail; bash /tmp/stryker-demo/run-node.sh node --test scripts/readme.test.mjs | grep -E '^(ok|not ok)'",
      'set -o pipefail; pnpm install --frozen-lockfile 2>&1 | tail -15',
      'bash ~/.claude/scripts/x-search.sh "query" 2>&1 | head -n 50',
      'pnpm install --frozen-lockfile || true',
      'node scripts/print-summary.cjs | tail -n 5',
      'node scripts/free2edit.mjs | tail -n 5',
    ], 1):
      check(run_hook(good_cmd, retro20_audit, '/bin/bash') == '', f'retro20 known-good case {idx} stays silent')

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
