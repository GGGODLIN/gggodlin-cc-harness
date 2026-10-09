import json, glob, os, time, collections
root = os.path.expanduser('~/.claude/projects'); cut = time.time() - 3 * 86400
per = collections.defaultdict(list); call = collections.defaultdict(list); odd = []; seen = set()
for f in glob.glob(root + '/**/*.jsonl', recursive=True):
  if '/subagents/' in f or os.path.getmtime(f) < cut: continue
  for line in open(f, errors='replace'):
    if '"durationMs"' not in line or '"hookEvent"' not in line: continue
    try: e = json.loads(line)
    except Exception: continue
    a = e.get('attachment') or {}
    if 'durationMs' not in a: continue
    key = (e.get('uuid'),)
    if key in seen: continue
    seen.add(key)
    ev, cmd, ms = a.get('hookEvent'), (a.get('command') or '')[:60], int(a['durationMs'])
    if a.get('type') != 'hook_success': odd.append((ev, a.get('type'), cmd, ms))
    per[(ev, cmd)].append(ms)
    call[(ev, a.get('toolUseID'))].append(ms)
def q(v, p): v = sorted(v); return v[min(len(v) - 1, int(p * len(v)))]
print('== 每支 hook（PreToolUse/PostToolUse/SessionStart 等），依 p95 排序，n>=20 ==')
for (ev, cmd), v in sorted(per.items(), key=lambda kv: -q(kv[1], .95)):
  if len(v) >= 20 and ev not in ('Stop',):
    print(f'{ev:18} n={len(v):5} p50={q(v,.5):5} p95={q(v,.95):5} max={max(v):6} >1s={sum(x>1000 for x in v):4}  {cmd}')
print('== 每次事件實際等待（同 toolUseID 取最慢）==')
by = collections.defaultdict(list)
for (ev, tid), v in call.items(): by[ev].append(max(v))
for ev, v in sorted(by.items()):
  print(f'{ev:18} events={len(v):5} p50={q(v,.5):5} p95={q(v,.95):5} p99={q(v,.99):6} max={max(v):6} >1s={sum(x>1000 for x in v)}')
print('== 非成功紀錄 ==')
for o in collections.Counter((a, b, c) for a, b, c, _ in odd).most_common(10): print(o)
