#!/bin/bash
set -euo pipefail

WORKFLOW="${LOCAL_ANALYSIS_WORKFLOW:-${CLAUDE_CONFIG_DIR:-~/.claude}/workflows/local-analysis.js}"

grep -F '不要寫報告檔，也不要啟動寫報告的 agent' "$WORKFLOW" >/dev/null
grep -F '用 StructuredOutput 回傳 summary（3-5 行繁中）、report_markdown（完整正文，不是摘要' "$WORKFLOW" >/dev/null
grep -F 'deferred_writeback' "$WORKFLOW" >/dev/null
grep -F '報告將由 main 寫到' "$WORKFLOW" >/dev/null
node --input-type=module - "$WORKFLOW" <<'NODE'
import fs from 'node:fs'

const workflow = fs.readFileSync(process.argv[2], 'utf8')
const start = workflow.indexOf('const llmPrompt = (c) => {')
const end = workflow.indexOf('\n}\n\nconst shellPrompt', start)
if (start < 0 || end < 0) throw new Error('llmPrompt function not found')
const expression = workflow.slice(start + 'const llmPrompt = '.length, end + 2)
const llmPrompt = Function('OUT_DIR', 'DATE', `return ${expression}`)('/tmp/reports', '2026-08-19')
const recap = llmPrompt({ key: 'recap', src: '/tmp/recap-daily.sh' })
const ordinary = llmPrompt({ key: 'wiki-lint', src: '/tmp/wiki-lint-daily.sh' })
for (const phrase of [
  'recap source 是 claude -p wrapper',
  'stdout 報告規則在本子任務改為 report_markdown',
  '兩份 ledger 都不得寫入',
  '最後只用 StructuredOutput 回傳資料',
]) {
  if (!recap.includes(phrase)) throw new Error(`recap completion contract missing: ${phrase}`)
}
if (ordinary.includes('recap source 是 claude -p wrapper')) {
  throw new Error('recap-specific contract leaked into ordinary channel')
}
NODE
if grep -F '用 Bash 把完整 markdown report 寫到' "$WORKFLOW" >/dev/null; then
  exit 1
fi

printf 'local-analysis workflow report contract: PASS\n'
