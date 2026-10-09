#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOKS = Path(__file__).parent
WRAPPER = HOOKS / 'ask-explainer.py'
GATE = HOOKS / 'acme-db-write-gate.py'
READING = {'does': '印出一段文字', 'touches': '只有標準輸出', 'reversible': '不需復原', 'mismatch': '只是提到主機名、不會連線', 'risk': '低'}

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
open(os.environ['FAKE_SEEN'], 'w').write(json.dumps({'argv': sys.argv[1:], 'stdin': sys.stdin.read()}))
mode = os.environ.get('FAKE_MODE', 'ok')
if mode == 'fail':
  sys.exit(3)
text = os.environ['FAKE_TEXT'] if mode == 'ok' else 'not json'
print(json.dumps({'is_error': False, 'result': text, 'usage': {'cache_creation_input_tokens': 1103}}))
'''


def gate_script(body):
  return f'#!/usr/bin/env python3\nimport sys\nsys.stdin.read()\n{body}\n'


class WrapperTest(unittest.TestCase):
  def setUp(self):
    self.tmp = Path(tempfile.mkdtemp())
    self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
    self.fake = self.tmp / 'claude'
    self.fake.write_text(FAKE_CLAUDE)
    self.fake.chmod(0o755)
    self.seen = self.tmp / 'seen.json'
    self.state = self.tmp / 'state'
    self.env = {**os.environ, 'ASK_EXPLAINER_CLAUDE': str(self.fake), 'ASK_EXPLAINER_STATE_DIR': str(self.state),
                'FAKE_SEEN': str(self.seen), 'FAKE_TEXT': json.dumps(READING, ensure_ascii=False)}
    self.env.pop('ASK_EXPLAINER_INNER', None)

  def wrapped(self, body):
    p = self.tmp / f'gate{len(list(self.tmp.glob("gate*")))}.py'
    p.write_text(gate_script(body))
    return [sys.executable, str(p)]

  def run_wrapper(self, wrapped, command='echo hi', env=None, cwd=None):
    payload = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(cwd or self.tmp)})
    return subprocess.run([sys.executable, str(WRAPPER), *wrapped], input=payload, capture_output=True, text=True,
                          env=env or self.env, timeout=30)

  def ask_body(self, reason='[gate] 這個指令會連正式庫'):
    out = {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'ask',
                                  'permissionDecisionReason': reason}}
    return f'print({json.dumps(json.dumps(out, ensure_ascii=False))})'

  # known-good: an allow (no output) passes through and the model is never called
  def test_allow_passes_through_without_model_call(self):
    r = self.run_wrapper(self.wrapped('pass'))
    self.assertEqual((r.returncode, r.stdout), (0, ''))
    self.assertFalse(self.seen.exists())

  # known-good: a deny is handed back byte for byte
  def test_deny_is_untouched(self):
    deny = json.dumps({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                              'permissionDecisionReason': 'no'}})
    r = self.run_wrapper(self.wrapped(f'print({json.dumps(deny)})'))
    self.assertEqual(r.stdout.strip(), deny)
    self.assertFalse(self.seen.exists())

  # known-bad: an ask gets the reading appended, and stays an ask
  def test_ask_gets_reading_and_stays_ask(self):
    r = self.run_wrapper(self.wrapped(self.ask_body()))
    hso = json.loads(r.stdout)['hookSpecificOutput']
    self.assertEqual(hso['permissionDecision'], 'ask')
    self.assertTrue(hso['permissionDecisionReason'].startswith('[gate] 這個指令會連正式庫\n\n【第三方判讀・haiku】風險：低'))
    self.assertIn('字面與實際不符：只是提到主機名、不會連線', hso['permissionDecisionReason'])
    argv = json.loads(self.seen.read_text())['argv']
    for flag in ('--safe-mode', '--no-session-persistence', '--strict-mcp-config'):
      self.assertIn(flag, argv)
    self.assertEqual(argv[argv.index('--tools') + 1], '')
    log = json.loads((self.state / 'ask-explainer.log').read_text().splitlines()[-1])
    self.assertEqual((log['outcome'], log['risk'], log['cache_creation']), ('read', '低', 1103))

  # boundary: model failure keeps the ask and says the reading failed
  def test_model_failure_keeps_ask_with_note(self):
    r = self.run_wrapper(self.wrapped(self.ask_body()), env={**self.env, 'FAKE_MODE': 'fail'})
    hso = json.loads(r.stdout)['hookSpecificOutput']
    self.assertEqual(hso['permissionDecision'], 'ask')
    self.assertIn('【第三方判讀失敗】模型呼叫失敗（claude -p 結束碼 3）', hso['permissionDecisionReason'])

  def test_unparsable_reply_keeps_ask_with_note(self):
    r = self.run_wrapper(self.wrapped(self.ask_body()), env={**self.env, 'FAKE_MODE': 'garbage'})
    hso = json.loads(r.stdout)['hookSpecificOutput']
    self.assertEqual(hso['permissionDecision'], 'ask')
    self.assertIn('回覆格式無法解析', hso['permissionDecisionReason'])

  # boundary: the wrapped hook's exit code and output survive, so `|| exit 2` still fails closed
  def test_wrapped_exit_code_and_output_pass_through(self):
    r = self.run_wrapper(self.wrapped('print("partial"); sys.exit(1)'))
    self.assertEqual((r.returncode, r.stdout.strip()), (1, 'partial'))
    self.assertFalse(self.seen.exists())

  def test_missing_wrapped_hook_does_not_exit_zero(self):
    r = self.run_wrapper([str(self.tmp / 'nope.py')])
    self.assertNotEqual(r.returncode, 0)

  # lifecycle: the inner claude -p carries a marker; a wrapper that sees it never reads again
  def test_inner_marker_passes_through(self):
    r = self.run_wrapper(self.wrapped(self.ask_body()), env={**self.env, 'ASK_EXPLAINER_INNER': '1'})
    self.assertEqual(json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason'], '[gate] 這個指令會連正式庫')
    self.assertFalse(self.seen.exists())

  def test_script_is_sent_masked_and_imports_are_named(self):
    (self.tmp / 'w.js').write_text("import { db } from './db.js'\nconst uri = 'mongodb://owner:S3cr3t@h/x'\n")
    r = self.run_wrapper(self.wrapped(self.ask_body()), command='node w.js')
    sent = json.loads(self.seen.read_text())['stdin']
    self.assertIn('腳本 w.js 全文', sent)
    self.assertIn('mongodb://***:***@h/x', sent)
    self.assertNotIn('S3cr3t', sent)
    self.assertIn('腳本 w.js 另引用了 ./db.js，這些沒有送審', json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason'])

  def test_unreadable_script_is_named(self):
    r = self.run_wrapper(self.wrapped(self.ask_body()), command='node gone.js')
    self.assertIn('未讀到腳本 gone.js', json.loads(r.stdout)['hookSpecificOutput']['permissionDecisionReason'])

  def test_log_symlink_is_not_written_through(self):
    self.state.mkdir()
    target = self.tmp / 'elsewhere.txt'
    target.write_text('keep\n')
    (self.state / 'ask-explainer.log').symlink_to(target)
    self.run_wrapper(self.wrapped(self.ask_body()))
    self.assertEqual(target.read_text(), 'keep\n')

  # the real acme gate, wrapped: a mention of the prod host asks, and the reading is appended
  def test_real_acme_gate_wrapped(self):
    env = {**self.env, 'acme_DB_GATE_STATE_DIR': str(self.tmp / 'gate-state')}
    r = self.run_wrapper([sys.executable, str(GATE)], command='echo ' + 'acme-db-pl-' + '0', env=env)
    hso = json.loads(r.stdout)['hookSpecificOutput']
    self.assertEqual(hso['permissionDecision'], 'ask')
    self.assertIn('[acme-db-write-gate]', hso['permissionDecisionReason'])
    self.assertIn('【第三方判讀・haiku】', hso['permissionDecisionReason'])


if __name__ == '__main__':
  unittest.main()
