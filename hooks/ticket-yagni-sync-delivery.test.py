"""ticket-yagni register --sync：前台 worker 交件時同步審完，main 同時拿到成果與判決（govern-implement-fix-dispatch Ticket 04）。

跑法：python3 ~/.claude/hooks/ticket-yagni-sync-delivery.test.py
seam：register 指令的 stdin JSON（PostToolUse Agent）→ stdout JSON；runner 用 stub 模擬判決、逾時、崩潰。
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

HOOK = Path(__file__).with_name('ticket-yagni.py')
SESSION = 'sess-sync-0001'
RUN = 'run-sync-0001'

STUB = r'''#!/usr/bin/env python3
import json, os, sys, time
a = sys.argv
out = a[a.index('--out') + 1]
ticket = a[a.index('--ticket') + 1]
open(os.path.join(out, 'argv.json'), 'w').write(json.dumps(a))
mode = os.environ.get('STUB_MODE_' + ticket, os.environ.get('STUB_MODE', 'keep'))
time.sleep(float(os.environ.get('STUB_SLEEP', '0')))
if mode == 'hang':
  time.sleep(30)
if mode == 'crash':
  sys.exit(1)
if mode == 'openspec':
  open(os.path.join(out, 'error.json'), 'w').write(json.dumps({'error': 'Unreviewed: openspec tasks.md tickets are not reviewable yet', 'unreviewed': 'openspec-unsupported'}))
  sys.exit(1)
vs = [{'item': f'FILE:mod{ticket}.py', 'verdict': 'keep', 'basis': 'a', 'ticket_quote': 'x', 'reason': 'core'}]
if mode == 'demote':
  vs.append({'item': f'Helper{ticket}', 'verdict': 'demote', 'basis': 'c', 'ticket_quote': 'none', 'reason': 'unjustified helper'})
counts = {k: sum(1 for v in vs if v['verdict'] == k) for k in ('keep', 'demote', 'kill')}
open(os.path.join(out, 'verdict.json'), 'w').write(json.dumps({'ticket': ticket, 'verdicts': vs, 'counts': counts, 'elapsed': 1.0, 'missing_information': []}))
'''


def ticket(nn, status='ready-for-agent'):
  return f'# {nn} — Ticket {nn}\n\n**Status:** `{status}`\n\n- [ ] criterion\n'


class SyncDeliveryTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(os.path.realpath(self.tmp.name))
    self.repo = self.root / 'repo'
    self.issues = self.repo / '.scratch/feat/issues'
    self.issues.mkdir(parents=True)
    git = ['git', '-C', str(self.repo)]
    subprocess.run(git + ['init', '-q'], check=True)
    subprocess.run(git + ['config', 'user.email', 't@t'], check=True)
    subprocess.run(git + ['config', 'user.name', 't'], check=True)
    self.t09 = self.issues / '09-wire.md'
    self.t09.write_text(ticket('09'))
    self.t03 = self.issues / '03-other.md'
    self.t03.write_text(ticket('03'))
    (self.repo / 'README.md').write_text('x\n')
    subprocess.run(git + ['add', '-A'], check=True)
    subprocess.run(git + ['commit', '-qm', 'base'], check=True)
    matt = self.root / 'matt' / SESSION / RUN
    matt.mkdir(parents=True)
    (matt / 'decision.json').write_text(json.dumps({
      'contract': 'MATT_TDD_DECISION v1', 'status': 'started', 'session_id': SESSION, 'run_id': RUN,
      'tickets_source': str(self.issues),
      'tickets': [{'id': '09', 'decision': 'required', 'seam': 'x'}, {'id': '03', 'decision': 'required', 'seam': 'x'}]}))
    stub = self.root / 'stub-runner.py'
    stub.write_text(STUB)
    self.yroot = self.root / 'yroot'
    self.env = {**os.environ, 'TICKET_YAGNI_ROOT': str(self.yroot), 'MATT_TDD_ROOT': str(self.root / 'matt'),
                'TICKET_YAGNI_OFF': str(self.root / 'off'), 'TICKET_YAGNI_RUNNER': str(stub),
                'TICKET_YAGNI_RUNNER_TIMEOUT': '20', 'TICKET_YAGNI_FAIL_OPEN': '1'}

  def tearDown(self):
    self.tmp.cleanup()

  def payload(self, description, prompt, response='Final result: done, tests green.', tool_use_id='toolu_fg_sync_0001'):
    return {'hook_event_name': 'PostToolUse', 'session_id': SESSION, 'cwd': str(self.repo), 'tool_name': 'Agent',
            'tool_use_id': tool_use_id,
            'tool_input': {'description': description, 'prompt': prompt, 'subagent_type': 'routed-impl'},
            'tool_response': response}

  def start(self, payload, sync=True, **env):
    args = [sys.executable, str(HOOK), 'register'] + (['--sync'] if sync else [])
    proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            env={**self.env, **env})
    proc.stdin.write(json.dumps(payload))
    proc.stdin.close()
    return proc

  def register(self, payload, sync=True, **env):
    started = time.time()
    proc = self.start(payload, sync, **env)
    out, err = proc.stdout.read(), proc.stderr.read()
    proc.wait(timeout=60)
    return proc.returncode, out, err, time.time() - started

  def context(self, out):
    self.assertTrue(out.strip(), 'expected hook stdout')
    data = json.loads(out)['hookSpecificOutput']
    self.assertEqual(data['hookEventName'], 'PostToolUse')
    return data['additionalContext']

  def dirty(self):
    (self.repo / 'README.md').write_text('x\ny\n')

  def test_foreground_demote_lists_items_in_the_same_output(self):
    self.dirty()
    rc, out, _, _ = self.register(self.payload('Ticket 09 wire', f'ticket: {self.t09}'), STUB_MODE='demote')
    self.assertEqual(rc, 0)
    ctx = self.context(out)
    self.assertIn('票 09', ctx)
    self.assertIn('demote', ctx)
    self.assertIn('Helper09', ctx)

  def test_real_foreground_response_with_agent_id_is_reviewed(self):
    # CC 2.1.283 實測的前台完成回傳：dict、status completed、同時帶 agentId、沒有 isAsync（Ticket 07 探針 caseA2）。
    self.dirty()
    response = {'status': 'completed', 'prompt': f'ticket: {self.t09}', 'agentId': 'af1e49c60d93ac5b9',
                'agentType': 'routed-impl', 'content': [{'type': 'text', 'text': 'Done.'}], 'totalToolUseCount': 2}
    rc, out, _, _ = self.register(self.payload('Ticket 09 wire', f'ticket: {self.t09}', response=response), STUB_MODE='demote')
    self.assertEqual(rc, 0)
    self.assertIn('Helper09', self.context(out))

  def test_unwritable_state_root_still_reports_unreviewed(self):
    blocker = self.root / 'blocker'
    blocker.write_text('a regular file where the state dir should be\n')
    self.env['TICKET_YAGNI_ROOT'] = str(blocker / 'sub')
    self.dirty()
    rc, out, _, _ = self.register(self.payload('Ticket 09 wire', f'ticket: {self.t09}'), STUB_MODE='keep')
    self.assertEqual(rc, 0)
    self.assertIn('未審到', self.context(out))

  def test_all_keep_says_reviewed_with_nothing_to_cut(self):
    self.dirty()
    rc, out, _, _ = self.register(self.payload('Ticket 09 wire', f'ticket: {self.t09}'), STUB_MODE='keep')
    self.assertEqual(rc, 0)
    ctx = self.context(out)
    self.assertIn('審過', ctx)
    self.assertIn('沒有要砍', ctx)
    self.assertNotIn('未審到', ctx)

  def test_runner_timeout_or_crash_reports_unreviewed_before_the_limit(self):
    self.dirty()
    rc, out, _, elapsed = self.register(self.payload('Ticket 09 wire', f'ticket: {self.t09}'),
                                        STUB_MODE='hang', TICKET_YAGNI_RUNNER_TIMEOUT='2')
    self.assertEqual(rc, 0)
    ctx = self.context(out)
    self.assertIn('未審到', ctx)
    self.assertIn('逾時', ctx)
    self.assertLess(elapsed, 8)
    rc, out, _, _ = self.register(self.payload('Ticket 09 wire', f'ticket: {self.t09}', tool_use_id='toolu_fg_sync_0002'),
                                  STUB_MODE='crash')
    self.assertEqual(rc, 0)
    self.assertIn('未審到', self.context(out))

  def test_runner_unreviewed_code_is_translated(self):
    self.dirty()
    rc, out, _, _ = self.register(self.payload('Ticket 09 wire', f'ticket: {self.t09}'), STUB_MODE='openspec')
    self.assertEqual(rc, 0)
    ctx = self.context(out)
    self.assertIn('未審到', ctx)
    self.assertIn('openspec 格式尚未支援', ctx)

  def test_parallel_foreground_workers_each_get_their_own_verdict(self):
    self.dirty()
    first = self.start(self.payload('Ticket 09 wire', f'ticket: {self.t09}', tool_use_id='toolu_par_aaaa_0001'),
                       STUB_MODE='demote', STUB_SLEEP='1')
    second = self.start(self.payload('Ticket 03 other', f'ticket: {self.t03}', tool_use_id='toolu_par_bbbb_0002'),
                        STUB_MODE='demote', STUB_SLEEP='1')
    out1, out2 = first.stdout.read(), second.stdout.read()
    first.wait(timeout=60)
    second.wait(timeout=60)
    ctx1, ctx2 = self.context(out1), self.context(out2)
    self.assertIn('Helper09', ctx1)
    self.assertNotIn('Helper03', ctx1)
    self.assertIn('Helper03', ctx2)
    self.assertNotIn('Helper09', ctx2)

  def test_fix_worker_on_an_already_closed_ticket_is_still_reviewed(self):
    self.t09.write_text(ticket('09', status='completed'))
    self.dirty()
    rc, out, _, _ = self.register(self.payload('Ticket 09 follow-up fix', f'ticket: {self.t09}'), STUB_MODE='demote')
    self.assertEqual(rc, 0)
    self.assertIn('Helper09', self.context(out))

  def test_background_worker_path_is_unchanged(self):
    self.dirty()
    resp = 'Async agent launched successfully. agentId: bgworker0001 (internal ID). The agent is working in the background.'
    rc, out, err, _ = self.register(self.payload('Ticket 09 wire', f'ticket: {self.t09}', response=resp))
    self.assertEqual((rc, out.strip(), err.strip()), (0, '', ''))
    registry = (self.yroot / SESSION / 'workers.jsonl').read_text()
    self.assertIn('bgworker0001', registry)
    self.assertFalse((self.yroot / SESSION / f'{RUN}__09' / 'bgworker0001').exists())

  def test_openspec_tasks_path_is_registered_as_the_ticket_file(self):
    tasks = self.repo / 'openspec/changes/demo/tasks.md'
    tasks.parent.mkdir(parents=True)
    tasks.write_text('# demo\n\n## 09 — Ninth\n\n**Status:** `ready-for-agent`\n')
    self.dirty()
    rc, out, _, _ = self.register(self.payload('Ticket 09 wire', f'ticket source: {tasks}'), STUB_MODE='keep')
    self.assertEqual(rc, 0)
    entry = json.loads((self.yroot / SESSION / 'workers.jsonl').read_text().splitlines()[-1])
    self.assertEqual(entry.get('ticket_file'), str(tasks))

  def test_without_sync_flag_foreground_keeps_the_legacy_output(self):
    self.dirty()
    rc, out, err, _ = self.register(self.payload('Ticket 09 wire', f'ticket: {self.t09}'), sync=False, STUB_MODE='demote')
    self.assertEqual(rc, 2)
    self.assertEqual(out.strip(), '')
    self.assertIn('Helper09', err)


if __name__ == '__main__':
  unittest.main()
