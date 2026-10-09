// 本檔在契約測試底下；跑法：node --test skills/tests/ticket-08-skill-structure.test.mjs
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const read = path => readFileSync(join(root, path), 'utf8')

const parseFrontmatter = path => {
  const text = read(path)
  assert.match(text, /^---\n/, `${path} must start with frontmatter`)
  const closing = text.indexOf('\n---\n', 4)
  assert.notEqual(closing, -1, `${path} must close frontmatter`)
  const yaml = text.slice(4, closing)
  const parser = spawnSync('ruby', [
    '-ryaml',
    '-rjson',
    '-e',
    'data = YAML.safe_load(STDIN.read, permitted_classes: [], aliases: false); STDOUT.write(JSON.generate(data))'
  ], { input: yaml, encoding: 'utf8' })
  assert.equal(parser.status, 0, `${path} frontmatter YAML failed: ${parser.stderr}`)
  const metadata = JSON.parse(parser.stdout)
  assert.equal(typeof metadata, 'object', `${path} frontmatter must be a map`)
  return metadata
}

const globalInventoryRows = () => {
  const inventory = read('skills/INVENTORY.md')
  const section = inventory.slice(
    inventory.indexOf('## Global skills'),
    inventory.indexOf('**Global Audit-eligible 統計**')
  )
  return section
    .split('\n')
    .filter(line => /^\| [^|-]/.test(line))
    .map(line => line.split('|').slice(1, -1).map(cell => cell.trim()))
}

test('E2E skill frontmatter parses and matches its directory name', () => {
  const path = 'skills/e2e-explore-then-batch/SKILL.md'
  const metadata = parseFrontmatter(path)
  assert.equal(metadata.name, 'e2e-explore-then-batch')
  assert.equal(typeof metadata.description, 'string')
  assert.match(metadata.description, /Use when/)
  assert.match(metadata.description, /Do not use for/)
})

test('E2E skill asset references resolve to both checked-in templates', () => {
  const path = 'skills/e2e-explore-then-batch/SKILL.md'
  const text = read(path)
  const references = [...text.matchAll(/`(assets\/[A-Za-z0-9._/-]+)`/g)].map(match => match[1])
  assert.deepEqual([...new Set(references)].sort(), [
    'assets/fixture-template.ts',
    'assets/spec-template.ts'
  ])
  for (const reference of references) {
    assert.equal(existsSync(resolve(root, dirname(path), reference)), true, `${reference} must resolve`)
  }
})

test('E2E skill and global inventory point to each other exactly once', () => {
  const rows = globalInventoryRows()
  const matches = rows.filter(([name]) => name === 'e2e-explore-then-batch')
  assert.equal(matches.length, 1)
  assert.equal(matches[0][1], 'self-written')
  assert.equal(matches[0][2], 'yes')
  const metadata = parseFrontmatter('skills/e2e-explore-then-batch/SKILL.md')
  assert.equal(metadata.name, matches[0][0])
  assert.equal(existsSync(join(root, 'skills', matches[0][0], 'SKILL.md')), true)
})

test('explain-diff remains manual-only through parsed frontmatter', () => {
  const metadata = parseFrontmatter('skills/explain-diff/SKILL.md')
  assert.equal(metadata.name, 'explain-diff')
  assert.equal(metadata['disable-model-invocation'], true)
})

test('Bitbucket token loading is env-first then zsh_secrets then zshrc without a value', () => {
  const path = 'skills/bitbucket-weekly-report/skill.md'
  const metadata = parseFrontmatter(path)
  assert.equal(metadata.name, 'bitbucket-weekly-report')
  const text = read(path)
  const loaders = text.match(/export BITBUCKET_API_TOKEN="\$\{BITBUCKET_API_TOKEN:-\$\([^\n]+~\/\.zsh_secrets ~\/\.zshrc[^\n]+\)\}"/g) ?? []
  assert.equal(loaders.length, 4)
  for (const loader of loaders) {
    assert.ok(loader.indexOf('${BITBUCKET_API_TOKEN:-') < loader.indexOf('~/.zsh_secrets'))
    assert.ok(loader.indexOf('~/.zsh_secrets') < loader.indexOf('~/.zshrc'))
  }
  assert.doesNotMatch(text, /export BITBUCKET_API_TOKEN=(?!"?\$\{)/)
})

test('gate-authoring and implement friction logs expose protocol sections', () => {
  for (const path of [
    'skills/gate-authoring/friction-log.md',
    'skills/implement/friction-log.md'
  ]) {
    const headings = read(path).match(/^## .+$/gm) ?? []
    assert.deepEqual(headings, ['## 待折', '## 已折／已否決'], path)
  }
})

test('TypeScript templates retain fixture and batch-spec structure', () => {
  const fixture = read('skills/e2e-explore-then-batch/assets/fixture-template.ts')
  assert.match(fixture, /from '@playwright\/test'/)
  assert.match(fixture, /base\.extend<EnvOptions>/)
  assert.match(fixture, /await use\(context\)/)
  assert.match(fixture, /await use\(page\)/)

  const spec = read('skills/e2e-explore-then-batch/assets/spec-template.ts')
  assert.match(spec, /from '\.\.\/fixtures'/)
  assert.match(spec, /const caseMatrix = \[/)
  assert.match(spec, /for \(const c of caseMatrix\)/)
  assert.match(spec, /test\(`batch:/)
})
