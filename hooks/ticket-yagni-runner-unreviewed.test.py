"""ticket-yagni runner：只用登記的票檔路徑、未審到一律帶可辨識原因（govern-implement-fix-dispatch Ticket 03）。

跑法：python3 ~/.claude/hooks/ticket-yagni-runner-unreviewed.test.py
"""
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

RUNNER = Path(__file__).with_name('ticket-yagni-runner.py')
GOOD_RESPONSE = {'model': 'stub', 'choices': [{'message': {'content': json.dumps({
  'verdicts': [{'item': 'FILE:README.md', 'verdict': 'keep', 'basis': 'a', 'ticket_quote': 'x', 'reason': 'x'}],
  'missing_information': [], 'summary': 'ok'})}}]}


class Relay(http.server.BaseHTTPRequestHandler):
  mode = 'ok'

  def do_POST(self):
    self.rfile.read(int(self.headers.get('Content-Length', 0)))
    if Relay.mode == 'slow':
      time.sleep(8)
    if Relay.mode == 'error':
      self.send_response(500)
      self.end_headers()
      self.wfile.write(b'{"error":"boom"}')
      return
    body = b'not json at all' if Relay.mode == 'garbage' else json.dumps(GOOD_RESPONSE).encode()
    self.send_response(200)
    self.send_header('Content-Type', 'application/json')
    self.end_headers()
    self.wfile.write(body)

  def log_message(self, *args):
    pass


class RunnerUnreviewedTests(unittest.TestCase):
  @classmethod
  def setUpClass(cls):
    cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Relay)
    cls.server.daemon_threads = True
    threading.Thread(target=cls.server.serve_forever, daemon=True).start()

  @classmethod
  def tearDownClass(cls):
    cls.server.shutdown()

  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)
    self.repo = self.root / 'repo'
    self.repo.mkdir()
    git = ['git', '-C', str(self.repo)]
    subprocess.run(git + ['init', '-q'], check=True)
    subprocess.run(git + ['config', 'user.email', 't@t'], check=True)
    subprocess.run(git + ['config', 'user.name', 't'], check=True)
    self.ticket = self.repo / '.scratch/feature/issues/09-wire.md'
    self.other = self.repo / '.scratch/older/issues/09-material.md'
    for path, text in [(self.ticket, '# 09 — Wire ticket\n'), (self.other, '# 09 — Material ticket\n')]:
      path.parent.mkdir(parents=True)
      path.write_text(text)
    self.tasks = self.repo / 'openspec/changes/demo/tasks.md'
    self.tasks.parent.mkdir(parents=True)
    self.tasks.write_text('# tickets\n\n## 09 — Wire ticket\n\n**Status:** `ready-for-agent`\n')
    (self.repo / 'README.md').write_text('hello\n')
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-qm', 'base'], check=True)
    self.base = subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    (self.repo / 'README.md').write_text('hello\nworld\n')
    keys = self.root / 'keys.env'
    keys.write_text('CLIPROXY_KEY_CC=test-key\n')
    self.env = {**os.environ, 'TICKET_YAGNI_KEYS_ENV': str(keys),
                'TICKET_YAGNI_RELAY_URL': f'http://127.0.0.1:{self.server.server_address[1]}/v1/chat/completions',
                'TICKET_YAGNI_ROOT': str(self.root / 'yroot'), 'MATT_TDD_ROOT': str(self.root / 'matt')}
    self.env.pop('TICKET_YAGNI_FAKE_RESPONSE', None)
    Relay.mode = 'ok'

  def tearDown(self):
    self.tmp.cleanup()

  def run_runner(self, *extra, ticket_file=None, out='out', timeout=30):
    cmd = [sys.executable, str(RUNNER), '--session', 'fixture', '--run', 'fixture-run', '--ticket', '09',
           '--agent', 'worker', '--worktree', str(self.repo), '--base', self.base, '--cwd', str(self.repo),
           '--out', str(self.root / out), '--model', 'stub-model', *extra]
    if ticket_file is not None:
      cmd += ['--ticket-file', str(ticket_file)]
    started = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, env=self.env, timeout=timeout)
    return result, time.time() - started

  def error_record(self, out='out'):
    return json.loads((self.root / out / 'error.json').read_text())

  def test_registered_path_is_the_only_ticket_read(self):
    result, _ = self.run_runner(ticket_file=self.ticket)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertNotIn('matches multiple', result.stderr)
    packet = (self.root / 'out/packet.md').read_text()
    self.assertIn('# 09 — Wire ticket', packet)
    self.assertNotIn('Material ticket', packet)
    self.assertTrue((self.root / 'out/verdict.json').exists())

  def test_missing_registered_path_is_unresolved_without_scanning(self):
    result, _ = self.run_runner()
    self.assertEqual(result.returncode, 1)
    record = self.error_record()
    self.assertEqual(record.get('unreviewed'), 'ticket-file-unresolved')
    self.assertNotIn('09-wire.md', record['error'])
    self.assertFalse((self.root / 'out/packet.md').exists())

  def test_registered_path_that_does_not_exist_is_unresolved(self):
    result, _ = self.run_runner(ticket_file=self.repo / '.scratch/feature/issues/09-gone.md')
    self.assertEqual(result.returncode, 1)
    self.assertEqual(self.error_record().get('unreviewed'), 'ticket-file-unresolved')
    self.assertFalse((self.root / 'out/packet.md').exists())

  def test_openspec_tasks_file_is_reported_unsupported(self):
    result, _ = self.run_runner(ticket_file=self.tasks)
    self.assertEqual(result.returncode, 1)
    record = self.error_record()
    self.assertEqual(record.get('unreviewed'), 'openspec-unsupported')
    self.assertFalse((self.root / 'out/verdict.json').exists())

  def test_slow_relay_hits_the_runner_deadline(self):
    Relay.mode = 'slow'
    result, elapsed = self.run_runner('--deadline', '2', ticket_file=self.ticket)
    self.assertEqual(result.returncode, 1)
    self.assertEqual(self.error_record().get('unreviewed'), 'timeout')
    self.assertLess(elapsed, 6)
    self.assertFalse((self.root / 'out/verdict.json').exists())

  def test_relay_error_is_reported_unreviewed(self):
    Relay.mode = 'error'
    result, _ = self.run_runner(ticket_file=self.ticket)
    self.assertEqual(result.returncode, 1)
    self.assertEqual(self.error_record().get('unreviewed'), 'relay-error')
    self.assertFalse((self.root / 'out/verdict.json').exists())

  def test_unparseable_relay_response_is_reported_unreviewed(self):
    Relay.mode = 'garbage'
    result, _ = self.run_runner(ticket_file=self.ticket)
    self.assertEqual(result.returncode, 1)
    self.assertEqual(self.error_record().get('unreviewed'), 'unparseable-response')
    self.assertFalse((self.root / 'out/verdict.json').exists())

  def test_manual_review_without_path_still_finds_a_unique_ticket(self):
    self.other.unlink()
    result, _ = self.run_runner('--manual', '--dry-run')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertIn('# 09 — Wire ticket', (self.root / 'out/packet.md').read_text())


if __name__ == '__main__':
  unittest.main()
