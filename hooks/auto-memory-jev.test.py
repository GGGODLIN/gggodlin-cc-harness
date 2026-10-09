#!/usr/bin/env python3
"""Offline contracts; temporary HOME, mocked provider, no production memory/log writes."""
import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import memory_reminder_common as common

spec = importlib.util.spec_from_file_location('auto_memory_jev', HERE / 'auto-memory-jev.py')
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)
REAL_RULE = common.rule_file().read_text()


def user(text, uid='human-1', **extra):
  return {'type': 'user', 'uuid': uid, 'message': {'content': text}, **extra}


def assistant(text, uid='assistant-1', blocks=None):
  return {'type': 'assistant', 'uuid': uid, 'message': {'id': uid,
          'content': blocks if blocks is not None else [{'type': 'text', 'text': text}], 'stop_reason': 'end_turn'}}


class ReminderTests(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory(prefix='jev-memory-test-')
    self.home = Path(self.tmp.name).resolve()
    self.environment = patch.dict(os.environ, {'HOME': str(self.home), 'JEV_MEMORY_DISABLE': '',
      'CLAUDE_CODE_CHILD_SESSION': '', 'CC_VENDOR': '', 'GIT_CLOSEOUT_DISABLE': '1'})
    self.environment.start()
    self.addCleanup(self.environment.stop)
    self.addCleanup(self.tmp.cleanup)
    self.cwd = self.home / 'Desktop/projects/demo'
    self.cwd.mkdir(parents=True)
    self.transcript = self.home / '.claude/projects/personal/session.jsonl'
    self.transcript.parent.mkdir(parents=True)
    common.rule_file().parent.mkdir(parents=True)
    common.rule_file().write_text(REAL_RULE)
    self.final = 'Understood. I will use concise Traditional Chinese in future sessions.'
    self.entries = [user('For future sessions, I prefer concise Traditional Chinese.'), assistant(self.final)]
    self.flush()
    self.payload = {'session_id': 'session-1', 'cwd': str(self.cwd), 'transcript_path': str(self.transcript),
                    'hook_event_name': 'Stop', 'last_assistant_message': self.final, 'stop_hook_active': False}
    self.response = {'model': 'jev-latest', 'answers': {'direct_nudge': {'noul': 0.7}},
                     'usage': {'input_tokens': 600, 'output_tokens': 23, 'cost': 0.0}}
    self.calls = []
    self.metadata_calls = 0
    self.price = '0'
    self.http_patch = patch.object(hook, 'http', side_effect=self.fake_http)
    self.endpoint_patch = patch.object(hook, 'endpoint', return_value=(hook.BASE, 'test-only'))
    self.http_patch.start()
    self.endpoint_patch.start()
    self.addCleanup(self.http_patch.stop)
    self.addCleanup(self.endpoint_patch.stop)

  def flush(self):
    self.transcript.write_text(''.join(json.dumps(e, ensure_ascii=False) + '\n' for e in self.entries))

  def fake_http(self, _base, path, _key, body=None, **_kwargs):
    if path == '/api/v1/models':
      self.metadata_calls += 1
      return {'data': [{'id': hook.MODEL, 'pricing': {'prompt': self.price, 'completion': '0'}}]}
    self.assertEqual(path, '/v1/systemone')
    self.assertEqual(body['model'], 'type-safe/jev-latest:free')
    self.calls.append(body)
    return self.response

  def invoke(self, mode='stop', **overrides):
    payload = {**self.payload, 'hook_event_name': 'Stop' if mode == 'stop' else 'UserPromptSubmit', **overrides}
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
      hook.main(payload, mode)
    return output.getvalue()

  def deliver(self, prompt='Continue the original task.'):
    return self.invoke('deliver', prompt=prompt)

  def journal(self):
    return hook.automatic_dir() / ('session-' + hook.sha('session-1')[:24] + '.json')

  def next_turn(self, text='A new standing preference.', final=None):
    n = sum(e['type'] == 'user' for e in self.entries) + 1
    self.entries += [user(text, 'human-' + str(n)), assistant(final or self.final, 'assistant-' + str(n))]
    self.flush()
    self.payload['last_assistant_message'] = final or self.final

  def test_positive_pending_then_full_delivery_no_manual_sentinels(self):
    original = common.rule_file().read_bytes()
    self.assertEqual(self.invoke(), '')
    self.assertEqual(len(self.calls), 1)
    self.assertFalse((common.state_directory() / 'long_injected_session-1').exists())
    result = json.loads(self.deliver())
    self.assertEqual(set(result), {'hookSpecificOutput'})
    self.assertEqual(result['hookSpecificOutput']['hookEventName'], 'UserPromptSubmit')
    text = result['hookSpecificOutput']['additionalContext']
    self.assertIn('[auto-memory:jev:long]', text)
    self.assertIn('## Tier 1:', text)
    self.assertIn('先檢索既有 memory', text)
    self.assertNotIn('Git closeout', text)
    self.assertIn('本輪使用者要求優先', text)
    self.assertNotIn('只回 "skip"', text)
    self.assertEqual((common.state_directory() / 'long_injected_session-1').read_text().strip(), '1')
    for prefix in ('checkpoint_', 'trigger_'):
      self.assertFalse((common.state_directory() / (prefix + 'session-1')).exists())
    self.assertEqual(common.rule_file().read_bytes(), original)
    self.assertEqual(self.deliver(), '')

  def test_negative_is_quiet(self):
    self.response['answers']['direct_nudge']['noul'] = 0.49
    self.invoke()
    self.assertEqual(self.deliver(), '')
    self.assertNotIn('pending', json.loads(self.journal().read_text()))

  def test_threshold_boundary(self):
    self.response['answers']['direct_nudge']['noul'] = 0.5
    self.invoke()
    self.assertIn('[auto-memory:jev:long]', self.deliver())

  def test_turn_dedup_and_stop_reentry(self):
    self.invoke()
    self.invoke()
    self.invoke(stop_hook_active=True)
    self.assertEqual(len(self.calls), 1)

  def test_current_manual_request_drops_pending_not_manual_trigger(self):
    self.invoke()
    self.assertEqual(self.deliver('好，那就結案'), '')
    self.assertNotIn('pending', json.loads(self.journal().read_text()))
    self.assertFalse((common.state_directory() / 'trigger_session-1').exists())
    self.assertEqual(len(self.calls), 1)

  def test_manual_then_auto_share_short_record(self):
    self.entries = [user('好，那就結案')]
    self.flush()
    out = subprocess.run(['bash', str(HERE / 'checkpoint-judge.sh')], input=json.dumps(self.payload),
                         capture_output=True, text=True, timeout=5, check=True)
    self.assertIn('[checkpoint:trigger:long]', out.stdout)
    self.next_turn()
    self.invoke()
    text = self.deliver()
    self.assertIn('[auto-memory:jev:short]', text)
    self.assertNotIn('## Tier 1:', text)

  def test_auto_then_manual_still_blocks_and_is_short(self):
    self.invoke()
    self.deliver()
    self.next_turn('好，那就結案')
    out = subprocess.run(['bash', str(HERE / 'checkpoint-judge.sh')], input=json.dumps(self.payload),
                         capture_output=True, text=True, timeout=5, check=True)
    result = json.loads(out.stdout)
    self.assertEqual(result['decision'], 'block')
    self.assertIn('[checkpoint:trigger:short]', result['reason'])
    self.assertNotIn('Git closeout', result['reason'])

  def test_refresh_boundary_and_compaction(self):
    common.mark_long('session-1', 1)
    self.entries = [user('temporary task', 'human-' + str(i)) for i in range(1, 52)]
    self.entries += [assistant(self.final)]
    self.flush()
    self.invoke()
    self.assertIn('[auto-memory:jev:short]', self.deliver())
    self.next_turn()
    self.invoke()
    self.assertIn('[auto-memory:jev:long]', self.deliver())
    newer = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    self.entries += [{'type': 'system', 'subtype': 'compact_boundary', 'uuid': 'compact-1', 'timestamp': newer}]
    self.next_turn('Another new reusable preference.')
    self.invoke()
    self.assertIn('[auto-memory:jev:long]', self.deliver())

  def test_rule_change_invalidates_shared_marker(self):
    common.mark_long('session-1', 1)
    marker = common.state_directory() / 'long_injected_session-1'
    os.utime(marker, (common.rule_file().stat().st_mtime-1,) * 2)
    self.assertEqual(common.last_long('session-1', 1, str(self.transcript)), 0)

  def test_missing_rule_does_not_claim_full_injection(self):
    common.rule_file().unlink()
    self.invoke()
    self.assertIn('Tier 1 段抽不到', self.deliver())
    self.assertFalse((common.state_directory() / 'long_injected_session-1').exists())
    self.assertIn('尚無有效完整版', common.reminder('short', '[test]'))

  def test_packet_repeat_dedup(self):
    self.invoke()
    self.deliver()
    self.next_turn('For future sessions, I prefer concise Traditional Chinese.')
    with self.assertRaisesRegex(ValueError, 'packet_repeat'):
      self.invoke()
    self.assertEqual(len(self.calls), 1)

  def test_late_final_payload_is_authoritative(self):
    self.entries = [user('A reusable preference.')]
    self.flush()
    self.invoke()
    self.assertEqual(self.calls[0]['state']['assistant'], self.final)

  def test_new_human_during_judge_is_stale(self):
    def response(*args, **kwargs):
      data = self.fake_http(*args, **kwargs)
      if args[1] == '/v1/systemone':
        self.next_turn('Next task started.')
      return data
    self.http_patch.stop()
    with patch.object(hook, 'http', side_effect=response), self.assertRaisesRegex(ValueError, 'stale_turn'):
      self.invoke()
    self.assertNotIn('pending', json.loads(self.journal().read_text()))

  def test_changed_reply_during_judge_is_stale(self):
    def response(*args, **kwargs):
      data = self.fake_http(*args, **kwargs)
      if args[1] == '/v1/systemone':
        self.entries[-1] = assistant('That proposal remains unaccepted.')
        self.flush()
      return data
    self.http_patch.stop()
    with patch.object(hook, 'http', side_effect=response), self.assertRaisesRegex(ValueError, 'stale_reply'):
      self.invoke()

  def test_memory_write_after_judge_skips_delivery(self):
    self.invoke()
    self.entries += [assistant('', 'write-memory', [{'type': 'tool_use', 'name': 'Write',
                    'input': {'file_path': str(common.rule_file())}}])]
    self.flush()
    self.assertEqual(self.deliver(), '')

  def test_compaction_after_judge_skips_delivery(self):
    self.invoke()
    self.entries += [{'type': 'system', 'subtype': 'compact_boundary', 'uuid': 'compact-1',
                      'timestamp': datetime.now(timezone.utc).isoformat()}]
    self.flush()
    self.assertEqual(self.deliver(), '')

  def test_current_prompt_already_in_transcript(self):
    self.invoke()
    self.entries += [user('Continue the original task.', 'human-2')]
    self.flush()
    self.assertIn('[auto-memory:jev:long]', self.deliver())

  def test_notifications_do_not_consume_pending(self):
    self.invoke()
    for extra in ({'prompt': '<task-notification>done</task-notification>'},
                  {'prompt': 'peer report', 'origin': {'kind': 'peer'}},
                  {'prompt': 'meta', 'isMeta': True}, {'prompt': 'unknown', 'promptSource': 'unknown'}):
      self.assertEqual(self.invoke('deliver', **extra), '')
      self.assertIn('pending', json.loads(self.journal().read_text()))
    self.assertIn('[auto-memory:jev:long]', self.deliver())

  def test_human_sdk_source_pairs(self):
    for extra in ({}, {'origin': {'kind': 'human'}, 'turnOrigin': 'human', 'promptSource': 'typed'},
                  {'origin': {'kind': 'sdk'}, 'turnOrigin': 'sdk', 'promptSource': 'sdk'}):
      self.assertTrue(hook.human(user('real input', **extra)))
    for extra in ({'origin': {'kind': 'task-notification'}}, {'origin': {'kind': 'peer'}},
                  {'turnOrigin': 'task_notification'}, {'promptSource': 'unknown'}, {'isMeta': True}):
      self.assertFalse(hook.human(user('not a human prompt', **extra)))
    self.assertFalse(hook.human(user([{'type': 'tool_result', 'content': 'done'}])))

  def test_nonhuman_stop_and_subagent_skipped(self):
    self.entries += [user('peer report', 'notice', origin={'kind': 'peer'})]
    self.flush()
    self.invoke()
    self.assertEqual(len(self.calls), 0)
    self.invoke(agent_type='routed-impl')
    self.assertEqual(len(self.calls), 0)

  def test_main_sdk_child_environment_is_not_a_subagent(self):
    # Native 2.1.289 sets this flag on a root streaming-SDK session with no agent_id.
    with patch.dict(os.environ, {'CLAUDE_CODE_CHILD_SESSION': '1'}):
      self.invoke()
      self.assertIn('[auto-memory:jev:long]', self.deliver())
    self.assertEqual(len(self.calls), 1)

  def test_company_and_secret_rejected_before_clipping(self):
    for message in ('company acme requirement', 'do not save this preference',
                    'sk-' + 'a' * 32, 'safe beginning' + 'x'*10000 + ' gsk_' + 'b'*32 + 'x'*10000):
      context = hook.snapshot(str(self.transcript))
      context['records'][-1]['user'] = message
      with self.assertRaises(ValueError):
        hook.packet(context, self.final)
    self.assertEqual(len(self.calls), 0)

  def test_manual_and_memory_write_exclusion(self):
    for text in ('記一下這個', '好，那就結案'):
      context = hook.snapshot(str(self.transcript))
      context['records'][-1]['user'] = text
      with self.assertRaisesRegex(ValueError, 'already_handled'):
        hook.packet(context, self.final)
    context = hook.snapshot(str(self.transcript))
    context['records'][-1]['saved'] = True
    with self.assertRaisesRegex(ValueError, 'already_handled'):
      hook.packet(context, self.final)

  def test_scope_symlink_company_and_invalid_session(self):
    company = self.home / 'Desktop/work/company'
    company.mkdir(parents=True)
    link = self.cwd / 'company-link'
    link.symlink_to(company, target_is_directory=True)
    for cwd in (company, link):
      self.assertEqual(self.invoke(cwd=str(cwd)), '')
    self.assertEqual(self.invoke(session_id='../escape'), '')
    self.assertEqual(len(self.calls), 0)

  def test_kill_switch_bootstrap_update_recovery(self):
    with patch.dict(os.environ, {'JEV_MEMORY_DISABLE': '1'}):
      self.assertEqual(self.invoke(), '')
    common.state_directory().mkdir(parents=True, exist_ok=True)
    marker = common.state_directory() / 'auto-memory-jev.disabled'
    marker.touch()
    self.assertEqual(self.invoke(), '')
    marker.unlink()
    self.invoke()
    self.assertEqual(len(self.calls), 1)
    self.deliver()
    self.next_turn()
    self.invoke()
    self.assertEqual(len(self.calls), 2)

  def test_price_guard_rejects_paid_lane(self):
    self.price = '0.000000042'
    with self.assertRaisesRegex(ValueError, 'free_lane_not_confirmed'):
      self.invoke()
    self.assertEqual(len(self.calls), 0)

  def test_price_cache_and_single_free_route(self):
    self.invoke()
    self.deliver()
    self.next_turn()
    self.invoke()
    self.assertEqual(self.metadata_calls, 1)
    self.assertEqual(len(self.calls), 2)
    self.assertEqual({r['model'] for r in self.calls}, {hook.MODEL})

  def test_paid_response_disables_automatic_only(self):
    self.response['usage']['cost'] = 0.01
    with self.assertRaisesRegex(ValueError, 'nonzero_cost'):
      self.invoke()
    self.assertTrue(hook.disabled())
    self.assertEqual(self.deliver(), '')
    self.next_turn('好，那就結案')
    result = subprocess.run(['bash', str(HERE / 'checkpoint-judge.sh')], input=json.dumps(self.payload),
                            capture_output=True, text=True, timeout=5, check=True)
    self.assertEqual(json.loads(result.stdout)['decision'], 'block')

  def test_missing_cost_starts_cooldown(self):
    del self.response['usage']['cost']
    with self.assertRaisesRegex(ValueError, 'missing_zero_cost_evidence'):
      self.invoke()
    self.assertGreater(json.loads((hook.automatic_dir() / 'budget.json').read_text())['cooldown_until'], 0)

  def test_bad_probabilities_rejected(self):
    for score in (True, '0.7', -0.1, 1.1, float('nan')):
      self.response['answers']['direct_nudge']['noul'] = score
      self.next_turn('Another preference ' + str(score))
      with self.assertRaisesRegex(ValueError, 'invalid_probability'):
        self.invoke()

  def test_http_429_cooldown_no_retry(self):
    def failed(_base, path, _key, body=None, **_kwargs):
      if path == '/api/v1/models':
        return self.fake_http(_base, path, _key, body)
      self.calls.append(body)
      raise urllib.error.HTTPError(hook.BASE, 429, 'quota', {}, None)
    self.http_patch.stop()
    with patch.object(hook, 'http', side_effect=failed), self.assertRaises(urllib.error.HTTPError):
      self.invoke()
    self.next_turn()
    with self.assertRaisesRegex(ValueError, 'quota_cooldown'):
      self.invoke()
    self.assertEqual(len(self.calls), 1)

  def test_daily_and_hourly_budget_reserve(self):
    with common.SafeDirectory(hook.automatic_dir()) as directory:
      hook.reserve(directory, 1000)
      budget = json.loads(directory.read('budget.json'))
      self.assertEqual(budget['daily_calls'], 1)
      budget['hourly_calls'] = 250
      directory.write('budget.json', hook.dump(budget))
      with self.assertRaisesRegex(ValueError, 'hourly_budget'):
        hook.reserve(directory, 1)
      budget['hourly_calls'] = 1
      budget['daily_bytes'] = 4000000
      directory.write('budget.json', hook.dump(budget))
      with self.assertRaisesRegex(ValueError, 'daily_budget'):
        hook.reserve(directory, 1)

  def audit_rows(self):
    return [json.loads(line) for line in (self.home / '.claude/logs/auto-memory-jev.jsonl').read_text().splitlines()]

  def test_pending_state_and_audit_carry_no_question_digest(self):
    self.assertEqual(self.invoke(), '')
    pending = json.loads(self.journal().read_text())['pending']
    self.assertNotIn('question_sha', pending)
    self.assertEqual(self.audit_rows()[-1]['status'], 'pending')
    self.assertNotIn('question_sha', self.audit_rows()[-1])

  def test_no_credentials_or_content_in_audit(self):
    self.invoke()
    self.deliver()
    text = (self.home / '.claude/logs/auto-memory-jev.jsonl').read_text()
    self.assertNotIn('test-only', text)
    self.assertNotIn(self.final, text)
    self.assertNotIn('concise Traditional Chinese', text)
    self.assertIn('"cost":0.0', text)

  def test_control_and_bidi_sanitization_nonempty(self):
    original = common.tier1()
    common.rule_file().write_text(REAL_RULE.replace('## Tier 1:', '## Tier 1:\x1b\u202e'))
    clean = common.tier1()
    self.assertGreater(len(clean), len(original)*0.9)
    self.assertNotIn('\x1b', clean)
    self.assertNotIn('\u202e', clean)

  def test_log_pathologies_do_not_write_elsewhere(self):
    parent = self.home / '.claude/logs'
    parent.mkdir(parents=True)
    target = self.home / 'innocent'
    target.write_text('unchanged')
    path = parent / 'auto-memory-jev.jsonl'
    for kind in ('symlink', 'hardlink', 'fifo'):
      if kind == 'symlink':
        path.symlink_to(target)
      elif kind == 'hardlink':
        os.link(target, path)
      else:
        os.mkfifo(path)
      with self.assertRaises((OSError, ValueError)):
        self.invoke()
      self.assertEqual(target.read_text(), 'unchanged')
      self.assertEqual(len(self.calls), 0)
      path.unlink()

  def test_state_and_marker_pathologies(self):
    self.invoke()
    journal = self.journal()
    original = journal.read_bytes()
    target = self.home / 'innocent'
    target.write_text('unchanged')
    for kind in ('symlink', 'hardlink', 'fifo'):
      journal.unlink()
      if kind == 'symlink':
        journal.symlink_to(target)
      elif kind == 'hardlink':
        os.link(target, journal)
      else:
        os.mkfifo(journal)
      with self.assertRaises((OSError, ValueError)):
        self.deliver()
      self.assertEqual(target.read_text(), 'unchanged')
      journal.unlink()
      journal.write_bytes(original)
    marker = common.state_directory() / 'long_injected_session-1'
    for kind in ('symlink', 'hardlink', 'fifo'):
      self.journal().write_bytes(original)
      if kind == 'symlink':
        marker.symlink_to(target)
      elif kind == 'hardlink':
        os.link(target, marker)
      else:
        os.mkfifo(marker)
      with self.assertRaises((OSError, ValueError)):
        self.deliver()
      self.assertEqual(target.read_text(), 'unchanged')
      marker.unlink()

  def test_bad_cli_input_and_disabled_exit_zero(self):
    for raw in ('bad-json', '{"session_id":"../escape"}'):
      result = subprocess.run([sys.executable, str(HERE / 'auto-memory-jev.py'), 'stop'], input=raw,
                              capture_output=True, text=True, timeout=3)
      self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))

  def test_helper_missing_cli_fails_open(self):
    script = self.home / 'isolated/auto-memory-jev.py'
    script.parent.mkdir()
    shutil.copyfile(HERE / 'auto-memory-jev.py', script)
    result = subprocess.run([sys.executable, str(script), 'stop'], input=json.dumps(self.payload),
                            capture_output=True, text=True, timeout=3)
    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))


if __name__ == '__main__':
  suite = unittest.defaultTestLoader.loadTestsFromTestCase(ReminderTests)
  result = unittest.TextTestRunner(verbosity=2).run(suite)
  if result.wasSuccessful():
    print('AUTO_MEMORY_JEV_CONTRACTS_OK')
  sys.exit(0 if result.wasSuccessful() else 1)
