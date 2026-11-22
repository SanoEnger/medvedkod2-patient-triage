import { expect } from '@playwright/test'
import type { Page } from '@playwright/test'
import { ApiError } from '../../src/api/client'
import { createMockClient } from '../../src/api/mock'
import type { AnswerRequest, Survey } from '../../src/api/contracts'
import type { DemoScenario } from '../../src/api/mock'

export async function apiFixture(page: Page, options: {
  scenario?: DemoScenario; lostAnswer?: boolean; deleteFailure?: boolean; conflict?: boolean; expiredAnswer?: boolean; malformedEmergency?: boolean
} = {}) {
  const client = createMockClient(options.scenario)
  const answers: AnswerRequest[] = []
  const deletions: string[] = []
  let current: Survey | null = null
  let lost = false, failedDelete = false, conflicted = false, expired = false
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    if (path.endsWith('/auth/launch')) {
      const body = request.postDataJSON()
      expect(body).toEqual(body.mode === 'demo' ? { mode: 'demo' } : { mode: 'host', host_token: 'synthetic-jwt' })
      await route.fulfill({ json: { access_token: 'synthetic-api-session', token_type: 'bearer', expires_in: 3600 } })
      return
    }
    expect(request.headers().authorization).toBe('Bearer synthetic-api-session')
    if (path === '/api/v1/chats/availability') {
      await route.fulfill({ json: { active_survey: current && ['COLLECTING', 'REVIEWING'].includes(current.status) ? current : null } })
      return
    }
    const id = path.split('/')[4]
    try {
      if (request.method() === 'POST' && path === '/api/v1/sessions') {
        expect(request.postDataJSON()).toEqual({ accepted_disclaimer: true })
        await route.fulfill({ status: 201, json: current = await client.create() })
      } else if (path.endsWith('/answers')) {
        const body = request.postDataJSON() as AnswerRequest
        answers.push(body)
        if (options.expiredAnswer && !expired) { expired = true; throw new ApiError(404) }
        if (options.conflict && !conflicted) { conflicted = true; throw new ApiError(409) }
        const response = current = await client.answer(id, body)
        if (options.lostAnswer && !lost) { lost = true; await route.abort(); return }
        await route.fulfill({ json: options.malformedEmergency ? { emergency: true } : response })
      } else if (path.endsWith('/back')) {
        await route.fulfill({ json: current = await client.back(id, request.postDataJSON().target_step) })
      } else if (path.endsWith('/triage')) {
        const result = await client.triage(id)
        current = await client.get(id)
        await route.fulfill({ json: result })
      } else if (request.method() === 'DELETE') {
        deletions.push(id)
        if (options.deleteFailure && !failedDelete) { failedDelete = true; throw new ApiError(503) }
        await client.delete(id)
        current = null
        await route.fulfill({ status: 204, body: '' })
      } else {
        await route.fulfill({ json: await client.get(id) })
      }
    } catch (error) {
      if (!(error instanceof ApiError)) throw error
      await route.fulfill({ status: error.status || 503, json: { detail: 'synthetic_error' } })
    }
  })
  return { answers, deletions }
}

export async function start(page: Page, path = '/?token=synthetic-jwt') {
  await page.goto(path)
  await page.getByRole('button', { name: 'Начать опрос', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Начать опрос', exact: true })).toBeDisabled()
  await page.getByRole('checkbox', { name: /Я понимаю/ }).check()
  await page.getByRole('button', { name: 'Начать опрос', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Что вас беспокоит?' })).toBeVisible()
}
export async function complete(page: Page) {
  await page.getByRole('radio', { name: 'Кожа', exact: true }).check()
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await page.getByLabel('Возраст в полных годах').fill('30')
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await page.getByLabel('Как давно появились симптомы?').fill('1 день')
  await page.getByLabel('Выраженность симптомов от 0 до 10').fill('2')
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await page.getByRole('button', { name: 'Ничего из перечисленного' }).click()
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await page.getByLabel('Госпитализации за последний год', { exact: true }).fill('Synthetic admission')
  await page.getByRole('button', { name: 'Завершить опрос и посмотреть итог' }).click()
  await expect(page.getByRole('heading', { name: 'Результат опроса' })).toBeVisible()
}
