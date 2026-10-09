#!/usr/bin/env python3
"""pi-register / pi-deliver 的夾具契約。全部是 temp UUID、假 runner、假 pid。
這不是模型審查，也不起動 pi。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

HOOK = Path(os.environ.get('TICKET_YAGNI_HOOK', str(Path(__file__).resolve().with_name('ticket-yagni.py'))))
STUB = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['PI_STUB_LOG'], 'a') as handle:
    handle.write(json.dumps(sys.argv) + '\\n')
out = sys.argv[sys.argv.index('--out') + 1]
ticket = sys.argv[sys.argv.index('--ticket') + 1]
open(os.path.join(out, 'verdict.json'), 'w').write(json.dumps(
    {'ticket': ticket, 'verdicts': [], 'counts': {'keep': 1, 'demote': 0, 'kill': 0}, 'elapsed': 0.1}))
'''


def git(repo, *args, check=True):
  result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, timeout=60)
  if check and result.returncode != 0:
    raise AssertionError(result.stderr)
  return result


class PiYagniTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)
    self.session = str(uuid.uuid4())
    self.job_uuid = str(uuid.uuid4())
    self.run = 'pi_run'
    decision = self.root / 'matt' / self.session / self.run
    decision.mkdir(parents=True)
    (decision / 'decision.json').write_text(json.dumps(
      {'contract': 'MATT_TDD_DECISION v1', 'status': 'started', 'session_id': self.session, 'run_id': self.run,
       'tickets': [{'id': '09', 'decision': 'required'}]}))
    self.ticket_file = self.root / 'gov' / '.scratch' / 'feat' / 'issues' / '09-wire.md'
    self.ticket_file.parent.mkdir(parents=True)
    self.ticket_file.write_text('# 09 — Wire\n\n**Status:** `ready-for-agent`\n')
    self.decoy = self.ticket_file.parent / '05-other.md'
    self.decoy.write_text('# 05 must stay untouched\n')
    self.service = self.root / 'service'
    self.service.mkdir()
    git(self.service, 'init', '-q')
    git(self.service, 'config', 'user.email', 't@t')
    git(self.service, 'config', 'user.name', 't')
    (self.service / 'README.md').write_text('base\n')
    git(self.service, 'add', '-A')
    git(self.service, 'commit', '-qm', 'base')
    self.worker = self.root / 'worker'
    subprocess.run(['git', 'clone', '-q', str(self.service), str(self.worker)], check=True, capture_output=True)
    git(self.worker, 'config', 'user.email', 't@t')
    git(self.worker, 'config', 'user.name', 't')
    self.base = git(self.worker, 'rev-parse', 'HEAD').stdout.strip()
    self.jobs = self.root / 'jobs'
    self.job = self.jobs / self.session / self.job_uuid
    self.job.mkdir(parents=True)
    self.sleep = subprocess.Popen(['sleep', '120'])
    self.stub = self.root / 'stub-runner.py'
    self.stub.write_text(STUB)
    self.stub.chmod(0o755)
    self.stub_log = self.root / 'stub.jsonl'
    self.env = dict(os.environ)
    self.env.update(TICKET_YAGNI_ROOT=str(self.root / 'yagni'), MATT_TDD_ROOT=str(self.root / 'matt'),
                    TICKET_YAGNI_OFF=str(self.root / 'off'), TICKET_YAGNI_RUNNER=str(self.stub),
                    TICKET_YAGNI_RUNNER_TIMEOUT='20', PI_SUBTASK_JOBS_ROOT=str(self.jobs),
                    PI_STUB_LOG=str(self.stub_log))
    self.original = {self.ticket_file: self.ticket_file.read_bytes(), self.decoy: self.decoy.read_bytes()}

  def tearDown(self):
    if self.sleep.poll() is None:
      self.sleep.kill()
      self.sleep.wait(timeout=5)
    self.tmp.cleanup()

  def hook(self, subcmd, payload):
    return subprocess.run([sys.executable, str(HOOK), subcmd], input=json.dumps(payload),
                          capture_output=True, text=True, env=self.env, timeout=30)

  def call(self, subcmd, session=None, job=None):
    return self.hook(subcmd, {'session_id': session or self.session, 'cwd': str(self.service),
                              'job_dir': str(job or self.job),
                              'tool_response': {'agentId': 'fakeAgent123', 'status': 'completed'}})

  def write_manifest(self, *, agent_type='routed-impl', description='Ticket 09 wire', base=None,
                     pid=None, status='ready', ticket_file=True, prompt=None):
    pid = self.sleep.pid if pid is None else pid
    prompt_path = self.job / 'prompt.txt'
    body = prompt if prompt is not None else f'你的 worktree：{self.worker}\n票檔（只讀）：{self.ticket_file}\n'
    prompt_path.write_text(body)
    manifest = {'session_id': self.session, 'job_id': 'pi-' + self.job_uuid, 'agent_type': agent_type,
                'description': description, 'cwd': str(self.service), 'base_sha': base if base is not None else self.base,
                'prompt_file': str(prompt_path), 'pi_session_id': 'pi-session-01', 'pi_pid': pid,
                'logical_model': 'logical', 'resolved_model': 'resolved', 'effort': 'high'}
    if ticket_file:
      manifest['ticket_file'] = str(self.ticket_file)
    (self.job / 'manifest.json').write_text(json.dumps(manifest))
    (self.job / 'state.json').write_text(json.dumps(
      {'status': status, 'pi_session_id': 'pi-session-01', 'pi_pid': pid}))
    return manifest

  def write_round(self, number, *, status='completed', settled=True, text='worker finished\n', name='body.txt'):
    folder = self.job / 'rounds' / str(number)
    folder.mkdir(parents=True, exist_ok=True)
    body = folder / name
    if text is not None:
      body.write_text(text)
    result = {'status': status, 'text_file': str(body), 'full_body_path': str(body), 'settled': settled}
    (folder / 'result.json').write_text(json.dumps(result))
    return result

  def point_at_last(self):
    rounds = sorted((p for p in (self.job / 'rounds').iterdir() if p.name.isdigit()), key=lambda p: int(p.name))
    (self.job / 'result.json').write_text((rounds[-1] / 'result.json').read_text())

  def registry(self):
    path = self.root / 'yagni' / self.session / 'workers.jsonl'
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

  def stub_calls(self):
    if not self.stub_log.exists():
      return []
    return [json.loads(line) for line in self.stub_log.read_text().splitlines() if line.strip()]

  def assert_untouched(self):
    for path, content in self.original.items():
      self.assertEqual(path.read_bytes(), content)

  def test_register_is_idempotent_and_ignores_fake_agent_response(self):
    self.write_manifest()
    first = self.call('pi-register')
    self.assertEqual(first.returncode, 0, first.stderr)
    second = self.call('pi-register')
    self.assertEqual(second.returncode, 0, second.stderr)
    entries = self.registry()
    self.assertEqual(len(entries), 1)
    self.assertEqual(entries[0]['agent_id'], 'pi-' + self.job_uuid)
    self.assertEqual(entries[0]['backend'], 'pi-subtask')
    self.assertEqual(entries[0]['base_sha'], self.base)
    self.assertEqual(entries[0]['ticket'], '09')
    self.assertEqual(entries[0].get('ticket_file'), str(self.ticket_file))
    self.assertEqual(os.path.realpath(entries[0]['job_dir']), os.path.realpath(self.job))
    self.assertNotEqual(entries[0]['agent_id'], 'fakeAgent123')
    self.assertEqual(self.stub_calls(), [])
    self.assert_untouched()

  def test_gate_denies_close_until_delivery_reviews_once(self):
    self.write_manifest(status='ready')
    self.assertEqual(self.call('pi-register').returncode, 0)
    close = self.hook('gate', {'session_id': self.session, 'tool_name': 'Edit',
                               'tool_input': {'file_path': str(self.ticket_file), 'new_string': '**Status:** `completed`'}})
    decision = json.loads(close.stdout)['hookSpecificOutput']
    self.assertEqual(decision['permissionDecision'], 'deny')
    self.assertIn('沒有交件審查紀錄', decision['permissionDecisionReason'])
    self.assertEqual(self.stub_calls(), [])
    newer = self.root / 'matt' / self.session / 'later_run'
    newer.mkdir()
    (newer / 'decision.json').write_text(json.dumps(
      {'contract': 'MATT_TDD_DECISION v1', 'status': 'started', 'session_id': self.session, 'run_id': 'later_run',
       'tickets': [{'id': '09', 'decision': 'required'}]}))
    os.utime(newer / 'decision.json', (4_000_000_000, 4_000_000_000))
    (self.job / 'state.json').write_text(json.dumps(
      {'status': 'completed', 'pi_session_id': 'pi-session-01', 'pi_pid': self.sleep.pid}))
    self.write_round(1)
    self.point_at_last()
    delivered = self.call('pi-deliver')
    self.assertEqual(delivered.returncode, 0, delivered.stderr)
    self.assertIn('additionalContext', delivered.stdout)
    self.assertEqual(len(self.stub_calls()), 1)
    argv = self.stub_calls()[0]
    self.assertEqual(argv[argv.index('--base') + 1], self.base)
    self.assertEqual(argv[argv.index('--run') + 1], self.run)
    self.assertEqual(argv[argv.index('--worktree') + 1], git(self.worker, 'rev-parse', '--show-toplevel').stdout.strip())
    self.assertEqual(argv[argv.index('--ticket-file') + 1], str(self.ticket_file))
    self.assertIn('pi-' + self.job_uuid, argv)
    (self.worker / 'later.txt').write_text('after dispatch\n')
    git(self.worker, 'add', '-A')
    git(self.worker, 'commit', '-qm', 'rework')
    moved = git(self.worker, 'rev-parse', 'HEAD').stdout.strip()
    self.assertNotEqual(moved, self.base)
    kept = self.call('pi-register')
    self.assertEqual(kept.returncode, 0, kept.stderr)
    self.assertEqual(len(self.registry()), 1)
    self.assertEqual(self.registry()[0]['base_sha'], self.base)
    self.write_round(2, text='rework finished\n', name='rework.txt')
    self.point_at_last()
    again = self.call('pi-deliver')
    self.assertEqual(again.returncode, 0, again.stderr)
    self.assertEqual(again.stdout, '')
    self.assertEqual(len(self.stub_calls()), 1)
    self.assertEqual(self.stub_calls()[0][self.stub_calls()[0].index('--base') + 1], self.base)
    self.assertEqual(len(self.registry()), 1)
    allowed = self.hook('gate', {'session_id': self.session, 'tool_name': 'Edit',
                                 'tool_input': {'file_path': str(self.ticket_file), 'new_string': '**Status:** `completed`'}})
    self.assertEqual(allowed.returncode, 0, allowed.stderr)
    self.assertEqual(allowed.stdout, '')
    self.assert_untouched()

  def test_wrong_session_is_rejected(self):
    self.write_manifest()
    other = str(uuid.uuid4())
    mismatch = self.call('pi-register', session=other)
    self.assertNotEqual(mismatch.returncode, 0)
    self.assertEqual(self.registry(), [])
    (self.job / 'manifest.json').write_text(json.dumps({**json.loads((self.job / 'manifest.json').read_text()),
                                                       'session_id': other}))
    lied = self.call('pi-register')
    self.assertNotEqual(lied.returncode, 0, lied.stderr)
    self.assertEqual(self.registry(), [])
    self.assertEqual(self.stub_calls(), [])

  def test_incomplete_ready_and_unsettled_delivery_do_not_register_or_review(self):
    dead = subprocess.Popen(['sleep', '120'])
    dead.kill()
    dead.wait(timeout=5)
    self.write_manifest(pid=dead.pid)
    refused = self.call('pi-register')
    self.assertNotEqual(refused.returncode, 0, refused.stderr)
    self.assertEqual(self.registry(), [])
    self.write_manifest(base='a' * 40)
    self.assertNotEqual(self.call('pi-register').returncode, 0)
    self.assertEqual(self.registry(), [])
    self.write_manifest()
    self.assertEqual(self.call('pi-register').returncode, 0)
    self.write_round(1, settled=False)
    self.point_at_last()
    (self.job / 'state.json').write_text(json.dumps(
      {'status': 'completed', 'pi_session_id': 'pi-session-01', 'pi_pid': self.sleep.pid}))
    unsettled = self.call('pi-deliver')
    self.assertNotEqual(unsettled.returncode, 0, unsettled.stderr)
    self.assertEqual(self.stub_calls(), [])
    self.write_round(1, status='failed', settled=False, text='failed first\n')
    self.write_round(2, text='later success\n', name='later.txt')
    self.point_at_last()
    skipped_first = self.call('pi-deliver')
    self.assertNotEqual(skipped_first.returncode, 0, skipped_first.stderr)
    self.assertEqual(self.stub_calls(), [])
    self.write_round(1, text='first body\n')
    late = self.call('pi-deliver')
    self.assertEqual(late.returncode, 0, late.stderr)
    self.assertEqual(len(self.stub_calls()), 1)
    self.assertEqual(self.stub_calls()[0][self.stub_calls()[0].index('--base') + 1], self.base)
    self.assert_untouched()

  def test_non_impl_and_unmatched_ticket_are_noop(self):
    self.write_manifest(agent_type='typescript-reviewer')
    result = self.call('pi-register')
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(self.registry(), [])
    delivered = self.call('pi-deliver')
    self.assertEqual(delivered.returncode, 0, delivered.stderr)
    self.write_manifest(description='Ticket 05 from the packet')
    self.assertEqual(self.call('pi-register').returncode, 0, )
    self.assertEqual(self.registry(), [])
    self.assertEqual(self.stub_calls(), [])
    self.assert_untouched()

  def test_off_does_not_block_and_bad_json_is_not_success(self):
    self.write_manifest()
    (self.root / 'off').write_text('')
    paused = self.call('pi-register')
    self.assertEqual(paused.returncode, 0, paused.stderr)
    self.assertEqual(self.registry(), [])
    self.env['TICKET_YAGNI_OFF'] = str(self.root / 'missing-off')
    broken = subprocess.run([sys.executable, str(HOOK), 'pi-register'], input='{', capture_output=True,
                            text=True, env=self.env, timeout=30)
    self.assertNotEqual(broken.returncode, 0)
    self.assertEqual(self.registry(), [])

  def test_symlink_hardlink_and_fifo_are_rejected(self):
    self.write_manifest()
    target = self.job / 'manifest-target.json'
    target.write_text((self.job / 'manifest.json').read_text())
    (self.job / 'manifest.json').unlink()
    (self.job / 'manifest.json').symlink_to(target)
    linked = self.call('pi-register')
    self.assertNotEqual(linked.returncode, 0, linked.stderr)
    self.assertEqual(self.registry(), [])
    (self.job / 'manifest.json').unlink()
    (self.job / 'manifest.json').write_text(target.read_text())
    os.link(self.job / 'manifest.json', self.job / 'manifest-hard.json')
    hard = self.call('pi-register')
    self.assertNotEqual(hard.returncode, 0, hard.stderr)
    self.assertEqual(self.registry(), [])
    (self.job / 'manifest-hard.json').unlink()
    (self.job / 'state.json').unlink()
    os.mkfifo(self.job / 'state.json')
    fifo = subprocess.run([sys.executable, str(HOOK), 'pi-register'], input=json.dumps(
      {'session_id': self.session, 'cwd': str(self.service), 'job_dir': str(self.job)}),
      capture_output=True, text=True, env=self.env, timeout=5)
    self.assertNotEqual(fifo.returncode, 0, fifo.stderr)
    self.assertEqual(self.registry(), [])
    self.assertEqual(self.stub_calls(), [])
    self.assert_untouched()


if __name__ == '__main__':
  unittest.main()
