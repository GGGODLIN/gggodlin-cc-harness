#!/usr/bin/env python3
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent
HOOK = ROOT / 'taskoutput-dedup-hook.py'
FAULT = ROOT / 'taskoutput-dedup-hook-fault.py'
A = 'LIVE-A-' + 'a' * 6000 + '\n'
B = 'LIVE-B-' + 'b' * 6000 + '\n'
REJECTED_SHAPES = ['unknown_event', 'unknown_tool', 'non_dict_response', 'non_dict_task', 'missing_result', 'unequal_result', 'empty_output', 'bad_status', 'bad_task_type', 'bad_retrieval', 'task_id_mismatch']


class HookCase(unittest.TestCase):
  def setUp(self):
    self.temp = tempfile.TemporaryDirectory()
    self.addCleanup(self.temp.cleanup)
    self.base = Path(self.temp.name)
    self.root = self.base / 'run'
    self.root.mkdir(mode=0o700)
    self.enable = self.base / 'enable.json'
    self.now = time.time()
    self.write_enable()

  def write_enable(self, version=1, started=None, expires=None):
    body = {
      'version': version,
      'started_at': self.now - 60 if started is None else started,
      'expires_at': self.now + 3600 if expires is None else expires,
    }
    self.enable.write_text(json.dumps(body))
    self.enable.chmod(0o600)

  def invoke(self, payload, root=None, enable=None):
    env = {**os.environ}
    env['TASKOUTPUT_DEDUP_ROOT'] = str(root if root is not None else self.root)
    env['TASKOUTPUT_DEDUP_ENABLE'] = str(enable if enable is not None else self.enable)
    result = subprocess.run(
      [sys.executable, str(HOOK)],
      input=json.dumps(payload),
      text=True,
      capture_output=True,
      env=env,
      timeout=10,
    )
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(result.stderr, '')
    return json.loads(result.stdout)

  def workdir(self, session='session-a', task='task-a'):
    digest = hashlib.sha256(f'{session}\n{task}'.encode()).hexdigest()
    return self.root / digest[:32]

  def task(self, body=A, session='session-a', task='task-a', tool_use_id='toolu-1', transcript='/tmp/transcript.jsonl'):
    return {
      'hook_event_name': 'PostToolUse',
      'tool_name': 'TaskOutput',
      'session_id': session,
      'tool_use_id': tool_use_id,
      'transcript_path': transcript,
      'tool_input': {'task_id': task},
      'tool_response': {
        'retrieval_status': 'not_ready',
        'extra': {'keep': True},
        'task': {
          'task_id': task,
          'task_type': 'local_agent',
          'status': 'running',
          'output': body,
          'result': body,
          'description': 'unchanged',
        },
      },
    }

  def session_start(self, source='startup', session='session-a'):
    return {
      'hook_event_name': 'SessionStart',
      'session_id': session,
      'source': source,
      'transcript_path': f'/tmp/{session}.jsonl',
    }

  def invoke_raw(self, payload, root=None, enable=None, timeout=10):
    env = {**os.environ}
    env['TASKOUTPUT_DEDUP_ROOT'] = str(root if root is not None else self.root)
    env['TASKOUTPUT_DEDUP_ENABLE'] = str(enable if enable is not None else self.enable)
    return subprocess.run(
      [sys.executable, str(HOOK)],
      input=json.dumps(payload),
      text=True,
      capture_output=True,
      env=env,
      timeout=timeout,
    )

  def state_path(self, session='session-a', task='task-a', name='state.json'):
    return self.workdir(session, task) / name

  def lock_path(self, session='session-a', task='task-a'):
    return self.workdir(session, task) / '.lock'

  def snapshot_paths(self, session='session-a', task='task-a'):
    return sorted((self.workdir(session, task)).glob('snapshot-*.txt'))

  def fault(self, mode, payload, root=None, enable=None, timeout=5):
    env = {**os.environ}
    env['TASKOUTPUT_DEDUP_ROOT'] = str(root if root is not None else self.root)
    env['TASKOUTPUT_DEDUP_ENABLE'] = str(enable if enable is not None else self.enable)
    return subprocess.run(
      [sys.executable, str(FAULT), mode],
      input=json.dumps(payload),
      text=True,
      capture_output=True,
      env=env,
      timeout=timeout,
    )

  def assert_passthrough(self, payload, root=None, enable=None):
    self.assertEqual(self.invoke(payload, root=root, enable=enable), {})

  def assert_reference(self, output, expected=A):
    response = output['hookSpecificOutput']['updatedToolOutput']
    marker = response['task']['output']
    self.assertEqual(response['task']['result'], marker)
    snapshot = Path(marker.split('快照：', 1)[1].split('\n', 1)[0])
    self.assertEqual(snapshot.read_bytes(), expected.encode())
    self.assertEqual(stat.S_IMODE(snapshot.stat().st_mode), 0o400)
    return snapshot

  def reference_a(self, **kwargs):
    first = self.invoke(self.task(A, **kwargs))
    self.assertEqual(first, {})
    return self.assert_reference(self.invoke(self.task(A, **kwargs)))

  def rejected_shape(self, name):
    payload = self.task(A)
    if name == 'unknown_event':
      payload['hook_event_name'] = 'PreToolUse'
    elif name == 'unknown_tool':
      payload['tool_name'] = 'Read'
    elif name == 'non_dict_response':
      payload['tool_response'] = []
    elif name == 'non_dict_task':
      payload['tool_response']['task'] = 'task'
    elif name == 'missing_result':
      payload['tool_response']['task'].pop('result')
    elif name == 'unequal_result':
      payload['tool_response']['task']['result'] = 'different'
    elif name == 'empty_output':
      payload['tool_response']['task']['output'] = ''
      payload['tool_response']['task']['result'] = ''
    elif name == 'bad_status':
      payload['tool_response']['task']['status'] = 'completed'
    elif name == 'bad_task_type':
      payload['tool_response']['task']['task_type'] = 'local_bash'
    elif name == 'bad_retrieval':
      payload['tool_response']['retrieval_status'] = 'completed'
    elif name == 'task_id_mismatch':
      payload['tool_input']['task_id'] = 'other'
    else:
      raise AssertionError(name)
    return payload

  def reference(self, body=A, **kwargs):
    output = self.invoke(self.task(body, **kwargs))
    response = output['hookSpecificOutput']['updatedToolOutput']
    marker = response['task']['output']
    snapshot = Path(marker.split('快照：', 1)[1].split('\n', 1)[0])
    return snapshot, response, marker

  def audit_rows(self, session='session-a'):
    path = self.root / f'audit-{hashlib.sha256(session.encode()).hexdigest()[:32]}.jsonl'
    if not path.exists():
      return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]

  def test_disabled_without_enable_file_passes_through_and_writes_no_state(self):
    self.enable.unlink()
    self.assertEqual(self.invoke(self.task(A)), {})
    self.assertEqual(self.invoke(self.task(A)), {})
    self.assertEqual(list(self.root.iterdir()), [])
    self.assertEqual(self.invoke(self.session_start()), {})
    self.assertEqual(list(self.root.iterdir()), [])

  def test_non_object_valid_json_passes_through(self):
    for raw in ['null', '[]', '"text"', '42', 'true', 'false']:
      with self.subTest(raw=raw):
        result = subprocess.run(
          [sys.executable, str(HOOK)],
          input=raw,
          text=True,
          capture_output=True,
          env={**os.environ, 'TASKOUTPUT_DEDUP_ROOT': str(self.root), 'TASKOUTPUT_DEDUP_ENABLE': str(self.enable)},
          timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {})
    self.assertEqual(list(self.root.iterdir()), [])

  def test_expired_or_invalid_enable_config_passes_through(self):
    self.write_enable(expires=self.now - 1)
    self.assertEqual(self.invoke(self.task(A)), {})
    self.assertEqual(self.invoke(self.task(A)), {})
    self.assertFalse((self.workdir()).exists())
    self.write_enable(version=99)
    self.assertEqual(self.invoke(self.task(A)), {})
    self.assertFalse((self.workdir()).exists())
    self.enable.write_text('{ not json')
    self.assertEqual(self.invoke(self.task(A)), {})
    self.assertFalse((self.workdir()).exists())
    self.write_enable()
    self.enable.chmod(0o644)
    self.assertEqual(self.invoke(self.task(A)), {})
    self.assertFalse((self.workdir()).exists())

  def test_first_unchanged_then_second_identical_requests_reference(self):
    self.assertEqual(self.invoke(self.task(A)), {})
    candidate = self.workdir() / 'candidate.txt'
    self.assertEqual(candidate.read_bytes(), A.encode())
    snapshot, response, marker = self.reference(A)
    self.assertEqual(snapshot.read_bytes(), A.encode())
    self.assertLess(len(marker.encode()), len(A.encode()))
    self.assertEqual(response['task']['result'], marker)
    self.assertIn('此提示不是本文證據', marker)
    self.assertIn('若回答所需內容不在現有 context，先查原文快照', marker)
    self.assertIn('grep/rg 限定輸出範圍搜尋', marker)
    self.assertIn('Read(offset, limit) 分段讀；無搜尋工具時直接分段讀', marker)
    self.assertIn('需要完整內容時持續分段讀完', marker)
    self.assertTrue(marker.endswith(f'原文快照：{snapshot}'))
    original = self.task(A)
    restored = copy.deepcopy(response)
    restored['task']['output'] = restored['task']['result'] = snapshot.read_bytes().decode()
    self.assertEqual(restored, original['tool_response'])

  def test_running_timeout_identical_body_requests_reference(self):
    first = self.task(A)
    first['tool_response']['retrieval_status'] = 'timeout'
    self.assertEqual(self.invoke(first), {})
    second = self.task(A)
    second['tool_response']['retrieval_status'] = 'timeout'
    self.assert_reference(self.invoke(second))
    failed = self.task(A)
    failed['tool_response']['retrieval_status'] = 'timeout'
    failed['tool_response']['task']['status'] = 'failed'
    self.assertEqual(self.invoke(failed), {})
    success = self.task(A)
    success['tool_response']['retrieval_status'] = 'success'
    self.assertEqual(self.invoke(success), {})

  def test_non_body_fields_unchanged(self):
    self.invoke(self.task(A))
    _, response, _ = self.reference(A)
    original = self.task(A)['tool_response']
    self.assertEqual(response['extra'], original['extra'])
    self.assertEqual(response['retrieval_status'], original['retrieval_status'])
    for key in original['task']:
      if key in ('output', 'result'):
        continue
      self.assertEqual(response['task'][key], original['task'][key])

  def test_changed_body_keeps_separate_immutable_snapshots(self):
    self.invoke(self.task(A))
    snapshot_a, _, _ = self.reference(A)
    self.assertEqual(self.invoke(self.task(B)), {})
    self.assertEqual((self.workdir() / 'candidate.txt').read_bytes(), B.encode())
    snapshot_b, _, _ = self.reference(B)
    self.assertNotEqual(snapshot_a, snapshot_b)
    self.assertEqual(snapshot_a.read_bytes(), A.encode())
    self.assertEqual(snapshot_b.read_bytes(), B.encode())
    self.assertEqual(stat.S_IMODE(snapshot_a.stat().st_mode), 0o400)

  def test_unknown_shape_empty_and_unequal_bodies_pass_through(self):
    self.assertEqual(self.invoke(self.task(A)), {})
    broken = self.task(A)
    broken['tool_response']['task']['result'] = 'different'
    self.assertEqual(self.invoke(broken), {})
    empty = self.task(A)
    empty['tool_response']['task']['output'] = ''
    empty['tool_response']['task']['result'] = ''
    self.assertEqual(self.invoke(empty), {})
    not_ready = self.task(A)
    not_ready['tool_response']['retrieval_status'] = 'completed'
    self.assertEqual(self.invoke(not_ready), {})
    wrong_type = self.task(A)
    wrong_type['tool_response']['task']['task_type'] = 'local_bash'
    self.assertEqual(self.invoke(wrong_type), {})
    other_tool = self.task(A)
    other_tool['tool_name'] = 'Read'
    self.assertEqual(self.invoke(other_tool), {})
    mismatch = self.task(A)
    mismatch['tool_input']['task_id'] = 'other'
    self.assertEqual(self.invoke(mismatch), {})
    self.assertEqual(self.invoke(self.task(A, session='session-z')), {})

  def test_identity_isolated_per_session_and_task(self):
    self.invoke(self.task(A, session='s1', task='t1'))
    self.invoke(self.task(A, session='s2', task='t2'))
    self.invoke(self.task(A, session='s1', task='t2'))
    self.assertNotEqual(self.invoke(self.task(A, session='s1', task='t1')), {})
    self.assertNotEqual(self.invoke(self.task(A, session='s2', task='t2')), {})
    self.assertNotEqual(self.invoke(self.task(A, session='s1', task='t2')), {})
    self.assertTrue((self.workdir('s1', 't1') / 'candidate.txt').exists())
    self.assertTrue((self.workdir('s2', 't2') / 'candidate.txt').exists())
    self.assertTrue((self.workdir('s1', 't2') / 'candidate.txt').exists())
    entries = list(self.root.iterdir())
    self.assertEqual(sorted(e.name for e in entries if e.is_dir()), sorted({self.workdir('s1', 't1').name, self.workdir('s2', 't2').name, self.workdir('s1', 't2').name}))
    self.assertEqual([e.name for e in entries if not e.is_dir()], [f'audit-{hashlib.sha256(b"s1").hexdigest()[:32]}.jsonl', f'audit-{hashlib.sha256(b"s2").hexdigest()[:32]}.jsonl'])

  def test_marker_not_shorter_passes_through(self):
    tiny = 'x'
    self.invoke(self.task(tiny))
    self.assertEqual(self.invoke(self.task(tiny)), {})

  def test_state_file_carries_no_content_digest(self):
    self.assertEqual(self.invoke(self.task(A)), {})
    state = json.loads(self.state_path().read_text())
    self.assertEqual(set(state), {'session', 'task', 'generation', 'bytes', 'confirmed'})
    self.assertEqual(state['bytes'], len(A.encode()))

  def test_snapshot_mismatch_passes_through(self):
    self.invoke(self.task(A))
    digest = hashlib.sha256(A.encode()).hexdigest()
    snapshot = self.workdir() / f'snapshot-{digest}.txt'
    snapshot.write_text('tampered')
    snapshot.chmod(0o400)
    self.assertEqual(self.invoke(self.task(A)), {})

  def test_audit_records_request_without_body(self):
    self.invoke(self.task(A, tool_use_id='toolu-a'))
    self.invoke(self.task(A, tool_use_id='toolu-b'))
    self.invoke(self.task('x' * 3))
    rows = self.audit_rows()
    self.assertGreaterEqual(len(rows), 3)
    first = rows[0]
    self.assertEqual(first['event'], 'PostToolUse')
    self.assertEqual(first['action'], 'first_full')
    self.assertEqual(first['shape'], 'accepted')
    self.assertEqual(first['body_bytes'], len(A.encode()))
    self.assertEqual(first['marker_bytes'], 0)
    self.assertEqual(first['reason'], 'created')
    self.assertIsInstance(first['timestamp'], float)
    self.assertEqual(first['session_hash'], hashlib.sha256(b'session-a').hexdigest()[:32])
    self.assertEqual(first['tool_use_id'], 'toolu-a')
    self.assertEqual(first['transcript_path'], '/tmp/transcript.jsonl')
    self.assertEqual(first['action'], 'first_full')
    self.assertIsInstance(first['body_bytes'], int)
    self.assertIsInstance(first['elapsed_ms'], int)
    self.assertGreaterEqual(first['elapsed_ms'], 0)
    self.assertFalse(first['rewrite_requested'])
    second = rows[1]
    self.assertTrue(second['rewrite_requested'])
    self.assertEqual(second['action'], 'rewrite_requested')
    self.assertEqual(first['task_hash'], hashlib.sha256(b'task-a').hexdigest()[:32])
    self.assertEqual(second['task_hash'], hashlib.sha256(b'task-a').hexdigest()[:32])
    for row in rows:
      joined = json.dumps(row)
      self.assertNotIn(A[:40], joined)
      self.assertNotIn('LIVE-A-', joined)

  def test_audit_failure_preserves_original_result(self):
    self.invoke(self.task(A))
    audit_path = self.root / f'audit-{hashlib.sha256(b"session-a").hexdigest()[:32]}.jsonl'
    audit_path.write_text('existing')
    audit_path.chmod(0o000)
    try:
      self.assertEqual(self.invoke(self.task(A)), {})
    finally:
      audit_path.chmod(0o600)

  def test_lifecycle_sources_reset_generation_for_next_body(self):
    for source in ['startup', 'resume', 'clear', 'compact']:
      with self.subTest(source=source):
        session = f'session-{source}'
        self.reference_a(session=session)
        self.assert_reference(self.invoke(self.task(A, session=session)))
        self.assert_passthrough(self.session_start(source, session=session))
        self.assert_passthrough(self.task(A, session=session))
        self.assert_reference(self.invoke(self.task(A, session=session)))

  def test_repeated_and_unknown_session_start_sources_never_stale(self):
    self.reference_a()
    for source in ['startup', 'startup', 'unknown-source', 'resume', 'clear', 'clear']:
      with self.subTest(source=source):
        self.assert_passthrough(self.session_start(source))
        self.assert_passthrough(self.task(A))
    self.assert_reference(self.invoke(self.task(A)))

  def test_session_start_without_usable_identity_writes_no_state(self):
    self.assertEqual(self.invoke(self.session_start(session='')), {})
    self.assert_passthrough({'hook_event_name': 'SessionStart', 'session_id': 'session-a'})
    self.assert_passthrough({'hook_event_name': 'SessionStart', 'source': 'startup'})
    self.assertEqual(list(self.root.iterdir()), [])

  def test_lock_busy_returns_promptly_with_original_output(self):
    self.assert_passthrough(self.task(A))
    lock_path = self.lock_path()
    with lock_path.open('r+') as lock:
      fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
      started = time.monotonic()
      self.assert_passthrough(self.task(A))
      elapsed = time.monotonic() - started
      self.assertLess(elapsed, 2.0)
      self.assert_passthrough(self.session_start('startup'))
      rows = self.audit_rows()
      actions = [row['action'] for row in rows]
      self.assertIn('lock_busy', actions)
      self.assertIn('pass_through', actions)
    self.assertTrue((self.workdir() / 'invalidate').exists())
    self.assert_passthrough(self.task(A))
    self.assertFalse((self.workdir() / 'invalidate').exists())
    self.assert_reference(self.invoke(self.task(A)))

  def test_identity_mismatch_never_shares_state(self):
    session = 'session-a'
    task_a = 'task-a'
    target = self.workdir(session, task_a)
    target.mkdir(mode=0o700)
    foreign = {'session': session, 'task': 'other-task', 'generation': 0, 'bytes': len(B.encode()), 'confirmed': True}
    foreign_bytes = json.dumps(foreign).encode()
    (target / 'state.json').write_bytes(foreign_bytes)
    (target / 'state.json').chmod(0o600)
    (target / 'candidate.txt').write_bytes(B.encode())
    (target / 'candidate.txt').chmod(0o600)
    self.assert_passthrough(self.task(A, session=session, task=task_a))
    self.assertEqual((target / 'state.json').read_bytes(), foreign_bytes)
    self.assertEqual((target / 'candidate.txt').read_bytes(), B.encode())
    rows = self.audit_rows(session)
    self.assertEqual(rows[-1]['action'], 'pass_through')
    self.assertEqual(rows[-1]['reason'], 'state_mismatch')

  def test_pending_state_passes_through_without_repair(self):
    self.reference_a()
    pending = self.state_path(name='state.pending')
    pending.write_bytes(b'{"session": "session-a", "task": "task-a"}')
    before = pending.read_bytes()
    self.assert_passthrough(self.task(A))
    self.assert_passthrough(self.task(A))
    self.assertEqual(pending.read_bytes(), before)
    self.assertEqual(self.audit_rows()[-1]['action'], 'pass_through')

  def test_interrupted_writes_pass_through_or_reference_a_safe_identity(self):
    self.assert_passthrough(self.task(A))
    state = self.state_path()
    state.chmod(0o644)
    self.assert_passthrough(self.task(A))
    state.chmod(0o600)
    snapshot = self.assert_reference(self.invoke(self.task(A)))
    snapshot.chmod(0o600)
    snapshot.write_bytes(b'corrupted')
    self.assert_passthrough(self.task(A))
    self.assertEqual(snapshot.read_bytes(), b'corrupted')
    snapshot.unlink()
    candidate = self.workdir() / 'candidate.txt'
    candidate.write_bytes(A.encode()[:20])
    self.assert_passthrough(self.task(A))
    candidate.write_text('{ not json')
    self.assert_passthrough(self.task(A))
    state.write_text('{ not json')
    self.assert_passthrough(self.task(A))
    state.write_text(json.dumps({'session': 'session-a', 'task': 'task-a', 'generation': 0, 'digest': 'x', 'bytes': 1, 'extra': True}))
    self.assert_passthrough(self.task(A))
    self.assertNotIn('updatedToolOutput', json.dumps(self.invoke(self.task(A))))

  def test_damaged_generation_passes_through_without_repair(self):
    self.reference_a()
    generation = self.workdir() / 'generation.json'
    self.assertTrue(generation.exists())
    generation.write_text('{ damaged')
    self.assert_passthrough(self.task(A))
    self.assertEqual(generation.read_text(), '{ damaged')
    self.assertEqual(self.audit_rows()[-1]['reason'], 'generation_unreadable')
    generation.chmod(0o644)
    self.assert_passthrough(self.task(A))
    self.assertEqual(self.audit_rows()[-1]['reason'], 'generation_unreadable')
    generation.chmod(0o600)
    pending = self.workdir() / 'generation.pending'
    pending.write_bytes(b'running')
    self.assert_passthrough(self.task(A))
    self.assertEqual(self.audit_rows()[-1]['reason'], 'pending_state')
    pending.unlink()
    self.assert_passthrough(self.task(A))
    self.assertEqual(generation.read_text(), '{ damaged')
    generation.write_text(json.dumps({'generation': 0}))
    self.assert_reference(self.invoke(self.task(A)))

  def test_pathological_targets_do_not_write_through_or_publish(self):
    self.assert_passthrough(self.task(A))
    self.assert_reference(self.invoke(self.task(A)))
    workdir = self.workdir()
    candidate = workdir / 'candidate.txt'
    victim = self.base / 'victim.txt'
    victim.write_bytes(b'VICTIM')
    snapshot_name = f'snapshot-{hashlib.sha256(A.encode()).hexdigest()}.txt'
    snapshot = workdir / snapshot_name

    snapshot.unlink()
    os.symlink(victim, snapshot)
    self.assert_passthrough(self.task(A))
    self.assertEqual(victim.read_bytes(), b'VICTIM')

    snapshot.unlink()
    os.link(victim, snapshot)
    self.assert_passthrough(self.task(A))
    self.assertEqual(victim.read_bytes(), b'VICTIM')
    snapshot.unlink()

    os.mkfifo(snapshot)
    self.assert_passthrough(self.task(A))
    snapshot.unlink()

    candidate.chmod(0o644)
    self.assert_passthrough(self.task(A))
    candidate.chmod(0o600)
    self.assertEqual(candidate.read_bytes(), A.encode())

    candidate.write_bytes(A.encode()[:20])
    self.assert_passthrough(self.task(A))
    self.assertEqual(candidate.read_bytes(), A.encode()[:20])
    self.assertEqual(victim.read_bytes(), b'VICTIM')

  def test_fault_injection_at_fsync_never_publishes_reference(self):
    result = self.fault('after-fsync', self.task(A))
    self.assertNotEqual(result.returncode, 0)
    self.assertNotIn('updatedToolOutput', result.stdout)
    self.assertEqual(self.invoke(self.task(A)), {})
    rows = self.audit_rows()
    self.assertTrue(all(row['action'] != 'rewrite_requested' for row in rows))
    self.assertEqual(self.snapshot_paths(), [])

  def test_fault_injection_interrupts_candidate_write_without_corruption(self):
    self.assert_passthrough(self.task(A))
    self.assert_reference(self.invoke(self.task(A)))
    snapshot = self.snapshot_paths()[0]
    before = snapshot.read_bytes()
    result = self.fault('partial-write', self.task(B))
    self.assertNotIn('updatedToolOutput', result.stdout)
    self.assert_passthrough(self.task(B))
    self.assertEqual(snapshot.read_bytes(), before)
    self.assertEqual(len(self.snapshot_paths()), 1)

  def test_fault_injection_before_replace_leaves_original_intact(self):
    self.assert_passthrough(self.task(A))
    result = self.fault('before-replace', self.task(B))
    self.assertNotIn('updatedToolOutput', result.stdout)
    self.assert_passthrough(self.task(A))
    self.assertEqual((self.workdir() / 'candidate.txt').read_bytes(), A.encode())

  def test_fault_injection_write_error_passes_through(self):
    result = self.fault('write-error', self.task(A))
    self.assertNotIn('updatedToolOutput', result.stdout)
    self.assert_passthrough(self.task(A))
    self.assertFalse((self.workdir() / 'candidate.txt').exists())
    self.assertEqual(self.snapshot_paths(), [])

  def test_sentinel_survives_interrupted_generation_bump(self):
    self.assert_passthrough(self.task(A))
    self.assertTrue((self.workdir() / 'generation.json').exists())
    (self.workdir() / 'invalidate').write_bytes(b'1')
    result = self.fault('before-replace', self.task(A))
    self.assertNotEqual(result.returncode, 0)
    self.assertNotIn('updatedToolOutput', result.stdout)
    self.assertTrue((self.workdir() / 'invalidate').exists())
    self.assert_passthrough(self.task(A))

  def test_stale_generation_pending_keeps_invalidation_until_consumed(self):
    self.assert_passthrough(self.task(A))
    (self.workdir() / 'generation.pending').write_bytes(b'{"generation": 1}')
    self.assert_passthrough(self.session_start('startup'))
    last = self.audit_rows()[-1]
    self.assertEqual(last['event'], 'SessionStart')
    self.assertEqual(last['action'], 'pass_through')
    self.assertIn(last['reason'], ['generation_uncertain', 'lock_busy'])
    self.assertTrue((self.workdir() / 'invalidate').exists())
    self.assert_passthrough(self.task(A))
    self.assertTrue((self.workdir() / 'invalidate').exists())
    (self.workdir() / 'generation.pending').unlink()
    self.assert_passthrough(self.task(A))
    self.assertFalse((self.workdir() / 'invalidate').exists())
    self.assert_reference(self.invoke(self.task(A)))

  def test_session_start_skips_unsafe_workdir_without_writing(self):
    self.assert_passthrough(self.task(A))
    workdir = self.workdir()
    foreign = {'session': 'session-a', 'task': 'task-unsafe', 'generation': 0, 'digest': 'x', 'bytes': 1}
    unsafe = self.workdir('session-a', 'task-unsafe')
    unsafe.mkdir(mode=0o755)
    (unsafe / 'state.json').write_text(json.dumps(foreign))
    foreign_bytes = (unsafe / 'state.json').read_bytes()
    self.assert_passthrough(self.session_start('startup'))
    self.assertEqual(stat.S_IMODE(unsafe.stat().st_mode), 0o755)
    self.assertEqual((unsafe / 'state.json').read_bytes(), foreign_bytes)
    self.assertFalse((unsafe / 'generation.json').exists())
    self.assertFalse((unsafe / 'invalidate').exists())
    self.assertEqual((workdir / 'generation.json').read_text(), '{"generation": 1}')
    self.assert_passthrough(self.task(A))
    self.assert_reference(self.invoke(self.task(A)))

  def test_session_start_continues_after_unreadable_workdir(self):
    self.assert_passthrough(self.task(A))
    broken = self.workdir('session-a', 'task-taskb')
    broken.mkdir(mode=0o700)
    (broken / 'state.json').write_text(json.dumps({'session': 'session-a', 'task': 'taskb', 'generation': 0, 'digest': 'x', 'bytes': 1}))
    (broken / 'state.json').chmod(0o600)
    (broken / 'generation.json').write_text('{ damaged')
    self.assert_passthrough(self.session_start('startup'))
    reset = self.workdir()
    self.assertEqual((reset / 'generation.json').read_text(), '{"generation": 1}')
    self.assertTrue((broken / 'invalidate').exists())
    session_rows = [row for row in self.audit_rows() if row['event'] == 'SessionStart']
    self.assertEqual(len(session_rows), 1)
    self.assertNotEqual(session_rows[-1]['reason'], 'generation_reset')
    self.assertEqual(session_rows[-1]['action'], 'pass_through')
    self.assert_passthrough(self.task(A))
    self.assert_reference(self.invoke(self.task(A)))

  def test_session_start_without_matching_workdir_is_not_reset(self):
    other = self.workdir('session-other', 'task-other')
    other.mkdir(mode=0o700)
    (other / 'state.json').write_text(json.dumps({'session': 'session-other', 'task': 'task-other', 'generation': 0, 'digest': 'x', 'bytes': 1}))
    (other / 'state.json').chmod(0o600)
    (other / 'generation.json').write_text('{"generation": 0}')
    (other / 'generation.json').chmod(0o600)
    self.assert_passthrough(self.session_start('startup'))
    self.assertEqual((other / 'generation.json').read_text(), '{"generation": 0}')
    session_rows = [row for row in self.audit_rows() if row['event'] == 'SessionStart']
    self.assertEqual(len(session_rows), 1)
    self.assertNotEqual(session_rows[-1]['reason'], 'generation_reset')

  def test_unsafe_lock_file_is_not_reported_as_lock_busy(self):
    self.assert_passthrough(self.task(A))
    lock = self.lock_path()
    lock.chmod(0o644)
    try:
      self.assert_passthrough(self.task(A))
      rows = self.audit_rows()
      self.assertNotEqual(rows[-1]['action'], 'lock_busy')
      self.assertEqual(rows[-1]['action'], 'pass_through')
      self.assertNotIn('updatedToolOutput', json.dumps(self.task(A)))
    finally:
      lock.chmod(0o600)

  def test_fault_interrupts_snapshot_publish_before_reference(self):
    self.assert_passthrough(self.task(A))
    result = self.fault('partial-write', self.task(A))
    self.assertNotEqual(result.returncode, 0)
    self.assertNotIn('updatedToolOutput', result.stdout)
    rows = self.audit_rows()
    self.assertTrue(all(row['action'] != 'rewrite_requested' for row in rows))
    self.assert_passthrough(self.task(A))
    self.assert_passthrough(self.task(A))

  def test_fault_interrupts_session_start_invalidation(self):
    self.assert_passthrough(self.task(A))
    self.assert_reference(self.invoke(self.task(A)))
    result = self.fault('before-replace', {'hook_event_name': 'SessionStart', 'session_id': 'session-a', 'source': 'startup', 'transcript_path': '/tmp/session-a.jsonl'})
    self.assertNotEqual(result.returncode, 0)
    self.assertNotIn('updatedToolOutput', result.stdout)
    self.assertEqual((self.workdir() / 'generation.json').read_text(), '{"generation": 0}')
    self.assert_passthrough(self.task(A))
    self.assertEqual(self.snapshot_paths()[0].read_bytes(), A.encode())

  def test_partial_workdir_state_never_initializes(self):
    workdir = self.workdir()
    workdir.mkdir(mode=0o700)
    (workdir / 'candidate.txt').write_bytes(A.encode())
    self.assert_passthrough(self.task(A))
    self.assertFalse((workdir / 'state.json').exists())
    rows = self.audit_rows()
    self.assertEqual(rows[-1]['action'], 'pass_through')
    self.assertEqual(rows[-1]['body_bytes'], 0)

  def test_session_start_marks_uncertain_when_enumerated_dir_unsafe(self):
    self.assert_passthrough(self.task(A))
    unsafe = self.workdir('session-a', 'task-unsafe')
    unsafe.mkdir(mode=0o755)
    self.assert_passthrough(self.session_start('startup'))
    session_rows = [row for row in self.audit_rows() if row['event'] == 'SessionStart']
    self.assertEqual(len(session_rows), 1)
    self.assertEqual(session_rows[-1]['action'], 'pass_through')
    self.assertNotEqual(session_rows[-1]['reason'], 'generation_reset')
    self.assertEqual(stat.S_IMODE(unsafe.stat().st_mode), 0o755)
    self.assertEqual(sorted(p.name for p in unsafe.iterdir()), [])

  def test_taskoutput_unreadable_workdir_records_body_free_pass_through(self):
    self.assert_passthrough(self.task(A))
    workdir = self.workdir()
    self.assertTrue((workdir / 'candidate.txt').exists())
    workdir.chmod(0o755)
    try:
      self.assert_passthrough(self.task(A))
      rows = self.audit_rows()
      self.assertEqual(rows[-1]['event'], 'PostToolUse')
      self.assertEqual(rows[-1]['action'], 'pass_through')
      self.assertEqual(rows[-1]['reason'], 'workdir_unreadable')
      self.assertEqual(rows[-1]['body_bytes'], 0)
    finally:
      workdir.chmod(0o700)

  def test_first_full_crash_after_state_replace_next_call_is_full(self):
    result = self.fault('after-second-replace', self.task(A))
    self.assertEqual(result.returncode, -9)
    self.assertNotIn('updatedToolOutput', result.stdout)
    self.assertEqual(self.workdir() / 'state.json' and (self.workdir() / 'state.json').exists(), True)
    self.assertFalse((self.workdir() / 'generation.json').exists())
    self.assertEqual(self.snapshot_paths(), [])
    self.assertEqual(self.invoke(self.task(A)), {})
    self.assert_reference(self.invoke(self.task(A)))

  def test_generation_reset_crash_after_state_replace_next_call_is_full(self):
    self.assert_passthrough(self.task(A))
    self.assert_passthrough(self.session_start('startup'))
    result = self.fault('after-second-replace', self.task(A))
    self.assertEqual(result.returncode, -9)
    self.assertNotIn('updatedToolOutput', result.stdout)
    self.assertEqual(self.invoke(self.task(A)), {})
    self.assert_reference(self.invoke(self.task(A)))

  def test_changed_full_crash_before_confirmation_next_call_is_full(self):
    self.assert_passthrough(self.task(A))
    result = self.fault('after-second-replace', self.task(B))
    self.assertEqual(result.returncode, -9)
    self.assertEqual(result.stdout, '')
    state = json.loads((self.workdir() / 'state.json').read_text())
    self.assertEqual(state['confirmed'], False)
    self.assertNotIn('digest', state)
    self.assertEqual(state['bytes'], len(B.encode()))
    self.assert_passthrough(self.task(B))
    self.assertEqual(json.loads((self.workdir() / 'state.json').read_text())['confirmed'], True)
    self.assert_reference(self.invoke(self.task(B)), expected=B)

  def test_confirmation_lock_busy_is_best_effort(self):
    result = self.fault('confirm-lock-busy', self.task(A))
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(result.stdout, '{}')
    self.assertEqual(result.stderr, '')
    state = json.loads((self.workdir() / 'state.json').read_text())
    self.assertEqual(state['confirmed'], False)
    self.assertEqual(self.invoke(self.task(A)), {})
    self.assertEqual(json.loads((self.workdir() / 'state.json').read_text())['confirmed'], True)
    self.assert_reference(self.invoke(self.task(A)))

  def test_changed_body_after_unconfirmed_crash_progresses(self):
    result = self.fault('after-second-replace', self.task(A))
    self.assertEqual(result.returncode, -9)
    self.assertEqual(json.loads((self.workdir() / 'state.json').read_text())['confirmed'], False)
    self.assert_passthrough(self.task(B))
    state = json.loads((self.workdir() / 'state.json').read_text())
    self.assertNotIn('digest', state)
    self.assertEqual(state['bytes'], len(B.encode()))
    self.assertEqual(state['confirmed'], True)
    self.assert_reference(self.invoke(self.task(B)), expected=B)

  def test_relative_root_yields_absolute_snapshot_marker(self):
    relative = 'relroot'
    env = {**os.environ, 'TASKOUTPUT_DEDUP_ROOT': relative, 'TASKOUTPUT_DEDUP_ENABLE': str(self.enable)}
    self.root = self.base / relative
    run = lambda payload: subprocess.run(
      [sys.executable, str(HOOK)],
      input=json.dumps(payload),
      text=True,
      capture_output=True,
      env=env,
      cwd=str(self.base),
      timeout=10,
    )
    self.assertEqual(run(self.task(A)).returncode, 0)
    result = run(self.task(A))
    self.assertEqual(result.returncode, 0, result.stderr)
    output = json.loads(result.stdout)
    marker = output['hookSpecificOutput']['updatedToolOutput']['task']['output']
    snapshot = marker.split('快照：', 1)[1].split('\n', 1)[0]
    self.assertTrue(os.path.isabs(snapshot), snapshot)
    self.assertEqual(Path(snapshot).resolve(), (self.root / self.workdir().name / Path(snapshot).name).resolve())
    self.assertEqual(Path(snapshot).read_bytes(), A.encode())

  def test_audit_rows_cover_enabled_taskoutput_and_session_start(self):
    self.assert_passthrough(self.task(A, tool_use_id='toolu-1'))
    self.assert_reference(self.invoke(self.task(A, tool_use_id='toolu-2')))
    self.assert_passthrough(self.task(B, tool_use_id='toolu-3'))
    self.assert_reference(self.invoke(self.task(B, tool_use_id='toolu-4')), expected=B)
    self.assert_passthrough(self.session_start('compact'))
    for shape in REJECTED_SHAPES:
      with self.subTest(shape=shape):
        self.assert_passthrough(self.rejected_shape(shape))
    rows = self.audit_rows()
    actions = [row['action'] for row in rows]
    self.assertEqual(actions[0], 'first_full')
    self.assertIn('rewrite_requested', actions)
    self.assertIn('changed_full', actions)
    for row in rows:
      self.assertIsInstance(row['timestamp'], float)
      self.assertIsInstance(row['session_hash'], str)
      self.assertIsInstance(row['shape'], str)
      self.assertIsInstance(row['body_bytes'], int)
      self.assertIsInstance(row['marker_bytes'], int)
      self.assertIsInstance(row['elapsed_ms'], int)
      self.assertIsInstance(row['reason'], str)
      self.assertIn(row['action'], ['first_full', 'changed_full', 'rewrite_requested', 'lock_busy', 'pass_through'])
      self.assertIn(row['event'], ['PostToolUse', 'SessionStart'])
      self.assertNotIn('bytes', row)
    session_rows = [row for row in rows if row['event'] == 'SessionStart']
    self.assertEqual(len(session_rows), 1)
    self.assertEqual(session_rows[0]['source'], 'compact')
    self.assertEqual(session_rows[0]['shape'], 'accepted')
    for row in rows:
      self.assertIn(row['shape'], ['accepted', 'other'])
    reasons = {}
    for row in rows:
      if row['event'] == 'PostToolUse' and row['action'] == 'pass_through':
        reasons[row['reason']] = reasons.get(row['reason'], 0) + 1
    for shape in REJECTED_SHAPES:
      self.assertEqual(reasons.get(shape, 0), 1, shape)
    joined = json.dumps(rows, ensure_ascii=False)
    for secret in [A[:40], 'LIVE-A-', 'LIVE-B-', 'description']:
      self.assertNotIn(secret, joined)
    self.assertEqual(rows[0]['transcript_path'], '/tmp/transcript.jsonl')
    self.assertEqual(session_rows[0]['transcript_path'], '/tmp/session-a.jsonl')

  def test_disabled_creates_no_state_or_audit(self):
    self.enable.unlink()
    self.assert_passthrough(self.task(A))
    self.assert_passthrough(self.session_start('startup'))
    self.assertEqual(list(self.root.iterdir()), [])

  def test_no_network_or_model_imports(self):
    source = HOOK.read_text()
    for banned in ['requests', 'urllib', 'http', 'socket', 'openai', 'anthropic', 'subprocess']:
      self.assertNotIn(banned, source, banned)


if __name__ == '__main__':
  unittest.main(verbosity=2)
