import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { test } from 'node:test'

const root = fileURLToPath(new URL('../../../../', import.meta.url))
const read = path => readFileSync(resolve(root, path), 'utf8')
const implement = read('skills/implement/SKILL.md')
const tickets = read('skills/to-tickets/SKILL.md')
const tdd = read('skills/tdd/SKILL.md')
const regression = read('skills/implement/references/regression-closeout.md')

test('本批模式在同一開工詢問取得，不能從 required 代選', () => {
  assert.match(implement, /同一輪再問本批尚未取得答案的.*測試模式/)
  assert.match(implement, /a\. 原 TDD.*b\. 回歸收尾/)
  assert.match(implement, /不從 `required` 代選/)
  assert.match(implement, /答案前不建立 started manifest/)
  assert.ok(implement.indexOf('Then one question round') < implement.indexOf('--testing-mode <tdd|regression-closeout>'))
})

test('同批續接沿用真實選擇，並保留舊 manifest 相容性', () => {
  assert.match(implement, /續接沿用、不逐票重問/)
  assert.match(implement, /started manifest 缺模式欄時相容為原 TDD/)
  assert.match(implement, /新 run 的續接用真正的新身分/)
  assert.match(implement, /已結束的另一批選擇不沿用/)
})

test('共用正文不再帶原先的完整 TDD 執行配方', () => {
  assert.doesNotMatch(implement, /write a failing behavioural test first, make the minimum production change/)
  assert.doesNotMatch(implement, /If any ticket is required, explicitly invoke/)
  assert.match(implement, /只有 `testing_mode=tdd` 且有 required 票時/)
  assert.match(implement, /配方只按已選路線載入/)
  assert.match(implement, /唯一所選配方/)
})

test('已載入舊正文的 context 不宣稱能卸載', () => {
  assert.match(implement, /回歸收尾不能復用該 context 作 Inline 執行/)
  assert.match(implement, /fresh worker 或新 session/)
  assert.match(implement, /不把選模式當成另起 Herdr 的授權/)
})

test('回歸收尾只讀品質 reference，允許必要案例提前留下', () => {
  assert.match(regression, /testing_mode=regression-closeout/)
  assert.match(regression, /可直接留下可重複執行的測試/)
  assert.match(regression, /不呼叫 `Skill\(tdd\)` 或讀它的 SKILL\.md/)
  assert.match(regression, /不從目前輸出反推/)
  assert.match(regression, /不普遍強制/)
  assert.doesNotMatch(regression, /Write the failing tests first|Red before green|先寫失敗測試/)
  for (const path of ['skills/tdd/tests.md', 'skills/tdd/mocking.md']) {
    assert.ok(existsSync(resolve(root, path)))
    assert.ok(regression.includes(`/${path}`))
  }
})

test('核票保留義務、回歸範圍與豁免，模式留到 implement', () => {
  for (const field of ['Tests', 'Test seam', 'Regression scope', 'Test waiver', 'Test waiver approved']) {
    assert.ok(tickets.includes(`**${field}:**`))
  }
  assert.match(tickets, /模式只由 implement 開頭選本批一次|原 TDD／回歸收尾只由 implement 開頭選本批一次/)
  assert.match(tickets, /這裡不另問、不預填模式/)
  assert.match(tickets, /單票不能混用兩族/)
  assert.doesNotMatch(tickets, /Classify TDD before the ticket is approved/)
})

test('新 description 與正文排除回歸收尾但保留 TDD 入口', () => {
  assert.match(tdd, /description:.*Do not use for regression-closeout batches/)
  assert.match(tdd, /適用條件與 description 相同/)
  assert.match(tdd, /保留 model-callable 與 implement → Skill\(tdd\) 接線/)
  assert.doesNotMatch(tdd, /disable-model-invocation:/)
  assert.match(tdd, /\*\*Red before green\.\*\*/)
})

test('兩路保留原共用驗證與收尾，補測在最後 review 前', () => {
  assert.match(implement, /有缺口就仍未達驗收，不進最後 review/)
  assert.match(implement, /Run the full test suite once/)
  assert.match(implement, /Run typechecking regularly and single test files regularly/)
  assert.match(implement, /Skill\(review-implement\)/)
  assert.match(implement, /For a started implement run in either testing mode/)
  assert.match(implement, /不是人類選擇或測試品質的機器證明/)
})
