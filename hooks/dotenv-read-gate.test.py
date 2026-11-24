#!/usr/bin/env python3
"""dotenv-read-gate.py 的四件套（known-good / known-bad / boundary / lifecycle + error branch）回歸測試。"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parent / 'dotenv-read-gate.py'


def run_gate(payload, env_extra=None):
  env = os.environ.copy()
  env.pop('DOTENV_READ_GATE_OFF', None)
  raw_in = payload if isinstance(payload, str) else json.dumps(payload)
  with tempfile.TemporaryDirectory() as temp:
    env['DOTENV_READ_GATE_SENTINEL'] = str(Path(temp) / 'sentinel')
    env['DOTENV_READ_GATE_AUDIT'] = str(Path(temp) / 'audit.jsonl')
    if env_extra:
      env.update(env_extra)
    proc = subprocess.run(
      ['/usr/bin/python3' if os.path.exists('/usr/bin/python3') else sys.executable, '-I', str(GATE)],
      input=raw_in,
      text=True,
      capture_output=True,
      env=env,
      timeout=10,
    )
  assert proc.returncode == 0, f'exit {proc.returncode}: {proc.stderr}'
  out = proc.stdout.strip()
  return json.loads(out) if out else None


class DotenvReadGateTest(unittest.TestCase):
  def assertAllowed(self, payload, env_extra=None):
    res = run_gate(payload, env_extra=env_extra)
    self.assertIsNone(res, f'Expected ALLOW (None), got: {res}')

  def assertDenied(self, payload, env_extra=None):
    res = run_gate(payload, env_extra=env_extra)
    self.assertIsNotNone(res, 'Expected DENY, got ALLOW (None)')
    decision = res.get('hookSpecificOutput', {}).get('permissionDecision')
    self.assertEqual(decision, 'deny', f'Expected deny, got: {res}')
    return res['hookSpecificOutput'].get('permissionDecisionReason', '')

  def test_1_known_good(self):
    # 安全範本檔與一般程式碼 Read 放行
    self.assertAllowed({'tool_name': 'Read', 'tool_input': {'file_path': '/Users/test/app/.env.example'}})
    self.assertAllowed({'tool_name': 'Read', 'tool_input': {'file_path': '/Users/test/app/.dev.env.template'}})
    self.assertAllowed({'tool_name': 'Read', 'tool_input': {'file_path': '/Users/test/app/src/config.ts'}})
    # Bash 只印欄位名（cut -d= -f1）及後續安全格式化管線放行
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': 'command grep -E "^[A-Za-z_][A-Za-z0-9_]*=" /app/.dev.env | cut -d= -f1'},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': 'command grep -E "^[A-Za-z_][A-Za-z0-9_]*=" /app/.env.local | cut -d= -f1 | tr \'\\n\' \' \''},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': 'command grep -E "^[A-Za-z_][A-Za-z0-9_]*=" /app/.dev.env | cut -d= -f1 | grep MONGO | wc -l'},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': "command grep -oE '^[A-Z_]+=' /app/.env.local | tr '\\n' ' '"},
    })
    # grep -c / grep -l 純計數或列檔名放行
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': "grep -c '^MOCK_DATASET=tyson' /app/.env.local"},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': 'command grep -l "APIFY" /app/.env /app/.env.local 2>/dev/null'},
    })
    # Bash 純非敏感白名單 key 錨定查詢放行
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': 'command grep -E "^(PORT|NODE_ENV|API_URL|HOST)=" /app/.dev.env'},
    })
    # Bash 檔案存在／權限元資料管線、cmp -s 與 git status 放行
    self.assertAllowed({'tool_name': 'Bash', 'tool_input': {'command': 'test -f /app/.dev.env'}})
    self.assertAllowed({'tool_name': 'Bash', 'tool_input': {'command': "ls -la /app/.dev.env 2>&1 | awk '{print $1, $NF}'"}})
    self.assertAllowed({'tool_name': 'Bash', 'tool_input': {'command': 'ls -la /app/.env.local | head -n 5'}})
    self.assertAllowed({'tool_name': 'Bash', 'tool_input': {'command': 'cmp -s /app/.dev.env /app/wt/.dev.env'}})
    self.assertAllowed({'tool_name': 'Bash', 'tool_input': {'command': 'git -C /app status .env'}})
    # jq 查詢 .json 設定檔內 .env 屬性、全形標點黏連 .env.example 與純文字單引號 heredoc 放行
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': "jq -r '.env // {} | keys[]' /Users/test/.claude/settings.json | head -5"},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': 'echo "請參考 .env.example（絕不硬編碼秘密）"'},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': "git commit -F - <<'EOF'\nfix: document .dev.env workflow\nEOF"},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': "mkdir -p /tmp/r && cat > /tmp/r/prompt.md <<'EOF'\ndo not read .dev.env\nEOF"},
    })
    # 2026-11-21 第二輪誤攔放寬（echo 標題、安全 $(grep -c)、ls/find 接 stdin-only 篩選、前綴 grep -o、含角括號的 jq、搜尋安全原始碼檔、cat <<'EOF' >> .md）
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': 'echo "== saas .test.env keys"; command grep -E "^[A-Za-z_][A-Za-z0-9_]*=" "app/.test.env" | cut -d= -f1 | tr \'\\n\' \' \''},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': 'echo "dev-pl-0: $(command grep -c -E \'^MONGO_CONNECTION_STRING=.*acme-dev-pl-0\' .dev.env)"'},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': 'ls acme-saas-v2-service/ | command grep -c -x ".test.env" ; ls -a acme-saas-v2-service | command grep -E "^\\.(test|dev)\\.env$"'},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': "find /app/.claude/worktrees -maxdepth 2 -name '.test.env' -type f | sed 's|/\\.test\\.env$||'"},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': "ls .env.local >/dev/null 2>&1 && echo 'env.local present'"},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': "command grep -o -E '^MONGO[A-Z_]*=' .dev.env"},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': "jq '{m:([.hooks.PreToolUse[].matcher // \"<any>\"]|length),c:(.env|has(\"X\"))}' /Users/test/.claude/settings.json"},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': "command grep -nE 'env.local|dev.env' /Users/test/scripts/up.sh | head -40"},
    })
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': "cat <<'EOF' >> /Users/test/notes.md\nmention .env here\nEOF"},
    })

  def test_2_known_bad(self):
    # 直接 Read .env / .dev.env / .env.local 攔截
    reason = self.assertDenied({'tool_name': 'Read', 'tool_input': {'file_path': '/Users/test/app/.env'}})
    self.assertIn('Write／Edit', reason)
    self.assertDenied({'tool_name': 'Read', 'tool_input': {'file_path': '/Users/test/app/.dev.env'}})
    self.assertDenied({'tool_name': 'Read', 'tool_input': {'file_path': '/Users/test/app/.env.local'}})
    # 反向斷言（2026-11-03 事故原貌）：黑名單 sed 遮罩漏遮 MONGO_PASS 必須攔截
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': "sed -E 's/(SECRET|TOKEN|KEY)=.*/\\1=***/' /app/.dev.env"},
    })
    # 直接 cat / head / python 讀 .env 攔截
    self.assertDenied({'tool_name': 'Bash', 'tool_input': {'command': 'cat /app/.dev.env'}})
    self.assertDenied({'tool_name': 'Bash', 'tool_input': {'command': 'head -n 20 .env'}})
    self.assertDenied({'tool_name': 'Bash', 'tool_input': {'command': "python3 -c \"print(open('.env').read())\""}})
    # 白名單夾帶敏感字根（MONGO_PASS / API_KEY / DATABASE_URL）攔截
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'command grep -E "^(PORT|MONGO_PASS)=" /app/.dev.env'},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'command grep -E "^(PORT|DATABASE_URL)=" /app/.dev.env'},
    })

  def test_3_boundary(self):
    # .env.sample 放行 vs .env.staging 攔截
    self.assertAllowed({'tool_name': 'Read', 'tool_input': {'file_path': '/app/.env.sample'}})
    self.assertDenied({'tool_name': 'Read', 'tool_input': {'file_path': '/app/.env.staging'}})
    # git diff --name-only .env 放行 vs git diff .env 攔截
    self.assertAllowed({'tool_name': 'Bash', 'tool_input': {'command': 'git diff --name-only .env'}})
    self.assertDenied({'tool_name': 'Bash', 'tool_input': {'command': 'git diff .env'}})
    # 合法白名單子句後串接未授權讀取（; cat .env）或加 -v / -A 2 攔截
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'command grep -E "^(PORT)=" .env; cat .env'},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'command grep -v -E "^(SECRET)=" .env'},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'command grep -A 3 -E "^(PORT)=" .env'},
    })
    # 安全邊界防繞行：jq 讀受保護 .dev.env、無 -s 之 cmp、直譯器 heredoc、危險下游 sh/xargs 皆必須攔截
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': "jq -Rs '.' /app/.dev.env"},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'cmp /app/.dev.env /app/wt/.dev.env'},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': "python3 - <<'PY'\nprint(open('/app/.dev.env').read())\nPY"},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': "cat > /tmp/probe.py <<'PY'\nprint(open('/app/.dev.env').read())\nPY\npython3 /tmp/probe.py"},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'command grep -E "^[A-Za-z_][A-Za-z0-9_]*=" /app/.dev.env | cut -d= -f1 | xargs cat /app/.dev.env'},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': "grep -E '^MONGO_CONNECTION_STRING' .test.env 2>/dev/null | sed -E 's#//[^@]*@#//***@#'"},
    })
    # 2026-11-21 第二輪防繞行反向斷言：下游偷傳 .env 檔、find -exec、echo 包不安全 $()、grep -o 跨 =、遞迴 grep、cat <<'EOF' >> .env
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'ls /tmp | grep foo .env'},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': "ls /tmp | sed 's/a/b/' .dev.env"},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': "find /app -name '.dev.env' -exec cat {} +"},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'echo "secret: $(command grep -E \'^MONGO_CONNECTION_STRING\' .dev.env | sed -E \'s#://[^@]*@#://***@#\')"'},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': "command grep -o -E '^MONGO.*' .dev.env"},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': "command grep -rn 'MONGO' .dev.env src/"},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': "command grep -nE 'dev.env' .dev.env"},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': "cat <<'EOF' >> /app/.env\nFOO=bar\nEOF"},
    })
    # 反向斷言（2026-11-21 回放 L55 抓到）：先存進變數再讀（f=.dev.env; grep "$f" | sed ...）必須攔截
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'f=/app/.dev.env; [ -f "$f" ] && command grep -E \'^MONGO_CONNECTION_STRING\' "$f" | sed -E \'s#://[^@]*@#://***@#\' || echo "no .dev.env"'},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'f=/app/.dev.env; cat "$f"'},
    })
    self.assertDenied({
      'tool_name': 'Bash',
      'tool_input': {'command': 'echo "$(ls /tmp; cat .env)"'},
    })
    # 控制字元與 bidi 注入淨化斷言
    reason = self.assertDenied({
      'tool_name': 'Read',
      'tool_input': {'file_path': '/app/‮.env\x07'},
    })
    self.assertNotIn('‮', reason)
    self.assertNotIn('\x07', reason)
    self.assertTrue(len(reason) > 40)

  def test_4_lifecycle_and_error_fail_closed(self):
    # update：讀取與測試 gate 自身、測試檔、settings.json 放行
    self.assertAllowed({'tool_name': 'Read', 'tool_input': {'file_path': str(GATE)}})
    self.assertAllowed({'tool_name': 'Read', 'tool_input': {'file_path': str( Path(__file__).resolve() )}})
    self.assertAllowed({'tool_name': 'Read', 'tool_input': {'file_path': '/Users/test/.claude/settings.json'}})
    self.assertAllowed({
      'tool_name': 'Bash',
      'tool_input': {'command': f'python3 {Path(__file__).resolve()}'},
    })
    # recovery：建立 sentinel 檔時放行，移除後恢復攔截（正反配對）
    with tempfile.TemporaryDirectory() as tmp:
      sentinel = Path(tmp) / 'dotenv-read-gate.off'
      sentinel.write_text('off\n')
      self.assertAllowed(
        {'tool_name': 'Read', 'tool_input': {'file_path': '/app/.dev.env'}},
        env_extra={'DOTENV_READ_GATE_SENTINEL': str(sentinel)},
      )
      sentinel.unlink()
      self.assertDenied(
        {'tool_name': 'Read', 'tool_input': {'file_path': '/app/.dev.env'}},
        env_extra={'DOTENV_READ_GATE_SENTINEL': str(sentinel)},
      )
    # error branch：損毀 JSON / 空輸入 / 缺 tool_input 一律 fail closed (deny)
    self.assertDenied('{invalid json')
    self.assertDenied('')
    self.assertDenied({'tool_name': 'Read', 'tool_input': None})

  def test_5_audit_side_effects_and_pathological_targets(self):
    with tempfile.TemporaryDirectory() as tmp:
      tmp_path = Path(tmp)
      tmp_path.chmod(0o700)
      audit_file = tmp_path / 'audit.jsonl'
      bystander = tmp_path / 'bystander.txt'
      bystander.write_text('untouched\n')

      # 1. 正常寫入 audit log 且旁路檔案未受影響
      self.assertDenied(
        {'session_id': 'sess-1', 'tool_name': 'Read', 'tool_input': {'file_path': '/app/.dev.env'}},
        env_extra={'DOTENV_READ_GATE_AUDIT': str(audit_file)},
      )
      self.assertEqual(bystander.read_text(), 'untouched\n')
      rows = [json.loads(line) for line in audit_file.read_text().splitlines() if line.strip()]
      self.assertEqual(len(rows), 1)
      self.assertEqual(rows[0]['tool'], 'Read')
      self.assertEqual(rows[0]['target'], '/app/.dev.env')

      # 2. symlink 目標：拒寫、沒寫到 victim、gate 仍正常 deny
      victim = tmp_path / 'victim.txt'
      victim.write_text('safe\n')
      sym_audit = tmp_path / 'sym-audit.jsonl'
      sym_audit.symlink_to(victim)
      self.assertDenied(
        {'session_id': 'sess-2', 'tool_name': 'Read', 'tool_input': {'file_path': '/app/.env'}},
        env_extra={'DOTENV_READ_GATE_AUDIT': str(sym_audit)},
      )
      self.assertEqual(victim.read_text(), 'safe\n')

      # 3. hard link 目標（st_nlink > 1）：拒寫、沒寫到 hardlink target、gate 仍正常 deny
      hl_audit = tmp_path / 'hl-audit.jsonl'
      os.link(victim, hl_audit)
      self.assertDenied(
        {'session_id': 'sess-3', 'tool_name': 'Read', 'tool_input': {'file_path': '/app/.env'}},
        env_extra={'DOTENV_READ_GATE_AUDIT': str(hl_audit)},
      )
      self.assertEqual(victim.read_text(), 'safe\n')

      # 4. FIFO 目標：不卡住（O_NONBLOCK）、gate 仍正常 deny
      fifo_audit = tmp_path / 'fifo-audit.jsonl'
      os.mkfifo(fifo_audit)
      self.assertDenied(
        {'session_id': 'sess-4', 'tool_name': 'Read', 'tool_input': {'file_path': '/app/.env'}},
        env_extra={'DOTENV_READ_GATE_AUDIT': str(fifo_audit)},
      )
      self.assertEqual(bystander.read_text(), 'untouched\n')


if __name__ == '__main__':
  suite = unittest.defaultTestLoader.loadTestsFromTestCase(DotenvReadGateTest)
  result = unittest.TextTestRunner(verbosity=2).run(suite)
  if not result.wasSuccessful():
    sys.exit(1)
  print('DOTENV_READ_GATE_ALL_TESTS_PASSED')
