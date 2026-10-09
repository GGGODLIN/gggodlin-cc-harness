import { execFileSync } from 'node:child_process'
import fs from 'node:fs'


const source = fs.readFileSync('~/.claude/workflows/local-analysis.js', 'utf8')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const compile = () => new AsyncFunction(
  'args',
  'phase',
  'log',
  'parallel',
  'agent',
  'Buffer',
  source.replace('export const meta =', 'const meta =')
)

const agent = async (_prompt, options) => {
  if (options.label === 'evidence-level-due') {
    return {
      date: '2026-08-11',
      due: false,
      last_success_date: '2026-08-10',
      days_since: 1,
    }
  }
  if (options.label === 'rba-verify-primary') return { eligible: 0, samples: [] }
  if (options.label === 'rba-verify-verifier') return { missed_claims: [], false_greens: [] }
  if (options.label === 'rba-verify-finalizer') {
    return {
      ok: true,
      report_path: '~/code/social-info/reports/local-analysis/2026-08-11-rba-verify.md',
    }
  }
  if (options.schema?.required?.includes('silent')) return { ok: true, silent: true }
  return { summary: `${options.label} summary` }
}
const parallel = (thunks) => Promise.all(thunks.map((thunk) => thunk()))
const result = await compile()(
  { date: '2026-08-11', weekday: 2 },
  () => {},
  () => {},
  parallel,
  agent,
  Buffer
)

const expected = "python3 ~/code/social-info/scripts/local-analysis/recurring-errors-promote.py --date 2026-08-11 --report '~/code/social-info/reports/local-analysis/2026-08-11-recurring-errors.md' --ledger '~/code/social-info/reports/local-analysis/pending-actions.jsonl' --aliases '~/code/social-info/scripts/local-analysis/recurring-errors-pattern-aliases.json'"
const fixtureCommand = result.recurring_promotion_cmd
  .replace(
    '~/code/social-info/reports/local-analysis/2026-08-11-recurring-errors.md',
    '~/code/social-info/tests/local_analysis/fixtures/2026-08-11-recurring-errors.md'
  )
  .replace(
    '~/code/social-info/reports/local-analysis/pending-actions.jsonl',
    '~/code/social-info/tests/local_analysis/fixtures/pending-actions.jsonl'
  )
const packet = JSON.parse(execFileSync('/bin/sh', ['-c', fixtureCommand], { encoding: 'utf8' }))
const checks = [
  ['星期二 reported channels 含 recurring-errors', result.channels.some((channel) => channel.key === 'recurring-errors')],
  ['workflow 回傳 deterministic recurring promotion 指令', result.recurring_promotion_cmd === expected],
  ['回傳指令可執行並產生單一 candidate packet', packet.date === '2026-08-11' && packet.eligible_count === 6 && packet.candidate !== null && typeof packet.candidate === 'object' && !Array.isArray(packet.candidate) && packet.candidate.source_key === 'recurring-errors:shell-eval-syntax' && packet.candidate.bucket === 'high' && packet.candidate.finding?.channel === 'recurring-errors'],
]
let failed = 0
for (const [name, passed] of checks) {
  if (!passed) failed++
  console.log(`${passed ? '✅' : '❌'} ${name}`)
}
process.exit(failed === 0 ? 0 : 1)
