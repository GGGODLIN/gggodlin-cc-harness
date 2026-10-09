import json, glob, os, datetime, re, collections

base = os.path.expanduser('~/.claude/projects')
now = datetime.datetime.now(datetime.timezone.utc)
cut = (now - datetime.timedelta(days=30)).isoformat()
sev = collections.Counter()
runs = set()

for f in glob.glob(base + '/*/*.jsonl'):
    try:
        mt = datetime.datetime.fromtimestamp(os.path.getmtime(f), datetime.timezone.utc)
        if mt < now - datetime.timedelta(days=35):
            continue
        for line in open(f, errors='ignore'):
            if 'Must Fix' not in line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get('type') != 'assistant' or o.get('timestamp', '') < cut:
                continue
            for c in (o.get('message') or {}).get('content', []) or []:
                if isinstance(c, dict) and c.get('type') == 'text':
                    t = c.get('text', '')
                    if 'Must Fix' in t and '|' in t:
                        runs.add(f)
                        for m in re.finditer(r'(Must Fix|Should Fix|Nice to Have|參考用)', t):
                            sev[m.group(1)] += 1
    except Exception:
        continue

print('近 30 天出現 Must Fix 字樣的 pr-review session 檔數:', len(runs))
print('分級詞出現次數（含表頭/重複，僅供量級對照）:', dict(sev))
