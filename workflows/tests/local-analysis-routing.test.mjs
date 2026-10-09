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

const DAILY_CHANNELS = [
  'memory',
  'wiki-candidates',
  'wiki-cross-link',
  'wiki-graduation',
  'wiki-lint',
  'wiki-stale',
  'skill-desc-quality',
  'recap',
  'bumblebee',
  'symlink',
  'path-rot',
  'tool-updates',
  'skill-collision',
  'agnix',
  'ledger-lifecycle',
  'codex-cdp',
  'free-pool',
  'skill-changes',
  'failure-mode',
]
const INTERVAL_CHANNEL = 'evidence-level'
const WEEKLY_CHANNELS = [
  'deep-research-pending',
  'codemap',
  'distill',
  'recurring-errors',
  'rba-verify',
  'skill-upstream',
  'skill-doctor',
  'tool-reliability',
  'skill-evidence',
  'rules-size',
  'skill-trigger',
  'skillevaluator',
  'beads-aging',
]
const sameMembers = (actual, expected) =>
  JSON.stringify([...actual].sort()) === JSON.stringify([...expected].sort())

const validPrimary = {
  eligible: 3,
  samples: [
    { session: 's1', invoke: 'i1', path: '/tmp/s1.jsonl', topic: '繁中題目', claims: [], R1: 'PASS', R2: 'PASS', R3: 'PASS', note: '' },
    { session: 's2', invoke: 'i2', path: '/tmp/s2.jsonl', topic: 'two', claims: [], R1: 'PASS', R2: 'PASS', R3: 'PASS', note: '' },
    { session: 's3', invoke: 'i3', path: '/tmp/s3.jsonl', topic: 'three', claims: [], R1: 'PASS', R2: 'PASS', R3: 'PASS', note: '' },
  ],
}
const validVerifier = { missed_claims: [], false_greens: [] }
const deferredEvidence = {
  date: '2026-07-29',
  due: false,
  last_success_date: '2026-07-28',
  days_since: 1,
}
const evidenceSamples = Array.from({ length: 20 }, (_, index) => ({
  timestamp: `2026-07-29T${String(index + 1).padStart(2, '0')}:00:00.000Z`,
  session: `evidence-session-${index + 1}`,
  path: `~/.claude/projects/fixture/session-${index + 1}.jsonl`,
  row_index: index,
  answer: '這是超過兩百字的受評回答。'.repeat(20),
}))
const evidenceChallenge = 'a'.repeat(64)
const evidenceAuditNonce = '9'.repeat(64)
const evidenceAttemptNonce = '7'.repeat(64)
const evidenceReauditPath = `~/code/social-info/reports/local-analysis/2026-07-29-evidence-level-reaudit-samples-${evidenceAttemptNonce}.txt`
const evidenceBatchDescriptors = Array.from({ length: 4 }, (_, batchIndex) => {
  const index = batchIndex + 1
  const members = evidenceSamples.slice(batchIndex * 5, index * 5).map(({ timestamp, session, path, row_index }) => ({ timestamp, session, path, row_index }))
  return {
    index,
    range: { start: batchIndex * 5 + 1, end: index * 5 },
    members,
    path: `~/code/social-info/reports/local-analysis/2026-07-29-evidence-level-samples-batch-${index}.txt`,
    audit_nonce: evidenceAuditNonce,
  }
})
const evidenceBatchAudits = evidenceBatchDescriptors.map((batch, batchIndex) => ({
  audit_nonce: evidenceAuditNonce,
  attempt_nonce: evidenceAttemptNonce,
  batch_index: batch.index,
  range: batch.range,
  rows: batch.members.map((member, rowIndex) => {
    const pass = batchIndex === 0 && rowIndex === 0
    return {
      sample_index: batch.range.start + rowIndex,
      result: pass ? 'PASS' : 'FAIL',
      findings: pass ? [] : [{ type: 'unsourced-number', quote: '這是' }],
    }
  }),
}))
const evidenceAllFailBatches = evidenceBatchAudits.map((batch) => ({
  ...batch,
  rows: batch.rows.map((row) => ({
    ...row,
    result: 'FAIL',
    findings: [{ type: 'unsourced-number', quote: '這是' }],
  })),
}))
const evidenceAllPassBatches = evidenceBatchAudits.map((batch) => ({
  ...batch,
  rows: batch.rows.map((row) => ({ ...row, result: 'PASS', findings: [] })),
}))
const batchOverridesFor = (audits) => Object.fromEntries(audits.map((audit) => [`evidence-level-audit-batch-${audit.batch_index}`, audit]))
const evidenceSamplePacket = {
  date: '2026-07-29',
  due: true,
  last_success_date: null,
  days_since: null,
  eligible: 20,
  sample_count: 20,
  audit_nonce: evidenceAuditNonce,
  attempt_nonce: evidenceAttemptNonce,
  batches: evidenceBatchDescriptors.map(({ members, ...batch }) => batch),
  challenge: evidenceChallenge,
}
const evidenceFreshMissingBatchesPacket = Object.fromEntries(Object.entries(evidenceSamplePacket).filter(([key]) => key !== 'batches'))
const evidenceLegacySamplePacket = Object.fromEntries(Object.entries(evidenceSamplePacket).filter(([key]) => !['attempt_nonce', 'batches'].includes(key)))
const evidenceReauditNonce = '8'.repeat(64)
const evidenceAudit = {
  audit_nonce: evidenceAuditNonce,
  rows: evidenceBatchAudits.flatMap((batch) => batch.rows),
}
const validFinalizer = {
  ok: true,
  report_path: '~/code/social-info/reports/local-analysis/2026-07-29-rba-verify.md',
}

// 舊 receipt／packet 可能仍帶 digest 欄（含彼此矛盾的值）；decoder 要忽略、不驗，而不是崩潰或拒收（F2）。
const legacyDigest = (char) => char.repeat(64)
const evidenceLegacyDigestSamplePacket = {
  ...evidenceSamplePacket,
  samples_sha256: legacyDigest('1'),
  samples_file_sha256: legacyDigest('2'),
  manifest_hash: legacyDigest('3'),
  batches: evidenceSamplePacket.batches.map((batch, index) => ({
    ...batch,
    batch_sha256: legacyDigest(String(index + 4)),
    samples_sha256: index === 0 ? legacyDigest('5') : legacyDigest('6'),
  })),
}
const evidenceLegacyDigestBatchAudits = evidenceBatchAudits.map((audit, index) => ({
  ...audit,
  batch_sha256: legacyDigest('7'),
  samples_sha256: legacyDigest(String(index)),
}))
const evidenceLegacyDigestReauditPreparer = (date) => ({
  date,
  reaudit_sample_count: 1,
  reaudit_samples_file_sha256: legacyDigest('8'),
  reaudit_nonce: evidenceReauditNonce,
})

const runWorkflow = async (inputArgs, resultOverrides = {}, runtime = {}) => {
  const calls = []
  const logs = []
  const phases = []
  runtime.calls = calls
  runtime.phases = phases
  const agent = async (prompt, options) => {
    calls.push({ prompt, options })
    if (Object.prototype.hasOwnProperty.call(resultOverrides, options.label)) {
      const override = resultOverrides[options.label]
      if (override instanceof Error) throw override
      return override
    }
    const inputDate = typeof inputArgs === 'string' ? JSON.parse(inputArgs).date : inputArgs.date
    if (runtime.deferRoutineScanLabel === options.label && options.phase === 'Scan') {
      return new Promise((resolve) => {
        runtime.pendingRoutineResolvers ??= []
        runtime.pendingRoutineResolvers.push(() => {
          runtime.resolvedRoutineLabels ??= []
          runtime.resolvedRoutineLabels.push(options.label)
          resolve({ summary: 'deferred routine summary' })
        })
      })
    }
    if (options.label === 'evidence-level-due') return { ...deferredEvidence, date: inputDate }
    if (options.label === 'evidence-level-sampler') return { ...evidenceSamplePacket, date: inputDate }
    if (options.label.startsWith('evidence-level-audit-batch-')) {
      const batchIndex = Number(options.label.at(-1))
      const result = evidenceBatchAudits[batchIndex - 1]
      if (runtime.deferBatchAudits !== true) return result
      return new Promise((resolve) => {
        runtime.pendingBatchResolvers ??= []
        runtime.pendingBatchResolvers.push(() => {
          runtime.resolvedBatchLabels ??= []
          runtime.resolvedBatchLabels.push(options.label)
          resolve(result)
        })
      })
    }
    if (options.label === 'evidence-level-audit') return evidenceAudit
    if (options.label === 'evidence-level-reaudit-preparer') return {
      date: inputDate,
      reaudit_sample_count: 1,
      reaudit_nonce: evidenceReauditNonce,
    }
    if (options.label === 'evidence-level-reaudit') {
      const primary = resultOverrides['evidence-level-primary-merged'] ?? evidenceAudit
      return { audit_nonce: evidenceReauditNonce, rows: primary.rows.filter((row) => row.result === 'PASS').map((row, index) => ({ ...row, sample_index: index + 1 })) }
    }
    if (options.label === 'evidence-level-finalizer') return {
      date: inputDate,
      ok: true,
      report_path: `~/code/social-info/reports/local-analysis/${inputDate}-evidence-level.md`,
      manifest_path: `~/code/social-info/reports/local-analysis/${inputDate}-evidence-level-manifest.json`,
      eligible: 20,
      sample_count: 20,
      tp_style_violation_count: 19,
      audit_nonce: evidenceAuditNonce,
      reaudit_sample_count: 1,
      reaudit_nonce: evidenceReauditNonce,
      top_violations: [{ type: 'unsourced-number', count: 19 }],
      challenge: evidenceChallenge,
    }
    if (options.label === 'rba-verify-primary') return validPrimary
    if (options.label === 'rba-verify-verifier') return validVerifier
    if (options.label === 'rba-verify-finalizer') return validFinalizer
    if (options.schema?.required?.includes('silent')) {
      return { ok: true, silent: false }
    }
    return { summary: `${options.label} summary` }
  }
  const parallel = (thunks) => Promise.all(thunks.map((thunk) => thunk()))
  const result = await compile()(inputArgs, (title) => phases.push(title), (message) => logs.push(message), parallel, agent, undefined)
  return { result, calls, logs, phases }
}

let syntaxValid = true
try {
  compile()
} catch {
  syntaxValid = false
}

const stringArgsRun = await runWorkflow('{"date":"2026-07-29","weekday":2}')
const stringWeekdayRun = await runWorkflow({ date: '2026-07-29', weekday: '2' })
let malformedArgsRejected = false
try {
  await runWorkflow('{not-json')
} catch {
  malformedArgsRejected = true
}
const silentRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  { bumblebee: { channel: 'wrong', report_path: '/tmp/wrong.md', ok: true, silent: true } }
)
const failureRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  { bumblebee: null }
)
const memoryRecoveryRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    memory: null,
    'memory-recovery': { ok: true, summary: 'recovered memory summary' },
  }
)
const REPORT_DIR = '~/code/social-info/reports/local-analysis'
const llmCheckCall = silentRun.calls.find((call) => call.options.label === 'llm-report-check')
const llmCheckedPaths = [...(llmCheckCall?.prompt.matchAll(/'([^']+\.md)'/g) ?? [])].map((m) => m[1])
const missingReportRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'llm-report-check': {
      present: llmCheckedPaths.filter((path) => path !== `${REPORT_DIR}/2026-07-29-memory.md`),
      missing: [`${REPORT_DIR}/2026-07-29-memory.md`],
    },
  }
)
const spoofedReportCheckRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  { 'llm-report-check': { present: [], missing: ['/tmp/not-a-channel.md'] } }
)
const runnerFailureRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  { bumblebee: { ok: false, silent: false } }
)
const spoofedIdentityRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    bumblebee: { channel: 'symlink', report_path: '/tmp/spoofed.md', ok: true, silent: false },
    symlink: null,
  }
)
const forceRun = await runWorkflow({ date: '2026-07-29', weekday: 3, force_shell: true })
const evidenceValidFinalizer = {
  date: '2026-07-29',
  ok: true,
  report_path: '~/code/social-info/reports/local-analysis/2026-07-29-evidence-level.md',
  manifest_path: '~/code/social-info/reports/local-analysis/2026-07-29-evidence-level-manifest.json',
  eligible: 20,
  sample_count: 20,
  tp_style_violation_count: 19,
  audit_nonce: evidenceAuditNonce,
  reaudit_sample_count: 1,
  reaudit_nonce: evidenceReauditNonce,
  top_violations: [{ type: 'unsourced-number', count: 19 }],
  challenge: evidenceChallenge,
}
const evidenceAllFailFinalizer = {
  date: '2026-07-29',
  ok: true,
  report_path: '~/code/social-info/reports/local-analysis/2026-07-29-evidence-level.md',
  manifest_path: '~/code/social-info/reports/local-analysis/2026-07-29-evidence-level-manifest.json',
  eligible: 20,
  sample_count: 20,
  tp_style_violation_count: 20,
  audit_nonce: evidenceAuditNonce,
  reaudit_sample_count: 0,
  reaudit_nonce: null,
  top_violations: [{ type: 'unsourced-number', count: 20 }],
  challenge: evidenceChallenge,
}
const evidencePrimaryFailRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    ...batchOverridesFor(evidenceAllFailBatches),
    'evidence-level-finalizer': evidenceAllFailFinalizer,
  }
)
const evidenceNeverRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  { 'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null } }
)
const evidenceSevenDayRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  { 'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: '2026-07-22', days_since: 7 } }
)
const evidenceLegacyRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    'evidence-level-sampler': evidenceLegacySamplePacket,
  }
)
const evidenceFreshMissingBatchesRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    'evidence-level-sampler': evidenceFreshMissingBatchesPacket,
  }
)
const evidenceInvalidFinalizerRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    'evidence-level-finalizer': { ...evidenceValidFinalizer, ok: false },
  }
)
const evidenceForgedVerifyRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    'evidence-level-finalizer': { ...evidenceValidFinalizer, tp_style_violation_count: 0 },
  }
)
const evidenceWrongChallengeRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    'evidence-level-finalizer': { ...evidenceValidFinalizer, challenge: 'c'.repeat(64) },
  }
)
const evidenceTopViolations = [
  { type: 'doc-as-evidence', count: 1 },
  { type: 'unsourced-mechanism', count: 1 },
]
const evidenceTopTwoReaudit = {
  audit_nonce: evidenceReauditNonce,
  rows: evidenceSamples.map((sample, index) => ({
    sample_index: index + 1,
    result: index === 0 ? 'FAIL' : 'PASS',
    findings: index === 0
      ? [
        { type: 'doc-as-evidence', quote: '兩百字' },
        { type: 'unsourced-mechanism', quote: '超過' },
      ]
      : [],
  })),
}
const evidenceTopTwoFinalizer = {
  date: '2026-07-29',
  ok: true,
  report_path: '~/code/social-info/reports/local-analysis/2026-07-29-evidence-level.md',
  manifest_path: '~/code/social-info/reports/local-analysis/2026-07-29-evidence-level-manifest.json',
  eligible: 20,
  sample_count: 20,
  tp_style_violation_count: 1,
  audit_nonce: evidenceAuditNonce,
  reaudit_sample_count: 20,
  reaudit_nonce: evidenceReauditNonce,
  top_violations: evidenceTopViolations,
  challenge: evidenceChallenge,
}
const evidenceLegacyDigestRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    'evidence-level-sampler': evidenceLegacyDigestSamplePacket,
    ...Object.fromEntries(evidenceLegacyDigestBatchAudits.map((audit) => [`evidence-level-audit-batch-${audit.batch_index}`, audit])),
    'evidence-level-reaudit-preparer': evidenceLegacyDigestReauditPreparer('2026-07-29'),
    'evidence-level-finalizer': {
      ...evidenceValidFinalizer,
      samples_sha256: legacyDigest('1'),
      samples_file_sha256: legacyDigest('2'),
      reaudit_samples_file_sha256: legacyDigest('8'),
    },
  }
)
const evidenceTopTwoRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    ...batchOverridesFor(evidenceAllPassBatches),
    'evidence-level-reaudit-preparer': {
      date: '2026-07-29',
      reaudit_sample_count: 20,
      reaudit_nonce: evidenceReauditNonce,
    },
    'evidence-level-reaudit': evidenceTopTwoReaudit,
    'evidence-level-finalizer': evidenceTopTwoFinalizer,
  }
)
const evidenceEmptyTopRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    ...batchOverridesFor(evidenceAllFailBatches),
    'evidence-level-finalizer': { ...evidenceAllFailFinalizer, top_violations: [] },
  }
)
const evidenceThirdTypeTopRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    ...batchOverridesFor(evidenceAllFailBatches),
    'evidence-level-finalizer': { ...evidenceAllFailFinalizer, top_violations: [{ type: 'not-a-type', count: 1 }] },
  }
)
const evidenceImpossibleTopRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    'evidence-level-finalizer': { ...evidenceValidFinalizer, top_violations: [{ type: 'unsourced-number', count: 2 }] },
  }
)
const evidenceWrongViolationCountRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    'evidence-level-finalizer': { ...evidenceValidFinalizer, tp_style_violation_count: 18 },
  }
)
const evidenceSamplerErrorRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    'evidence-level-sampler': new Error('sampler failed'),
  }
)
const evidenceAuditErrorRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    'evidence-level-audit-batch-2': new Error('audit failed'),
  }
)
const evidenceFinalizerErrorRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  {
    'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null },
    'evidence-level-finalizer': new Error('finalizer failed'),
  }
)
const evidenceForgedDateRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  { 'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: '2026-07-28', days_since: 7 } }
)
const evidencePreflightErrorRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'evidence-level-due': new Error('preflight failed') }
)
const primaryNullRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'rba-verify-primary': null }
)
const primaryInvalidRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'rba-verify-primary': { eligible: 3, samples: [{ session: 'broken' }] } }
)
const primaryShortRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'rba-verify-primary': { eligible: 3, samples: [] } }
)
const primaryEmptyRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'rba-verify-primary': { eligible: 1, samples: [{ ...validPrimary.samples[0], path: '' }] } }
)
const verifierNullRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'rba-verify-verifier': null }
)
const verifierInvalidRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'rba-verify-verifier': { missed_claims: [], false_greens: [], overall_verdict: 'PASS' } }
)
const primaryWhitespaceRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'rba-verify-primary': { eligible: 1, samples: [{ ...validPrimary.samples[0], session: '   ' }] } }
)
const finalizerNullRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'rba-verify-finalizer': null }
)
const finalizerFalseRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'rba-verify-finalizer': { ...validFinalizer, ok: false } }
)
const finalizerWrongPathRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'rba-verify-finalizer': { ok: true, report_path: '/tmp/wrong.md' } }
)
const finalizerExtraFieldRun = await runWorkflow(
  { date: '2026-07-29', weekday: 2 },
  { 'rba-verify-finalizer': { ...validFinalizer, extra: true } }
)
const barrierRuntime = { deferBatchAudits: true, pendingBatchResolvers: [], resolvedBatchLabels: [] }
const barrierPromise = runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  { 'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null } },
  barrierRuntime
)
await new Promise((resolve) => setImmediate(resolve))
const barrierCallsBeforeRelease = [...barrierRuntime.calls]
const barrierPendingCount = barrierRuntime.pendingBatchResolvers.length
const barrierDownstreamBeforeRelease = barrierCallsBeforeRelease.some(({ options }) => options.label === 'evidence-level-reaudit-preparer' || options.label === 'evidence-level-reaudit' || options.label === 'evidence-level-finalizer')
const barrierReleases = [...barrierRuntime.pendingBatchResolvers]
const barrierPreDownstreamChecks = []
for (const [index, release] of barrierReleases.entries()) {
  release()
  await new Promise((resolve) => setImmediate(resolve))
  if (index < barrierReleases.length - 1) {
    barrierPreDownstreamChecks.push(!barrierRuntime.calls.some(({ options }) => options.label === 'evidence-level-reaudit-preparer' || options.label === 'evidence-level-reaudit' || options.label === 'evidence-level-finalizer'))
  }
}
const barrierRun = await barrierPromise
const scanBarrierRuntime = { deferRoutineScanLabel: 'memory', pendingRoutineResolvers: [], resolvedRoutineLabels: [] }
const scanBarrierPromise = runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  { 'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null } },
  scanBarrierRuntime
)
await new Promise((resolve) => setImmediate(resolve))
const scanBarrierBeforeRelease = !scanBarrierRuntime.phases.includes('EvidenceBatchAudit') && !scanBarrierRuntime.calls.some(({ options }) => options.label.startsWith('evidence-level-audit-batch-'))
const scanBarrierRelease = scanBarrierRuntime.pendingRoutineResolvers[0]
scanBarrierRelease?.()
const scanBarrierRun = await scanBarrierPromise
const scanBarrierBatchIndex = scanBarrierRun.calls.findIndex(({ options }) => options.label.startsWith('evidence-level-audit-batch-'))
const scanBarrierRoutineCalls = scanBarrierRun.calls
  .map((call, index) => call.options.phase === 'Scan' && !call.options.label.startsWith('evidence-level-') ? index : null)
  .filter((index) => index != null)
const scanBarrierSatisfied = scanBarrierBeforeRelease && scanBarrierRuntime.resolvedRoutineLabels.includes('memory') && scanBarrierBatchIndex >= 0 && scanBarrierRoutineCalls.every((index) => index < scanBarrierBatchIndex) && scanBarrierRun.phases.includes('EvidenceBatchAudit')
const barrierBatchPositions = barrierRun.calls
  .map((call, index) => call.options.label.startsWith('evidence-level-audit-batch-') ? index : null)
  .filter((index) => index != null)
const barrierDownstreamPositions = barrierRun.calls
  .map((call, index) => call.options.label === 'evidence-level-reaudit-preparer' || call.options.label === 'evidence-level-reaudit' || call.options.label === 'evidence-level-finalizer' ? index : null)
  .filter((index) => index != null)
const normalShellCall = silentRun.calls.find((call) => call.options.label === 'bumblebee')
const memoryRecoveryCalls = memoryRecoveryRun.calls.filter((call) => call.options.label === 'memory' || call.options.label === 'memory-recovery')
const memoryRecoveryChannel = memoryRecoveryRun.result.channels.find((channel) => channel.key === 'memory')
const forceShellCall = forceRun.calls.find((call) => call.options.label === 'bumblebee')
const beadsShellCall = stringArgsRun.calls.find((call) => call.options.label === 'beads-aging')
const ledgerLifecycleShellCall = stringArgsRun.calls.find((call) => call.options.label === 'ledger-lifecycle')
const skillEvaluatorShellCall = stringArgsRun.calls.find((call) => call.options.label === 'skillevaluator')
const skillEvaluatorChannel = stringArgsRun.result.channels.find((channel) => channel.key === 'skillevaluator')
const bumblebeeChannel = spoofedIdentityRun.result.channels.find((channel) => channel.key === 'bumblebee')
const beadsChannel = stringArgsRun.result.channels.find((channel) => channel.key === 'beads-aging')
const rbaCalls = stringArgsRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const rbaChannel = stringArgsRun.result.channels.find((channel) => channel.key === 'rba-verify')
const deferredEvidenceCalls = silentRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const primaryFailEvidenceCalls = evidencePrimaryFailRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const neverEvidenceCalls = evidenceNeverRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const sevenDayEvidenceCalls = evidenceSevenDayRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const sevenDayBatchCalls = sevenDayEvidenceCalls.filter((call) => call.options.label.startsWith('evidence-level-audit-batch-'))
const sevenDayReauditCall = sevenDayEvidenceCalls.find((call) => call.options.label === 'evidence-level-reaudit')
const invalidFinalizerEvidenceCalls = evidenceInvalidFinalizerRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const wrongChallengeEvidenceCalls = evidenceWrongChallengeRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const wrongViolationCountEvidenceCalls = evidenceWrongViolationCountRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const samplerErrorRbaCalls = evidenceSamplerErrorRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const auditErrorRbaCalls = evidenceAuditErrorRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const auditErrorEvidenceCalls = evidenceAuditErrorRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const finalizerErrorRbaCalls = evidenceFinalizerErrorRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const evidenceBatchPhaseAfterScan = (run) => {
  const firstBatchIndex = run.calls.findIndex((call) => call.options.label.startsWith('evidence-level-audit-batch-'))
  const nonEvidenceIndices = run.calls
    .map((call, index) => call.options.label.startsWith('evidence-level-') ? null : index)
    .filter((index) => index != null)
  return firstBatchIndex >= 0 && nonEvidenceIndices.every((index) => index < firstBatchIndex)
}
const barrierSatisfied = barrierPendingCount === 4 && !barrierDownstreamBeforeRelease && barrierPreDownstreamChecks.length === 3 && barrierPreDownstreamChecks.every(Boolean) && barrierRuntime.resolvedBatchLabels.length === 4 && barrierBatchPositions.length === 4 && barrierDownstreamPositions.length === 3 && Math.max(...barrierBatchPositions) < Math.min(...barrierDownstreamPositions) && barrierRun.result.ran.includes('evidence-level')
const forgedDateEvidenceCalls = evidenceForgedDateRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const preflightErrorRbaCalls = evidencePreflightErrorRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const legacyEvidenceCalls = evidenceLegacyRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const freshMissingBatchesEvidenceCalls = evidenceFreshMissingBatchesRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const evidenceChannel = evidenceSevenDayRun.result.channels.find((channel) => channel.key === 'evidence-level')
const evidenceTopTwoChannel = evidenceTopTwoRun.result.channels.find((channel) => channel.key === 'evidence-level')
const primaryNullRbaCalls = primaryNullRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const primaryInvalidRbaCalls = primaryInvalidRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const primaryShortRbaCalls = primaryShortRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const primaryEmptyRbaCalls = primaryEmptyRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const verifierNullRbaCalls = verifierNullRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const verifierInvalidRbaCalls = verifierInvalidRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const primaryWhitespaceRbaCalls = primaryWhitespaceRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const finalizerNullRbaCalls = finalizerNullRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const finalizerFalseRbaCalls = finalizerFalseRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const finalizerWrongPathRbaCalls = finalizerWrongPathRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))
const legacyDigestEvidenceCalls = evidenceLegacyDigestRun.calls.filter((call) => call.options.label.startsWith('evidence-level-'))
const finalizerExtraFieldRbaCalls = finalizerExtraFieldRun.calls.filter((call) => call.options.label.startsWith('rba-verify-'))

const checks = [
  ['workflow script 語法有效', syntaxValid],
  ['字串 args 正確解析 32 個 calendar channel 並 defer 未到期 interval channel', sameMembers(stringArgsRun.result.attempted, [...DAILY_CHANNELS, ...WEEKLY_CHANNELS]) && sameMembers(stringArgsRun.result.skipped, [INTERVAL_CHANNEL]) && sameMembers(stringArgsRun.result.deferred, [INTERVAL_CHANNEL])],
  ['字串 weekday 正規化為數字', stringWeekdayRun.result.attempted.includes('codemap')],
  ['非週二只跑 daily 並跳過 weekly 與未到期 interval channel', sameMembers(silentRun.result.attempted, DAILY_CHANNELS) && sameMembers(silentRun.result.skipped, [...WEEKLY_CHANNELS, INTERVAL_CHANNEL])],
  ['非法 JSON args fail-fast', malformedArgsRejected],
  ['silent shell channel 不進 reported channels', silentRun.result.ran.includes('bumblebee') && silentRun.result.silent.includes('bumblebee') && !silentRun.result.channels.some((channel) => channel.key === 'bumblebee')],
  ['失敗 channel 不冒充 ran', failureRun.result.failed.includes('bumblebee') && !failureRun.result.ran.includes('bumblebee')],
  ['memory primary 無回傳時由 fresh finalizer 恢復', JSON.stringify(memoryRecoveryCalls.map((call) => call.options.label)) === JSON.stringify(['memory', 'memory-recovery']) && memoryRecoveryRun.result.ran.includes('memory') && !memoryRecoveryRun.result.failed.includes('memory') && memoryRecoveryChannel?.summary === 'recovered memory summary'],
  ['memory primary prompt 禁止報告寫入後重讀', memoryRecoveryCalls[0]?.prompt.includes('寫入後不要再 Read')],
  ['memory recovery 只讀固定報告並驗證必要結構', memoryRecoveryCalls[1]?.options.model === 'sonnet' && JSON.stringify(memoryRecoveryCalls[1]?.options.schema?.required) === JSON.stringify(['ok', 'summary']) && memoryRecoveryCalls[1]?.prompt.includes('/2026-07-29-memory.md') && memoryRecoveryCalls[1]?.prompt.includes('# Memory Audit') && memoryRecoveryCalls[1]?.prompt.includes('## Summary')],
  ['runner 回報失敗不進 ran', runnerFailureRun.result.failed.includes('bumblebee') && !runnerFailureRun.result.ran.includes('bumblebee')],
  ['channel 身分綁定 workflow 設定', spoofedIdentityRun.result.ran.includes('bumblebee') && spoofedIdentityRun.result.failed.includes('symlink') && !spoofedIdentityRun.result.ran.includes('symlink')],
  ['report path 綁定 workflow 設定', bumblebeeChannel.report_path === '~/code/social-info/reports/local-analysis/2026-07-29-bumblebee.md'],
  ['shell channel 標記 needs_read', bumblebeeChannel.needs_read === true],
  ['一般 shell 走完整性 runner', normalShellCall.prompt.includes('run-shell-channel.sh') && normalShellCall.prompt.includes('2026-07-29 false')],
  ['shell channel 走 haiku、未指定 model 的 llm channel 維持 sonnet high', silentRun.calls.filter((call) => call.options.schema?.properties?.silent).length > 0 && silentRun.calls.filter((call) => call.options.schema?.properties?.silent).every((call) => call.options.model === 'haiku' && call.options.effort === 'medium') && silentRun.calls.find((call) => call.options.label === 'wiki-lint')?.options.model === 'sonnet' && silentRun.calls.find((call) => call.options.label === 'wiki-lint')?.options.effort === 'high'],
  ['force_shell 傳入 runner',forceShellCall.prompt.includes('run-shell-channel.sh') && forceShellCall.prompt.includes('2026-07-29 true')],
  ['beads shell 指向正確 wrapper 與報告', beadsShellCall.prompt.includes('bash ~/code/social-info/scripts/local-analysis/run-shell-channel.sh ~/code/social-info/scripts/local-analysis/beads-aging-weekly.sh ~/code/social-info/reports/local-analysis/2026-07-29-beads-aging.md 2026-07-29 true') && beadsChannel.report_path === '~/code/social-info/reports/local-analysis/2026-07-29-beads-aging.md'],
  ['beads 同日重跑強制刷新', beadsShellCall.prompt.includes('2026-07-29 true')],
  ['ledger-lifecycle daily shell 指向 ticket03 腳本與報告', ledgerLifecycleShellCall?.prompt?.includes('bash ~/code/social-info/scripts/local-analysis/run-shell-channel.sh ~/code/social-info/scripts/local-analysis/ledger-lifecycle-daily.sh ~/code/social-info/reports/local-analysis/2026-07-29-ledger-lifecycle.md 2026-07-29 false') === true && stringArgsRun.result.ran.includes('ledger-lifecycle')],
  ['skill-changes daily shell 指向 wrapper 與 canonical report', stringArgsRun.calls.find((call) => call.options.label === 'skill-changes')?.prompt?.includes('bash ~/code/social-info/scripts/local-analysis/run-shell-channel.sh ~/.claude/workflows/skill-changes-daily.sh ~/code/social-info/reports/local-analysis/2026-07-29-skill-changes.md 2026-07-29 false') === true && stringArgsRun.result.ran.includes('skill-changes') && silentRun.result.attempted.includes('skill-changes') && stringArgsRun.result.channels.find((channel) => channel.key === 'skill-changes')?.needs_read === true],
  ['skillevaluator weekly shell 指向 trial wrapper 與 canonical report', skillEvaluatorShellCall?.prompt?.includes('bash ~/code/social-info/scripts/local-analysis/run-shell-channel.sh ~/.claude/workflows/skillevaluator-weekly.sh ~/code/social-info/reports/local-analysis/2026-07-29-skillevaluator.md 2026-07-29 false') === true && stringArgsRun.result.ran.includes('skillevaluator') && skillEvaluatorChannel?.report_path === '~/code/social-info/reports/local-analysis/2026-07-29-skillevaluator.md' && skillEvaluatorChannel?.needs_read === true],
  ['evidence-level 未到期只跑 Sonnet due preflight', JSON.stringify(deferredEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due']) && deferredEvidenceCalls[0]?.options.model === 'sonnet'],
  ['evidence-level 未到期算 deferred 與 skipped', silentRun.result.deferred.includes('evidence-level') && silentRun.result.skipped.includes('evidence-level')],
  ['evidence-level 未到期不算 failed、ran 或 reported', !silentRun.result.failed.includes('evidence-level') && !silentRun.result.ran.includes('evidence-level') && !silentRun.result.channels.some((channel) => channel.key === 'evidence-level')],
  ['evidence-level 第一輪四批全 FAIL 不派 preparer 或第二支 auditor', JSON.stringify(primaryFailEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler', 'evidence-level-audit-batch-1', 'evidence-level-audit-batch-2', 'evidence-level-audit-batch-3', 'evidence-level-audit-batch-4', 'evidence-level-finalizer']) && evidenceBatchPhaseAfterScan(evidencePrimaryFailRun) && evidencePrimaryFailRun.result.ran.includes('evidence-level')],
  ['evidence-level 從未成功時四批到期且驗收後才算 ran', JSON.stringify(neverEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler', 'evidence-level-audit-batch-1', 'evidence-level-audit-batch-2', 'evidence-level-audit-batch-3', 'evidence-level-audit-batch-4', 'evidence-level-reaudit-preparer', 'evidence-level-reaudit', 'evidence-level-finalizer']) && evidenceNeverRun.result.ran.includes('evidence-level')],
  ['evidence-level 剛好 7 日到期四批且驗收後才算 ran', JSON.stringify(sevenDayEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler', 'evidence-level-audit-batch-1', 'evidence-level-audit-batch-2', 'evidence-level-audit-batch-3', 'evidence-level-audit-batch-4', 'evidence-level-reaudit-preparer', 'evidence-level-reaudit', 'evidence-level-finalizer']) && evidenceSevenDayRun.result.ran.includes('evidence-level')],
  ['evidence-level packet 缺兩個 discriminator fail closed', JSON.stringify(legacyEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler']) && evidenceLegacyRun.result.failed.includes('evidence-level') && !evidenceLegacyRun.result.ran.includes('evidence-level')],
  ['evidence-level fresh packet 缺 batches fail closed', JSON.stringify(freshMissingBatchesEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler']) && evidenceFreshMissingBatchesRun.result.failed.includes('evidence-level') && !evidenceFreshMissingBatchesRun.result.ran.includes('evidence-level')],
  ['routine Scan 未完成前不進 EvidenceBatchAudit', scanBarrierSatisfied],
  ['evidence-level batch barrier 等四批完成後才啟動下游', barrierSatisfied],
  ['evidence-level audit ok 但驗收 packet 不合格仍 fail', invalidFinalizerEvidenceCalls.length === 9 && evidenceInvalidFinalizerRun.result.failed.includes('evidence-level') && !evidenceInvalidFinalizerRun.result.ran.includes('evidence-level') && !evidenceInvalidFinalizerRun.result.channels.some((channel) => channel.key === 'evidence-level')],
  ['evidence-level 不信 finalizer 的 ok=true 偽造數量', evidenceForgedVerifyRun.result.failed.includes('evidence-level') && !evidenceForgedVerifyRun.result.ran.includes('evidence-level')],
  ['evidence-level 拒絕結構正確但 challenge 錯誤的偽造 packet', wrongChallengeEvidenceCalls.length === 9 && evidenceWrongChallengeRun.result.failed.includes('evidence-level') && !evidenceWrongChallengeRun.result.ran.includes('evidence-level')],
  ['evidence-level 拒絕 challenge 正確但命中數被改寫的 packet', wrongViolationCountEvidenceCalls.length === 9 && evidenceWrongViolationCountRun.result.failed.includes('evidence-level') && !evidenceWrongViolationCountRun.result.ran.includes('evidence-level')],
  ['evidence-level 拒絕錯誤、空白或第三類 top_violations', evidenceImpossibleTopRun.result.failed.includes('evidence-level') && evidenceEmptyTopRun.result.failed.includes('evidence-level') && evidenceThirdTypeTopRun.result.failed.includes('evidence-level') && !evidenceImpossibleTopRun.result.ran.includes('evidence-level') && !evidenceEmptyTopRun.result.ran.includes('evidence-level') && !evidenceThirdTypeTopRun.result.ran.includes('evidence-level')],
  ['evidence-level 拒絕與日期不一致的 due packet', forgedDateEvidenceCalls.length === 1 && evidenceForgedDateRun.result.failed.includes('evidence-level') && !evidenceForgedDateRun.result.ran.includes('evidence-level')],
  ['evidence-level preflight 失敗不阻斷既有 RBA', evidencePreflightErrorRun.result.failed.includes('evidence-level') && preflightErrorRbaCalls.length === 3 && evidencePreflightErrorRun.result.ran.includes('rba-verify')],
  ['evidence-level preflight 錯誤保留於 log 與結構化狀態', evidencePreflightErrorRun.logs.some((entry) => entry.includes('preflight failed')) && JSON.stringify(evidencePreflightErrorRun.result.preflight_errors) === JSON.stringify([{ channel: 'evidence-level', message: 'preflight failed' }])],
  ['evidence-level sampler 例外只讓自身 channel 失敗', evidenceSamplerErrorRun.result.failed.includes('evidence-level') && evidenceSamplerErrorRun.result.ran.includes('rba-verify') && samplerErrorRbaCalls.length === 3 && evidenceSamplerErrorRun.logs.some((entry) => entry.includes('sampler failed'))],
  ['evidence-level 任一 batch error 不進 re-audit 或 finalizer', JSON.stringify(auditErrorEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler', 'evidence-level-audit-batch-1', 'evidence-level-audit-batch-2', 'evidence-level-audit-batch-3', 'evidence-level-audit-batch-4']) && evidenceAuditErrorRun.result.failed.includes('evidence-level') && evidenceAuditErrorRun.result.ran.includes('rba-verify') && auditErrorRbaCalls.length === 3 && evidenceAuditErrorRun.logs.some((entry) => entry.includes('audit failed'))],
  ['evidence-level finalizer 例外只讓自身 channel 失敗', evidenceFinalizerErrorRun.result.failed.includes('evidence-level') && evidenceFinalizerErrorRun.result.ran.includes('rba-verify') && finalizerErrorRbaCalls.length === 3 && evidenceFinalizerErrorRun.logs.some((entry) => entry.includes('finalizer failed'))],
  ['evidence-level sampler 只執行固定指令並回 opaque packet', sevenDayEvidenceCalls[1]?.options.model === 'sonnet' && sevenDayEvidenceCalls[1]?.prompt.includes('--mode sample') && !sevenDayEvidenceCalls[1]?.prompt.includes(evidenceSamples[0].answer)],
  ['evidence-level sampler schema requires fresh attempt and four batches', sevenDayEvidenceCalls[1]?.options.schema?.required?.includes('attempt_nonce') && sevenDayEvidenceCalls[1]?.options.schema?.required?.includes('batches')],
  ['evidence-level 四批 auditor 都收到自己的檔案、attempt nonce、schema 與 read-only 契約', sevenDayBatchCalls.length === 4 && sevenDayBatchCalls.every((call, index) => call.options.agentType === 'evidence-level-auditor' && !Object.hasOwn(call.options, 'model') && !Object.hasOwn(call.options, 'effort') && call.options.phase === 'EvidenceBatchAudit' && call.prompt.includes(`-evidence-level-samples-batch-${index + 1}.txt`) && call.prompt.includes(`attempt_nonce 必須逐字回傳為 ${evidenceAttemptNonce}`) && call.prompt.includes(`[${evidenceChallenge.slice(0, 16)}]`) && !call.prompt.includes(evidenceSamples[0].answer) && !call.prompt.includes(evidenceChallenge) && !call.prompt.includes('evidence-level-manifest.json') && JSON.stringify([...call.options.schema.required].sort()) === JSON.stringify(['attempt_nonce', 'audit_nonce', 'batch_index', 'range', 'rows'].sort()))],
  ['evidence-level observability 區分 Sonnet helper 與 Opus medium auditor', source.includes('"phase": "EvidenceBatchAudit", "model": "sonnet"') && source.includes('"phase": "EvidenceBatchAudit", "model": "opus", "effort": "medium", "agentType": "evidence-level-auditor"') && source.includes('"phase": "Scan", "minimum": 0, "maximum": 29, "formula": "due channels excluding evidence-level"')],
  ['evidence-level auditor 契約要求逐一主張、相鄰相關證據、禁止來源外溢、純討論豁免與全數處理才 PASS', sevenDayBatchCalls.every((call) => ['逐一盤點', '每個獨立主張', '內容相關', '相鄰證據', '跨系統', '本機設定', '外溢', '待查', '我猜', '純討論', '全部處理完', 'PASS'].every((text) => call.prompt.includes(text)))],
  ['evidence-level runtime phase 與 agent options 對齊 EvidenceBatchAudit', JSON.stringify(evidenceSevenDayRun.phases) === JSON.stringify(['Scan', 'EvidenceBatchAudit']) && sevenDayEvidenceCalls.filter((call) => call.options.label !== 'evidence-level-due').every((call) => call.options.phase === 'EvidenceBatchAudit')],
  ['evidence-level finalizer 從固定 transcript root 取得雙 audit、attempt nonce 與 current re-audit path', sevenDayEvidenceCalls[8]?.options.model === 'sonnet' && sevenDayEvidenceCalls[8]?.prompt.includes('--mode finalize') && sevenDayEvidenceCalls[8]?.prompt.includes("--audit-from-transcripts '~/.claude/projects/-Users-you-code-social-info'") && sevenDayEvidenceCalls[8]?.prompt.includes(`--attempt-nonce '${evidenceAttemptNonce}'`) && sevenDayEvidenceCalls[8]?.prompt.includes(`--reaudit-nonce '${evidenceReauditNonce}'`) && sevenDayReauditCall?.prompt.includes(evidenceReauditPath) && sevenDayEvidenceCalls.slice(6).every((call) => !call.prompt.includes('--reaudit-samples-path')) && !sevenDayEvidenceCalls[8]?.prompt.includes('ls -td') && !sevenDayEvidenceCalls[8]?.prompt.includes('--audit-b64') && !sevenDayEvidenceCalls[8]?.prompt.includes(evidenceChallenge) && !sevenDayEvidenceCalls[8]?.prompt.includes('draft')],
  ['evidence-level 合併後 canonical Top 2 並只傳 finalizer 值且 needs_read=false', evidenceTopTwoChannel?.summary.includes('doc-as-evidence：1、unsourced-mechanism：1') && !evidenceTopTwoChannel?.summary.includes('unsourced-number') && evidenceTopTwoChannel?.needs_read === false],
  ['evidence-level report path 與 needs_read 正確', evidenceChannel?.report_path === '~/code/social-info/reports/local-analysis/2026-07-29-evidence-level.md' && evidenceChannel?.needs_read === false],
  ['evidence-level 到期後 reported channel count 正確', evidenceSevenDayRun.result.channels.length === DAILY_CHANNELS.length + 1],
  ['evidence-level sampler 的 batch 描述欄位固定為 index／range／path／audit_nonce', JSON.stringify(Object.keys(sevenDayEvidenceCalls[1]?.options.schema?.properties?.batches?.items?.properties ?? {})) === JSON.stringify(['index', 'range', 'path', 'audit_nonce'])],
  ['evidence-level 不帶 digest 欄的 packet 走完整流程並算 ran', evidenceSevenDayRun.result.ran.includes('evidence-level') && !evidenceSevenDayRun.result.failed.includes('evidence-level')],
  ['evidence-level 舊 packet 帶互相矛盾的 digest 欄仍被讀取、欄位被忽略而不崩（F2）', legacyDigestEvidenceCalls.length === 9 && evidenceLegacyDigestRun.result.ran.includes('evidence-level') && !evidenceLegacyDigestRun.result.failed.includes('evidence-level')],
  ['shell channel 說明不再提 SHA-256 完成標記', !normalShellCall.prompt.includes('SHA-256') && normalShellCall.prompt.includes('完成標記')],
  ['RBA 依序呼叫 primary、verifier、finalizer', JSON.stringify(rbaCalls.map((call) => call.options.label)) === JSON.stringify(['rba-verify-primary', 'rba-verify-verifier', 'rba-verify-finalizer'])],
  ['RBA primary 保持 opus medium', rbaCalls[0]?.options.model === 'opus' && rbaCalls[0]?.options.effort === 'medium'],
  ['RBA verifier 使用 fresh opus high', rbaCalls[1]?.options.model === 'opus' && rbaCalls[1]?.options.effort === 'high'],
  ['RBA finalizer prompt 只執行固定 Python 指令', rbaCalls[2]?.prompt.includes('python3 ~/code/social-info/scripts/local-analysis/rba-verify-finalize.py --date 2026-07-29') && rbaCalls[2]?.prompt.includes('不得自行計數或改寫 Markdown')],
  ['RBA finalizer 使用 raw JSON pair、不重跑 sampler', rbaCalls[2]?.prompt.includes('--primary-json') && rbaCalls[2]?.prompt.includes('--verifier-json') && !rbaCalls[2]?.prompt.includes('--primary-b64') && !rbaCalls[2]?.prompt.includes('--verifier-b64') && !rbaCalls[2]?.prompt.includes('--packets-from-transcripts') && !rbaCalls[2]?.prompt.includes('--sampler') && !rbaCalls[2]?.prompt.includes('WF_DIR') && !rbaCalls[2]?.prompt.includes('snapshot')],
  ['RBA 成功後仍標記 needs_read', rbaChannel?.needs_read === true && rbaChannel.report_path.endsWith('/2026-07-29-rba-verify.md')],
  ['RBA primary null fail closed', primaryNullRun.result.failed.includes('rba-verify') && primaryNullRbaCalls.length === 1],
  ['RBA primary schema 不合格 fail closed', primaryInvalidRun.result.failed.includes('rba-verify') && primaryInvalidRbaCalls.length === 1],
  ['RBA primary 不得漏回應抽樣筆數', primaryShortRun.result.failed.includes('rba-verify') && primaryShortRbaCalls.length === 1],
  ['RBA primary 身分與證據欄位不可為空', primaryEmptyRun.result.failed.includes('rba-verify') && primaryEmptyRbaCalls.length === 1],
  ['RBA verifier null fail closed', verifierNullRun.result.failed.includes('rba-verify') && verifierNullRbaCalls.length === 2],
  ['RBA verifier schema 不合格 fail closed', verifierInvalidRun.result.failed.includes('rba-verify') && verifierInvalidRbaCalls.length === 2],
  ['RBA 空白身分欄位 fail closed', primaryWhitespaceRun.result.failed.includes('rba-verify') && primaryWhitespaceRbaCalls.length === 1],
  ['RBA finalizer null fail closed', finalizerNullRun.result.failed.includes('rba-verify') && finalizerNullRbaCalls.length === 3],
  ['RBA finalizer ok=false fail closed', finalizerFalseRun.result.failed.includes('rba-verify') && finalizerFalseRbaCalls.length === 3],
  ['RBA finalizer report path 不符 fail closed', finalizerWrongPathRun.result.failed.includes('rba-verify') && finalizerWrongPathRbaCalls.length === 3],
  ['RBA finalizer 額外欄位 fail closed', finalizerExtraFieldRun.result.failed.includes('rba-verify') && finalizerExtraFieldRbaCalls.length === 3],
  ['LLM report 存在性由固定指令驗證、涵蓋全部 llm channel', llmCheckCall != null && llmCheckCall.options.model === 'sonnet' && llmCheckCall.prompt.includes('[ -s "$f" ]') && llmCheckedPaths.includes(`${REPORT_DIR}/2026-07-29-memory.md`) && llmCheckedPaths.includes(`${REPORT_DIR}/2026-07-29-wiki-lint.md`) && llmCheckedPaths.length === silentRun.result.channels.filter((channel) => channel.kind === 'llm').length],
  ['LLM channel 自述已寫但報告缺檔 → failed、不冒充 ran', missingReportRun.result.failed.includes('memory') && !missingReportRun.result.ran.includes('memory') && !missingReportRun.result.channels.some((channel) => channel.key === 'memory') && missingReportRun.result.ran.includes('wiki-lint')],
  ['report check 回傳非預期路徑 → 略過驗證、channel 維持自述', !spoofedReportCheckRun.result.failed.includes('memory') && spoofedReportCheckRun.result.ran.includes('memory') && spoofedReportCheckRun.logs.some((line) => line.includes('llm-report-check 回傳無效'))],
  ['回傳 reconcile 指令', stringArgsRun.result.reconcile_cmd.includes('ledger-reconcile.py')],
  ['workflow 明示不產 digest', stringArgsRun.result.next_action.includes('只做偵測、不產 digest')],
]

let failed = 0
for (const [name, passed] of checks) {
  if (!passed) failed++
  console.log(`${passed ? '✅' : '❌'} ${name}`)
}

console.log(`\n${checks.length - failed}/${checks.length} passed`)
process.exit(failed === 0 ? 0 : 1)
