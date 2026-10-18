#!/usr/bin/env node
import { constants } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { chmod, lstat, mkdir, mkdtemp, open, readdir, realpath, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { isAbsolute, join, relative, resolve, sep } from 'node:path'

const productionTrialRoot = join(homedir(), 'Desktop/projects/.claude/trials/plannotator-visual-gate')
const productionArchifyTrialRoot = join(homedir(), 'Desktop/projects/.claude/trials/archify-visual-gate')
const productionReviewTimeoutMs = 30 * 60 * 1000
const productionIdentity = {
  schemaVersion: 1,
  release: 'v0.27.8',
  tagCommit: 'b381ecbe1200b07db8c050715c0f2c035a44b73a',
  asset: 'plannotator-darwin-arm64',
  versionOutput: 'plannotator 0.27.8',
}
const shaPattern = /^[a-f0-9]{40}$/
const productionArchifyPinnedSha = '1c2b42d660e4a7571813fb43839c79e3e9ca7720'
const gitEnvironment = Object.fromEntries(Object.entries(process.env).filter(([name]) => !name.startsWith('GIT_')))
gitEnvironment.PATH = '/usr/bin:/bin'

const fail = message => { throw new Error(message) }

const hasSymlinkComponent = async target => {
  const absolute = resolve(target)
  const root = resolve(sep)
  const segments = relative(root, absolute).split(sep).filter(Boolean)
  let current = root
  for (const segment of segments) {
    current = join(current, segment)
    try {
      if ((await lstat(current)).isSymbolicLink()) return true
    } catch (error) {
      if (error?.code === 'ENOENT') return false
      throw error
    }
  }
  return false
}

const assertOwnedRegular = async (path, label, { ownerOnly = true, exactMode, executable = false } = {}) => {
  if (await hasSymlinkComponent(path)) fail(`${label} contains a symlink`)
  let metadata
  try {
    metadata = await lstat(path)
  } catch {
    fail(`${label} is unavailable`)
  }
  if (!metadata.isFile()) fail(`${label} must be a regular file`)
  if (metadata.nlink !== 1) fail(`${label} must have one link`)
  if (ownerOnly && (metadata.mode & 0o077) !== 0) fail(`${label} must be owner-only`)
  if (exactMode !== undefined && (metadata.mode & 0o777) !== exactMode) fail(`${label} must have mode ${exactMode.toString(8)}`)
  if (executable && (metadata.mode & 0o111) === 0) fail(`${label} must be executable`)
  if (typeof process.getuid === 'function' && metadata.uid !== process.getuid()) fail(`${label} owner is invalid`)
  return metadata
}

const assertOwnedDirectory = async (path, label) => {
  if (await hasSymlinkComponent(path)) fail(`${label} contains a symlink`)
  let metadata
  try {
    metadata = await lstat(path)
  } catch {
    fail(`${label} is unavailable`)
  }
  if (!metadata.isDirectory()) fail(`${label} must be a directory`)
  if ((metadata.mode & 0o777) !== 0o700) fail(`${label} must have mode 700`)
  if (typeof process.getuid === 'function' && metadata.uid !== process.getuid()) fail(`${label} owner is invalid`)
  let canonical
  try {
    canonical = await realpath(path)
  } catch {
    fail(`${label} is not canonical`)
  }
  if (canonical !== resolve(path)) fail(`${label} is not canonical`)
  return metadata
}

const ensureOwnedDirectory = async (path, label) => {
  if (await hasSymlinkComponent(path)) fail(`${label} contains a symlink`)
  let metadata
  try {
    metadata = await lstat(path)
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error
  }
  if (!metadata) {
    await mkdir(path, { recursive: true, mode: 0o700 })
    await chmod(path, 0o700)
  }
  return assertOwnedDirectory(path, label)
}

const readFileBytes = async (path, label, options) => {
  await assertOwnedRegular(path, label, options)
  let handle
  try {
    handle = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0))
    const metadata = await handle.stat()
    if (!metadata.isFile()) fail(`${label} must be a regular file`)
    if (metadata.nlink !== 1) fail(`${label} must have one link`)
    if (options?.ownerOnly !== false && (metadata.mode & 0o077) !== 0) fail(`${label} must be owner-only`)
    if (options?.exactMode !== undefined && (metadata.mode & 0o777) !== options.exactMode) fail(`${label} must have mode ${options.exactMode.toString(8)}`)
    if (options?.executable && (metadata.mode & 0o111) === 0) fail(`${label} must be executable`)
    if (typeof process.getuid === 'function' && metadata.uid !== process.getuid()) fail(`${label} owner is invalid`)
    return await handle.readFile()
  } finally {
    await handle?.close()
  }
}

const appendAudit = async (path, row) => {
  if (await hasSymlinkComponent(path)) fail('audit path contains a symlink')
  let handle
  try {
    handle = await open(path, constants.O_WRONLY | constants.O_APPEND | constants.O_CREAT | (constants.O_NOFOLLOW ?? 0) | (constants.O_NONBLOCK ?? 0), 0o600)
    const metadata = await handle.stat()
    if (!metadata.isFile()) fail('audit path must be a regular file')
    if (metadata.nlink !== 1) fail('audit path must have one link')
    if ((metadata.mode & 0o077) !== 0) fail('audit path must be owner-only')
    if (typeof process.getuid === 'function' && metadata.uid !== process.getuid()) fail('audit path owner is invalid')
    const bytes = Buffer.from(`${JSON.stringify(row)}\n`)
    const result = await handle.write(bytes)
    if (result.bytesWritten !== bytes.length) fail('audit append was incomplete')
    await handle.sync()
  } finally {
    await handle?.close()
  }
}

const writeAdapterReceipt = async (path, value) => {
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600, flag: 'wx' })
  await assertOwnedRegular(path, 'adapter receipt', { exactMode: 0o600 })
}

const parseJson = (bytes, label) => {
  try {
    return JSON.parse(bytes.toString('utf8'))
  } catch {
    fail(`${label} is invalid JSON`)
  }
}

const stableJson = value => {
  if (Array.isArray(value)) return value.map(stableJson)
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, stableJson(value[key])]))
  }
  return value
}

const assertWithinRoot = (path, root, label) => {
  const relativePath = relative(resolve(root), resolve(path))
  if (!relativePath || relativePath === '..' || relativePath.startsWith(`..${sep}`) || isAbsolute(relativePath)) fail(`${label} is outside the pinned root`)
}

const readRepoState = async root => {
  if (await hasSymlinkComponent(root)) fail('repository path contains a symlink')
  const head = spawnSync('/usr/bin/git', ['-C', root, 'rev-parse', 'HEAD'], { encoding: 'utf8', env: gitEnvironment })
  const status = spawnSync('/usr/bin/git', ['-C', root, 'status', '--porcelain'], { encoding: 'utf8', env: gitEnvironment })
  if (head.status !== 0 || status.status !== 0) fail('repository state is unavailable')
  return { headSha: head.stdout.trim(), clean: status.stdout === '' }
}

const readIdentity = async (trialRoot, binaryPath) => {
  const identityPath = join(trialRoot, 'identity.json')
  const identityBytes = await readFileBytes(identityPath, 'identity', { ownerOnly: false })
  const identity = parseJson(identityBytes, 'identity')
  await assertOwnedRegular(binaryPath, 'binary', { ownerOnly: false, executable: true })
  if (identity.schemaVersion !== productionIdentity.schemaVersion || identity.release !== productionIdentity.release || identity.tagCommit !== productionIdentity.tagCommit || identity.asset !== productionIdentity.asset || identity.versionOutput !== productionIdentity.versionOutput) {
    fail('Plannotator binary identity does not match the pinned identity')
  }
  const { schemaVersion, release, tagCommit, asset, versionOutput } = identity
  return { schemaVersion, release, tagCommit, asset, versionOutput, path: binaryPath, identityPath }
}

const readReceipt = async path => {
  const sourcePath = resolve(path)
  assertWithinRoot(sourcePath, productionArchifyTrialRoot, 'wrapper receipt')
  const bytes = await readFileBytes(sourcePath, 'wrapper receipt')
  const receipt = parseJson(bytes, 'wrapper receipt')
  if (receipt?.schemaVersion !== 1 || receipt.ok !== true || typeof receipt.receipt !== 'string' || !isAbsolute(receipt.receipt) || resolve(receipt.receipt) !== resolve(path)) fail('wrapper receipt is not bound to its input path')
  if (typeof receipt.type !== 'string' || !shaPattern.test(receipt.pinnedSha ?? '')) fail('wrapper receipt is missing safe-wrapper identity')
  const expectedCommand = receipt.mode === 'actual-delta' ? 'compare' : 'deliver'
  if (receipt.archify?.ok !== true || receipt.archify.command !== expectedCommand || receipt.archify.type !== receipt.type) {
    fail('wrapper receipt is missing a valid Archify child receipt')
  }
  if (typeof receipt.outputRoot !== 'string' || typeof receipt.artifact !== 'string' || !isAbsolute(receipt.outputRoot) || !isAbsolute(receipt.artifact)) fail('wrapper receipt is missing absolute paths')
  const outputRoot = resolve(receipt.outputRoot)
  assertWithinRoot(outputRoot, productionArchifyTrialRoot, 'wrapper output root')
  await assertOwnedDirectory(outputRoot, 'wrapper output root')
  const artifact = resolve(receipt.artifact)
  if (artifact.startsWith(`${outputRoot}${sep}`) === false || relative(outputRoot, artifact).includes(sep)) fail('wrapper artifact is not a direct child')
  const artifactBytes = await readFileBytes(artifact, 'artifact')
  if (receipt.archify.artifact.bytes !== undefined && receipt.archify.artifact.bytes !== artifactBytes.length) fail('Archify child receipt artifact size does not match')
  return { receipt, receiptBytes: bytes, artifactBytes, artifact }
}

const main = async () => {
  const values = process.argv.slice(2)
  const [reviewKind, sourcePath, expectedHeadSha] = values
  if (reviewKind !== 'intent' && reviewKind !== 'actual-delta') fail('usage: plannotator-review intent <wrapper-receipt> | actual-delta <wrapper-receipt> <expected-final-head-sha>')
  if ((reviewKind === 'intent' && values.length !== 2) || (reviewKind === 'actual-delta' && values.length !== 3)) fail('invalid arguments')
  const source = await readReceipt(sourcePath)
  if (source.receipt.mode !== reviewKind) fail('review kind does not match wrapper receipt')
  if (reviewKind === 'intent' && (source.receipt.status !== 'proposed' || source.receipt.intent?.status !== 'proposed' || source.receipt.proofLevel !== 'authored' || source.receipt.intent?.proofLevel !== 'authored')) {
    fail('intent wrapper receipt must be proposed and authored')
  }
  let repositoryBefore
  if (reviewKind === 'actual-delta') {
    if (!shaPattern.test(expectedHeadSha)) fail('expected final head SHA is invalid')
    if (source.receipt.headSha !== expectedHeadSha) fail('actual-delta receipt head does not match expected head')
    if (source.receipt.artifacts?.delta?.path !== source.artifact || (source.receipt.artifacts?.delta?.bytes !== undefined && source.receipt.artifacts.delta.bytes !== source.artifactBytes.length)) {
      fail('actual-delta receipt does not bind its delta artifact')
    }
    if (typeof source.receipt.repoRoot !== 'string' || !isAbsolute(source.receipt.repoRoot)) fail('actual-delta receipt is missing an absolute repository root')
    repositoryBefore = await readRepoState(source.receipt.repoRoot)
    if (repositoryBefore.headSha !== expectedHeadSha || !repositoryBefore.clean) fail('repository must be clean at the expected head')
  }
  if (source.receipt.pinnedSha !== productionArchifyPinnedSha) fail('Archify wrapper identity is not pinned')
  const trialRoot = productionTrialRoot
  await assertOwnedDirectory(trialRoot, 'Plannotator trial root')
  const binaryPath = join(trialRoot, 'tool/plannotator-darwin-arm64')
  const identity = await readIdentity(trialRoot, binaryPath)
  const reviewsRoot = join(trialRoot, 'reviews')
  await ensureOwnedDirectory(reviewsRoot, 'adapter review root')
  const reviewRoot = await mkdtemp(join(reviewsRoot, `${reviewKind}-`))
  await chmod(reviewRoot, 0o700)
  await assertOwnedDirectory(reviewRoot, 'adapter review directory')
  const resultPath = join(reviewRoot, 'result.json')
  const adapterReceiptPath = join(reviewRoot, 'receipt.json')
  let resultPreexists = false
  try {
    await lstat(resultPath)
    resultPreexists = true
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error
  }
  if (resultPreexists) fail('adapter result path already exists')
  const child = spawnSync(binaryPath, [
    'annotate',
    source.artifact,
    '--gate',
    '--json',
    '--require-approval',
    '--result-file',
    resultPath,
  ], {
    cwd: reviewRoot,
    encoding: 'utf8',
    timeout: productionReviewTimeoutMs,
  })
  const timedOut = child.error?.code === 'ETIMEDOUT'
  let errorMessage = child.error?.message ?? null
  let resultBytes = null
  let result = null
  let stdout = null
  const recordError = error => {
    if (errorMessage === null) errorMessage = error?.message ?? String(error)
  }
  try {
    const entries = await readdir(reviewRoot)
    if (entries.some(entry => entry !== 'result.json')) recordError(new Error(`unexpected review output: ${entries.join(', ')}`))
  } catch (error) {
    recordError(error)
  }
  if (errorMessage === null) {
    try {
      resultBytes = await readFileBytes(resultPath, 'Plannotator result', { exactMode: 0o600 })
      result = parseJson(resultBytes, 'Plannotator result')
    } catch (error) {
      recordError(error)
    }
  }
  if (errorMessage === null) {
    try {
      stdout = parseJson(Buffer.from(child.stdout ?? ''), 'Plannotator stdout')
      if (JSON.stringify(stableJson(stdout)) !== JSON.stringify(stableJson(result))) fail('Plannotator stdout and result disagree')
    } catch (error) {
      recordError(error)
    }
  }
  let repositoryAfter
  if (reviewKind === 'actual-delta') {
    try {
      repositoryAfter = await readRepoState(source.receipt.repoRoot)
      if (repositoryAfter.headSha !== expectedHeadSha || !repositoryAfter.clean) fail('repository changed during review')
    } catch (error) {
      recordError(error)
    }
  }
  try {
    await assertOwnedDirectory(reviewRoot, 'adapter review directory')
  } catch (error) {
    recordError(error)
  }
  const resultIsObject = result !== null && typeof result === 'object' && !Array.isArray(result)
  const rawFeedback = resultIsObject && Object.hasOwn(result, 'feedback') ? result.feedback : undefined
  const feedback = rawFeedback === undefined ? null : rawFeedback
  const feedbackIsString = typeof feedback === 'string'
  if (rawFeedback !== undefined && !feedbackIsString) recordError(new Error('Plannotator feedback must be a string'))
  const feedbackBuffer = feedbackIsString ? Buffer.from(feedback, 'utf8') : null
  const rawDecision = result?.decision
  const validDecision = rawDecision === 'approved' || rawDecision === 'annotated' || rawDecision === 'dismissed'
  const expectedExit = rawDecision === 'approved' ? 0 : rawDecision === 'annotated' || rawDecision === 'dismissed' ? 1 : null
  if (!validDecision) recordError(new Error('Plannotator result decision is invalid'))
  if (rawDecision === 'annotated' && (!feedbackIsString || feedback.length === 0)) recordError(new Error('annotated result requires feedback'))
  if (rawDecision === 'dismissed' && feedback !== null) recordError(new Error('dismissed result cannot contain feedback'))
  if (errorMessage === null && (child.status !== expectedExit || child.signal !== null)) recordError(new Error('Plannotator exit status does not match result'))
  const decision = errorMessage === null ? rawDecision : 'gate-error'
  const transition = decision === 'approved'
    ? reviewKind === 'intent' ? 'intent-accepted' : 'accepted'
    : decision === 'annotated' ? 'classification-required' : 'BLOCKED'
  const normalized = {
    schemaVersion: 1,
    ok: decision !== 'gate-error',
    reviewKind,
    decision,
    transition,
    ...(errorMessage !== null ? { error: errorMessage } : {}),
    ...(decision === 'gate-error' && validDecision ? { rawDecision } : {}),
    feedback,
    feedbackBytes: feedbackBuffer?.length ?? 0,
    binary: identity,
    sourceReceipt: {
      path: resolve(sourcePath),
      bytes: source.receiptBytes.length,
    },
    artifact: {
      path: source.artifact,
      bytes: source.artifactBytes.length,
    },
    ...(reviewKind === 'actual-delta' ? {
      repoRoot: source.receipt.repoRoot,
      repository: {
        expectedHeadSha,
        headBefore: repositoryBefore.headSha,
        headAfter: repositoryAfter?.headSha ?? null,
        cleanBefore: repositoryBefore.clean,
        cleanAfter: repositoryAfter?.clean ?? false,
      },
    } : {}),
    result: {
      path: resultPath,
      bytes: resultBytes?.length ?? 0,
    },
    receipt: adapterReceiptPath,
    childExitStatus: child.status,
    timedOut,
    childSignal: child.signal,
    ...(reviewKind === 'actual-delta' ? { headSha: expectedHeadSha } : {}),
  }
  const auditPath = join(trialRoot, 'audit.jsonl')
  let finalDecision = decision
  let finalError = errorMessage
  try {
    await appendAudit(auditPath, {
      timestamp: new Date().toISOString(),
      reviewKind,
      decision,
      feedbackPresent: feedback !== null,
      ...(reviewKind === 'actual-delta' ? { headSha: expectedHeadSha } : {}),
    })
  } catch (error) {
    finalDecision = 'gate-error'
    finalError = error?.message ?? String(error)
  }
  const finalTransition = finalDecision === 'approved'
    ? reviewKind === 'intent' ? 'intent-accepted' : 'accepted'
    : finalDecision === 'annotated' ? 'classification-required' : 'BLOCKED'
  const completed = {
    ...normalized,
    ok: finalDecision !== 'gate-error',
    decision: finalDecision,
    transition: finalTransition,
    ...(finalError !== null ? { error: finalError } : {}),
    auditPath,
  }
  await writeAdapterReceipt(adapterReceiptPath, completed)
  process.stdout.write(`${JSON.stringify(completed)}\n`)
  process.exitCode = finalDecision === 'approved' ? 0 : finalDecision === 'annotated' || finalDecision === 'dismissed' ? 1 : 2
}

main().catch(error => {
  process.stderr.write(`${error?.message ?? String(error)}\n`)
  process.exitCode = 2
})
