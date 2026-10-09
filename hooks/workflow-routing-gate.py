#!/usr/bin/env python3
# PreToolUse:Workflow — workflow agent() 不經過 T2-routing-gate（subagent-routing.md「Workflow 內 agent() 不 fire hook」），
# 沒寫 model／agentType 的 agent() 會默默繼承 main 的 model（main 是 Fable 時直接燒週額度）。本 gate 補這個缺口。
#
# Threat model：防漂移（誠實但健忘的 author 漏寫），不防主動規避。
# 不承諾完整語意，只認常見入口：只擋「確定漏寫」——單參數 agent(x)，或 opts 是物件字面值且頂層沒有
# model／agentType／spread。opts 是變數、函式呼叫、三元式時看不透，放行。
# 明文不保證：寫了 model 但選錯分類照過；`const a = agent; a(x)` 這類別名照過；agentType:'fork' 照過。
# 判不出來（讀不到 scriptPath、具名 workflow 找不到檔、tokenizer 例外）一律放行：本 gate 是提示型偏嚴，
# 誤攔會擋掉每日 digest／本機分析，代價高於漏攔。
# 停用開關：touch ~/.claude/hooks/workflow-routing-gate.off
# Codex 端不搬：Codex 已於 2026-09-20 停用，且 Workflow tool 是 CC 專屬。

import json
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
OFF_SENTINEL = Path.home() / '.claude/hooks/workflow-routing-gate.off'
WORKFLOW_DIRS = [Path.home() / '.claude/workflows']
ROUTING_DOC = '~/.claude/references/subagent-routing.md「B. Workflow author 寫 script」段'
IDENT_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$')


def code_mask(src):
  """Return a copy of src where every char inside strings/comments is replaced by a space.

  Template literal ${...} bodies stay as code, because agent() is often called inside them-free
  helper code but prompts are built with templates; nested templates inside ${} are handled
  with an explicit stack.
  """
  out = list(src)
  i, n = 0, len(src)
  stack = []  # entries: 'tpl' (inside template text) or 'expr' (inside ${ } with brace depth)
  depth = []
  while i < n:
    c = src[i]
    in_tpl = stack and stack[-1] == 'tpl'
    if in_tpl:
      if c == '\\':
        out[i] = ' '
        if i + 1 < n:
          out[i + 1] = ' '
        i += 2
        continue
      if c == '`':
        stack.pop()
        i += 1
        continue
      if c == '$' and i + 1 < n and src[i + 1] == '{':
        stack.append('expr')
        depth.append(0)
        i += 2
        continue
      out[i] = ' '
      i += 1
      continue
    if c == '/' and i + 1 < n and src[i + 1] == '/':
      j = src.find('\n', i)
      j = n if j == -1 else j
      for k in range(i, j):
        out[k] = ' '
      i = j
      continue
    if c == '/' and i + 1 < n and src[i + 1] == '*':
      j = src.find('*/', i + 2)
      j = n if j == -1 else j + 2
      for k in range(i, j):
        if out[k] != '\n':
          out[k] = ' '
      i = j
      continue
    if c in ('"', "'"):
      j = i + 1
      while j < n and src[j] != c and src[j] != '\n':
        j += 2 if src[j] == '\\' else 1
      for k in range(i + 1, min(j, n)):
        out[k] = ' '
      i = j + 1
      continue
    if c == '`':
      stack.append('tpl')
      i += 1
      continue
    if stack and stack[-1] == 'expr':
      if c == '{':
        depth[-1] += 1
      elif c == '}':
        if depth[-1] == 0:
          stack.pop()
          depth.pop()
          i += 1
          continue
        depth[-1] -= 1
    i += 1
  return ''.join(out)


def split_top_level_args(masked, start):
  """start points just after '('. Returns (list of (a, b) arg spans, end index) or None."""
  spans, d, seg_start, i = [], 0, start, start
  while i < len(masked):
    c = masked[i]
    if c in '([{':
      d += 1
    elif c in ')]}':
      if d == 0:
        if c != ')':
          return None
        spans.append((seg_start, i))
        return spans, i
      d -= 1
    elif c == ',' and d == 0:
      spans.append((seg_start, i))
      seg_start = i + 1
    i += 1
  return None


def object_has_routing(src, masked, a, b):
  """src/masked[a:b] is an object literal '{...}'. True if a top-level key is model/agentType or a spread.

  Structure comes from masked (strings blanked); key text comes from src so quoted keys still count.
  """
  end = masked.rfind('}', a, b)
  d, entry_start, entries = 0, a + 1, []
  for i in range(a + 1, end):
    c = masked[i]
    if c in '([{':
      d += 1
    elif c in ')]}':
      d -= 1
    elif c == ',' and d == 0:
      entries.append((entry_start, i))
      entry_start = i + 1
  entries.append((entry_start, end))
  for s0, s1 in entries:
    e = src[s0:s1].strip()
    if e.startswith('...'):
      return True
    colon = masked[s0:s1].find(':')
    key = (src[s0:s0 + colon] if colon != -1 else src[s0:s1]).strip().strip('\'"')
    if key in ('model', 'agentType'):
      return True
  return False


def find_missing(src):
  """Return 1-indexed line numbers of agent() calls that provably lack model/agentType."""
  masked = code_mask(src)
  missing, i = [], 0
  while True:
    i = masked.find('agent', i)
    if i == -1:
      return missing
    prev = masked[i - 1] if i > 0 else ''
    j = i + 5
    while j < len(masked) and masked[j] in ' \t':
      j += 1
    is_call = (j < len(masked) and masked[j] == '('
               and prev not in IDENT_CHARS and prev != '.'
               and (i + 5 >= len(masked) or masked[i + 5] not in IDENT_CHARS))
    if not is_call:
      i += 5
      continue
    parsed = split_top_level_args(masked, j + 1)
    if parsed is None:
      i = j + 1
      continue
    spans, _end = parsed
    spans = [(a, b) for a, b in spans if masked[a:b].strip()]
    line = src.count('\n', 0, i) + 1
    if len(spans) == 1:
      missing.append(line)
    elif len(spans) >= 2:
      a, b = spans[1]
      text = masked[a:b].strip()
      if text.startswith('{') and text.endswith('}'):
        lead = a + (len(masked[a:b]) - len(masked[a:b].lstrip()))
        if not object_has_routing(src, masked, lead, b):
          missing.append(line)
    i = j + 1


def load_script(tool_input):
  script = tool_input.get('script')
  if isinstance(script, str) and script:
    return script, 'inline script'
  path = tool_input.get('scriptPath')
  if isinstance(path, str) and path:
    p = Path(path).expanduser()
    return p.read_text(encoding='utf-8'), str(p)
  name = tool_input.get('name')
  if isinstance(name, str) and name:
    for d in WORKFLOW_DIRS:
      p = d / f'{name}.js'
      if p.is_file():
        return p.read_text(encoding='utf-8'), str(p)
  return None, None


def evaluate(payload):
  if payload.get('tool_name') != 'Workflow':
    return None
  tool_input = payload.get('tool_input')
  if not isinstance(tool_input, dict):
    return None
  src, origin = load_script(tool_input)
  if src is None:
    return None
  missing = find_missing(src)
  if not missing:
    return None
  lines = ', '.join(str(n) for n in missing[:10])
  more = f'（另 {len(missing) - 10} 處）' if len(missing) > 10 else ''
  reason = (
    '[workflow-routing-gate] 這支 workflow 有 agent() 沒寫 model 也沒寫 agentType，'
    '會默默繼承 main session 的 model。'
    f'先讀 {ROUTING_DOC}，照分類改寫後再送：'
    "判斷類 agentType:'routed-judge'、實作類 agentType:'routed-impl'、機械類 agentType:'routed-mech'"
    "（要 haiku 就再加 model:'haiku'）。"
    '只接受 opts 物件字面值裡寫出 model、agentType 或 spread；opts 用變數傳入的呼叫不會被擋。'
    f'誤攔時的停用開關：touch {OFF_SENTINEL}。'
    f'來源：{origin}；缺漏行號：{lines}{more}'
  )
  return {
    'hookSpecificOutput': {
      'hookEventName': 'PreToolUse',
      'permissionDecision': 'deny',
      'permissionDecisionReason': reason,
    }
  }


def main():
  if OFF_SENTINEL.exists():
    return 0
  try:
    payload = json.load(sys.stdin)
  except (json.JSONDecodeError, OSError, ValueError):
    return 0
  try:
    decision = evaluate(payload) if isinstance(payload, dict) else None
  except Exception:
    return 0
  if decision is not None:
    print(json.dumps(decision, ensure_ascii=False))
  return 0


if __name__ == '__main__':
  raise SystemExit(main())
