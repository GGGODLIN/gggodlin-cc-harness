#!/usr/bin/env node
import { chmodSync, existsSync, linkSync, lstatSync, mkdirSync, readFileSync, readdirSync, realpathSync, unlinkSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, isAbsolute, join, relative, resolve } from 'node:path'

const contract = 'MATT_TDD_DECISION v1'
const waiverReasons = new Set([
  'docs-only',
  'generated-only',
  'no-stable-seam',
  'non-executable-artifact'
])
const notStartedReasons = new Set([
  'preflight-only',
  'prerequisite-blocked',
  'user-deferred'
])

const fail = message => {
  process.stderr.write(`${message}\n`)
  process.exit(1)
}

const parseArgs = values => {
  const args = {}
  for (let index = 0; index < values.length; index += 1) {
    const key = values[index]
    if (!key.startsWith('--')) {
      fail(`unexpected argument: ${key}`)
    }
    const name = key.slice(2)
    const value = values[index + 1]
    if (!value || value.startsWith('--')) {
      fail(`missing value for --${name}`)
    }
    if (args[name] !== undefined) {
      fail(`duplicate argument: --${name}`)
    }
    args[name] = value
    index += 1
  }
  return args
}

const requireArg = (args, name) => {
  const value = args[name]
  if (!value) {
    fail(`missing --${name}`)
  }
  return value
}

const safeId = (value, label) => {
  if (!/^[A-Za-z0-9._-]+$/.test(value)) {
    fail(`${label} contains unsupported characters`)
  }
  if (value === '.' || value === '..') {
    fail(`${label} must not be dot or dot-dot`)
  }
  return value
}

const rootDir = () => resolve(process.env.MATT_TDD_ROOT ?? join(homedir(), '.claude', 'logs', 'matt-tdd'))

const runDir = args => {
  const root = rootDir()
  const target = resolve(
    root,
    safeId(requireArg(args, 'session'), 'session'),
    safeId(requireArg(args, 'run'), 'run')
  )
  const pathFromRoot = relative(root, target)
  if (!pathFromRoot || pathFromRoot.startsWith('..') || isAbsolute(pathFromRoot)) {
    fail('resolved run directory must stay under the control root')
  }
  return target
}

const manifestPath = args => join(runDir(args), 'decision.json')

const ensureDirectory = path => {
  mkdirSync(path, { recursive: true, mode: 0o700 })
  const details = lstatSync(path)
  if (details.isSymbolicLink() || !details.isDirectory()) {
    fail(`control directory must be a regular directory: ${path}`)
  }
  chmodSync(path, 0o700)
}

const assertControlFile = path => {
  const details = lstatSync(path)
  if (details.isSymbolicLink() || !details.isFile()) {
    fail(`manifest must be a regular control file: ${path}`)
  }
  if (details.uid !== process.getuid()) {
    fail('manifest must be owned by the current user')
  }
  if ((details.mode & 0o077) !== 0) {
    fail('manifest must be owner-only')
  }
}

const ensureRunDirectory = args => {
  const root = rootDir()
  const sessionDirectory = resolve(root, safeId(requireArg(args, 'session'), 'session'))
  const target = runDir(args)
  ensureDirectory(root)
  ensureDirectory(sessionDirectory)
  ensureDirectory(target)
  return target
}

const writeAtomicJson = (args, value) => {
  const path = join(ensureRunDirectory(args), 'decision.json')
  if (existsSync(path)) {
    assertControlFile(path)
    fail('decision manifest already exists for this session run')
  }
  const temporary = `${path}.${process.pid}.${Date.now()}.tmp`
  try {
    writeFileSync(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600, flag: 'wx' })
    chmodSync(temporary, 0o600)
    try {
      linkSync(temporary, path)
    } catch (error) {
      if (error?.code === 'EEXIST') {
        fail('decision manifest already exists for this session run')
      }
      throw error
    }
  } finally {
    if (existsSync(temporary)) {
      unlinkSync(temporary)
    }
  }
}

const stripTicks = value => {
  const trimmed = value.trim()
  return trimmed.startsWith('`') && trimmed.endsWith('`')
    ? trimmed.slice(1, -1).trim()
    : trimmed
}

const fieldValues = (section, name) => {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return [...section.matchAll(new RegExp(`^\\*\\*${escaped}:\\*\\*\\s*(.*)$`, 'gmi'))]
    .map(match => stripTicks(match[1]))
}

const markdownFiles = path => {
  const target = resolve(path)
  if (!existsSync(target)) {
    fail(`ticket path does not exist: ${target}`)
  }
  const details = lstatSync(target)
  if (details.isSymbolicLink()) {
    fail(`ticket path must not be a symlink: ${target}`)
  }
  const segments = target.split('/').filter(Boolean)
  if (details.isFile()) {
    const changeIndex = segments.lastIndexOf('changes')
    if (basename(target) !== 'tasks.md' || changeIndex < 1 || segments[changeIndex - 1] !== 'openspec' || changeIndex !== segments.length - 3) {
      fail('ticket path must be a canonical ticket source: openspec/changes/<change>/tasks.md')
    }
    return [target]
  }
  if (!details.isDirectory()) {
    fail(`ticket path must be a file or directory: ${target}`)
  }
  const scratchIndex = segments.lastIndexOf('.scratch')
  if (basename(target) !== 'issues' || scratchIndex < 0 || scratchIndex !== segments.length - 3) {
    fail('ticket path must be a canonical ticket source: .scratch/<feature>/issues')
  }
  const files = []
  const visit = directory => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const entryPath = join(directory, entry.name)
      if (entry.isSymbolicLink()) {
        fail(`ticket directory entry must not be a symlink: ${entryPath}`)
      }
      if (entry.isDirectory()) {
        if (entry.name.endsWith('.md')) {
          fail(`ticket directory entry must be a regular Markdown file: ${entryPath}`)
        }
        visit(entryPath)
        continue
      }
      if (entry.name.endsWith('.md')) {
        if (!entry.isFile()) {
          fail(`ticket directory entry must be a regular Markdown file: ${entryPath}`)
        }
        files.push(entryPath)
      }
    }
  }
  visit(target)
  return files.sort()
}

const parseTickets = ticketPath => {
  const tickets = []
  const files = markdownFiles(ticketPath)
  const sourceIsFile = lstatSync(resolve(ticketPath)).isFile()
  for (const file of files) {
    const content = readFileSync(file, 'utf8')
    const headings = [...content.matchAll(/^(#{1,3})\s+(\d+)\s+[—-]\s+(.+)$/gm)]
    const numericHeadings = [...content.matchAll(/^#{1,3}\s+\d+\b.*$/gm)]
    if (numericHeadings.length !== headings.length) {
      const malformedHeading = numericHeadings.find(heading => !/^(#{1,3})\s+(\d+)\s+[—-]\s+(.+)$/.test(heading[0]))
      if (malformedHeading) {
        const lineNumber = content.slice(0, malformedHeading.index ?? 0).split('\n').length
        const expectedShape = sourceIsFile ? '## <NN> — <title>' : '# <NN> — <title>'
        fail(`${sourceIsFile ? 'malformed ticket section' : 'malformed ticket file'}: ${file}: line ${lineNumber}: "${malformedHeading[0]}"; expected canonical shape: ${expectedShape}`)
      }
      fail(`${sourceIsFile ? 'malformed ticket section' : 'malformed ticket file'}: ${file}`)
    }
    if (headings.length === 0) {
      fail(`malformed ticket file: ${file}`)
    }
    for (let index = 0; index < headings.length; index += 1) {
      const heading = headings[index]
      const section = content.slice(heading.index ?? 0, headings[index + 1]?.index ?? content.length)
      const id = heading[2].padStart(2, '0')
      const families = [
        { name: 'TDD', seam: 'TDD seam', waiver: 'TDD waiver', approval: 'TDD waiver approved' },
        { name: 'Tests', seam: 'Test seam', waiver: 'Test waiver', approval: 'Test waiver approved' }
      ].map(family => ({
        ...family,
        decisions: fieldValues(section, family.name),
        seams: fieldValues(section, family.seam),
        reasons: fieldValues(section, family.waiver),
        approvals: fieldValues(section, family.approval)
      }))
      const used = families.filter(family => family.decisions.length || family.seams.length || family.reasons.length || family.approvals.length)
      if (used.length > 1) {
        fail(`ticket ${id}: mixed TDD and Tests fields`)
      }
      const family = used[0] ?? families[0]
      const decisions = family.decisions
      const seams = family.seams
      const reasons = family.reasons
      const approvals = family.approvals
      if (decisions.length === 0 || !decisions[0]) {
        fail(`ticket ${id}: ${family.name} classification is required`)
      }
      if (decisions.length !== 1) {
        fail(`ticket ${id}: exactly one ${family.name} classification is required`)
      }
      const decision = decisions[0]
      if (!['required', 'waived'].includes(decision)) {
        fail(`ticket ${id}: ${family.name} must be required or waived`)
      }
      if (decision === 'required') {
        if (seams.length !== 1 || !seams[0]) {
          fail(`ticket ${id}: required ${family.name} needs exactly one non-empty ${family.seam}`)
        }
        if (reasons.length !== 0 || approvals.length !== 0) {
          fail(`ticket ${id}: required ${family.name} forbids waiver fields`)
        }
        tickets.push({ id, decision, seam: seams[0] })
        continue
      }
      if (seams.length !== 0) {
        fail(`ticket ${id}: waived ${family.name} forbids seam fields`)
      }
      if (reasons.length !== 1 || !waiverReasons.has(reasons[0])) {
        fail(`ticket ${id}: waived ${family.name} needs exactly one closed waiver reason`)
      }
      if (approvals.length !== 1 || approvals[0] !== 'ticket-breakdown-user-approved') {
        fail(`ticket ${id}: waived ${family.name} needs exactly one approved waiver from ticket-breakdown-user-approved`)
      }
      tickets.push({ id, decision, reason: reasons[0], approval: approvals[0] })
    }
  }
  if (tickets.length === 0) {
    fail('no ticket headings found')
  }
  tickets.sort((left, right) => left.id.localeCompare(right.id))
  const ids = new Set()
  for (const ticket of tickets) {
    const logicalId = ticket.id.replace(/^0+(?=\d)/, '')
    if (ids.has(logicalId)) {
      fail(`duplicate ticket id: ${ticket.id}`)
    }
    ids.add(logicalId)
  }
  return tickets
}

const readManifest = args => {
  const path = manifestPath(args)
  if (!existsSync(path)) {
    fail('decision manifest is missing')
  }
  assertControlFile(path)
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    fail('decision manifest is malformed')
  }
}

const assertExactKeys = (value, keys, label) => {
  const actual = Object.keys(value).sort()
  const expected = [...keys].sort()
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) {
    fail(`${label} has unexpected fields`)
  }
}

const validateManifest = (manifest, args) => {
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) {
    fail('decision manifest is malformed')
  }
  if (manifest.contract !== contract) {
    fail('decision manifest contract is invalid')
  }
  if (manifest.session_id !== requireArg(args, 'session') || manifest.run_id !== requireArg(args, 'run')) {
    fail('decision manifest is not bound to this session run')
  }
  if (!Array.isArray(manifest.tickets)) {
    fail('decision manifest tickets are malformed')
  }
  if (manifest.status === 'not-started') {
    assertExactKeys(manifest, ['contract', 'status', 'reason', 'session_id', 'run_id', 'tickets'], 'not-started manifest')
    if (!notStartedReasons.has(manifest.reason) || manifest.tickets.length !== 0) {
      fail('not-started manifest needs a closed reason and no tickets')
    }
    return { status: manifest.status, requiredCount: 0, ticketCount: 0 }
  }
  if (manifest.status !== 'started') {
    fail('decision manifest status is invalid')
  }
  // tickets_source 讓 implement 派工閘門判斷「這張票屬於這一批」；沒有這欄的舊 manifest 照舊有效。
  // 缺 testing_mode 是舊 manifest，讀成 tdd。鍵在但值非法不能用 falsy 判斷，否則 null 會被當成缺欄。
  const startedKeys = ['contract', 'status', 'session_id', 'run_id', 'tickets']
  if ('tickets_source' in manifest) {
    startedKeys.push('tickets_source')
  }
  if ('testing_mode' in manifest) {
    startedKeys.push('testing_mode')
  }
  assertExactKeys(manifest, startedKeys, 'started manifest')
  const testingMode = readTestingMode(manifest)
  if (manifest.tickets.length === 0) {
    fail('started manifest must cover at least one ticket')
  }
  const ids = new Set()
  let requiredCount = 0
  for (const ticket of manifest.tickets) {
    if (!ticket || typeof ticket !== 'object' || Array.isArray(ticket)) {
      fail('decision manifest ticket is malformed')
    }
    if (typeof ticket.id !== 'string') {
      fail('decision manifest ticket id must be a string')
    }
    if (!/^[0-9]+$/.test(ticket.id)) {
      fail('decision manifest ticket is malformed')
    }
    const logicalId = ticket.id.replace(/^0+(?=\d)/, '')
    if (ids.has(logicalId)) {
      fail(`duplicate ticket id: ${ticket.id}`)
    }
    ids.add(logicalId)
    if (ticket.decision === 'required') {
      assertExactKeys(ticket, ['id', 'decision', 'seam'], `ticket ${ticket.id}`)
      if (typeof ticket.seam !== 'string' || !ticket.seam.trim()) {
        fail(`ticket ${ticket.id}: required TDD needs a non-empty seam`)
      }
      requiredCount += 1
      continue
    }
    if (ticket.decision !== 'waived') {
      fail(`ticket ${ticket.id}: decision must be required or waived`)
    }
    assertExactKeys(ticket, ['id', 'decision', 'reason', 'approval'], `ticket ${ticket.id}`)
    if (!waiverReasons.has(ticket.reason) || ticket.approval !== 'ticket-breakdown-user-approved') {
      fail(`ticket ${ticket.id}: waiver is invalid or unapproved`)
    }
  }
  const tddRequiredCount = testingMode === 'regression-closeout' ? 0 : requiredCount
  return { status: manifest.status, testingMode, requiredCount, tddRequiredCount, ticketCount: manifest.tickets.length }
}

const testingModes = new Set(['tdd', 'regression-closeout'])

const selectedTestingMode = args => {
  if (!('testing-mode' in args)) {
    return 'tdd'
  }
  const mode = args['testing-mode']
  if (!testingModes.has(mode)) {
    fail('testing-mode must be tdd or regression-closeout')
  }
  return mode
}

const readTestingMode = manifest => {
  if (!('testing_mode' in manifest)) {
    return 'tdd'
  }
  if (typeof manifest.testing_mode !== 'string' || !testingModes.has(manifest.testing_mode)) {
    fail('testing_mode must be tdd or regression-closeout')
  }
  return manifest.testing_mode
}

const startedModeFacts = result => result.status === 'started'
  ? { testing_mode: result.testingMode, tdd_required_count: result.tddRequiredCount }
  : {}

const initAction = args => {
  const testingMode = selectedTestingMode(args)
  const tickets = parseTickets(requireArg(args, 'tickets'))
  const manifest = {
    contract,
    status: 'started',
    testing_mode: testingMode,
    session_id: requireArg(args, 'session'),
    run_id: requireArg(args, 'run'),
    tickets_source: realpathSync(resolve(requireArg(args, 'tickets'))),
    tickets
  }
  const result = validateManifest(manifest, args)
  writeAtomicJson(args, manifest)
  process.stdout.write(`${JSON.stringify({ status: 'started', testing_mode: result.testingMode, required_count: result.requiredCount, tdd_required_count: result.tddRequiredCount, manifest: manifestPath(args), ticket_count: result.ticketCount })}\n`)
}

const notStartedAction = args => {
  const reason = requireArg(args, 'reason')
  if (!notStartedReasons.has(reason)) {
    fail('not-started decision needs a closed not-started reason')
  }
  const manifest = {
    contract,
    status: 'not-started',
    reason,
    session_id: requireArg(args, 'session'),
    run_id: requireArg(args, 'run'),
    tickets: []
  }
  validateManifest(manifest, args)
  writeAtomicJson(args, manifest)
  process.stdout.write(`${JSON.stringify({ status: 'not-started', manifest: manifestPath(args), reason })}\n`)
}

const validateAction = args => {
  const result = validateManifest(readManifest(args), args)
  process.stdout.write(`${JSON.stringify({ status: result.status, valid: true, required_count: result.requiredCount, ...startedModeFacts(result), ticket_count: result.ticketCount, manifest: manifestPath(args) })}\n`)
}

const consumeAction = args => {
  const result = validateManifest(readManifest(args), args)
  unlinkSync(manifestPath(args))
  process.stdout.write(`${JSON.stringify({ status: result.status, consumed: true, required_count: result.requiredCount, ...startedModeFacts(result), ticket_count: result.ticketCount })}\n`)
}

const action = process.argv[2]
const args = parseArgs(process.argv.slice(3))
const actions = {
  init: initAction,
  'not-started': notStartedAction,
  validate: validateAction,
  consume: consumeAction
}

if (!actions[action]) {
  fail(`unknown action: ${action ?? ''}`)
}

actions[action](args)
