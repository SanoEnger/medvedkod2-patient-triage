import { expect, test } from '@playwright/test'
import { apiFixture } from './fixtures/survey'

test.beforeEach(async ({ page }, info) => {
  await apiFixture(page, { scenario: info.title.startsWith('emergency') ? 'emergency' : 'planned' })
})
import type { Locator, Page } from '@playwright/test'

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
}
async function contrast(locator: Locator, property: 'color' | 'borderTopColor' = 'color') {
  const colors = await locator.evaluate((element, property) => {
    let surface: Element | null = element
    while (surface && getComputedStyle(surface).backgroundColor === 'rgba(0, 0, 0, 0)') surface = surface.parentElement
    return [getComputedStyle(element)[property], getComputedStyle(surface!).backgroundColor]
  }, property)
  const luminances = colors.map((color) => {
    const [r, g, b] = color.match(/[\d.]+/g)!.slice(0, 3).map((channel) => {
      const value = Number(channel) / 255
      return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4
    })
    return r * .2126 + g * .7152 + b * .0722
  })
  return (Math.max(...luminances) + .05) / (Math.min(...luminances) + .05)
}

for (const width of [320, 360, 390]) for (const scale of [1, 2]) {
  test('all survey screens, both modes at ' + width + 'px and ' + scale * 100 + '% text', async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/')
    const toggle = page.getByRole('button', { name: 'Версия для слабовидящих', exact: true })
    await page.getByRole('button', { name: 'Начать опрос', exact: true }).waitFor()
    await page.evaluate((scale) => { document.documentElement.style.fontSize = String(scale * 100) + '%' }, scale)
    const header = await page.locator('.site-header').boundingBox()
    const controls = await page.locator('.readability-controls').boundingBox()
    expect(controls!.y).toBeGreaterThanOrEqual(header!.y + header!.height)
    await page.getByRole('button', { name: 'Начать опрос', exact: true }).click()
    for (const mode of ['enhanced', 'default']) {
      await toggle.click()
      await expect(toggle).toHaveAttribute('aria-pressed', String(mode === 'enhanced'))
      await noOverflow(page)
    }
    await page.getByRole('checkbox', { name: /Я понимаю/ }).check()
    await page.getByRole('button', { name: 'Начать опрос', exact: true }).click()
    await page.getByRole('radio', { name: 'Кожа', exact: true }).check()
    const text = page.getByLabel('Что беспокоит — своими словами')
    await text.fill('Synthetic retained readability draft')
    for (const mode of ['enhanced', 'default']) {
      await toggle.click()
      await expect(text).toHaveValue('Synthetic retained readability draft')
      await expect(page.getByRole('radio', { name: 'Кожа', exact: true })).toBeChecked()
      expect(await text.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBe((mode === 'enhanced' ? 20 : 16) * scale)
      await noOverflow(page)
    }
    // Keep enhanced text for the remaining, denser steps.
    await toggle.click()
    await page.getByRole('button', { name: 'Продолжить' }).click()
    await noOverflow(page)
    await page.getByLabel('Возраст в полных годах').fill('30')
    await page.getByRole('button', { name: 'Продолжить' }).click()
    await noOverflow(page)
    await page.getByLabel('Как давно появились симптомы?').fill('1 день')
    await page.getByLabel('Выраженность симптомов от 0 до 10').fill('2')
    await page.getByRole('button', { name: 'Продолжить' }).click()
    await page.getByRole('button', { name: 'Ничего из перечисленного' }).click()
    await noOverflow(page)
    await page.getByRole('button', { name: 'Продолжить' }).click()
    await noOverflow(page)
    await page.getByLabel('Госпитализации за последний год', { exact: true }).fill('Synthetic admission')
    await page.getByRole('button', { name: 'Сохранить ответы и посмотреть итог' }).click()
    await expect(page.getByRole('heading', { name: 'Результат опроса' })).toBeVisible()
    await noOverflow(page)
    await page.getByRole('button', { name: 'Удалить обращение' }).click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await noOverflow(page)
    await page.getByRole('button', { name: 'Отмена' }).click()
  })
}

test('enhanced contrast and keyboard toggle', async ({ page }) => {
  await page.goto('/')
  const toggle = page.getByRole('button', { name: 'Версия для слабовидящих', exact: true })
  await page.getByRole('button', { name: 'Начать опрос', exact: true }).waitFor()
  await page.keyboard.press('Tab'); await page.keyboard.press('Tab'); await page.keyboard.press('Tab')
  await expect(toggle).toBeFocused()
  await page.keyboard.press('Space')
  await expect(toggle).toHaveAttribute('aria-pressed', 'true')
  const start = page.getByRole('button', { name: 'Начать опрос', exact: true })
  await expect(start).toHaveCSS('background-color', 'rgb(84, 59, 145)')
  for (const element of await page.locator('h1, h2, h3, p, button, .brand-caption, .mode-badge, .step-number, .site-footer span').all()) {
    if (await element.isVisible()) expect(await contrast(element), await element.innerText()).toBeGreaterThanOrEqual(7)
  }
  await start.click()
  await page.getByRole('checkbox', { name: /Я понимаю/ }).check()
  await page.getByRole('button', { name: 'Начать опрос', exact: true }).click()
  const text = page.getByLabel('Что беспокоит — своими словами')
  expect(await contrast(text)).toBeGreaterThanOrEqual(7)
  expect(await contrast(text, 'borderTopColor')).toBeGreaterThanOrEqual(3)
})

for (const width of [320, 390]) {
  test('emergency stays reachable at ' + width + 'px and 200% enhanced text', async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    await page.goto('/?scenario=emergency')
    await page.getByRole('button', { name: 'Начать опрос', exact: true }).click()
    await page.getByRole('button', { name: 'Версия для слабовидящих', exact: true }).click()
    await page.evaluate(() => { document.documentElement.style.fontSize = '200%' })
    await page.getByRole('checkbox', { name: /Я понимаю/ }).check()
    await page.getByRole('button', { name: 'Начать опрос', exact: true }).click()
    await page.getByRole('radio', { name: 'Кожа', exact: true }).check()
    await page.getByRole('button', { name: 'Продолжить' }).click()
    await expect(page.getByRole('heading', { name: 'Вызовите скорую помощь' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Позвонить 103' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Позвонить 112' })).toBeVisible()
    await noOverflow(page)
  })
}
