import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'
import { QUESTIONS } from '../src/api/contracts'
import type { Survey } from '../src/api/contracts'
import type { Clinic, ClinicSearch } from '../src/api/clinics'
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
  payments: [{ method: 'dms', specialty_code: 'dermatologist', insurer, program: null }],
  specialties: ['dermatologist'],
  sources: [{ name: 'Поликлиника45', url: 'https://www.poliklinika45.ru/service/schedule/profiles', updated_at: '2026-11-25T05:00:00Z' }],
}
const image = Buffer.from('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7', 'base64')

async function clinicRoutes(page: Page, items = [branch]) {
  const searches: ClinicSearch[] = []
  const addresses: string[] = []
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
    await route.fulfill({ json: { items, insurers: body.payment_method === 'dms' ? [insurer] : [] } })
  })
  return { searches, addresses }
}

async function tiles(page: Page, { failOsm = false, failYandex = false } = {}) {
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
    if (failYandex) await route.abort()
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

test('manual address after denial, DMS, booking and origin-only tile Referer', async ({ page, context, baseURL }) => {
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
  await page.getByRole('radio', { name: 'ДМС' }).check()
  await page.getByLabel('Страховая').selectOption(insurer.id)
  await expect(page.getByText('Уточните покрытие у страховой.')).toBeVisible()
  await expect(page.getByText('Источники данных')).toHaveCount(0)
  expect(searches.at(-1)).toMatchObject({ payment_method: 'dms', insurer_id: insurer.id })
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
  const phoneOnly = page.getByRole('article', { name: branch.name })
  await expect(phoneOnly.getByRole('list', { name: 'Телефоны для записи' }).getByRole('link'))
    .toHaveAttribute('href', 'tel:+12025550101')
  await expect(phoneOnly.getByRole('link')).toHaveCount(1)
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
  expect(searches).toEqual([])
  await page.getByLabel('Возраст пациента').selectOption('adult')
  await expect(page.getByText('Карта недоступна. Медучреждения показаны списком.')).toBeVisible()
  await expect(page.getByRole('heading', { name: branch.name })).toBeVisible()
  expect(searches[0]).toEqual({ lat: 55.44, lon: 65.34, radius_km: 5, patient_group: 'adult' })
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
  await input.fill('Шадринск, Ленина 4')
  await input.press('Enter')
  await expect(page.getByRole('alert')).toContainText('Каталог сейчас покрывает только Курган.')
  await input.fill('Гоголя 999')
  await input.press('Enter')
  await expect(page.getByRole('alert')).toContainText('Дом не найден в справочнике.')
  await page.getByRole('button', { name: 'Поставить точку на карте' }).click()
  await page.getByRole('button', { name: 'Искать от центра карты' }).click()
  await expect.poll(() => searches.length).toBe(1)
  expect(searches[0]).toMatchObject({ patient_group: 'child', specialty_code: 'gynecologist' })
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

test('Yandex primary layer has its logo and uses origin only', async ({ page, context, baseURL }) => {
  test.skip(!process.env.VITE_YANDEX_TILES_API_KEY, 'Run with the synthetic Tiles API key to exercise Yandex')
  await context.grantPermissions(['geolocation'])
  await context.setGeolocation({ latitude: 55.44, longitude: 65.34, accuracy: 10 })
  await openSavedResult(page, 'planned')
  await page.getByRole('button', { name: 'Найти поликлиники рядом' }).click()
  await clinicRoutes(page)
  const provider = await tiles(page)
  await page.getByRole('button', { name: 'Определить моё местоположение' }).click()
  await expect(page.getByRole('link', { name: 'Яндекс Карты' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Показать на карте' })).toBeVisible()
  expect(new Set(provider.yandex)).toEqual(new Set([new URL(baseURL!).origin + '/']))
  expect(provider.osm).toEqual([])
})
