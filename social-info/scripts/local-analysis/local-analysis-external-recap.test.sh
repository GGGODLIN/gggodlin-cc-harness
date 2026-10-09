#!/bin/bash
set -euo pipefail

WORKFLOW="$HOME/.claude/workflows/local-analysis.js"

grep -F 'const EXTERNAL_RECAP = WORKFLOW_ARGS.external_recap' "$WORKFLOW" >/dev/null
grep -F 'const selectRoutineDue = ' "$WORKFLOW" >/dev/null
grep -F 'const routineDue = selectRoutineDue(CHANNELS, WEEKDAY, EXTERNAL_RECAP)' "$WORKFLOW" >/dev/null
grep -F "external_channels: EXTERNAL_RECAP ? [{ key: 'recap', report_path:" "$WORKFLOW" >/dev/null
grep -F 'attempted: [...due.map((c) => c.key), ...preflightFailed]' "$WORKFLOW" >/dev/null
grep -F '...due.filter((c) => !completedChannels.has(c.key)).map((c) => c.key)' "$WORKFLOW" >/dev/null

node --input-type=module - "$WORKFLOW" <<'NODE'
import fs from 'node:fs'

const source = fs.readFileSync(process.argv[2], 'utf8')
const coerceStart = source.indexOf('function coerceArgs(value) {')
const coerceEnd = source.indexOf('\n}\n\nconst WORKFLOW_ARGS', coerceStart)
if (coerceStart < 0 || coerceEnd < 0) throw new Error('coerceArgs not found')
const coerceArgs = Function(`${source.slice(coerceStart, coerceEnd + 2)}; return coerceArgs`)()
const defaultArgs = coerceArgs({ date: '2026-09-08', weekday: 2 })
if (defaultArgs.external_recap !== false) throw new Error('external_recap default must be false')
const externalArgs = coerceArgs({ date: '2026-09-08', weekday: 2, external_recap: true })
if (externalArgs.external_recap !== true) throw new Error('external_recap true not preserved')
let rejected = false
try { coerceArgs({ date: '2026-09-08', weekday: 2, external_recap: 'yes' }) } catch { rejected = true }
if (!rejected) throw new Error('external_recap non-boolean accepted')

const selectStart = source.indexOf('const isCalendarDue = ')
const selectEnd = source.indexOf('\nconst routineDue = ', selectStart)
if (selectStart < 0 || selectEnd < 0) throw new Error('due selection functions not found')
const selectRoutineDue = Function(`${source.slice(selectStart, selectEnd)}; return selectRoutineDue`)()
const channels = [
  { key: 'memory', freq: 'daily' },
  { key: 'recap', freq: 'daily' },
  { key: 'weekly', freq: 'weekly-tue' },
]
const internal = selectRoutineDue(channels, 2, false).map(c => c.key)
const external = selectRoutineDue(channels, 2, true).map(c => c.key)
if (JSON.stringify(internal) !== JSON.stringify(['memory', 'recap', 'weekly'])) throw new Error(`internal due mismatch: ${internal}`)
if (JSON.stringify(external) !== JSON.stringify(['memory', 'weekly'])) throw new Error(`external due mismatch: ${external}`)
NODE

printf 'local-analysis external recap contract: PASS\n'
