import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { QUESTIONS } from '../src/api/contracts'
import type { Survey } from '../src/api/contracts'
import type { Clinic, ClinicSearch } from '../src/api/clinics'
import type { ChatMessage } from '../src/api/chat'
import { demoResult } from '../src/api/mock'
import { apiFixture, complete, start } from './fixtures/survey'

const address = { label: 'Курган, улица Гоголя, 5', city: 'Курган', lat: 55.44, lon: 65.34 }
const insurer = { id: 'example', name: 'Пример страховой' }
const branch: Clinic = {
  id: 'central', name: 'Городская поликлиника', address: 'Курган, улица Гоголя, 20', lat: 55.445, lon: 65.345,
  kind: 'public', phones: ['+12025550101'], website: 'https://clinic.example/', booking_url: 'https://clinic.example/booking',
  gosuslugi_url: 'https://www.gosuslugi.ru/10700', gosuslugi_select_branch: true,
  poliklinika45_url: 'https://www.poliklinika45.ru/service/hospitals/view/1143538',
  demo: false, distance_km: 0.5,
  payments: [
    { method: 'oms', specialty_code: 'dermatologist', insurer: null, program: null },
    { method: 'dms', specialty_code: 'dermatologist', insurer, program: null },
  ],
  specialties: ['dermatologist'],
  sources: [{ name: 'Поликлиника45', url: 'https://www.poliklinika45.ru/service/schedule/profiles', updated_at: '2026-11-25T05:00:00Z' }],
}
const image = Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7', 'base64')

async function clinicRoutes(page: Page, items = [branch]) {
  const searches: ClinicSearch[] = []
  const addresses: string[] = []
  await page.route('**/api/v1/clinics/reverse-geocode', async (route) => {
    expect(route.request().headers().authorization).toBe('Bearer synthetic-api-session')
    expect(Object.keys(route.request().postDataJSON()).sort()).toEqual(['lat', 'lon'])
    await route.fulfill({ json: { candidates: [{ ...address, lat: 55.4403 }] } })
  })
  await page.route('**/api/v1/clinics/geocode', async (route) => {
    const request = route.request()
    expect(request.headers().authorization).toBe('Bearer synthetic-api-session')
    const body = request.postDataJSON()
    expect(Object.keys(body)).toEqual(['address'])
    addresses.push(body.address)
    if (body.address.startsWith('Шадринск')) {
      await route.fulfill({ status: 422, json: { detail: 'clinic_outside_pilot' } })
    } else {
      await route.fulfill({ json: { candidates: body.address.includes('999') ? []
        : [address, { ...address, label: 'Курган, улица Гоголя, 5к1', lat: 55.441 }] } })
    }
  })
  await page.route('**/api/v1/clinics/search', async (route) => {
    expect(route.request().headers().authorization).toBe('Bearer synthetic-api-session')
    const body = route.request().postDataJSON() as ClinicSearch
    searches.push(body)
    await route.fulfill({ json: { items, insurers: [] } })
  })
  return { searches, addresses }
}

async function tiles(page: Page, { failOsm = false, failYandex = false, failFirstYandex = false } = {}) {
  const osm: string[] = []
  const yandex: string[] = []
  await page.route('https://tile.openstreetmap.org/**', async (route) => {
    osm.push((await route.request().allHeaders()).referer || '')
    if (failOsm) await route.abort()
    else await route.fulfill({ contentType: 'image/gif', body: image })
  })
  await page.route('https://tiles.api-maps.yandex.ru/**', async (route) => {
    const request = route.request()
    yandex.push((await request.allHeaders()).referer || '')
    expect(new URL(request.url()).searchParams.get('projection')).toBe('web_mercator')
    if (failYandex || (failFirstYandex && yandex.length === 1)) await route.abort()
    else await route.fulfill({ contentType: 'image/gif', body: image })
  })
  return { osm, yandex }
}

async function openNewResult(page: Page) {
  await apiFixture(page)
  await start(page, '/?token=synthetic-jwt')
  await complete(page)
  await page.getByRole('button', { name: 'Найти поликлиники рядом' }).click()
}

async function openSavedResult(page: Page, scenario: 'planned' | 'unknown' | 'emergency', age = 30, specialty?: string) {
  await apiFixture(page)
  const id = '12345678-1234-1234-1234-123456789abc'
  const date = '2026-11-25T00:00:00Z'
  await page.route('**/api/v1/chats?**', (route) => route.fulfill({ json: {
    items: [{ id, kind: 'questionnaire_result', title: 'Сохранённый опрос', emergency: scenario === 'emergency',
      created_at: date, last_activity_at: date, expires_at: date }], next_cursor: null,
  } }))
  await page.route('**/api/v1/chats', (route) => route.fulfill({ json: {
    items: [{ id, kind: 'questionnaire_result', title: 'Сохранённый опрос', emergency: scenario === 'emergency',
      created_at: date, last_activity_at: date, expires_at: date }], next_cursor: null,
  } }))
  const status = scenario === 'emergency' ? 'EMERGENCY_STOP' : 'COMPLETED'
  const result = demoResult(scenario)
  if (specialty) result.specialty = specialty
  const survey: Survey = {
    id, status, state: status, progress: { answered: QUESTIONS.length, total: QUESTIONS.length, percent: 100 },
    current_question: null, next_question: null, expires_at: date, emergency: scenario === 'emergency', message: null,
    matched_rule_codes: [], urgency: result.urgency, result,
    answers: scenario === 'unknown' ? undefined : { patient_context: {
      age_years: age, temperature_c: null, pregnancy: null, lactation: null,
    } },
  }
  await page.route('**/api/v1/sessions/' + id, (route) => route.fulfill({ json: survey }))
  await page.goto('/?token=synthetic-jwt')
  await page.getByRole('button', { name: 'История чатов' }).click()
  await page.getByRole('button', { name: /Открыть:.*Сохранённый опрос/ }).click()
}

test('chat offers clinic search after a specialist recommendation and hides it in an emergency', async ({ page }) => {
  await apiFixture(page)
  const { searches } = await clinicRoutes(page)
  const id = '12345678-1234-1234-1234-123456789abc'
  const date = '2026-11-25T00:00:00Z'
  const messages: ChatMessage[] = []
  const add = (role: ChatMessage['role'], text: string, extra: Partial<ChatMessage> = {}) =>
    messages.push({ id: crypto.randomUUID(), role, text, created_at: date, emergency: false, ...extra })
  add('assistant', 'Здравствуйте!')
  const chat = () => ({
    id, questionnaire_id: null, messages, result: null, pending: false, retryable: false,
    emergency: messages.some((message) => message.emergency),
  })
  await page.route('**/api/v1/chats', (route) => route.fulfill({ status: 201, json: chat() }))
  await page.route('**/api/v1/chats/' + id, (route) => route.fulfill({ json: chat() }))
  const replies = [
    { text: 'Когда появились симптомы?' },
    { text: 'Рекомендую обратиться к дерматологу.', clinic_specialty: 'Дерматолог' },
    { text: 'Срочно позвоните 103/112.', emergency: true },
  ]
  await page.route('**/api/v1/chats/' + id + '/messages', (route) => {
    const { text, client_message_id } = route.request().postDataJSON()
    add('user', text, { client_message_id })
    const reply = replies.shift()!
    add('assistant', reply.text, reply)
    return route.fulfill({ json: chat() })
  })
  const send = async (text: string) => {
    await page.getByLabel('Ваше сообщение').fill(text)
    await page.getByRole('button', { name: 'Отправить', exact: true }).click()
  }
  await page.goto('/?token=synthetic-jwt')
  await page.getByRole('button', { name: 'Начать чат с МедВедом' }).click()
  const offer = page.getByRole('button', { name: 'Посмотреть медучреждения рядом' })
  await expect(page.getByText('Здравствуйте!')).toBeVisible()
  await expect(offer).toHaveCount(0)
  await send('Появилась сыпь.')
  await expect(page.getByText('Когда появились симптомы?')).toBeVisible()
  await expect(offer).toHaveCount(0)
  await send('Два дня назад. К какому врачу обратиться?')
  await expect(page.locator('.chat-message--assistant').last().getByRole('button')).toBeVisible()
  expect(searches).toEqual([])
  await offer.click()
  await expect(page.getByRole('heading', { name: 'Медучреждения рядом' })).toBeVisible()
  await expect(page.getByLabel('Специалист')).toHaveValue('dermatologist')
  expect(searches).toEqual([])
  await page.getByRole('button', { name: 'Назад' }).click()
  await expect(offer).toBeVisible()
  await send('Теперь мне трудно дышать.')
  await expect(page.getByRole('link', { name: 'Позвонить 112' })).toBeVisible()
  await expect(offer).toHaveCount(0)
})

test('manual address after denial, payment filters, booking and origin-only tile Referer', async ({ page, context, baseURL }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator.geolocation, 'getCurrentPosition', { value: (_: unknown, fail: (error: { code: number }) => void) => fail({ code: 1 }) })
  })
  await openNewResult(page)
  const { searches, addresses } = await clinicRoutes(page)
  const provider = await tiles(page, { failYandex: true })
  await expect(page.getByLabel('Специалист')).toHaveValue('dermatologist')
  await expect(page.getByLabel('Возраст пациента')).toHaveValue('adult')
  await page.getByRole('button', { name: 'Определить моё местоположение' }).click()
  await expect(page.getByRole('alert')).toContainText('Доступ к местоположению запрещён')
  await page.getByLabel('Адрес пациента', { exact: true }).fill('Го')
  expect(addresses).toEqual([])
  await page.getByLabel('Адрес пациента', { exact: true }).fill('Гоголя 5, кв. 21')
  await expect(page.getByText('Выберите подходящий адрес.')).toBeVisible()
  expect(addresses).toEqual(['Гоголя 5'])
  expect(searches).toEqual([])
  await page.getByRole('button', { name: address.label, exact: true }).click()
  await expect(page.getByRole('heading', { name: branch.name })).toBeVisible()
  expect(searches[0]).toEqual({ lat: 55.44, lon: 65.34, specialty_code: 'dermatologist', radius_km: 5, patient_group: 'adult' })
  await expect(page.getByRole('region', { name: 'Карта медучреждений' }).getByText('OpenStreetMap contributors')).toBeVisible()
  const origin = new URL(baseURL!).origin + '/'
  await expect.poll(() => provider.osm.length).toBeGreaterThan(0)
  expect(new Set(provider.osm)).toEqual(new Set([origin]))
  if (process.env.VITE_YANDEX_TILES_API_KEY) expect(new Set(provider.yandex)).toEqual(new Set([origin]))
  else expect(provider.yandex).toEqual([])

  const pin = page.locator('.clinic-pin')
  await pin.click()
  await expect(page.getByRole('article', { name: branch.name })).toBeFocused()
  await page.getByRole('button', { name: 'Показать на карте' }).click()
  await expect(pin).toBeFocused()
  await expect(page.getByRole('radio', { name: 'ДМС' })).toHaveCount(0)
  await expect(page.getByText(insurer.name)).toHaveCount(0)
  await page.getByRole('radio', { name: 'ОМС' }).check()
  await expect.poll(() => searches.at(-1)?.payment_method).toBe('oms')
  await expect(page.getByText('Уточните условия приёма по ОМС в регистратуре.')).toBeVisible()
  await expect(page.getByText('Источники данных')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '+12025550101' })).toHaveAttribute('href', 'tel:+12025550101')
  for (const [label, url] of [
    ['Записаться через Госуслуги', branch.gosuslugi_url!],
    ['Записаться через Поликлинику45', branch.poliklinika45_url!],
  ]) {
    const booking = page.getByRole('link', { name: label })
    await expect(booking).toHaveAttribute('href', url)
    await context.route(url, (route) =>
      route.fulfill({ contentType: 'text/html', body: '<title>Synthetic booking page</title>' }))
    const [popup, bookingRequest] = await Promise.all([
      page.waitForEvent('popup'),
      context.waitForEvent('request', (request) => request.url() === url),
      booking.click(),
    ])
    expect((await bookingRequest.allHeaders()).referer).toBeUndefined()
    await popup.close()
  }
  await page.getByRole('radio', { name: 'Платно' }).check()
  await expect.poll(() => searches.at(-1)?.payment_method).toBe('paid')
  const phoneOnly = page.getByRole('article', { name: branch.name })
  await expect(phoneOnly.getByRole('list', { name: 'Телефоны для записи' }).getByRole('link'))
    .toHaveAttribute('href', 'tel:+12025550101')
  await expect(phoneOnly.getByRole('link')).toHaveCount(1)
  await page.getByRole('radio', { name: 'Все', exact: true }).check()
  await expect.poll(() => searches.at(-1)?.payment_method).toBeUndefined()
  await page.getByRole('button', { name: 'Назад', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Результат опроса' })).toBeVisible()
})

test('private clinic offers phone booking in unfiltered results', async ({ page }) => {
  await openNewResult(page)
  await clinicRoutes(page, [{ ...branch, kind: 'private' }])
  await tiles(page)
  await page.getByLabel('Адрес пациента', { exact: true }).fill('Гоголя 5')
  await page.getByRole('button', { name: address.label, exact: true }).click()
  const card = page.getByRole('article', { name: branch.name })
  await expect(card.getByRole('list', { name: 'Телефоны для записи' }).getByRole('link'))
    .toHaveAttribute('href', 'tel:+12025550101')
  await expect(card.getByRole('link')).toHaveCount(1)
})

test('history result, geolocation with permission and fallback when both maps fail', async ({ page, context }) => {
  await context.grantPermissions(['geolocation'])
  await context.setGeolocation({ latitude: 55.44, longitude: 65.34, accuracy: 15 })
  await openSavedResult(page, 'unknown')
  await expect(page.getByText(/Это справочник медучреждений/)).toBeVisible()
  await page.getByRole('button', { name: 'Посмотреть медучреждения рядом' }).click()
  const { searches } = await clinicRoutes(page)
  await tiles(page, { failOsm: true, failYandex: true })
  await expect(page.getByLabel('Специалист')).toHaveValue('')
  expect(searches).toEqual([])
  await page.getByRole('button', { name: 'Определить моё местоположение' }).click()
  await expect(page.getByText('Выберите возрастную группу пациента, чтобы подобрать медучреждения.')).toBeVisible()
  await expect(page.getByLabel('Адрес пациента', { exact: true })).toHaveValue(address.label)
  expect(searches).toEqual([])
  await page.getByLabel('Возраст пациента').selectOption('adult')
  await expect(page.getByText('Карта недоступна. Медучреждения показаны списком.')).toBeVisible()
  await expect(page.getByRole('heading', { name: branch.name })).toBeVisible()
  expect(searches[0]).toEqual({ lat: 55.44, lon: 65.34, radius_km: 5, patient_group: 'adult' })
  await tiles(page)
  await page.getByRole('button', { name: 'Повторить загрузку карты' }).click()
  await expect(page.getByRole('button', { name: 'Показать на карте' })).toBeVisible()
  expect(searches).toHaveLength(1)
  await page.getByRole('button', { name: 'Назад', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Результат опроса' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'К истории' })).toBeVisible()
})

test('unknown house offers a map point and another city is reported', async ({ page }) => {
  await openSavedResult(page, 'planned', 17, 'Врач — акушер-гинеколог')
  await page.getByRole('button', { name: 'Найти поликлиники рядом' }).click()
  const { searches } = await clinicRoutes(page)
  await tiles(page)
  await expect(page.getByLabel('Возраст пациента')).toHaveValue('child')
  await expect(page.getByLabel('Специалист')).toHaveValue('gynecologist')
  const input = page.getByLabel('Адрес пациента', { exact: true })
  await expect(page.getByRole('button', { name: 'Поставить точку на карте' })).toBeVisible()
  await input.fill('Шадринск, Ленина 4')
  await input.press('Enter')
  await expect(page.getByRole('alert')).toContainText('Каталог сейчас покрывает только Курган.')
  await input.fill('Гоголя 999')
  await input.press('Enter')
  await expect(page.getByRole('alert')).toContainText('Дом не найден в справочнике.')
  await page.getByRole('button', { name: 'Поставить точку на карте' }).click()
  const picker = page.getByRole('region', { name: 'Карта выбора точки' })
  await expect(picker).toBeFocused()
  const confirm = page.getByRole('button', { name: 'Искать от этой точки' })
  await expect(confirm).toBeEnabled()
  await picker.click({ position: { x: 90, y: 90 } })
  expect(searches).toHaveLength(0)
  await confirm.click()
  await expect.poll(() => searches.length).toBe(1)
  expect(searches[0]).toMatchObject({ patient_group: 'child', specialty_code: 'gynecologist' })
  expect(searches[0].lat).not.toBeCloseTo(55.445, 4)
  await expect(input).toBeEmpty()
  await expect(page.getByText('Точка поиска выбрана на карте.')).toBeVisible()
  const specialty = page.getByLabel('Специалист')
  await specialty.selectOption('pediatric_surgeon')
  await expect.poll(() => searches.at(-1)?.specialty_code).toBe('pediatric_surgeon')
  await page.getByLabel('Возраст пациента').selectOption('adult')
  await expect(specialty).toHaveValue('')
  await expect(specialty.locator('option[value="pediatric_surgeon"]')).toHaveCount(0)
  await expect.poll(() => searches.at(-1)?.patient_group).toBe('adult')
  expect(searches.at(-1)?.specialty_code).toBeUndefined()
})

test('clinic search retries a temporary failure with the same filters', async ({ page, context }) => {
  await context.grantPermissions(['geolocation'])
  await context.setGeolocation({ latitude: 55.44, longitude: 65.34, accuracy: 10 })
  await openSavedResult(page, 'planned')
  await page.getByRole('button', { name: 'Найти поликлиники рядом' }).click()
  await tiles(page)
  const requests: ClinicSearch[] = []
  await page.route('**/api/v1/clinics/search', async (route) => {
    requests.push(route.request().postDataJSON())
    if (requests.length === 1) {
      await route.fulfill({ status: 503, json: { detail: 'clinic_catalog_unavailable' } })
      return
    }
    await route.fulfill({ json: { items: [{ ...branch, payments: [], oms_needs_confirmation: true }], insurers: [] } })
  })
  await page.getByRole('radio', { name: 'ОМС' }).check()
  await page.getByRole('button', { name: 'Определить моё местоположение' }).click()
  await expect(page.getByRole('alert')).toContainText('Не удалось загрузить медучреждения.')
  await page.getByRole('button', { name: 'Повторить поиск' }).click()
  await expect(page.getByText(/Учреждение участвует в программе ОМС/)).toBeVisible()
  expect(requests).toHaveLength(2)
  expect(requests[1]).toEqual(requests[0])
  expect(requests[1]).toMatchObject({ payment_method: 'oms', patient_group: 'adult', specialty_code: 'dermatologist' })
})

test('changing payment keeps the map and ignores a stale result', async ({ page, context }) => {
  await context.grantPermissions(['geolocation'])
  await context.setGeolocation({ latitude: 55.44, longitude: 65.34, accuracy: 10 })
  await openSavedResult(page, 'planned')
  await page.getByRole('button', { name: 'Найти поликлиники рядом' }).click()
  await tiles(page)
  const slowPaid = { ...branch, name: 'Устаревший платный результат' }
  const readyPaid = { ...branch, name: 'Государственная клиника с платным приёмом', payments: [
    { ...branch.payments[0], method: 'paid' as const },
  ] }
  let releasePaid = () => {}
  const paidWait = new Promise<void>((resolve) => { releasePaid = resolve })
  let finishPaid = () => {}
  const paidFinished = new Promise<void>((resolve) => { finishPaid = resolve })
  await page.route('**/api/v1/clinics/search', async (route) => {
    const query = route.request().postDataJSON() as ClinicSearch
    if (query.payment_method === 'paid') {
      await paidWait
      await route.fulfill({ json: { items: [slowPaid], insurers: [] } }).catch(() => {})
      finishPaid()
      return
    }
    await route.fulfill({ json: { items: [readyPaid], insurers: [] } })
  })
  await page.getByRole('button', { name: 'Определить моё местоположение' }).click()
  const card = page.getByRole('article', { name: readyPaid.name })
  await expect(card.getByRole('link', { name: '+12025550101' })).toBeVisible()
  await expect(card.getByRole('link')).toHaveCount(1)
  const map = page.getByRole('region', { name: 'Карта медучреждений' })
  await card.getByRole('button', { name: 'Показать на карте' }).click()
  await expect(map.locator('.clinic-pin')).toBeFocused()
  await map.evaluate((node) => node.setAttribute('data-test-mounted', 'original'))
  const paidStarted = page.waitForRequest((request) => request.url().endsWith('/clinics/search')
    && request.postDataJSON().payment_method === 'paid')
  try {
    await page.getByRole('radio', { name: 'Платно' }).check()
    await paidStarted
    await expect(page.getByText('Ищем медучреждения…')).toBeVisible()
    await expect(map).toHaveAttribute('data-test-mounted', 'original')
    await expect(map.locator('.clinic-pin')).toHaveCount(0)
    const all = page.getByRole('radio', { name: 'Все', exact: true })
    await all.check()
    await expect(card).toBeVisible()
    await expect(all).toBeFocused()
  } finally {
    releasePaid()
  }
  await paidFinished
  await expect(page.getByRole('heading', { name: slowPaid.name })).toHaveCount(0)
  await expect(map).toHaveAttribute('data-test-mounted', 'original')
})

test('saved emergency keeps emergency phone actions without clinic search', async ({ page }) => {
  await openSavedResult(page, 'emergency')
  await expect(page.getByRole('link', { name: 'Позвонить 103' })).toHaveAttribute('href', 'tel:103')
  await expect(page.getByRole('link', { name: 'Позвонить 112' })).toHaveAttribute('href', 'tel:112')
  await expect(page.getByRole('button', { name: /поликлиники рядом|медучреждения рядом|моё местоположение/ })).toHaveCount(0)
})

test('new emergency keeps emergency phone actions without clinic search', async ({ page }) => {
  await apiFixture(page, { scenario: 'emergency' })
  await start(page)
  await page.getByRole('radio', { name: 'Кожа', exact: true }).check()
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await expect(page.getByRole('link', { name: 'Позвонить 103' })).toHaveAttribute('href', 'tel:103')
  await expect(page.getByRole('link', { name: 'Позвонить 112' })).toHaveAttribute('href', 'tel:112')
  await expect(page.getByRole('button', { name: /поликлиники рядом|медучреждения рядом|моё местоположение/ })).toHaveCount(0)
})

test('Yandex stays primary after one failed tile and uses origin only', async ({ page, context, baseURL }) => {
  test.skip(!process.env.VITE_YANDEX_TILES_API_KEY, 'Run with the synthetic Tiles API key to exercise Yandex')
  await context.grantPermissions(['geolocation'])
  await context.setGeolocation({ latitude: 55.44, longitude: 65.34, accuracy: 10 })
  await openSavedResult(page, 'planned')
  await page.getByRole('button', { name: 'Найти поликлиники рядом' }).click()
  await clinicRoutes(page)
  const provider = await tiles(page, { failFirstYandex: true })
  await page.getByRole('button', { name: 'Определить моё местоположение' }).click()
  await expect(page.getByRole('link', { name: 'Яндекс Карты' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Показать на карте' })).toBeVisible()
  expect(new Set(provider.yandex)).toEqual(new Set([new URL(baseURL!).origin + '/']))
  expect(provider.osm).toEqual([])
})
