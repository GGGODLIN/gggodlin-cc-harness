#!/bin/bash
set -euo pipefail

WORKFLOW="$HOME/.claude/workflows/local-analysis.js"

grep -F '用 Write 工具把完整 markdown report 寫到' "$WORKFLOW" >/dev/null
grep -F '若檔案已存在，先用 Read 工具讀取後再覆寫' "$WORKFLOW" >/dev/null
grep -F '不要用 Bash redirect 寫報告' "$WORKFLOW" >/dev/null
grep -F '其他寫回也優先用專用 mutation 工具' "$WORKFLOW" >/dev/null
grep -F '只有 touch 這類無專用工具的操作才用 Bash' "$WORKFLOW" >/dev/null
grep -F '不得與動態 redirect 合併成同一條指令' "$WORKFLOW" >/dev/null
grep -F '最後一個動作必須呼叫 StructuredOutput 回傳 summary' "$WORKFLOW" >/dev/null
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
  '舊 claude -p wrapper',
  '不要把報告寫到 stdout',
  '先完成 source 指示要求的兩個 ledger append',
  '最後只用 StructuredOutput 回傳 summary',
]) {
  if (!recap.includes(phrase)) throw new Error(`recap completion contract missing: ${phrase}`)
}
if (ordinary.includes('舊 claude -p wrapper')) throw new Error('recap-specific contract leaked into ordinary channel')
NODE
if grep -F '用 Bash 把完整 markdown report 寫到' "$WORKFLOW" >/dev/null; then
  exit 1
fi

printf 'local-analysis workflow report contract: PASS\n'
