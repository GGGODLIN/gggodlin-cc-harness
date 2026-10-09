"""routed-judge 派工盤點 v2。

相對 v1 的修正（來自 2026-09-26 GPT-6 Pro 審查）：
- 以派工事件 timestamp 篩選時間窗，不只看檔案修改時間
- token 只在同一則 task-notification 內配對 tool-use-id 與 subagent_tokens
- 實際模型／effort 從該次子 agent 自己的 transcript 讀，連不到就標 unknown
"""
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path.home() / '.claude/projects'
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 30
END = dt.datetime.now(dt.timezone.utc)
START = END - dt.timedelta(days=DAYS)
OUT = Path(sys.argv[1])

NOTE = re.compile(r'<task-notification>(.*?)</task-notification>', re.S)
TID = re.compile(r'<tool-use-id>(toolu_\w+)</tool-use-id>')
TOK = re.compile(r'<subagent_tokens>(\d+)</subagent_tokens>')
AID = re.compile(r'agentId: (a[0-9a-f]{8,})')


def in_window(ts):
  if not ts:
    return False
  t = dt.datetime.fromisoformat(ts.replace('Z', '+00:00'))
  return START <= t <= END


def text_of(content):
  if isinstance(content, str):
    return content
  if isinstance(content, list):
    return ''.join(c.get('text', '') for c in content if isinstance(c, dict))
  return ''


calls, tokens, agent_ids = {}, {}, {}
cutoff_mtime = START.timestamp() - 86400
for p in ROOT.rglob('*.jsonl'):
  try:
    if p.stat().st_mtime < cutoff_mtime:
      continue
    raw = p.read_text(errors='replace')
    lines = raw.splitlines()
  except OSError:
    continue
  # 通知也會出現在 attachment／queue 類紀錄裡，只掃 user content 會漏掉約四分之一
  for block in NOTE.findall(raw.replace('\\n', '\n').replace('\\"', '"')):
    i, k = TID.search(block), TOK.search(block)
    if i and k:
      u = re.search(r'<tool_uses>(\d+)</tool_uses>', block)
      tokens.setdefault(i.group(1), (int(k.group(1)), int(u.group(1)) if u else None))
  for line in lines:
    try:
      d = json.loads(line)
    except ValueError:
      continue
    msg = d.get('message') or {}
    content = msg.get('content')
    if d.get('type') == 'assistant' and isinstance(content, list):
      for c in content:
        if c.get('type') == 'tool_use' and c.get('name') in ('Agent', 'Task'):
          inp = c.get('input') or {}
          if inp.get('subagent_type') == 'routed-judge' and in_window(d.get('timestamp')):
            calls.setdefault(c['id'], {
              'id': c['id'], 'ts': d.get('timestamp'), 'session': d.get('sessionId'),
              'project_dir': p.parts[len(ROOT.parts)], 'from_subagent': 'subagents' in p.parts,
              'caller_model': msg.get('model'), 'model_override': inp.get('model'),
              'description': inp.get('description'), 'prompt_len': len(inp.get('prompt') or ''),
              'prompt_head': (inp.get('prompt') or '')[:400],
            })
    if d.get('type') == 'user':
      tur = d.get('toolUseResult')
      if isinstance(content, list):
        for c in content:
          if c.get('type') != 'tool_result':
            continue
          tid = c.get('tool_use_id')
          if isinstance(tur, dict):
            if tur.get('agentId'):
              agent_ids[tid] = tur['agentId']
            if tur.get('totalTokens'):
              tokens[tid] = (tur.get('totalTokens'), tur.get('totalToolUseCount'))
          m = AID.search(text_of(c.get('content')))
          if m:
            agent_ids.setdefault(tid, m.group(1))
      for block in NOTE.findall(text_of(content)):
        i, k = TID.search(block), TOK.search(block)
        if i and k:
          u = re.search(r'<tool_uses>(\d+)</tool_uses>', block)
          tokens.setdefault(i.group(1), (int(k.group(1)), int(u.group(1)) if u else None))

runtime_cache = {}


def runtime(row, aid):
  f = ROOT / row['project_dir'] / (row['session'] or '') / 'subagents' / f'agent-{aid}.jsonl'
  if f not in runtime_cache:
    models, efforts = collections.Counter(), collections.Counter()
    try:
      for line in f.read_text(errors='replace').splitlines():
        for m in re.findall(r'"model":"([A-Za-z0-9.\-\[\]]+)"', line):
          models[m] += 1
        for e in re.findall(r'"effort":"([a-z]+)"', line):
          efforts[e] += 1
    except OSError:
      pass
    runtime_cache[f] = (models.most_common(1)[0][0] if models else None,
                        efforts.most_common(1)[0][0] if efforts else None)
  return runtime_cache[f]


rows = []
for tid, r in calls.items():
  aid = agent_ids.get(tid)
  r['agent_id'] = aid
  r['actual_model'], r['actual_effort'] = runtime(r, aid) if aid else (None, None)
  r['total_tokens'], r['tool_uses'] = tokens.get(tid, (None, None))
  rows.append(r)
rows.sort(key=lambda r: r['ts'])
OUT.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows))
print(json.dumps({
  'window': [START.isoformat()[:10], END.isoformat()[:10]], 'calls': len(rows),
  'with_agent_id': sum(1 for r in rows if r['agent_id']),
  'with_actual_model': sum(1 for r in rows if r['actual_model']),
  'with_tokens': sum(1 for r in rows if r['total_tokens']),
}))
