#!/bin/bash
set -euo pipefail

FILE="${RBA_SKILL_FILE:-/Users/you/.claude/skills/research-before-answer/SKILL.md}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

python3 - "$FILE" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding='utf-8')


def section(source, start, end):
  left = source.index(start)
  right = source.index(end, left)
  return source[left:right]


def validate(source):
  live = re.sub(r'<!--.*?-->', '', source, flags=re.S)
  inline = section(live, '## 交付前 inline 自查（R1–R3）', '### 抽樣 dispatch verify')
  dispatch = section(live, '### 抽樣 dispatch verify', '## 記憶升級')
  errors = []
  routing = section(live, '## 來源選路：先分最新外部題與個人歷史', '## 交付前 inline 自查（R1–R3）')
  checks = [
    ('external current routing', r'1\. 如果是最新外部事實查核或外部探索[^\n]*本機 memory、wiki、session、報告與歷史收錄不作探索入口，也不作搜尋失敗的替代', routing),
    ('current eligibility separate', r'2\. 如果同時問「我能不能用」[^\n]*目前帳號、設定或即時資格回應[^\n]*不因此觸發個人歷史檢索', routing),
    ('history retained', r'3\. 如果是個人歷史、既有決策或經驗回顧[^\n]*個人資料層', routing),
    ('blocked external no history fallback', r'\*\*外部搜尋受阻或沒答案\*\*[^\n]*不改查本機歷史收錄', routing),
    ('R1 local evidence', r'^- \*\*R1[^\n]*個人或本地現況可用權威檔案的 Read、git／CLI 原始輸出', inline),
    ('R2 decision claims', r'^- \*\*R2[^\n]*decision table 每一列[^\n]*不得拿來推薦或排除方案', inline),
    ('decision table source column', r'^- \*\*Decision table 固定形狀\*\*[^\n]*欄名逐字為 `來源`[^\n]*每列[^\n]*逐項對應[^\n]*不得交付推薦', inline),
    ('unknown is not counterevidence', r'^- \*\*未知不是反證\*\*[^\n]*不能改寫成「因此不選 X」[^\n]*判斷只引用已驗證部分', inline),
    ('R3 proxy target', r'^- \*\*R3[^\n]*observed metric → target outcome → attribution', inline),
    ('dispatch alternatives', r'^2\. decision table／兩個以上替代方案比較', dispatch),
    ('exclusive verdict', r'最後一行只能是 `VERDICT: COMPLIANT` 或 `VERDICT: VIOLATIONS:', dispatch),
    ('malformed verdict override', r'任一 FAIL 時，即使最後一行誤寫 COMPLIANT 也按 VIOLATIONS 處理', dispatch),
    ('single attempt', r'只有一次 auditor 額度', dispatch),
    ('no auditor continuation', r'不得用 SendMessage 續問同一個 auditor', dispatch),
    ('fixed discloses no second audit', r'FIXED_AFTER_AUDIT（R#）」並明寫「未經第二次獨立稽查', dispatch),
    ('failed narrows the claim', r'把不實或佐證不足的主張從 draft 刪除或收窄', dispatch),
    ('final binding', r'audit 後不得新增或改寫推薦理由', dispatch),
  ]
  for name, pattern, target in checks:
    if not re.search(pattern, target, flags=re.M):
      errors.append(name)
  if 'VERDICT: COMPLIANT | VIOLATIONS:' in live:
    errors.append('ambiguous verdict')
  return errors


errors = validate(text)
if errors:
  print('FAIL live contract:', ', '.join(errors))
  raise SystemExit(1)
print('PASS live contract')

r2_line = next(line for line in text.splitlines() if line.startswith('- **R2 '))
comment_mutant = text.replace(r2_line, f'<!-- {r2_line} -->', 1)
if not validate(comment_mutant):
  print('FAIL comment-only mutant passed')
  raise SystemExit(1)
print('PASS comment-only mutant rejected')

table_source_line = next(line for line in text.splitlines() if line.startswith('- **Decision table 固定形狀**'))
table_source_mutant = text.replace(table_source_line, '', 1)
if not validate(table_source_mutant):
  print('FAIL source-column mutant passed')
  raise SystemExit(1)
print('PASS source-column mutant rejected')

weak_source_mutant = text.replace(
  '每列在 `來源` 欄用「取捨 claim → URL／文件／指令輸出」逐項對應',
  '可以使用 `來源` 欄補充來源',
  1,
)
if not validate(weak_source_mutant):
  print('FAIL weak source-column mutant passed')
  raise SystemExit(1)
print('PASS weak source-column mutant rejected')

unknown_line = next(line for line in text.splitlines() if line.startswith('- **未知不是反證**'))
unknown_mutant = text.replace(unknown_line, '', 1)
if not validate(unknown_mutant):
  print('FAIL unknown-as-counterevidence mutant passed')
  raise SystemExit(1)
print('PASS unknown-as-counterevidence mutant rejected')

retry_mutant = text.replace('只有一次 auditor 額度', '最多可以再派一次 auditor', 1)
if not validate(retry_mutant):
  print('FAIL retry-loop mutant passed')
  raise SystemExit(1)
print('PASS retry-loop mutant rejected')

continuation_mutant = text.replace('不得用 SendMessage 續問同一個 auditor', '可用 SendMessage 續問同一個 auditor', 1)
if not validate(continuation_mutant):
  print('FAIL auditor-continuation mutant passed')
  raise SystemExit(1)
print('PASS auditor-continuation mutant rejected')

routing_line = next(line for line in text.splitlines() if line.startswith('1. 如果是最新外部事實查核或外部探索'))
if not validate(text.replace(routing_line, '', 1)):
  print('FAIL external-routing mutant passed')
  raise SystemExit(1)
print('PASS external-routing mutant rejected')

eligibility_line = next(line for line in text.splitlines() if line.startswith('2. 如果同時問「我能不能用」'))
if not validate(text.replace(eligibility_line, '', 1)):
  print('FAIL eligibility-routing mutant passed')
  raise SystemExit(1)
print('PASS eligibility-routing mutant rejected')

blocked_line = next(line for line in text.splitlines() if line.startswith('- **外部搜尋受阻或沒答案**'))
if not validate(text.replace(blocked_line, '', 1)):
  print('FAIL blocked-routing mutant passed')
  raise SystemExit(1)
print('PASS blocked-routing mutant rejected')

print('PASS=10 FAIL=0')
PY

python3 "$SCRIPT_DIR/decision-table-output-contract.py" --self-test
python3 "$SCRIPT_DIR/low-confidence-output-contract.py" --self-test
