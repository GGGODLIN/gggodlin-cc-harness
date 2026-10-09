import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-collision-check-'))
try {
  for (const [name, description] of [
    ['workflow-review-one', 'Use when reviewing a JavaScript workflow for correctness routing failures async behavior schema validation report paths channel identity and error handling'],
    ['workflow-review-two', 'Use when reviewing a JavaScript workflow for correctness routing failures async behavior schema validation report paths channel identity and error handling'],
  ]) {
    const dir = path.join(root, name)
    fs.mkdirSync(dir)
    fs.writeFileSync(path.join(dir, 'SKILL.md'), `---\nname: ${name}\ndescription: ${description}\n---\n`)
  }
  const output = execFileSync('node', ['~/.claude/scripts/skill-collision-check.js', '--pairs-only', root], { encoding: 'utf8' }).trim()
  assert.ok(output)
  const score = output.split('|')[2]
  assert.match(score, /^[01]\.\d{6}$/)
  console.log('1/1 passed')
} finally {
  fs.rmSync(root, { recursive: true, force: true })
}
