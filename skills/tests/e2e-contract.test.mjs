import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const names = ['e2e-route', 'e2e-contract', 'e2e-tester-army', 'e2e-explore-then-batch']
const texts = Object.fromEntries(names.map(name => [name, readFileSync(join(root, 'skills', name, 'SKILL.md'), 'utf8')]))

test('契約與執行入口保留可呼叫的合法 frontmatter', () => {
  for (const name of names) {
    const match = texts[name].match(/^---\n([\s\S]*?)\n---\n/)
    assert.ok(match, name)
    const parsed = spawnSync('ruby', ['-ryaml', '-rjson', '-e', 'STDOUT.write(JSON.generate(YAML.safe_load(STDIN.read, permitted_classes: [], aliases: false)))'], { input: match[1], encoding: 'utf8' })
    assert.equal(parsed.status, 0, parsed.stderr)
    const metadata = JSON.parse(parsed.stdout)
    assert.equal(metadata.name, name)
    assert.match(metadata.description, /Use when/)
    assert.match(metadata.description, /Do not use for/)
    assert.notEqual(metadata['disable-model-invocation'], true)
  }
})

test('共同契約與模板引用可從 repo root 定位', () => {
  for (const name of names) {
    for (const match of texts[name].matchAll(/\]\((\/skills\/e2e-contract\/[^)]+)\)/g)) {
      assert.equal(existsSync(join(root, match[1].slice(1))), true, match[1])
    }
  }
  for (const path of ['references/execution-contract.md', 'assets/contract-template.md', 'assets/run-template.md']) {
    assert.equal(existsSync(join(root, 'skills/e2e-contract', path)), true, path)
  }
})

test('路由有工作種類分支且兩工具引用相同契約', () => {
  assert.match(texts['e2e-route'], /work-kind=contract/)
  assert.match(texts['e2e-route'], /Skill\(e2e-contract\)/)
  assert.match(texts['e2e-route'], /普通工作/)
  for (const name of ['e2e-tester-army', 'e2e-explore-then-batch']) {
    assert.match(texts[name], /mode=contract/)
    assert.match(texts[name], /\/skills\/e2e-contract\/references\/execution-contract\.md/)
    assert.match(texts[name], /不回 route 重試或降級普通模式/)
  }
})

test('契約保存欄位與庫存列存在而不取代產品驗證', () => {
  const contract = readFileSync(join(root, 'skills/e2e-contract/assets/contract-template.md'), 'utf8')
  const run = readFileSync(join(root, 'skills/e2e-contract/assets/run-template.md'), 'utf8')
  assert.match(contract, /內容指紋/)
  assert.match(contract, /確認子集/)
  assert.match(contract, /原話／訊息來源/)
  assert.match(run, /測試版本/)
  assert.match(run, /本次實際產品版本/)
  assert.match(run, /未執行／阻塞／失敗／通過/)
  const inventory = readFileSync(join(root, 'skills/INVENTORY.md'), 'utf8')
  assert.equal((inventory.match(/^\| e2e-contract\s+\|/gm) ?? []).length, 1)
})
