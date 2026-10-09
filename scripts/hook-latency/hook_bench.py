import json, os, subprocess, time
H = os.path.expanduser('~/.claude/hooks')
bash_pre = {'tool_name': 'Bash', 'tool_input': {'command': 'ls', 'description': 'List files'}}
post_any = {'tool_name': 'Read', 'tool_input': {'file_path': '/tmp/x'}, 'tool_response': {}}
ups = {'prompt': '幫我把這個函式改成 async', 'origin': {'kind': 'human'}, 'promptSource': 'typed'}
cases = [
  ('PreToolUse:Bash', f'python3 {H}/pipestatus-zsh-gate.py', bash_pre),
  ('PreToolUse:Bash', f'{H}/agent-contract-validator-gate.sh', bash_pre),
  ('PreToolUse:Bash', f'python3 {H}/archify-raw-cli-gate.py', bash_pre),
  ('PreToolUse:Bash', f'python3 {H}/tool-upgrade-guard.py', bash_pre),
  ('PreToolUse:Bash', f'{H}/fable-gate.sh {H}/cd-cwd-persistence-nudge.sh', bash_pre),
  ('PostToolUse:*', f'{H}/session-limit-nudge.sh', post_any),
  ('PostToolUse:Bash', f'{H}/repeat-verify-reminder.sh', bash_pre),
  ('UserPromptSubmit', f'/usr/bin/python3 {H}/claude-config-lag-reminder.py', ups),
  ('UserPromptSubmit', f'{H}/model-drift-watch.sh', ups),
  ('UserPromptSubmit', f'{H}/recall-before-answer.sh', {**ups, 'prompt': '我記得這件事'}),
]
for ev, cmd, payload in cases:
  base = {'session_id': 'hook-bench', 'transcript_path': '/dev/null', 'cwd': os.path.expanduser('~/Desktop/projects'),
          'hook_event_name': ev.split(':')[0], **payload}
  ms = []
  for _ in range(10):
    t = time.monotonic()
    subprocess.run(cmd, shell=True, input=json.dumps(base, ensure_ascii=False), capture_output=True, text=True, timeout=30)
    ms.append(round((time.monotonic() - t) * 1000))
  ms.sort()
  print(f'{ev:18} p50={ms[5]:5} max={ms[-1]:5}  {cmd.replace(H, "~hooks")[:70]}')
