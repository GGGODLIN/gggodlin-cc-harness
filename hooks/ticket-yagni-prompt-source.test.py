#!/usr/bin/env python3
"""ticket-yagni register/deliver 從 worker prompt 抓明示票檔的契約測試。
跑法：TICKET_YAGNI_HOOK 不設時讀本檔旁的 ticket-yagni.py；stub runner 隔離外部 relay 呼叫。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(os.environ.get('TICKET_YAGNI_HOOK', str(Path(__file__).resolve().with_name('ticket-yagni.py'))))

STUB_RUNNER = '''#!/usr/bin/env python3
import json, os, sys
open(os.environ['PT_STUB_ARGS'], 'w').write(json.dumps(sys.argv))
out = sys.argv[sys.argv.index('--out') + 1]
ticket = sys.argv[sys.argv.index('--ticket') + 1]
open(os.path.join(out, 'verdict.json'), 'w').write(json.dumps(
  {'ticket': ticket, 'verdicts': [], 'counts': {'keep': 0, 'demote': 0, 'kill': 0}, 'elapsed': 1.0}))
'''


def git(repo, *args):
  return subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, timeout=60)


class PromptTicketFileTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    root = Path(self.tmp.name)
    self.root = root
    self.session = 'sess-pt-0001'
    run = 'pt_run'
    (root / 'matt' / self.session / run).mkdir(parents=True)
    (root / 'matt' / self.session / run / 'decision.json').write_text(json.dumps(
      {'contract': 'MATT_TDD_DECISION v1', 'status': 'started', 'session_id': self.session, 'run_id': run,
       'tickets': [{'id': '09', 'decision': 'required'}]}))
    self.gov = root / 'gov'
    issues = self.gov / '.scratch' / 'feat' / 'issues'
    issues.mkdir(parents=True)
    self.ticket_file = issues / '09-wire.md'
    self.ticket_file.write_text('# 09 — Wire\n\n**Status:** `ready-for-agent`\n')
    self.service = root / 'service'
    self.service.mkdir()
    git(self.service, 'init', '-q')
    git(self.service, 'config', 'user.email', 't@t')
    git(self.service, 'config', 'user.name', 't')
    (self.service / 'README.md').write_text('x\n')
    git(self.service, 'add', '-A')
    git(self.service, 'commit', '-qm', 'base')
    self.stub = root / 'stub-runner.py'
    self.stub.write_text(STUB_RUNNER)
    self.stub.chmod(0o755)
    self.argv_path = root / 'argv.json'
    self.env = dict(os.environ)
    self.env.update(TICKET_YAGNI_ROOT=str(root / 'yagni'), MATT_TDD_ROOT=str(root / 'matt'),
                    TICKET_YAGNI_OFF=str(root / 'off'), TICKET_YAGNI_RUNNER=str(self.stub),
                    TICKET_YAGNI_RUNNER_TIMEOUT='20', TICKET_YAGNI_PENDING_TTL='700',
                    PT_STUB_ARGS=str(self.argv_path))
    self.env.pop('TICKET_YAGNI_FAKE_RESPONSE', None)

  def tearDown(self):
    self.tmp.cleanup()

  def hook(self, subcmd, payload):
    return subprocess.run([sys.executable, str(HOOK), subcmd], input=json.dumps(payload),
                          capture_output=True, text=True, env=self.env, timeout=60)

  def register(self, description, prompt, response='Async agent launched successfully. agentId: abc123def0', agent_type='routed-impl'):
    return self.hook('register', {
      'hook_event_name': 'PostToolUse', 'session_id': self.session, 'cwd': str(self.service),
      'tool_name': 'Agent', 'tool_use_id': 'toolu_pt_0001',
      'tool_input': {'description': description, 'prompt': prompt, 'subagent_type': agent_type},
      'tool_response': response})

  def deliver(self, agent_id='abc123def0'):
    return self.hook('deliver', {
      'hook_event_name': 'UserPromptSubmit', 'session_id': self.session, 'cwd': str(self.service),
      'prompt': f'<task-notification>\n<task-id>{agent_id}</task-id>\n<status>completed</status>\n'
                f'<summary>Agent done</summary>\n</task-notification>'})

  def read_registry(self):
    p = self.root / 'yagni' / self.session / 'workers.jsonl'
    return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

  def stub_args(self):
    return json.loads(self.argv_path.read_text()) if self.argv_path.exists() else []

  def prompt_with_path(self, *paths):
    return '既有流程續作狀態：implement\n\n票檔（只讀）：' + '\n另見：'.join(str(p) for p in paths)

  def test_async_register_persists_prompt_ticket_file_and_delivery_uses_it(self):
    result = self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file))
    self.assertEqual(result.returncode, 0, result.stderr)
    entries = self.read_registry()
    self.assertEqual(len(entries), 1)
    self.assertEqual(entries[0].get('ticket_file'), str(self.ticket_file))
    result = self.deliver('abc123def0')
    self.assertEqual(result.returncode, 0, result.stderr)
    argv = self.stub_args()
    self.assertIn('--ticket-file', argv)
    self.assertEqual(argv[argv.index('--ticket-file') + 1], str(self.ticket_file))
    self.assertIn('09', argv)

  def test_foreground_register_passes_prompt_ticket_file_to_sync_runner(self):
    result = self.register('ticket 09 inline', self.prompt_with_path(self.ticket_file),
                           response='Final result: done, all tests green.')
    self.assertEqual(result.returncode, 0, result.stderr)
    argv = self.stub_args()
    self.assertIn('--ticket-file', argv)
    self.assertEqual(argv[argv.index('--ticket-file') + 1], str(self.ticket_file))

  def test_foreground_fullwidth_separators_preserve_ticket_path(self):
    prompt = f'你的 worktree：{self.service}，票檔（只讀）：{self.ticket_file}'
    result = self.register('Ticket 09 wire', prompt, response='Final result: done.')
    self.assertEqual(result.returncode, 0, result.stderr)
    argv = self.stub_args()
    self.assertIn('--ticket-file', argv)
    self.assertEqual(argv[argv.index('--ticket-file') + 1], str(self.ticket_file))

  def test_async_fullwidth_separators_preserve_ticket_path(self):
    prompt = f'你的 worktree：{self.service}；票檔（只讀）：{self.ticket_file}'
    result = self.register('Ticket 09 wire', prompt)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.read_registry()[0].get('ticket_file'), str(self.ticket_file))
    result = self.deliver()
    self.assertEqual(result.returncode, 0, result.stderr)
    argv = self.stub_args()
    self.assertEqual(argv[argv.index('--ticket-file') + 1], str(self.ticket_file))

  def test_fullwidth_worktree_separators_review_worker_diff_not_cwd(self):
    worker = self.root / 'worker-中文'
    subprocess.run(['git', 'clone', '-q', str(self.service), str(worker)], check=True, capture_output=True)
    (worker / 'worker-only.txt').write_text('worker change\n')
    response_file = self.root / 'relay-response.json'
    response_file.write_text(json.dumps({'choices': [{'message': {'content': json.dumps({
      'verdicts': [{'item': 'FILE:worker-only.txt', 'verdict': 'keep', 'reason': 'required'}]})}}]}))
    self.env['TICKET_YAGNI_RUNNER'] = str(HOOK.with_name('ticket-yagni-runner.py'))
    self.env['TICKET_YAGNI_FAKE_RESPONSE'] = str(response_file)
    for index, suffix in enumerate(('（detached，說明）', '，另一段說明', ' (detached)')):
      for source in ('cc', 'codex'):
        with self.subTest(suffix=suffix, source=source):
          agent_id = f'worker-{source}-{index}'
          response = ({'isAsync': True, 'status': 'async_launched', 'agentId': agent_id}
                      if source == 'cc' else f'agentId: {agent_id}')
          prompt = f'你的 worktree：{worker}{suffix}\n票檔（只讀）：{self.ticket_file}'
          result = self.register('Ticket 09 wire', prompt, response)
          self.assertEqual(result.returncode, 0, result.stderr)
          self.assertEqual(self.read_registry()[-1]['worktree'], str(worker.resolve()))
          result = self.deliver(agent_id)
          self.assertEqual(result.returncode, 0, result.stderr)
          state = self.root / 'yagni' / self.session / 'pt_run__09' / agent_id
          self.assertFalse((state / 'skip.json').exists())
          verdict = json.loads((state / 'verdict.json').read_text())
          self.assertEqual(verdict['worktree'], str(worker.resolve()))
          self.assertEqual(verdict['files_changed'], 1)
          self.assertEqual(verdict['coverage'], {'missing': [], 'extra': []})
          self.assertEqual(verdict['verdicts'][0]['item'], 'FILE:worker-only.txt')

  def test_no_prompt_path_keeps_original_behavior(self):
    result = self.register('Ticket 09 wire', 'work in the service repo')
    self.assertEqual(result.returncode, 0, result.stderr)
    entries = self.read_registry()
    self.assertEqual(len(entries), 1)
    self.assertNotIn('ticket_file', entries[0])
    result = self.deliver('abc123def0')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertNotIn('--ticket-file', self.stub_args())

  def test_wrong_ticket_number_not_used(self):
    other = self.gov / '.scratch' / 'feat' / 'issues' / '05-other.md'
    other.write_text('# 05 — Other\n')
    self.register('Ticket 09 wire', self.prompt_with_path(other))
    self.deliver('abc123def0')
    self.assertNotIn('--ticket-file', self.stub_args())

  def test_two_matching_candidates_not_used(self):
    second = self.gov / '.scratch' / 'feat' / 'issues' / '09-second.md'
    second.write_text('# 09 — Second\n')
    self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file, second))
    entries = self.read_registry()
    self.assertEqual(len(entries), 1)
    self.assertNotIn('ticket_file', entries[0])
    self.deliver('abc123def0')
    self.assertNotIn('--ticket-file', self.stub_args())

  def test_missing_prompt_path_not_used(self):
    ghost = self.gov / '.scratch' / 'feat' / 'issues' / '09-ghost.md'
    self.register('Ticket 09 wire', self.prompt_with_path(ghost))
    self.deliver('abc123def0')
    self.assertNotIn('--ticket-file', self.stub_args())

  def test_symlinked_prompt_path_not_used(self):
    link = self.gov / '.scratch' / 'feat' / 'issues' / '09-link.md'
    link.symlink_to(self.ticket_file)
    self.register('Ticket 09 wire', self.prompt_with_path(link))
    self.deliver('abc123def0')
    self.assertNotIn('--ticket-file', self.stub_args())

  def test_reviewer_dispatch_with_ticket_file_is_not_registered(self):
    result = self.register('review the diff for scope', self.prompt_with_path(self.ticket_file))
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.read_registry(), [])
    self.assertEqual(self.stub_args(), [])

  def test_auditor_mentioning_ticket_is_not_registered_as_worker(self):
    result = self.register('skill-verify:mutation-testing ticket 09 fix round', self.prompt_with_path(self.ticket_file),
                           {'status': 'running', 'agentId': 'abc123def0'}, 'skill-verify-auditor')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.read_registry(), [])
    self.assertEqual(self.stub_args(), [])

  def test_reviewer_type_with_ticket_number_is_not_registered(self):
    result = self.register('Review ticket 09 diff', self.prompt_with_path(self.ticket_file),
                           agent_type='typescript-reviewer')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.read_registry(), [])
    self.assertEqual(self.stub_args(), [])

  def test_existing_implementation_worker_types_still_register(self):
    for agent_type in ('routed-secure', 'codex:codex-rescue'):
      result = self.register('Ticket 09 implementation', self.prompt_with_path(self.ticket_file),
                             response=f'Async agent launched successfully. agentId: {agent_type.replace(":", "-")}-worker01',
                             agent_type=agent_type)
      self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(len(self.read_registry()), 2)
    self.assertEqual(self.stub_args(), [])

  def test_real_async_response_shape_registers_and_waits(self):
    response = {'isAsync': True, 'status': 'async_launched', 'agentId': 'abc123def0'}
    result = self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file), response)
    self.assertEqual(result.returncode, 0, result.stderr)
    entries = self.read_registry()
    self.assertEqual(len(entries), 1)
    self.assertEqual(entries[0]['agent_id'], 'abc123def0')
    self.assertFalse(entries[0]['foreground'])
    self.assertEqual(self.stub_args(), [])
    self.assertEqual(self.deliver().returncode, 0)
    self.assertIn('--ticket-file', self.stub_args())

  def test_structured_async_launch_registers_and_waits_for_delivery(self):
    response = {'status': 'running', 'agentId': 'abc123def0', 'text': 'Async agent launched successfully.'}
    result = self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file), response)
    self.assertEqual(result.returncode, 0, result.stderr)
    entries = self.read_registry()
    self.assertEqual(len(entries), 1)
    self.assertEqual(entries[0]['agent_id'], 'abc123def0')
    self.assertFalse(entries[0]['foreground'])
    self.assertEqual(self.stub_args(), [])
    self.assertEqual(self.deliver().returncode, 0)
    self.assertIn('--ticket-file', self.stub_args())

  def test_async_launch_without_identity_remains_unreviewed(self):
    response = {'isAsync': True, 'status': 'async_launched'}
    result = self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file), response)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.read_registry(), [])
    self.assertEqual(self.stub_args(), [])
    close = self.hook('gate', {'session_id': self.session, 'tool_name': 'Edit',
                               'tool_input': {'file_path': str(self.ticket_file), 'new_string': '**Status:** `completed`'}})
    decision = json.loads(close.stdout)['hookSpecificOutput']
    self.assertEqual(decision['permissionDecision'], 'deny')
    self.assertIn('YAGNI 未審', decision['permissionDecisionReason'])

  def test_prompt_text_cannot_fake_background_launch(self):
    response = {'isAsync': False, 'status': 'completed', 'result': 'Final result: done',
                'prompt': 'Async agent launched successfully. agentId: fake123456'}
    result = self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file), response)
    self.assertEqual(result.returncode, 0, result.stderr)
    entries = self.read_registry()
    self.assertEqual(len(entries), 1)
    self.assertTrue(entries[0]['foreground'])
    self.assertIn('--ticket-file', self.stub_args())

  def test_prompt_text_cannot_supply_missing_agent_identity(self):
    response = {'isAsync': True, 'status': 'async_launched', 'prompt': 'agentId: fake123456'}
    result = self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file), response)
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.read_registry(), [])
    self.assertEqual(self.stub_args(), [])

  def test_structured_foreground_completion_still_reviews(self):
    response = {'isAsync': False, 'status': 'completed', 'result': 'Final result: done'}
    result = self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file), response)
    self.assertEqual(result.returncode, 0, result.stderr)
    entries = self.read_registry()
    self.assertEqual(len(entries), 1)
    self.assertTrue(entries[0]['foreground'])
    self.assertIn('--ticket-file', self.stub_args())

  def test_codex_identity_only_response_waits_for_delivery(self):
    result = self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file), 'agentId: agent-123')
    self.assertEqual(result.returncode, 0, result.stderr)
    entries = self.read_registry()
    self.assertEqual(len(entries), 1)
    self.assertEqual(entries[0]['agent_id'], 'agent-123')
    self.assertFalse(entries[0]['foreground'])
    self.assertEqual(self.stub_args(), [])

  def test_launch_failure_without_error_prefix_stays_unreviewed(self):
    result = self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file), 'Agent failed to start: timed out')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.read_registry(), [])
    self.assertEqual(self.stub_args(), [])

  def test_arbitrary_text_does_not_claim_foreground_completion(self):
    result = self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file), 'Still pending; retry later')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.read_registry(), [])
    self.assertEqual(self.stub_args(), [])

  def test_failed_launch_with_identity_does_not_register(self):
    result = self.register('Ticket 09 wire', self.prompt_with_path(self.ticket_file),
                           'Error: agent failed to start\nagentId: abc123def0')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.read_registry(), [])
    self.assertEqual(self.stub_args(), [])


if __name__ == '__main__':
  unittest.main()
