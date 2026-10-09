import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

const source = fs.readFileSync(new URL('../local-analysis.js', import.meta.url), 'utf8')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor

const run = async (auditResult = { ok: true, silent: false }) => {
  const calls = []
  const agent = async (prompt, options) => {
    calls.push({ prompt, options })
    if (options.label === 'evidence-level-due') return { date: '2026-10-05', due: false, last_success_date: '2026-10-04', days_since: 1 }
    if (options.label === 'session-audit') return auditResult
    if (options.schema?.required?.includes('silent')) return { ok: true, silent: true }
    return { summary: `${options.label} summary`, report_markdown: `# ${options.label}`, deferred_writeback: '' }
  }
  const compile = new AsyncFunction('args', 'phase', 'log', 'parallel', 'agent', 'Buffer', source.replace('export const meta =', 'const meta ='))
  const result = await compile({ date: '2026-10-05', weekday: 1 }, () => {}, () => {}, (thunks) => Promise.all(thunks.map((thunk) => thunk())), agent, Buffer)
  return { result, calls }
}

test('daily-local reads current coverage without running the analyzer', async () => {
  const { result, calls } = await run()
  const call = calls.find(({ options }) => options.label === 'session-audit')
  assert.ok(call, 'session-audit must be a daily channel')
  assert.ok(call.prompt.includes('session-audit-daily.sh'))
  assert.ok(call.prompt.includes('2026-10-05 true'), 'coverage must not reuse a stale same-day report')
  const channel = result.channels.find(({ key }) => key === 'session-audit')
  assert.equal(channel.needs_read, true)
  assert.equal(channel.scope, 'coverage-only')
  assert.ok(result.next_action.includes('不新增 H/M/L 或 pending-actions'))
  assert.ok(result.next_action.includes('trial-review'))
})

test('a failed coverage reader is failed rather than counted as analyzed', async () => {
  const { result } = await run({ ok: false, silent: false })
  assert.ok(result.failed.includes('session-audit'))
  assert.ok(!result.ran.includes('session-audit'))
  assert.ok(!result.channels.some(({ key }) => key === 'session-audit'))
})
