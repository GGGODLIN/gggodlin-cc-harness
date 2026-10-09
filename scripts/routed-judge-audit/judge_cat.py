import json, sys, re, collections, statistics as st
rows=[json.loads(l) for l in open(sys.argv[1])]
CATS=[
 ('A skill-verify 稽核', r'^skill-verify:'),
 ('B RED/GREEN/REFACTOR 行為測試', r'\b(RED|GREEN|REFACTOR|Regression)\b|行為驗證|Behaviour dry-run|probe'),
 ('C review-implement 席位', r'review-implement-(selection|fable)'),
 ('D review-spec YAGNI c 席', r'YAGNI'),
 ('E 模型考試評分 exam2', r'^exam2'),
 ('F 批次分類／標註', r'(batch|chunk) ?\d|Classify|Judge (friction|Layer C)'),
 ('G 部落格產線 phase', r'^Phase \d'),
 ('H 網路研究／查證', r'Research|研究|Verify .*(alive|status|endorse|credential|demo|X posts)|status$|查 |fresh research|docs|Find .*tools|Fact-check|Mine awesome|Collect .*X|official|Read .* docs|Firstmate|diagram|OSS'),
 ('I 本機掃描／計數／抽取', r'Scan|Compute|Extract|inventory|Find fully|Trace|sweep|Aggregate|Audit .*(sessions|outcomes|samples)|evolution|Statusline'),
]
def cat(d):
  for name,p in CATS:
    if re.search(p,d or ''): return name
  return 'Z 其他（單次判斷／審查）'
g=collections.defaultdict(list)
for r in rows: g[cat(r['description'])].append(r)
tot=sum(r.get('total_tokens') or 0 for r in rows)
print('%-28s %5s %8s %10s %6s'%('群組','次數','中位token','token合計','佔比'))
for k in sorted(g):
  t=[r['total_tokens'] for r in g[k] if r.get('total_tokens')]
  s=sum(t); print('%-28s %5d %8s %10d %5.1f%%'%(k,len(g[k]),int(st.median(t)) if t else '-',s,100*s/tot))
print('total tokens',tot)
if len(sys.argv)>2:
  for r in g[sys.argv[2]]: print('  ',(r['description'] or '')[:80], r.get('total_tokens'), r.get('tool_uses'))
