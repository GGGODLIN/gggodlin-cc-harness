import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { spawn, spawnSync } from 'node:child_process'

const script = new URL('./evidence-level-sample.mjs', import.meta.url).pathname
const TEST_AUDIT_NONCE = '9'.repeat(64)
const TEST_ATTEMPT_NONCE = '7'.repeat(64)
const TRANSCRIPT_MAX_FILES = 128
const TRANSCRIPT_MAX_BYTES = 8 * 1024 * 1024

const makeFixture = () => {
  const base = fs.mkdtempSync(path.join(os.tmpdir(), 'evidence-level-'))
  const root = path.join(base, 'projects')
  const reports = path.join(base, 'reports')
  const project = path.join(root, 'fixture')
  fs.mkdirSync(project, { recursive: true })
  fs.mkdirSync(reports, { recursive: true })
  return { base, root, reports, project }
}

const writeRows = (file, rows) => {
  fs.writeFileSync(file, `${rows.map((row) => JSON.stringify(row)).join('\n')}\n`)
}

const assistant = ({ text, timestamp, stopReason = 'end_turn', sidechain = false, sessionId = 'session' }) => ({
  type: 'assistant',
  isSidechain: sidechain,
  sessionId,
  timestamp,
  message: {
    stop_reason: stopReason,
    content: [{ type: 'text', text }],
  },
})

// Only the legacy-format fixtures below compute digests; the script itself neither writes nor checks one.
const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex')
const argsFor = ({ date = '2026-08-14', root, reports, mode = 'sample', audit = null, auditTranscripts = null, auditNonce = null, attemptNonce = TEST_ATTEMPT_NONCE, reauditNonce = null, extraFlags = [] }) => [
  script,
  '--date',
  date,
  '--root',
  root,
  '--reports',
  reports,
  '--mode',
  mode,
  ...(audit == null ? [] : ['--audit-b64', Buffer.from(JSON.stringify(audit)).toString('base64')]),
  ...(auditTranscripts == null ? [] : ['--audit-from-transcripts', auditTranscripts]),
  ...(!['finalize', 'prepare-reaudit'].includes(mode) ? [] : [
    '--audit-nonce',
    auditNonce ?? TEST_AUDIT_NONCE,
    ...(attemptNonce == null ? [] : ['--attempt-nonce', attemptNonce]),
  ]),
  ...(mode !== 'finalize' || reauditNonce == null ? [] : ['--reaudit-nonce', reauditNonce]),
  ...extraFlags,
]

const run = (options) => {
  const result = spawnSync(process.execPath, argsFor(options), { encoding: 'utf8' })
  assert.equal(result.status, 0, result.stderr)
  return JSON.parse(result.stdout)
}

const runAsync = (options) => new Promise((resolve, reject) => {
  const child = spawn(process.execPath, argsFor(options))
  let stdout = ''
  let stderr = ''
  child.stdout.setEncoding('utf8')
  child.stderr.setEncoding('utf8')
  child.stdout.on('data', (chunk) => { stdout += chunk })
  child.stderr.on('data', (chunk) => { stderr += chunk })
  child.on('error', reject)
  child.on('close', (status) => {
    if (status !== 0) {
      reject(new Error(stderr))
      return
    }
    resolve(JSON.parse(stdout))
  })
})

const repeat = (value, length) => value.repeat(length)
const manifestPathFor = (fixture, date = '2026-08-14') => path.join(fixture.reports, `${date}-evidence-level-manifest.json`)
const samplesFor = (fixture, date = '2026-08-14') =>
  JSON.parse(fs.readFileSync(manifestPathFor(fixture, date), 'utf8')).samples
const samplesTextPathFor = (fixture, date = '2026-08-14') => path.join(fixture.reports, `${date}-evidence-level-samples.txt`)
const reauditSamplesTextPathFor = (fixture, date = '2026-08-14', attemptNonce = null) => path.join(fixture.reports, `${date}-evidence-level-reaudit-samples${attemptNonce == null ? '' : `-${attemptNonce}`}.txt`)
const reportPathFor = (fixture, date = '2026-08-14') => path.join(fixture.reports, `${date}-evidence-level.md`)
const receiptPathFor = (fixture, date = '2026-08-14') => path.join(fixture.reports, `${date}-evidence-level.verified.json`)
const publicationPathFor = (fixture, date = '2026-08-14') => path.join(fixture.reports, `${date}-evidence-level.publish.json`)
const versionPathFor = (fixture, date = '2026-08-14') => path.join(fixture.reports, `${date}-evidence-level.version.json`)
const modeFor = (file) => fs.statSync(file).mode & 0o777
const readJson = (file) => JSON.parse(fs.readFileSync(file, 'utf8'))
const auditFor = (samples, findings = [], auditNonce = TEST_AUDIT_NONCE) => ({
  audit_nonce: auditNonce,
  rows: samples.map((sample, index) => ({
    timestamp: sample.timestamp,
    session: sample.session,
    path: sample.path,
    result: findings[index]?.length ? 'FAIL' : 'PASS',
    findings: findings[index] ?? [],
  })),
})
const readResultText = (value, startLine = 1) => value.split('\n').map((line, index) => `${startLine + index}\t${line}`).join('\n')
const writeAuditTranscript = ({ directory, name = 'agent-audit.jsonl', samplesPath, samplesText, audit, includeRead = true, includeOutput = true, includeOutputResult = false, chunks = null, extraTool = null }) => {
  const content = []
  const readChunks = chunks ?? [{ offset: null, text: samplesText }]
  if (includeRead) {
    readChunks.forEach((chunk, index) => content.push({
      type: 'tool_use',
      name: 'Read',
      id: `read-${index + 1}`,
      input: { file_path: samplesPath, ...(chunk.offset == null ? {} : { offset: chunk.offset }), ...(chunk.limit == null ? {} : { limit: chunk.limit }) },
    }))
  }
  if (extraTool != null) content.push(extraTool)
  const rows = [{ message: { content } }]
  if (includeRead) {
    readChunks.forEach((chunk, index) => rows.push({ message: { content: [{ type: 'tool_result', tool_use_id: `read-${index + 1}`, content: readResultText(chunk.text, chunk.offset ?? 1) }] } }))
  }
  if (includeOutput) {
    rows.push({ message: { content: [{ type: 'tool_use', id: 'structured-output', name: 'StructuredOutput', input: audit }] } })
    if (includeOutputResult) rows.push({ message: { content: [{ type: 'tool_result', tool_use_id: 'structured-output', content: 'Structured output provided successfully' }] } })
  }
  fs.writeFileSync(path.join(directory, name), `${rows.map((row) => JSON.stringify(row)).join('\n')}\n`)
}

const writeBatchAuditTranscript = ({ directory, name, batch, samplesText, audit, metadata, attemptNonce, includeOutputResult = false }) => writeAuditTranscript({
  directory,
  name,
  samplesPath: batch.path,
  samplesText,
  audit: {
    ...audit,
    batch_index: batch.index,
    range: batch.range,
    ...(metadata ?? (attemptNonce == null ? {} : { attempt_nonce: attemptNonce })),
  },
  includeOutputResult,
})

const makeTwentySampleFixture = () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'twenty.jsonl'), Array.from({ length: 20 }, (_, index) => assistant({
    text: repeat(String.fromCharCode(97 + index), 220),
    timestamp: `2026-08-14T${String(index + 1).padStart(2, '0')}:00:00.000Z`,
    sessionId: `batch-session-${index + 1}`,
  })))
  const sampled = run(fixture)
  const manifest = JSON.parse(fs.readFileSync(manifestPathFor(fixture), 'utf8'))
  return { fixture, sampled, manifest, samples: manifest.samples }
}

const writeValidBatchTranscripts = ({ fixture, sampled, manifest, directory = path.join(fixture.reports, 'wf-transcripts'), findings = null, attemptNonce, namePrefix = 'agent-batch-', includeOutputResult = false }) => {
  const effectiveAttemptNonce = attemptNonce === undefined ? sampled.attempt_nonce : attemptNonce
  fs.mkdirSync(directory, { recursive: true })
  manifest.batches.forEach((batch, index) => {
    const batchSamples = manifest.samples.slice(index * 5, index * 5 + 5)
    const batchFindings = findings?.[index] ?? batchSamples.map((sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }])
    writeBatchAuditTranscript({
      directory,
      name: `${namePrefix}${batch.index}.jsonl`,
      batch,
      samplesText: fs.readFileSync(batch.path, 'utf8'),
      audit: auditFor(batchSamples, batchFindings, sampled.audit_nonce),
      attemptNonce: effectiveAttemptNonce,
      includeOutputResult,
    })
  })
  return directory
}

const assertUnverified = (fixture, packet) => {
  assert.equal(packet.ok, false)
  assert.equal(packet.tp_style_violation_count, null)
  assert.equal(fs.existsSync(publicationPathFor(fixture)), false)
  assert.equal(fs.existsSync(reportPathFor(fixture)), false)
  assert.equal(fs.existsSync(receiptPathFor(fixture)), false)
}

test('filters known-good and includes known-bad and 200-character boundary', () => {
  const fixture = makeFixture()
  const file = path.join(fixture.project, 'fixture.jsonl')
  writeRows(file, [
    assistant({ text: repeat('a', 250), timestamp: '2026-08-09T01:00:00.000Z', stopReason: 'tool_use', sessionId: 'tool-message' }),
    assistant({ text: repeat('b', 250), timestamp: '2026-08-09T02:00:00.000Z', sidechain: true, sessionId: 'sidechain' }),
    assistant({ text: `${repeat('c', 199)}\n\`\`\`js\n${repeat('x', 100)}\n\`\`\``, timestamp: '2026-08-09T03:00:00.000Z', sessionId: 'boundary-199' }),
    assistant({ text: `${repeat('i', 199)}\n    ${repeat('z', 300)}`, timestamp: '2026-08-09T03:30:00.000Z', sessionId: 'indented-code-199' }),
    assistant({ text: `${repeat('d', 200)}\n\`\`\`js\n${repeat('y', 100)}\n\`\`\``, timestamp: '2026-08-09T04:00:00.000Z', sessionId: 'boundary-200' }),
    assistant({ text: repeat('e', 240), timestamp: '2026-08-09T05:00:00.000Z', sessionId: 'known-bad' }),
  ])

  const packet = run(fixture)
  const samples = samplesFor(fixture)
  assert.equal(packet.eligible, 2)
  assert.equal(packet.sample_count, 2)
  assert.deepEqual(samples.map((sample) => sample.session), ['boundary-200', 'known-bad'])
  assert.equal(samples[0].answer.includes('```js'), true)
  assert.equal(Object.hasOwn(packet, 'samples_b64'), false)
  const samplesTextPath = samplesTextPathFor(fixture)
  const samplesText = fs.readFileSync(samplesTextPath, 'utf8')
  assert.equal(modeFor(samplesTextPath), 0o600)
  assert.equal(samplesText.includes(`=== BEGIN SAMPLE 1/2 [${packet.challenge.slice(0, 16)}] ===`), true)
  assert.equal(samplesText.includes(`=== END SAMPLE 2/2 [${packet.challenge.slice(0, 16)}] ===`), true)
  assert.equal(samplesText.includes(samples[0].answer), true)
  assert.equal(samplesText.includes(samples[1].answer), true)
})

test('samples at most 20 answers in deterministic total order', () => {
  const fixture = makeFixture()
  const file = path.join(fixture.project, 'many.jsonl')
  const rows = Array.from({ length: 41 }, (_, index) => assistant({
    text: repeat(String(index % 10), 220),
    timestamp: `2026-08-10T00:${String(index).padStart(2, '0')}:00.000Z`,
    sessionId: `session-${String(index).padStart(2, '0')}`,
  }))
  writeRows(file, rows)

  const packet = run(fixture)
  const samples = samplesFor(fixture)
  assert.equal(packet.eligible, 41)
  assert.equal(packet.sample_count, 20)
  assert.equal(samples.length, 20)
  assert.deepEqual(
    samples.map((sample) => sample.row_index),
    [0, 2, 4, 6, 8, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 32, 34, 36, 38, 40]
  )
})

test('uses timestamp path and row index as a locale-independent total order', () => {
  const fixture = makeFixture()
  const firstProject = path.join(fixture.root, 'z-project')
  const secondProject = path.join(fixture.root, 'ä-project')
  fs.mkdirSync(firstProject)
  fs.mkdirSync(secondProject)
  writeRows(path.join(firstProject, 'same.jsonl'), [assistant({
    text: repeat('z', 220),
    timestamp: '2026-08-10T00:00:00.000Z',
    sessionId: 'z-session',
  })])
  writeRows(path.join(secondProject, 'same.jsonl'), [assistant({
    text: repeat('a', 220),
    timestamp: '2026-08-10T00:00:00.000Z',
    sessionId: 'accent-session',
  })])

  const packet = run(fixture)
  assert.deepEqual(samplesFor(fixture).map((sample) => sample.session), ['z-session', 'accent-session'])
})

test('persists full redacted answers in private artifacts', () => {
  const fixture = makeFixture()
  const secretValues = [
    'sk-ant-api03-FAKESECRET0123456789',
    'ghp_FAKESECRET012345678901234567890123456',
    // 拆開拼接：完整字面值會被 gitleaks 等掃描器當成真的 Slack token
    ['xoxb', '1234567890-1234567890-FAKESECRET'].join('-'),
    'AKIAFAKESECRET123456',
    'GENERIC-SECRET-987654321',
    'secret value with spaces',
    'dXNlcjpiYXNpYy1mYWtlLXNlY3JldA==',
    'abc123',
    'COOKIE-SESSION-FAKE-111',
    'COOKIE-SID-FAKE-222',
    'SET-COOKIE-SESSION-FAKE-333',
    'QUOTED-COOKIE-FAKE-444',
    'QUOTED-SET-COOKIE-FAKE-555',
    'CURL-COOKIE-FAKE-666',
    'JSON-COOKIE-FAKE-777',
    'ESCAPED-COOKIE-FAKE-888',
    'ESCAPED-PASSWORD-FAKE-999',
    'fullwidth-token-secret',
    'UNQUOTED-HEADER-COOKIE-111',
    'UNQUOTED-HEADER-SET-COOKIE-222',
    'CURL-B-COOKIE-333',
    'CURL-LONG-COOKIE-444',
  ]
  const trailingClaim = '已完成全部驗證但此句沒有證據'
  const fullwidthClaim = '這段全形標點後的聲明必須保留'
  const longTail = repeat('長', 9000)
  writeRows(path.join(fixture.project, 'secret.jsonl'), [assistant({
    text: `Authorization: Bearer ${secretValues[0]}\napi_key=${secretValues[1]}\nslack=${secretValues[2]}\naws=${secretValues[3]}\n{"password": "${secretValues[4]}"}\nclient_secret="${secretValues[5]}"\nAuthorization: Basic ${secretValues[6]}\ntoken=${secretValues[7]} ${trailingClaim}\nCookie: session=${secretValues[8]}; sid=${secretValues[9]}; theme=dark\nSet-Cookie: session_id=${secretValues[10]}; Path=/; HttpOnly\n> Cookie: session=${secretValues[11]}\n  < Set-Cookie: sid=${secretValues[12]}\ncurl -H 'Cookie: session=${secretValues[13]}' https://example.test/after-cookie\n{"Cookie": "session=${secretValues[14]}"}\n{\\"Cookie\\": \\"session=${secretValues[15]}\\"}\n{\\"password\\": \\"${secretValues[16]}\\"}\ntoken=${secretValues[17]}，${fullwidthClaim}\ncurl -H Cookie:session=${secretValues[18]} https://example.test/unquoted-header\ncurl --header=Set-Cookie:sid=${secretValues[19]} https://example.test/unquoted-set-header\ncurl -b 'session=${secretValues[20]}' https://example.test/curl-b\ncurl --cookie 'sid=${secretValues[21]}' https://example.test/curl-cookie\n${longTail}`,
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'secret-session',
  })])

  const packet = run(fixture)
  const samples = samplesFor(fixture)
  const manifestPath = manifestPathFor(fixture)
  const persisted = fs.readFileSync(manifestPath, 'utf8')

  assert.equal(samples[0].answer.endsWith(longTail), true)
  assert.equal(samples[0].answer.length > 6000, true)
  assert.equal(samples[0].answer.includes(trailingClaim), true)
  assert.equal(persisted.includes(trailingClaim), true)
  assert.equal(samples[0].answer.includes(fullwidthClaim), true)
  assert.equal(persisted.includes(fullwidthClaim), true)
  assert.equal(samples[0].answer.includes('Cookie: session=[REDACTED]; sid=[REDACTED]; theme=[REDACTED]'), true)
  assert.equal(samples[0].answer.includes('Set-Cookie: session_id=[REDACTED]; Path=[REDACTED]; HttpOnly'), true)
  assert.equal(samples[0].answer.includes('> Cookie: session=[REDACTED]'), true)
  assert.equal(samples[0].answer.includes('< Set-Cookie: sid=[REDACTED]'), true)
  assert.equal(samples[0].answer.includes("curl -H 'Cookie: session=[REDACTED]' https://example.test/after-cookie"), true)
  assert.equal(samples[0].answer.includes('{"Cookie": "session=[REDACTED]"}'), true)
  assert.equal(samples[0].answer.includes('{\\"Cookie\\": \\"session=[REDACTED]\\"}'), true)
  assert.equal(samples[0].answer.includes('{\\"password\\": \\"[REDACTED]\\"}'), true)
  assert.equal(samples[0].answer.includes('https://example.test/unquoted-header'), true)
  assert.equal(samples[0].answer.includes('https://example.test/unquoted-set-header'), true)
  assert.equal(samples[0].answer.includes('https://example.test/curl-b'), true)
  assert.equal(samples[0].answer.includes('https://example.test/curl-cookie'), true)
  const samplesText = fs.readFileSync(samplesTextPathFor(fixture), 'utf8')
  for (const [index, secret] of secretValues.entries()) {
    assert.equal(persisted.includes(secret), false, `persisted secret index ${index}`)
    assert.equal(samples[0].answer.includes(secret), false, `packet secret index ${index}`)
    assert.equal(samplesText.includes(secret), false, `samples text secret index ${index}`)
  }
  assert.equal(samplesText.includes(trailingClaim), true)
  assert.equal(persisted.includes('[REDACTED]'), true)
  assert.equal(modeFor(fixture.reports), 0o700)
  assert.equal(modeFor(manifestPath), 0o600)
})

test('redacts quoted sensitive assignments through escaped quotes while preserving trailing claims', () => {
  const fixture = makeFixture()
  const secretTail = 'ESCAPED-QUOTE-SECRET-TAIL-123456'
  const trailingClaim = '已完成全部驗證但沒有附上證據'
  const backslash = String.fromCharCode(0x5c)
  writeRows(path.join(fixture.project, 'escaped-quote.jsonl'), [assistant({
    text: `{${backslash}"password${backslash}":${backslash}"prefix${secretTail}${backslash.repeat(5)}"} ${trailingClaim}\n${repeat('補', 220)}`,
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'escaped-quote-session',
  })])

  const packet = run(fixture)
  const answer = samplesFor(fixture)[0].answer
  const persisted = fs.readFileSync(manifestPathFor(fixture), 'utf8')

  assert.equal(answer.includes(secretTail), false)
  assert.equal(persisted.includes(secretTail), false)
  assert.equal(answer.includes(trailingClaim), true)
  assert.equal(persisted.includes(trailingClaim), true)
})

test('redacts cookie pair values while preserving same-line unsupported claims', () => {
  const fixture = makeFixture()
  const cookieSecret = 'COOKIE-SECRET-ONE-123456'
  const setCookieSecret = 'SET-COOKIE-SECRET-TWO-123456'
  const cookieClaim = '已完成 Cookie 全部驗證但沒有證據'
  const setCookieClaim = '已完成 Set-Cookie 全部驗證但沒有證據'
  writeRows(path.join(fixture.project, 'cookie-claim.jsonl'), [assistant({
    text: `Cookie: session=${cookieSecret}; theme=dark：${cookieClaim}\nSet-Cookie: sid=${setCookieSecret}; Path=/; HttpOnly。${setCookieClaim}\n${repeat('補', 220)}`,
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'cookie-claim-session',
  })])

  const packet = run(fixture)
  const answer = samplesFor(fixture)[0].answer
  const persisted = fs.readFileSync(manifestPathFor(fixture), 'utf8')

  assert.equal(answer.includes(cookieSecret), false)
  assert.equal(answer.includes(setCookieSecret), false)
  assert.equal(persisted.includes(cookieSecret), false)
  assert.equal(persisted.includes(setCookieSecret), false)
  assert.equal(answer.includes(`Cookie: session=[REDACTED]; theme=[REDACTED]：${cookieClaim}`), true)
  assert.equal(answer.includes(`Set-Cookie: sid=[REDACTED]; Path=[REDACTED]; HttpOnly。${setCookieClaim}`), true)
  assert.equal(persisted.includes(cookieClaim), true)
  assert.equal(persisted.includes(setCookieClaim), true)
})

test('publishes one complete manifest under concurrent sampling', async () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'concurrent.jsonl'), [assistant({
    text: repeat('m', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'manifest-session',
  })])

  const packets = await Promise.all(Array.from({ length: 24 }, () => runAsync(fixture)))
  assert.equal(new Set(packets.map((packet) => packet.challenge)).size, 1)
  const persisted = JSON.parse(fs.readFileSync(manifestPathFor(fixture), 'utf8'))
  assert.equal(persisted.challenge, packets[0].challenge)
  assert.equal(persisted.samples[0].session, 'manifest-session')
})

test('publishes one complete batched manifest under concurrent sampling', async () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'concurrent-twenty.jsonl'), Array.from({ length: 20 }, (_, index) => assistant({
    text: repeat(String.fromCharCode(65 + index), 220),
    timestamp: `2026-08-14T${String(index + 1).padStart(2, '0')}:00:00.000Z`,
    sessionId: `concurrent-batch-session-${index + 1}`,
  })))

  const packets = await Promise.all(Array.from({ length: 12 }, () => runAsync(fixture)))
  assert.equal(packets.every((packet) => packet.sample_count === 20 && packet.batches.length === 4), true)
  assert.equal(new Set(packets.map((packet) => packet.challenge)).size, 1)
  assert.equal(new Set(packets.map((packet) => packet.audit_nonce)).size, 1)
  const persisted = JSON.parse(fs.readFileSync(manifestPathFor(fixture), 'utf8'))
  assert.equal(persisted.challenge, packets[0].challenge)
  assert.equal(persisted.audit_nonce, packets[0].audit_nonce)
})

test('finalizer rejects an audit when the manifest no longer matches the samples text it was shown', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
    text: repeat('a', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'digest-bound-session',
  })])
  const sampled = run(fixture)
  const samples = samplesFor(fixture)
  const audit = auditFor(samples)
  const manifestPath = manifestPathFor(fixture)
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  manifest.samples[0].answer = repeat('b', 220)
  manifest.challenge = 'c'.repeat(64)
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`, { mode: 0o600 })

  const finalized = run({ ...fixture, mode: 'finalize', audit })
  assert.equal(finalized.ok, false)
  assert.equal(fs.existsSync(publicationPathFor(fixture)), false)
})

test('finalizer rejects a one-byte samples text mutation before publication', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
    text: repeat('a', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'file-bound-session',
  })])
  run(fixture)
  const audit = auditFor(samplesFor(fixture))
  fs.appendFileSync(samplesTextPathFor(fixture), 'x')

  const finalized = run({ ...fixture, mode: 'finalize', audit })
  assert.equal(finalized.ok, false)
  assert.equal(fs.existsSync(publicationPathFor(fixture)), false)
})

test('finalize validates structured rows and generates the complete report', () => {
  const fixture = makeFixture()
  const firstPath = path.join(fixture.project, 'first.jsonl')
  const secondPath = path.join(fixture.project, 'second.jsonl')
  writeRows(firstPath, [assistant({
    text: repeat('v', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'first-session',
  })])
  writeRows(secondPath, [assistant({
    text: repeat('w', 220),
    timestamp: '2026-08-14T02:00:00.000Z',
    sessionId: 'second-session',
  })])
  const sampled = run(fixture)
  const samples = samplesFor(fixture)
  const manifestPath = manifestPathFor(fixture)
  const reportPath = reportPathFor(fixture)
  const manifestBefore = fs.readFileSync(manifestPath, 'utf8')

  writeRows(path.join(fixture.project, 'concurrent.jsonl'), [assistant({
    text: repeat('x', 220),
    timestamp: '2026-08-14T03:00:00.000Z',
    sessionId: 'concurrent-session',
  })])
  assert.equal(run(fixture).challenge, sampled.challenge)
  assert.equal(fs.readFileSync(manifestPath, 'utf8'), manifestBefore)

  const validAudit = auditFor(samples, [
    [
      { type: 'unsourced-number', quote: 'vvvvv' },
      { type: 'doc-as-evidence', quote: 'vvvv' },
      { type: 'unsourced-mechanism', quote: 'vvv' },
    ],
    [{ type: 'unsourced-number', quote: 'wwwww' }],
  ])
  const reordered = { rows: [...validAudit.rows].reverse() }
  assert.equal(run({ ...fixture, mode: 'finalize', audit: reordered }).ok, false)

  const invalidQuote = structuredClone(validAudit)
  invalidQuote.rows[0].findings[0].quote = 'not in the answer'
  assert.equal(run({ ...fixture, mode: 'finalize', audit: invalidQuote }).ok, false)

  const duplicateType = structuredClone(validAudit)
  duplicateType.rows[0].findings.push({ type: 'unsourced-number', quote: 'vvv' })
  assert.equal(run({ ...fixture, mode: 'finalize', audit: duplicateType }).ok, false)

  const finalized = run({ ...fixture, mode: 'finalize', audit: validAudit })
  assert.equal(finalized.ok, true)
  assert.equal(finalized.challenge, sampled.challenge)
  assert.equal(finalized.eligible, 2)
  assert.equal(finalized.sample_count, 2)
  assert.equal(finalized.tp_style_violation_count, 2)
  assert.equal(fs.existsSync(reportPath), true)
  assert.equal(fs.existsSync(path.join(fixture.reports, '2026-08-14-evidence-level.draft.md')), false)
  assert.equal(run({ ...fixture, mode: 'due' }).due, false)

  const reportContent = fs.readFileSync(reportPath, 'utf8')
  assert.equal(reportContent.includes('- unsourced-number：2\n- doc-as-evidence：1'), true)
  assert.equal(reportContent.includes('unsourced-mechanism：1'), false)
  assert.equal(reportContent.includes('命中 unsourced-number、unsourced-mechanism、doc-as-evidence'), true)
  const publication = JSON.parse(fs.readFileSync(publicationPathFor(fixture), 'utf8'))
  assert.deepEqual(publication.top_violations, [
    { type: 'unsourced-number', count: 2 },
    { type: 'doc-as-evidence', count: 1 },
  ])
  assert.equal(reportContent.includes('本報告只判單則回答文字；每次最多抽樣 20 則；code 不計入 200 字長度門檻，但完整保留在受評回答；未核對回答所述外部事實真偽。'), true)
  const receiptPath = receiptPathFor(fixture)
  assert.equal(modeFor(reportPath), 0o600)
  assert.equal(modeFor(receiptPath), 0o600)

  const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'))
  assert.equal(receipt.schema_version, 2)
  fs.writeFileSync(receiptPath, `${JSON.stringify({ ...receipt, challenge: 'f'.repeat(64) })}\n`)
  assert.equal(run({ ...fixture, mode: 'due' }).due, true)
  fs.writeFileSync(receiptPath, `${JSON.stringify({ ...receipt, sample_count: receipt.sample_count + 1 })}\n`)
  assert.equal(run({ ...fixture, mode: 'due' }).due, true)
  fs.writeFileSync(receiptPath, `${JSON.stringify(receipt)}\n`)
  assert.equal(run({ ...fixture, mode: 'due' }).due, false)

  fs.appendFileSync(reportPath, '\nchanged\n')
  assert.equal(run({ ...fixture, mode: 'due' }).due, true)
  fs.writeFileSync(reportPath, reportContent)
  assert.equal(run({ ...fixture, mode: 'due' }).due, false)
  const manifestEdited = JSON.parse(manifestBefore)
  manifestEdited.eligible += 1
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifestEdited)}\n`)
  assert.equal(run({ ...fixture, mode: 'due' }).due, true)
})

test('v2 receipt invalidates when samples text changes or disappears', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
    text: repeat('s', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'receipt-v2-session',
  })])
  run(fixture)
  const audit = auditFor(samplesFor(fixture), [[{ type: 'unsourced-completion', quote: 'sssss' }]])
  assert.equal(run({ ...fixture, mode: 'finalize', audit, reauditNonce: '0' }).ok, true)
  assert.equal(run({ ...fixture, mode: 'due' }).due, false)

  const samplesTextPath = samplesTextPathFor(fixture)
  const samplesText = fs.readFileSync(samplesTextPath)
  fs.appendFileSync(samplesTextPath, 'x')
  assert.equal(run({ ...fixture, mode: 'due' }).due, true)
  fs.writeFileSync(samplesTextPath, samplesText)
  assert.equal(run({ ...fixture, mode: 'due' }).due, false)
  fs.rmSync(samplesTextPath)
  assert.equal(run({ ...fixture, mode: 'due' }).due, true)
})

test('new pre-cutoff v2 packet cannot downgrade while version commitment remains', () => {
  const fixture = makeFixture()
  const date = '2026-08-13'
  writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
    text: repeat('g', 220),
    timestamp: '2026-08-13T01:00:00.000Z',
    sessionId: 'full-downgrade-session',
  })])
  run({ ...fixture, date })
  const audit = auditFor(samplesFor(fixture, date), [[{ type: 'unsourced-completion', quote: 'ggggg' }]])
  assert.equal(run({ ...fixture, date, mode: 'finalize', audit }).ok, true)
  const manifestPath = manifestPathFor(fixture, date)
  const publicationPath = publicationPathFor(fixture, date)
  const receiptPath = receiptPathFor(fixture, date)
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  const publication = JSON.parse(fs.readFileSync(publicationPath, 'utf8'))
  const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'))
  delete manifest.schema_version
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`)
  delete publication.schema_version
  delete publication.top_violations
  fs.writeFileSync(publicationPath, `${JSON.stringify(publication)}\n`)
  delete receipt.schema_version
  delete receipt.top_violations
  fs.writeFileSync(receiptPath, `${JSON.stringify(receipt)}\n`)
  fs.rmSync(samplesTextPathFor(fixture, date))

  assert.equal(fs.existsSync(versionPathFor(fixture, date)), true)
  assert.equal(run({ ...fixture, date, mode: 'due' }).due, true)
})

test('version commitment mismatch bad permissions and missing new v2 are rejected', () => {
  for (const mutation of ['mismatch', 'permissions', 'missing']) {
    const fixture = makeFixture()
    writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
      text: repeat('c', 220),
      timestamp: '2026-08-14T01:00:00.000Z',
      sessionId: `commitment-${mutation}`,
    })])
    run(fixture)
    const versionPath = versionPathFor(fixture)
    if (mutation === 'mismatch') {
      const version = JSON.parse(fs.readFileSync(versionPath, 'utf8'))
      fs.writeFileSync(versionPath, `${JSON.stringify({ ...version, date: '2026-08-13' })}\n`)
    }
    if (mutation === 'permissions') fs.chmodSync(versionPath, 0o644)
    if (mutation === 'missing') fs.rmSync(versionPath)
    assert.equal(run({ ...fixture, mode: 'due' }).due, true, mutation)
  }
})

test('schema_version null is rejected for v2 manifests publications and receipts', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
    text: repeat('n', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'null-version-session',
  })])
  run(fixture)
  const manifestPath = manifestPathFor(fixture)
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
  manifest.schema_version = null
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`)
  assert.equal(run({ ...fixture, mode: 'due' }).due, true)
})

test('v2 packet cannot downgrade to v1 after samples text disappears', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
    text: repeat('d', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'receipt-downgrade-session',
  })])
  run(fixture)
  const audit = auditFor(samplesFor(fixture), [[{ type: 'unsourced-completion', quote: 'ddddd' }]])
  assert.equal(run({ ...fixture, mode: 'finalize', audit }).ok, true)
  const receiptPath = receiptPathFor(fixture)
  const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'))
  delete receipt.schema_version
  delete receipt.top_violations
  fs.writeFileSync(receiptPath, `${JSON.stringify(receipt)}\n`)
  fs.rmSync(samplesTextPathFor(fixture))

  assert.equal(run({ ...fixture, mode: 'due' }).due, true)
})

test('pre-cutoff markerless v1 manifest that still carries manifest_hash can finish publication', () => {
  const fixture = makeFixture()
  const date = '2026-08-13'
  fs.chmodSync(fixture.reports, 0o700)
  const sample = {
    session: 'legacy-finalize-session',
    path: '/tmp/legacy-finalize.jsonl',
    timestamp: '2026-08-13T01:00:00.000Z',
    row_index: 0,
    answer: repeat('l', 220),
  }
  const manifestPayload = { date, eligible: 1, samples: [sample], challenge: 'b'.repeat(64) }
  const manifest = { ...manifestPayload, manifest_hash: sha256(JSON.stringify(manifestPayload)) }
  fs.writeFileSync(manifestPathFor(fixture, date), `${JSON.stringify(manifest)}\n`, { mode: 0o600 })
  const samplesText = [
    `=== BEGIN SAMPLE 1/1 [${manifest.challenge.slice(0, 16)}] ===`,
    `timestamp: ${sample.timestamp}`,
    `session: ${sample.session}`,
    `path: ${sample.path}`,
    'answer:',
    sample.answer,
    `=== END SAMPLE 1/1 [${manifest.challenge.slice(0, 16)}] ===`,
    '',
  ].join('\n')
  fs.writeFileSync(samplesTextPathFor(fixture, date), samplesText, { mode: 0o600 })
  const finalized = run({
    ...fixture,
    date,
    mode: 'finalize',
    audit: auditFor([sample], [[{ type: 'unsourced-number', quote: 'lllll' }]]),
  })

  assert.equal(finalized.ok, true)
  assert.deepEqual(finalized.top_violations, [{ type: 'unsourced-number', count: 1 }])
  assert.equal(Object.hasOwn(JSON.parse(fs.readFileSync(publicationPathFor(fixture, date), 'utf8')), 'schema_version'), false)
  assert.equal(run({ ...fixture, date, mode: 'due' }).due, false)
})

test('pre-cutoff markerless v1 packet written with digest fields remains verified', () => {
  const fixture = makeFixture()
  const date = '2026-08-13'
  const manifestPath = manifestPathFor(fixture, date)
  const publicationPath = publicationPathFor({ ...fixture, reports: fixture.reports }, date)
  const receiptPath = receiptPathFor({ ...fixture, reports: fixture.reports }, date)
  const reportPath = reportPathFor({ ...fixture, reports: fixture.reports }, date)
  fs.chmodSync(fixture.reports, 0o700)
  const manifestPayload = { date, eligible: 0, samples: [], challenge: 'a'.repeat(64) }
  const manifest = { ...manifestPayload, manifest_hash: sha256(JSON.stringify(manifestPayload)) }
  fs.writeFileSync(manifestPath, `${JSON.stringify(manifest)}\n`, { mode: 0o600 })
  const report = 'legacy report\n'
  const publication = {
    date,
    manifest_sha256: sha256(fs.readFileSync(manifestPath)),
    samples_sha256: sha256(JSON.stringify([])),
    report,
    report_sha256: sha256(report),
    eligible: 0,
    sample_count: 0,
    tp_style_violation_count: 0,
    challenge: manifest.challenge,
  }
  fs.writeFileSync(publicationPath, `${JSON.stringify(publication)}\n`, { mode: 0o600 })
  fs.writeFileSync(reportPath, report, { mode: 0o600 })
  const receipt = {
    date,
    report_sha256: publication.report_sha256,
    manifest_sha256: publication.manifest_sha256,
    samples_sha256: publication.samples_sha256,
    publication_sha256: sha256(fs.readFileSync(publicationPath)),
    eligible: 0,
    sample_count: 0,
    tp_style_violation_count: 0,
    challenge: manifest.challenge,
  }
  fs.writeFileSync(receiptPath, `${JSON.stringify(receipt)}\n`, { mode: 0o600 })

  assert.equal(run({ ...fixture, date, mode: 'due' }).due, false)
})

test('concurrent finalizers are idempotent and return one verified challenge', async () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
    text: repeat('q', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'finalize-session',
  })])
  const sampled = run(fixture)
  const audit = auditFor(samplesFor(fixture), [[{ type: 'unsourced-completion', quote: 'qqqqq' }]])

  const packets = await Promise.all(Array.from({ length: 12 }, () => runAsync({ ...fixture, mode: 'finalize', audit })))
  assert.equal(packets.every((packet) => packet.ok), true)
  assert.equal(new Set(packets.map((packet) => packet.challenge)).size, 1)
  assert.equal(packets[0].challenge, sampled.challenge)
  assert.equal(run({ ...fixture, mode: 'due' }).due, false)
  assert.equal(run({ ...fixture, mode: 'finalize', audit: { rows: [] } }).ok, true)
  assert.equal(run({ ...fixture, mode: 'due' }).due, false)

  const reportPath = reportPathFor(fixture)
  const receiptPath = receiptPathFor(fixture)
  const expectedReport = fs.readFileSync(reportPath, 'utf8')
  fs.writeFileSync(reportPath, 'corrupt report')
  fs.rmSync(receiptPath)
  const recovered = run({ ...fixture, mode: 'finalize', audit: { rows: [] } })
  assert.equal(recovered.ok, true)
  assert.equal(fs.readFileSync(reportPath, 'utf8'), expectedReport)
  assert.equal(fs.existsSync(receiptPath), true)
  assert.equal(run({ ...fixture, mode: 'due' }).due, false)
})

test('conflicting concurrent finalizers publish one atomic first-wins report without touching stale locks', async () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
    text: repeat('r', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'conflicting-finalizer-session',
  })])
  const sampled = run(fixture)
  const samples = samplesFor(fixture)
  const numberAudit = auditFor(samples, [[{ type: 'unsourced-number', quote: 'rrrrr' }]])
  const completionAudit = auditFor(samples, [[{ type: 'unsourced-completion', quote: 'rrrrr' }]])
  const staleLock = path.join(fixture.reports, '2026-08-14-evidence-level.finalize.lock')
  fs.writeFileSync(staleLock, `${JSON.stringify({ pid: 999999 })}\n`, { mode: 0o600 })
  fs.utimesSync(staleLock, new Date('2020-01-01T00:00:00Z'), new Date('2020-01-01T00:00:00Z'))

  const packets = await Promise.all(Array.from({ length: 20 }, (_, index) =>
    runAsync({ ...fixture, mode: 'finalize', audit: index % 2 === 0 ? numberAudit : completionAudit })
  ))
  const counts = new Set(packets.map((packet) => packet.tp_style_violation_count))
  const publication = JSON.parse(fs.readFileSync(publicationPathFor(fixture), 'utf8'))
  const report = fs.readFileSync(reportPathFor(fixture), 'utf8')

  assert.equal(packets.every((packet) => packet.ok), true)
  assert.equal(counts.size, 1)
  assert.equal(publication.tp_style_violation_count, packets[0].tp_style_violation_count)
  assert.equal(report, publication.report)
  assert.equal(fs.existsSync(staleLock), true)
  assert.equal(modeFor(publicationPathFor(fixture)), 0o600)
  assert.equal(run({ ...fixture, mode: 'due' }).due, false)
})

test('uses report filename dates for the seven-day due boundary', () => {
  const fixture = makeFixture()
  fs.writeFileSync(path.join(fixture.reports, '2026-07-30-evidence-level.md'), 'partial report')
  fs.writeFileSync(path.join(fixture.reports, '2026-08-01-evidence-level.md'), 'unverified report')
  run({ ...fixture, date: '2026-07-31', mode: 'sample' })
  const finalized = run({ ...fixture, date: '2026-07-31', mode: 'finalize', audit: auditFor(samplesFor(fixture, '2026-07-31')) })
  assert.equal(finalized.ok, true)
  fs.utimesSync(path.join(fixture.reports, '2026-07-31-evidence-level.md'), new Date('2020-01-01T00:00:00Z'), new Date('2020-01-01T00:00:00Z'))

  const sixDays = run({ ...fixture, date: '2026-08-06', mode: 'due' })
  const sevenDays = run({ ...fixture, date: '2026-08-07', mode: 'due' })
  assert.deepEqual(sixDays, {
    date: '2026-08-06',
    due: false,
    last_success_date: '2026-07-31',
    days_since: 6,
  })
  assert.deepEqual(sevenDays, {
    date: '2026-08-07',
    due: true,
    last_success_date: '2026-07-31',
    days_since: 7,
  })

  fs.rmSync(path.join(fixture.reports, '2026-07-31-evidence-level.md'))
  assert.deepEqual(run({ ...fixture, date: '2026-08-07', mode: 'due' }), {
    date: '2026-08-07',
    due: true,
    last_success_date: null,
    days_since: null,
  })
})

test('prepare-reaudit writes only primary PASS samples with a distinct nonce', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answers.jsonl'), [
    assistant({ text: repeat('a', 220), timestamp: '2026-08-14T01:00:00.000Z', sessionId: 'pass-session' }),
    assistant({ text: repeat('b', 220), timestamp: '2026-08-14T02:00:00.000Z', sessionId: 'fail-session' }),
  ])
  const sampled = run(fixture)
  const samples = samplesFor(fixture)
  const primaryAudit = auditFor(samples, [[], [{ type: 'unsourced-number', quote: 'bbbbb' }]], sampled.audit_nonce)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  writeAuditTranscript({ directory: wfDir, samplesPath: samplesTextPathFor(fixture), samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'), audit: primaryAudit })

  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce })
  const subsetText = fs.readFileSync(reauditSamplesTextPathFor(fixture), 'utf8')
  assert.equal(prepared.reaudit_sample_count, 1)
  assert.notEqual(prepared.reaudit_nonce, sampled.audit_nonce)
  assert.deepEqual(Object.keys(prepared).sort(), ['date', 'reaudit_nonce', 'reaudit_sample_count'])
  assert.equal(subsetText.includes('pass-session'), true)
  assert.equal(subsetText.includes('fail-session'), false)
})

test('prepare-reaudit accepts zero-based Read results', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answers.jsonl'), [assistant({
    text: repeat('z', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'zero-based-read-session',
  })])
  const sampled = run(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  const samplesText = fs.readFileSync(samplesTextPathFor(fixture), 'utf8')
  writeAuditTranscript({
    directory: wfDir,
    samplesPath: samplesTextPathFor(fixture),
    samplesText,
    audit: auditFor(samplesFor(fixture), [], sampled.audit_nonce),
    chunks: [{ offset: 0, text: samplesText }],
  })

  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce })
  assert.equal(prepared.reaudit_sample_count, 1)
})

test('v2 finalize rejects primary PASS rows when reaudit is omitted', () => {
  for (const source of ['transcript', 'base64']) {
    const fixture = makeFixture()
    writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
      text: repeat('p', 220),
      timestamp: '2026-08-14T01:00:00.000Z',
      sessionId: `missing-reaudit-${source}`,
    })])
    const sampled = run(fixture)
    const samples = samplesFor(fixture)
    const audit = auditFor(samples, [], sampled.audit_nonce)
    let finalized
    if (source === 'transcript') {
      const wfDir = path.join(fixture.reports, 'wf-transcripts')
      fs.mkdirSync(wfDir, { recursive: true })
      writeAuditTranscript({ directory: wfDir, samplesPath: samplesTextPathFor(fixture), samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'), audit })
      finalized = run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce })
    } else {
      finalized = run({ ...fixture, mode: 'finalize', audit, auditNonce: sampled.audit_nonce })
    }
    assert.equal(finalized.ok, false, source)
    assert.equal(fs.existsSync(publicationPathFor(fixture)), false, source)
  }
})

test('repeated preparer keeps the first subset artifact stable', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
    text: repeat('r', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'stable-reaudit-session',
  })])
  const sampled = run(fixture)
  const samples = samplesFor(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  writeAuditTranscript({ directory: wfDir, samplesPath: samplesTextPathFor(fixture), samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'), audit: auditFor(samples, [], sampled.audit_nonce) })

  const first = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce })
  const firstText = fs.readFileSync(reauditSamplesTextPathFor(fixture), 'utf8')
  const second = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce })
  assert.deepEqual(second, first)
  assert.equal(fs.readFileSync(reauditSamplesTextPathFor(fixture), 'utf8'), firstText)
})

test('finalize merges PASS-only reaudit and binds the subset nonce into publication and receipt', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answers.jsonl'), [
    assistant({ text: repeat('a', 220), timestamp: '2026-08-14T01:00:00.000Z', sessionId: 'primary-fail' }),
    assistant({ text: repeat('b', 220), timestamp: '2026-08-14T02:00:00.000Z', sessionId: 'reaudit-fail' }),
    assistant({ text: repeat('c', 220), timestamp: '2026-08-14T03:00:00.000Z', sessionId: 'both-pass' }),
  ])
  const sampled = run(fixture)
  const samples = samplesFor(fixture)
  const primaryAudit = auditFor(samples, [
    [{ type: 'unsourced-number', quote: 'aaaaa' }],
    [],
    [],
  ], sampled.audit_nonce)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  writeAuditTranscript({ directory: wfDir, name: 'agent-primary.jsonl', samplesPath: samplesTextPathFor(fixture), samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'), audit: primaryAudit })
  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce })
  const subsetSamples = [samples[1], samples[2]]
  const secondAudit = auditFor(subsetSamples, [[{ type: 'doc-as-evidence', quote: 'bbbbb' }], []], prepared.reaudit_nonce)
  writeAuditTranscript({ directory: wfDir, name: 'agent-reaudit.jsonl', samplesPath: reauditSamplesTextPathFor(fixture), samplesText: fs.readFileSync(reauditSamplesTextPathFor(fixture), 'utf8'), audit: secondAudit })

  const finalized = run({
    ...fixture,
    mode: 'finalize',
    auditTranscripts: wfDir,
    auditNonce: sampled.audit_nonce,
    attemptNonce: sampled.attempt_nonce,
    reauditNonce: prepared.reaudit_nonce,
  })
  assert.equal(finalized.ok, true)
  assert.equal(finalized.tp_style_violation_count, 2)
  assert.deepEqual(finalized.top_violations, [
    { type: 'doc-as-evidence', count: 1 },
    { type: 'unsourced-number', count: 1 },
  ])
  const publication = JSON.parse(fs.readFileSync(publicationPathFor(fixture), 'utf8'))
  const receipt = JSON.parse(fs.readFileSync(receiptPathFor(fixture), 'utf8'))
  assert.equal(publication.reaudit_sample_count, 2)
  assert.equal(publication.reaudit_nonce, prepared.reaudit_nonce)
  assert.equal(receipt.reaudit_sample_count, 2)
  assert.equal(receipt.reaudit_nonce, prepared.reaudit_nonce)
})

test('finalize rejects wrong reaudit nonce path and cross-transcript evidence', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
    text: repeat('v', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'reaudit-closed-session',
  })])
  const sampled = run(fixture)
  const samples = samplesFor(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  writeAuditTranscript({ directory: wfDir, name: 'agent-primary.jsonl', samplesPath: samplesTextPathFor(fixture), samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'), audit: auditFor(samples, [], sampled.audit_nonce) })
  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce })
  writeAuditTranscript({ directory: wfDir, name: 'agent-wrong-path.jsonl', samplesPath: samplesTextPathFor(fixture), samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'), audit: auditFor(samples, [], prepared.reaudit_nonce) })
  assert.equal(run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, reauditNonce: prepared.reaudit_nonce }).ok, false)

  fs.rmSync(path.join(wfDir, 'agent-wrong-path.jsonl'))
  writeAuditTranscript({ directory: wfDir, name: 'agent-reaudit-read.jsonl', samplesPath: reauditSamplesTextPathFor(fixture), samplesText: fs.readFileSync(reauditSamplesTextPathFor(fixture), 'utf8'), audit: auditFor(samples, [], prepared.reaudit_nonce), includeOutput: false })
  writeAuditTranscript({ directory: wfDir, name: 'agent-reaudit-output.jsonl', samplesPath: reauditSamplesTextPathFor(fixture), samplesText: '', audit: auditFor(samples, [], prepared.reaudit_nonce), includeRead: false })
  assert.equal(run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, reauditNonce: prepared.reaudit_nonce }).ok, false)
})

test('finalize binds explicit null and zero reaudit fields when primary has no PASS rows', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
    text: repeat('f', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'all-primary-fail',
  })])
  const sampled = run(fixture)
  const samples = samplesFor(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  writeAuditTranscript({ directory: wfDir, samplesPath: samplesTextPathFor(fixture), samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'), audit: auditFor(samples, [[{ type: 'silent-skip', quote: 'fffff' }]], sampled.audit_nonce) })
  const finalized = run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, reauditNonce: '0' })
  assert.equal(finalized.ok, true)
  const publication = JSON.parse(fs.readFileSync(publicationPathFor(fixture), 'utf8'))
  const receipt = JSON.parse(fs.readFileSync(receiptPathFor(fixture), 'utf8'))
  assert.equal(publication.reaudit_sample_count, 0)
  assert.equal(publication.reaudit_nonce, null)
  assert.equal(receipt.reaudit_sample_count, 0)
  assert.equal(receipt.reaudit_nonce, null)
})

test('finalize binds audit rows to the exact samples text read in the same transcript', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'first.jsonl'), [assistant({
    text: repeat('v', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'first-session',
  })])
  run(fixture)
  const samples = samplesFor(fixture)
  const validAudit = auditFor(samples, [[{ type: 'unsourced-number', quote: 'vvvvv' }]])
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  fs.writeFileSync(path.join(wfDir, 'agent-scan.jsonl'), `${JSON.stringify({
    message: { content: [{ type: 'tool_use', name: 'StructuredOutput', input: { ok: true, silent: false } }] },
  })}\n`)
  writeAuditTranscript({
    directory: wfDir,
    samplesPath: samplesTextPathFor(fixture),
    samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'),
    audit: validAudit,
  })
  const finalized = run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir })
  assert.equal(finalized.ok, true)
  assert.equal(finalized.tp_style_violation_count, 1)

  const conflicting = spawnSync(process.execPath, argsFor({
    ...fixture,
    mode: 'finalize',
    auditTranscripts: wfDir,
    audit: validAudit,
  }), { encoding: 'utf8' })
  assert.notEqual(conflicting.status, 0)
})

test('finalize rejects transcript read content that differs from the manifest samples', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'first.jsonl'), [assistant({
    text: repeat('v', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'tampered-read-session',
  })])
  run(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  writeAuditTranscript({
    directory: wfDir,
    samplesPath: samplesTextPathFor(fixture),
    samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8').replace(/v/g, 'x'),
    audit: auditFor(samplesFor(fixture)),
  })

  assert.equal(run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir }).ok, false)
})

test('finalize rejects an audit transcript that reads any other path', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'first.jsonl'), [assistant({
    text: repeat('v', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'extra-read-session',
  })])
  run(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  writeAuditTranscript({
    directory: wfDir,
    samplesPath: samplesTextPathFor(fixture),
    samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'),
    audit: auditFor(samplesFor(fixture)),
    extraTool: { type: 'tool_use', name: 'Read', id: 'extra-read', input: { file_path: '/tmp/other.txt' } },
  })

  assert.equal(run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir }).ok, false)
})

test('finalize skips a newer wrong-nonce transcript and selects the matching run', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'first.jsonl'), [assistant({
    text: repeat('v', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'nonce-selection-session',
  })])
  run(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  const samplesText = fs.readFileSync(samplesTextPathFor(fixture), 'utf8')
  writeAuditTranscript({ directory: wfDir, name: 'agent-correct.jsonl', samplesPath: samplesTextPathFor(fixture), samplesText, audit: auditFor(samplesFor(fixture)) })
  writeAuditTranscript({ directory: wfDir, name: 'agent-wrong.jsonl', samplesPath: samplesTextPathFor(fixture), samplesText, audit: auditFor(samplesFor(fixture), [], '8'.repeat(64)) })
  fs.utimesSync(path.join(wfDir, 'agent-wrong.jsonl'), new Date(), new Date())

  assert.equal(run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir }).reaudit_sample_count, 1)
})

test('finalize rejects Read and StructuredOutput split across transcripts', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'first.jsonl'), [assistant({
    text: repeat('v', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'split-transcript-session',
  })])
  run(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  writeAuditTranscript({ directory: wfDir, name: 'agent-read.jsonl', samplesPath: samplesTextPathFor(fixture), samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'), audit: auditFor(samplesFor(fixture)), includeOutput: false })
  writeAuditTranscript({ directory: wfDir, name: 'agent-output.jsonl', samplesPath: samplesTextPathFor(fixture), samplesText: '', audit: auditFor(samplesFor(fixture)), includeRead: false })

  assert.equal(run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir }).ok, false)
})

test('finalize accepts complete consecutive paginated Read results', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'first.jsonl'), [assistant({
    text: repeat('v', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'paginated-read-session',
  })])
  run(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  const lines = fs.readFileSync(samplesTextPathFor(fixture), 'utf8').split('\n')
  const split = Math.floor(lines.length / 2)
  writeAuditTranscript({
    directory: wfDir,
    samplesPath: samplesTextPathFor(fixture),
    samplesText: '',
    audit: auditFor(samplesFor(fixture)),
    chunks: [
      { offset: 1, limit: split, text: lines.slice(0, split).join('\n') },
      { offset: Math.max(1, split - 1), limit: lines.length - split + 2, text: lines.slice(Math.max(0, split - 2)).join('\n') },
    ],
  })

  assert.equal(run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir }).reaudit_sample_count, 1)
})

test('finalize accepts literal ellipsis and truncated words inside samples', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'first.jsonl'), [assistant({
    text: `${repeat('v', 210)} … user wrote truncated here`,
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'literal-truncated-session',
  })])
  run(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  writeAuditTranscript({ directory: wfDir, samplesPath: samplesTextPathFor(fixture), samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'), audit: auditFor(samplesFor(fixture)) })

  assert.equal(run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir }).reaudit_sample_count, 1)
})

test('finalize rejects StructuredOutput emitted before Read results', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'first.jsonl'), [assistant({
    text: repeat('v', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'early-output-session',
  })])
  run(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  const rows = [
    { message: { content: [{ type: 'tool_use', name: 'StructuredOutput', input: auditFor(samplesFor(fixture)) }] } },
    { message: { content: [{ type: 'tool_use', name: 'Read', id: 'read-1', input: { file_path: samplesTextPathFor(fixture) } }] } },
    { message: { content: [{ type: 'tool_result', tool_use_id: 'read-1', content: readResultText(fs.readFileSync(samplesTextPathFor(fixture), 'utf8')) }] } },
  ]
  fs.writeFileSync(path.join(wfDir, 'agent-audit.jsonl'), `${rows.map((row) => JSON.stringify(row)).join('\n')}\n`)

  assert.equal(run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir }).ok, false)
})

test('finalize rejects truncated Read tool results', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'first.jsonl'), [assistant({
    text: repeat('v', 220),
    timestamp: '2026-08-14T01:00:00.000Z',
    sessionId: 'truncated-read-session',
  })])
  run(fixture)
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  const samplesText = fs.readFileSync(samplesTextPathFor(fixture), 'utf8')
  writeAuditTranscript({ directory: wfDir, samplesPath: samplesTextPathFor(fixture), samplesText: samplesText.slice(0, -10), audit: auditFor(samplesFor(fixture)) })

  assert.equal(run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir }).ok, false)
})

test('sample mode writes four five-row batches and finalizer merges their transcripts', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'twenty.jsonl'), Array.from({ length: 20 }, (_, index) => assistant({
    text: repeat(String.fromCharCode(97 + index), 220),
    timestamp: `2026-08-14T${String(index + 1).padStart(2, '0')}:00:00.000Z`,
    sessionId: `batch-session-${index + 1}`,
  })))

  const sampled = run(fixture)
  const manifest = JSON.parse(fs.readFileSync(manifestPathFor(fixture), 'utf8'))
  const samples = manifest.samples
  const expectedRanges = [
    { start: 1, end: 5 },
    { start: 6, end: 10 },
    { start: 11, end: 15 },
    { start: 16, end: 20 },
  ]
  assert.equal(sampled.sample_count, 20)
  assert.equal(manifest.audit_nonce, sampled.audit_nonce)
  assert.deepEqual(manifest.batches.map((batch) => batch.range), expectedRanges)
  assert.deepEqual(manifest.batches.map((batch) => batch.index), [1, 2, 3, 4])
  assert.equal(new Set(manifest.batches.map((batch) => batch.path)).size, 4)
  assert.equal(manifest.batches.every((batch) => batch.audit_nonce === sampled.audit_nonce), true)

  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(wfDir, { recursive: true })
  manifest.batches.forEach((batch, index) => {
    assert.equal(fs.existsSync(batch.path), true)
    assert.equal(modeFor(batch.path), 0o600)
    assert.equal(fs.readFileSync(batch.path, 'utf8').startsWith(`=== BEGIN SAMPLE ${batch.range.start}/20 [${manifest.challenge.slice(0, 16)}] ===`), true)
    const batchSamples = samples.slice(index * 5, index * 5 + 5)
    const audit = auditFor(batchSamples, batchSamples.map((sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]), sampled.audit_nonce)
    writeBatchAuditTranscript({
      directory: wfDir,
      name: `agent-batch-${batch.index}.jsonl`,
      batch,
      samplesText: fs.readFileSync(batch.path, 'utf8'),
      audit,
      attemptNonce: sampled.attempt_nonce,
    })
  })

  const finalized = run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  assert.equal(finalized.ok, true)
  assert.equal(finalized.sample_count, 20)
  const report = fs.readFileSync(reportPathFor(fixture), 'utf8')
  const reportRows = report.split('\n').filter((line) => line.startsWith('| 2026-08-14T'))
  assert.equal(reportRows.length, 20)
  assert.deepEqual(reportRows.map((line) => line.split(' | ')[1]), samples.map((sample) => sample.session))
  const publication = JSON.parse(fs.readFileSync(publicationPathFor(fixture), 'utf8'))
  const receipt = JSON.parse(fs.readFileSync(receiptPathFor(fixture), 'utf8'))
  assert.equal(publication.sample_count, 20)
  assert.equal(receipt.sample_count, 20)
  assert.equal(receipt.audit_nonce, sampled.audit_nonce)
})

test('finalizer ignores large and malformed historical transcripts', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
  const historicalDuplicate = path.join(wfDir, 'agent-history-batch-1.jsonl')
  const batch = manifest.batches[0]
  const batchSamples = manifest.samples.slice(0, 5)
  writeBatchAuditTranscript({
    directory: wfDir,
    name: 'agent-history-batch-1.jsonl',
    batch,
    samplesText: fs.readFileSync(batch.path, 'utf8'),
    audit: auditFor(batchSamples, batchSamples.map((sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]), sampled.audit_nonce),
    attemptNonce: sampled.attempt_nonce,
  })
  fs.appendFileSync(historicalDuplicate, `${JSON.stringify({ message: { content: [{ type: 'text', text: 'historical' }] } })}\n`.repeat(20000))
  const historicalMalformed = path.join(wfDir, 'agent-history-malformed.jsonl')
  fs.writeFileSync(historicalMalformed, 'not-json\n')
  const oldTime = new Date(fs.statSync(samplesTextPathFor(fixture)).mtimeMs - 60000)
  fs.utimesSync(historicalDuplicate, oldTime, oldTime)
  fs.utimesSync(historicalMalformed, oldTime, oldTime)

  const finalized = run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  assert.equal(finalized.ok, true)
})

test('finalizer rejects a missing primary batch without publishing a report', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
  fs.rmSync(path.join(wfDir, 'agent-batch-4.jsonl'))

  assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }))
})

test('prepare-reaudit ignores oversized transcripts from another workflow directory', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const transcriptsRoot = path.join(fixture.reports, 'transcripts')
  const wfDir = path.join(transcriptsRoot, 'current-workflow')
  const unrelatedDir = path.join(transcriptsRoot, 'unrelated-workflow')
  const stringContentDir = path.join(transcriptsRoot, 'string-content-workflow')
  const findings = manifest.batches.map((_, batchIndex) => Array.from({ length: 5 }, (_, rowIndex) => {
    const sampleIndex = batchIndex * 5 + rowIndex
    return sampleIndex === 0
      ? []
      : [{ type: 'unsourced-number', quote: manifest.samples[sampleIndex].answer.slice(0, 5) }]
  }))
  writeValidBatchTranscripts({ fixture, sampled, manifest, directory: wfDir, findings })
  fs.mkdirSync(unrelatedDir, { recursive: true })
  fs.mkdirSync(stringContentDir, { recursive: true })
  fs.writeFileSync(path.join(unrelatedDir, 'agent-unrelated.jsonl'), `${'x'.repeat(TRANSCRIPT_MAX_BYTES)}\n`)
  fs.writeFileSync(path.join(stringContentDir, 'agent-string-content.jsonl'), `${JSON.stringify({ message: { content: 'plain text' } })}\n`)

  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: transcriptsRoot, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  assert.equal(prepared.reaudit_sample_count, 1)
})

test('prepare-reaudit ignores too many transcripts from another workflow directory', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const transcriptsRoot = path.join(fixture.reports, 'transcripts')
  const wfDir = path.join(transcriptsRoot, 'current-workflow')
  const unrelatedDir = path.join(transcriptsRoot, 'unrelated-workflow')
  const findings = manifest.batches.map((_, batchIndex) => Array.from({ length: 5 }, (_, rowIndex) => {
    const sampleIndex = batchIndex * 5 + rowIndex
    return sampleIndex === 0
      ? []
      : [{ type: 'unsourced-number', quote: manifest.samples[sampleIndex].answer.slice(0, 5) }]
  }))
  writeValidBatchTranscripts({ fixture, sampled, manifest, directory: wfDir, findings })
  fs.mkdirSync(unrelatedDir, { recursive: true })
  for (let index = 0; index <= TRANSCRIPT_MAX_FILES; index += 1) {
    fs.writeFileSync(path.join(unrelatedDir, `agent-unrelated-${index}.jsonl`), `${JSON.stringify({ message: { content: 'plain text' } })}\n`)
  }

  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: transcriptsRoot, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  assert.equal(prepared.reaudit_sample_count, 1)
})

test('prepare-reaudit accepts StructuredOutput success receipts', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const findings = manifest.batches.map((_, batchIndex) => Array.from({ length: 5 }, (_, rowIndex) => {
    const sampleIndex = batchIndex * 5 + rowIndex
    return sampleIndex === 0
      ? []
      : [{ type: 'unsourced-number', quote: manifest.samples[sampleIndex].answer.slice(0, 5) }]
  }))
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, findings, includeOutputResult: true })

  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  assert.equal(prepared.reaudit_sample_count, 1)
})

test('finalizer canonicalizes markdown-stripped finding quotes to exact source lines', () => {
  const fixture = makeFixture()
  const canonicalLine = '- `✓` 13 commits are traced. | note'
  writeRows(path.join(fixture.project, 'markdown-quotes.jsonl'), Array.from({ length: 20 }, (_, index) => assistant({
    text: index === 0 ? `${canonicalLine}\n${repeat('a', 220)}` : repeat(String.fromCharCode(98 + index), 220),
    timestamp: `2026-08-14T${String(index + 1).padStart(2, '0')}:00:00.000Z`,
    sessionId: `markdown-session-${index + 1}`,
  })))
  const sampled = run(fixture)
  const manifest = JSON.parse(fs.readFileSync(manifestPathFor(fixture), 'utf8'))
  const findings = manifest.batches.map((_, batchIndex) => Array.from({ length: 5 }, (_, rowIndex) => {
    const sampleIndex = batchIndex * 5 + rowIndex
    return [{ type: 'unsourced-number', quote: sampleIndex === 0 ? '✓ 13 commits are traced.' : manifest.samples[sampleIndex].answer.slice(0, 5) }]
  }))
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, findings, includeOutputResult: true })

  const finalized = run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  assert.equal(finalized.ok, true)
  assert.equal(fs.readFileSync(reportPathFor(fixture), 'utf8').includes(canonicalLine.split('|')[0].trim()), true)
})

test('finalizer does not collapse literal identifier punctuation in finding quotes', () => {
  const fixture = makeFixture()
  writeRows(path.join(fixture.project, 'identifier-quotes.jsonl'), Array.from({ length: 20 }, (_, index) => assistant({
    text: index === 0 ? `foo_bar is a literal identifier.\n${repeat('a', 220)}` : repeat(String.fromCharCode(98 + index), 220),
    timestamp: `2026-08-14T${String(index + 1).padStart(2, '0')}:00:00.000Z`,
    sessionId: `identifier-session-${index + 1}`,
  })))
  const sampled = run(fixture)
  const manifest = JSON.parse(fs.readFileSync(manifestPathFor(fixture), 'utf8'))
  const findings = manifest.batches.map((_, batchIndex) => Array.from({ length: 5 }, (_, rowIndex) => {
    const sampleIndex = batchIndex * 5 + rowIndex
    return [{ type: 'unsourced-mechanism', quote: sampleIndex === 0 ? 'foobar is a literal identifier.' : manifest.samples[sampleIndex].answer.slice(0, 5) }]
  }))
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, findings, includeOutputResult: true })

  assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }))
})

test('finalizer rejects too many current transcript candidates', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
  const extra = `${JSON.stringify({ message: { content: [{ type: 'text', text: 'extra current transcript' }] } })}\n`
  for (let index = 0; index < TRANSCRIPT_MAX_FILES; index += 1) {
    fs.writeFileSync(path.join(wfDir, `agent-current-extra-${index}.jsonl`), extra)
  }

  assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }))
})

test('finalizer rejects an oversized current transcript candidate', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
  fs.rmSync(path.join(wfDir, 'agent-batch-1.jsonl'))
  const batch = manifest.batches[0]
  const oversizedPath = path.join(wfDir, 'agent-oversized-batch-1.jsonl')
  writeBatchAuditTranscript({
    directory: wfDir,
    name: 'agent-oversized-batch-1.jsonl',
    batch,
    samplesText: fs.readFileSync(batch.path, 'utf8'),
    audit: auditFor(manifest.samples.slice(0, 5), manifest.samples.slice(0, 5).map((sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]), sampled.audit_nonce),
    attemptNonce: sampled.attempt_nonce,
  })
  fs.appendFileSync(oversizedPath, `${'x'.repeat(TRANSCRIPT_MAX_BYTES)}\n`)

  assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }))
})

test('finalizer selects the newest valid packet for a duplicate current batch', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, namePrefix: 'agent-old-batch-' })
  const batch = manifest.batches[0]
  const batchSamples = manifest.samples.slice(0, 5)
  const newestPath = path.join(wfDir, 'agent-newest-batch-1.jsonl')
  writeBatchAuditTranscript({
    directory: wfDir,
    name: 'agent-newest-batch-1.jsonl',
    batch,
    samplesText: fs.readFileSync(batch.path, 'utf8'),
    audit: auditFor(batchSamples, batchSamples.map((sample) => [{ type: 'unsourced-completion', quote: sample.answer.slice(0, 5) }]), sampled.audit_nonce),
    attemptNonce: sampled.attempt_nonce,
  })
  const newestTime = new Date(fs.statSync(samplesTextPathFor(fixture)).mtimeMs + 60000)
  fs.utimesSync(newestPath, newestTime, newestTime)

  const finalized = run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  assert.equal(finalized.ok, true)
  assert.deepEqual(finalized.top_violations, [
    { type: 'unsourced-number', count: 15 },
    { type: 'unsourced-completion', count: 5 },
  ])
})

test('finalizer rejects a newest malformed current-attempt candidate instead of falling back', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, namePrefix: 'agent-old-batch-' })
  const newestPath = path.join(wfDir, 'agent-newest-batch-1.jsonl')
  fs.writeFileSync(newestPath, 'not-json\n')
  const newestTime = new Date(fs.statSync(samplesTextPathFor(fixture)).mtimeMs + 60000)
  fs.utimesSync(newestPath, newestTime, newestTime)

  assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }))
})

test('finalizer rejects a newest malformed packet with an older valid packet', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, namePrefix: 'agent-old-batch-' })
  const batch = manifest.batches[0]
  const batchSamples = manifest.samples.slice(0, 5)
  const malformedAudit = auditFor(batchSamples, batchSamples.map((sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]), sampled.audit_nonce)
  malformedAudit.rows[0].session = 'malformed-current-packet'
  const newestPath = path.join(wfDir, 'agent-newest-malformed-packet.jsonl')
  writeBatchAuditTranscript({
    directory: wfDir,
    name: 'agent-newest-malformed-packet.jsonl',
    batch,
    samplesText: fs.readFileSync(batch.path, 'utf8'),
    audit: malformedAudit,
    attemptNonce: sampled.attempt_nonce,
  })
  const newestTime = new Date(fs.statSync(samplesTextPathFor(fixture)).mtimeMs + 60000)
  fs.utimesSync(newestPath, newestTime, newestTime)

  assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }))
})

test('finalizer rejects duplicate, overlapping, stale, and malformed batch packets', () => {
  const cases = [
    { name: 'overlapping range', metadata: { range: { start: 5, end: 9 } } },
    { name: 'stale attempt nonce', metadata: { attempt_nonce: '6'.repeat(64) } },
    { name: 'wrong parent nonce', metadata: { audit_nonce: '8'.repeat(64) } },
    { name: 'wrong member identity', mutateRows: (rows) => { rows[0].session = 'wrong-session' } },
    { name: 'reordered rows', mutateRows: (rows) => { [rows[0], rows[1]] = [rows[1], rows[0]] } },
    { name: 'six rows', rowCount: 6 },
  ]

  for (const scenario of cases) {
    const { fixture, sampled, manifest } = makeTwentySampleFixture()
    const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
    const batch = manifest.batches[1]
    const sourceBatch = scenario.sourceBatchIndex == null ? batch : manifest.batches[scenario.sourceBatchIndex]
    const batchSamples = manifest.samples.slice(sourceBatch.range.start - 1, sourceBatch.range.end)
    const auditSamples = scenario.rowCount == null ? batchSamples : manifest.samples.slice(sourceBatch.range.start - 1, sourceBatch.range.start - 1 + scenario.rowCount)
    const audit = auditFor(auditSamples, auditSamples.map((sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]), sampled.audit_nonce)
    scenario.mutateRows?.(audit.rows)
    writeBatchAuditTranscript({
      directory: wfDir,
      name: scenario.name === 'duplicate index' ? 'agent-batch-duplicate-1.jsonl' : `agent-batch-${batch.index}.jsonl`,
      batch: sourceBatch,
      samplesText: fs.readFileSync(sourceBatch.path, 'utf8'),
      audit,
      metadata: { attempt_nonce: sampled.attempt_nonce, ...scenario.metadata },
    })

    assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }), scenario.name)
  }
})

test('finalizer rejects a wrong batch read, cross-transcript output, and disallowed tool call', () => {
  {
    const { fixture, sampled, manifest } = makeTwentySampleFixture()
    const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
    const batch = manifest.batches[0]
    const otherBatch = manifest.batches[1]
    const batchSamples = manifest.samples.slice(0, 5)
    const audit = auditFor(batchSamples, batchSamples.map((sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]), sampled.audit_nonce)
    const packet = {
      ...audit,
      attempt_nonce: sampled.attempt_nonce,
      batch_index: batch.index,
      range: batch.range,
    }
    writeAuditTranscript({
      directory: wfDir,
      name: 'agent-batch-1.jsonl',
      samplesPath: otherBatch.path,
      samplesText: fs.readFileSync(otherBatch.path, 'utf8'),
      audit: packet,
    })
    assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }), 'wrong batch read')
  }

  {
    const { fixture, sampled, manifest } = makeTwentySampleFixture()
    const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
    const batch = manifest.batches[0]
    const batchSamples = manifest.samples.slice(0, 5)
    const audit = auditFor(batchSamples, batchSamples.map((sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]), sampled.audit_nonce)
    const packet = {
      ...audit,
      attempt_nonce: sampled.attempt_nonce,
      batch_index: batch.index,
      range: batch.range,
    }
    fs.rmSync(path.join(wfDir, 'agent-batch-1.jsonl'))
    writeAuditTranscript({ directory: wfDir, name: 'agent-batch-1-read.jsonl', samplesPath: batch.path, samplesText: fs.readFileSync(batch.path, 'utf8'), audit: packet, includeOutput: false })
    writeAuditTranscript({ directory: wfDir, name: 'agent-batch-1-output.jsonl', samplesPath: batch.path, samplesText: '', audit: packet, includeRead: false })
    assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }), 'cross transcript')
  }

  {
    const { fixture, sampled, manifest } = makeTwentySampleFixture()
    const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
    const batch = manifest.batches[0]
    const batchSamples = manifest.samples.slice(0, 5)
    const audit = auditFor(batchSamples, batchSamples.map((sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]), sampled.audit_nonce)
    writeAuditTranscript({
      directory: wfDir,
      name: 'agent-batch-1.jsonl',
      samplesPath: batch.path,
      samplesText: fs.readFileSync(batch.path, 'utf8'),
      audit: {
        ...audit,
        attempt_nonce: sampled.attempt_nonce,
        batch_index: batch.index,
        range: batch.range,
      },
      extraTool: { type: 'tool_use', name: 'Bash', id: 'disallowed', input: { command: 'true' } },
    })
    assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }), 'disallowed tool')
  }
})

test('finalizer rejects server and tool-call-like content blocks', () => {
  for (const type of ['server_tool_use', 'tool_call', 'function_call', 'computer_use', 'mcp_tool_use']) {
    const { fixture, sampled, manifest } = makeTwentySampleFixture()
    const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
    const batch = manifest.batches[0]
    const batchSamples = manifest.samples.slice(0, 5)
    const audit = auditFor(batchSamples, batchSamples.map((sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]), sampled.audit_nonce)
    writeBatchAuditTranscript({
      directory: wfDir,
      name: 'agent-batch-1.jsonl',
      batch,
      samplesText: fs.readFileSync(batch.path, 'utf8'),
      audit,
      metadata: { attempt_nonce: sampled.attempt_nonce },
    })
    const transcriptPath = path.join(wfDir, 'agent-batch-1.jsonl')
    const transcript = fs.readFileSync(transcriptPath, 'utf8')
    const rows = transcript.split('\n').filter(Boolean).map((row) => JSON.parse(row))
    rows[0].message.content.push({ type, id: `disallowed-${type}`, name: 'Read', input: { file_path: batch.path } })
    fs.writeFileSync(transcriptPath, `${rows.map((row) => JSON.stringify(row)).join('\n')}\n`)

    assertUnverified(fixture, run({
      ...fixture,
      mode: 'finalize',
      auditTranscripts: wfDir,
      auditNonce: sampled.audit_nonce,
      attemptNonce: sampled.attempt_nonce,
    }), type)
  }
})

test('finalizer rejects error Read results in both transcript parsers', () => {
  {
    const { fixture, sampled, manifest } = makeTwentySampleFixture()
    const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
    const transcriptPath = path.join(wfDir, 'agent-batch-1.jsonl')
    const rows = fs.readFileSync(transcriptPath, 'utf8').split('\n').filter(Boolean).map((row) => JSON.parse(row))
    const resultRow = rows.find((row) => row.message?.content?.some((item) => item.type === 'tool_result'))
    resultRow.message.content[0].is_error = true
    fs.writeFileSync(transcriptPath, `${rows.map((row) => JSON.stringify(row)).join('\n')}\n`)

    assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }))
  }

  {
    const fixture = makeFixture()
    writeRows(path.join(fixture.project, 'answer.jsonl'), [assistant({
      text: repeat('e', 220),
      timestamp: '2026-08-14T01:00:00.000Z',
      sessionId: 'error-read-legacy-session',
    })])
    const sampled = run(fixture)
    const wfDir = path.join(fixture.reports, 'wf-transcripts')
    fs.mkdirSync(wfDir, { recursive: true })
    writeAuditTranscript({ directory: wfDir, samplesPath: samplesTextPathFor(fixture), samplesText: fs.readFileSync(samplesTextPathFor(fixture), 'utf8'), audit: auditFor(samplesFor(fixture), [], sampled.audit_nonce) })
    const transcriptPath = path.join(wfDir, 'agent-audit.jsonl')
    const rows = fs.readFileSync(transcriptPath, 'utf8').split('\n').filter(Boolean).map((row) => JSON.parse(row))
    const resultRow = rows.find((row) => row.message?.content?.some((item) => item.type === 'tool_result'))
    resultRow.message.content[0].is_error = true
    fs.writeFileSync(transcriptPath, `${rows.map((row) => JSON.stringify(row)).join('\n')}\n`)

    assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce }))
  }
})

test('finalizer rejects a Read offset above the safe reconstruction limit', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
  const batch = manifest.batches[0]
  const transcriptPath = path.join(wfDir, 'agent-batch-1.jsonl')
  const rows = fs.readFileSync(transcriptPath, 'utf8').split('\n').filter(Boolean).map((row) => JSON.parse(row))
  const readRow = rows.find((row) => row.message?.content?.some((item) => item.type === 'tool_use' && item.name === 'Read'))
  const resultRow = rows.find((row) => row.message?.content?.some((item) => item.type === 'tool_result'))
  const hugeOffset = Number.MAX_SAFE_INTEGER
  const read = readRow.message.content.find((item) => item.type === 'tool_use' && item.name === 'Read')
  read.input.offset = hugeOffset
  const result = resultRow.message.content.find((item) => item.type === 'tool_result')
  result.content = readResultText(fs.readFileSync(batch.path, 'utf8'), hugeOffset)
  fs.writeFileSync(transcriptPath, `${rows.map((row) => JSON.stringify(row)).join('\n')}\n`)

  assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }))
})

test('merged primary batches feed the existing PASS-only reaudit and zero-pass path', () => {
  {
    const { fixture, sampled, manifest } = makeTwentySampleFixture()
    const findings = manifest.batches.map((_, batchIndex) => Array.from({ length: 5 }, (_, rowIndex) => {
      const sample = manifest.samples[batchIndex * 5 + rowIndex]
      return [0, 10].includes(batchIndex * 5 + rowIndex) ? [] : [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]
    }))
    const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, findings })
    const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
    assert.equal(prepared.reaudit_sample_count, 2)
    const reauditText = fs.readFileSync(reauditSamplesTextPathFor(fixture, '2026-08-14', sampled.attempt_nonce), 'utf8')
    assert.equal(reauditText.includes('batch-session-1'), true)
    assert.equal(reauditText.includes('batch-session-11'), true)
    assert.equal(reauditText.includes('batch-session-2'), false)
  }

  {
    const { fixture, sampled, manifest } = makeTwentySampleFixture()
    const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
    const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
    assert.deepEqual(prepared, { date: '2026-08-14', reaudit_sample_count: 0, reaudit_nonce: null })
    const finalized = run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce, reauditNonce: '0' })
    assert.equal(finalized.ok, true)
    const publication = JSON.parse(fs.readFileSync(publicationPathFor(fixture), 'utf8'))
    assert.equal(publication.reaudit_sample_count, 0)
    assert.equal(publication.reaudit_nonce, null)
  }
})

test('finalizer rejects re-audit disk bytes that differ from expected samples', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const finding = (sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]
  const findings = manifest.batches.map((_, batchIndex) => Array.from({ length: 5 }, (_, rowIndex) => batchIndex === 0 && rowIndex === 0 ? [] : finding(manifest.samples[batchIndex * 5 + rowIndex])))
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, findings })
  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  const reauditPath = reauditSamplesTextPathFor(fixture, '2026-08-14', sampled.attempt_nonce)
  const expectedText = fs.readFileSync(reauditPath, 'utf8')
  writeAuditTranscript({
    directory: wfDir,
    name: 'agent-reaudit.jsonl',
    samplesPath: reauditPath,
    samplesText: expectedText,
    audit: auditFor([manifest.samples[0]], [], prepared.reaudit_nonce),
  })
  fs.appendFileSync(reauditPath, 'tampered on disk')

  assertUnverified(fixture, run({
    ...fixture,
    mode: 'finalize',
    auditTranscripts: wfDir,
    auditNonce: sampled.audit_nonce,
    attemptNonce: sampled.attempt_nonce,
    reauditNonce: prepared.reaudit_nonce,
  }))
})

test('batched re-audit artifacts are isolated by attempt nonce', () => {
  const { fixture, sampled: attemptA, manifest } = makeTwentySampleFixture()
  const wfDir = path.join(fixture.reports, 'wf-transcripts')
  const finding = (sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }]
  const findingsA = manifest.batches.map((_, batchIndex) => Array.from({ length: 5 }, (_, rowIndex) => {
    const sampleIndex = batchIndex * 5 + rowIndex
    return [0, 1].includes(sampleIndex) ? [] : finding(manifest.samples[sampleIndex])
  }))
  writeValidBatchTranscripts({ fixture, sampled: attemptA, manifest, directory: wfDir, findings: findingsA, namePrefix: 'agent-attempt-a-batch-' })
  const preparedA = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: attemptA.audit_nonce, attemptNonce: attemptA.attempt_nonce })
  const pathA = reauditSamplesTextPathFor(fixture, '2026-08-14', attemptA.attempt_nonce)
  assert.equal(preparedA.reaudit_sample_count, 2)
  assert.equal(fs.existsSync(pathA), true)
  assert.equal(fs.readFileSync(pathA, 'utf8').includes('batch-session-1'), true)

  const attemptB = run(fixture)
  const findingsB = manifest.batches.map((_, batchIndex) => Array.from({ length: 5 }, (_, rowIndex) => {
    const sampleIndex = batchIndex * 5 + rowIndex
    return [2, 3].includes(sampleIndex) ? [] : finding(manifest.samples[sampleIndex])
  }))
  writeValidBatchTranscripts({ fixture, sampled: attemptB, manifest, directory: wfDir, findings: findingsB, namePrefix: 'agent-attempt-b-batch-' })
  const preparedB = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: attemptB.audit_nonce, attemptNonce: attemptB.attempt_nonce })
  const pathB = reauditSamplesTextPathFor(fixture, '2026-08-14', attemptB.attempt_nonce)
  assert.equal(preparedB.reaudit_sample_count, 2)
  assert.notEqual(pathA, pathB)
  assert.equal(fs.existsSync(pathB), true)
  assert.equal(fs.readFileSync(pathA, 'utf8').includes('batch-session-3'), false)
  assert.equal(fs.readFileSync(pathB, 'utf8').includes('batch-session-3'), true)
  assert.notEqual(preparedA.reaudit_nonce, preparedB.reaudit_nonce)
})

test('finalizer merges four primary batches with the existing single reaudit transcript', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const findings = manifest.batches.map(() => Array.from({ length: 5 }, () => []))
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, findings })
  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  const reauditPath = reauditSamplesTextPathFor(fixture, '2026-08-14', sampled.attempt_nonce)
  writeAuditTranscript({
    directory: wfDir,
    name: 'agent-reaudit.jsonl',
    samplesPath: reauditPath,
    samplesText: fs.readFileSync(reauditPath, 'utf8'),
    audit: auditFor(manifest.samples, [], prepared.reaudit_nonce),
  })

  const finalized = run({
    ...fixture,
    mode: 'finalize',
    auditTranscripts: wfDir,
    auditNonce: sampled.audit_nonce,
    attemptNonce: sampled.attempt_nonce,
    reauditNonce: prepared.reaudit_nonce,
  })
  assert.equal(finalized.ok, true)
  assert.equal(finalized.sample_count, 20)
  assert.equal(finalized.reaudit_sample_count, 20)
  assert.equal(JSON.parse(fs.readFileSync(receiptPathFor(fixture), 'utf8')).reaudit_sample_count, 20)
})

test('finalizer completes mixed PASS and FAIL batches through the single reaudit path', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const passIndexes = new Set([0, 5, 10, 15])
  const findings = manifest.batches.map((_, batchIndex) => Array.from({ length: 5 }, (_, rowIndex) => {
    const sampleIndex = batchIndex * 5 + rowIndex
    return passIndexes.has(sampleIndex)
      ? []
      : [{ type: 'unsourced-number', quote: manifest.samples[sampleIndex].answer.slice(0, 5) }]
  }))
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, findings })
  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  assert.equal(prepared.reaudit_sample_count, 4)
  const passSamples = [...passIndexes].sort((left, right) => left - right).map((index) => manifest.samples[index])
  const reauditFindings = passSamples.map((sample, index) => index === 1
    ? [{ type: 'doc-as-evidence', quote: sample.answer.slice(0, 5) }]
    : [])
  writeAuditTranscript({
    directory: wfDir,
    name: 'agent-reaudit.jsonl',
    samplesPath: reauditSamplesTextPathFor(fixture, '2026-08-14', sampled.attempt_nonce),
    samplesText: fs.readFileSync(reauditSamplesTextPathFor(fixture, '2026-08-14', sampled.attempt_nonce), 'utf8'),
    audit: auditFor(passSamples, reauditFindings, prepared.reaudit_nonce),
  })

  const finalized = run({
    ...fixture,
    mode: 'finalize',
    auditTranscripts: wfDir,
    auditNonce: sampled.audit_nonce,
    attemptNonce: sampled.attempt_nonce,
    reauditNonce: prepared.reaudit_nonce,
  })
  assert.equal(finalized.ok, true)
  assert.equal(finalized.sample_count, 20)
  assert.equal(finalized.tp_style_violation_count, 17)
  assert.deepEqual(finalized.top_violations, [
    { type: 'unsourced-number', count: 16 },
    { type: 'doc-as-evidence', count: 1 },
  ])
  const publication = JSON.parse(fs.readFileSync(publicationPathFor(fixture), 'utf8'))
  const receipt = JSON.parse(fs.readFileSync(receiptPathFor(fixture), 'utf8'))
  assert.equal(publication.reaudit_sample_count, 4)
  assert.deepEqual(publication.top_violations, finalized.top_violations)
  assert.equal(receipt.reaudit_sample_count, 4)
  assert.deepEqual(receipt.top_violations, finalized.top_violations)
})

test('finalizer rejects a mutated batch artifact before reading auditor transcripts', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
  const batch = manifest.batches[2]
  fs.appendFileSync(batch.path, 'tampered')

  assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }))
})

test('batched finalizer rejects appended combined samples text', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
  const combinedPath = samplesTextPathFor(fixture)
  fs.appendFileSync(combinedPath, 'appended content')

  assertUnverified(fixture, run({
    ...fixture,
    mode: 'finalize',
    auditTranscripts: wfDir,
    auditNonce: sampled.audit_nonce,
    attemptNonce: sampled.attempt_nonce,
  }))
})

test('finalizer rejects a batch transcript with a JSON parse error', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest })
  fs.appendFileSync(path.join(wfDir, 'agent-batch-1.jsonl'), 'not-json\n')

  assertUnverified(fixture, run({
    ...fixture,
    mode: 'finalize',
    auditTranscripts: wfDir,
    auditNonce: sampled.audit_nonce,
    attemptNonce: sampled.attempt_nonce,
  }))
})

test('fresh sample attempts stay out of the manifest and reject prior-attempt batch transcripts', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  assert.match(sampled.attempt_nonce, /^[a-f0-9]{64}$/)
  const fresh = run(fixture)
  assert.match(fresh.attempt_nonce, /^[a-f0-9]{64}$/)
  assert.notEqual(fresh.attempt_nonce, sampled.attempt_nonce)
  assert.equal(fresh.audit_nonce, sampled.audit_nonce)
  assert.equal(Object.hasOwn(JSON.parse(fs.readFileSync(manifestPathFor(fixture), 'utf8')), 'attempt_nonce'), false)

  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, attemptNonce: sampled.attempt_nonce })
  assertUnverified(fixture, run({
    ...fixture,
    mode: 'finalize',
    auditTranscripts: wfDir,
    auditNonce: sampled.audit_nonce,
    attemptNonce: fresh.attempt_nonce,
    reauditNonce: '0',
  }))

  writeValidBatchTranscripts({ fixture, sampled, manifest, directory: wfDir, attemptNonce: fresh.attempt_nonce })
  const finalized = run({
    ...fixture,
    mode: 'finalize',
    auditTranscripts: wfDir,
    auditNonce: sampled.audit_nonce,
    attemptNonce: fresh.attempt_nonce,
    reauditNonce: '0',
  })
  assert.equal(finalized.ok, true)
})

test('legacy twenty-row v2 manifests remain on the single-auditor path', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const legacyPayload = {
    schema_version: 2,
    date: manifest.date,
    eligible: manifest.eligible,
    samples: manifest.samples,
    challenge: manifest.challenge,
  }
  const legacyManifest = { ...legacyPayload, manifest_hash: sha256(JSON.stringify(legacyPayload)) }
  fs.writeFileSync(manifestPathFor(fixture), `${JSON.stringify(legacyManifest)}\n`, { mode: 0o600 })
  fs.writeFileSync(versionPathFor(fixture), `${JSON.stringify({ date: manifest.date, schema_version: 2, manifest_hash: legacyManifest.manifest_hash })}\n`, { mode: 0o600 })
  manifest.batches.forEach((batch) => fs.rmSync(batch.path))

  const legacySampled = run(fixture)
  assert.equal(legacySampled.sample_count, 20)
  assert.equal(Object.hasOwn(legacySampled, 'batches'), false)
  assert.equal(Object.hasOwn(legacySampled, 'attempt_nonce'), false)
  assert.equal(Object.hasOwn(JSON.parse(fs.readFileSync(manifestPathFor(fixture), 'utf8')), 'batches'), false)

  const finalized = run({
    ...fixture,
    mode: 'finalize',
    audit: auditFor(manifest.samples, manifest.samples.map((sample) => [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }])),
    attemptNonce: null,
  })
  assert.equal(finalized.ok, true)
  assert.equal(finalized.sample_count, 20)
})

test('batched preparer and finalizer reject missing attempt nonce', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const wfDir = writeValidBatchTranscripts({ fixture, sampled, manifest, attemptNonce: null })
  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: null })
  assert.deepEqual(prepared, { date: '2026-08-14', reaudit_sample_count: 0, reaudit_nonce: null })
  assertUnverified(fixture, run({
    ...fixture,
    mode: 'finalize',
    auditTranscripts: wfDir,
    auditNonce: sampled.audit_nonce,
    attemptNonce: null,
    reauditNonce: '0',
  }))
})

const compactAuditFor = (samples, findings, auditNonce, startIndex = 1) => ({
  audit_nonce: auditNonce,
  rows: samples.map((_, index) => ({
    sample_index: startIndex + index,
    result: findings[index]?.length ? 'FAIL' : 'PASS',
    findings: findings[index] ?? [],
  })),
})

const writeCompactBatchTranscripts = (options) => {
  const directory = writeValidBatchTranscripts(options)
  for (const batch of options.manifest.batches) {
    const file = path.join(directory, `agent-batch-${batch.index}.jsonl`)
    const records = fs.readFileSync(file, 'utf8').trim().split('\n').map((line) => JSON.parse(line))
    for (const record of records) {
      for (const item of record.message.content) {
        if (item.name !== 'StructuredOutput') continue
        item.input.rows = item.input.rows.map((row, index) => ({
          sample_index: batch.range.start + index,
          result: row.result,
          findings: row.findings,
        }))
        options.mutate?.(item.input, batch)
      }
    }
    writeRows(file, records)
  }
  return directory
}

test('compact sampler omits copied identities while the manifest keeps its source members', () => {
  const { sampled, manifest } = makeTwentySampleFixture()
  assert.equal(sampled.batches.length, 4)
  for (const batch of sampled.batches) {
    assert.equal(Object.hasOwn(batch, 'members'), false)
    assert.deepEqual(Object.keys(batch).sort(), ['audit_nonce', 'index', 'path', 'range'])
  }
  assert.equal(manifest.batches[0].members[0].session, 'batch-session-1')
  assert.equal(manifest.batches[0].members[0].path.endsWith('/twenty.jsonl'), true)
})

test('compact primary audits restore report identities from the manifest instead of model text', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const manifestBefore = fs.readFileSync(manifestPathFor(fixture))
  const wfDir = writeCompactBatchTranscripts({ fixture, sampled, manifest })
  const finalized = run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  assert.equal(finalized.ok, true)
  assert.equal(finalized.tp_style_violation_count, 20)
  const rows = fs.readFileSync(reportPathFor(fixture), 'utf8').split('\n').filter((line) => line.startsWith('| 2026-08-14T'))
  assert.equal(rows.length, 20)
  for (let index = 0; index < rows.length; index += 1) {
    assert.equal(rows[index].startsWith(`| ${manifest.samples[index].timestamp} | batch-session-${index + 1} | ${path.join(fixture.project, 'twenty.jsonl')} | FAIL |`), true)
  }
  assert.deepEqual(fs.readFileSync(manifestPathFor(fixture)), manifestBefore)
})

test('compact PASS reaudit indexes bind to the subset rather than primary sample positions', () => {
  for (const wrongIndex of [false, true]) {
    const { fixture, sampled, manifest } = makeTwentySampleFixture()
    const passIndexes = [0, 5, 10, 15]
    const findings = manifest.batches.map((_, batchIndex) => Array.from({ length: 5 }, (_, rowIndex) => {
      const index = batchIndex * 5 + rowIndex
      return passIndexes.includes(index) ? [] : [{ type: 'unsourced-number', quote: manifest.samples[index].answer.slice(0, 5) }]
    }))
    const wfDir = writeCompactBatchTranscripts({ fixture, sampled, manifest, findings })
    const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
    assert.equal(prepared.reaudit_sample_count, 4)
    const passSamples = passIndexes.map((index) => manifest.samples[index])
    const audit = compactAuditFor(passSamples, [[], [{ type: 'doc-as-evidence', quote: passSamples[1].answer.slice(0, 5) }]], prepared.reaudit_nonce)
    if (wrongIndex) audit.rows[1].sample_index = 6
    const reauditPath = reauditSamplesTextPathFor(fixture, '2026-08-14', sampled.attempt_nonce)
    writeAuditTranscript({ directory: wfDir, name: 'agent-reaudit.jsonl', samplesPath: reauditPath, samplesText: fs.readFileSync(reauditPath, 'utf8'), audit })
    const finalized = run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce, reauditNonce: prepared.reaudit_nonce })
    if (wrongIndex) assertUnverified(fixture, finalized)
    else {
      assert.equal(finalized.ok, true)
      assert.equal(finalized.reaudit_sample_count, 4)
      assert.equal(finalized.tp_style_violation_count, 17)
    }
  }
})

test('compact audits reject malformed indices, mixed rows, bad bindings and forged quotes', () => {
  const cases = [
    (packet) => { packet.rows[0].sample_index = 0 },
    (packet) => { packet.rows[0].sample_index = 21 },
    (packet) => { packet.rows[0].sample_index = 1.5 },
    (packet) => { packet.rows[1].sample_index = 1 },
    (packet) => { [packet.rows[0], packet.rows[1]] = [packet.rows[1], packet.rows[0]] },
    (packet) => { packet.rows.pop() },
    (packet) => { packet.rows[0].path = '/invented/session.jsonl' },
    (packet) => { delete packet.rows[0].sample_index; Object.assign(packet.rows[0], { timestamp: 't', session: 's', path: 'p' }) },
    (packet) => { packet.audit_nonce = '0'.repeat(64) },
    (packet) => { packet.attempt_nonce = '0'.repeat(64) },
    (packet) => { packet.batch_index = 2 },
    (packet) => { packet.rows[0].findings[0].quote = 'not in this answer' },
  ]
  for (const mutate of cases) {
    const { fixture, sampled, manifest } = makeTwentySampleFixture()
    const wfDir = writeCompactBatchTranscripts({ fixture, sampled, manifest, mutate: (packet, batch) => { if (batch.index === 1) mutate(packet) } })
    assertUnverified(fixture, run({ ...fixture, mode: 'finalize', auditTranscripts: wfDir, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }))
  }
})

// Ticket 14 acceptance batch (hash-free-harness): receipts carry no digest, verify recomputes none,
// and artefacts written by the old digest-bearing format still load.
const writeBareBatchTranscripts = ({ fixture, sampled, manifest, passIndexes = new Set() }) => {
  const directory = path.join(fixture.reports, 'wf-transcripts')
  fs.mkdirSync(directory, { recursive: true })
  manifest.batches.forEach((batch, index) => {
    const batchSamples = manifest.samples.slice(index * 5, index * 5 + 5)
    const findings = batchSamples.map((sample, row) => passIndexes.has(index * 5 + row) ? [] : [{ type: 'unsourced-number', quote: sample.answer.slice(0, 5) }])
    writeAuditTranscript({
      directory,
      name: `agent-batch-${batch.index}.jsonl`,
      samplesPath: batch.path,
      samplesText: fs.readFileSync(batch.path, 'utf8'),
      audit: { ...auditFor(batchSamples, findings, sampled.audit_nonce), batch_index: batch.index, range: batch.range, attempt_nonce: sampled.attempt_nonce },
    })
  })
  return directory
}
const finalizeBare = ({ passIndexes = new Set(), extraFlags = [] } = {}) => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const directory = writeBareBatchTranscripts({ fixture, sampled, manifest, passIndexes })
  const common = { ...fixture, auditTranscripts: directory, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce }
  let prepared = null
  let reauditNonce = '0'
  if (passIndexes.size > 0) {
    prepared = run({ ...common, mode: 'prepare-reaudit' })
    const reauditPath = reauditSamplesTextPathFor(fixture, '2026-08-14', sampled.attempt_nonce)
    writeAuditTranscript({
      directory,
      name: 'agent-reaudit.jsonl',
      samplesPath: reauditPath,
      samplesText: fs.readFileSync(reauditPath, 'utf8'),
      audit: auditFor([...passIndexes].sort((a, b) => a - b).map((index) => manifest.samples[index]), [], prepared.reaudit_nonce),
    })
    reauditNonce = prepared.reaudit_nonce
  }
  const finalized = run({ ...common, mode: 'finalize', reauditNonce, extraFlags })
  return { fixture, sampled, manifest, prepared, finalized, common }
}
const legacyDigestsInto = (fixture, { garbage = false } = {}) => {
  const date = '2026-08-14'
  const digest = (value) => garbage ? 'f'.repeat(64) : sha256(value)
  const manifestPath = manifestPathFor(fixture)
  const manifest = readJson(manifestPath)
  const wholeSamples = digest(JSON.stringify(manifest.samples))
  const batches = manifest.batches?.map(({ index, range, members, path: batchPath, audit_nonce }) => ({
    index, range, members, path: batchPath, batch_sha256: digest(fs.readFileSync(batchPath, 'utf8')), samples_sha256: wholeSamples, audit_nonce,
  }))
  const payload = { schema_version: 2, date, eligible: manifest.eligible, samples: manifest.samples, challenge: manifest.challenge, ...(batches == null ? {} : { audit_nonce: manifest.audit_nonce, batches }) }
  const manifestHash = digest(JSON.stringify(payload))
  fs.writeFileSync(manifestPath, `${JSON.stringify({ ...payload, manifest_hash: manifestHash })}\n`)
  fs.writeFileSync(versionPathFor(fixture), `${JSON.stringify({ date, schema_version: 2, manifest_hash: manifestHash })}\n`)
  const reauditFile = reauditSamplesTextPathFor(fixture, date, manifest.batches == null ? null : readJson(publicationPathFor(fixture)).attempt_nonce)
  const reauditSha = readJson(publicationPathFor(fixture)).reaudit_sample_count === 0 ? null : digest(fs.readFileSync(reauditFile))
  const publication = {
    ...readJson(publicationPathFor(fixture)),
    manifest_sha256: digest(fs.readFileSync(manifestPath)),
    samples_sha256: wholeSamples,
    samples_file_sha256: digest(fs.readFileSync(samplesTextPathFor(fixture))),
    report_sha256: digest(readJson(publicationPathFor(fixture)).report),
    reaudit_samples_file_sha256: reauditSha,
  }
  fs.writeFileSync(publicationPathFor(fixture), `${JSON.stringify(publication)}\n`)
  const receipt = {
    ...readJson(receiptPathFor(fixture)),
    report_sha256: publication.report_sha256,
    manifest_sha256: publication.manifest_sha256,
    samples_sha256: publication.samples_sha256,
    samples_file_sha256: publication.samples_file_sha256,
    publication_sha256: digest(fs.readFileSync(publicationPathFor(fixture))),
    reaudit_samples_file_sha256: reauditSha,
  }
  fs.writeFileSync(receiptPathFor(fixture), `${JSON.stringify(receipt)}\n`)
}

test('sampler stdout, manifest, batches and version file carry no digest fields', () => {
  const { fixture, sampled } = makeTwentySampleFixture()
  assert.deepEqual(Object.keys(sampled).sort(), ['attempt_nonce', 'audit_nonce', 'batches', 'challenge', 'date', 'days_since', 'due', 'eligible', 'last_success_date', 'sample_count'])
  for (const batch of sampled.batches) assert.deepEqual(Object.keys(batch).sort(), ['audit_nonce', 'index', 'path', 'range'])
  assert.deepEqual(Object.keys(readJson(manifestPathFor(fixture))).sort(), ['audit_nonce', 'batches', 'challenge', 'date', 'eligible', 'samples', 'schema_version'])
  assert.deepEqual(readJson(versionPathFor(fixture)), { date: '2026-08-14', schema_version: 2 })
})

test('finalize without digest flags writes receipt, publication and packet with no digest field', () => {
  const { fixture, finalized } = finalizeBare()
  assert.equal(finalized.ok, true)
  assert.deepEqual(Object.keys(finalized).sort(), ['audit_nonce', 'challenge', 'date', 'eligible', 'manifest_path', 'ok', 'reaudit_nonce', 'reaudit_sample_count', 'report_path', 'sample_count', 'top_violations', 'tp_style_violation_count'])
  const receipt = readJson(receiptPathFor(fixture))
  const publication = readJson(publicationPathFor(fixture))
  assert.deepEqual(Object.keys(receipt).sort(), ['attempt_nonce', 'audit_nonce', 'challenge', 'date', 'eligible', 'reaudit_nonce', 'reaudit_sample_count', 'sample_count', 'schema_version', 'top_violations', 'tp_style_violation_count'])
  assert.deepEqual(Object.keys(publication).sort(), ['attempt_nonce', 'audit_nonce', 'challenge', 'date', 'eligible', 'reaudit_nonce', 'reaudit_sample_count', 'report', 'sample_count', 'schema_version', 'top_violations', 'tp_style_violation_count'])
  const forbidden = new Set([
    fs.readFileSync(reportPathFor(fixture)), fs.readFileSync(manifestPathFor(fixture)), fs.readFileSync(publicationPathFor(fixture)), fs.readFileSync(samplesTextPathFor(fixture)),
  ].map(sha256))
  const values = (value) => value == null || typeof value !== 'object' ? [value] : Object.values(value).flatMap(values)
  for (const written of [finalized, receipt, publication]) assert.equal(values(written).some((value) => forbidden.has(value)), false)
  assert.equal(receipt.sample_count, 20)
  assert.equal(receipt.audit_nonce, finalized.audit_nonce)
})

test('finalize ignores legacy digest flags instead of requiring or checking them', () => {
  const { finalized } = finalizeBare({ extraFlags: ['--samples-sha256', 'x', '--samples-file-sha256', 'y', '--reaudit-samples-file-sha256', 'z'] })
  assert.equal(finalized.ok, true)
})

test('prepare-reaudit and finalize work from nonces alone and bind the PASS subset', () => {
  const { fixture, prepared, finalized } = finalizeBare({ passIndexes: new Set([0, 5, 10, 15]) })
  assert.deepEqual(Object.keys(prepared).sort(), ['date', 'reaudit_nonce', 'reaudit_sample_count'])
  assert.equal(prepared.reaudit_sample_count, 4)
  assert.equal(finalized.ok, true)
  assert.equal(finalized.reaudit_sample_count, 4)
  assert.equal(finalized.reaudit_nonce, prepared.reaudit_nonce)
  assert.equal(readJson(receiptPathFor(fixture)).reaudit_nonce, prepared.reaudit_nonce)
})

test('prepare-reaudit with no PASS rows returns the zero packet without a digest field', () => {
  const { fixture, sampled, manifest } = makeTwentySampleFixture()
  const directory = writeBareBatchTranscripts({ fixture, sampled, manifest })
  const prepared = run({ ...fixture, mode: 'prepare-reaudit', auditTranscripts: directory, auditNonce: sampled.audit_nonce, attemptNonce: sampled.attempt_nonce })
  assert.deepEqual(prepared, { date: '2026-08-14', reaudit_sample_count: 0, reaudit_nonce: null })
})

test('verify recomputes no digest: receipt stays verified while still checking the report text', () => {
  const { fixture } = finalizeBare()
  const due = () => run({ ...fixture, mode: 'due' })
  assert.equal(due().last_success_date, '2026-08-14')
  fs.appendFileSync(reportPathFor(fixture), 'edited\n')
  assert.equal(due().last_success_date, null)
})

for (const garbage of [false, true]) {
  test(`old receipts with ${garbage ? 'wrong' : 'correct'} sha256 fields still load and are never recomputed`, () => {
    const { fixture, finalized } = finalizeBare({ passIndexes: new Set([0, 5, 10, 15]) })
    legacyDigestsInto(fixture, { garbage })
    assert.equal(run({ ...fixture, mode: 'due' }).last_success_date, '2026-08-14')
    const again = run({ ...fixture, mode: 'finalize', auditTranscripts: path.join(fixture.reports, 'wf-transcripts'), auditNonce: finalized.audit_nonce, attemptNonce: readJson(receiptPathFor(fixture)).attempt_nonce, reauditNonce: finalized.reaudit_nonce })
    assert.equal(again.ok, true)
    assert.equal(again.tp_style_violation_count, finalized.tp_style_violation_count)
  })
}
