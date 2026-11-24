import fs from 'node:fs'

const source = fs.readFileSync(new URL('../local-analysis.js', import.meta.url), 'utf8')
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const compile = () => new AsyncFunction(
  'args',
  'phase',
  'log',
  'parallel',
  'agent',
  'Buffer',
  'workflow',
  source.replace('export const meta =', 'const meta =')
)

const DAILY_CHANNELS = [
  'memory',
  'memory-conflict',
  'wiki-candidates',
  'wiki-cross-link',
  'wiki-graduation',
  'wiki-lint',
  'wiki-stale',
  'skill-desc-quality',
  'recap',
  'bumblebee',
  'path-rot',
  'tool-updates',
  'skill-collision',
  'agnix',
  'ledger-lifecycle',
  'memory-origin',
  'skill-changes',
  'failure-mode',
  'hash-reflow',
]
const INTERVAL_CHANNEL = 'evidence-level'
const WEEKLY_SAT_CHANNELS = ['session-audit-consume']
const WEEKLY_CHANNELS = [
  'distill',
  'habits',
  'recurring-errors',
  'rba-verify',
  'skill-upstream',
  'skill-doctor',
  'tool-reliability',
  'tool-latency',
  'skill-evidence',
  'rules-size',
  'session-telemetry',
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
const evidenceBatchDescriptors = Array.from({ length: 10 }, (_, batchIndex) => {
  const index = batchIndex + 1
  const members = evidenceSamples.slice(batchIndex * 2, index * 2).map(({ timestamp, session, path, row_index }) => ({ timestamp, session, path, row_index }))
  return {
    index,
    range: { start: batchIndex * 2 + 1, end: index * 2 },
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

const HABITS_DIR = '~/code/social-info/reports/local-analysis/habits'
const habitsPacketFor = (date) => {
  const end = new Date(`${date}T00:00:00.000Z`)
  const day = (offset) => new Date(end.getTime() + offset * 86400000).toISOString().slice(0, 10)
  const slices = [0, 1, 2].map((i) => ({
    index: i + 1,
    start: day(-20 + i * 7),
    end: day(-14 + i * 7),
    path: `${HABITS_DIR}/${date}-habits-slice-${i + 1}.txt`,
    total_messages: 100 + i,
    body_messages: 70 + i,
    sessions: 10 + i,
  }))
  return { date, since: slices[0].start, slices }
}
const habitsHeaderFor = (slice) => `# 第 ${slice.index} 段：${slice.start} ~ ${slice.end}，共 ${slice.total_messages} 則使用者訊息、${slice.sessions} 個 session，其中 >6 字的 ${slice.body_messages} 則收在正文`
const habitsMinerFor = (date, index, habits) => {
  const slice = habitsPacketFor(date).slices[index - 1]
  return {
    segment: index,
    header: habitsHeaderFor(slice),
    habits: habits ?? [{
      category: '回覆偏好',
      habit: '要求先結論再細節',
      count: 4,
      evidence: [{ ts: '2026-07-10T01:00', quote: '先講結論' }, { ts: '2026-07-11T02:00', quote: '結論先說' }],
    }],
  }
}
const habitsPartHeaderFor = (slice, part, totalParts) =>
  `# 第 ${slice.index} 段第 ${part.part}/${totalParts} 批：${slice.start} ~ ${slice.end}，本批 ${part.body_messages} 則正文訊息（全段共 ${slice.total_messages} 則使用者訊息、${slice.sessions} 個 session）`
const habitsSplitPacketFor = (date) => {
  const pkt = habitsPacketFor(date)
  pkt.slices[0].parts = [
    { part: 1, path: `${HABITS_DIR}/${date}-habits-slice-1-part-1.txt`, body_messages: 35 },
    { part: 2, path: `${HABITS_DIR}/${date}-habits-slice-1-part-2.txt`, body_messages: 35 },
  ]
  return pkt
}
const habitsPartMinerFor = (date, sliceIndex, partNo, habits) => {
  const pkt = habitsSplitPacketFor(date)
  const slice = pkt.slices[sliceIndex - 1]
  const part = slice.parts[partNo - 1]
  return {
    segment: sliceIndex,
    part: partNo,
    header: habitsPartHeaderFor(slice, part, slice.parts.length),
    habits: habits ?? [{
      category: '回覆偏好',
      habit: '子批內要求先結論',
      count: 2,
      evidence: [{ ts: '2026-07-10T01:00', quote: '先講結論' }, { ts: '2026-07-10T02:00', quote: '結論先說' }],
    }],
  }
}
const habitsRunArgs = { date: '2026-07-29', weekday: 2 }

// 舊 receipt／packet 可能仍帶 digest 欄（含彼此矛盾的值）；decoder 要忽略、不驗，而不是崩潰或拒收（F2）。
const legacyDigest = (char) => char.repeat(64)
const evidenceLegacyDigestSamplePacket = {
  ...evidenceSamplePacket,
  samples_sha256: legacyDigest('1'),
  samples_file_sha256: legacyDigest('2'),
  manifest_hash: legacyDigest('3'),
  batches: evidenceSamplePacket.batches.map((batch, index) => ({
    ...batch,
    batch_sha256: legacyDigest(String((index % 9) + 1)),
    samples_sha256: index === 0 ? legacyDigest('5') : legacyDigest('6'),
  })),
}
const evidenceLegacyDigestBatchAudits = evidenceBatchAudits.map((audit, index) => ({
  ...audit,
  batch_sha256: legacyDigest('7'),
  samples_sha256: legacyDigest(String(index % 10)),
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
      const batchIndex = Number(options.label.split('-').at(-1))
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
    if (options.label === 'habits-extract') return habitsPacketFor(inputDate)
    if (/^habits-miner-[123](-retry)?$/.test(options.label)) return habitsMinerFor(inputDate, Number(options.label.split('-')[2]))
    const partMatch = options.label.match(/^habits-miner-([123])-p(\d+)(-retry)?$/)
    if (partMatch) return habitsPartMinerFor(inputDate, Number(partMatch[1]), Number(partMatch[2]))
    if (options.schema?.required?.includes('silent')) {
      return { ok: true, silent: false }
    }
    if (options.schema?.required?.includes('report_markdown')) {
      return {
        summary: `${options.label} summary`,
        report_markdown: `# ${options.label}\n\n## Summary\n`,
        deferred_writeback: '',
      }
    }
    return { summary: `${options.label} summary` }
  }
  const parallel = (thunks) => Promise.all(thunks.map((thunk) => thunk()))
  const workflowCalls = []
  const workflow = async (name, childArgs) => {
    workflowCalls.push({ name, args: childArgs })
    const key = `workflow:${name}`
    if (Object.prototype.hasOwnProperty.call(resultOverrides, key)) {
      const override = resultOverrides[key]
      if (override instanceof Error) throw override
      return override
    }
    return { ok: true, silent: false, summary: `${name} summary`, report_markdown: `# ${name}\n`, deferred_writeback: '' }
  }
  const result = await compile()(inputArgs, (title) => phases.push(title), (message) => logs.push(message), parallel, agent, undefined, workflow)
  return { result, calls, logs, phases, workflowCalls }
}

let syntaxValid = true
try {
  compile()
} catch {
  syntaxValid = false
}

const stringArgsRun = await runWorkflow('{"date":"2026-07-29","weekday":2}')
const stringWeekdayRun = await runWorkflow({ date: '2026-07-29', weekday: '2' })
const saturdayRun = await runWorkflow({ date: '2026-07-29', weekday: 6 })
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
const memoryFailureRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    memory: null,
  }
)
const memoryInvalidSchemaRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    memory: { summary: 'only summary' },
  }
)
const runnerFailureRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  { bumblebee: { ok: false, silent: false } }
)
const spoofedIdentityRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3 },
  {
    bumblebee: { channel: 'path-rot', report_path: '/tmp/spoofed.md', ok: true, silent: false },
    'path-rot': null,
  }
)
const forceRun = await runWorkflow({ date: '2026-07-29', weekday: 3, force_shell: true })
const memoryConflictFailureRun = await runWorkflow({ date: '2026-07-29', weekday: 3 }, { 'workflow:memory-conflict-check': { ok: false, reason: 'prepare-failed' } })
const memoryConflictThrowRun = await runWorkflow({ date: '2026-07-29', weekday: 3 }, { 'workflow:memory-conflict-check': new Error('child boom') })
const habitsDate = habitsRunArgs.date
const habitsBadPathPacket = habitsPacketFor(habitsDate)
habitsBadPathPacket.slices[1].path = '/tmp/evil.txt'
const habitsBadHeaderMiner = { ...habitsMinerFor(habitsDate, 3), header: '# 第 3 段：偽造的標頭' }
const habitsLowCountMiner = habitsMinerFor(habitsDate, 1, [{ category: '回覆偏好', habit: '只出現兩次', count: 2, evidence: [{ ts: 't1', quote: 'q1' }, { ts: 't2', quote: 'q2' }] }])
const habitsLongQuote = '長'.repeat(60)
const habitsLongQuoteMiner = habitsMinerFor(habitsDate, 1, [{ category: '驗證姿態', habit: '要求附驗證輸出', count: 5, evidence: [{ ts: 't1', quote: habitsLongQuote }, { ts: 't2', quote: '附輸出' }] }])
const habitsExtractNullRun = await runWorkflow(habitsRunArgs, { 'habits-extract': null })
const habitsExtractThrowRun = await runWorkflow(habitsRunArgs, { 'habits-extract': new Error('extract boom') })
const habitsExtractBadPathRun = await runWorkflow(habitsRunArgs, { 'habits-extract': habitsBadPathPacket })
const habitsMinerRetryRun = await runWorkflow(habitsRunArgs, { 'habits-miner-2': null })
const habitsMinerNullTwiceRun = await runWorkflow(habitsRunArgs, { 'habits-miner-2': null, 'habits-miner-2-retry': null })
const habitsMinerThrowTwiceRun = await runWorkflow(habitsRunArgs, { 'habits-miner-1': new Error('miner boom'), 'habits-miner-1-retry': new Error('miner boom') })
const habitsMinerBadHeaderRun = await runWorkflow(habitsRunArgs, { 'habits-miner-3': habitsBadHeaderMiner, 'habits-miner-3-retry': habitsBadHeaderMiner })
const habitsMinerLowCountRun = await runWorkflow(habitsRunArgs, { 'habits-miner-1': habitsLowCountMiner, 'habits-miner-1-retry': habitsLowCountMiner })
const habitsAllEmptyRun = await runWorkflow(habitsRunArgs, Object.fromEntries([1, 2, 3].map((i) => [`habits-miner-${i}`, habitsMinerFor(habitsDate, i, [])])))
const habitsLongQuoteRun = await runWorkflow(habitsRunArgs, { 'habits-miner-1': habitsLongQuoteMiner })
const habitsMergeNullRun = await runWorkflow(habitsRunArgs, { 'habits-merge': null, 'habits-merge-retry': null })
const habitsMergeWritebackRun = await runWorkflow(habitsRunArgs, {
  'habits-merge': { summary: 's', report_markdown: '# r', deferred_writeback: 'rm -rf /' },
  'habits-merge-retry': { summary: 's', report_markdown: '# r', deferred_writeback: 'rm -rf /' },
})
const habitsMergeEmptyReportRun = await runWorkflow(habitsRunArgs, {
  'habits-merge': { summary: 's', report_markdown: '  ', deferred_writeback: '' },
  'habits-merge-retry': { summary: 's', report_markdown: '  ', deferred_writeback: '' },
})
const habitsMergeRetrySuccessRun = await runWorkflow(habitsRunArgs, { 'habits-merge': new Error('32768 output limit') })
const habitsSplitSuccessRun = await runWorkflow(habitsRunArgs, { 'habits-extract': habitsSplitPacketFor(habitsDate) })
const habitsSplitRetryRun = await runWorkflow(habitsRunArgs, { 'habits-extract': habitsSplitPacketFor(habitsDate), 'habits-miner-1-p2': new Error('empty reply') })
const habitsSplitFailRun = await runWorkflow(habitsRunArgs, {
  'habits-extract': habitsSplitPacketFor(habitsDate),
  'habits-miner-1-p2': null,
  'habits-miner-1-p2-retry': null,
})
const habitsLabels = (run) => run.calls.map((c) => c.options.label).filter((l) => l.startsWith('habits-'))
const habitsFailedCleanly = (run) => run.result.failed.includes('habits') && !run.result.pending_reports.some((r) => r.key === 'habits') && !run.result.ran.includes('habits')
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
const evidenceTopTwoReauditBatches = Object.fromEntries(Array.from({ length: 10 }, (_, batchIdx) => {
  const index = batchIdx + 1
  const start = batchIdx * 2 + 1
  const end = index * 2
  return [`evidence-level-reaudit-batch-${index}`, {
    audit_nonce: evidenceReauditNonce,
    attempt_nonce: evidenceAttemptNonce,
    batch_index: index,
    range: { start, end },
    rows: evidenceTopTwoReaudit.rows.slice(start - 1, end),
  }]
}))
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
    ...evidenceTopTwoReauditBatches,
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
    'evidence-level-audit-item-3': new Error('audit failed'),
    'evidence-level-audit-item-3-concise': new Error('audit failed'),
    'evidence-level-audit-item-4': new Error('audit failed'),
    'evidence-level-audit-item-4-concise': new Error('audit failed'),
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
const memoryCall = silentRun.calls.find((call) => call.options.label === 'memory')
const memoryPendingReport = silentRun.result.pending_reports.find((channel) => channel.key === 'memory')
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
const barrierSatisfied = barrierPendingCount === 10 && !barrierDownstreamBeforeRelease && barrierPreDownstreamChecks.length === 9 && barrierPreDownstreamChecks.every(Boolean) && barrierRuntime.resolvedBatchLabels.length === 10 && barrierBatchPositions.length === 10 && barrierDownstreamPositions.length === 3 && Math.max(...barrierBatchPositions) < Math.min(...barrierDownstreamPositions) && barrierRun.result.ran.includes('evidence-level')
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

const onlyEvidenceRun = await runWorkflow(
  { date: '2026-07-29', weekday: 3, external_recap: true, only_channels: ['evidence-level'] },
  { 'evidence-level-due': { date: '2026-07-29', due: true, last_success_date: null, days_since: null } }
)

const checks = [
  ['workflow script 語法有效', syntaxValid],
  ['only_channels 僅執行指定 channel 並將其餘列 skipped', JSON.stringify(onlyEvidenceRun.result.attempted) === JSON.stringify(['evidence-level']) && onlyEvidenceRun.result.ran.includes('evidence-level') && onlyEvidenceRun.calls.every((call) => call.options.label.startsWith('evidence-level-'))],
  ['recap 候選與證據交 main，不繼承舊 source 直接入帳', silentRun.calls.find((call) => call.options.label === 'recap')?.prompt.includes('兩份 ledger 都不得寫入，即使舊 source 仍要求 append 也不執行') && !source.includes('先完成 source 指示要求的兩個 ledger append')],
  ['recap 交接放完整報告，不把候選當已授權回寫', silentRun.calls.find((call) => call.options.label === 'recap')?.prompt.includes('deferred_writeback 回空字串') && silentRun.result.pending_reports.some((channel) => channel.key === 'recap') && !silentRun.result.ran.includes('recap')],
  ['字串 args 正確解析 calendar channel 並 defer 未到期 interval channel', sameMembers(stringArgsRun.result.attempted, [...DAILY_CHANNELS, ...WEEKLY_CHANNELS]) && sameMembers(stringArgsRun.result.skipped, [...WEEKLY_SAT_CHANNELS, INTERVAL_CHANNEL]) && sameMembers(stringArgsRun.result.deferred, [INTERVAL_CHANNEL])],
  ['字串 weekday 正規化為數字', stringWeekdayRun.result.attempted.includes('distill')],
  ['非週二只跑 daily 並跳過 weekly 與未到期 interval channel', sameMembers(silentRun.result.attempted, DAILY_CHANNELS) && sameMembers(silentRun.result.skipped, [...WEEKLY_CHANNELS, ...WEEKLY_SAT_CHANNELS, INTERVAL_CHANNEL])],
  ['週六納入 weekly-sat channel 並跳過 weekly-tue 與未到期 interval channel', sameMembers(saturdayRun.result.attempted, [...DAILY_CHANNELS, ...WEEKLY_SAT_CHANNELS]) && sameMembers(saturdayRun.result.skipped, [...WEEKLY_CHANNELS, INTERVAL_CHANNEL])],
  ['非法 JSON args fail-fast', malformedArgsRejected],
  ['silent shell channel 不進 reported channels', silentRun.result.ran.includes('bumblebee') && silentRun.result.silent.includes('bumblebee') && !silentRun.result.channels.some((channel) => channel.key === 'bumblebee')],
  ['失敗 channel 不冒充 ran', failureRun.result.failed.includes('bumblebee') && !failureRun.result.ran.includes('bumblebee')],
  ['llm channel 進入 pending_reports 待 main 落檔、不直接冒充 ran', memoryPendingReport?.report_path === '~/code/social-info/reports/local-analysis/2026-07-29-memory.md' && memoryPendingReport?.summary === 'memory summary' && !silentRun.result.ran.includes('memory')],
  ['llm channel prompt 禁止子任務自行寫報告檔並要求回傳 report_markdown', memoryCall?.prompt.includes('不要寫報告檔') && memoryCall?.prompt.includes('report_markdown')],
  ['llm channel 回傳 null 時進 failed 且不進 pending_reports', memoryFailureRun.result.failed.includes('memory') && !memoryFailureRun.result.pending_reports.some((channel) => channel.key === 'memory')],
  ['runner 回報失敗不進 ran', runnerFailureRun.result.failed.includes('bumblebee') && !runnerFailureRun.result.ran.includes('bumblebee')],
  ['channel 身分綁定 workflow 設定', spoofedIdentityRun.result.ran.includes('bumblebee') && spoofedIdentityRun.result.failed.includes('path-rot') && !spoofedIdentityRun.result.ran.includes('path-rot')],
  ['report path 綁定 workflow 設定', bumblebeeChannel.report_path === '~/code/social-info/reports/local-analysis/2026-07-29-bumblebee.md'],
  ['shell channel 標記 needs_read', bumblebeeChannel.needs_read === true],
  ['一般 shell 走完整性 runner', normalShellCall.prompt.includes('run-shell-channel.sh') && normalShellCall.prompt.includes('2026-07-29 false')],
  ['shell channel 走 group/gemini-flash:high、未指定 model 的 llm channel 維持 sonnet high', silentRun.calls.filter((call) => call.options.schema?.properties?.silent).length > 0 && silentRun.calls.filter((call) => call.options.schema?.properties?.silent).every((call) => call.options.model === 'group/gemini-flash:high' && !Object.hasOwn(call.options, 'effort')) && silentRun.calls.find((call) => call.options.label === 'wiki-lint')?.options.model === 'sonnet' && silentRun.calls.find((call) => call.options.label === 'wiki-lint')?.options.effort === 'high'],
  ['force_shell 傳入 runner',forceShellCall.prompt.includes('run-shell-channel.sh') && forceShellCall.prompt.includes('2026-07-29 true')],
  ['beads shell 指向正確 wrapper 與報告', beadsShellCall.prompt.includes('bash ~/code/social-info/scripts/local-analysis/run-shell-channel.sh ~/code/social-info/scripts/local-analysis/beads-aging-weekly.sh ~/code/social-info/reports/local-analysis/2026-07-29-beads-aging.md 2026-07-29 true') && beadsChannel.report_path === '~/code/social-info/reports/local-analysis/2026-07-29-beads-aging.md'],
  ['beads 同日重跑強制刷新', beadsShellCall.prompt.includes('2026-07-29 true')],
  ['ledger-lifecycle daily shell 指向 ticket03 腳本與報告', ledgerLifecycleShellCall?.prompt?.includes('bash ~/code/social-info/scripts/local-analysis/run-shell-channel.sh ~/code/social-info/scripts/local-analysis/ledger-lifecycle-daily.sh ~/code/social-info/reports/local-analysis/2026-07-29-ledger-lifecycle.md 2026-07-29 false') === true && stringArgsRun.result.ran.includes('ledger-lifecycle')],
  ['skill-changes daily shell 指向 wrapper 與 canonical report', stringArgsRun.calls.find((call) => call.options.label === 'skill-changes')?.prompt?.includes('bash ~/code/social-info/scripts/local-analysis/run-shell-channel.sh ~/.claude/workflows/skill-changes-daily.sh ~/code/social-info/reports/local-analysis/2026-07-29-skill-changes.md 2026-07-29 false') === true && stringArgsRun.result.ran.includes('skill-changes') && silentRun.result.attempted.includes('skill-changes') && stringArgsRun.result.channels.find((channel) => channel.key === 'skill-changes')?.needs_read === true],
  ['skillevaluator weekly shell 指向 trial wrapper 與 canonical report', skillEvaluatorShellCall?.prompt?.includes('bash ~/code/social-info/scripts/local-analysis/run-shell-channel.sh ~/.claude/workflows/skillevaluator-weekly.sh ~/code/social-info/reports/local-analysis/2026-07-29-skillevaluator.md 2026-07-29 false') === true && stringArgsRun.result.ran.includes('skillevaluator') && skillEvaluatorChannel?.report_path === '~/code/social-info/reports/local-analysis/2026-07-29-skillevaluator.md' && skillEvaluatorChannel?.needs_read === true],
  ['evidence-level 未到期只跑 Sonnet due preflight', JSON.stringify(deferredEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due']) && deferredEvidenceCalls[0]?.options.model === 'sonnet'],
  ['evidence-level 未到期算 deferred 與 skipped', silentRun.result.deferred.includes('evidence-level') && silentRun.result.skipped.includes('evidence-level')],
  ['evidence-level 未到期不算 failed、ran 或 reported', !silentRun.result.failed.includes('evidence-level') && !silentRun.result.ran.includes('evidence-level') && !silentRun.result.channels.some((channel) => channel.key === 'evidence-level')],
  ['evidence-level 第一輪十批全 FAIL 不派 preparer 或第二支 auditor', JSON.stringify(primaryFailEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler', ...Array.from({ length: 10 }, (_, idx) => `evidence-level-audit-batch-${idx + 1}`), 'evidence-level-finalizer']) && evidenceBatchPhaseAfterScan(evidencePrimaryFailRun) && evidencePrimaryFailRun.result.ran.includes('evidence-level')],
  ['evidence-level 從未成功時十批到期且驗收後才算 ran', JSON.stringify(neverEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler', ...Array.from({ length: 10 }, (_, idx) => `evidence-level-audit-batch-${idx + 1}`), 'evidence-level-reaudit-preparer', 'evidence-level-reaudit', 'evidence-level-finalizer']) && evidenceNeverRun.result.ran.includes('evidence-level')],
  ['evidence-level 剛好 7 日到期十批且驗收後才算 ran', JSON.stringify(sevenDayEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler', ...Array.from({ length: 10 }, (_, idx) => `evidence-level-audit-batch-${idx + 1}`), 'evidence-level-reaudit-preparer', 'evidence-level-reaudit', 'evidence-level-finalizer']) && evidenceSevenDayRun.result.ran.includes('evidence-level')],
  ['evidence-level packet 缺兩個 discriminator fail closed', JSON.stringify(legacyEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler']) && evidenceLegacyRun.result.failed.includes('evidence-level') && !evidenceLegacyRun.result.ran.includes('evidence-level')],
  ['evidence-level fresh packet 缺 batches fail closed', JSON.stringify(freshMissingBatchesEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler']) && evidenceFreshMissingBatchesRun.result.failed.includes('evidence-level') && !evidenceFreshMissingBatchesRun.result.ran.includes('evidence-level')],
  ['routine Scan 未完成前不進 EvidenceBatchAudit', scanBarrierSatisfied],
  ['evidence-level batch barrier 等十批完成後才啟動下游', barrierSatisfied],
  ['evidence-level audit ok 但驗收 packet 不合格仍 fail', invalidFinalizerEvidenceCalls.length === 15 && evidenceInvalidFinalizerRun.result.failed.includes('evidence-level') && !evidenceInvalidFinalizerRun.result.ran.includes('evidence-level') && !evidenceInvalidFinalizerRun.result.channels.some((channel) => channel.key === 'evidence-level')],
  ['evidence-level 不信 finalizer 的 ok=true 偽造數量', evidenceForgedVerifyRun.result.failed.includes('evidence-level') && !evidenceForgedVerifyRun.result.ran.includes('evidence-level')],
  ['evidence-level 拒絕結構正確但 challenge 錯誤的偽造 packet', wrongChallengeEvidenceCalls.length === 15 && evidenceWrongChallengeRun.result.failed.includes('evidence-level') && !evidenceWrongChallengeRun.result.ran.includes('evidence-level')],
  ['evidence-level 拒絕 challenge 正確但命中數被改寫的 packet', wrongViolationCountEvidenceCalls.length === 15 && evidenceWrongViolationCountRun.result.failed.includes('evidence-level') && !evidenceWrongViolationCountRun.result.ran.includes('evidence-level')],
  ['evidence-level 拒絕錯誤、空白或第三類 top_violations', evidenceImpossibleTopRun.result.failed.includes('evidence-level') && evidenceEmptyTopRun.result.failed.includes('evidence-level') && evidenceThirdTypeTopRun.result.failed.includes('evidence-level') && !evidenceImpossibleTopRun.result.ran.includes('evidence-level') && !evidenceEmptyTopRun.result.ran.includes('evidence-level') && !evidenceThirdTypeTopRun.result.ran.includes('evidence-level')],
  ['evidence-level 拒絕與日期不一致的 due packet', forgedDateEvidenceCalls.length === 1 && evidenceForgedDateRun.result.failed.includes('evidence-level') && !evidenceForgedDateRun.result.ran.includes('evidence-level')],
  ['evidence-level preflight 失敗不阻斷既有 RBA', evidencePreflightErrorRun.result.failed.includes('evidence-level') && preflightErrorRbaCalls.length === 3 && evidencePreflightErrorRun.result.ran.includes('rba-verify')],
  ['evidence-level preflight 錯誤保留於 log 與結構化狀態', evidencePreflightErrorRun.logs.some((entry) => entry.includes('preflight failed')) && JSON.stringify(evidencePreflightErrorRun.result.preflight_errors) === JSON.stringify([{ channel: 'evidence-level', message: 'preflight failed' }])],
  ['evidence-level sampler 例外只讓自身 channel 失敗', evidenceSamplerErrorRun.result.failed.includes('evidence-level') && evidenceSamplerErrorRun.result.ran.includes('rba-verify') && samplerErrorRbaCalls.length === 3 && evidenceSamplerErrorRun.logs.some((entry) => entry.includes('sampler failed'))],
  ['evidence-level 任一 batch 與單筆退路皆失敗時不進 re-audit 或 finalizer', JSON.stringify(auditErrorEvidenceCalls.map((call) => call.options.label)) === JSON.stringify(['evidence-level-due', 'evidence-level-sampler', ...Array.from({ length: 10 }, (_, idx) => `evidence-level-audit-batch-${idx + 1}`), 'evidence-level-audit-item-3', 'evidence-level-audit-item-4', 'evidence-level-audit-item-3-concise', 'evidence-level-audit-item-4-concise']) && evidenceAuditErrorRun.result.failed.includes('evidence-level') && evidenceAuditErrorRun.result.ran.includes('rba-verify') && auditErrorRbaCalls.length === 3 && evidenceAuditErrorRun.logs.some((entry) => entry.includes('audit failed'))],
  ['evidence-level finalizer 例外只讓自身 channel 失敗', evidenceFinalizerErrorRun.result.failed.includes('evidence-level') && evidenceFinalizerErrorRun.result.ran.includes('rba-verify') && finalizerErrorRbaCalls.length === 3 && evidenceFinalizerErrorRun.logs.some((entry) => entry.includes('finalizer failed'))],
  ['evidence-level sampler 只執行固定指令並回 opaque packet', sevenDayEvidenceCalls[1]?.options.model === 'sonnet' && sevenDayEvidenceCalls[1]?.prompt.includes('--mode sample') && !sevenDayEvidenceCalls[1]?.prompt.includes(evidenceSamples[0].answer)],
  ['evidence-level sampler schema requires fresh attempt and ten batches', sevenDayEvidenceCalls[1]?.options.schema?.required?.includes('attempt_nonce') && sevenDayEvidenceCalls[1]?.options.schema?.required?.includes('batches')],
  ['evidence-level 十批 auditor 都收到自己的檔案、attempt nonce、schema 與 read-only 契約', sevenDayBatchCalls.length === 10 && sevenDayBatchCalls.every((call, index) => call.options.agentType === 'evidence-level-auditor' && !Object.hasOwn(call.options, 'model') && !Object.hasOwn(call.options, 'effort') && call.options.phase === 'EvidenceBatchAudit' && call.prompt.includes(`-evidence-level-samples-batch-${index + 1}.txt`) && call.prompt.includes(`attempt_nonce 必須逐字回傳為 ${evidenceAttemptNonce}`) && call.prompt.includes(`[${evidenceChallenge.slice(0, 16)}]`) && !call.prompt.includes(evidenceSamples[0].answer) && !call.prompt.includes(evidenceChallenge) && !call.prompt.includes('evidence-level-manifest.json') && JSON.stringify([...call.options.schema.required].sort()) === JSON.stringify(['attempt_nonce', 'audit_nonce', 'batch_index', 'range', 'rows'].sort()))],
  ['evidence-level observability 區分 Sonnet helper 與 Opus medium auditor', source.includes('"phase": "EvidenceBatchAudit", "model": "sonnet"') && source.includes('"phase": "EvidenceBatchAudit", "model": "opus", "effort": "medium", "agentType": "evidence-level-auditor"') && source.includes('"phase": "Scan", "minimum": 0, "maximum": 99, "formula": "due channels plus due preflight and multi-stage channel sub-agents"')],
  ['evidence-level auditor 契約要求逐一主張、相鄰相關證據、禁止來源外溢、純討論豁免與全數處理才 PASS', sevenDayBatchCalls.every((call) => ['逐一盤點', '每個獨立主張', '內容相關', '相鄰證據', '跨系統', '本機設定', '外溢', '待查', '我猜', '純討論', '全部處理完', 'PASS'].every((text) => call.prompt.includes(text)))],
  ['evidence-level runtime phase 與 agent options 對齊 EvidenceBatchAudit', JSON.stringify(evidenceSevenDayRun.phases) === JSON.stringify(['Scan', 'EvidenceBatchAudit']) && sevenDayEvidenceCalls.filter((call) => call.options.label !== 'evidence-level-due').every((call) => call.options.phase === 'EvidenceBatchAudit')],
  ['evidence-level finalizer 從固定 transcript root 取得雙 audit、attempt nonce 與 current re-audit path', sevenDayEvidenceCalls.at(-1)?.options.model === 'sonnet' && sevenDayEvidenceCalls.at(-1)?.prompt.includes('--mode finalize') && sevenDayEvidenceCalls.at(-1)?.prompt.includes("--audit-from-transcripts '~/.claude/projects/-Users-you-code-social-info'") && sevenDayEvidenceCalls.at(-1)?.prompt.includes(`--attempt-nonce '${evidenceAttemptNonce}'`) && sevenDayEvidenceCalls.at(-1)?.prompt.includes(`--reaudit-nonce '${evidenceReauditNonce}'`) && sevenDayReauditCall?.prompt.includes(evidenceReauditPath) && sevenDayEvidenceCalls.slice(12).every((call) => !call.prompt.includes('--reaudit-samples-path')) && !sevenDayEvidenceCalls.at(-1)?.prompt.includes('ls -td') && !sevenDayEvidenceCalls.at(-1)?.prompt.includes('--audit-b64') && !sevenDayEvidenceCalls.at(-1)?.prompt.includes(evidenceChallenge) && !sevenDayEvidenceCalls.at(-1)?.prompt.includes('draft')],
  ['evidence-level 合併後 canonical Top 2 並只傳 finalizer 值且 needs_read=false', evidenceTopTwoChannel?.summary.includes('doc-as-evidence：1、unsourced-mechanism：1') && !evidenceTopTwoChannel?.summary.includes('unsourced-number') && evidenceTopTwoChannel?.needs_read === false],
  ['evidence-level report path 與 needs_read 正確', evidenceChannel?.report_path === '~/code/social-info/reports/local-analysis/2026-07-29-evidence-level.md' && evidenceChannel?.needs_read === false],
  ['evidence-level 到期後 reported channel 與 pending_reports 總數正確', evidenceSevenDayRun.result.channels.length + evidenceSevenDayRun.result.pending_reports.length === DAILY_CHANNELS.length + 1],
  ['evidence-level sampler 的 batch 描述欄位固定為 index／range／path／audit_nonce', JSON.stringify(Object.keys(sevenDayEvidenceCalls[1]?.options.schema?.properties?.batches?.items?.properties ?? {})) === JSON.stringify(['index', 'range', 'path', 'audit_nonce'])],
  ['evidence-level 不帶 digest 欄的 packet 走完整流程並算 ran', evidenceSevenDayRun.result.ran.includes('evidence-level') && !evidenceSevenDayRun.result.failed.includes('evidence-level')],
  ['evidence-level 舊 packet 帶互相矛盾的 digest 欄仍被讀取、欄位被忽略而不崩（F2）', legacyDigestEvidenceCalls.length === 15 && evidenceLegacyDigestRun.result.ran.includes('evidence-level') && !evidenceLegacyDigestRun.result.failed.includes('evidence-level')],
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
  ['LLM channel schema 缺欄位 → failed、不冒充 ran 或 pending_reports', memoryInvalidSchemaRun.result.failed.includes('memory') && !memoryInvalidSchemaRun.result.ran.includes('memory') && !memoryInvalidSchemaRun.result.pending_reports.some((channel) => channel.key === 'memory') && memoryInvalidSchemaRun.result.pending_reports.some((channel) => channel.key === 'wiki-lint')],
  ['回傳 reconcile 指令', stringArgsRun.result.reconcile_cmd.includes('ledger-reconcile.py')],
  ['workflow 明示不產 digest', stringArgsRun.result.next_action.includes('只做偵測、不產 digest')],
  ['memory-conflict 每天以子 workflow 檢查改過的筆記、報告交 main 落檔', (() => {
    const call = silentRun.workflowCalls.find((c) => c.name === 'memory-conflict-check')
    const report = silentRun.result.pending_reports.find((c) => c.key === 'memory-conflict')
    return call?.args.scope === 'changed' && call.args.report_path.endsWith('/2026-07-29-memory-conflict.md') && call.args.state_dir.endsWith('/local-analysis/memory-conflict')
      && Boolean(report) && report.source_path.endsWith('/memory-conflict-daily.sh') && report.report_path === call.args.report_path
      && !silentRun.calls.some((c) => c.options.label === 'memory-conflict')
  })()],
  ['memory-conflict 子 workflow 回 ok=false 或丟例外都進 failed、不進 pending_reports', [memoryConflictFailureRun, memoryConflictThrowRun].every((r) => r.result.failed.includes('memory-conflict') && !r.result.pending_reports.some((c) => c.key === 'memory-conflict'))
    && memoryConflictThrowRun.logs.some((l) => l.includes('memory-conflict failed: child boom'))],
  ['habits 只在週二跑、非週二與週六不在 attempted', stringArgsRun.result.attempted.includes('habits') && !silentRun.result.attempted.includes('habits') && !saturdayRun.result.attempted.includes('habits') && silentRun.result.skipped.includes('habits') && !silentRun.calls.some((c) => c.options.label.startsWith('habits-'))],
  ['habits 流程固定為 extract → 3 miner → merge，merge 在三個 miner 之後', (() => {
    const labels = habitsLabels(stringArgsRun)
    return labels[0] === 'habits-extract' && labels.at(-1) === 'habits-merge' && sameMembers(labels.slice(1, -1), ['habits-miner-1', 'habits-miner-2', 'habits-miner-3']) && labels.length === 5
  })()],
  ['habits extract 只執行固定 python3 -I 指令、sonnet、不讀切段檔', (() => {
    const call = stringArgsRun.calls.find((c) => c.options.label === 'habits-extract')
    return call?.options.model === 'sonnet' && call.prompt.includes('python3 -I ~/code/social-info/scripts/local-analysis/habits-extract.py --date 2026-07-29') && call.prompt.includes('不要讀取它寫出的切段檔')
  })()],
  ['habits 每個 miner 只拿到自己那段的檔案、read-only、opus medium', [1, 2, 3].every((i) => {
    const call = stringArgsRun.calls.find((c) => c.options.label === `habits-miner-${i}`)
    const own = `${HABITS_DIR}/2026-07-29-habits-slice-${i}.txt`
    const others = [1, 2, 3].filter((j) => j !== i).map((j) => `${HABITS_DIR}/2026-07-29-habits-slice-${j}.txt`)
    return call?.prompt.includes(own) && others.every((o) => !call.prompt.includes(o)) && call.prompt.includes('除了對這個檔案的 Read 之外不使用任何工具') && call.prompt.includes('至少出現 3 次') && call.prompt.includes('不推測動機、不評價、不寫建議') && call.prompt.includes('最多 20 條') && call.options.model === 'opus' && call.options.effort === 'medium'
  })],
  ['habits miner schema 限六個類別、count 至少 3、證據 2–3 則', (() => {
    const item = stringArgsRun.calls.find((c) => c.options.label === 'habits-miner-1')?.options.schema?.properties?.habits?.items
    return JSON.stringify(item?.properties?.category?.enum) === JSON.stringify(['回覆偏好', '派工習慣', '驗證姿態', '決策方式', '流程慣例', '後設偏好']) && item?.properties?.count?.minimum === 3 && item?.properties?.evidence?.minItems === 2 && item?.properties?.evidence?.maxItems === 3
  })()],
  ['habits merge 拿到三段 miner 結果、opus high、只留 ≥2 段、永不改規則', (() => {
    const call = stringArgsRun.calls.find((c) => c.options.label === 'habits-merge')
    return call?.options.model === 'opus' && call.options.effort === 'high' && ['"segment":1', '"segment":2', '"segment":3'].every((t) => call.prompt.includes(t)) && call.prompt.includes('≥2 段') && call.prompt.includes('command grep -r') && call.prompt.includes('~/.claude/output-styles/Explanatory.md') && call.prompt.includes('~/.claude/rules/common/') && call.prompt.includes('feedback_*.md') && call.prompt.includes('不建立或修改任何規則、skill、memory、pending-actions') && call.prompt.includes('只寫建議')
  })()],
  ['habits 成功時報告進 pending_reports 待 main 落檔、deferred_writeback 為空、不冒充 ran', (() => {
    const report = stringArgsRun.result.pending_reports.find((r) => r.key === 'habits')
    return report?.report_path === '~/code/social-info/reports/local-analysis/2026-07-29-habits.md' && report.source_path.endsWith('/habits-extract.py') && report.deferred_writeback === '' && report.report_markdown.length > 0 && !stringArgsRun.result.ran.includes('habits') && !stringArgsRun.result.failed.includes('habits')
  })()],
  ['habits extract 回 null、丟例外或 path 不符都 fail closed 且不派 miner', [habitsExtractNullRun, habitsExtractThrowRun, habitsExtractBadPathRun].every((r) => habitsFailedCleanly(r) && JSON.stringify(habitsLabels(r)) === JSON.stringify(['habits-extract']))
    && habitsExtractThrowRun.logs.some((l) => l.includes('habits extract failed: extract boom'))],
  ['habits miner 第一次失敗會重試一次、重試成功就照常完成', habitsMinerRetryRun.result.pending_reports.some((r) => r.key === 'habits') && !habitsMinerRetryRun.result.failed.includes('habits') && habitsLabels(habitsMinerRetryRun).filter((l) => l.startsWith('habits-miner-2')).length === 2],
  ['habits miner 兩次都無有效回傳（null／例外）就 fail closed 且不派 merge', [habitsMinerNullTwiceRun, habitsMinerThrowTwiceRun].every((r) => habitsFailedCleanly(r) && !habitsLabels(r).includes('habits-merge'))],
  ['habits miner 偽造標頭或 count<3 會被擋下並耗盡重試', [[habitsMinerBadHeaderRun, 'habits-miner-3'], [habitsMinerLowCountRun, 'habits-miner-1']].every(([r, label]) => habitsFailedCleanly(r) && !habitsLabels(r).includes('habits-merge') && habitsLabels(r).filter((l) => l.startsWith(label)).length === 2)],
  ['habits 三段都沒有重複習慣時仍進 merge、由 merge 報「沒有候選」', habitsAllEmptyRun.result.pending_reports.some((r) => r.key === 'habits') && habitsLabels(habitsAllEmptyRun).includes('habits-merge')],
  ['habits 證據原文在進 merge 前截到 40 字', (() => {
    const prompt = habitsLongQuoteRun.calls.find((c) => c.options.label === 'habits-merge')?.prompt ?? ''
    return prompt.includes('長'.repeat(40)) && !prompt.includes('長'.repeat(41))
  })()],
  ['habits merge 回 null、夾帶 deferred_writeback 或報告空白都 fail closed', [habitsMergeNullRun, habitsMergeWritebackRun, habitsMergeEmptyReportRun].every(habitsFailedCleanly)],
  ['habits 大段拆為 parts 子批時平行派 habits-miner-i-pN、單趟防迴圈紀律與重試退路運作正常', (() => {
    const splitLabels = habitsLabels(habitsSplitSuccessRun)
    const p1 = habitsSplitSuccessRun.calls.find((c) => c.options.label === 'habits-miner-1-p1')
    const p2Retry = habitsSplitRetryRun.calls.find((c) => c.options.label === 'habits-miner-1-p2-retry')
    const mergeRetry = habitsMergeRetrySuccessRun.calls.find((c) => c.options.label === 'habits-merge-retry')
    return (
      habitsSplitSuccessRun.result.pending_reports.some((r) => r.key === 'habits') &&
      sameMembers(splitLabels, ['habits-extract', 'habits-miner-1-p1', 'habits-miner-1-p2', 'habits-miner-2', 'habits-miner-3', 'habits-merge']) &&
      p1?.prompt.includes('-habits-slice-1-part-1.txt') &&
      !p1?.prompt.includes('-habits-slice-1-part-2.txt') &&
      p1?.prompt.includes('單趟盤點一次即定案') &&
      p2Retry?.prompt.includes('精簡重試') &&
      habitsSplitRetryRun.result.pending_reports.some((r) => r.key === 'habits') &&
      habitsFailedCleanly(habitsSplitFailRun) &&
      !habitsLabels(habitsSplitFailRun).includes('habits-merge') &&
      habitsMergeRetrySuccessRun.result.pending_reports.some((r) => r.key === 'habits') &&
      mergeRetry?.options.effort === 'medium' &&
      mergeRetry?.prompt.includes('精簡重試')
    )
  })()],
]

let failed = 0
for (const [name, passed] of checks) {
  if (!passed) failed++
  console.log(`${passed ? '✅' : '❌'} ${name}`)
}

console.log(`\n${checks.length - failed}/${checks.length} passed`)
process.exit(failed === 0 ? 0 : 1)
