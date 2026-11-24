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

const run = async ({ withPass = false, manyPass = false, batch2Empty = false, badPrimaryIndex = false, badReauditIndex = false, copiedMembers = false, topViolations } = {}) => {
  const calls = []
  const batches = Array.from({ length: 10 }, (_, index) => ({
    index: index + 1,
    range: { start: index * 2 + 1, end: index * 2 + 2 },
    path: `${out}/${date}-evidence-level-samples-batch-${index + 1}.txt`,
    audit_nonce: nonce,
  }))
  if (copiedMembers) batches[0].members = [{ path: '/model-invented/path' }]
  const passSet = manyPass ? new Set([1, 2, 3, 4, 5]) : withPass ? new Set([6]) : new Set()
  const agent = async (prompt, options) => {
    calls.push({ prompt, options })
    const label = options.label
    if (label === 'evidence-level-due') return { date, due: true, last_success_date: null, days_since: null }
    if (label === 'evidence-level-sampler') return {
      date, due: true, last_success_date: null, days_since: null, eligible: 20, sample_count: 20,
      audit_nonce: nonce, attempt_nonce: attempt, batches, challenge,
    }
    if (label.startsWith('evidence-level-audit-batch-')) {
      const batchIndex = Number(label.split('-').at(-1))
      if (batch2Empty && batchIndex === 2) throw new Error('empty output after 32K thinking tokens')
      const batch = batches[batchIndex - 1]
      return {
        audit_nonce: nonce, attempt_nonce: attempt, batch_index: batch.index, range: batch.range,
        rows: Array.from({ length: 2 }, (_, index) => {
          const sampleIndex = batch.range.start + index
          const pass = passSet.has(sampleIndex)
          return {
            sample_index: badPrimaryIndex && sampleIndex === 6 ? 7 : sampleIndex,
            result: pass ? 'PASS' : 'FAIL',
            findings: pass ? [] : [{ type: 'unsourced-number', quote: 'example' }],
          }
        }),
      }
    }
    if (label.startsWith('evidence-level-audit-item-')) {
      const sampleIndex = Number(label.split('-').at(-1))
      const pass = passSet.has(sampleIndex)
      return {
        audit_nonce: nonce, attempt_nonce: attempt, batch_index: 100 + sampleIndex, range: { start: sampleIndex, end: sampleIndex },
        rows: [{ sample_index: sampleIndex, result: pass ? 'PASS' : 'FAIL', findings: pass ? [] : [{ type: 'unsourced-number', quote: 'example' }] }],
      }
    }
    if (label === 'evidence-level-reaudit-preparer') return { date, reaudit_sample_count: passSet.size, reaudit_nonce: reauditNonce }
    if (label === 'evidence-level-reaudit') return { audit_nonce: reauditNonce, rows: [{ sample_index: badReauditIndex ? 6 : 1, result: 'PASS', findings: [] }] }
    if (label.startsWith('evidence-level-reaudit-batch-')) {
      const rBatchIndex = Number(label.split('-').at(-1))
      const start = (rBatchIndex - 1) * 2 + 1
      const end = Math.min(rBatchIndex * 2, passSet.size)
      return {
        audit_nonce: reauditNonce, attempt_nonce: attempt, batch_index: rBatchIndex, range: { start, end },
        rows: Array.from({ length: end - start + 1 }, (_, idx) => ({
          sample_index: badReauditIndex && start + idx === 2 ? 9 : start + idx,
          result: 'PASS',
          findings: [],
        })),
      }
    }
    if (label === 'evidence-level-finalizer') return {
      date, ok: true, report_path: `${out}/${date}-evidence-level.md`, manifest_path: `${out}/${date}-evidence-level-manifest.json`,
      eligible: 20, sample_count: 20, tp_style_violation_count: 20 - passSet.size,
      audit_nonce: nonce,
      reaudit_sample_count: passSet.size,
      reaudit_nonce: passSet.size > 0 ? reauditNonce : null,
      top_violations: topViolations ?? [{ type: 'unsourced-number', count: 20 - passSet.size }], challenge,
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
  assert.equal(auditors.length, 10)
  for (const { prompt, options } of auditors) {
    assert.deepEqual(options.schema.properties.rows.items.required, ['sample_index', 'result', 'findings'])
    assert.equal(prompt.includes('不要回傳 timestamp、session 或 path'), true)
    assert.equal(prompt.includes('身分欄位逐字照抄'), false)
  }
})

test('workflow splits a 32K-truncated two-sample batch into single-item retries and batches >2 PASS re-audits', async () => {
  const fallback = await run({ manyPass: true, batch2Empty: true })
  assert.equal(fallback.result.ran.includes('evidence-level'), true)
  const itemCalls = fallback.calls.filter(({ options }) => options.label.startsWith('evidence-level-audit-item-'))
  assert.deepEqual(itemCalls.map(({ options }) => options.label), ['evidence-level-audit-item-3', 'evidence-level-audit-item-4'])
  const reauditBatchCalls = fallback.calls.filter(({ options }) => options.label.startsWith('evidence-level-reaudit-batch-'))
  assert.equal(reauditBatchCalls.length, 3)
  assert.equal(reauditBatchCalls.every(({ prompt }) => prompt.includes('不沿用主審序號')), true)
  const badMany = await run({ manyPass: true, badReauditIndex: true })
  assert.equal(badMany.result.failed.includes('evidence-level'), true)
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
