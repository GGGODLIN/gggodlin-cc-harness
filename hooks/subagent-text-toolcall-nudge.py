#!/usr/bin/env python3
"""
Threat model: NUDGE-class SubagentStop hook, not a security gate. It targets an honest subagent
whose model emitted its native tool-call syntax (`<tool_call>`, DeepSeek `<｜DSML｜…>`, `<invoke
name=…>`) as plain text, so the harness never executed the tool and the subagent stopped with a
hollow result. Every broken or ambiguous path fails OPEN (prints `{}`).

String matching only: it does not promise full semantics and only recognises the common native
formats listed in SIGNATURES. It can also fire on a subagent that legitimately quotes such syntax
outside a code span; the feedback text tells that subagent to simply repeat its answer, and
`stop_hook_active` limits the nudge to one round per stop, so a false positive costs one extra turn.

It does NOT promise: that the subagent recovers (a free-pool model may repeat the same text
syntax — the feedback then asks it to lead with a warning line so main can see the result is not
trustworthy); catching hollow results that carry no tool syntax (title-only replies, "tool not
available" refusals); notifying main directly — SubagentStop output is fed back into the subagent,
never to the parent session (probed 2026-09-24).

Recovery: set SUBAGENT_TEXT_TOOLCALL_NUDGE_DISABLED=1, or drop the SubagentStop entry from
~/.claude/settings.json. Audit rows go to ~/.claude/logs/subagent-text-toolcall-nudge.jsonl
(append-only, pure log).

CC-only: SubagentStop last_assistant_message has no Codex counterpart, and Codex is retired
(2026-09-20), so this is not mirrored into ~/.codex/hooks/cc-hooks.json.
"""

import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

SIGNATURES = re.compile(
  r'<tool_call>|</tool_call>|<｜DSML｜|<\|tool_call|<invoke name=|<function_calls>'
  r'|to=functions\.|\bToolSearch\(select:|<tool_use>'
)
FENCE = re.compile(r'```.*?(```|$)', re.S)
INLINE = re.compile(r'`[^`\n]*`')

FEEDBACK = (
  '[subagent-text-toolcall-nudge] 你的最後回覆把工具呼叫寫成了文字（例如 <tool_call>、<｜DSML｜、<invoke>），'
  'harness 沒有執行它，所以這份結果是空的。請改用真正的工具呼叫把剩下的工作做完，再交最終回覆。'
  '如果你是刻意引用這類語法當範例，原樣再回覆一次即可。'
  '如果你做不到真正的工具呼叫，最終回覆第一行必須寫「⚠️ SUBAGENT_TOOLCALL_FAILED：工具沒有執行，以下結果不可信」，讓派工的 main 知道。'
)


def detect(text):
  if not isinstance(text, str) or not text:
    return None
  stripped = INLINE.sub('', FENCE.sub('', text))
  match = SIGNATURES.search(stripped)
  return match.group(0) if match else None


def audit(row):
  path = Path(os.environ.get('SUBAGENT_TEXT_TOOLCALL_NUDGE_LOG') or Path.home() / '.claude/logs/subagent-text-toolcall-nudge.jsonl')
  try:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK
    if hasattr(os, 'O_NOFOLLOW'):
      flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
      metadata = os.fstat(descriptor)
      if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        return
      os.write(descriptor, (json.dumps(row, ensure_ascii=False) + '\n').encode())
    finally:
      os.close(descriptor)
  except OSError:
    return


def main():
  if os.environ.get('SUBAGENT_TEXT_TOOLCALL_NUDGE_DISABLED') == '1':
    print('{}')
    return
  try:
    payload = json.load(sys.stdin)
  except (ValueError, OSError):
    print('{}')
    return
  if not isinstance(payload, dict):
    print('{}')
    return
  hit = detect(payload.get('last_assistant_message'))
  if not hit:
    print('{}')
    return
  active = bool(payload.get('stop_hook_active'))
  audit({
    'ts': datetime.now(timezone.utc).isoformat(),
    'decision': 'release' if active else 'block',
    'signature': hit,
    'agent_type': payload.get('agent_type'),
    'agent_id': payload.get('agent_id'),
    'session_id': payload.get('session_id'),
  })
  if active:
    print('{}')
    return
  print(json.dumps({'decision': 'block', 'reason': FEEDBACK}, ensure_ascii=False))


if __name__ == '__main__':
  try:
    main()
  except Exception:
    print('{}')
