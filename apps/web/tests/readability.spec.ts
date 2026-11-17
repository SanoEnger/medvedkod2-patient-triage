import { expect, test } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'

async function expectNoOverflow(page: Page) {
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

for (const width of [320, 360, 390]) {
  for (const scale of [1, 2]) {
    test(`both readability modes at ${width}px and ${scale * 100}% text`, async ({ page }) => {
      await page.setViewportSize({ width, height: 844 })
      await page.goto('/')
      const toggle = page.getByRole('button', { name: 'Читаемость', exact: true })
      const open = page.getByRole('button', { name: 'Открыть пример интерфейса' })
      await expect(open).toBeVisible()
      await page.evaluate((scale) => { document.documentElement.style.fontSize = `${scale * 100}%` }, scale)
      const header = await page.locator('.site-header').boundingBox()
      const controls = await page.locator('.readability-controls').boundingBox()
      expect(controls!.y).toBeGreaterThanOrEqual(header!.y + header!.height)
      for (const mode of ['default', 'enhanced']) {
        if (mode === 'enhanced') await toggle.click()
        await expect(toggle).toHaveAttribute('aria-pressed', String(mode === 'enhanced'))
        expect(await open.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBe((mode === 'enhanced' ? 20 : 15) * scale)
        await expectNoOverflow(page)
      }

      await open.click()
      const select = page.getByLabel('Пример варианта')
      const text = page.getByLabel('Пример текстового ответа')
      await select.selectOption('second')
      await text.fill('Synthetic readability example')
      await page.getByRole('button', { name: 'Проверить форму' }).click()
      for (const mode of ['default', 'enhanced']) {
        await toggle.click()
        await expect(toggle).toHaveAttribute('aria-pressed', String(mode === 'enhanced'))
        await expect(select).toHaveValue('second')
        await expect(text).toHaveValue('Synthetic readability example')
        await expect(page.getByRole('status')).toContainText('данные никуда не отправлены')
        await expectNoOverflow(page)
        expect(await select.evaluate((element: HTMLSelectElement) => {
          const style = getComputedStyle(element)
          const canvas = document.createElement('canvas')
          const context = canvas.getContext('2d')!
          context.font = `${style.fontSize} ${style.fontFamily}`
          return context.measureText(element.selectedOptions[0].text).width + parseFloat(style.paddingLeft) + parseFloat(style.paddingRight) + 24 <= element.clientWidth
        })).toBe(true)
      }
      await page.getByRole('button', { name: 'На главную' }).click()
      await expect(page.getByRole('heading', { level: 1 })).toBeFocused()

      await page.goto('/?demo=error-once')
      await page.evaluate((scale) => { document.documentElement.style.fontSize = `${scale * 100}%` }, scale)
      await expect(page.getByRole('alert')).toBeVisible()
      await expectNoOverflow(page)
      await toggle.click()
      await expectNoOverflow(page)
      await page.getByRole('button', { name: 'Попробовать снова' }).click()
      await expect(open).toBeVisible()
      await expect(page.locator('.app-shell')).toHaveAttribute('data-readability', 'enhanced')
    })
  }
}

test('enhanced contrast, focus and keyboard toggle', async ({ page }) => {
  await page.goto('/')
  const toggle = page.getByRole('button', { name: 'Читаемость', exact: true })
  await page.getByRole('button', { name: 'Открыть пример интерфейса' }).waitFor()
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await page.keyboard.press('Tab')
  await expect(toggle).toBeFocused()
  await page.keyboard.press('Space')
  await expect(toggle).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: 'Открыть пример интерфейса' })).toHaveCSS('background-color', 'rgb(84, 59, 145)')
  expect(await toggle.evaluate((element) => getComputedStyle(element).outlineStyle)).toBe('solid')
  for (const element of await page.locator('h1, h2, h3, p, button, .brand-caption, .mode-badge, .step-number, .site-footer span').all()) {
    if (await element.isVisible()) expect(await contrast(element), await element.innerText()).toBeGreaterThanOrEqual(7)
  }
  const open = page.getByRole('button', { name: 'Открыть пример интерфейса' })
  await open.hover()
  expect(await contrast(open)).toBeGreaterThanOrEqual(7)
  await open.click()
  const select = page.getByLabel('Пример варианта')
  expect(await contrast(select)).toBeGreaterThanOrEqual(7)
  expect(await contrast(select, 'borderTopColor')).toBeGreaterThanOrEqual(3)
  await page.keyboard.press('Tab')
  await expect(select).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('Пример текстового ответа')).toBeFocused()
})
