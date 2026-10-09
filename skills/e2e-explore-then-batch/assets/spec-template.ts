import { test, expect } from '../fixtures'

test.describe('REPLACE-flow-name', () => {
  test('REPLACE-case-name (trajectory: trajectories/REPLACE-flow-YYYY-MM-DD.md)', async ({ page, storeUrl }) => {
    await page.goto(`${storeUrl}/REPLACE-entry-path`)
    await page.getByRole('button', { name: 'REPLACE' }).click()
    await expect(page.getByRole('region', { name: 'REPLACE' })).toContainText('REPLACE')
  })
})

const caseMatrix = [
  { name: 'REPLACE-case-a', input: { REPLACE: 'REPLACE' }, expected: 'REPLACE' },
]

for (const c of caseMatrix) {
  test(`batch: ${c.name}`, async ({ page, storeUrl }) => {
    await page.goto(`${storeUrl}/REPLACE-entry-path`)
    await expect(page.getByRole('status')).toContainText(c.expected)
  })
}
