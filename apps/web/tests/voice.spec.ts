import { expect, test } from '@playwright/test'
import { apiFixture, start } from './fixtures/survey'

test.use({ launchOptions: { args: ['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream'] } })

test('microphone is purple only during recording and transcription stays in the draft', async ({ page }) => {
  const fixture = await apiFixture(page)
  await page.route('**/api/v1/voice/transcriptions', async (route) => {
    const request = route.request()
    expect(request.method()).toBe('POST')
    expect(request.headers().authorization).toBe('Bearer synthetic-api-session')
    expect(request.headers()['content-type']).toMatch(/^audio\//)
    expect(request.postDataBuffer()?.length).toBeGreaterThan(0)
    await route.fulfill({ json: { text: 'Тестовая диктовка' } })
  })

  await start(page)
  const complaint = page.getByLabel('Что беспокоит — своими словами')
  const microphone = page.getByRole('button', { name: 'Голосовой ввод' })
  await complaint.fill('Мой текст')
  await expect(microphone).toHaveCSS('color', 'rgb(115, 115, 115)')
  await microphone.click()
  await expect(microphone).toHaveCSS('color', 'rgb(117, 96, 184)')
  await page.waitForTimeout(250) // Let the fake microphone produce audio frames.
  await microphone.click()
  await expect(complaint).toHaveValue('Мой текст Тестовая диктовка')
  await expect(microphone).toHaveCSS('color', 'rgb(115, 115, 115)')
  expect(fixture.answers).toHaveLength(0)
})
