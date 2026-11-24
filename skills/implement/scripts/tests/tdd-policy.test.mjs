// 本檔在契約測試底下；跑法：node --test ~/.claude/skills/implement/scripts/tests/tdd-policy.test.mjs
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { chmodSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

// 跟著測試檔所在位置找 policy：寫死 ~/.claude 路徑時，在 worktree 跑測試會測到 live 那份。
const policy = fileURLToPath(new URL('../tdd-policy.mjs', import.meta.url))

const createFixture = () => {
  const root = mkdtempSync(join(tmpdir(), 'matt-tdd-policy-'))
  const tickets = join(root, 'openspec', 'changes', 'change', 'tasks.md')
  mkdirSync(join(root, 'openspec', 'changes', 'change'), { recursive: true })
  return {
    root,
    state: join(root, 'state'),
    session: `session-${Math.random().toString(16).slice(2)}`,
    run: `run-${Math.random().toString(16).slice(2)}`,
    tickets
  }
}

const run = (fixture, action, extra = [], timeout) => spawnSync(process.execPath, [
  policy,
  action,
  '--session', fixture.session,
  '--run', fixture.run,
  ...extra
], {
  encoding: 'utf8',
  env: {
    ...process.env,
    MATT_TDD_ROOT: fixture.state
  },
  timeout
})

const init = fixture => run(fixture, 'init', ['--tickets', fixture.tickets])

const manifestPath = fixture => join(fixture.state, fixture.session, fixture.run, 'decision.json')

const requiredTicket = `# 01 — Required behavior

**Status:** ready-for-agent

**TDD:** required

**TDD seam:** CLI output
`

const waivedTicket = ({ reason = 'docs-only', approval = 'ticket-breakdown-user-approved' } = {}) => `# 02 — Documentation behavior

**Status:** ready-for-agent

**TDD:** waived

**TDD waiver:** \`${reason}\`

**TDD waiver approved:** \`${approval}\`
`

test('missing classification is rejected', () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, '# 01 — Missing classification\n\n**Status:** ready-for-agent\n')
  const result = init(fixture)
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /classification is required/)
})

test('valid required ticket produces a deterministic bound manifest', () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, requiredTicket)
  const result = init(fixture)
  assert.equal(result.status, 0, result.stderr)
  const manifest = JSON.parse(readFileSync(manifestPath(fixture), 'utf8'))
  assert.deepEqual(manifest, {
    contract: 'MATT_TDD_DECISION v1',
    status: 'started',
    testing_mode: 'tdd',
    session_id: fixture.session,
    run_id: fixture.run,
    tickets_source: realpathSync(fixture.tickets),
    tickets: [{ id: '01', decision: 'required', seam: 'CLI output' }]
  })
  assert.equal(lstatSync(manifestPath(fixture)).mode & 0o077, 0)
  const validated = run(fixture, 'validate')
  assert.equal(validated.status, 0, validated.stderr)
  assert.match(validated.stdout, /"required_count":1/)
})

test('legacy started manifest without tickets_source still validates', () => {
  const fixture = createFixture()
  mkdirSync(join(fixture.state, fixture.session, fixture.run), { recursive: true })
  writeFileSync(manifestPath(fixture), `${JSON.stringify({
    contract: 'MATT_TDD_DECISION v1',
    status: 'started',
    session_id: fixture.session,
    run_id: fixture.run,
    tickets: [{ id: '01', decision: 'required', seam: 'CLI output' }]
  })}\n`, { mode: 0o600 })
  const validated = run(fixture, 'validate')
  assert.equal(validated.status, 0, validated.stderr)
})

test('validate preserves a manifest until terminal consume', () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, requiredTicket)
  assert.equal(init(fixture).status, 0)
  const before = readFileSync(manifestPath(fixture), 'utf8')
  const validated = run(fixture, 'validate')
  assert.equal(validated.status, 0, validated.stderr)
  assert.equal(existsSync(manifestPath(fixture)), true)
  assert.equal(readFileSync(manifestPath(fixture), 'utf8'), before)
  const consumed = run(fixture, 'consume')
  assert.equal(consumed.status, 0, consumed.stderr)
  assert.equal(existsSync(manifestPath(fixture)), false)
  const after = run(fixture, 'validate')
  assert.notEqual(after.status, 0)
  assert.match(after.stderr, /manifest is missing/)
})

test('failed consume preserves an invalid manifest for repair', () => {
  const fixture = createFixture()
  mkdirSync(join(fixture.state, fixture.session, fixture.run), { recursive: true })
  const invalid = '{"contract":"invalid"}\n'
  writeFileSync(manifestPath(fixture), invalid, { mode: 0o600 })
  const consumed = run(fixture, 'consume')
  assert.notEqual(consumed.status, 0)
  assert.equal(readFileSync(manifestPath(fixture), 'utf8'), invalid)
})

test('valid approved waiver is accepted and covers every ticket', () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, `${requiredTicket}\n${waivedTicket()}`)
  assert.equal(init(fixture).status, 0)
  const manifest = JSON.parse(readFileSync(manifestPath(fixture), 'utf8'))
  assert.deepEqual(manifest.tickets, [
    { id: '01', decision: 'required', seam: 'CLI output' },
    {
      id: '02',
      decision: 'waived',
      reason: 'docs-only',
      approval: 'ticket-breakdown-user-approved'
    }
  ])
})

test('invalid or unapproved waiver is rejected', () => {
  const invalidReason = createFixture()
  writeFileSync(invalidReason.tickets, waivedTicket({ reason: 'because-i-said-so' }))
  const reasonResult = init(invalidReason)
  assert.notEqual(reasonResult.status, 0)
  assert.match(reasonResult.stderr, /closed waiver reason/)

  const unapproved = createFixture()
  writeFileSync(unapproved.tickets, waivedTicket({ approval: 'pending' }))
  const approvalResult = init(unapproved)
  assert.notEqual(approvalResult.status, 0)
  assert.match(approvalResult.stderr, /ticket-breakdown-user-approved/)
})

test('not-started decision accepts only a closed reason', () => {
  const fixture = createFixture()
  const valid = run(fixture, 'not-started', ['--reason', 'preflight-only'])
  assert.equal(valid.status, 0, valid.stderr)
  const manifest = JSON.parse(readFileSync(manifestPath(fixture), 'utf8'))
  assert.deepEqual(manifest, {
    contract: 'MATT_TDD_DECISION v1',
    status: 'not-started',
    reason: 'preflight-only',
    session_id: fixture.session,
    run_id: fixture.run,
    tickets: []
  })
  assert.equal(run(fixture, 'validate').status, 0)

  const invalid = createFixture()
  const result = run(invalid, 'not-started', ['--reason', 'maybe-later'])
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /closed not-started reason/)
})

test('malformed manifest and symlink control file are rejected', () => {
  const malformed = createFixture()
  mkdirSync(join(malformed.state, malformed.session, malformed.run), { recursive: true })
  writeFileSync(manifestPath(malformed), '{bad json\n', { mode: 0o600 })
  const malformedResult = run(malformed, 'validate')
  assert.notEqual(malformedResult.status, 0)
  assert.match(malformedResult.stderr, /manifest is malformed/)

  const linked = createFixture()
  mkdirSync(join(linked.state, linked.session, linked.run), { recursive: true })
  const target = join(linked.root, 'target.json')
  writeFileSync(target, '{}\n')
  symlinkSync(target, manifestPath(linked))
  const linkedResult = run(linked, 'validate')
  assert.notEqual(linkedResult.status, 0)
  assert.match(linkedResult.stderr, /regular control file/)
})

test('world-readable manifest is rejected', () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, requiredTicket)
  assert.equal(init(fixture).status, 0)
  chmodSync(manifestPath(fixture), 0o644)
  const result = run(fixture, 'validate')
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /owner-only/)
})

test('each ticket has exactly one TDD classification', () => {
  const duplicate = createFixture()
  writeFileSync(duplicate.tickets, `${requiredTicket}\n**TDD:** required\n`)
  const duplicateResult = init(duplicate)
  assert.notEqual(duplicateResult.status, 0)
  assert.match(duplicateResult.stderr, /exactly one TDD classification/)

  const conflicting = createFixture()
  writeFileSync(conflicting.tickets, `${requiredTicket}\n**TDD:** waived\n`)
  const conflictingResult = init(conflicting)
  assert.notEqual(conflictingResult.status, 0)
  assert.match(conflictingResult.stderr, /exactly one TDD classification/)
})

test('required tickets need exactly one non-empty TDD seam', () => {
  const missing = createFixture()
  writeFileSync(missing.tickets, '# 01 — Required\n\n**TDD:** required\n')
  const missingResult = init(missing)
  assert.notEqual(missingResult.status, 0)
  assert.match(missingResult.stderr, /non-empty TDD seam/)

  const duplicate = createFixture()
  writeFileSync(duplicate.tickets, `${requiredTicket}\n**TDD seam:** HTTP response\n`)
  const duplicateResult = init(duplicate)
  assert.notEqual(duplicateResult.status, 0)
  assert.match(duplicateResult.stderr, /exactly one non-empty TDD seam/)
})

test('required and waived decision shapes are mutually exclusive', () => {
  const requiredWithWaiver = createFixture()
  writeFileSync(requiredWithWaiver.tickets, `${requiredTicket}\n**TDD waiver:** \`docs-only\`\n\n**TDD waiver approved:** \`ticket-breakdown-user-approved\`\n`)
  const requiredResult = init(requiredWithWaiver)
  assert.notEqual(requiredResult.status, 0)
  assert.match(requiredResult.stderr, /required TDD forbids waiver fields/)

  const waivedWithSeam = createFixture()
  writeFileSync(waivedWithSeam.tickets, `${waivedTicket()}\n**TDD seam:** CLI output\n`)
  const waivedResult = init(waivedWithSeam)
  assert.notEqual(waivedResult.status, 0)
  assert.match(waivedResult.stderr, /waived TDD forbids seam fields/)

  const duplicateReason = createFixture()
  writeFileSync(duplicateReason.tickets, `${waivedTicket()}\n**TDD waiver:** \`generated-only\`\n`)
  const reasonResult = init(duplicateReason)
  assert.notEqual(reasonResult.status, 0)
  assert.match(reasonResult.stderr, /exactly one closed waiver reason/)

  const duplicateApproval = createFixture()
  writeFileSync(duplicateApproval.tickets, `${waivedTicket()}\n**TDD waiver approved:** \`ticket-breakdown-user-approved\`\n`)
  const approvalResult = init(duplicateApproval)
  assert.notEqual(approvalResult.status, 0)
  assert.match(approvalResult.stderr, /exactly one approved waiver/)
})

test('canonical ticket sources accept only complete scratch issues directories or OpenSpec tasks files', () => {
  const single = createFixture()
  single.tickets = join(single.root, '.scratch', 'feature', 'issues', '01.md')
  mkdirSync(join(single.root, '.scratch', 'feature', 'issues'), { recursive: true })
  writeFileSync(single.tickets, requiredTicket)
  const singleResult = init(single)
  assert.notEqual(singleResult.status, 0)
  assert.match(singleResult.stderr, /canonical ticket source/)

  const directory = createFixture()
  directory.tickets = join(directory.root, '.scratch', 'feature', 'issues')
  mkdirSync(directory.tickets, { recursive: true })
  writeFileSync(join(directory.tickets, '01.md'), requiredTicket)
  writeFileSync(join(directory.tickets, '02.md'), waivedTicket())
  const directoryResult = init(directory)
  assert.equal(directoryResult.status, 0, directoryResult.stderr)
  const manifest = JSON.parse(readFileSync(manifestPath(directory), 'utf8'))
  assert.equal(manifest.tickets.length, 2)

  const arbitrary = createFixture()
  arbitrary.tickets = join(arbitrary.root, 'issues')
  mkdirSync(arbitrary.tickets)
  writeFileSync(join(arbitrary.tickets, '01.md'), requiredTicket)
  const arbitraryResult = init(arbitrary)
  assert.notEqual(arbitraryResult.status, 0)
  assert.match(arbitraryResult.stderr, /canonical ticket source/)
})

test('nested scratch child cannot omit a required sibling ticket', () => {
  const fixture = createFixture()
  const issues = join(fixture.root, '.scratch', 'feature', 'issues')
  fixture.tickets = join(issues, 'waived-only')
  mkdirSync(fixture.tickets, { recursive: true })
  writeFileSync(join(issues, '01.md'), requiredTicket)
  writeFileSync(join(fixture.tickets, '02.md'), waivedTicket())
  const result = init(fixture)
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /canonical ticket source/)
})

test('directory enumeration rejects symlinks, non-regular Markdown entries, and malformed tickets', () => {
  const linked = createFixture()
  linked.tickets = join(linked.root, '.scratch', 'linked', 'issues')
  mkdirSync(linked.tickets, { recursive: true })
  writeFileSync(join(linked.tickets, '01.md'), requiredTicket)
  symlinkSync(join(linked.tickets, '01.md'), join(linked.tickets, '02.md'))
  const linkedResult = init(linked)
  assert.notEqual(linkedResult.status, 0)
  assert.match(linkedResult.stderr, /symlink/)

  const nonRegular = createFixture()
  nonRegular.tickets = join(nonRegular.root, '.scratch', 'non-regular', 'issues')
  mkdirSync(nonRegular.tickets, { recursive: true })
  writeFileSync(join(nonRegular.tickets, '01.md'), requiredTicket)
  mkdirSync(join(nonRegular.tickets, '02.md'))
  const nonRegularResult = init(nonRegular)
  assert.notEqual(nonRegularResult.status, 0)
  assert.match(nonRegularResult.stderr, /regular Markdown file/)

  const malformed = createFixture()
  malformed.tickets = join(malformed.root, '.scratch', 'malformed', 'issues')
  mkdirSync(malformed.tickets, { recursive: true })
  writeFileSync(join(malformed.tickets, '01.md'), requiredTicket)
  writeFileSync(join(malformed.tickets, '02.md'), '# 02 Missing separator\n\n**TDD:** required\n\n**TDD seam:** CLI output\n')
  const malformedResult = init(malformed)
  assert.notEqual(malformedResult.status, 0)
  assert.match(malformedResult.stderr, /malformed ticket file/)

  const malformedOnly = createFixture()
  malformedOnly.tickets = join(malformedOnly.root, '.scratch', 'malformed-only', 'issues')
  mkdirSync(malformedOnly.tickets, { recursive: true })
  const malformedFile = join(malformedOnly.tickets, '03.md')
  const malformedHeading = '# 03 —【Scratch 條件票】'
  writeFileSync(malformedFile, `${malformedHeading}\n`)
  const malformedOnlyResult = init(malformedOnly)
  assert.notEqual(malformedOnlyResult.status, 0)
  assert.match(malformedOnlyResult.stderr, /malformed ticket file/)
  assert.ok(malformedOnlyResult.stderr.includes(malformedFile))
  assert.ok(malformedOnlyResult.stderr.includes(malformedHeading))
  assert.match(malformedOnlyResult.stderr, /line 1/)
  assert.match(malformedOnlyResult.stderr, /expected canonical shape: # <NN> — <title>/)
})

test('combined tasks artifact diagnoses numeric-only headings and keeps generic fallback', () => {
  const malformedOnly = createFixture()
  const malformedHeading = '## 07 —【條件票：02 通過才活】'
  writeFileSync(malformedOnly.tickets, `${malformedHeading}\n`)
  const malformedResult = init(malformedOnly)
  assert.notEqual(malformedResult.status, 0)
  assert.match(malformedResult.stderr, /malformed ticket section/)
  assert.ok(malformedResult.stderr.includes(malformedOnly.tickets))
  assert.ok(malformedResult.stderr.includes(malformedHeading))
  assert.match(malformedResult.stderr, /line 1/)
  assert.match(malformedResult.stderr, /expected canonical shape: ## <NN> — <title>/)

  const generic = createFixture()
  writeFileSync(generic.tickets, '# Missing separator\n\n**TDD:** waived\n')
  const genericResult = init(generic)
  assert.notEqual(genericResult.status, 0)
  assert.match(genericResult.stderr, /malformed ticket file/)
})

test('combined tasks artifact reports only the first malformed numeric heading', () => {
  const fixture = createFixture()
  const validCombinedTicket = requiredTicket.replace(/^# /, '## ')
  const firstMalformedHeading = '## 07 —【條件票：02 通過才活】'
  const secondMalformedHeading = '## 08—【第二個格式錯誤】'
  writeFileSync(fixture.tickets, `${validCombinedTicket}${firstMalformedHeading}\n${secondMalformedHeading}\n`)
  const result = init(fixture)
  assert.notEqual(result.status, 0)
  assert.match(result.stderr, /malformed ticket section/)
  assert.ok(result.stderr.includes(fixture.tickets))
  assert.ok(result.stderr.includes(firstMalformedHeading))
  assert.equal(result.stderr.includes(secondMalformedHeading), false)
  assert.match(result.stderr, /line 8/)
  assert.match(result.stderr, /expected canonical shape: ## <NN> — <title>/)
})

test('combines and sorts tickets from a Markdown source while preserving their decisions', () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, `# Release checklist

### 12 - Documentation
**tests:** waived${'  '}
**test waiver:** generated-only
**test waiver approved:** ticket-breakdown-user-approved

## 2 — Output
**TESTS:** required
**TEST SEAM:** \`  CLI output  \`
`)
  const result = init(fixture)
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(JSON.parse(result.stdout), {
    status: 'started', testing_mode: 'tdd', required_count: 1, tdd_required_count: 1,
    manifest: manifestPath(fixture), ticket_count: 2
  })
  assert.deepEqual(JSON.parse(readFileSync(manifestPath(fixture), 'utf8')).tickets, [
    { id: '02', decision: 'required', seam: 'CLI output' },
    { id: '12', decision: 'waived', reason: 'generated-only', approval: 'ticket-breakdown-user-approved' }
  ])
})

test('a valid spaced heading does not take the place of the first malformed heading in diagnostics', () => {
  const fixture = createFixture()
  const valid = requiredTicket.replace(/^# 01 — Required behavior/, '##  01  —  Required behavior')
  const malformed = '## 02 Missing separator near # 03 — Example'
  writeFileSync(fixture.tickets, `${valid}\n${malformed}\n`)
  const result = init(fixture)
  assert.equal(result.status, 1, result.stderr)
  assert.equal(result.stderr, `malformed ticket section: ${fixture.tickets}: line 9: "${malformed}"; expected canonical shape: ## <NN> — <title>\n`)
})

test('manifest validation requires string ticket ids and rejects logical duplicates', () => {
  const nonString = createFixture()
  mkdirSync(join(nonString.state, nonString.session, nonString.run), { recursive: true })
  writeFileSync(manifestPath(nonString), `${JSON.stringify({
    contract: 'MATT_TDD_DECISION v1',
    status: 'started',
    session_id: nonString.session,
    run_id: nonString.run,
    tickets: [{ id: 1, decision: 'required', seam: 'CLI output' }]
  })}\n`, { mode: 0o600 })
  const nonStringResult = run(nonString, 'validate')
  assert.notEqual(nonStringResult.status, 0)
  assert.match(nonStringResult.stderr, /ticket id must be a string/)

  const duplicate = createFixture()
  mkdirSync(join(duplicate.state, duplicate.session, duplicate.run), { recursive: true })
  writeFileSync(manifestPath(duplicate), `${JSON.stringify({
    contract: 'MATT_TDD_DECISION v1',
    status: 'started',
    session_id: duplicate.session,
    run_id: duplicate.run,
    tickets: [
      { id: '1', decision: 'required', seam: 'CLI output' },
      { id: '01', decision: 'required', seam: 'HTTP response' }
    ]
  })}\n`, { mode: 0o600 })
  const duplicateResult = run(duplicate, 'validate')
  assert.notEqual(duplicateResult.status, 0)
  assert.match(duplicateResult.stderr, /duplicate ticket id/)
})

test('dot session and run ids are rejected and resolved run stays under root', () => {
  for (const [session, runId] of [['.', 'run-1'], ['..', 'run-1'], ['session-1', '.'], ['session-1', '..']]) {
    const fixture = createFixture()
    fixture.session = session
    fixture.run = runId
    writeFileSync(fixture.tickets, requiredTicket)
    const result = init(fixture)
    assert.notEqual(result.status, 0)
    assert.match(result.stderr, /must not be dot or dot-dot/)
  }
})

test('without a root override the manifest is placed beneath the subprocess home', () => {
  const fixture = createFixture()
  const fixtureHome = join(fixture.root, 'fixture-home')
  mkdirSync(fixtureHome)
  const env = { ...process.env, HOME: fixtureHome, USERPROFILE: fixtureHome }
  delete env.MATT_TDD_ROOT
  const result = spawnSync(process.execPath, [
    policy, 'not-started', '--session', fixture.session, '--run', fixture.run, '--reason', 'user-deferred'
  ], { encoding: 'utf8', env })
  const expected = join(fixtureHome, '.claude', 'logs', 'matt-tdd', fixture.session, fixture.run, 'decision.json')
  assert.equal(result.status, 0, result.stderr)
  assert.equal(JSON.parse(result.stdout).manifest, expected)
  assert.equal(JSON.parse(readFileSync(expected, 'utf8')).reason, 'user-deferred')
})

test('a second decision for the same run preserves the first decision', () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, requiredTicket)
  const first = init(fixture)
  assert.equal(first.status, 0, first.stderr)
  const stored = readFileSync(manifestPath(fixture), 'utf8')
  const second = run(fixture, 'not-started', ['--reason', 'user-deferred'])
  assert.equal(second.status, 1, second.stderr)
  assert.equal(second.stderr, 'decision manifest already exists for this session run\n')
  assert.equal(second.stdout, '')
  assert.equal(readFileSync(manifestPath(fixture), 'utf8'), stored)
})

test('decision creation restricts every control directory to its owner', () => {
  const fixture = createFixture()
  const dirs = [fixture.state, join(fixture.state, fixture.session), join(fixture.state, fixture.session, fixture.run)]
  mkdirSync(dirs[2], { recursive: true })
  for (const path of dirs) chmodSync(path, 0o755)
  const result = run(fixture, 'not-started', ['--reason', 'prerequisite-blocked'])
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(dirs.map(path => lstatSync(path).mode & 0o777), [0o700, 0o700, 0o700])
  assert.equal(lstatSync(manifestPath(fixture)).mode & 0o777, 0o600)
  assert.deepEqual(readdirSync(dirs[2]), ['decision.json'])
  assert.deepEqual(JSON.parse(result.stdout), {
    status: 'not-started', manifest: manifestPath(fixture), reason: 'prerequisite-blocked'
  })
})

test('manifest creation is atomic create-once under concurrency', async () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, requiredTicket)
  const launch = () => new Promise(resolveChild => {
    const child = spawn(process.execPath, [
      policy,
      'init',
      '--session', fixture.session,
      '--run', fixture.run,
      '--tickets', fixture.tickets
    ], {
      env: { ...process.env, MATT_TDD_ROOT: fixture.state },
      stdio: ['ignore', 'pipe', 'pipe']
    })
    let stderr = ''
    child.stderr.on('data', value => { stderr += value })
    child.on('close', status => resolveChild({ status, stderr }))
  })
  const results = await Promise.all(Array.from({ length: 12 }, launch))
  assert.equal(results.filter(result => result.status === 0).length, 1, JSON.stringify(results))
  for (const result of results.filter(result => result.status !== 0)) {
    assert.equal(result.status, 1, result.stderr)
    assert.equal(result.stderr, 'decision manifest already exists for this session run\n')
  }
  const manifest = JSON.parse(readFileSync(manifestPath(fixture), 'utf8'))
  assert.equal(manifest.session_id, fixture.session)
  assert.equal(manifest.run_id, fixture.run)
})

const initMode = (fixture, mode) => run(fixture, 'init', ['--tickets', fixture.tickets, '--testing-mode', mode])

const testingFacts = output => [output.testing_mode, output.required_count, output.tdd_required_count]

const testsRequiredTicket = `# 01 — Required behavior

**Status:** ready-for-agent

**Tests:** required

**Test seam:** CLI output
`

const testsWaivedTicket = ({ reason = 'docs-only', approval = 'ticket-breakdown-user-approved' } = {}) => `# 02 — Documentation behavior

**Status:** ready-for-agent

**Tests:** waived

**Test waiver:** \`${reason}\`

**Test waiver approved:** \`${approval}\`
`

const writeStartedManifest = (fixture, extra = {}) => {
  mkdirSync(join(fixture.state, fixture.session, fixture.run), { recursive: true })
  const manifest = {
    contract: 'MATT_TDD_DECISION v1',
    status: 'started',
    session_id: fixture.session,
    run_id: fixture.run,
    tickets: [{ id: '01', decision: 'required', seam: 'CLI output' }],
    ...extra
  }
  writeFileSync(manifestPath(fixture), `${JSON.stringify(manifest, null, 2)}\n`, { mode: 0o600 })
  return readFileSync(manifestPath(fixture), 'utf8')
}

test('omitted testing mode stays compatible and records tdd', () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, `${requiredTicket}\n${waivedTicket()}`)
  const result = init(fixture)
  assert.equal(result.status, 0, result.stderr)
  const manifest = JSON.parse(readFileSync(manifestPath(fixture), 'utf8'))
  assert.deepEqual(manifest, {
    contract: 'MATT_TDD_DECISION v1',
    status: 'started',
    testing_mode: 'tdd',
    session_id: fixture.session,
    run_id: fixture.run,
    tickets_source: realpathSync(fixture.tickets),
    tickets: [
      { id: '01', decision: 'required', seam: 'CLI output' },
      { id: '02', decision: 'waived', reason: 'docs-only', approval: 'ticket-breakdown-user-approved' }
    ]
  })
  assert.deepEqual(testingFacts(JSON.parse(result.stdout)), ['tdd', 1, 1])
  const validated = run(fixture, 'validate')
  assert.equal(validated.status, 0, validated.stderr)
  assert.deepEqual(testingFacts(JSON.parse(validated.stdout)), ['tdd', 1, 1])
  const consumed = run(fixture, 'consume')
  assert.equal(consumed.status, 0, consumed.stderr)
  assert.deepEqual(testingFacts(JSON.parse(consumed.stdout)), ['tdd', 1, 1])
})

test('explicit tdd mode reconciles tdd_required_count with required_count', () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, `${requiredTicket}\n${waivedTicket()}`)
  const result = initMode(fixture, 'tdd')
  assert.equal(result.status, 0, result.stderr)
  const manifest = JSON.parse(readFileSync(manifestPath(fixture), 'utf8'))
  assert.equal(manifest.testing_mode, 'tdd')
  assert.deepEqual(manifest.tickets[0], { id: '01', decision: 'required', seam: 'CLI output' })
  assert.deepEqual(testingFacts(JSON.parse(result.stdout)), ['tdd', 1, 1])
  assert.deepEqual(testingFacts(JSON.parse(run(fixture, 'validate').stdout)), ['tdd', 1, 1])
})

test('regression-closeout keeps required obligation and asks for no Skill tdd', () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, `${requiredTicket}\n${waivedTicket()}`)
  const result = initMode(fixture, 'regression-closeout')
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(testingFacts(JSON.parse(result.stdout)), ['regression-closeout', 1, 0])
  const manifest = JSON.parse(readFileSync(manifestPath(fixture), 'utf8'))
  assert.deepEqual(manifest, {
    contract: 'MATT_TDD_DECISION v1',
    status: 'started',
    testing_mode: 'regression-closeout',
    session_id: fixture.session,
    run_id: fixture.run,
    tickets_source: realpathSync(fixture.tickets),
    tickets: [
      { id: '01', decision: 'required', seam: 'CLI output' },
      { id: '02', decision: 'waived', reason: 'docs-only', approval: 'ticket-breakdown-user-approved' }
    ]
  })
  const validated = run(fixture, 'validate')
  assert.equal(validated.status, 0, validated.stderr)
  assert.deepEqual(testingFacts(JSON.parse(validated.stdout)), ['regression-closeout', 1, 0])
  const consumed = run(fixture, 'consume')
  assert.equal(consumed.status, 0, consumed.stderr)
  assert.deepEqual(testingFacts(JSON.parse(consumed.stdout)), ['regression-closeout', 1, 0])
})

test('unknown testing mode is rejected and creates no manifest', () => {
  for (const mode of ['waived', 'TDD', 'regression']) {
    const fixture = createFixture()
    writeFileSync(fixture.tickets, requiredTicket)
    const result = initMode(fixture, mode)
    assert.ok(
      result.status !== 0 && !existsSync(manifestPath(fixture)) && /testing-mode|testing_mode/.test(result.stderr),
      `mode=${mode} status=${result.status} manifest=${existsSync(manifestPath(fixture))} stderr=${JSON.stringify(result.stderr)} stdout=${JSON.stringify(result.stdout)}`
    )
  }
})

test('legacy started manifest without testing_mode is read as tdd and not rewritten', () => {
  const fixture = createFixture()
  const before = writeStartedManifest(fixture)
  const validated = run(fixture, 'validate')
  assert.equal(validated.status, 0, validated.stderr)
  assert.deepEqual(testingFacts(JSON.parse(validated.stdout)), ['tdd', 1, 1])
  assert.equal(readFileSync(manifestPath(fixture), 'utf8'), before)
  const consumed = run(fixture, 'consume')
  assert.equal(consumed.status, 0, consumed.stderr)
  assert.deepEqual(testingFacts(JSON.parse(consumed.stdout)), ['tdd', 1, 1])
})

test('illegal testing_mode is not treated as the legacy tdd mode', () => {
  for (const illegal of [null, false, 0, '', 'waived', 'TDD', ['tdd']]) {
    const fixture = createFixture()
    const before = writeStartedManifest(fixture, { testing_mode: illegal })
    const result = run(fixture, 'validate')
    assert.ok(
      result.status !== 0 && /testing_mode/.test(result.stderr) && !/"valid":true/.test(result.stdout) && readFileSync(manifestPath(fixture), 'utf8') === before,
      `value=${JSON.stringify(illegal)} status=${result.status} stderr=${JSON.stringify(result.stderr)} stdout=${JSON.stringify(result.stdout)}`
    )
  }
})

test('stored legal testing modes reconcile without rewriting the manifest', () => {
  for (const [testingMode, tddRequiredCount] of [['tdd', 1], ['regression-closeout', 0]]) {
    const fixture = createFixture()
    const before = writeStartedManifest(fixture, { testing_mode: testingMode })
    const validated = run(fixture, 'validate')
    assert.equal(validated.status, 0, `${testingMode} ${validated.stderr}`)
    assert.deepEqual(testingFacts(JSON.parse(validated.stdout)), [testingMode, 1, tddRequiredCount])
    assert.equal(readFileSync(manifestPath(fixture), 'utf8'), before)
  }
})

test('Tests fields are accepted and do not become a waiver when the mode changes', () => {
  const closeout = createFixture()
  writeFileSync(closeout.tickets, `${testsRequiredTicket}\n${testsWaivedTicket()}`)
  const closeoutResult = initMode(closeout, 'regression-closeout')
  assert.equal(closeoutResult.status, 0, closeoutResult.stderr)
  const closeoutManifest = JSON.parse(readFileSync(manifestPath(closeout), 'utf8'))
  assert.equal(closeoutManifest.testing_mode, 'regression-closeout')
  assert.deepEqual(closeoutManifest.tickets, [
    { id: '01', decision: 'required', seam: 'CLI output' },
    { id: '02', decision: 'waived', reason: 'docs-only', approval: 'ticket-breakdown-user-approved' }
  ])
  assert.deepEqual(testingFacts(JSON.parse(closeoutResult.stdout)), ['regression-closeout', 1, 0])

  const mixed = createFixture()
  writeFileSync(mixed.tickets, `${requiredTicket}\n${testsWaivedTicket()}`)
  const mixedResult = initMode(mixed, 'tdd')
  assert.equal(mixedResult.status, 0, mixedResult.stderr)
  const mixedManifest = JSON.parse(readFileSync(manifestPath(mixed), 'utf8'))
  assert.deepEqual(mixedManifest.tickets, [
    { id: '01', decision: 'required', seam: 'CLI output' },
    { id: '02', decision: 'waived', reason: 'docs-only', approval: 'ticket-breakdown-user-approved' }
  ])
  assert.deepEqual(testingFacts(JSON.parse(mixedResult.stdout)), ['tdd', 1, 1])
})

test('mixed or duplicate test classification fields are rejected', () => {
  const samples = [
    ['duplicate classification', `${requiredTicket}\n**Tests:** required\n`],
    ['mixed seam', `${requiredTicket}\n**Test seam:** HTTP response\n`],
    ['mixed waiver field', `${waivedTicket()}\n**Test waiver:** \`generated-only\`\n`],
    ['second classification on a waiver', `${waivedTicket()}\n**Tests:** waived\n`]
  ]
  const failures = []
  for (const [label, body] of samples) {
    const fixture = createFixture()
    writeFileSync(fixture.tickets, body)
    const result = init(fixture)
    if (result.status === 0 || existsSync(manifestPath(fixture))) {
      failures.push(`${label} status=${result.status} manifest=${existsSync(manifestPath(fixture))} stdout=${JSON.stringify(result.stdout)}`)
    }
  }
  assert.deepEqual(failures, [])
})

test('incomplete Tests tickets are rejected for the new fields', () => {
  const missingSeam = createFixture()
  writeFileSync(missingSeam.tickets, '# 01 — Required behavior\n\n**Tests:** required\n')
  const missingResult = init(missingSeam)
  assert.ok(
    missingResult.status !== 0 && !existsSync(manifestPath(missingSeam)) && /Test seam/.test(missingResult.stderr),
    `stderr=${JSON.stringify(missingResult.stderr)} status=${missingResult.status}`
  )

  const unapproved = createFixture()
  writeFileSync(unapproved.tickets, testsWaivedTicket({ approval: 'pending' }))
  const unapprovedResult = init(unapproved)
  assert.ok(
    unapprovedResult.status !== 0 && !existsSync(manifestPath(unapproved)) && /ticket-breakdown-user-approved/.test(unapprovedResult.stderr),
    `stderr=${JSON.stringify(unapprovedResult.stderr)} status=${unapprovedResult.status}`
  )

  const badReason = createFixture()
  writeFileSync(badReason.tickets, testsWaivedTicket({ reason: 'because-i-said-so' }))
  const reasonResult = init(badReason)
  assert.ok(
    reasonResult.status !== 0 && !existsSync(manifestPath(badReason)) && /closed waiver reason/.test(reasonResult.stderr),
    `stderr=${JSON.stringify(reasonResult.stderr)} status=${reasonResult.status}`
  )

  const duplicate = createFixture()
  writeFileSync(duplicate.tickets, `${testsRequiredTicket}\n**Tests:** required\n`)
  const duplicateResult = init(duplicate)
  assert.ok(
    duplicateResult.status !== 0 && !existsSync(manifestPath(duplicate)) && /exactly one/.test(duplicateResult.stderr),
    `stderr=${JSON.stringify(duplicateResult.stderr)} status=${duplicateResult.status}`
  )
})

test('not-started output does not invent a testing mode', () => {
  const fixture = createFixture()
  const created = run(fixture, 'not-started', ['--reason', 'preflight-only'])
  assert.equal(created.status, 0, created.stderr)
  assert.equal('testing_mode' in JSON.parse(created.stdout), false)
  const manifest = JSON.parse(readFileSync(manifestPath(fixture), 'utf8'))
  assert.equal('testing_mode' in manifest, false)
  assert.deepEqual(manifest, {
    contract: 'MATT_TDD_DECISION v1',
    status: 'not-started',
    reason: 'preflight-only',
    session_id: fixture.session,
    run_id: fixture.run,
    tickets: []
  })
  const validated = run(fixture, 'validate')
  assert.equal(validated.status, 0, validated.stderr)
  assert.equal('testing_mode' in JSON.parse(validated.stdout), false)
  const consumed = run(fixture, 'consume')
  assert.equal(consumed.status, 0, consumed.stderr)
  assert.equal('testing_mode' in JSON.parse(consumed.stdout), false)
})

test('session and run identifiers must consist entirely of supported characters', () => {
  for (const [label, value] of [['session', '!sample'], ['session', 'sample!'], ['run', '!run'], ['run', 'run!']]) {
    const fixture = createFixture()
    fixture[label] = value
    const result = run(fixture, 'not-started', ['--reason', 'preflight-only'])
    assert.equal(result.status, 1, result.stderr)
    assert.equal(result.stderr, `${label} contains unsupported characters\n`)
    assert.equal(existsSync(fixture.state), false)
  }
})

test('a malformed CLI invocation reports the offending argument or action', () => {
  const cases = [
    ['validate', [], 'missing --session'],
    ['validate', ['--session', 'sample'], 'missing --run'],
    ['init', ['--session', 'sample', '--run', 'run-1'], 'missing --tickets'],
    ['validate', ['session'], 'unexpected argument: session'],
    ['validate', ['--session'], 'missing value for --session'],
    ['validate', ['--session', 'invalid!', '--run', 'run-1'], 'session contains unsupported characters'],
    ['validate', ['--session', '--run', 'run-1'], 'missing value for --session'],
    ['validate', ['--session', 'sample', '--session', 'another'], 'duplicate argument: --session'],
    ['inspect', [], 'unknown action: inspect'],
    [undefined, [], 'unknown action: ']
  ]
  const fixture = createFixture()
  for (const [action, args, message] of cases) {
    const result = spawnSync(process.execPath, [policy, ...(action === undefined ? [] : [action]), ...args], {
      encoding: 'utf8', env: { ...process.env, MATT_TDD_ROOT: fixture.state }
    })
    assert.equal(result.status, 1, result.stderr)
    assert.equal(result.stderr, `${message}\n`)
    assert.equal(result.stdout, '')
  }
  assert.equal(existsSync(fixture.state), false)
})

test('validation requires a decision for this run with a legal status and ticket list', () => {
  const cases = [
    [{ status: 'paused' }, 'decision manifest status is invalid'],
    [{ run_id: 'different-run' }, 'decision manifest is not bound to this session run'],
    [{ session_id: 'different-session' }, 'decision manifest is not bound to this session run'],
    [{ tickets: {} }, 'decision manifest tickets are malformed'],
    [{ tickets: [] }, 'started manifest must cover at least one ticket'],
    [{ tickets: [null] }, 'decision manifest ticket is malformed'],
    [{ tickets: [{ id: 'a1', decision: 'required', seam: 'CLI output' }] }, 'decision manifest ticket is malformed'],
    [{ tickets: [{ id: '01', decision: 'pending' }] }, 'ticket 01: decision must be required or waived'],
    [{ tickets: [{ id: '01', decision: 'required', seam: '   ' }] }, 'ticket 01: required TDD needs a non-empty seam'],
    [{ tickets: [{ id: '01', decision: 'waived', reason: 'pending', approval: 'ticket-breakdown-user-approved' }] }, 'ticket 01: waiver is invalid or unapproved'],
    [{ tickets: [{ id: '01', decision: 'waived', reason: 'docs-only', approval: 'pending' }] }, 'ticket 01: waiver is invalid or unapproved']
  ]
  for (const [changes, message] of cases) {
    const fixture = createFixture()
    const original = writeStartedManifest(fixture, changes)
    const result = run(fixture, 'consume')
    assert.equal(result.status, 1, result.stderr)
    assert.equal(result.stderr, `${message}\n`)
    assert.equal(result.stdout, '')
    assert.equal(readFileSync(manifestPath(fixture), 'utf8'), original)
  }
})

test('the closed reason vocabulary round-trips through validate and consume', () => {
  for (const reason of ['preflight-only', 'prerequisite-blocked', 'user-deferred']) {
    const fixture = createFixture()
    const created = run(fixture, 'not-started', ['--reason', reason])
    assert.equal(created.status, 0, created.stderr)
    assert.deepEqual(JSON.parse(created.stdout), { status: 'not-started', manifest: manifestPath(fixture), reason })
    const validated = run(fixture, 'validate')
    assert.equal(validated.status, 0, validated.stderr)
    assert.deepEqual(JSON.parse(validated.stdout), {
      status: 'not-started', valid: true, required_count: 0, ticket_count: 0, manifest: manifestPath(fixture)
    })
    const consumed = run(fixture, 'consume')
    assert.equal(consumed.status, 0, consumed.stderr)
    assert.deepEqual(JSON.parse(consumed.stdout), { status: 'not-started', consumed: true, required_count: 0, ticket_count: 0 })
  }
  for (const reason of ['docs-only', 'generated-only', 'no-stable-seam', 'non-executable-artifact']) {
    const fixture = createFixture()
    writeFileSync(fixture.tickets, waivedTicket({ reason }))
    const created = init(fixture)
    assert.equal(created.status, 0, created.stderr)
    assert.deepEqual(JSON.parse(readFileSync(manifestPath(fixture), 'utf8')).tickets, [
      { id: '02', decision: 'waived', reason, approval: 'ticket-breakdown-user-approved' }
    ])
  }
})

test('ticket source diagnostics name mislocated files and directories', () => {
  const fixture = createFixture()
  const cases = [
    [join(fixture.root, 'openspec', 'changes', 'change', 'notes.md'), 'file', 'openspec/changes/<change>/tasks.md'],
    [join(fixture.root, 'archive', 'changes', 'change', 'tasks.md'), 'file', 'openspec/changes/<change>/tasks.md'],
    [join(fixture.root, 'openspec', 'changes', 'change', 'notes', 'tasks.md'), 'file', 'openspec/changes/<change>/tasks.md'],
    [join(fixture.root, '.scratch', 'feature', 'notes'), 'directory', '.scratch/<feature>/issues'],
    [join(fixture.root, 'archive', 'feature', 'issues'), 'directory', '.scratch/<feature>/issues'],
    [join(fixture.root, '.scratch', 'feature', 'draft', 'issues'), 'directory', '.scratch/<feature>/issues'],
  ]
  for (const [path, type, expected] of cases) {
    fixture.tickets = path
    if (type === 'file') {
      mkdirSync(dirname(path), { recursive: true })
      writeFileSync(path, requiredTicket)
    } else {
      mkdirSync(path, { recursive: true })
      writeFileSync(join(path, '01.md'), requiredTicket)
    }
    const result = init(fixture)
    assert.equal(result.status, 1, result.stderr)
    assert.equal(result.stderr, `ticket path must be a canonical ticket source: ${expected}\n`)
    assert.equal(result.stdout, '')
  }
  assert.equal(existsSync(fixture.state), false)
})

test('non-regular ticket sources report their path before reading content', () => {
  const fixture = createFixture()
  const issues = join(fixture.root, '.scratch', 'feature', 'issues')
  mkdirSync(issues, { recursive: true })
  const entry = join(issues, '01.md')
  const fifo = spawnSync('mkfifo', [entry], { encoding: 'utf8' })
  assert.equal(fifo.status, 0, fifo.error?.message ?? fifo.stderr)

  const source = run(fixture, 'init', ['--tickets', entry], 5000)
  assert.equal(source.status, 1, source.error?.message ?? source.stderr)
  assert.equal(source.stderr, `ticket path must be a file or directory: ${entry}\n`)

  const nested = run(fixture, 'init', ['--tickets', issues], 5000)
  assert.equal(nested.status, 1, nested.error?.message ?? nested.stderr)
  assert.equal(nested.stderr, `ticket directory entry must be a regular Markdown file: ${entry}\n`)
  assert.equal(existsSync(fixture.state), false)
})

test('a linked ticket source is rejected before opening the linked file', () => {
  const fixture = createFixture()
  const original = join(fixture.root, 'original.md')
  writeFileSync(original, requiredTicket)
  symlinkSync(original, fixture.tickets)
  const result = init(fixture)
  assert.equal(result.status, 1, result.stderr)
  assert.equal(result.stderr, `ticket path must not be a symlink: ${fixture.tickets}\n`)
  assert.equal(existsSync(fixture.state), false)
})

test('a scratch ticket source includes nested Markdown tickets and ignores other files', () => {
  const fixture = createFixture()
  fixture.tickets = join(fixture.root, '.scratch', 'feature', 'issues')
  const nested = join(fixture.tickets, 'documentation')
  mkdirSync(nested, { recursive: true })
  writeFileSync(join(fixture.tickets, '01.md'), requiredTicket)
  writeFileSync(join(nested, '02.md'), waivedTicket())
  writeFileSync(join(nested, 'meeting.txt'), 'Meeting notes\n')
  const result = init(fixture)
  assert.equal(result.status, 0, result.stderr)
  const manifest = JSON.parse(readFileSync(manifestPath(fixture), 'utf8'))
  assert.deepEqual(manifest.tickets.map(ticket => ticket.id), ['01', '02'])
})

test('ticket sources report missing, empty, or semantically invalid input', () => {
  const fixture = createFixture()
  const missing = init(fixture)
  assert.equal(missing.status, 1)
  assert.equal(missing.stderr, `ticket path does not exist: ${fixture.tickets}\n`)
  const cases = [
    [requiredTicket.replace('**TDD:** required', '**TDD:** ``'), 'ticket 01: TDD classification is required'],
    [requiredTicket.replace('**TDD:** required', '**TDD:** pending'), 'ticket 01: TDD must be required or waived'],
    [`${requiredTicket}\n**TDD waiver:** docs-only\n`, 'ticket 01: required TDD forbids waiver fields'],
    [`${requiredTicket}\n**TDD waiver approved:** ticket-breakdown-user-approved\n`, 'ticket 01: required TDD forbids waiver fields'],
    [`${requiredTicket}\n${requiredTicket.replace(/^# 01/, '# 0001')}`, 'duplicate ticket id: 01']
  ]
  for (const [content, message] of cases) {
    writeFileSync(fixture.tickets, content)
    const result = init(fixture)
    assert.equal(result.status, 1, result.stderr)
    assert.equal(result.stderr, `${message}\n`)
    assert.equal(result.stdout, '')
  }
  writeFileSync(fixture.tickets, requiredTicket.replace('**Status:** ready-for-agent', '**Tests:** required'))
  const mixed = init(fixture)
  assert.equal(mixed.status, 1, mixed.stderr)
  assert.equal(mixed.stderr, 'ticket 01: mixed TDD and Tests fields\n')
  fixture.tickets = join(fixture.root, '.scratch', 'feature', 'issues')
  mkdirSync(join(fixture.tickets, 'notes'), { recursive: true })
  writeFileSync(join(fixture.tickets, 'notes', 'readme.txt'), 'Supporting notes\n')
  const empty = init(fixture)
  assert.equal(empty.status, 1)
  assert.equal(empty.stderr, 'no ticket headings found\n')
  assert.equal(existsSync(fixture.state), false)
})

test('ticket headings accept flexible spacing and ignore non-headings', () => {
  const fixture = createFixture()
  writeFileSync(fixture.tickets, `# Checklist

Background text mentions # 99 — Example only.

##  2  —  Output
**Tests:** required
**Test seam:** \`CLI output\` with notes

###  3 - Documentation
**Tests:** required
**Test seam:** compare \`summary\`
`)
  const result = init(fixture)
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(JSON.parse(readFileSync(manifestPath(fixture), 'utf8')).tickets, [
    { id: '02', decision: 'required', seam: '`CLI output` with notes' },
    { id: '03', decision: 'required', seam: 'compare `summary`' }
  ])
})

test('manifest validation preserves distinct numeric IDs with internal zeroes', () => {
  const fixture = createFixture()
  const ticket = id => ({ id, decision: 'required', seam: 'CLI output' })
  writeStartedManifest(fixture, { tickets: [ticket('101'), ticket('11')] })
  const distinct = run(fixture, 'validate')
  assert.equal(distinct.status, 0, distinct.stderr)
  assert.equal(JSON.parse(distinct.stdout).ticket_count, 2)

  writeStartedManifest(fixture, { tickets: [ticket('0011'), ticket('11')] })
  const duplicate = run(fixture, 'validate')
  assert.equal(duplicate.status, 1, duplicate.stderr)
  assert.equal(duplicate.stderr, 'duplicate ticket id: 11\n')

  const source = createFixture()
  const markdown = id => requiredTicket.replace(/^# 01/, `## ${id}`)
  writeFileSync(source.tickets, `${markdown('101')}\n${markdown('11')}`)
  const initialized = init(source)
  assert.equal(initialized.status, 0, initialized.stderr)
  const manifest = JSON.parse(readFileSync(manifestPath(source), 'utf8'))
  assert.deepEqual(manifest.tickets.map(row => row.id), ['101', '11'])
})

test('unknown testing modes are diagnosed before loading the ticket source', () => {
  const fixture = createFixture()
  const result = initMode(fixture, 'pending')
  assert.equal(result.status, 1, result.stderr)
  assert.equal(result.stderr, 'testing-mode must be tdd or regression-closeout\n')
  assert.equal(existsSync(fixture.state), false)
})

test('an existing run directory link is rejected without writing into its destination', () => {
  const fixture = createFixture()
  const destination = join(fixture.root, 'sample-directory')
  mkdirSync(destination)
  const sessionDir = join(fixture.state, fixture.session)
  mkdirSync(sessionDir, { recursive: true })
  const runDir = join(sessionDir, fixture.run)
  symlinkSync(destination, runDir, 'dir')
  const result = run(fixture, 'not-started', ['--reason', 'preflight-only'])
  assert.equal(result.status, 1, result.stderr)
  assert.equal(result.stderr, `control directory must be a regular directory: ${runDir}\n`)
  assert.deepEqual(readdirSync(destination), [])
})

test('a second decision cannot replace a malformed control file', () => {
  const fixture = createFixture()
  writeStartedManifest(fixture)
  chmodSync(manifestPath(fixture), 0o644)
  const result = run(fixture, 'not-started', ['--reason', 'preflight-only'])
  assert.equal(result.status, 1, result.stderr)
  assert.equal(result.stderr, 'manifest must be owner-only\n')
  assert.deepEqual(readdirSync(dirname(manifestPath(fixture))), ['decision.json'])
})

test('a directory at the decision path is diagnosed as an invalid control file', () => {
  const fixture = createFixture()
  mkdirSync(manifestPath(fixture), { recursive: true })
  const result = run(fixture, 'validate')
  assert.equal(result.status, 1, result.stderr)
  assert.equal(result.stderr, `manifest must be a regular control file: ${manifestPath(fixture)}\n`)
  assert.equal(result.stdout, '')
})

test('manifest diagnostics distinguish malformed decisions from ticket schema errors', () => {
  const cases = [
    [null, 'decision manifest is malformed'],
    [[], 'decision manifest is malformed'],
    ['decision', 'decision manifest is malformed'],
    [{ contract: 'unrecognized' }, 'decision manifest contract is invalid'],
    [{ status: 'not-started', reason: 'pending', tickets: [] }, 'not-started manifest needs a closed reason and no tickets'],
    [{ status: 'not-started', reason: 'user-deferred', tickets: [], extra: true }, 'not-started manifest has unexpected fields'],
    [{ status: 'not-started', reason: 'user-deferred', tickets: [{}] }, 'not-started manifest needs a closed reason and no tickets'],
    [{ tickets: [[]] }, 'decision manifest ticket is malformed'],
    [{ tickets: ['ticket'] }, 'decision manifest ticket is malformed'],
    [{ tickets: [{ id: '1a', decision: 'required', seam: 'CLI output' }] }, 'decision manifest ticket is malformed'],
    [{ tickets: [{ id: '01', decision: 'required', seam: 1 }] }, 'ticket 01: required TDD needs a non-empty seam'],
    [{ extra: true }, 'started manifest has unexpected fields'],
    [{ tickets: [{ id: '01', decision: 'required', extra: true }] }, 'ticket 01 has unexpected fields'],
    [{ tickets: [{ id: '02', decision: 'waived', approval: 'ticket-breakdown-user-approved', extra: true }] }, 'ticket 02 has unexpected fields']
  ]
  for (const [value, message] of cases) {
    const fixture = createFixture()
    const valid = JSON.parse(writeStartedManifest(fixture))
    const stored = `${JSON.stringify(value !== null && typeof value === 'object' && !Array.isArray(value) ? { ...valid, ...value } : value)}\n`
    writeFileSync(manifestPath(fixture), stored)
    const result = run(fixture, 'consume')
    assert.equal(result.status, 1, result.stderr)
    assert.equal(result.stderr, `${message}\n`)
    assert.equal(result.stdout, '')
    assert.equal(readFileSync(manifestPath(fixture), 'utf8'), stored)
  }
})

test('manifest and ticket validation reject extra unknown fields and missing required fields', () => {
  const cases = [
    [
      'started manifest with extra unknown key',
      (fixture) => ({
        contract: 'MATT_TDD_DECISION v1',
        status: 'started',
        session_id: fixture.session,
        run_id: fixture.run,
        tickets: [{ id: '01', decision: 'required', seam: 'CLI output' }],
        unexpected_top_level: true
      })
    ],
    [
      'not-started manifest with extra unknown key',
      (fixture) => ({
        contract: 'MATT_TDD_DECISION v1',
        status: 'not-started',
        reason: 'preflight-only',
        session_id: fixture.session,
        run_id: fixture.run,
        tickets: [],
        testing_mode: 'tdd'
      })
    ],
    [
      'required ticket with extra unknown key',
      (fixture) => ({
        contract: 'MATT_TDD_DECISION v1',
        status: 'started',
        session_id: fixture.session,
        run_id: fixture.run,
        tickets: [{ id: '01', decision: 'required', seam: 'CLI output', extra: 1 }]
      })
    ],
    [
      'waived ticket with extra unknown key',
      (fixture) => ({
        contract: 'MATT_TDD_DECISION v1',
        status: 'started',
        session_id: fixture.session,
        run_id: fixture.run,
        tickets: [{ id: '01', decision: 'waived', reason: 'docs-only', approval: 'ticket-breakdown-user-approved', extra: 1 }]
      })
    ],
    [
      'required ticket missing seam key',
      (fixture) => ({
        contract: 'MATT_TDD_DECISION v1',
        status: 'started',
        session_id: fixture.session,
        run_id: fixture.run,
        tickets: [{ id: '01', decision: 'required' }]
      })
    ],
    [
      'waived ticket missing approval key',
      (fixture) => ({
        contract: 'MATT_TDD_DECISION v1',
        status: 'started',
        session_id: fixture.session,
        run_id: fixture.run,
        tickets: [{ id: '01', decision: 'waived', reason: 'docs-only' }]
      })
    ],
    [
      'required ticket with same key count but wrong key name',
      (fixture) => ({
        contract: 'MATT_TDD_DECISION v1',
        status: 'started',
        session_id: fixture.session,
        run_id: fixture.run,
        tickets: [{ id: '01', decision: 'required', wrong_key: 'CLI output' }]
      })
    ],
    [
      'not-started manifest with same key count but wrong key name',
      (fixture) => ({
        contract: 'MATT_TDD_DECISION v1',
        status: 'not-started',
        wrong_key: 'preflight-only',
        session_id: fixture.session,
        run_id: fixture.run,
        tickets: []
      })
    ]
  ]

  for (const [label, buildManifest] of cases) {
    const fixture = createFixture()
    mkdirSync(join(fixture.state, fixture.session, fixture.run), { recursive: true })
    writeFileSync(manifestPath(fixture), `${JSON.stringify(buildManifest(fixture), null, 2)}\n`, { mode: 0o600 })
    const result = run(fixture, 'validate')
    assert.notEqual(result.status, 0, `${label}: expected non-zero exit`)
    assert.match(result.stderr, /has unexpected fields/, `${label}: expected assertExactKeys error, got: ${result.stderr}`)
  }
})
