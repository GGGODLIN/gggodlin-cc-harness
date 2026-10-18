import assert from 'node:assert/strict'
import { execFileSync, spawnSync } from 'node:child_process'
import { chmod, link, lstat, mkdir, mkdtemp, readFile, readdir, realpath, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

const scriptPath = join(dirname(fileURLToPath(import.meta.url)), 'plannotator-review.mjs')
const adapterCopies = new Map()

const replaceUnique = (source, marker, replacement) => {
  const occurrences = source.split(marker).length - 1
  assert.equal(occurrences, 1, `expected one marker occurrence: ${marker}`)
  const updated = source.replace(marker, replacement)
  assert.equal(updated.includes(marker), false, `marker was not replaced: ${marker}`)
  return updated
}

const createAdapterCopy = async (home, trialRoot, archifyTrialRoot, identity, timeoutMs) => {
  let source = await readFile(scriptPath, 'utf8')
  source = replaceUnique(source, "join(homedir(), 'Desktop/projects/.claude/trials/plannotator-visual-gate')", JSON.stringify(trialRoot))
  source = replaceUnique(source, "join(homedir(), 'Desktop/projects/.claude/trials/archify-visual-gate')", JSON.stringify(archifyTrialRoot))
  source = replaceUnique(source, "'v0.27.8'", JSON.stringify(identity.release))
  source = replaceUnique(source, "'b381ecbe1200b07db8c050715c0f2c035a44b73a'", JSON.stringify(identity.tagCommit))
  source = replaceUnique(source, "'plannotator 0.27.8'", JSON.stringify(identity.versionOutput))
  source = replaceUnique(source, "'1c2b42d660e4a7571813fb43839c79e3e9ca7720'", JSON.stringify('a'.repeat(40)))
  if (timeoutMs !== undefined) source = replaceUnique(source, '30 * 60 * 1000', String(timeoutMs))
  const adapterPath = join(home, 'adapter-copy.mjs')
  await writeFile(adapterPath, source, { mode: 0o700, flag: 'wx' })
  await chmod(adapterPath, 0o700)
  return adapterPath
}

const createProductionBoundaryCopy = async (home, trialRoot, archifyTrialRoot) => {
  let source = await readFile(scriptPath, 'utf8')
  source = replaceUnique(source, "join(homedir(), 'Desktop/projects/.claude/trials/plannotator-visual-gate')", JSON.stringify(trialRoot))
  source = replaceUnique(source, "join(homedir(), 'Desktop/projects/.claude/trials/archify-visual-gate')", JSON.stringify(archifyTrialRoot))
  source = replaceUnique(source, "'1c2b42d660e4a7571813fb43839c79e3e9ca7720'", JSON.stringify('a'.repeat(40)))
  const adapterPath = join(home, 'production-boundary-copy.mjs')
  await writeFile(adapterPath, source, { mode: 0o700, flag: 'wx' })
  await chmod(adapterPath, 0o700)
  return adapterPath
}

const runAdapter = (home, args, env = {}) => spawnSync(process.execPath, [adapterCopies.get(home), ...args], {
  encoding: 'utf8',
  env: { ...process.env, HOME: home, ...env },
})

const writeOwned = async (path, value, mode = 0o600) => {
  await writeFile(path, value, { mode, flag: 'wx' })
  await chmod(path, mode)
}

const createFixture = async (kind, { timeoutMs } = {}) => {
  const home = await realpath(await mkdtemp(join(tmpdir(), 'plannotator-review-home-')))
  const trialRoot = join(home, 'Desktop/projects/.claude/trials/plannotator-visual-gate')
  const archifyTrialRoot = join(home, 'Desktop/projects/.claude/trials/archify-visual-gate')
  const toolRoot = join(trialRoot, 'tool')
  const binaryPath = join(toolRoot, 'plannotator-darwin-arm64')
  const reviewsRoot = join(trialRoot, 'reviews')
  const invocationLog = join(home, 'invocations.jsonl')
  await mkdir(toolRoot, { recursive: true, mode: 0o700 })
  await chmod(trialRoot, 0o700)
  await chmod(toolRoot, 0o700)
  const binary = `#!/usr/bin/env node
import { appendFileSync, chmodSync, linkSync, mkdirSync, symlinkSync, writeFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
const args = process.argv.slice(2)
const resultPath = args[args.indexOf('--result-file') + 1]
const result = { decision: process.env.FAKE_DECISION ?? 'approved', ...(process.env.FAKE_FEEDBACK === undefined ? {} : { feedback: process.env.FAKE_FEEDBACK }) }
appendFileSync(process.env.FAKE_INVOCATION_LOG, JSON.stringify({ args }) + '\\n')
if (process.env.FAKE_TIMEOUT === '1') Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 4000)
if (process.env.FAKE_REPO_ROOT !== undefined) appendFileSync(process.env.FAKE_REPO_ROOT + '/file.txt', 'drift')
if (process.env.FAKE_SIGNAL === '1') process.kill(process.pid, 'SIGTERM')
if (process.env.FAKE_RESULT_SYMLINK === '1') symlinkSync(args[1], resultPath)
else if (process.env.FAKE_RESULT_HARDLINK === '1') linkSync(args[1], resultPath)
else if (process.env.FAKE_RESULT_DIRECTORY === '1') mkdirSync(resultPath)
else if (process.env.FAKE_MISSING_RESULT !== '1') writeFileSync(resultPath, process.env.FAKE_INVALID_RESULT === '1' ? 'not-json' : JSON.stringify(result), { mode: 0o600, flag: 'wx' })
if (process.env.FAKE_RESULT_MODE !== undefined) chmodSync(resultPath, parseInt(process.env.FAKE_RESULT_MODE, 8))
if (process.env.FAKE_REVIEW_MODE !== undefined) chmodSync(resultPath.replace(/result\\.json$/, ''), parseInt(process.env.FAKE_REVIEW_MODE, 8))
process.stdout.write(JSON.stringify(process.env.FAKE_MISMATCH_STDOUT === '1' ? { decision: 'dismissed' } : result))
if (process.env.FAKE_REPO_HEAD !== undefined) {
  appendFileSync(process.env.FAKE_REPO_HEAD + '/file.txt', 'head-drift')
  execFileSync('/usr/bin/git', ['add', 'file.txt'], { cwd: process.env.FAKE_REPO_HEAD })
  execFileSync('/usr/bin/git', ['commit', '-q', '-m', 'head drift'], { cwd: process.env.FAKE_REPO_HEAD })
}
if (process.env.FAKE_EXTRA_FILE === '1') writeFileSync(resultPath.replace(/result\\.json$/, 'extra.txt'), 'extra')
process.exitCode = process.env.FAKE_EXIT === undefined ? result.decision === 'approved' ? 0 : result.decision === 'annotated' || result.decision === 'dismissed' ? 1 : 2 : Number(process.env.FAKE_EXIT)
`
  await writeFile(binaryPath, binary, { mode: 0o700, flag: 'wx' })
  await chmod(binaryPath, 0o700)
  const identity = {
    schemaVersion: 1,
    release: 'fixture-release',
    tagCommit: 'fixture-tag',
    asset: 'plannotator-darwin-arm64',
    versionOutput: 'plannotator fixture',
  }
  await writeOwned(join(trialRoot, 'identity.json'), JSON.stringify(identity) + '\n')
  await mkdir(reviewsRoot, { recursive: true, mode: 0o700 })
  await chmod(reviewsRoot, 0o700)

  const outputRoot = join(archifyTrialRoot, 'artifacts', `${kind}-fixture`)
  await mkdir(outputRoot, { recursive: true, mode: 0o700 })
  await chmod(outputRoot, 0o700)
  const artifactPath = join(outputRoot, kind === 'actual-delta' ? 'delta.html' : 'artifact.html')
  const artifactBytes = Buffer.from(`<!DOCTYPE html><title>${kind}</title>\n`)
  await writeOwned(artifactPath, artifactBytes)
  const receiptPath = join(outputRoot, 'receipt.json')
  const receipt = {
    schemaVersion: 1,
    ok: true,
    mode: kind,
    type: kind === 'actual-delta' ? 'architecture' : 'workflow',
    pinnedSha: 'a'.repeat(40),
    outputRoot,
    artifact: artifactPath,
    archify: {
      ok: true,
      command: kind === 'actual-delta' ? 'compare' : 'deliver',
      type: kind === 'actual-delta' ? 'architecture' : 'workflow',
      artifact: { bytes: artifactBytes.length },
    },
    receipt: receiptPath,
  }
  if (kind === 'intent') {
    receipt.status = 'proposed'
    receipt.intent = { status: 'proposed', proofLevel: 'authored' }
    receipt.proofLevel = 'authored'
  } else {
    const repoRoot = join(home, 'repo')
    await mkdir(repoRoot, { recursive: true, mode: 0o700 })
    spawnSync('git', ['init', '-q'], { cwd: repoRoot })
    spawnSync('git', ['config', 'user.name', 'fixture'], { cwd: repoRoot })
    spawnSync('git', ['config', 'user.email', 'fixture@example.test'], { cwd: repoRoot })
    await writeFile(join(repoRoot, 'file.txt'), 'fixture\n')
    spawnSync('git', ['add', 'file.txt'], { cwd: repoRoot })
    spawnSync('git', ['commit', '-q', '-m', 'fixture'], { cwd: repoRoot })
    const headSha = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: repoRoot, encoding: 'utf8' }).stdout.trim()
    receipt.repoRoot = repoRoot
    receipt.headSha = headSha
    receipt.repository = { headSha, cleanBefore: true, cleanAfter: true }
    receipt.artifacts = { delta: { path: artifactPath, bytes: artifactBytes.length } }
  }
  await writeOwned(receiptPath, JSON.stringify(receipt) + '\n')
  const adapterPath = await createAdapterCopy(home, trialRoot, archifyTrialRoot, identity, timeoutMs)
  adapterCopies.set(home, adapterPath)
  return { home, kind, receiptPath, artifactPath, invocationLog, adapterPath, headSha: receipt.headSha }
}

test('intent and actual-delta use one public adapter interface to invoke the pinned fake binary', async () => {
  const fixtures = await Promise.all([createFixture('intent'), createFixture('actual-delta')])
  try {
    for (const fixture of fixtures) {
      const args = fixture.kind === 'intent'
        ? ['intent', fixture.receiptPath]
        : ['actual-delta', fixture.receiptPath, fixture.headSha]
      const result = runAdapter(fixture.home, args, { FAKE_INVOCATION_LOG: fixture.invocationLog })
      assert.equal(result.status, 0, result.stderr)
      const normalized = JSON.parse(result.stdout)
      assert.equal(normalized.reviewKind, fixture.kind)
      assert.equal(normalized.decision, 'approved')
      assert.equal(normalized.feedback, null)
      assert.equal(normalized.feedbackBytes, 0)
      const invocation = JSON.parse((await readFile(fixture.invocationLog, 'utf8')).trim())
      assert.deepEqual(invocation.args.slice(0, 6), [
        'annotate',
        fixture.artifactPath,
        '--gate',
        '--json',
        '--require-approval',
        '--result-file',
      ])
      assert.equal(basename(invocation.args[6]), 'result.json')
    }
  } finally {
    await Promise.all(fixtures.map(fixture => rm(fixture.home, { recursive: true, force: true })))
  }
})

test('adapter owns a private review directory and fixed result paths', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 0, result.stderr)
    const normalized = JSON.parse(result.stdout)
    const reviewRoot = dirname(normalized.receipt)
    assert.equal((await lstat(reviewRoot)).mode & 0o777, 0o700)
    assert.equal((await lstat(normalized.result.path)).mode & 0o777, 0o600)
    assert.equal((await lstat(normalized.receipt)).mode & 0o777, 0o600)
    assert.equal((await lstat(normalized.result.path)).nlink, 1)
    assert.equal((await lstat(normalized.receipt)).nlink, 1)
    assert.deepEqual((await readdir(reviewRoot)).sort(), ['receipt.json', 'result.json'])
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('production adapter reaches the fixed runtime boundary instead of temp HOME', async () => {
  const fixture = await createFixture('intent')
  try {
    const fixedMissingRoot = join(fixture.home, 'fixed-missing-runtime')
    const archifyTrialRoot = join(fixture.home, 'Desktop/projects/.claude/trials/archify-visual-gate')
    const adapterPath = await createProductionBoundaryCopy(fixture.home, fixedMissingRoot, archifyTrialRoot)
    adapterCopies.set(fixture.home, adapterPath)
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
    })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /Plannotator trial root is unavailable/)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('public adapter rejects caller-controlled output and binary arguments', async () => {
  const fixture = await createFixture('intent')
  try {
    for (const args of [
      ['intent', fixture.receiptPath, '/tmp/result.json'],
      ['intent', fixture.receiptPath, '--binary', '/tmp/fake'],
    ]) {
      const result = runAdapter(fixture.home, args, { FAKE_INVOCATION_LOG: fixture.invocationLog })
      assert.equal(result.status, 2)
      assert.match(result.stderr, /argument|usage/i)
    }
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('annotated and dismissed normalize to blocking decisions with exit one', async () => {
  const cases = [
    { kind: 'intent', decision: 'annotated', feedback: 'needs revision' },
    { kind: 'actual-delta', decision: 'dismissed' },
  ]
  const fixtures = await Promise.all(cases.map(item => createFixture(item.kind)))
  try {
    for (const fixture of fixtures) {
      const env = {
        FAKE_INVOCATION_LOG: fixture.invocationLog,
        FAKE_DECISION: fixture.kind === 'intent' ? 'annotated' : 'dismissed',
        ...(fixture.kind === 'intent' ? { FAKE_FEEDBACK: 'needs revision' } : {}),
      }
      const args = fixture.kind === 'intent'
        ? ['intent', fixture.receiptPath]
        : ['actual-delta', fixture.receiptPath, fixture.headSha]
      const result = runAdapter(fixture.home, args, env)
      assert.equal(result.status, 1, result.stderr)
      const normalized = JSON.parse(result.stdout)
      assert.equal(normalized.decision, fixture.kind === 'intent' ? 'annotated' : 'dismissed')
      assert.equal(normalized.transition, fixture.kind === 'intent' ? 'classification-required' : 'BLOCKED')
      assert.equal(normalized.ok, true)
      assert.equal(normalized.feedback, fixture.kind === 'intent' ? 'needs revision' : null)
      const auditPath = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/audit.jsonl')
      const row = JSON.parse((await readFile(auditPath, 'utf8')).trim())
      assert.equal(row.decision, normalized.decision)
      assert.equal(row.feedbackPresent, fixture.kind === 'intent')
    }
  } finally {
    await Promise.all(fixtures.map(fixture => rm(fixture.home, { recursive: true, force: true })))
  }
})

test('child exit two becomes gate-error instead of an approval', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_EXIT: '2',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.equal(normalized.ok, false)
    assert.equal(normalized.transition, 'BLOCKED')
    const row = JSON.parse((await readFile(join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/audit.jsonl'), 'utf8')).trim())
    assert.equal(row.decision, 'gate-error')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('rejects a wrapper receipt that is not owner-only', async () => {
  const fixture = await createFixture('intent')
  try {
    await chmod(fixture.receiptPath, 0o644)
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /owner|permission|receipt/i)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('rejects wrapper receipt symlinks and multiple links before launch', async () => {
  const hardLinkFixture = await createFixture('intent')
  const symlinkFixture = await createFixture('intent')
  try {
    await link(hardLinkFixture.receiptPath, `${hardLinkFixture.receiptPath}.hard`)
    const hardLinkResult = runAdapter(hardLinkFixture.home, ['intent', hardLinkFixture.receiptPath], { FAKE_INVOCATION_LOG: hardLinkFixture.invocationLog })
    assert.equal(hardLinkResult.status, 2)
    assert.match(hardLinkResult.stderr, /link/i)

    const symlinkPath = `${symlinkFixture.receiptPath}.symlink`
    await symlink(symlinkFixture.receiptPath, symlinkPath)
    const symlinkResult = runAdapter(symlinkFixture.home, ['intent', symlinkPath], { FAKE_INVOCATION_LOG: symlinkFixture.invocationLog })
    assert.equal(symlinkResult.status, 2)
    assert.match(symlinkResult.stderr, /symlink/i)
  } finally {
    await Promise.all([hardLinkFixture, symlinkFixture].map(fixture => rm(fixture.home, { recursive: true, force: true })))
  }
})

test('stale child receipt artifact sizes fail before launch', async () => {
  const fixture = await createFixture('intent')
  try {
    const receipt = JSON.parse(await readFile(fixture.receiptPath, 'utf8'))
    receipt.archify.artifact.bytes += 1
    await writeFile(fixture.receiptPath, JSON.stringify(receipt) + '\n')
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /artifact|size|child/i)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('rejects artifact hard links before launch', async () => {
  const fixture = await createFixture('intent')
  try {
    const artifactBackup = join(fixture.home, 'artifact-backup.html')
    await link(fixture.artifactPath, artifactBackup)
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /link|artifact/i)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('rejects non-owner-only output roots and artifacts before launch', async () => {
  const rootFixture = await createFixture('intent')
  const artifactFixture = await createFixture('intent')
  try {
    const rootReceipt = JSON.parse(await readFile(rootFixture.receiptPath, 'utf8'))
    await chmod(rootReceipt.outputRoot, 0o755)
    const rootResult = runAdapter(rootFixture.home, ['intent', rootFixture.receiptPath], { FAKE_INVOCATION_LOG: rootFixture.invocationLog })
    assert.equal(rootResult.status, 2)
    assert.match(rootResult.stderr, /output root|owner/i)

    const artifactReceipt = JSON.parse(await readFile(artifactFixture.receiptPath, 'utf8'))
    await chmod(artifactReceipt.artifact, 0o644)
    const artifactResult = runAdapter(artifactFixture.home, ['intent', artifactFixture.receiptPath], { FAKE_INVOCATION_LOG: artifactFixture.invocationLog })
    assert.equal(artifactResult.status, 2)
    assert.match(artifactResult.stderr, /artifact|owner/i)
  } finally {
    await Promise.all([rootFixture, artifactFixture].map(fixture => rm(fixture.home, { recursive: true, force: true })))
  }
})

test('intent requires proposed authored wrapper proof', async () => {
  const cases = [
    receipt => { receipt.status = 'accepted' },
    receipt => { receipt.intent.status = 'accepted' },
    receipt => { receipt.proofLevel = 'revision-pinned' },
  ]
  for (const mutate of cases) {
    const fixture = await createFixture('intent')
    try {
      const receipt = JSON.parse(await readFile(fixture.receiptPath, 'utf8'))
      mutate(receipt)
      await writeFile(fixture.receiptPath, JSON.stringify(receipt) + '\n')
      const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
      assert.equal(result.status, 2)
      assert.match(result.stderr, /proposed|authored|intent/i)
      assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
    } finally {
      await rm(fixture.home, { recursive: true, force: true })
    }
  }
})

test('actual-delta requires the delta artifact size binding', async () => {
  const fixture = await createFixture('actual-delta')
  try {
    const receipt = JSON.parse(await readFile(fixture.receiptPath, 'utf8'))
    receipt.artifacts.delta.bytes += 1
    await writeFile(fixture.receiptPath, JSON.stringify(receipt) + '\n')
    const result = runAdapter(fixture.home, ['actual-delta', fixture.receiptPath, fixture.headSha], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /artifact|size|binding/i)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('actual-delta requires artifacts.delta to equal the reviewed artifact', async () => {
  const fixture = await createFixture('actual-delta')
  try {
    const receipt = JSON.parse(await readFile(fixture.receiptPath, 'utf8'))
    receipt.artifacts.delta.path = join(fixture.home, 'wrong-delta.html')
    await writeFile(fixture.receiptPath, JSON.stringify(receipt) + '\n')
    const result = runAdapter(fixture.home, ['actual-delta', fixture.receiptPath, fixture.headSha], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /delta|artifact/i)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('actual-delta requires the expected final head SHA before launch', async () => {
  const fixture = await createFixture('actual-delta')
  try {
    const result = runAdapter(fixture.home, ['actual-delta', fixture.receiptPath, 'b'.repeat(40)], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /head/i)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('actual-delta refuses a dirty repository before launching Plannotator', async () => {
  const fixture = await createFixture('actual-delta')
  try {
    await writeFile(join(fixture.home, 'repo', 'dirty.txt'), 'dirty\n')
    const result = runAdapter(fixture.home, ['actual-delta', fixture.receiptPath, fixture.headSha], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /clean|repository/i)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('actual-delta receipt records clean expected repository state before and after review', async () => {
  const fixture = await createFixture('actual-delta')
  try {
    const result = runAdapter(fixture.home, ['actual-delta', fixture.receiptPath, fixture.headSha], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 0, result.stderr)
    const normalized = JSON.parse(result.stdout)
    assert.deepEqual(normalized.repository, {
      expectedHeadSha: fixture.headSha,
      headBefore: fixture.headSha,
      headAfter: fixture.headSha,
      cleanBefore: true,
      cleanAfter: true,
    })
    assert.equal(normalized.headSha, fixture.headSha)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('missing result is a gate-error with a blocking adapter receipt', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_MISSING_RESULT: '1',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.equal(normalized.ok, false)
    assert.equal(normalized.result.bytes, 0)
    assert.equal(JSON.parse(await readFile(normalized.receipt, 'utf8')).decision, 'gate-error')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('invalid result JSON is a gate-error', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_INVALID_RESULT: '1',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /invalid JSON/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('stdout and result disagreement is a gate-error', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_MISMATCH_STDOUT: '1',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /disagree/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('annotated results require non-empty feedback', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_DECISION: 'annotated',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /feedback/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('non-regular result paths are gate-errors without a release', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_RESULT_DIRECTORY: '1',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /regular|directory|result/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('symlinked result paths are rejected before reading bytes', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_RESULT_SYMLINK: '1',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /symlink/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('multiple-link result paths are rejected before parsing', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_RESULT_HARDLINK: '1',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /link/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('result files with group or world permissions are gate-errors', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_RESULT_MODE: '0644',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /mode|owner|permission/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('unexpected files in the adapter review directory are gate-errors', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_EXTRA_FILE: '1',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /unexpected|extra/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('child timeout becomes gate-error', async () => {
  const fixture = await createFixture('intent', { timeoutMs: 2000 })
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_TIMEOUT: '1',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.equal(normalized.timedOut, true)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('actual-delta repository dirtied during review becomes gate-error', async () => {
  const fixture = await createFixture('actual-delta')
  try {
    const result = runAdapter(fixture.home, ['actual-delta', fixture.receiptPath, fixture.headSha], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_REPO_ROOT: join(fixture.home, 'repo'),
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /repository.*changed|dirty/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('actual-delta head drift during review becomes gate-error', async () => {
  const fixture = await createFixture('actual-delta')
  try {
    const result = runAdapter(fixture.home, ['actual-delta', fixture.receiptPath, fixture.headSha], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_REPO_HEAD: join(fixture.home, 'repo'),
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /repository.*changed|head/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('non-executable pinned binaries fail closed before launch', async () => {
  const fixture = await createFixture('intent')
  try {
    const binaryPath = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/tool/plannotator-darwin-arm64')
    await chmod(binaryPath, 0o600)
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /executable|binary/i)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('pinned identity drift and missing binaries fail closed before launch', async () => {
  const cases = ['identity', 'missing']
  for (const kind of cases) {
    const fixture = await createFixture('intent')
    try {
      const binaryPath = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/tool/plannotator-darwin-arm64')
      const identityPath = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/identity.json')
      if (kind === 'identity') {
        const identity = JSON.parse(await readFile(identityPath, 'utf8'))
        identity.asset = 'replaced-binary'
        await writeFile(identityPath, JSON.stringify(identity) + '\n')
      } else {
        await rm(binaryPath)
      }
      const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
      assert.equal(result.status, 2)
      assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
    } finally {
      await rm(fixture.home, { recursive: true, force: true })
    }
  }
})

test('result and child exit status must agree exactly', async () => {
  const cases = [
    { decision: 'approved', exit: '1' },
    { decision: 'annotated', exit: '0', feedback: 'feedback' },
    { decision: 'dismissed', exit: '0' },
  ]
  for (const item of cases) {
    const fixture = await createFixture('intent')
    try {
      const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
        FAKE_INVOCATION_LOG: fixture.invocationLog,
        FAKE_DECISION: item.decision,
        FAKE_EXIT: item.exit,
        ...(item.feedback ? { FAKE_FEEDBACK: item.feedback } : {}),
      })
      assert.equal(result.status, 2)
      const normalized = JSON.parse(result.stdout)
      assert.equal(normalized.decision, 'gate-error')
      assert.match(normalized.error, /exit status|match/i)
    } finally {
      await rm(fixture.home, { recursive: true, force: true })
    }
  }
})

test('audit symlinks fail closed without writing through the link', async () => {
  const fixture = await createFixture('intent')
  try {
    const auditPath = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/audit.jsonl')
    const outsidePath = join(fixture.home, 'audit-target.jsonl')
    await writeFile(outsidePath, 'outside\n')
    await symlink(outsidePath, auditPath)
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.equal(await readFile(outsidePath, 'utf8'), 'outside\n')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('audit hard links fail closed without writing through the link', async () => {
  const fixture = await createFixture('intent')
  try {
    const auditPath = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/audit.jsonl')
    const outsidePath = join(fixture.home, 'audit-target.jsonl')
    await writeFile(outsidePath, 'outside\n')
    await link(outsidePath, auditPath)
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.equal(await readFile(outsidePath, 'utf8'), 'outside\n')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('audit FIFOs fail closed without hanging the adapter', async () => {
  const fixture = await createFixture('intent')
  try {
    const auditPath = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/audit.jsonl')
    const fifo = spawnSync('/usr/bin/mkfifo', [auditPath])
    assert.equal(fifo.status, 0, fifo.stderr?.toString())
    const started = Date.now()
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.ok(Date.now() - started < 2000)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('each started review appends exactly one audit row', async () => {
  const fixture = await createFixture('intent')
  try {
    for (let index = 0; index < 2; index += 1) {
      const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
      assert.equal(result.status, 0, result.stderr)
    }
    const auditPath = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/audit.jsonl')
    const rows = (await readFile(auditPath, 'utf8')).trim().split('\n').map(line => JSON.parse(line))
    assert.equal(rows.length, 2)
    assert.equal(rows.every(row => row.reviewKind === 'intent' && row.decision === 'approved'), true)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('actual-delta audit rows include the bound final head SHA', async () => {
  const fixture = await createFixture('actual-delta')
  try {
    const result = runAdapter(fixture.home, ['actual-delta', fixture.receiptPath, fixture.headSha], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 0, result.stderr)
    const auditPath = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/audit.jsonl')
    const row = JSON.parse((await readFile(auditPath, 'utf8')).trim())
    assert.deepEqual(Object.keys(row).sort(), ['decision', 'feedbackPresent', 'headSha', 'reviewKind', 'timestamp'].sort())
    assert.equal(row.headSha, fixture.headSha)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('normalized receipt exposes every bound path and UTF-8 feedback size', async () => {
  const fixture = await createFixture('intent')
  try {
    const feedback = '保留 ✓'
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_FEEDBACK: feedback,
    })
    assert.equal(result.status, 0, result.stderr)
    const normalized = JSON.parse(result.stdout)
    for (const alias of ['binaryPath', 'sourceReceiptPath', 'artifactPath', 'resultPath']) {
      assert.equal(Object.hasOwn(normalized, alias), false, alias)
    }
    const resultBytes = await readFile(normalized.result.path)
    assert.equal(normalized.binary.path, join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/tool/plannotator-darwin-arm64'))
    assert.equal(normalized.sourceReceipt.path, fixture.receiptPath)
    assert.equal(normalized.sourceReceipt.bytes, (await readFile(fixture.receiptPath)).length)
    assert.equal(normalized.artifact.path, fixture.artifactPath)
    assert.equal(normalized.artifact.bytes, (await readFile(fixture.artifactPath)).length)
    assert.equal(basename(normalized.result.path), 'result.json')
    assert.equal(normalized.result.bytes, resultBytes.length)
    assert.equal(normalized.feedback, feedback)
    assert.equal(normalized.feedbackBytes, Buffer.byteLength(feedback, 'utf8'))
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('child signals are normalized as gate-error', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_SIGNAL: '1',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.equal(normalized.childSignal, 'SIGTERM')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('forged receipts without a safe-wrapper child receipt fail before launch', async () => {
  const fixture = await createFixture('intent')
  try {
    const receipt = JSON.parse(await readFile(fixture.receiptPath, 'utf8'))
    delete receipt.archify
    await writeFile(fixture.receiptPath, JSON.stringify(receipt) + '\n')
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /wrapper|Archify|child receipt/i)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('broadly accessible Plannotator trial roots fail closed', async () => {
  const fixture = await createFixture('intent')
  try {
    const trialRoot = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate')
    await chmod(trialRoot, 0o755)
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /trial root|owner|mode/i)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('pre-existing review roots with broad permissions fail closed', async () => {
  const fixture = await createFixture('intent')
  try {
    const reviewsRoot = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/reviews')
    await chmod(reviewsRoot, 0o755)
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.match(result.stderr, /review root|owner|mode/i)
    assert.equal(await readFile(fixture.invocationLog, 'utf8').catch(() => ''), '')
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('adapter review root symlinks fail closed before creating output', async () => {
  const fixture = await createFixture('intent')
  try {
    const reviewsRoot = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/reviews')
    const outsideRoot = join(fixture.home, 'outside-reviews')
    await rm(reviewsRoot, { recursive: true, force: true })
    await mkdir(outsideRoot, { mode: 0o700 })
    await symlink(outsideRoot, reviewsRoot)
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], { FAKE_INVOCATION_LOG: fixture.invocationLog })
    assert.equal(result.status, 2)
    assert.equal((await readdir(outsideRoot)).length, 0)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('review directory permission drift becomes gate-error', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_REVIEW_MODE: '0755',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /review directory|owner|permission/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('dismissed results cannot carry feedback', async () => {
  const fixture = await createFixture('actual-delta')
  try {
    const result = runAdapter(fixture.home, ['actual-delta', fixture.receiptPath, fixture.headSha], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_DECISION: 'dismissed',
      FAKE_FEEDBACK: 'unexpected feedback',
    })
    assert.equal(result.status, 2)
    const normalized = JSON.parse(result.stdout)
    assert.equal(normalized.decision, 'gate-error')
    assert.match(normalized.error, /dismissed|feedback/i)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('approved with notes preserves feedback bytes and appends one minimal audit row', async () => {
  const fixture = await createFixture('intent')
  try {
    const result = runAdapter(fixture.home, ['intent', fixture.receiptPath], {
      FAKE_INVOCATION_LOG: fixture.invocationLog,
      FAKE_FEEDBACK: 'keep this guidance',
    })
    assert.equal(result.status, 0, result.stderr)
    const normalized = JSON.parse(result.stdout)
    const feedbackBytes = Buffer.byteLength('keep this guidance', 'utf8')
    assert.equal(normalized.decision, 'approved')
    assert.equal(normalized.transition, 'intent-accepted')
    assert.equal(normalized.feedback, 'keep this guidance')
    assert.equal(normalized.feedbackBytes, feedbackBytes)
    const persisted = JSON.parse(await readFile(normalized.receipt, 'utf8'))
    assert.equal(persisted.feedback, 'keep this guidance')
    const auditPath = join(fixture.home, 'Desktop/projects/.claude/trials/plannotator-visual-gate/audit.jsonl')
    const rows = (await readFile(auditPath, 'utf8')).trim().split('\n').map(line => JSON.parse(line))
    assert.equal(rows.length, 1)
    assert.deepEqual(Object.keys(rows[0]).sort(), ['decision', 'feedbackPresent', 'reviewKind', 'timestamp'].sort())
    assert.equal(rows[0].reviewKind, 'intent')
    assert.equal(rows[0].decision, 'approved')
    assert.equal(rows[0].feedbackPresent, true)
  } finally {
    await rm(fixture.home, { recursive: true, force: true })
  }
})

test('adapter receipt of each mode carries exactly the bound fields', async () => {
  const base = [
    'artifact', 'auditPath', 'binary', 'childExitStatus', 'childSignal', 'decision', 'feedback', 'feedbackBytes', 'ok',
    'receipt', 'result', 'reviewKind', 'schemaVersion', 'sourceReceipt', 'timedOut', 'transition',
  ]
  const fixtures = await Promise.all([createFixture('intent'), createFixture('actual-delta')])
  try {
    for (const fixture of fixtures) {
      const args = fixture.kind === 'intent' ? ['intent', fixture.receiptPath] : ['actual-delta', fixture.receiptPath, fixture.headSha]
      const result = runAdapter(fixture.home, args, { FAKE_INVOCATION_LOG: fixture.invocationLog })
      assert.equal(result.status, 0, result.stderr)
      const normalized = JSON.parse(result.stdout)
      assert.deepEqual(Object.keys(normalized).sort(), fixture.kind === 'intent' ? base : [...base, 'headSha', 'repoRoot', 'repository'].sort(), fixture.kind)
      assert.deepEqual(Object.keys(normalized.binary).sort(), ['asset', 'identityPath', 'path', 'release', 'schemaVersion', 'tagCommit', 'versionOutput'], fixture.kind)
    }
  } finally {
    await Promise.all(fixtures.map(fixture => rm(fixture.home, { recursive: true, force: true })))
  }
})
