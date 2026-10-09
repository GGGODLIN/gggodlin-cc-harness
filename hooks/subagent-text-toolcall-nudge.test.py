#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = Path(__file__).with_name('subagent-text-toolcall-nudge.py')
failures = []


def run(payload, env_extra=None, raw=None):
  tmp = tempfile.mkdtemp()
  log = Path(tmp) / 'audit.jsonl'
  env = dict(os.environ, SUBAGENT_TEXT_TOOLCALL_NUDGE_LOG=str(log))
  env.pop('SUBAGENT_TEXT_TOOLCALL_NUDGE_DISABLED', None)
  env.update(env_extra or {})
  data = raw if raw is not None else json.dumps(payload)
  proc = subprocess.run([sys.executable, str(HOOK)], input=data, capture_output=True, text=True, env=env, timeout=10)
  out = json.loads(proc.stdout or 'null')
  rows = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() and log.is_file() else []
  return proc.returncode, out, rows, log


def check(name, cond):
  print(('PASS ' if cond else 'FAIL ') + name)
  if not cond:
    failures.append(name)


def stop(msg, active=False):
  return {'hook_event_name': 'SubagentStop', 'agent_type': 'routed-judge', 'agent_id': 'a1', 'session_id': 's1', 'stop_hook_active': active, 'last_assistant_message': msg}


code, out, rows, _ = run(stop('檔案讀完了，結論是 A 比 B 快 12%。'))
check('known-good plain report releases', code == 0 and out == {} and rows == [])

for label, msg in [
  ('glm tool_call', '我先載入 Chrome 工具。<tool_call>ToolSearch(select:mcp__x)</tool_call>'),
  ('deepseek DSML', '<｜DSML｜tool_calls> <｜DSML｜invoke name="Bash">'),
  ('invoke name', '現在實際發出查詢： <invoke name="WebSearch"> <parameter name="query">x</parameter>'),
]:
  code, out, rows, _ = run(stop(msg))
  check(f'known-bad {label} blocks with feedback', code == 0 and out.get('decision') == 'block' and 'SUBAGENT_TOOLCALL_FAILED' in out.get('reason', ''))
  check(f'known-bad {label} audited once as block', len(rows) == 1 and rows[0]['decision'] == 'block' and rows[0]['agent_type'] == 'routed-judge')

code, out, rows, _ = run(stop('範例寫法是 `<tool_call>Bash(ls)</tool_call>`，這只是引用。'))
check('boundary inline code quote releases', out == {} and rows == [])
code, out, rows, _ = run(stop('格式如下：\n```\n<｜DSML｜invoke name="Bash">\n```\n以上是文件範例。'))
check('boundary fenced quote releases', out == {} and rows == [])
code, out, rows, _ = run(stop('提到 tool_call 這個詞但沒有角括號。'))
check('boundary bare word releases', out == {} and rows == [])

code, out, rows, _ = run(stop('<tool_call>Bash(ls)</tool_call>', active=True))
check('second round (stop_hook_active) releases but audits', out == {} and len(rows) == 1 and rows[0]['decision'] == 'release')

code, out, rows, _ = run(stop('<tool_call>Bash(ls)</tool_call>'), env_extra={'SUBAGENT_TEXT_TOOLCALL_NUDGE_DISABLED': '1'})
check('recovery switch disables', out == {} and rows == [])

code, out, rows, _ = run(None, raw='not json')
check('malformed payload fails open', code == 0 and out == {})
code, out, rows, _ = run({'last_assistant_message': None})
check('missing message fails open', out == {})

with tempfile.TemporaryDirectory() as tmp:
  target = Path(tmp) / 'victim.txt'
  target.write_text('keep')
  link = Path(tmp) / 'audit.jsonl'
  link.symlink_to(target)
  code, out, rows, _ = run(stop('<tool_call>x</tool_call>'), env_extra={'SUBAGENT_TEXT_TOOLCALL_NUDGE_LOG': str(link)})
  check('symlink log refused, decision still made', out.get('decision') == 'block' and target.read_text() == 'keep')
  hard = Path(tmp) / 'hard.jsonl'
  os.link(target, hard)
  run(stop('<tool_call>x</tool_call>'), env_extra={'SUBAGENT_TEXT_TOOLCALL_NUDGE_LOG': str(hard)})
  check('hard-link log refused', target.read_text() == 'keep')
  fifo = Path(tmp) / 'fifo.jsonl'
  os.mkfifo(fifo)
  try:
    code, out, rows, _ = run(stop('<tool_call>x</tool_call>'), env_extra={'SUBAGENT_TEXT_TOOLCALL_NUDGE_LOG': str(fifo)})
    check('fifo log does not hang', out.get('decision') == 'block')
  except subprocess.TimeoutExpired:
    check('fifo log does not hang', False)

code, out, rows, _ = run(stop('\x1b[31m<tool_call>‮evil</tool_call>'))
check('control and bidi chars not echoed into feedback', out.get('decision') == 'block' and '‮' not in out.get('reason', '') and '\x1b' not in out.get('reason', ''))

self_src = HOOK.read_text()
code, out, rows, _ = run(stop('我把 hook 原始碼貼給你看：\n```python\n' + self_src[:400] + '\n```'))
check('self lifecycle: quoting own source in a fence releases', out == {})

if failures:
  print(f'{len(failures)} FAILED')
  sys.exit(1)
print('ALL-SUBAGENT-NUDGE-TESTS-PASSED')
