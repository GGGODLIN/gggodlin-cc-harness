// 本檔在契約測試底下；跑法：node --test ~/.claude/skills/implement/scripts/tests/tdd-policy.test.mjs
import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { chmodSync, existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, realpathSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
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

const run = (fixture, action, extra = []) => spawnSync(process.execPath, [
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
  }
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
