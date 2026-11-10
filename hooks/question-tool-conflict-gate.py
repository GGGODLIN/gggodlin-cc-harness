#!/usr/bin/env python3
# 防漂移型 PreToolUse gate（question-tool-conflict-gate）：
# Threat model：
# - 對誰有效：防誠實但搶拍的模型在同一回合已輸出
#   「### 第 N/M 題」「### 待拍板」「**待你拍板」等選擇題文字後，同回合尾端又夾帶工具呼叫（Skill/Read/Edit/Bash 等），
#   導致 Claude Code 不停下來等使用者打字、直接執行工具並跳題自答。
# - 明文不保證：
#   1. 字串比對型 gate 不承諾完整自然語言理解，只認常見訪談／待拍板標題與選擇句型；未命中句型則放行。
#   2. 字串比對型 gate 也會攔到同回合文字中未放進程式碼區塊（```）或引言（>）的待拍板標題樣本
#      （替代路徑：把樣本包進 ``` 程式碼區塊或 > 引言，或先結束提問回合、等使用者回覆後再呼叫工具）。
#   3. 每個問題區塊（question_key）最多攔截 2 次即由 loop guard 放行，避免極端情況下 session 死鎖。
# Surface 四分表：
# - Locked: ~/.claude/hooks/question-tool-conflict-gate.py 與 ~/.claude/hooks/question-tool-conflict-gate.test.py
# - Editable: 待檢工具呼叫與對話回覆
# - Append-only: ~/.claude/logs/question-tool-conflict-audit.jsonl
# - Human-controlled: ~/.claude/settings.json hooks 註冊
# 自身生命週期三路徑：
# - bootstrap: 掛上 settings.json 前先建立本檔與測試檔並跑通契約測試
# - update: 一般回合（未同回合先印出待拍板問句）直接以 Edit/Write/Bash 修改本檔與跑測試；若誤觸同回合問句，最多 2 次後 loop guard 自動放行
# - recovery: 設環境變數 QUESTION_TOOL_GATE_DISABLE=1 或從 ~/.claude/settings.json 移除本 hook
# 本檔在契約測試底下：python3 ~/.claude/hooks/question-tool-conflict-gate.test.py
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
import time

TAIL_BYTES = 131072
LOG_LIMIT = 512 * 1024
MAX_BLOCKS_PER_QUESTION = 2

FENCED_CODE_RE = re.compile(r'```.*?```|~~~.*?~~~', re.DOTALL)
BLOCKQUOTE_LINE_RE = re.compile(r'(?m)^\s*>.*$')
INLINE_CODE_RE = re.compile(r'`[^`\n]+`')
CJK_QUOTED_SPEECH_RE = re.compile(r'「[^」\n]+」|『[^』\n]+』')
CONTROL_BIDI_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f‎‏‪-‮⁦-⁩]')

PENDING_QUESTION_RE = re.compile(
  r'(?m)'
  r'(?:^#{1,4}\s*第\s*\d+\s*/\s*\d+\s*題[^\n]*)'
  r'|(?:^(?:#{1,4}\s*|\*\*)待(?:你)?(?:拍板|補確認)[^\n]*)'
  r'|(?:(?:你想選|請選擇)\s*[*`「『"\']?[A-Za-z1-9][*`」』"\']?\s*(?:（[^）\n]*）)?\s*(?:還是|或)\s*[*`「『"\']?[A-Za-z1-9])'
  r'|(?:請[^\n]{0,50}(?:按同意|完成[^\n]{0,15}授權)[^\n]{0,30}(?:後|再)[^\n]{0,20}(?:回我|跟我說|回覆))'
  r'|(?:Let\'s wait for your pick\b)'
)


def strip_non_prose(text):
  text = FENCED_CODE_RE.sub('', text)
  text = BLOCKQUOTE_LINE_RE.sub('', text)
  # 必須先對齊每一對反引號與引號再依長度過濾，否則同行前面的短 `Edit` 尾端反引號會與下一個開頭反引號錯配。
  text = INLINE_CODE_RE.sub(lambda m: '' if len(m.group(0)) >= 6 else m.group(0), text)
  text = CJK_QUOTED_SPEECH_RE.sub(lambda m: '' if len(m.group(0)) >= 6 else m.group(0), text)
  return text


def sanitize_snippet(text):
  cleaned = CONTROL_BIDI_RE.sub('', text)
  cleaned = INLINE_CODE_RE.sub('', cleaned).strip()
  return cleaned[:80]


def safe_dir(root):
  try:
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    return stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not (info.st_mode & 0o077)
  except OSError:
    return False


def append_audit(session_id, tool_name, outcome, question_key, snippet):
  audit_path = Path(
    os.environ.get(
      'QUESTION_TOOL_GATE_AUDIT',
      str(Path.home() / '.claude/logs/question-tool-conflict-audit.jsonl'),
    )
  )
  row = {
    'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    'session': session_id,
    'tool': tool_name,
    'outcome': outcome,
    'question_key': question_key,
    'snippet': snippet,
  }
  try:
    audit_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    parent_info = audit_path.parent.lstat()
    if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid():
      return
    fd = os.open(
      audit_path,
      os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
      0o600,
    )
    with os.fdopen(fd, 'a', encoding='utf-8') as handle:
      info = os.fstat(handle.fileno())
      if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_size > LOG_LIMIT
      ):
        return
      handle.write(json.dumps(row, ensure_ascii=False) + '\n')
  except OSError:
    return


def check_and_increment_block_count(state_root, session_id, question_key):
  # 若 state 目錄或檔案異常（symlink / FIFO / hard link），安全預設為攔截（回傳 True），不靜默放行。
  safe_session = re.sub(r'[^A-Za-z0-9_.-]', '_', session_id)[:128] or 'default'
  try:
    if not safe_dir(state_root):
      return True
    state_path = state_root / f'{safe_session}.json'
    fd = os.open(
      state_path,
      os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
      0o600,
    )
    with os.fdopen(fd, 'r+', encoding='utf-8') as handle:
      fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
      info = os.fstat(handle.fileno())
      if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or (info.st_mode & 0o077)
      ):
        return True
      raw = handle.read(8193)
      if len(raw) > 8192:
        return True
      data = json.loads(raw) if raw.strip() else {}
      if not isinstance(data, dict):
        data = {}
      counts = data.get('counts')
      if not isinstance(counts, dict):
        counts = {}
      current = counts.get(question_key, 0)
      if not isinstance(current, int) or current < 0:
        current = 0
      if current >= MAX_BLOCKS_PER_QUESTION:
        return False
      counts[question_key] = current + 1
      # 只保留最近 16 個 question_key，避免狀態檔無限增長。
      if len(counts) > 16:
        for old_key in list(counts.keys())[:-16]:
          counts.pop(old_key, None)
      handle.seek(0)
      handle.write(json.dumps({'counts': counts}, ensure_ascii=False))
      handle.truncate()
      return True
  except (OSError, ValueError, TypeError):
    return True


def is_stop_blocking_remediation(entry):
  # 當 Stop hook 發生 blocking error（要求模型先跑契約測試或 git closeout 才能結束回合）時，
  # 暫停攔截 Stop block 之前的待拍板問句，避免 PreToolUse 與 Stop hook 互鎖。
  # 普通 stop_hook_summary、一般 isMeta skill 載入或背景通知不觸發此放行；這只是暫停補工攔截，不代表使用者已回答原問題。
  if entry.get('type') == 'attachment':
    att = entry.get('attachment')
    if isinstance(att, dict) and att.get('type') == 'hook_blocking_error' and att.get('hookEvent') == 'Stop':
      return True
    return False
  if entry.get('type') == 'user' and entry.get('isMeta'):
    message = entry.get('message')
    if not isinstance(message, dict):
      return False
    content = message.get('content')
    if isinstance(content, list):
      text = '\n'.join(
        item.get('text', '')
        for item in content
        if isinstance(item, dict) and item.get('type') == 'text' and isinstance(item.get('text'), str)
      )
    elif isinstance(content, str):
      text = content
    else:
      return False
    return text.lstrip().startswith('Stop hook feedback:')
  return False


def is_human_turn_reset(entry):
  if entry.get('isMeta') or entry.get('isSidechain'):
    return False
  message = entry.get('message')
  if not isinstance(message, dict):
    return False
  content = message.get('content')
  # tool_result 回件不是真人回答，不能重置未答問題。
  if isinstance(content, list):
    if any(isinstance(item, dict) and item.get('type') == 'tool_result' for item in content):
      return False
    text = '\n'.join(
      item.get('text', '')
      for item in content
      if isinstance(item, dict) and item.get('type') == 'text' and isinstance(item.get('text'), str)
    )
  elif isinstance(content, str):
    text = content
  else:
    return False

  stripped = text.lstrip()
  if stripped.startswith(('<task-notification>', '<cross-session-message', '[SYSTEM NOTIFICATION')):
    return False
  # Compaction 續接摘要會重置壓縮前的舊回合狀態。
  if stripped.startswith('This session is being continued from a previous conversation'):
    return True

  origin = entry.get('origin')
  if not isinstance(origin, dict):
    # 未知或缺失 origin 一律 fail-closed（不當作真人回答重置）。
    return False
  kind = origin.get('kind')
  return kind in ('human', 'sdk')


def find_unanswered_question(transcript_path):
  path = Path(transcript_path)
  if not path.is_file() or path.is_symlink():
    return None
  size = path.stat().st_size
  offset = max(0, size - TAIL_BYTES)
  with path.open('rb') as handle:
    handle.seek(offset)
    chunk = handle.read(TAIL_BYTES)
  text_chunk = chunk.decode('utf-8', errors='replace')
  lines = text_chunk.splitlines()
  if offset > 0 and lines:
    lines = lines[1:]

  pending = None
  for idx, raw in enumerate(lines, 1):
    raw = raw.strip()
    if not raw:
      continue
    try:
      entry = json.loads(raw)
    except json.JSONDecodeError:
      continue
    if not isinstance(entry, dict) or entry.get('isSidechain'):
      continue
    entry_type = entry.get('type')
    if is_stop_blocking_remediation(entry):
      pending = None
    elif entry_type == 'user':
      if is_human_turn_reset(entry):
        pending = None
    elif entry_type == 'assistant':
      message = entry.get('message')
      if not isinstance(message, dict):
        continue
      content = message.get('content')
      if not isinstance(content, list):
        continue
      texts = [
        item.get('text', '')
        for item in content
        if isinstance(item, dict) and item.get('type') == 'text' and isinstance(item.get('text'), str)
      ]
      if not texts:
        continue
      prose = strip_non_prose('\n'.join(texts))
      match = PENDING_QUESTION_RE.search(prose)
      if match:
        row_id = entry.get('uuid')
        q_key = row_id if isinstance(row_id, str) and row_id else f'tail-line-{idx}'
        pending = (q_key, sanitize_snippet(match.group(0)))
  return pending


def main():
  if os.environ.get('QUESTION_TOOL_GATE_DISABLE') == '1':
    return
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, OSError):
    return
  if not isinstance(payload, dict):
    return
  if payload.get('hook_event_name', 'PreToolUse') != 'PreToolUse':
    return
  # 只管 main session 的真人互動回合；subagent 不與真人直接做多輪訪談。
  if payload.get('agent_id'):
    return
  tool_name = payload.get('tool_name', '')
  session_id = payload.get('session_id', '')
  transcript_path = payload.get('transcript_path', '')
  if not isinstance(session_id, str) or not session_id:
    return
  if not isinstance(transcript_path, str) or not transcript_path:
    return

  found = find_unanswered_question(transcript_path)
  if found is None:
    return
  question_key, snippet = found
  state_root = Path(
    os.environ.get(
      'QUESTION_TOOL_GATE_STATE_DIR',
      str(Path.home() / '.claude/hooks/state/question-tool-conflict'),
    )
  )
  should_block = check_and_increment_block_count(state_root, session_id, question_key)
  if not should_block:
    append_audit(session_id, tool_name, 'loop_guard_release', question_key, snippet)
    return

  append_audit(session_id, tool_name, 'deny', question_key, snippet)
  reason = (
    '偵測到本回合你已經向使用者輸出待拍板或逐題訪談問題，卻在同一回合呼叫了工具。'
    '在 Claude Code 中，同回合夾帶工具呼叫會直接繼續執行工具、搶走使用者的回答回合（導致跳題自答）。'
    '請不要呼叫任何工具，直接結束本回合等待使用者回覆；若只是引用範例文字，請放進 ``` 程式碼區塊或 > 引言中。'
    f'（命中段落：{snippet}｜tool={tool_name}）'
  )
  print(
    json.dumps(
      {
        'hookSpecificOutput': {
          'hookEventName': 'PreToolUse',
          'permissionDecision': 'deny',
          'permissionDecisionReason': reason,
        }
      },
      ensure_ascii=False,
    )
  )


if __name__ == '__main__':
  main()
