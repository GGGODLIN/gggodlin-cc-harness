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
      ('rg-files-no-pattern-giant-root', 'rg --files ~/.claude'),
      ('explicit-e-flag-giant-root', 'command grep -rn -e "alpha" -e "beta" ~/.claude'),
      ('giant-pattern-and-giant-target', 'command grep -rn "~" ~/.claude'),
      ('rg-literal-equals-giant-root', 'rg = ~/.claude'),
      ('bare-recursive-grep', 'grep -rn "pattern" src/'),
      ('bare-recursive-grep-in-cmd-sub', 'F=$(grep -rl "pattern" src/)'),
      (
        'py-heredoc-glob-projects',
        "python3 - <<'PY'\nimport glob, os\nfiles = glob.glob(os.path.expanduser('~/.claude/projects/**/*.jsonl'), recursive=True)\nprint(len(files))\nPY",
      ),
      (
        'py-dash-c-glob-projects',
        'python3 -c "import glob; print(glob.glob(\'~/.claude/projects/-Users-x/*.jsonl\'))"',
      ),
      (
        'py-heredoc-pathlib-root-glob-projects',
        "python3 -I - <<'PY'\nimport pathlib\nroot = pathlib.Path.home() / '.claude/projects/-Users-you-Desktop-projects'\nprint(list(root.glob('*.jsonl')))\nPY",
      ),
      (
        'py-heredoc-split-segments-rglob-projects',
        "python3 - <<'PY'\nfrom pathlib import Path\nroot = Path.home() / '.claude' / 'projects'\nfor p in root.rglob('*.jsonl'):\n  print(p)\nPY",
      ),
      (
        'py-dash-c-os-walk-projects',
        'python3 -c "import os; print(list(os.walk(os.path.expanduser(\'~/.claude/projects\'))))"',
      ),
      (
        'py-dash-c-os-listdir-projects',
        'python3 -c "import os; print(os.listdir(\'~/.claude/projects/-Users-x\'))"',
      ),
      (
        'chained-cd-py-heredoc-glob-projects',
        "cd /tmp && python3 - <<'PY'\nimport glob\nprint(glob.glob('~/.claude/projects/*.jsonl'))\nPY",
      ),
      (
        'uv-run-py-dash-c-glob-projects',
        'uv run python -c "import glob, os; print(glob.glob(os.path.expanduser(\'~/.claude/projects/**/*.jsonl\'), recursive=True))"',
      ),
      (
        'bash-dash-c-find-projects',
        'bash -c \'find ~/.claude/projects -name "*.jsonl"\'',
      ),
      (
        'bash-euo-pipefail-dash-c-grep',
        'bash -euo pipefail -c "grep -rn foo src/"',
      ),
      (
        'bash-heredoc-single-quoted-find-projects',
        "bash <<'EOF'\nfind ~/.claude/projects -name '*.jsonl'\nEOF",
      ),
      (
        'bash-dash-c-wrapping-py-glob-projects',
        'bash -c "python3 -c \'import glob, os; print(glob.glob(os.path.expanduser(\\\"~/.claude/projects/*.jsonl\\\")))\'"',
      ),
      (
        'leading-py-does-not-exempt-chained-bare-grep',
        "python3 -c 'print(1)' && grep -rn 'pattern' src/",
      ),
      # 2026-11-21 Level-1 重驗補洞：cd + .、~/.claude*/projects 萬用字元、for 迴圈與 Python 遞迴掃 ~/.claude 根目錄
      (
        'cd-projects-then-command-grep-dot',
        "cd ~/.claude/projects && command grep -l -F '$15' -r --include=*.jsonl .",
      ),
      (
        'find-claude-wildcard-projects',
        "find ~/.claude*/projects -name '*.jsonl' -mtime -30 -print0",
      ),
      (
        'for-loop-claude-projects-command-grep',
        'for d in ~/.claude/projects ~/.claude-team-*/projects; do command grep -rl foo "$d"; done',
      ),
      (
        'py-dash-c-rglob-claude-root',
        'python3 -c "from pathlib import Path; list(Path(\'~/.claude\').expanduser().rglob(\'relay-provider.mjs\'))"',
      ),
      # 2026-11-24 放行 `ast.walk` 後的邊界：真正的 `os.walk` 照擋；以裸名或別名呼叫的 walk 認不出來源，照舊擋。
      (
        'py-os-walk-claude-root-still-deny',
        'python3 -c "import os; print(list(os.walk(os.path.expanduser(\'~/.claude\'))))"',
      ),
      (
        'py-bare-walk-from-ast-import-still-deny',
        'python3 -c "from ast import walk, parse; root = \'~/.claude\'; print(len(list(walk(parse(\'x = 1\')))))"',
      ),
      # 回歸案例：command grep 無排除掃 ~/.claude/。
      (
        'recurrence-multi-root-command-grep-with-claude',
        'type -a custom-cli-alias 2>&1 || true\ncommand grep -rn \'custom-cli-alias\' ~/.zshrc ~/.zprofile ~/.local/bin/ ~/.claude/ 2>&1 | head -n 15 || true\necho "=== Inspect fixture jsonl error entries ==="\ntail -n 6 ~/.claude-alt/projects/-tmp-fixture-worktree/11111111-2222-3333-4444-555555555555.jsonl | python3 -c \'\nimport sys, json\nfor line in sys.stdin:\n    d = json.loads(line)\n    print(d.get("type"), d.get("timestamp"), d.get("isApiErrorMessage"), str(d.get("message",{}).get("model")), str(d.get("message",{}).get("content"))[:160])\n\'',
      ),
      (
        'recurrence-scratch-and-claude-command-grep',
        'command grep -rn "SampleProject" ~/Desktop/projects/.scratch/ ~/.claude/ 2>/dev/null | grep -E "2026-11-22|digest|SampleProject" | head -n 20 || true',
      ),      # 回歸案例：glob 樣式自帶 `.claude/**`，接收者是家目錄。
      (
        'py-heredoc-home-glob-claude-recursive-pattern',
        "python3 - <<'PY'\nimport pathlib\nprint(list(pathlib.Path.home().glob('.claude/**/ccsi*.db')))\nPY",
      ),
      (
        'py-dash-c-home-glob-claude-variant-recursive-pattern',
        'python3 -c "import pathlib; list(pathlib.Path.home().glob(\'.claude-alt/**/*.db\'))"',
      ),      (
        'py-glob-expanduser-claude-recursive',
        'python3 -c "import glob, os; glob.glob(os.path.expanduser(\'~/.claude/**/*.db\'), recursive=True)"',
      ),
      (
        'py-glob-fstring-home-claude-recursive',
        "python3 - <<'PY'\nimport glob, os\nhome = os.path.expanduser('~')\nprint(glob.glob(f'{home}/.claude/**/*.db', recursive=True))\nPY",
      ),
      (
        'py-home-glob-pattern-keyword',
        'python3 -c "import pathlib; list(pathlib.Path.home().glob(pattern=\'.claude/**/ccsi*.db\'))"',
      ),
      (
        'py-home-glob-claude-star-wildcard',
        'python3 -c "import pathlib; list(pathlib.Path.home().glob(\'.claude*/**/*.db\'))"',
      ),      (
        'py-cd-home-relative-path-glob',
        'cd ~ && python3 -c "import pathlib; list(pathlib.Path(\'.\').glob(\'.claude/**/*.db\'))"',
      ),
      (
        'py-cd-home-heredoc-module-glob-recursive',
        "cd ~ && python3 - <<'PY'\nimport glob\nprint(glob.glob('.claude/**/*.db', recursive=True))\nPY",
      ),
    ]
    for label, cmd in bad_cases:
      with self.subTest(label=label):
        out = self.run_hook(cmd)
        self.assertTrue(bool(out), f'{label} should deny')
        data = json.loads(out)['hookSpecificOutput']
        self.assertEqual(data['permissionDecision'], 'deny')

    projects_out = json.loads(
      self.run_hook('find ~/.claude/projects -name "*.jsonl"')
    )['hookSpecificOutput']['permissionDecisionReason']
    self.assertIn('ccsi search', projects_out)
    self.assertIn('ccsi events', projects_out)
    self.assertIn('-maxdepth 2', projects_out)
    self.assertIn('-name subagents -prune', projects_out)

    py_projects_out = json.loads(
      self.run_hook("python3 - <<'PY'\nimport glob\nglob.glob('~/.claude/projects/**/*.jsonl', recursive=True)\nPY")
    )['hookSpecificOutput']['permissionDecisionReason']
    self.assertIn('ccsi search', py_projects_out)
    self.assertIn('ccsi events', py_projects_out)

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
      # 2026-11-14 trial-review 反向斷言：audit #80 grep pattern 含 /Users/<u > 但目標為具體小目錄
      (
        'grep-pattern-is-home-path-on-small-target',
        'command grep -rn "~" ~/code/.worktrees/claude-x/workflows/tests/daily-topic.mjs',
      ),
      (
        'grep-context-flag-before-home-pattern',
        'command grep -rn -C 2 "~" ~/.claude/hooks',
      ),
      # 2026-11-14 trial-review 反向斷言：audit #49 遠端雙引號 heredoc 內 Python 變數 ag = ... + "/"
      (
        'embedded-python-ag-assignment-not-search-tool',
        'ssh remote-host \'/usr/bin/python3 -I - << "PY"\nag = str(r.get("agent")) + "/" + str(r.get("protocol"))\nPY\'',
      ),
      # 2026-11-14 M11 反向斷言：內嵌 Python 讀取已知單一 .jsonl 檔案放行，且串接 cd && python3 變數賦值不誤判
      (
        'py-heredoc-single-jsonl-file-open-allow',
        "python3 - <<'PY'\nimport json\npath = '~/.claude/projects/-Users-you-code-social-info/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jsonl'\nwith open(path) as f:\n  print(sum(1 for _ in f))\nPY",
      ),
      (
        'py-dash-c-single-jsonl-pathlib-allow',
        "python3 -c \"from pathlib import Path; p = Path.home() / '.claude/projects/-Users-x/11111111-1111-1111-1111-111111111111.jsonl'; print(p.exists())\"",
      ),
      (
        'py-heredoc-single-jsonl-plus-unrelated-tmp-glob-allow',
        "python3 - <<'PY'\nimport glob\nf = '~/.claude/projects/-Users-x/11111111-1111-1111-1111-111111111111.jsonl'\nprint(f, glob.glob('/tmp/scratch/*.json'))\nPY",
      ),
      (
        'py-heredoc-string-literal-mentioning-glob-not-called-allow',
        "python3 - <<'PY'\ns = 'glob.glob(\"~/.claude/projects/**/*.jsonl\")'\nprint(len(s))\nPY",
      ),
      (
        'chained-cd-py-dash-c-ag-assignment-allow',
        'cd /tmp && python3 -c \'ag = str(1) + "/"\'',
      ),
      (
        'chained-cd-py-dash-c-multiline-giant-root-assignment-allow',
        'cd /tmp && python3 -c \'\nag = "/"\nrg = "~"\nprint(ag, rg)\n\'',
      ),
      (
        'chained-cd-py-heredoc-ag-assignment-allow',
        "cd /tmp && python3 - <<'PY'\nag = str(1) + '/'\nprint(ag)\nPY",
      ),
      (
        'inert-cat-single-quoted-heredoc-allow',
        "cat > /tmp/doc.md <<'EOF'\npython3 -c 'import glob; glob.glob(\"~/.claude/projects/*.jsonl\")'\ngrep -rn foo ~/.claude\nEOF",
      ),
      (
        'bash-script-file-not-dash-c-allow',
        'bash scripts/vpn-precheck.test.sh',
      ),
      # 2026-11-21 Level-1 重驗正對照：具體子目錄 cd/for/rglob 與 ~/.claude 淺層 iterdir 皆應放行
      (
        'cd-hooks-subdir-command-grep-dot-allow',
        'cd ~/.claude/hooks && command grep -rn "extract_search_targets" .',
      ),
      (
        'for-loop-hooks-rules-command-grep-allow',
        'for d in ~/.claude/hooks ~/.claude/rules; do command grep -rl "ccsi" "$d"; done',
      ),
      (
        'py-rglob-hooks-subdir-allow',
        'python3 -c "from pathlib import Path; list(Path(\'~/.claude/hooks\').expanduser().rglob(\'*.py\'))"',
      ),
      (
        'py-project-receiver-claude-recursive-allow',
        'python3 -c "import pathlib; list(pathlib.Path(\'~/Desktop/projects/my-repo\').glob(\'.claude/**/*.md\'))"',
      ),
      (
        'py-fstring-project-claude-recursive-allow',
        'python3 -c "import glob; repo=\'/x/r\'; glob.glob(f\'{repo}/.claude/**/*.md\', recursive=True)"',
      ),
      (
        'py-project-cwd-relative-glob-allow',
        'cd ~/Desktop/projects/my-repo && python3 -c "import glob; glob.glob(\'.claude/**/*.md\', recursive=True)"',
      ),
      (
        'py-module-glob-non-recursive-allow',
        'python3 -c "import glob; print(glob.glob(\'.claude/**/*.md\'))"',
      ),
      (
        'py-home-glob-claude-subdir-recursive-allow',
        'python3 -c "import pathlib; list(pathlib.Path.home().glob(\'.claude/hooks/**/*.py\'))"',
      ),
      (
        'py-home-glob-claude-shallow-allow',
        'python3 -c "import pathlib; list(pathlib.Path.home().glob(\'.claude/*.json\'))"',
      ),
      (
        'py-shallow-iterdir-claude-root-allow',
        'python3 -c "from pathlib import Path; list(Path(\'~/.claude\').expanduser().iterdir())"',
      ),
      # 2026-11-24 retro 第 7 步：`ast.walk` 走語法樹不碰檔案系統；11-21 版把它當目錄遞迴，審計 682 誤擋同形指令。
      (
        'py-ast-walk-git-show-claude-repo-allow',
        "python3 - <<'PY'\nimport ast, subprocess\nsrc = subprocess.check_output(['git', '-C', '~/.claude', 'show', 'HEAD:hooks/code-search-root-gate.py'], text=True)\nprint(sum(1 for n in ast.walk(ast.parse(src))))\nPY",
      ),
      (
        'py-ast-walk-claude-root-string-allow',
        'python3 -c "import ast; root = \'~/.claude\'; print(len(list(ast.walk(ast.parse(\'x = 1\')))))"',
      ),
      # 自身生命週期 update 路徑：執行本測試與搜 hooks 子目錄放行
      ('self-update-test-run', 'python3 ~/.claude/hooks/code-search-root-gate.test.py'),
      ('self-update-syntax-check-self', 'python3 -m py_compile ~/.claude/hooks/code-search-root-gate.py'),
      ('self-update-hooks-grep', 'command grep -rn "extract_search_targets" ~/.claude/hooks/'),
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

    hardlink_audit = self.temp_root / 'hardlink-audit.jsonl'
    os.link(self.untouched, hardlink_audit)
    out_hardlink = self.run_hook(
      'grep -rn "x" ~/.claude',
      extra_env={'CODE_SEARCH_GATE_AUDIT': str(hardlink_audit)},
    )
    self.assertTrue(bool(out_hardlink))
    self.assertEqual(self.untouched.read_text(encoding='utf-8'), 'keep-me')

    fifo_audit = self.temp_root / 'fifo-audit.jsonl'
    os.mkfifo(fifo_audit)
    out_fifo = self.run_hook('grep -rn "x" ~/.claude', extra_env={'CODE_SEARCH_GATE_AUDIT': str(fifo_audit)})
    self.assertTrue(bool(out_fifo))


if __name__ == '__main__':
  unittest.main()
