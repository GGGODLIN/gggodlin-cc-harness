import { test as base, expect, BrowserContext, Page } from '@playwright/test'

type EnvOptions = {
  storeUrl: string
  storePassword: string
}

export const test = base.extend<EnvOptions>({
  storeUrl: ['https://REPLACE-ME.example.com', { option: true }],
  storePassword: ['REPLACE-ME', { option: true }],

  context: async ({ context }, use) => {
    await installRouteOverrides(context)
    await use(context)
  },

  page: async ({ page, storeUrl, storePassword }, use) => {
    await passwordWallLogin(page, storeUrl, storePassword)
    await use(page)
  },
})

export { expect }

async function installRouteOverrides(context: BrowserContext) {
  await context.route('**/REPLACE-cdn-pattern/**', async (route) => {
    const response = await route.fetch({ headers: { cookie: 'REPLACE-ME' } })
    await route.fulfill({ response })
  })
}

async function passwordWallLogin(page: Page, storeUrl: string, storePassword: string) {
  await page.goto(storeUrl)
  const passwordInput = page.locator('input[type=password]')
  if (await passwordInput.count()) {
    await passwordInput.fill(storePassword)
    await passwordInput.press('Enter')
  }
}

export async function addToCartViaApi(page: Page, variantId: number, quantity = 1) {
  await page.request.post('/cart/add.js', {
    data: { id: variantId, quantity },
  })
}
