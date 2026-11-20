import { env } from 'node:process'
import { expect, test } from '@playwright/test'
import { complete, start } from '../fixtures/survey'

const origin = env.MEDVED_LIVE_API_ORIGIN || 'https://127.0.0.1:8444'
let token = ''
let ids: Set<string>
test.beforeEach(async ({ page }) => {
  token = ''
  ids = new Set()
  page.on('response', async (response) => {
    if (response.url().endsWith('/api/v1/auth/launch') && response.status() === 200) token = (await response.json()).access_token
    if (response.url().endsWith('/api/v1/sessions') && response.status() === 201) ids.add((await response.json()).id)
  })
})
test.afterEach(async ({ request }) => {
  if (token) for (const id of ids) await request.delete(origin + '/api/v1/sessions/' + id, { headers: { Authorization: 'Bearer ' + token } })
})

test('real browser → HTTPS API → PostgreSQL, editing, completion and delete', async ({ page, request }) => {
  await start(page, '/')
  const medical = page.waitForRequest((request) => request.url().endsWith('/answers') && request.postDataJSON().question_key === 'medical_history')
  await complete(page)
  expect((await medical).postDataJSON().value.hospitalizations_last_year).toEqual(['Synthetic admission'])
  await expect(page.getByText('Дерматолог', { exact: true })).toBeVisible()
  const id = [...ids][0]
  await page.getByRole('button', { name: 'Завершить опрос' }).click()
  await expect(page.getByText(/Ответы сохранены/)).toBeVisible()
  let state = await request.get(origin + '/api/v1/sessions/' + id, { headers: { Authorization: 'Bearer ' + token } })
  expect((await state.json()).status).toBe('COMPLETED')
  await page.getByRole('button', { name: 'Уточнить ответы' }).click()
  await page.getByRole('button', { name: '1. Что вас беспокоит?' }).click()
  await expect(page.getByRole('heading', { name: 'Что вас беспокоит?' })).toBeVisible()
  state = await request.get(origin + '/api/v1/sessions/' + id, { headers: { Authorization: 'Bearer ' + token } })
  expect(await state.json()).toMatchObject({ status: 'COLLECTING', progress: { answered: 0 }, result: null })
  await page.getByRole('button', { name: 'Удалить обращение' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Удалить', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Несколько важных слов' })).toBeVisible()
  expect((await request.get(origin + '/api/v1/sessions/' + id, { headers: { Authorization: 'Bearer ' + token } })).status()).toBe(404)
})

const emergencies = [
  ['У меня болит грудь', 'RF_CHEST_PAIN'],
  ['Одышка в покое', 'RF_DYSPNEA_REST'],
  ['Потеря сознания', 'RF_LOSS_CONSCIOUSNESS'],
  ['Судороги', 'RF_SEIZURE'],
  ['Кровотечение', 'RF_BLEEDING'],
  ['Асимметрия лица', 'RF_FAST'],
  ['Анафилаксия', 'RF_ANAPHYLAXIS'],
  ['Острая боль в животе', 'RF_ACUTE_ABDOMINAL_PAIN'],
  ['Травма головы с потерей сознания', 'RF_HEAD_INJURY_LOC'],
]
for (const [text, code] of emergencies) {
  test('server safety is reflected immediately: ' + code, async ({ page, request }) => {
    await start(page, '/')
    await page.getByRole('radio', { name: 'Другое', exact: true }).check()
    await page.getByLabel('Что беспокоит — своими словами').fill(text)
    await page.getByRole('button', { name: 'Продолжить' }).click()
    await expect(page.getByRole('heading', { name: 'Вызовите скорую помощь' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Назад', exact: true })).toHaveCount(0)
    const state = await request.get(origin + '/api/v1/sessions/' + [...ids][0], { headers: { Authorization: 'Bearer ' + token } })
    expect((await state.json()).matched_rule_codes).toContain(code)
  })
}

test('child high fever is evaluated by the backend at the context step', async ({ page, request }) => {
  await start(page, '/')
  await page.getByRole('radio', { name: 'Температура', exact: true }).check()
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await page.getByLabel('Возраст в полных годах').fill('10')
  await page.getByLabel('Температура тела, °C').fill('39.6')
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await expect(page.getByRole('heading', { name: 'Вызовите скорую помощь' })).toBeVisible()
  const state = await request.get(origin + '/api/v1/sessions/' + [...ids][0], { headers: { Authorization: 'Bearer ' + token } })
  expect((await state.json()).matched_rule_codes).toContain('RF_CHILD_FEVER_39_5')
})

test('real incomplete data remain UNKNOWN', async ({ page }) => {
  await start(page, '/')
  await page.getByRole('radio', { name: 'Другое', exact: true }).check()
  for (let step = 0; step < 4; step++) await page.getByRole('button', { name: 'Продолжить' }).click()
  await page.getByRole('button', { name: 'Сохранить ответы и посмотреть итог' }).click()
  await expect(page.getByText('Нужно уточнение', { exact: true })).toBeVisible()
  await expect(page.getByText('Самопомощь', { exact: true })).toHaveCount(0)
})

test('retry after a lost real API response does not duplicate the answer', async ({ page, request }) => {
  const bodies: unknown[] = []
  let lost = false
  await page.route('**/answers', async (route) => {
    bodies.push(route.request().postDataJSON())
    if (!lost) {
      lost = true
      const response = await route.fetch()
      expect(response.status()).toBe(200)
      await route.abort()
    } else await route.continue()
  })
  await start(page, '/')
  await page.getByRole('radio', { name: 'Кожа', exact: true }).check()
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await page.getByRole('button', { name: 'Повторить действие' }).click()
  await expect(page.getByRole('heading', { name: 'Важные сведения о самочувствии' })).toBeVisible()
  expect(bodies[0]).toEqual(bodies[1])
  const state = await request.get(origin + '/api/v1/sessions/' + [...ids][0], { headers: { Authorization: 'Bearer ' + token } })
  expect((await state.json()).progress.answered).toBe(1)
})
