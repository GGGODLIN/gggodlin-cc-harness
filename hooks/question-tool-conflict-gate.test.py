#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / 'hooks/question-tool-conflict-gate.py'
SETTINGS = ROOT / 'settings.json'


class QuestionToolConflictGateTest(unittest.TestCase):
  def setUp(self):
    self.temp_root = Path(tempfile.mkdtemp(prefix='question-tool-gate-test.'))
    self.audit = self.temp_root / 'audit.jsonl'
    self.state_dir = self.temp_root / 'state'
    self.transcript = self.temp_root / 'session.jsonl'
    self.untouched = self.temp_root / 'untouched.txt'
    self.untouched.write_text('keep-me', encoding='utf-8')

  def tearDown(self):
    shutil.rmtree(self.temp_root, ignore_errors=True)

  def write_transcript(self, rows):
    with self.transcript.open('w', encoding='utf-8') as handle:
      for row in rows:
        handle.write(json.dumps(row, ensure_ascii=False) + '\n')

  def run_hook(self, tool_name='Skill', session_id='test-session', agent_id=None, extra_env=None):
    env = {
      'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
      'HOME': os.environ.get('HOME', str(self.temp_root)),
      'QUESTION_TOOL_GATE_AUDIT': str(self.audit),
      'QUESTION_TOOL_GATE_STATE_DIR': str(self.state_dir),
    }
    if extra_env:
      env.update(extra_env)
    payload = {
      'hook_event_name': 'PreToolUse',
      'session_id': session_id,
      'transcript_path': str(self.transcript),
      'tool_name': tool_name,
      'tool_input': {},
    }
    if agent_id:
      payload['agent_id'] = agent_id
    res = subprocess.run(
      [sys.executable, str(HOOK)],
      input=json.dumps(payload),
      capture_output=True,
      text=True,
      env=env,
      timeout=3,
      check=False,
    )
    self.assertEqual(res.returncode, 0, res.stderr)
    self.assertEqual(self.untouched.read_text(encoding='utf-8'), 'keep-me')
    return res.stdout.strip()

  def test_known_bad_interview_and_read_steal_all_deny(self):
    cases = [
      (
        'numbered-interview-heading',
        'Skill',
        '💡 完全不會卡死\n\n### 第 5/5 題（最後一題）：中途呼叫工具時的伴隨文字偶爾出現英文，要維持現況嗎？\n- **建議答案**：選 **a**',
      ),
      (
        'inline-ab-choice',
        'Skill',
        '**結論：有用**\n\n**待你拍板（聽完下面白話版後，選 `A` 或 `B`）：**\n這樣看下來，你想選 **`A`** 還是 **`B`**？ Let\'s wait for your pick.',
      ),
      (
        'read-steal-on-q3',
        'Read',
        '已完成：第 1/4 題｜目前：續問第 3/4 題\n\n### 第 3/4 題：要在對話當下抓出跳題嗎？',
      ),
      (
        'pending-decision-heading',
        'Bash',
        '### 待拍板：請選擇本輪回顧範圍與執行設定\n1. a. 上次至今\n2. b. 最近一天',
      ),
      (
        'pending-decision-lcu-browser-steal',
        'mcp__lcu__js',
        '### 待拍板（第 4 項：要現在登入雲端主控台把新端點接進來嗎？）',
      ),
      (
        'drive-consent-confirm-steal',
        'Bash',
        '請點上方連結選對應的 Google 帳號按同意，完成後回我，我再跑確認步驟',
      ),
    ]
    for label, tool_name, text in cases:
      with self.subTest(label=label):
        self.write_transcript([
          {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': 'a'}},
          {'type': 'assistant', 'uuid': f'u-{label}', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}},
        ])
        out = self.run_hook(tool_name=tool_name, session_id=f'sess-{label}')
        self.assertTrue(bool(out), f'{label} should deny')
        data = json.loads(out)['hookSpecificOutput']
        self.assertEqual(data['hookEventName'], 'PreToolUse')
        self.assertEqual(data['permissionDecision'], 'deny')
        self.assertTrue(
          data['permissionDecisionReason'].startswith('偵測到本回合你已經向使用者輸出待拍板或逐題訪談問題'),
          'static prefix must come first for prompt cache stability',
        )

  def test_known_good_progress_fenced_and_answered_turns_allow(self):
    # 1. 狀態列含「第 1/4 題」但非標題問句
    self.write_transcript([
      {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': 'a'}},
      {
        'type': 'assistant',
        'uuid': 'u-status',
        'message': {
          'role': 'assistant',
          'content': [{'type': 'text', 'text': '已完成：第 1/4 題（P1 選 a）｜目前：修改檔案｜下一步：跑測試'}],
        },
      },
    ])
    self.assertEqual(self.run_hook(tool_name='Edit', session_id='sess-good-1'), '')

    # 2. Code fence、blockquote、inline code 與中文引號內提及「### 第 5/5 題」「你想選 A 還是 B」
    self.write_transcript([
      {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': '請舉例'}},
      {
        'type': 'assistant',
        'uuid': 'u-fenced',
        'message': {
          'role': 'assistant',
          'content': [{
            'type': 'text',
            'text': (
              '範例如下：\n```markdown\n### 第 5/5 題：範例\n### 待拍板：範例\n```\n'
              '> ### 第 3/4 題：引言\n> **待你拍板**：引言\n'
              '當呼叫 `Skill`、`Edit`、`Write` 時，行內說明 `### 第 N/M 題`、`待你拍板`、`你想選 A 還是 B` 與「這樣看下來，你想選 A 還是 B？ Let\'s wait for your pick.」都不應因前段短反引號錯配而誤觸。'
            ),
          }],
        },
      },
    ])
    self.assertEqual(self.run_hook(tool_name='Read', session_id='sess-good-2'), '')

    # 3. Subagent 呼叫不攔截
    self.write_transcript([
      {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': 'go'}},
      {
        'type': 'assistant',
        'uuid': 'u-sub',
        'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': '### 待拍板：子任務內部文字'}]},
      },
    ])
    self.assertEqual(self.run_hook(tool_name='Read', session_id='sess-sub', agent_id='agent-123'), '')

  def test_paired_turn_reset_human_and_sdk_reset_while_non_human_origins_do_not(self):
    question_row = {
      'type': 'assistant',
      'uuid': 'u-q-origin',
      'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': '### 第 2/4 題：要修嗎？'}]},
    }
    non_reset_rows = [
      ('tool_result', {'type': 'user', 'message': {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'c1', 'content': 'ok'}]}}),
      ('is_meta', {'type': 'user', 'isMeta': True, 'message': {'role': 'user', 'content': [{'type': 'text', 'text': 'Base directory for this skill'}]}}),
      ('task_notification', {'type': 'user', 'origin': {'kind': 'task-notification'}, 'message': {'role': 'user', 'content': '<task-notification>done</task-notification>'}}),
      ('peer', {'type': 'user', 'origin': {'kind': 'peer'}, 'message': {'role': 'user', 'content': 'hello'}}),
      ('unknown_origin', {'type': 'user', 'origin': {'kind': 'mystery'}, 'message': {'role': 'user', 'content': 'a'}}),
      ('missing_origin', {'type': 'user', 'message': {'role': 'user', 'content': 'a'}}),
      ('stop_hook_summary', {'type': 'attachment', 'attachment': {'type': 'stop_hook_summary', 'hookCount': 3}}),
    ]
    for idx, (label, row) in enumerate(non_reset_rows):
      with self.subTest(non_reset=label):
        self.write_transcript([
          {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': 'start'}},
          {**question_row, 'uuid': f'u-q-{idx}'},
          row,
        ])
        out = self.run_hook(tool_name='Skill', session_id=f'sess-nr-{idx}')
        self.assertTrue(bool(out), f'{label} must NOT reset pending question')

    reset_rows = [
      ('human', {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': 'a'}}),
      ('sdk', {'type': 'user', 'origin': {'kind': 'sdk'}, 'message': {'role': 'user', 'content': 'a'}}),
      ('compaction', {'type': 'user', 'message': {'role': 'user', 'content': 'This session is being continued from a previous conversation that ran out of context.'}}),
      ('stop_blocking_attachment', {'type': 'attachment', 'attachment': {'type': 'hook_blocking_error', 'hookEvent': 'Stop'}}),
      ('stop_hook_feedback_meta', {'type': 'user', 'isMeta': True, 'message': {'role': 'user', 'content': 'Stop hook feedback:\n請先執行契約測試'}}),
    ]
    for idx, (label, row) in enumerate(reset_rows):
      with self.subTest(reset=label):
        self.write_transcript([
          {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': 'start'}},
          {**question_row, 'uuid': f'u-q-reset-{idx}'},
          row,
        ])
        out = self.run_hook(tool_name='Skill', session_id=f'sess-r-{idx}')
        self.assertEqual(out, '', f'{label} MUST reset pending question')

  def test_boundary_loop_guard_releases_on_third_attempt_and_resets_for_new_question(self):
    self.write_transcript([
      {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': 'start'}},
      {'type': 'assistant', 'uuid': 'q-loop-1', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': '### 第 1/4 題：選哪個？'}]}},
    ])
    self.assertTrue(bool(self.run_hook(tool_name='Read', session_id='sess-loop')))
    self.assertTrue(bool(self.run_hook(tool_name='Read', session_id='sess-loop')))
    # 第 3 次觸發 loop guard 放行
    self.assertEqual(self.run_hook(tool_name='Read', session_id='sess-loop'), '')

    # 新題目 uuid 重新計數並攔截
    self.write_transcript([
      {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': 'a'}},
      {'type': 'assistant', 'uuid': 'q-loop-2', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': '### 第 2/4 題：下一題選哪個？'}]}},
    ])
    self.assertTrue(bool(self.run_hook(tool_name='Read', session_id='sess-loop')))

  def test_control_and_bidi_chars_stripped_and_self_lifecycle_paths(self):
    self.write_transcript([
      {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': 'start'}},
      {
        'type': 'assistant',
        'uuid': 'q-bidi',
        'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': '### 第 1/2 題：‮\x07危險文字'}]},
      },
    ])
    out = self.run_hook(tool_name='Bash', session_id='sess-bidi')
    reason = json.loads(out)['hookSpecificOutput']['permissionDecisionReason']
    self.assertNotIn('‮', reason)
    self.assertNotIn('\x07', reason)

    # Recovery path: QUESTION_TOOL_GATE_DISABLE=1
    self.assertEqual(
      self.run_hook(
        tool_name='Bash',
        session_id='sess-bidi-disable',
        extra_env={'QUESTION_TOOL_GATE_DISABLE': '1'},
      ),
      '',
    )

  def test_pathological_symlink_hardlink_and_fifo_targets_do_not_hang_or_corrupt(self):
    self.write_transcript([
      {'type': 'user', 'origin': {'kind': 'human'}, 'message': {'role': 'user', 'content': 'start'}},
      {'type': 'assistant', 'uuid': 'q-patho', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': '### 待拍板：病態路徑測試'}]}},
    ])
    # 1. Symlink audit target
    symlink_audit = self.temp_root / 'symlink-audit.jsonl'
    symlink_audit.symlink_to(self.untouched)
    out = self.run_hook(
      tool_name='Bash',
      session_id='sess-sym',
      extra_env={'QUESTION_TOOL_GATE_AUDIT': str(symlink_audit)},
    )
    self.assertTrue(bool(out))
    self.assertEqual(self.untouched.read_text(encoding='utf-8'), 'keep-me')

    # 2. Hard link state target
    self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    hardlink_state = self.state_dir / 'sess-hard.json'
    os.link(self.untouched, hardlink_state)
    out_hard = self.run_hook(tool_name='Bash', session_id='sess-hard')
    self.assertTrue(bool(out_hard))
    self.assertEqual(self.untouched.read_text(encoding='utf-8'), 'keep-me')

    # 3. FIFO audit & state target (must not block)
    fifo_audit = self.temp_root / 'fifo-audit.jsonl'
    os.mkfifo(fifo_audit)
    fifo_state = self.state_dir / 'sess-fifo.json'
    os.mkfifo(fifo_state)
    out_fifo = self.run_hook(
      tool_name='Bash',
      session_id='sess-fifo',
      extra_env={'QUESTION_TOOL_GATE_AUDIT': str(fifo_audit)},
    )
    self.assertTrue(bool(out_fifo))

  def test_settings_registers_pretooluse_hook(self):
    settings = json.loads(SETTINGS.read_text(encoding='utf-8'))
    pre_hooks = settings.get('hooks', {}).get('PreToolUse', [])
    matched_groups = [
      entry
      for entry in pre_hooks
      if any('question-tool-conflict-gate.py' in h.get('command', '') for h in entry.get('hooks', []))
    ]
    self.assertEqual(
      len(matched_groups),
      1,
      'settings.json must wire question-tool-conflict-gate.py in PreToolUse',
    )
    self.assertIn('mcp__lcu__js', matched_groups[0].get('matcher', ''))


if __name__ == '__main__':
  unittest.main()
