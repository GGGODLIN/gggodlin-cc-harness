#!/usr/bin/env node

import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const parseArgs = (argv) => {
  const values = {}
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]
    const value = argv[index + 1]
    if (!key?.startsWith('--') || value == null) throw new Error('arguments must be --key value pairs')
    values[key.slice(2)] = value
  }
  return values
}

const parseDate = (value) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value ?? '')) throw new Error('date must be YYYY-MM-DD')
  const parsed = new Date(`${value}T00:00:00.000Z`)
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) throw new Error('date must be valid')
  return parsed
}

const formatDate = (value) => value.toISOString().slice(0, 10)
const addDays = (value, days) => new Date(value.getTime() + days * 86400000)

const REPORT_TABLE_HEADER = '| timestamp | session | path | 結果 | 類型 | 最短原句 | 說明 |'
const REPORT_TABLE_SEPARATOR = '|---|---|---|---|---|---|---|'
const LIMITATIONS = '本報告只判單則回答文字；每次最多抽樣 20 則；code 不計入 200 字長度門檻，但完整保留在受評回答；未核對回答所述外部事實真偽。'
const VIOLATION_TYPES = new Set(['unsourced-completion', 'unsourced-number', 'unsourced-mechanism', 'doc-as-evidence', 'silent-skip'])
const VIOLATION_ORDER = new Map([...VIOLATION_TYPES].map((type, index) => [type, index]))
const EVIDENCE_V2_START_DATE = '2026-08-14'
const PRIMARY_SAMPLE_COUNT = 20
const PRIMARY_BATCH_SIZE = 5
const PRIMARY_BATCH_COUNT = 4
const TRANSCRIPT_STABILITY_RETRIES = 3
const TRANSCRIPT_STABILITY_WAIT_MS = 5
const TRANSCRIPT_MAX_CANDIDATE_FILES = 128
const TRANSCRIPT_MAX_CANDIDATE_BYTES = 8 * 1024 * 1024
const MAX_READ_OFFSET = 1_000_000
const MAX_READ_LIMIT = 100_000
const MAX_RECONSTRUCTED_LINES = 100_000

// Artefacts written before digests were removed still carry per-file digest fields and a manifest self-digest;
// they are dropped before shape checks so an old receipt loads instead of being read as forged.
const isLegacyDigestKey = (key) => /_sha\d+$/.test(key) || key === 'manifest_hash'
const withoutLegacyDigests = (value) => value && typeof value === 'object' && !Array.isArray(value)
  ? Object.fromEntries(Object.entries(value).filter(([key]) => !isLegacyDigestKey(key)))
  : value
const manifestPathFor = (reports, date) => path.join(reports, `${date}-evidence-level-manifest.json`)
const samplesTextPathFor = (reports, date) => path.join(reports, `${date}-evidence-level-samples.txt`)
const batchSamplesTextPathFor = (reports, date, index) => path.join(reports, `${date}-evidence-level-samples-batch-${index}.txt`)
const reauditSamplesTextPathFor = (reports, date, attemptNonce = null) => path.join(reports, `${date}-evidence-level-reaudit-samples${attemptNonce == null ? '' : `-${attemptNonce}`}.txt`)
const publicationPathFor = (reports, date) => path.join(reports, `${date}-evidence-level.publish.json`)
const reportPathFor = (reports, date) => path.join(reports, `${date}-evidence-level.md`)
const receiptPathFor = (reports, date) => path.join(reports, `${date}-evidence-level.verified.json`)
const versionPathFor = (reports, date) => path.join(reports, `${date}-evidence-level.version.json`)
const ensurePrivateDirectory = (directory) => {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 })
  fs.chmodSync(directory, 0o700)
}
const isPrivateFile = (file) => (fs.statSync(file).mode & 0o077) === 0
const hasVerifiedReport = (reports, date) => {
  if (!fs.existsSync(reports) || (fs.statSync(reports).mode & 0o077) !== 0) return false
  const reportPath = reportPathFor(reports, date)
  const manifestPath = manifestPathFor(reports, date)
  const publicationPath = publicationPathFor(reports, date)
  const receiptPath = receiptPathFor(reports, date)
  if (![reportPath, manifestPath, publicationPath, receiptPath].every((file) => fs.existsSync(file) && isPrivateFile(file))) return false
  try {
    const receipt = withoutLegacyDigests(JSON.parse(fs.readFileSync(receiptPath, 'utf8')))
    const publication = withoutLegacyDigests(JSON.parse(fs.readFileSync(publicationPath, 'utf8')))
    const packetValid = receipt.date === date
    const receiptVersion = Object.hasOwn(receipt, 'schema_version') ? receipt.schema_version : 1
    const publicationVersion = Object.hasOwn(publication, 'schema_version') ? publication.schema_version : 1
    const expectedVersion = date >= EVIDENCE_V2_START_DATE ? 2 : receiptVersion
    if (!packetValid || receiptVersion !== publicationVersion || receiptVersion !== expectedVersion || ![1, 2].includes(receiptVersion)) return false
    if (receiptVersion === 1) return true
    if (Object.hasOwn(receipt, 'attempt_nonce') && !isNonce(receipt.attempt_nonce)) return false
    const samplesTextPath = samplesTextPathFor(reports, date)
    if (!fs.existsSync(samplesTextPath) || !isPrivateFile(samplesTextPath)) return false
    if (receipt.reaudit_sample_count === 0) return receipt.reaudit_nonce === null
    const reauditSamplesTextPath = reauditSamplesTextPathFor(reports, date, receipt.attempt_nonce ?? null)
    return fs.existsSync(reauditSamplesTextPath) && isPrivateFile(reauditSamplesTextPath)
  } catch {
    return false
  }
}

const findLastSuccessDate = (reports, date) => {
  if (!fs.existsSync(reports)) return null
  return fs.readdirSync(reports, { withFileTypes: true })
    .filter((entry) => entry.isFile())
    .map((entry) => entry.name.match(/^(\d{4}-\d{2}-\d{2})-evidence-level\.md$/)?.[1] ?? null)
    .filter((entryDate) => entryDate != null && entryDate <= date && verifiedPacket(reports, entryDate) != null)
    .sort()
    .at(-1) ?? null
}

const buildDuePacket = (reports, date) => {
  const lastSuccessDate = findLastSuccessDate(reports, date)
  if (lastSuccessDate == null) {
    return { date, due: true, last_success_date: null, days_since: null }
  }
  const daysSince = Math.floor((parseDate(date).getTime() - parseDate(lastSuccessDate).getTime()) / 86400000)
  return {
    date,
    due: daysSince >= 7,
    last_success_date: lastSuccessDate,
    days_since: daysSince,
  }
}

const removeCode = (value) => value
  .replace(/```[\s\S]*?```/g, '')
  .replace(/~~~[\s\S]*?~~~/g, '')
  .replace(/^(?: {4}|\t).*$(?:\r?\n)?/gm, '')
  .replace(/`[^`\n]*`/g, '')

const extractText = (content) => {
  if (typeof content === 'string') return content
  if (!Array.isArray(content)) return ''
  return content
    .filter((item) => item && typeof item === 'object' && item.type === 'text' && typeof item.text === 'string')
    .map((item) => item.text)
    .join('\n')
}

const FULLWIDTH_STOPS = new Set(['，', '；', '。', '！', '？', '、', '：'])

const lineEndFrom = (value, start) => {
  const carriageReturn = value.indexOf('\r', start)
  const newline = value.indexOf('\n', start)
  const candidates = [carriageReturn, newline].filter((index) => index >= 0)
  return candidates.length === 0 ? value.length : Math.min(...candidates)
}

const quotedBoundsAt = (value, start, limit) => {
  const quote = value[start]
  if (quote === '"' || quote === "'") {
    let index = start + 1
    while (index < limit) {
      if (value[index] === '\\') {
        index += Math.min(2, limit - index)
        continue
      }
      if (value[index] === quote) {
        return { contentStart: start + 1, contentEnd: index, after: index + 1 }
      }
      index += 1
    }
    return { contentStart: start + 1, contentEnd: limit, after: limit }
  }

  const escapedQuote = value[start + 1]
  if (value[start] !== '\\' || (escapedQuote !== '"' && escapedQuote !== "'")) return null
  let index = start + 2
  while (index < limit) {
    if (value[index] !== '\\') {
      index += 1
      continue
    }
    let runEnd = index
    while (runEnd < limit && value[runEnd] === '\\') runEnd += 1
    if (runEnd < limit && value[runEnd] === escapedQuote && (runEnd - index) % 4 === 1) {
      return { contentStart: start + 2, contentEnd: index, after: runEnd + 1 }
    }
    index = runEnd < limit && value[runEnd] === escapedQuote ? runEnd + 1 : runEnd
  }
  return { contentStart: start + 2, contentEnd: limit, after: limit }
}

const replaceRanges = (value, ranges) => {
  const ordered = [...ranges].sort((left, right) => left.start - right.start || left.end - right.end)
  let cursor = 0
  let result = ''
  for (const range of ordered) {
    if (range.start < cursor || range.end <= range.start) continue
    result += `${value.slice(cursor, range.start)}[REDACTED]`
    cursor = range.end
  }
  return result + value.slice(cursor)
}

const isCookieNameCharacter = (character) =>
  character != null && !/[=;,\s"'\\，；。！？、]/.test(character)

const cookiePairRanges = (value, start, end) => {
  const ranges = []
  let segmentStart = start
  while (segmentStart < end) {
    let segmentEnd = segmentStart
    while (
      segmentEnd < end &&
      value[segmentEnd] !== ';' &&
      value[segmentEnd] !== ',' &&
      !FULLWIDTH_STOPS.has(value[segmentEnd])
    ) segmentEnd += 1

    let index = segmentStart
    while (index < segmentEnd && /\s/.test(value[index])) index += 1
    const nameStart = index
    while (index < segmentEnd && isCookieNameCharacter(value[index])) index += 1
    while (index < segmentEnd && /\s/.test(value[index])) index += 1
    if (index > nameStart && value[index] === '=') {
      index += 1
      while (index < segmentEnd && /\s/.test(value[index])) index += 1
      const bounds = quotedBoundsAt(value, index, segmentEnd)
      if (bounds != null) {
        ranges.push({ start: bounds.contentStart, end: bounds.contentEnd })
      } else {
        const valueStart = index
        while (index < segmentEnd && !/\s/.test(value[index]) && value[index] !== '"' && value[index] !== "'") index += 1
        ranges.push({ start: valueStart, end: index })
      }
    }

    if (segmentEnd >= end || value[segmentEnd] !== ';') break
    segmentStart = segmentEnd + 1
  }
  return ranges
}

const cookieValueRanges = (value, start) => {
  const lineEnd = lineEndFrom(value, start)
  const bounds = quotedBoundsAt(value, start, lineEnd)
  return bounds == null
    ? cookiePairRanges(value, start, lineEnd)
    : cookiePairRanges(value, bounds.contentStart, bounds.contentEnd)
}

const redactNamedCookieHeaders = (value) => {
  const ranges = []
  const pattern = /\b(?:Set-Cookie|Cookie)(?:\\?["'])?\s*:\s*/gi
  for (let match = pattern.exec(value); match != null; match = pattern.exec(value)) {
    ranges.push(...cookieValueRanges(value, match.index + match[0].length))
  }
  return replaceRanges(value, ranges)
}

const redactCookieOptions = (value) => {
  const ranges = []
  const pattern = /(?:^|\s)(?:-b|--cookie)(?:\s+|=)/gim
  for (let match = pattern.exec(value); match != null; match = pattern.exec(value)) {
    ranges.push(...cookieValueRanges(value, match.index + match[0].length))
  }
  return replaceRanges(value, ranges)
}

const redactCookieHeaders = (value) => redactCookieOptions(redactNamedCookieHeaders(value))

const redactSensitiveAssignments = (value) => {
  const ranges = []
  const pattern = /(?:\\?["'])?(?:api[_-]?key|access[_-]?token|auth[_-]?token|refresh[_-]?token|token|client[_-]?secret|aws[_-]?secret[_-]?access[_-]?key|secret|password|passwd|pwd)(?:\\?["'])?\s*[:=]\s*/gi
  for (let match = pattern.exec(value); match != null; match = pattern.exec(value)) {
    const start = match.index + match[0].length
    const lineEnd = lineEndFrom(value, start)
    const bounds = quotedBoundsAt(value, start, lineEnd)
    if (bounds != null) {
      ranges.push({ start: bounds.contentStart, end: bounds.contentEnd })
      pattern.lastIndex = bounds.after
      continue
    }
    let end = start
    while (end < lineEnd && !/[\s,;，；。！？、]/.test(value[end])) end += 1
    ranges.push({ start, end })
    pattern.lastIndex = end
  }
  return replaceRanges(value, ranges)
}

const redactCredentials = (value) => redactSensitiveAssignments(redactCookieHeaders(value)
  .replace(/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, '[REDACTED]')
  .replace(/\bAuthorization\s*:\s*Basic\s+[A-Za-z0-9+/=]{8,}/gi, 'Authorization: Basic [REDACTED]')
  .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]{12,}/gi, 'Bearer [REDACTED]')
  .replace(/\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/g, '[REDACTED]')
  .replace(/\b(?:sk-ant-[A-Za-z0-9_-]{12,}|sk-(?:proj-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[A-Z0-9]{16})\b/g, '[REDACTED]'))
  .replace(/(https?:\/\/[^\s/:@]+:)[^\s/@]+@/gi, '$1[REDACTED]@')

const listJsonlFiles = (root) => {
  if (!fs.existsSync(root)) return []
  return fs.readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .flatMap((entry) => {
      const directory = path.join(root, entry.name)
      return fs.readdirSync(directory, { withFileTypes: true })
        .filter((file) => file.isFile() && file.name.endsWith('.jsonl'))
        .map((file) => path.join(directory, file.name))
    })
    .filter((file) => !file.includes(`${path.sep}subagents${path.sep}`) && !file.includes(`${path.sep}workflows${path.sep}`))
    .sort()
}

const collectEligible = (root, date) => {
  const currentDate = parseDate(date)
  const start = `${formatDate(addDays(currentDate, -6))}T00:00:00.000Z`
  const end = `${date}T23:59:59.999Z`
  const eligible = []

  for (const file of listJsonlFiles(root)) {
    const rows = fs.readFileSync(file, 'utf8').split('\n')
    rows.forEach((line, rowIndex) => {
      if (line.trim() === '') return
      let row
      try {
        row = JSON.parse(line)
      } catch {
        return
      }
      const message = row.message ?? {}
      const timestamp = row.timestamp
      if (
        row.type !== 'assistant' ||
        row.isSidechain === true ||
        message.stop_reason !== 'end_turn' ||
        typeof timestamp !== 'string' ||
        timestamp < start ||
        timestamp > end
      ) return
      const answer = extractText(message.content)
      if (removeCode(answer).trim().length < 200) return
      eligible.push({
        session: row.sessionId ?? path.basename(file, '.jsonl'),
        path: file,
        timestamp,
        row_index: rowIndex,
        answer: redactCredentials(answer),
      })
    })
  }

  const compareText = (left, right) => left === right ? 0 : left < right ? -1 : 1
  return eligible.sort((left, right) =>
    compareText(left.timestamp, right.timestamp) ||
    compareText(left.path, right.path) ||
    left.row_index - right.row_index
  )
}

const sampleEvenly = (items, limit = 20) => {
  if (items.length <= limit) return items
  return Array.from({ length: limit }, (_, index) =>
    items[Math.round(index * (items.length - 1) / (limit - 1))]
  )
}

const sameKeys = (value, keys) =>
  value && typeof value === 'object' && !Array.isArray(value) &&
  JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...keys].sort())
const isNonce = (value) => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)
const batchRangeFor = (index) => ({
  start: (index - 1) * PRIMARY_BATCH_SIZE + 1,
  end: index * PRIMARY_BATCH_SIZE,
})
const sampleIdentity = ({ timestamp, session, path: samplePath, row_index }) => ({
  timestamp,
  session,
  path: samplePath,
  row_index,
})
const batchSamplesFor = (samples, batch) => samples.slice(batch.range.start - 1, batch.range.end)
const isBatchedManifest = (manifest) => Array.isArray(manifest?.batches)
const parseVersionCommitment = (reports, date) => {
  const file = versionPathFor(reports, date)
  if (!fs.existsSync(file)) return null
  if (!isPrivateFile(file)) return false
  try {
    const commitment = withoutLegacyDigests(JSON.parse(fs.readFileSync(file, 'utf8')))
    return sameKeys(commitment, ['date', 'schema_version']) && commitment.date === date && commitment.schema_version === 2 ? commitment : false
  } catch {
    return false
  }
}
const validSampleRecords = (samples) => {
  const identities = new Set()
  return Array.isArray(samples) && samples.every((sample) => {
    if (!sameKeys(sample, ['session', 'path', 'timestamp', 'row_index', 'answer']) ||
      typeof sample.session !== 'string' || sample.session === '' ||
      typeof sample.path !== 'string' || sample.path === '' ||
      typeof sample.timestamp !== 'string' ||
      !Number.isInteger(sample.row_index) || sample.row_index < 0 ||
      typeof sample.answer !== 'string') return false
    const identity = JSON.stringify(sampleIdentity(sample))
    if (identities.has(identity)) return false
    identities.add(identity)
    return true
  })
}
const parseManifest = (file, date) => {
  if (!fs.existsSync(file) || !isPrivateFile(file)) return null
  try {
    const manifest = withoutLegacyDigests(JSON.parse(fs.readFileSync(file, 'utf8')))
    const v1Keys = ['date', 'eligible', 'samples', 'challenge']
    const v2Keys = ['schema_version', 'date', 'eligible', 'samples', 'challenge']
    const batchedV2Keys = ['schema_version', 'date', 'eligible', 'samples', 'challenge', 'audit_nonce', 'batches']
    const isV2 = Object.hasOwn(manifest, 'schema_version')
    const isBatched = Object.hasOwn(manifest, 'batches') || Object.hasOwn(manifest, 'audit_nonce')
    const commitment = parseVersionCommitment(path.dirname(file), date)
    if (commitment === false) return null
    if (isV2
      ? (isBatched ? !sameKeys(manifest, batchedV2Keys) : !sameKeys(manifest, v2Keys)) || manifest.schema_version !== 2 || commitment == null
      : !sameKeys(manifest, v1Keys) || commitment != null || date >= EVIDENCE_V2_START_DATE) return null
    if (manifest.date !== date || !Number.isInteger(manifest.eligible) || manifest.eligible < 0 || !Array.isArray(manifest.samples)) return null
    if (!/^[a-f0-9]{64}$/.test(manifest.challenge) || manifest.samples.length !== Math.min(manifest.eligible, PRIMARY_SAMPLE_COUNT)) return null
    if (!validSampleRecords(manifest.samples)) return null
    if (isBatched) {
      if (manifest.samples.length !== PRIMARY_SAMPLE_COUNT || !/^[a-f0-9]{64}$/.test(manifest.audit_nonce) || !Array.isArray(manifest.batches) || manifest.batches.length !== PRIMARY_BATCH_COUNT) return null
      const indices = new Set()
      manifest.batches = manifest.batches.map(withoutLegacyDigests)
      const batchesValid = manifest.batches.every((batch) => {
        if (!sameKeys(batch, ['index', 'range', 'members', 'path', 'audit_nonce'])) return false
        if (!Number.isInteger(batch.index) || batch.index < 1 || batch.index > PRIMARY_BATCH_COUNT || indices.has(batch.index)) return false
        indices.add(batch.index)
        const expectedRange = batchRangeFor(batch.index)
        if (!sameKeys(batch.range, ['start', 'end']) || batch.range.start !== expectedRange.start || batch.range.end !== expectedRange.end) return false
        const expectedSamples = batchSamplesFor(manifest.samples, batch)
        if (!Array.isArray(batch.members) || batch.members.length !== PRIMARY_BATCH_SIZE || batch.members.some((member, index) =>
          !sameKeys(member, ['timestamp', 'session', 'path', 'row_index']) ||
          member.timestamp !== expectedSamples[index].timestamp ||
          member.session !== expectedSamples[index].session ||
          member.path !== expectedSamples[index].path ||
          member.row_index !== expectedSamples[index].row_index
        )) return false
        if (batch.path !== batchSamplesTextPathFor(path.dirname(file), date, batch.index)) return false
        return batch.audit_nonce === manifest.audit_nonce
      })
      if (!batchesValid || indices.size !== PRIMARY_BATCH_COUNT) return null
    }
    return manifest
  } catch {
    return null
  }
}
const buildBatchedManifest = (reports, date, eligible, samples, challenge, auditNonce) => {
  const batches = Array.from({ length: PRIMARY_BATCH_COUNT }, (_, index) => {
    const batchIndex = index + 1
    const range = batchRangeFor(batchIndex)
    const batchSamples = samples.slice(range.start - 1, range.end)
    return {
      index: batchIndex,
      range,
      members: batchSamples.map(sampleIdentity),
      path: batchSamplesTextPathFor(reports, date, batchIndex),
      audit_nonce: auditNonce,
    }
  })
  return {
    schema_version: 2,
    date,
    eligible,
    samples,
    challenge,
    audit_nonce: auditNonce,
    batches,
  }
}
const readPersistedManifest = (file, date) => {
  const signal = new Int32Array(new SharedArrayBuffer(4))
  for (let attempt = 0; attempt < 20; attempt += 1) {
    const persisted = parseManifest(file, date)
    if (persisted != null) return persisted
    if (attempt < 19) Atomics.wait(signal, 0, 0, 5)
  }
  return null
}
const loadOrCreateManifest = (root, reports, date) => {
  ensurePrivateDirectory(reports)
  const file = manifestPathFor(reports, date)
  const existing = parseManifest(file, date)
  if (existing != null) return { file, manifest: existing }
  if (fs.existsSync(file)) {
    const persisted = readPersistedManifest(file, date)
    if (persisted != null) return { file, manifest: persisted }
    throw new Error('existing evidence-level manifest is invalid')
  }
  const eligibleAnswers = collectEligible(root, date)
  const samples = sampleEvenly(eligibleAnswers)
  const challenge = crypto.randomBytes(32).toString('hex')
  const manifest = samples.length === PRIMARY_SAMPLE_COUNT
    ? buildBatchedManifest(reports, date, eligibleAnswers.length, samples, challenge, crypto.randomBytes(32).toString('hex'))
    : {
      schema_version: 2,
      date,
      eligible: eligibleAnswers.length,
      samples,
      challenge,
    }
  const temporary = `${file}.${process.pid}.tmp`
  fs.rmSync(temporary, { force: true })
  fs.writeFileSync(temporary, `${JSON.stringify(manifest)}\n`, { flag: 'wx', mode: 0o600 })
  let linked = true
  try {
    fs.linkSync(temporary, file)
  } catch (error) {
    if (error?.code !== 'EEXIST') throw error
    linked = false
  } finally {
    fs.rmSync(temporary, { force: true })
  }
  if (!linked) {
    const persisted = readPersistedManifest(file, date)
    if (persisted == null) throw new Error('evidence-level manifest persistence failed')
    return { file, manifest: persisted }
  }
  const commitment = { date, schema_version: 2 }
  publishFirstWins(versionPathFor(reports, date), `${JSON.stringify(commitment)}\n`)
  const persisted = parseManifest(file, date)
  if (persisted == null) throw new Error('evidence-level manifest persistence failed')
  return { file, manifest: persisted }
}
const normalizeFindingText = (value) => value
  .replace(/^\s*(?:[-+]|\*)\s+/, '')
  .replace(/\*\*/g, '')
  .replace(/`/g, '')
  .replace(/\s+/g, ' ')
  .trim()
const canonicalFindingQuote = (answer, quote) => {
  if (answer.includes(quote)) return quote
  const normalizedQuote = normalizeFindingText(quote)
  if (normalizedQuote === '') return null
  const matches = answer
    .split('\n')
    .flatMap((line) => line.split('|'))
    .map((line) => line.trim())
    .filter((line) => line !== '' && normalizeFindingText(line).includes(normalizedQuote))
  return matches.length === 1 ? matches[0] : null
}
const parseAuditObject = (audit, samples, startIndex = 1) => {
  if (!sameKeys(audit, ['audit_nonce', 'rows']) || !/^[a-f0-9]{64}$/.test(audit.audit_nonce) || !Array.isArray(audit.rows) || audit.rows.length !== samples.length) return null
  const compact = audit.rows.every((row) => sameKeys(row, ['sample_index', 'result', 'findings']))
  const legacy = audit.rows.every((row) => sameKeys(row, ['timestamp', 'session', 'path', 'result', 'findings']))
  if (!compact && !legacy) return null
  const rows = audit.rows.map((row, index) => {
    const sample = samples[index]
    if (compact ? row.sample_index !== startIndex + index : row.timestamp !== sample.timestamp || row.session !== sample.session || row.path !== sample.path) return null
    if (!['PASS', 'FAIL'].includes(row.result) || !Array.isArray(row.findings)) return null
    const findings = row.findings.map((finding) => {
      if (!sameKeys(finding, ['type', 'quote'])) return null
      if (!VIOLATION_TYPES.has(finding.type) || typeof finding.quote !== 'string' || finding.quote === '') return null
      if (finding.quote.includes('|') || /[\r\n]/.test(finding.quote)) return null
      const quote = canonicalFindingQuote(sample.answer, finding.quote)
      return quote == null ? null : { ...finding, quote }
    })
    if (findings.some((finding) => finding == null)) return null
    if (new Set(findings.map((finding) => finding.type)).size !== findings.length) return null
    if ((row.result === 'PASS') !== (findings.length === 0)) return null
    return {
      timestamp: sample.timestamp,
      session: sample.session,
      path: sample.path,
      result: row.result,
      findings: [...findings].sort((left, right) => VIOLATION_ORDER.get(left.type) - VIOLATION_ORDER.get(right.type)),
    }
  })
  return rows.some((row) => row == null) ? null : { auditNonce: audit.audit_nonce, rows }
}
const parseAudit = (value, manifest) => {
  if (typeof value !== 'string' || value === '' || value.length % 4 !== 0 || !/^[A-Za-z0-9+/]*={0,2}$/.test(value)) return null
  try {
    return parseAuditObject(JSON.parse(Buffer.from(value, 'base64').toString('utf8')), manifest.samples)
  } catch {
    return null
  }
}
const parseBatchAuditObject = (audit, manifest, batch, attemptNonce) => {
  if (!isNonce(attemptNonce)) return null
  const packet = withoutLegacyDigests(audit)
  if (!sameKeys(packet, ['audit_nonce', 'attempt_nonce', 'batch_index', 'range', 'rows'])) return null
  if (packet.attempt_nonce !== attemptNonce) return null
  if (packet.audit_nonce !== manifest.audit_nonce || packet.batch_index !== batch.index || !sameKeys(packet.range, ['start', 'end']) || packet.range.start !== batch.range.start || packet.range.end !== batch.range.end) return null
  return parseAuditObject({ audit_nonce: packet.audit_nonce, rows: packet.rows }, batchSamplesFor(manifest.samples, batch), batch.range.start)
}
const violationCounts = (rows) => {
  const counts = new Map()
  for (const row of rows) {
    for (const finding of row.findings) counts.set(finding.type, (counts.get(finding.type) ?? 0) + 1)
  }
  return [...counts.entries()].sort((left, right) => right[1] - left[1] || (left[0] < right[0] ? -1 : left[0] > right[0] ? 1 : 0))
}
const tableCell = (value) => String(value).replace(/\|/g, '／').replace(/[\r\n]+/g, ' ')
const shortestQuote = (findings) => findings
  .map((finding) => finding.quote)
  .sort((left, right) => left.length - right.length || (left < right ? -1 : left > right ? 1 : 0))[0]
const renderReport = (manifest, rows) => {
  const counts = violationCounts(rows)
  const violationCount = rows.filter((row) => row.result === 'FAIL').length
  const conclusion = violationCount === 0
    ? `本週抽樣 ${rows.length} 則，未命中證據層級違規。`
    : `本週抽樣 ${rows.length} 則，${violationCount} 則命中證據層級違規，最常見為 ${counts[0][0]}。`
  const top = counts.length === 0
    ? '無'
    : counts.slice(0, 2).map(([type, count]) => `- ${type}：${count}`).join('\n')
  const reportRows = rows.map((row) => {
    const types = row.findings.length === 0 ? '無' : row.findings.map((finding) => finding.type).join('、')
    const quote = row.findings.length === 0 ? '未命中' : shortestQuote(row.findings)
    const explanation = row.findings.length === 0 ? '未命中五種違規' : `命中 ${types}`
    return `| ${tableCell(row.timestamp)} | ${tableCell(row.session)} | ${tableCell(row.path)} | ${row.result} | ${types} | ${tableCell(quote)} | ${explanation} |`
  })
  return `${conclusion}\n\n## 重複違規 Top 2\n\n${top}\n\n## 數量\n\n- 抽樣數：${rows.length}\n- eligible：${manifest.eligible}\n- TP-style violation count：${violationCount}\n\n## 逐案核對\n\n${REPORT_TABLE_HEADER}\n${REPORT_TABLE_SEPARATOR}${reportRows.length === 0 ? '' : `\n${reportRows.join('\n')}`}\n\n## 限制\n\n${LIMITATIONS}\n`
}
const topViolationsFromReport = (report) => {
  const section = report.match(/## 重複違規 Top 2\n\n([\s\S]*?)\n\n## 數量/)?.[1]
  if (section == null || section === '無') return []
  const items = section.split('\n').map((line) => line.match(/^- ([a-z-]+)：(\d+)$/)).map((match) => match == null ? null : ({ type: match[1], count: Number(match[2]) }))
  return items.some((item) => item == null) ? [] : items
}
const packetFor = (date, reportPath, manifestPath, manifest, violationCount, topViolations, ok) => ({
  date,
  ok,
  report_path: reportPath,
  manifest_path: manifestPath,
  eligible: manifest?.eligible ?? null,
  sample_count: manifest?.samples.length ?? null,
  tp_style_violation_count: violationCount,
  top_violations: topViolations,
  audit_nonce: null,
  reaudit_sample_count: 0,
  reaudit_nonce: null,
  challenge: ok ? manifest?.challenge ?? null : null,
})
const parsePublication = (file, date, manifest) => {
  if (!fs.existsSync(file) || !isPrivateFile(file)) return null
  try {
    const publication = withoutLegacyDigests(JSON.parse(fs.readFileSync(file, 'utf8')))
    const v1Keys = ['date', 'report', 'eligible', 'sample_count', 'tp_style_violation_count', 'challenge']
    const v2Keys = ['schema_version', 'date', 'report', 'eligible', 'sample_count', 'tp_style_violation_count', 'top_violations', 'audit_nonce', 'reaudit_sample_count', 'reaudit_nonce', 'challenge']
    const batchedV2Keys = [...v2Keys, 'attempt_nonce']
    const isV2 = Object.hasOwn(publication, 'schema_version')
    const expectedV2Keys = isBatchedManifest(manifest) ? batchedV2Keys : v2Keys
    if (isV2 ? !sameKeys(publication, expectedV2Keys) || publication.schema_version !== 2 : !sameKeys(publication, v1Keys) || date >= EVIDENCE_V2_START_DATE) return null
    if ((Object.hasOwn(manifest, 'schema_version') ? 2 : 1) !== (isV2 ? 2 : 1)) return null
    if (publication.date !== date || publication.challenge !== manifest.challenge) return null
    if (typeof publication.report !== 'string') return null
    if (publication.eligible !== manifest.eligible || publication.sample_count !== manifest.samples.length) return null
    if (!Number.isInteger(publication.tp_style_violation_count) || publication.tp_style_violation_count < 0 || publication.tp_style_violation_count > manifest.samples.length) return null
    if (isV2) {
      if (!isNonce(publication.audit_nonce)) return null
      if (isBatchedManifest(manifest) && (!isNonce(publication.attempt_nonce) || publication.audit_nonce !== manifest.audit_nonce)) return null
      if (!Number.isInteger(publication.reaudit_sample_count) || publication.reaudit_sample_count < 0 || publication.reaudit_sample_count > publication.sample_count) return null
      if (publication.reaudit_sample_count === 0 ? publication.reaudit_nonce !== null : !isNonce(publication.reaudit_nonce) || publication.reaudit_nonce === publication.audit_nonce) return null
      if (!Array.isArray(publication.top_violations) || publication.top_violations.length > 2) return null
      if (!publication.top_violations.every((item) => sameKeys(item, ['type', 'count']) && VIOLATION_TYPES.has(item.type) && Number.isInteger(item.count) && item.count > 0 && item.count <= publication.tp_style_violation_count)) return null
      if (new Set(publication.top_violations.map((item) => item.type)).size !== publication.top_violations.length) return null
      if ((publication.tp_style_violation_count === 0) !== (publication.top_violations.length === 0)) return null
      const sortedTop = [...publication.top_violations].sort((left, right) => right.count - left.count || (left.type < right.type ? -1 : left.type > right.type ? 1 : 0))
      if (JSON.stringify(publication.top_violations) !== JSON.stringify(sortedTop)) return null
      const topSection = publication.report.match(/## 重複違規 Top 2\n\n([\s\S]*?)\n\n## 數量/)?.[1]
      const expectedTopSection = publication.top_violations.length === 0 ? '無' : publication.top_violations.map((item) => `- ${item.type}：${item.count}`).join('\n')
      if (topSection !== expectedTopSection) return null
    }
    return publication
  } catch {
    return null
  }
}
const verifiedPacket = (reports, date, expectedAttemptNonce = null) => {
  if (!hasVerifiedReport(reports, date)) return null
  const manifestPath = manifestPathFor(reports, date)
  const publicationPath = publicationPathFor(reports, date)
  const reportPath = reportPathFor(reports, date)
  const receiptPath = receiptPathFor(reports, date)
  const manifest = parseManifest(manifestPath, date)
  if (manifest == null || !batchArtifactsValid(reports, date, manifest)) return null
  const publication = parsePublication(publicationPath, date, manifest)
  if (publication == null) return null
  if (isBatchedManifest(manifest) && expectedAttemptNonce != null && publication.attempt_nonce !== expectedAttemptNonce) return null
  try {
    const receipt = withoutLegacyDigests(JSON.parse(fs.readFileSync(receiptPath, 'utf8')))
    const v1Keys = ['date', 'eligible', 'sample_count', 'tp_style_violation_count', 'challenge']
    const v2Keys = ['schema_version', 'date', 'eligible', 'sample_count', 'tp_style_violation_count', 'top_violations', 'audit_nonce', 'reaudit_sample_count', 'reaudit_nonce', 'challenge']
    const batchedV2Keys = [...v2Keys, 'attempt_nonce']
    const isV2 = Object.hasOwn(receipt, 'schema_version')
    const expectedV2Keys = isBatchedManifest(manifest) ? batchedV2Keys : v2Keys
    if (isV2 ? !sameKeys(receipt, expectedV2Keys) || receipt.schema_version !== 2 : !sameKeys(receipt, v1Keys) || date >= EVIDENCE_V2_START_DATE) return null
    if ((Object.hasOwn(publication, 'schema_version') ? 2 : 1) !== (isV2 ? 2 : 1)) return null
    if (receipt.date !== date || receipt.challenge !== publication.challenge) return null
    if (receipt.schema_version === 2 && (publication.schema_version !== 2 || (isBatchedManifest(manifest) && (receipt.attempt_nonce !== publication.attempt_nonce || !isNonce(receipt.attempt_nonce))) || receipt.audit_nonce !== publication.audit_nonce || receipt.reaudit_sample_count !== publication.reaudit_sample_count || receipt.reaudit_nonce !== publication.reaudit_nonce || JSON.stringify(receipt.top_violations) !== JSON.stringify(publication.top_violations))) return null
    if (receipt.eligible !== publication.eligible || receipt.sample_count !== publication.sample_count) return null
    if (receipt.tp_style_violation_count !== publication.tp_style_violation_count) return null
    if (fs.readFileSync(reportPath, 'utf8') !== publication.report) return null
    if (receipt.schema_version === 2 && fs.readFileSync(samplesTextPathFor(reports, date), 'utf8') !== renderSamplesText(manifest)) return null
    return {
      ...packetFor(date, reportPath, manifestPath, manifest, receipt.tp_style_violation_count, publication.top_violations ?? topViolationsFromReport(publication.report), true),
      audit_nonce: publication.audit_nonce ?? null,
      reaudit_sample_count: publication.reaudit_sample_count ?? 0,
      reaudit_nonce: publication.reaudit_nonce ?? null,
    }
  } catch {
    return null
  }
}
const uniqueTemporaryPath = (file) => `${file}.${process.pid}.${crypto.randomBytes(8).toString('hex')}.tmp`
const replaceFile = (file, content) => {
  const temporary = uniqueTemporaryPath(file)
  fs.writeFileSync(temporary, content, { flag: 'wx', mode: 0o600 })
  try {
    fs.renameSync(temporary, file)
    fs.chmodSync(file, 0o600)
  } finally {
    fs.rmSync(temporary, { force: true })
  }
}
const publishFirstWins = (file, content) => {
  const temporary = uniqueTemporaryPath(file)
  fs.writeFileSync(temporary, content, { flag: 'wx', mode: 0o600 })
  try {
    try {
      fs.linkSync(temporary, file)
      return true
    } catch (error) {
      if (error?.code !== 'EEXIST') throw error
      return false
    }
  } finally {
    fs.rmSync(temporary, { force: true })
  }
}
const materializePublication = (reports, date, publication) => {
  const manifestPath = manifestPathFor(reports, date)
  const reportPath = reportPathFor(reports, date)
  const receiptPath = receiptPathFor(reports, date)
  replaceFile(reportPath, publication.report)
  replaceFile(receiptPath, `${JSON.stringify({
    ...(publication.schema_version === 2 ? { schema_version: 2 } : {}),
    date,
    eligible: publication.eligible,
    sample_count: publication.sample_count,
    tp_style_violation_count: publication.tp_style_violation_count,
    ...(publication.schema_version === 2 ? {
      top_violations: publication.top_violations,
      audit_nonce: publication.audit_nonce,
      ...(Object.hasOwn(publication, 'attempt_nonce') ? { attempt_nonce: publication.attempt_nonce } : {}),
      reaudit_sample_count: publication.reaudit_sample_count,
      reaudit_nonce: publication.reaudit_nonce,
    } : {}),
    challenge: publication.challenge,
  })}\n`)
  return verifiedPacket(reports, date) ?? packetFor(date, reportPath, manifestPath, null, null, [], false)
}
const transcriptFiles = (root) => {
  if (!fs.existsSync(root)) return []
  const files = []
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name)
      if (entry.isDirectory()) visit(target)
      if (entry.isFile() && /^agent-.*\.jsonl$/.test(entry.name)) files.push(target)
    }
  }
  visit(root)
  return files
    .map((file) => {
      try {
        const stat = fs.statSync(file)
        return { file, size: stat.size, mtimeMs: stat.mtimeMs }
      } catch {
        return null
      }
    })
    .filter((entry) => entry != null)
    .sort((left, right) => right.mtimeMs - left.mtimeMs || (left.file < right.file ? -1 : left.file > right.file ? 1 : 0))
}
const sleepSync = (milliseconds) => {
  const signal = new Int32Array(new SharedArrayBuffer(4))
  Atomics.wait(signal, 0, 0, milliseconds)
}
const stableTranscriptText = (file) => {
  for (let attempt = 0; attempt < TRANSCRIPT_STABILITY_RETRIES; attempt += 1) {
    try {
      const before = fs.statSync(file)
      const text = fs.readFileSync(file, 'utf8')
      const after = fs.statSync(file)
      if (before.size === after.size && before.mtimeMs === after.mtimeMs && before.ctimeMs === after.ctimeMs) return text
    } catch {
      return null
    }
    if (attempt < TRANSCRIPT_STABILITY_RETRIES - 1) sleepSync(TRANSCRIPT_STABILITY_WAIT_MS)
  }
  return null
}
const parseTranscriptRows = (text) => {
  const rows = []
  for (const line of text.split('\n')) {
    if (line === '') continue
    try {
      rows.push(JSON.parse(line))
    } catch {
      return null
    }
  }
  return rows
}
const currentTranscriptCandidates = (root, boundaryFile) => {
  let boundaryMtimeMs
  let files
  try {
    boundaryMtimeMs = fs.statSync(boundaryFile).mtimeMs
    files = transcriptFiles(root)
  } catch {
    return null
  }
  return files.filter(({ mtimeMs }) => mtimeMs >= boundaryMtimeMs)
}
const snapshotCandidates = (candidates) => {
  const totalBytes = candidates.reduce((total, { size }) => total + size, 0)
  if (totalBytes > TRANSCRIPT_MAX_CANDIDATE_BYTES) return null
  const snapshots = []
  for (const { file } of candidates) {
    const text = stableTranscriptText(file)
    if (text == null) return null
    const rows = parseTranscriptRows(text)
    if (rows == null) return null
    snapshots.push({ file, rows })
  }
  return snapshots
}
const transcriptSnapshot = (root, boundaryFile) => {
  const candidates = currentTranscriptCandidates(root, boundaryFile)
  return candidates == null || candidates.length > TRANSCRIPT_MAX_CANDIDATE_FILES ? null : snapshotCandidates(candidates)
}
const restoreReadText = (content, expectedStartLine) => {
  if (typeof content !== 'string' || /^<tool_use_error>/m.test(content) || !Number.isSafeInteger(expectedStartLine) || expectedStartLine < 0 || expectedStartLine > MAX_READ_OFFSET) return null
  const lines = content.split('\n')
  const restored = []
  for (let index = 0; index < lines.length; index += 1) {
    const match = lines[index].match(/^(\d+)\t(.*)$/)
    const lineNumber = match == null ? null : Number(match[1])
    const expectedLine = expectedStartLine + index
    if (match == null || !Number.isSafeInteger(lineNumber) || !Number.isSafeInteger(expectedLine) || lineNumber !== expectedLine) return null
    restored.push(match[2])
  }
  return restored.join('\n')
}
const completeRestoredText = (restored) => {
  if (restored.size === 0) return null
  let firstLine = null
  let lastLine = null
  for (const lineNumber of restored.keys()) {
    if (!Number.isSafeInteger(lineNumber)) return null
    firstLine = firstLine == null ? lineNumber : Math.min(firstLine, lineNumber)
    lastLine = lastLine == null ? lineNumber : Math.max(lastLine, lineNumber)
  }
  const span = lastLine - firstLine + 1
  if (!Number.isSafeInteger(span) || span <= 0 || span > MAX_RECONSTRUCTED_LINES) return null
  const complete = Array.from({ length: span }, (_, index) => restored.get(firstLine + index))
  return complete.some((line) => line == null) ? null : complete.join('\n')
}
const isToolCallLike = (item) => {
  if (item == null || typeof item !== 'object') return false
  const type = typeof item.type === 'string' ? item.type.toLowerCase() : ''
  return type === 'tool_use' || type === 'tool_result' || type === 'function' || type.includes('tool') || type.includes('call') || ['name', 'input', 'arguments', 'tool_use_id'].some((key) => Object.hasOwn(item, key))
}
const auditB64FromSnapshot = (snapshots, samplesTextPath, expectedText, auditNonce) => {
  if (snapshots == null) return null
  for (const { rows } of snapshots) {
    const pending = new Map()
    const chunks = []
    const seenIds = new Set()
    let invalidTranscript = false
    let output = null
    let outputId = null
    let outputReceiptSeen = false
    for (const row of rows) {
      const content = row?.message?.content
      if (!Array.isArray(content)) continue
      for (const item of content) {
        if (output != null) {
          if (item?.type === 'tool_result' && outputId != null && item.tool_use_id === outputId && item.is_error !== true && !outputReceiptSeen) {
            outputReceiptSeen = true
            continue
          }
          if (isToolCallLike(item)) invalidTranscript = true
          if (invalidTranscript) break
          continue
        }
        if (isToolCallLike(item) && item?.type !== 'tool_use' && item?.type !== 'tool_result') {
          invalidTranscript = true
          break
        }
        if (item?.type === 'tool_use' && item?.name === 'Read' && item?.input?.file_path !== samplesTextPath) {
          invalidTranscript = true
          break
        }
        if (item?.type === 'tool_use' && item?.name === 'Read' && item?.input?.file_path === samplesTextPath && typeof item.id === 'string') {
          const inputKeys = ['file_path', ...(item.input.offset == null ? [] : ['offset']), ...(item.input.limit == null ? [] : ['limit'])]
          if (seenIds.has(item.id) || !sameKeys(item.input, inputKeys) || (item.input.offset != null && (!Number.isSafeInteger(item.input.offset) || item.input.offset < 0 || item.input.offset > MAX_READ_OFFSET)) || (item.input.limit != null && (!Number.isSafeInteger(item.input.limit) || item.input.limit <= 0 || item.input.limit > MAX_READ_LIMIT))) return null
          seenIds.add(item.id)
          pending.set(item.id, item.input)
          continue
        }
        if (item?.type === 'tool_result') {
          if (item.is_error === true || typeof item.tool_use_id !== 'string' || !pending.has(item.tool_use_id)) {
            invalidTranscript = true
            break
          }
          const input = pending.get(item.tool_use_id)
          const text = restoreReadText(item.content, input.offset ?? 1)
          if (text == null) return null
          chunks.push({ startLine: input.offset ?? 1, limit: input.limit ?? null, text })
          pending.delete(item.tool_use_id)
          continue
        }
        if (item?.type === 'tool_use' && item?.name === 'StructuredOutput' && sameKeys(item.input, ['audit_nonce', 'rows']) && item.input.audit_nonce === auditNonce) {
          if (pending.size !== 0 || chunks.length === 0) return null
          const ordered = [...chunks].sort((left, right) => left.startLine - right.startLine)
          const restored = new Map()
          for (const chunk of ordered) {
            const lines = chunk.text.split('\n')
            if (chunk.limit != null && lines.length > chunk.limit) return null
            for (let index = 0; index < lines.length; index += 1) {
              const lineNumber = chunk.startLine + index
              const existing = restored.get(lineNumber)
              if (existing != null && existing !== lines[index]) return null
              restored.set(lineNumber, lines[index])
            }
          }
          const restoredText = completeRestoredText(restored)
          if (restoredText == null) return null
          if (restoredText === expectedText) {
            output = Buffer.from(JSON.stringify(item.input), 'utf8').toString('base64')
            outputId = typeof item.id === 'string' ? item.id : null
            continue
          }
          return null
        }
        if (item?.type === 'tool_use') {
          invalidTranscript = true
          break
        }
      }
      if (invalidTranscript) break
    }
    if (!invalidTranscript && output != null) return output
  }
  return null
}
const batchAuditFromRows = (rows, manifest, batch, attemptNonce) => {
  const pending = new Map()
  const chunks = []
  const seenIds = new Set()
  let output = null
  let outputId = null
  let outputReceiptSeen = false
  let invalidTranscript = false
  for (const row of rows) {
    const content = row?.message?.content
    if (!Array.isArray(content)) continue
    for (const item of content) {
      if (output != null) {
        if (item?.type === 'tool_result' && outputId != null && item.tool_use_id === outputId && item.is_error !== true && !outputReceiptSeen) {
          outputReceiptSeen = true
          continue
        }
        if (isToolCallLike(item)) invalidTranscript = true
        if (invalidTranscript) break
        continue
      }
      if (isToolCallLike(item) && item?.type !== 'tool_use' && item?.type !== 'tool_result') {
        invalidTranscript = true
        break
      }
      if (item?.type === 'tool_use' && item?.name === 'Read') {
        if (item.input?.file_path !== batch.path || typeof item.id !== 'string') {
          invalidTranscript = true
          break
        }
        const inputKeys = ['file_path', ...(item.input.offset == null ? [] : ['offset']), ...(item.input.limit == null ? [] : ['limit'])]
        if (seenIds.has(item.id) || !sameKeys(item.input, inputKeys) || (item.input.offset != null && (!Number.isSafeInteger(item.input.offset) || item.input.offset < 0 || item.input.offset > MAX_READ_OFFSET)) || (item.input.limit != null && (!Number.isSafeInteger(item.input.limit) || item.input.limit <= 0 || item.input.limit > MAX_READ_LIMIT))) {
          invalidTranscript = true
          break
        }
        seenIds.add(item.id)
        pending.set(item.id, item.input)
        continue
      }
      if (item?.type === 'tool_result') {
        if (item.is_error === true || typeof item.tool_use_id !== 'string' || !pending.has(item.tool_use_id)) {
          invalidTranscript = true
          break
        }
        const input = pending.get(item.tool_use_id)
        const text = restoreReadText(item.content, input.offset ?? 1)
        if (text == null) {
          invalidTranscript = true
          break
        }
        chunks.push({ startLine: input.offset ?? 1, limit: input.limit ?? null, text })
        pending.delete(item.tool_use_id)
        continue
      }
      if (item?.type === 'tool_use' && item?.name === 'StructuredOutput') {
        if (pending.size !== 0 || chunks.length === 0) {
          invalidTranscript = true
          break
        }
        const ordered = [...chunks].sort((left, right) => left.startLine - right.startLine)
        const restored = new Map()
        for (const chunk of ordered) {
          const lines = chunk.text.split('\n')
          if (chunk.limit != null && lines.length > chunk.limit) {
            invalidTranscript = true
            break
          }
          for (let index = 0; index < lines.length; index += 1) {
            const lineNumber = chunk.startLine + index
            const existing = restored.get(lineNumber)
            if (existing != null && existing !== lines[index]) {
              invalidTranscript = true
              break
            }
            restored.set(lineNumber, lines[index])
          }
          if (invalidTranscript) break
        }
        if (invalidTranscript) break
        const restoredText = completeRestoredText(restored)
        if (restoredText == null || restoredText !== batch.expected_text) {
          invalidTranscript = true
          break
        }
        output = parseBatchAuditObject(item.input, manifest, batch, attemptNonce)
        outputId = typeof item.id === 'string' ? item.id : null
        if (output == null) invalidTranscript = true
        continue
      }
      if (item?.type === 'tool_use') {
        invalidTranscript = true
        break
      }
    }
    if (invalidTranscript) break
  }
  return invalidTranscript || pending.size !== 0 || output == null ? null : output
}
const batchAttemptMatches = (rows, manifest, batch, attemptNonce) => rows.some((row) =>
  Array.isArray(row?.message?.content) && row.message.content.some((item) =>
    item?.type === 'tool_use' &&
    item?.name === 'StructuredOutput' &&
    item?.input?.audit_nonce === manifest.audit_nonce &&
    item?.input?.attempt_nonce === attemptNonce &&
    item?.input?.batch_index === batch.index
  )
)
const batchTranscriptSnapshot = (root, boundaryFile, manifest, attemptNonce) => {
  const candidates = currentTranscriptCandidates(root, boundaryFile)
  if (candidates == null) return null
  const groups = new Map()
  for (const candidate of candidates) {
    const directory = path.dirname(candidate.file)
    groups.set(directory, [...(groups.get(directory) ?? []), candidate])
  }
  if (groups.size > TRANSCRIPT_MAX_CANDIDATE_FILES) return null
  for (const group of groups.values()) {
    if (group.length > TRANSCRIPT_MAX_CANDIDATE_FILES) continue
    const snapshots = snapshotCandidates(group)
    if (snapshots == null) continue
    const matches = manifest.batches.some((batch) => snapshots.some((snapshot) => batchAttemptMatches(snapshot.rows, manifest, batch, attemptNonce)))
    if (matches) return snapshots
  }
  return []
}
const batchAuditsFromSnapshot = (snapshots, manifest, attemptNonce) => {
  if (snapshots == null) return null
  const matches = []
  for (const batch of manifest.batches) {
    const batchWithText = { ...batch, expected_text: renderBatchText(manifest, batch) }
    let packet = null
    for (const snapshot of snapshots) {
      const candidate = batchAuditFromRows(snapshot.rows, manifest, batchWithText, attemptNonce)
      if (candidate != null) {
        packet = candidate
        break
      }
      if (batchAttemptMatches(snapshot.rows, manifest, batch, attemptNonce)) return null
    }
    if (packet == null) return null
    matches.push({ batch, packet })
  }
  const rows = matches
    .sort((left, right) => left.batch.index - right.batch.index)
    .flatMap(({ packet }) => packet.rows)
  return parseAuditObject({ audit_nonce: manifest.audit_nonce, rows }, manifest.samples)
}
const prepareReaudit = (reports, date, transcriptsRoot, auditNonce, attemptNonce = null) => {
  ensurePrivateDirectory(reports)
  const manifest = parseManifest(manifestPathFor(reports, date), date)
  const batched = isBatchedManifest(manifest)
  if (batched && !isNonce(attemptNonce)) return null
  const expectedReauditPath = reauditSamplesTextPathFor(reports, date, batched ? attemptNonce : null)
  const existingPath = expectedReauditPath
  if (fs.existsSync(existingPath)) {
    const existingText = fs.readFileSync(existingPath, 'utf8')
    const marker = existingText.match(/^=== BEGIN SAMPLE 1\/\d+ \[([a-f0-9]{16})\] ===$/m)?.[1]
    const count = Number(existingText.match(/^=== BEGIN SAMPLE 1\/(\d+) /m)?.[1])
    if (marker != null && Number.isInteger(count) && count > 0) {
      const nonceFile = `${existingPath}.nonce`
      if (fs.existsSync(nonceFile) && isPrivateFile(nonceFile)) {
        const nonce = fs.readFileSync(nonceFile, 'utf8').trim()
        if (/^[a-f0-9]{64}$/.test(nonce) && nonce.startsWith(marker)) return { date, reaudit_sample_count: count, reaudit_nonce: nonce }
      }
    }
    return null
  }
  const samplesTextPath = samplesTextPathFor(reports, date)
  if (manifest == null || transcriptsRoot == null || !fs.existsSync(samplesTextPath) || !batchArtifactsValid(reports, date, manifest)) return null
  const snapshots = batched && auditNonce !== manifest.audit_nonce
    ? []
    : batched
      ? batchTranscriptSnapshot(transcriptsRoot, samplesTextPath, manifest, attemptNonce)
      : transcriptSnapshot(transcriptsRoot, samplesTextPath)
  const auditPacket = batched
    ? batchAuditsFromSnapshot(snapshots, manifest, attemptNonce)
    : parseAudit(auditB64FromSnapshot(snapshots, samplesTextPath, renderSamplesText(manifest), auditNonce), manifest)
  if (auditPacket == null || auditPacket.auditNonce !== auditNonce) return null
  const passSamples = manifest.samples.filter((sample, index) => auditPacket.rows[index].result === 'PASS')
  if (passSamples.length === 0) return null
  const reauditNonce = crypto.randomBytes(32).toString('hex')
  const reauditText = renderSampleRowsText(passSamples, reauditNonce)
  const reauditSamplesTextPath = expectedReauditPath
  if (!publishFirstWins(reauditSamplesTextPath, reauditText)) return prepareReaudit(reports, date, transcriptsRoot, auditNonce, attemptNonce)
  publishFirstWins(`${reauditSamplesTextPath}.nonce`, `${reauditNonce}\n`)
  return {
    date,
    reaudit_sample_count: passSamples.length,
    reaudit_nonce: reauditNonce,
  }
}
const finalizeReport = (reports, date, auditB64, transcriptsRoot, auditNonce, attemptNonce, reauditNonce) => {
  ensurePrivateDirectory(reports)
  const existing = verifiedPacket(reports, date, attemptNonce)
  if (existing != null) return existing
  const manifestPath = manifestPathFor(reports, date)
  const publicationPath = publicationPathFor(reports, date)
  const reportPath = reportPathFor(reports, date)
  const manifest = parseManifest(manifestPath, date)
  if (manifest == null) return packetFor(date, reportPath, manifestPath, null, null, [], false)
  const batched = isBatchedManifest(manifest)
  const expectedReauditPath = reauditSamplesTextPathFor(reports, date, batched ? attemptNonce : null)
  if (batched && !batchArtifactsValid(reports, date, manifest)) return packetFor(date, reportPath, manifestPath, manifest, null, [], false)

  const published = parsePublication(publicationPath, date, manifest)
  if (published != null) {
    if (batched && published.attempt_nonce !== attemptNonce) return packetFor(date, reportPath, manifestPath, manifest, null, [], false)
    return materializePublication(reports, date, published)
  }
  if (fs.existsSync(publicationPath)) return packetFor(date, reportPath, manifestPath, manifest, null, [], false)
  const samplesTextPath = samplesTextPathFor(reports, date)
  if (!fs.existsSync(samplesTextPath) || fs.readFileSync(samplesTextPath, 'utf8') !== renderSamplesText(manifest)) {
    return packetFor(date, reportPath, manifestPath, manifest, null, [], false)
  }

  if (batched && (transcriptsRoot == null || auditB64 != null || auditNonce !== manifest.audit_nonce || !isNonce(attemptNonce) || !batchArtifactsValid(reports, date, manifest))) {
    return packetFor(date, reportPath, manifestPath, manifest, null, [], false)
  }
  const snapshots = transcriptsRoot == null
    ? []
    : batched
      ? batchTranscriptSnapshot(transcriptsRoot, samplesTextPath, manifest, attemptNonce)
      : transcriptSnapshot(transcriptsRoot, samplesTextPath)
  const auditPacket = batched
    ? batchAuditsFromSnapshot(snapshots, manifest, attemptNonce)
    : parseAudit(transcriptsRoot == null ? auditB64 : auditB64FromSnapshot(snapshots, samplesTextPath, renderSamplesText(manifest), auditNonce), manifest)
  if (auditPacket == null || auditPacket.auditNonce !== auditNonce) return packetFor(date, reportPath, manifestPath, manifest, null, [], false)
  const primaryPassSamples = manifest.samples.filter((sample, index) => auditPacket.rows[index].result === 'PASS')
  const reauditDeclared = reauditNonce != null
  let reauditPacket = null
  let reauditAuditNonce = null
  if (primaryPassSamples.length > 0 && Object.hasOwn(manifest, 'schema_version') && !reauditDeclared) return packetFor(date, reportPath, manifestPath, manifest, null, [], false)
  if (primaryPassSamples.length > 0 && reauditDeclared) {
    const reauditSamplesTextPath = expectedReauditPath
    if (transcriptsRoot == null || !/^[a-f0-9]{64}$/.test(reauditNonce ?? '') || reauditNonce === auditNonce || !fs.existsSync(reauditSamplesTextPath)) {
      return packetFor(date, reportPath, manifestPath, manifest, null, [], false)
    }
    const expectedReauditText = renderSampleRowsText(primaryPassSamples, reauditNonce)
    let actualReauditText
    try {
      actualReauditText = fs.readFileSync(reauditSamplesTextPath, 'utf8')
    } catch {
      return packetFor(date, reportPath, manifestPath, manifest, null, [], false)
    }
    if (actualReauditText !== expectedReauditText) return packetFor(date, reportPath, manifestPath, manifest, null, [], false)
    const reauditManifest = { samples: primaryPassSamples }
    const reauditAuditB64 = auditB64FromSnapshot(snapshots, reauditSamplesTextPath, expectedReauditText, reauditNonce)
    reauditPacket = parseAudit(reauditAuditB64, reauditManifest)
    if (reauditPacket == null || reauditPacket.auditNonce !== reauditNonce) return packetFor(date, reportPath, manifestPath, manifest, null, [], false)
    reauditAuditNonce = reauditNonce
  } else if (primaryPassSamples.length === 0 && reauditDeclared && reauditNonce !== '0') {
    return packetFor(date, reportPath, manifestPath, manifest, null, [], false)
  }
  let passIndex = 0
  const rows = auditPacket.rows.map((row) => {
    if (row.result === 'FAIL' || reauditPacket == null) return row
    const reauditRow = reauditPacket.rows[passIndex]
    passIndex += 1
    return reauditRow.result === 'PASS' ? row : reauditRow
  })
  const violationCount = rows.filter((row) => row.result === 'FAIL').length
  const topViolations = violationCounts(rows).slice(0, 2).map(([type, count]) => ({ type, count }))
  const report = renderReport(manifest, rows)
  const isV2 = Object.hasOwn(manifest, 'schema_version')
  const publication = {
    ...(isV2 ? { schema_version: 2 } : {}),
    date,
    report,
    eligible: manifest.eligible,
    sample_count: manifest.samples.length,
    tp_style_violation_count: violationCount,
    ...(isV2 ? {
      top_violations: topViolations,
      audit_nonce: auditNonce,
      ...(batched ? { attempt_nonce: attemptNonce } : {}),
      reaudit_sample_count: reauditPacket == null ? 0 : primaryPassSamples.length,
      reaudit_nonce: reauditAuditNonce,
    } : {}),
    challenge: manifest.challenge,
  }
  publishFirstWins(publicationPath, `${JSON.stringify(publication)}\n`)
  const winner = parsePublication(publicationPath, date, manifest)
  return winner == null
    ? packetFor(date, reportPath, manifestPath, manifest, null, [], false)
    : materializePublication(reports, date, winner)
}

const sampleMarker = (manifest, index, position) =>
  `=== ${position} SAMPLE ${index + 1}/${manifest.samples.length} [${manifest.challenge.slice(0, 16)}] ===`
const renderSampleRowsText = (samples, challenge, startIndex = 0, total = samples.length) => `${samples.map((sample, index) => [
  `=== BEGIN SAMPLE ${startIndex + index + 1}/${total} [${challenge.slice(0, 16)}] ===`,
  `timestamp: ${sample.timestamp}`,
  `session: ${sample.session}`,
  `path: ${sample.path}`,
  'answer:',
  sample.answer,
  `=== END SAMPLE ${startIndex + index + 1}/${total} [${challenge.slice(0, 16)}] ===`,
].join('\n')).join('\n\n')}\n`
const renderSamplesText = (manifest) => renderSampleRowsText(manifest.samples, manifest.challenge)
const renderBatchText = (manifest, batch) => renderSampleRowsText(batchSamplesFor(manifest.samples, batch), manifest.challenge, batch.range.start - 1, PRIMARY_SAMPLE_COUNT)
const batchArtifactsValid = (reports, date, manifest) => {
  if (!isBatchedManifest(manifest)) return true
  try {
    const combinedFile = samplesTextPathFor(reports, date)
    if (!fs.existsSync(combinedFile) || !isPrivateFile(combinedFile)) return false
    const combinedText = fs.readFileSync(combinedFile, 'utf8')
    const expectedCombinedText = renderSamplesText(manifest)
    if (combinedText !== expectedCombinedText) return false
    return manifest.batches.every((batch) => {
      const file = batchSamplesTextPathFor(reports, date, batch.index)
      if (batch.path !== file || !fs.existsSync(file) || !isPrivateFile(file)) return false
      return fs.readFileSync(file, 'utf8') === renderBatchText(manifest, batch)
    })
  } catch {
    return false
  }
}

const main = () => {
  const options = parseArgs(process.argv.slice(2))
  const date = options.date
  const root = options.root
  const reports = options.reports
  const mode = options.mode ?? 'sample'
  parseDate(date)
  if (typeof root !== 'string' || typeof reports !== 'string') throw new Error('root and reports are required')
  if (!['due', 'sample', 'prepare-reaudit', 'finalize'].includes(mode)) throw new Error('mode must be due, sample, prepare-reaudit, or finalize')
  if (mode === 'prepare-reaudit') {
    const packet = prepareReaudit(reports, date, options['audit-from-transcripts'], options['audit-nonce'], options['attempt-nonce'])
    process.stdout.write(`${JSON.stringify(packet ?? { date, reaudit_sample_count: 0, reaudit_nonce: null })}\n`)
    return
  }
  if (mode === 'finalize') {
    const transcriptsRoot = options['audit-from-transcripts']
    if (transcriptsRoot != null && options['audit-b64'] != null) throw new Error('audit-from-transcripts excludes audit-b64')
    process.stdout.write(`${JSON.stringify(finalizeReport(reports, date, options['audit-b64'], transcriptsRoot, options['audit-nonce'], options['attempt-nonce'], options['reaudit-nonce']))}\n`)
    return
  }

  const duePacket = buildDuePacket(reports, date)
  if (mode === 'due' || !duePacket.due) {
    process.stdout.write(`${JSON.stringify(duePacket)}\n`)
    return
  }

  const { manifest } = loadOrCreateManifest(root, reports, date)
  const samplesTextPath = samplesTextPathFor(reports, date)
  replaceFile(samplesTextPath, renderSamplesText(manifest))
  if (isBatchedManifest(manifest)) {
    manifest.batches.forEach((batch) => replaceFile(batch.path, renderBatchText(manifest, batch)))
  }
  const batched = isBatchedManifest(manifest)
  const auditNonce = manifest.audit_nonce ?? crypto.randomBytes(32).toString('hex')
  const attemptNonce = batched ? crypto.randomBytes(32).toString('hex') : null
  process.stdout.write(`${JSON.stringify({
    ...duePacket,
    audit_nonce: auditNonce,
    eligible: manifest.eligible,
    sample_count: manifest.samples.length,
    ...(batched ? { attempt_nonce: attemptNonce, batches: manifest.batches.map(({ members, ...batch }) => batch) } : {}),
    challenge: manifest.challenge,
  })}\n`)
}

main()
