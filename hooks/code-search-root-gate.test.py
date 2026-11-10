#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / 'hooks/code-search-root-gate.py'


class CodeSearchRootGateTest(unittest.TestCase):
  def setUp(self):
    self.temp_root = Path(tempfile.mkdtemp(prefix='code-search-gate-test.'))
    self.audit = self.temp_root / 'audit.jsonl'
    self.untouched = self.temp_root / 'untouched.txt'
    self.untouched.write_text('keep-me', encoding='utf-8')

  def tearDown(self):
    shutil.rmtree(self.temp_root, ignore_errors=True)

  def run_hook(self, command, tool_name='Bash', extra_env=None):
    env = {
      'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
      'HOME': os.environ.get('HOME', str(self.temp_root)),
      'CODE_SEARCH_GATE_AUDIT': str(self.audit),
    }
    if extra_env:
      env.update(extra_env)
    payload = {
      'hook_event_name': 'PreToolUse',
      'session_id': 'code-search-test',
      'tool_name': tool_name,
      'tool_input': {'command': command},
    }
    res = subprocess.run(
      [sys.executable, '-I', str(HOOK)],
      input=json.dumps(payload),
      capture_output=True,
      text=True,
      env=env,
      timeout=3,
      check=False,
    )
    self.assertEqual(res.returncode, 0, res.stderr)
    self.assertEqual(self.untouched.read_text(encoding='utf-8'), 'keep-me')
    return res.stdout.strip()

  def test_known_bad_giant_root_and_bare_recursive_grep_deny(self):
    bad_cases = [
      ('giant-claude-root-no-exclude', 'command grep -rn "hy4" ~/.claude/'),
      ('giant-home-root-find', 'find ~ -name "*.jsonl"'),
      ('giant-fs-root-find', 'find / -name "oci" -type f 2>/dev/null'),
      ('giant-user-root-rg', 'rg "secret" ~/.claude'),
      ('giant-projects-subdir-grep', 'command grep -rl "skill" ~/.claude/projects/'),
      ('bare-recursive-grep', 'grep -rn "pattern" src/'),
      ('bare-recursive-grep-in-cmd-sub', 'F=$(grep -rl "pattern" src/)'),
    ]
    for label, cmd in bad_cases:
      with self.subTest(label=label):
        out = self.run_hook(cmd)
        self.assertTrue(bool(out), f'{label} should deny')
        data = json.loads(out)['hookSpecificOutput']
        self.assertEqual(data['permissionDecision'], 'deny')

  def test_known_good_and_boundary_cases_allow(self):
    good_cases = [
      ('single-file-bare-grep', 'grep -n "events" retro-store.py | head'),
      ('usr-bin-grep-recursive', '/usr/bin/grep -rn "pattern" src/'),
      ('command-grep-with-exclude', 'command grep -rn --exclude-dir={.git,projects,cache} "pattern" ~/.claude'),
      ('desktop-projects-not-blocked-for-projects-name', 'command grep -rn "Vibe coding" ~/Desktop/projects/CLAUDE.md'),
      ('shallow-find-maxdepth', 'find ~ -maxdepth 1 -name "*.md"'),
      ('specific-subdir', 'command grep -rn "lcu" ~/.claude/hooks ~/.claude/rules'),
      ('command-grep-in-var-cmd-sub', 'F=$(command grep -rl --include=*.js -E \'name: *"read"\' "$R"/)'),
      ('single-jsonl-file-grep', 'command grep -n "skill" ~/.claude/projects/-Users-x/abc.jsonl'),
      ('heredoc-body-ignored', "python3 -I - <<'PY'\n# grep -rn foo ~/.claude\nprint('ok')\nPY"),
    ]
    for label, cmd in good_cases:
      with self.subTest(label=label):
        self.assertEqual(self.run_hook(cmd), '')

  def test_self_lifecycle_and_pathological_audit_targets(self):
    self.assertEqual(
      self.run_hook('grep -rn "x" ~/.claude', extra_env={'CODE_SEARCH_GATE_DISABLE': '1'}),
      '',
    )
    self.assertEqual(self.run_hook('grep -rn "x" ~/.claude', tool_name='Read'), '')

    symlink_audit = self.temp_root / 'symlink-audit.jsonl'
    symlink_audit.symlink_to(self.untouched)
    out = self.run_hook('grep -rn "x" ~/.claude', extra_env={'CODE_SEARCH_GATE_AUDIT': str(symlink_audit)})
    self.assertTrue(bool(out))
    self.assertEqual(self.untouched.read_text(encoding='utf-8'), 'keep-me')

    fifo_audit = self.temp_root / 'fifo-audit.jsonl'
    os.mkfifo(fifo_audit)
    out_fifo = self.run_hook('grep -rn "x" ~/.claude', extra_env={'CODE_SEARCH_GATE_AUDIT': str(fifo_audit)})
    self.assertTrue(bool(out_fifo))


if __name__ == '__main__':
  unittest.main()
