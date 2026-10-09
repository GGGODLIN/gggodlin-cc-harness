#!/usr/bin/env python3

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / 'hooks' / 'websearch-parallel-enforce.sh'
SETTINGS = ROOT / 'settings.json'


def compact(value):
  return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def user(text='find official docs'):
  return compact({
    'type': 'user',
    'message': {'role': 'user', 'content': text},
  })


def tool(name, tool_input):
  return compact({
    'type': 'assistant',
    'message': {
      'role': 'assistant',
      'content': [{
        'type': 'tool_use',
        'id': f'tool-{name}',
        'name': name,
        'input': tool_input,
      }],
    },
  })


def tool_result_for(tool_id, content, is_error=False):
  return compact({
    'type': 'user',
    'message': {
      'role': 'user',
      'content': [{
        'type': 'tool_result',
        'tool_use_id': tool_id,
        'content': content,
        'is_error': is_error,
      }],
    },
  })


def tool_result(content):
  return tool_result_for('tool-WebSearch', content)


def write_transcript(path, lines):
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def run_hook(transcript, query, agent_type='', agent_id=''):
  payload = {
    'tool_name': 'WebSearch',
    'tool_input': {'query': query},
    'transcript_path': str(transcript),
    'agent_type': agent_type,
  }
  if agent_id:
    payload['agent_id'] = agent_id
  with tempfile.TemporaryDirectory() as home:
    env = os.environ.copy()
    env['HOME'] = home
    env.pop('CC_VENDOR', None)
    result = subprocess.run(
      ['bash', str(HOOK)],
      input=json.dumps(payload),
      text=True,
      capture_output=True,
      env=env,
      timeout=10,
    )
  return result


class PairedSearchTranscriptContractTest(unittest.TestCase):
  def setUp(self):
    self.tmp = tempfile.TemporaryDirectory()
    self.root = Path(self.tmp.name)
    self.transcript = self.root / 'main.jsonl'

  def tearDown(self):
    self.tmp.cleanup()

  def assert_allowed(self, result):
    self.assertEqual(result.returncode, 0, result.stderr)
    self.assertEqual(result.stdout.strip(), '')

  def assert_blocked(self, result):
    self.assertEqual(result.returncode, 0, result.stderr)
    body = json.loads(result.stdout)
    self.assertEqual(body.get('decision'), 'block')
    self.assertIn('[search-parallel]', body.get('reason', ''))

  def test_successful_lcu_navigation_grants_ticket(self):
    query = 'LCU docs'
    write_transcript(self.transcript, [
      user(),
      tool('mcp__lcu__js', {'code': 'var t = await cua.createBrowserTab("1", "https://www.google.com/search?q=LCU%20docs"); await t.getAXState();'}),
      tool_result_for('tool-mcp__lcu__js', compact({'isError': False, 'content': [{'type': 'text', 'text': 'Google search results'}]})),
    ])
    self.assert_allowed(run_hook(self.transcript, query))

  def test_lcu_failed_or_unexecuted_navigation_does_not_grant_ticket(self):
    query = 'LCU docs'
    nav = tool('mcp__lcu__js', {'code': 'await t.goto("https://www.google.com/search?q=LCU%20docs");'})
    for result in (None, tool_result_for('tool-mcp__lcu__js', 'failed', is_error=True), tool_result_for('tool-mcp__lcu__js', compact({'isError': True, 'content': []}))):
      write_transcript(self.transcript, [user(), nav] + ([] if result is None else [result]))
      self.assert_blocked(run_hook(self.transcript, query))

  def test_lcu_url_print_alone_does_not_grant_ticket(self):
    write_transcript(self.transcript, [
      user(),
      tool('mcp__lcu__js', {'code': 'console.log("https://www.google.com/search?q=LCU%20docs");'}),
      tool_result_for('tool-mcp__lcu__js', compact({'isError': False, 'content': [{'type': 'text', 'text': 'printed URL'}]})),
    ])
    self.assert_blocked(run_hook(self.transcript, 'LCU docs'))

  def test_lcu_ticket_is_query_specific_and_consumed(self):
    nav = tool('mcp__lcu__js', {'code': 'await t.goto("https://www.google.com/search?q=LCU%20docs");'})
    result = tool_result_for('tool-mcp__lcu__js', compact({'isError': False, 'content': [{'type': 'text', 'text': 'Google search results'}]}))
    write_transcript(self.transcript, [user(), nav, result])
    self.assert_blocked(run_hook(self.transcript, 'other query'))
    write_transcript(self.transcript, [user(), nav, result, tool('WebSearch', {'query': 'LCU docs'}), tool_result('results')])
    self.assert_blocked(run_hook(self.transcript, 'LCU docs'))

  def test_lcu_navigation_in_redirected_subagent_transcript(self):
    write_transcript(self.transcript, [user()])
    sub = self.root / 'main' / 'subagents' / 'agent-agent-7.jsonl'
    write_transcript(sub, [
      user(),
      tool('mcp__lcu__js', {'code': 'await t.goto("https://www.google.com/search?q=LCU%20docs");'}),
      tool_result_for('tool-mcp__lcu__js', compact({'isError': False, 'content': [{'type': 'text', 'text': 'Google search results'}]})),
    ])
    self.assert_allowed(run_hook(self.transcript, 'LCU docs', agent_type='parallel-search', agent_id='agent-7'))

  def test_main_obu_open_tab_grants_same_query_ticket(self):
    query = 'Claude Code hooks'
    write_transcript(self.transcript, [
      user(),
      tool('mcp__open_browser_use__open_tab', {
        'url': 'https://www.google.com/search?q=Claude%20Code%20hooks',
      }),
    ])
    self.assert_allowed(run_hook(self.transcript, query))

  def test_main_obu_navigate_grants_same_query_ticket(self):
    query = 'Open Browser Use docs'
    write_transcript(self.transcript, [
      user(),
      tool('mcp__open_browser_use__navigate', {
        'url': 'https://www.google.com/search?q=Open+Browser+Use+docs',
      }),
    ])
    self.assert_allowed(run_hook(self.transcript, query))

  def test_missing_and_mismatched_tickets_block(self):
    write_transcript(self.transcript, [user()])
    self.assert_blocked(run_hook(self.transcript, 'missing query'))
    write_transcript(self.transcript, [
      user(),
      tool('mcp__open_browser_use__open_tab', {
        'url': 'https://www.google.com/search?q=other%20query',
      }),
    ])
    self.assert_blocked(run_hook(self.transcript, 'wanted query'))

  def test_success_consumes_ticket_but_blocked_attempt_does_not(self):
    query = 'same query'
    nav = tool('mcp__open_browser_use__open_tab', {
      'url': 'https://www.google.com/search?q=same%20query',
    })
    websearch = tool('WebSearch', {'query': query})
    write_transcript(self.transcript, [user(), nav, websearch, tool_result('results')])
    self.assert_blocked(run_hook(self.transcript, query))
    write_transcript(self.transcript, [
      user(),
      nav,
      websearch,
      tool_result('[search-parallel] blocked before execution'),
    ])
    self.assert_allowed(run_hook(self.transcript, query))

  def test_legacy_navigation_no_longer_grants_ticket(self):
    query = 'legacy query'
    write_transcript(self.transcript, [
      user(),
      tool('mcp__claude-in-chrome__navigate', {
        'url': 'https://www.google.com/search?q=legacy%20query',
      }),
    ])
    self.assert_blocked(run_hook(self.transcript, query))

  def test_settings_keep_one_websearch_hook_entry(self):
    settings = json.loads(SETTINGS.read_text(encoding='utf-8'))
    groups = [
      group for group in (settings.get('hooks') or {}).get('PreToolUse', [])
      if group.get('matcher') == 'WebSearch'
    ]
    commands = [
      hook.get('command', '')
      for group in groups
      for hook in group.get('hooks', [])
      if 'websearch-parallel-enforce.sh' in hook.get('command', '')
    ]
    self.assertEqual(len(commands), 1)


if __name__ == '__main__':
  unittest.main(verbosity=2)
