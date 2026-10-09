#!/usr/bin/env python3
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent
HOOK = ROOT / 'taskoutput-dedup-hook.py'
SETTINGS = ROOT.parent / 'settings.json'
BASE_COMMIT = '7ae408e17ab38ba3d75f6bf32d220275a55cf3d0'
DEDUP_COMMAND = 'python3 ~/.claude/hooks/taskoutput-dedup-hook.py'
DEDUP_POST_GROUP = {
  'matcher': 'TaskOutput',
  'hooks': [
    {
      'type': 'command',
      'command': DEDUP_COMMAND,
      'timeout': 10,
    }
  ],
}
DEDUP_SESSION_GROUP = {
  'hooks': [
    {
      'type': 'command',
      'command': DEDUP_COMMAND,
      'timeout': 10,
    }
  ],
}


def baseline_settings():
  completed = subprocess.run(
    ['git', 'show', f'{BASE_COMMIT}:settings.json'],
    cwd=ROOT.parent,
    capture_output=True,
    text=True,
    check=True,
  )
  return json.loads(completed.stdout)


def split_dedup(settings):
  removed_post = []
  kept_post = []
  for group in settings['hooks']['PostToolUse']:
    if group.get('matcher') == 'TaskOutput' and any(h.get('command') == DEDUP_COMMAND for h in group.get('hooks', [])):
      removed_post.append(group)
    else:
      kept_post.append(group)
  removed_session = []
  kept_session = []
  for group in settings['hooks']['SessionStart']:
    if 'matcher' not in group and any(h.get('command') == DEDUP_COMMAND for h in group.get('hooks', [])):
      removed_session.append(group)
    else:
      kept_session.append(group)
  return removed_post, kept_post, removed_session, kept_session


class SettingsContractCase(unittest.TestCase):
  def setUp(self):
    self.current = json.loads(SETTINGS.read_text())
    self.baseline = baseline_settings()

  def test_daily_settings_register_exact_dedup_groups(self):
    removed_post, _, removed_session, _ = split_dedup(copy.deepcopy(self.current))
    self.assertEqual(removed_post, [DEDUP_POST_GROUP])
    self.assertEqual(removed_session, [DEDUP_SESSION_GROUP])
    self.assertEqual(Path(DEDUP_COMMAND.split(' ', 1)[1]).name, HOOK.name)

  def test_settings_minus_dedup_registrations_equal_dispatch_base_structurally(self):
    settings = copy.deepcopy(self.current)
    removed_post, kept_post, removed_session, kept_session = split_dedup(settings)
    self.assertEqual(len(removed_post), 1)
    self.assertEqual(len(removed_session), 1)
    settings['hooks']['PostToolUse'] = kept_post
    settings['hooks']['SessionStart'] = kept_session
    self.assertEqual(settings, self.baseline)

  def test_taskoutput_gate_and_matchers_scoped_to_expected_events(self):
    baseline_gate = [g for g in self.baseline['hooks']['PreToolUse'] if g.get('matcher') == 'TaskOutput']
    current_gate = [g for g in self.current['hooks']['PreToolUse'] if g.get('matcher') == 'TaskOutput']
    self.assertEqual(current_gate, baseline_gate)
    self.assertEqual(len(current_gate), 1)
    self.assertIn('taskoutput-block-gate.py', current_gate[0]['hooks'][0]['command'])
    dedup_events = []
    for event, groups in self.current['hooks'].items():
      if any(any('taskoutput-dedup' in h.get('command', '') for h in g.get('hooks', [])) for g in groups):
        dedup_events.append(event)
    self.assertEqual(sorted(dedup_events), ['PostToolUse', 'SessionStart'])
    for event, groups in self.current['hooks'].items():
      if event == 'PreToolUse':
        continue
      taskoutput_matchers = [g for g in groups if g.get('matcher') == 'TaskOutput']
      self.assertEqual(len(taskoutput_matchers), 1 if event == 'PostToolUse' else 0, event)

  def test_fresh_home_without_enable_file_or_env_passes_through_stateless(self):
    with tempfile.TemporaryDirectory() as home:
      env = {**os.environ}
      env.pop('TASKOUTPUT_DEDUP_ROOT', None)
      env.pop('TASKOUTPUT_DEDUP_ENABLE', None)
      env['HOME'] = home
      body = 'FRESH-' + 'x' * 6000 + '\n'
      payloads = [
        {
          'hook_event_name': 'PostToolUse',
          'tool_name': 'TaskOutput',
          'session_id': 'fresh-session',
          'tool_use_id': 'toolu-fresh',
          'transcript_path': '/tmp/fresh.jsonl',
          'tool_input': {'task_id': 'task-fresh'},
          'tool_response': {
            'retrieval_status': 'not_ready',
            'task': {
              'task_id': 'task-fresh',
              'task_type': 'local_agent',
              'status': 'running',
              'output': body,
              'result': body,
            },
          },
        },
        {
          'hook_event_name': 'SessionStart',
          'session_id': 'fresh-session',
          'source': 'startup',
          'transcript_path': '/tmp/fresh.jsonl',
        },
      ]
      for payload in payloads:
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
        self.assertEqual(json.loads(result.stdout), {})
      cache = Path(home) / '.claude' / 'cache'
      self.assertFalse((cache / 'taskoutput-dedup').exists())
      self.assertFalse((cache / 'taskoutput-dedup.enable.json').exists())
      if cache.exists():
        self.assertEqual(sorted(entry.name for entry in cache.iterdir()), [])


if __name__ == '__main__':
  unittest.main(verbosity=2)
