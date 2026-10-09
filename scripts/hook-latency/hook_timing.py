import json, sys, glob, os, time, collections, re
root = os.path.expanduser('~/.claude/projects')
cut = time.time() - 3 * 86400
files = [f for f in glob.glob(root + '/**/*.jsonl', recursive=True) if '/subagents/' not in f and os.path.getmtime(f) >= cut]
d = collections.defaultdict(list); src = collections.Counter()
for f in files:
  for line in open(f, errors='replace'):
    if '"durationMs"' not in line or ('hookInfos' not in line and 'hook_' not in line):
      continue
    try: e = json.loads(line)
    except Exception: continue
    if 'hookInfos' in e:
      ev = e.get('subtype') or e.get('type')
      for h in [h for h in e['hookInfos'] if 'durationMs' in h]:
        d[(ev, h.get('command', '')[:70])].append(int(h['durationMs']))
      src[ev] += 1
    a = e.get('attachment') or {}
    if a.get('type', '').startswith('hook_') and 'durationMs' in a and a.get('hookEvent') in ('UserPromptSubmit', 'Stop'):
      d[('att:' + a['hookEvent'], a.get('command', '')[:70])].append(int(a['durationMs']))
print('files', len(files), 'summary entries by subtype', dict(src))
def pct(v, p): v = sorted(v); return v[min(len(v) - 1, int(p * len(v)))]
for (ev, cmd), v in sorted(d.items(), key=lambda kv: -pct(kv[1], .95)):
  print(f'{ev[:26]:26} n={len(v):5} p50={pct(v,.5):6} p95={pct(v,.95):6} max={max(v):6}  {cmd}')
