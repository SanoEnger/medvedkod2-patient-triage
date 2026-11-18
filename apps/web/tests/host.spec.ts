import { expect, test } from '@playwright/test'

test('host JWT overrides demo, is exchanged once and removed from URL', async ({ page }) => {
  let calls = 0
  await page.route('**/api/v1/auth/launch', async (route) => {
    calls++
    expect(route.request().postDataJSON()).toEqual({ mode: 'host', host_token: 'synthetic-jwt' })
    await route.fulfill({ json: { access_token: 'synthetic-app-session', token_type: 'bearer', expires_in: 3600 } })
  })
  await page.goto('/?token=synthetic-jwt&keep=yes#section')
  await expect(page.getByText('MAX', { exact: true })).toBeVisible()
  expect(page.url()).not.toContain('token=')
  expect(page.url()).toContain('keep=yes#section')
  expect(calls).toBe(1)
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)
  await page.getByRole('button', { name: 'Открыть пример интерфейса' }).click()
  expect(calls).toBe(1)
})

for (const status of [401, 503]) {
  test(`failed host login ${status} never falls back to demo`, async ({ page }) => {
    await page.route('**/api/v1/auth/launch', (route) => route.fulfill({ status, json: { detail: 'synthetic' } }))
    await page.goto('/?token=synthetic-expired')
    await expect(page.getByRole('alert')).toContainText('Вернитесь в MAX')
    await expect(page.getByText('Демоверсия', { exact: true })).toHaveCount(0)
    expect(page.url()).not.toContain('synthetic-expired')
  })
}

test('malformed API session rejected', async ({ page }) => {
  await page.route('**/api/v1/auth/launch', (route) => route.fulfill({ json: { access_token: 'synthetic' } }))
  await page.goto('/?token=synthetic-jwt')
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByText('MAX', { exact: true })).toHaveCount(0)
})

test('ambiguous duplicate JWTs are removed without exchange', async ({ page }) => {
  let calls = 0
  await page.route('**/api/v1/auth/launch', async (route) => { calls++; await route.abort() })
  await page.goto('/?token=one&token=two')
  await expect(page.getByRole('alert')).toBeVisible()
  expect(calls).toBe(0)
  expect(page.url()).not.toContain('token=')
})
