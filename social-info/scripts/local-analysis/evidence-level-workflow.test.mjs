import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

const workflowPath = process.env.LOCAL_ANALYSIS_WORKFLOW ?? path.join(os.homedir(), '.claude/workflows/local-analysis.js')
const source = fs.readFileSync(workflowPath, 'utf8')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const date = '2026-09-27'
const out = '~/code/social-info/reports/local-analysis'
const nonce = '1'.repeat(64)
const attempt = '2'.repeat(64)
const challenge = '5'.repeat(64)
const reauditNonce = '6'.repeat(64)

const run = async ({ withPass = false, badPrimaryIndex = false, badReauditIndex = false, copiedMembers = false, topViolations } = {}) => {
  const calls = []
  const batches = Array.from({ length: 4 }, (_, index) => ({
    index: index + 1,
    range: { start: index * 5 + 1, end: index * 5 + 5 },
    path: `${out}/${date}-evidence-level-samples-batch-${index + 1}.txt`,
    audit_nonce: nonce,
  }))
  if (copiedMembers) batches[0].members = [{ path: '/model-invented/path' }]
  const agent = async (prompt, options) => {
    calls.push({ prompt, options })
    const label = options.label
    if (label === 'evidence-level-due') return { date, due: true, last_success_date: null, days_since: null }
    if (label === 'evidence-level-sampler') return {
      date, due: true, last_success_date: null, days_since: null, eligible: 20, sample_count: 20,
      audit_nonce: nonce, attempt_nonce: attempt, batches, challenge,
    }
    if (label.startsWith('evidence-level-audit-batch-')) {
      const batch = batches[Number(label.at(-1)) - 1]
      return {
        audit_nonce: nonce, attempt_nonce: attempt, batch_index: batch.index, range: batch.range,
        rows: Array.from({ length: 5 }, (_, index) => {
          const sampleIndex = batch.range.start + index
          const pass = withPass && sampleIndex === 6
          return {
            sample_index: badPrimaryIndex && sampleIndex === 6 ? 7 : sampleIndex,
            result: pass ? 'PASS' : 'FAIL',
            findings: pass ? [] : [{ type: 'unsourced-number', quote: 'example' }],
          }
        }),
      }
    }
    if (label === 'evidence-level-reaudit-preparer') return { date, reaudit_sample_count: 1, reaudit_nonce: reauditNonce }
    if (label === 'evidence-level-reaudit') return { audit_nonce: reauditNonce, rows: [{ sample_index: badReauditIndex ? 6 : 1, result: 'PASS', findings: [] }] }
    if (label === 'evidence-level-finalizer') return {
      date, ok: true, report_path: `${out}/${date}-evidence-level.md`, manifest_path: `${out}/${date}-evidence-level-manifest.json`,
      eligible: 20, sample_count: 20, tp_style_violation_count: withPass ? 19 : 20,
      audit_nonce: nonce,
      reaudit_sample_count: withPass ? 1 : 0,
      reaudit_nonce: withPass ? reauditNonce : null,
      top_violations: topViolations ?? [{ type: 'unsourced-number', count: withPass ? 19 : 20 }], challenge,
    }
    if (options.schema?.required?.includes('silent')) return { ok: true, silent: true }
    return { summary: 'fixture', report_markdown: 'fixture report', deferred_writeback: '' }
  }
  const compiled = new AsyncFunction('args', 'phase', 'log', 'parallel', 'agent', source.replace('export const meta =', 'const meta ='))
  const result = await compiled({ date, weekday: 7, external_recap: true }, () => {}, () => {}, (items) => Promise.all(items.map((item) => item())), agent)
  return { result, calls }
}

test('workflow accepts compact batches and requests only sample indices from auditors', async () => {
  const { result, calls } = await run()
  assert.equal(result.ran.includes('evidence-level'), true)
  const sampler = calls.find(({ options }) => options.label === 'evidence-level-sampler')
  assert.equal(Object.hasOwn(sampler.options.schema.properties.batches.items.properties, 'members'), false)
  const auditors = calls.filter(({ options }) => options.label.startsWith('evidence-level-audit-batch-'))
  assert.equal(auditors.length, 4)
  for (const { prompt, options } of auditors) {
    assert.deepEqual(options.schema.properties.rows.items.required, ['sample_index', 'result', 'findings'])
    assert.equal(prompt.includes('不要回傳 timestamp、session 或 path'), true)
    assert.equal(prompt.includes('身分欄位逐字照抄'), false)
  }
})

test('workflow accepts finalizer object keys in either order without accepting changed values', async () => {
  const reordered = await run({ topViolations: [{ count: 20, type: 'unsourced-number' }] })
  assert.equal(reordered.result.ran.includes('evidence-level'), true)
  assert.equal(reordered.result.failed.includes('evidence-level'), false)
  for (const topViolations of [
    [],
    [{ count: 19, type: 'unsourced-number' }],
    [{ count: 20, type: 'unsourced-completion' }],
    [{ count: 20, type: 'unsourced-number', extra: true }],
  ]) {
    const { result } = await run({ topViolations })
    assert.equal(result.failed.includes('evidence-level'), true)
  }
})

test('workflow binds reaudit indices to the PASS subset', async () => {
  const good = await run({ withPass: true })
  assert.equal(good.result.ran.includes('evidence-level'), true)
  assert.equal(good.calls.find(({ options }) => options.label === 'evidence-level-reaudit').prompt.includes('不沿用主審序號'), true)
  const bad = await run({ withPass: true, badReauditIndex: true })
  assert.equal(bad.result.failed.includes('evidence-level'), true)
  assert.equal(bad.calls.some(({ options }) => options.label === 'evidence-level-finalizer'), false)
})

test('workflow rejects an invalid primary index and a copied members table', async () => {
  for (const input of [{ badPrimaryIndex: true }, { copiedMembers: true }]) {
    const { result, calls } = await run(input)
    assert.equal(result.failed.includes('evidence-level'), true)
    assert.equal(calls.some(({ options }) => options.label === 'evidence-level-finalizer'), false)
  }
})
