import { expect, test } from '@playwright/test'
import { apiFixture, complete, start } from './fixtures/survey'

test('REST flow uses host bearer, structured answers, back and confirmed deletion', async ({ page }) => {
  const fixture = await apiFixture(page)
  await start(page)
  await complete(page)
  await expect(page.getByText('Дерматолог', { exact: true })).toBeVisible()
  expect(fixture.answers).toHaveLength(5)
  expect(fixture.answers[4].value).toMatchObject({ hospitalizations_last_year: ['Synthetic admission'] })
  await page.getByRole('button', { name: 'Уточнить ответы' }).click()
  await page.getByRole('button', { name: '1. Что вас беспокоит?' }).click()
  await expect(page.getByText('Дерматолог', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('radio', { name: 'Кожа', exact: true })).toBeChecked()
  await page.getByRole('button', { name: 'Удалить обращение' }).click()
  expect(fixture.deletions).toHaveLength(0)
  await page.getByRole('button', { name: 'Отмена' }).click()
  expect(fixture.deletions).toHaveLength(0)
  await page.getByRole('button', { name: 'Удалить обращение' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Удалить', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Несколько важных слов' })).toBeVisible()
  expect(fixture.deletions).toHaveLength(1)
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)
})

test('lost confirmation retries the exact answer UUID and advances once', async ({ page }) => {
  const fixture = await apiFixture(page, { lostAnswer: true })
  await start(page)
  await page.getByRole('radio', { name: 'Кожа', exact: true }).check()
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await expect(page.getByRole('alert')).toContainText('Не удалось подтвердить')
  await page.getByRole('button', { name: 'Повторить действие' }).click()
  await expect(page.getByRole('heading', { name: 'Важные сведения о самочувствии' })).toBeVisible()
  expect(fixture.answers).toHaveLength(2)
  expect(fixture.answers[0]).toEqual(fixture.answers[1])
  await expect(page.getByRole('progressbar')).toHaveAttribute('value', '20')
})

test('conflict blocks submission until state is refreshed', async ({ page }) => {
  await apiFixture(page, { conflict: true })
  await start(page)
  await page.getByRole('radio', { name: 'Кожа', exact: true }).check()
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await expect(page.getByRole('alert')).toContainText('Состояние обращения изменилось')
  await expect(page.getByRole('button', { name: 'Продолжить' })).toBeDisabled()
  await page.getByRole('button', { name: 'Обновить состояние' }).click()
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await expect(page.getByRole('heading', { name: 'Важные сведения о самочувствии' })).toBeVisible()
})

test('expiration replaces old fields with a new consent flow', async ({ page }) => {
  await apiFixture(page, { expiredAnswer: true })
  await start(page)
  await page.getByRole('radio', { name: 'Кожа', exact: true }).check()
  await page.getByLabel('Что беспокоит — своими словами').fill('Synthetic expiring draft')
  await page.getByRole('button', { name: 'Продолжить' }).click()
  await expect(page.getByRole('heading', { name: 'Обращение недоступно' })).toBeVisible()
  await page.getByRole('button', { name: 'Начать новый опрос' }).click()
  await expect(page.getByRole('checkbox', { name: /Я понимаю/ })).not.toBeChecked()
})

for (const malformedEmergency of [false, true]) {
  test('emergency response has unconditional visual priority: malformed=' + malformedEmergency, async ({ page }) => {
    await apiFixture(page, { scenario: 'emergency', malformedEmergency })
    await start(page)
    await page.getByRole('radio', { name: 'Кожа', exact: true }).check()
    await page.getByRole('button', { name: 'Продолжить' }).click()
    await expect(page.getByRole('heading', { name: 'Вызовите скорую помощь' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Позвонить 103' })).toHaveAttribute('href', 'tel:103')
    await expect(page.getByRole('button', { name: 'Назад', exact: true })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Продолжить' })).toHaveCount(0)
  })
}

test('UNKNOWN displays clarification, not a made-up recommendation', async ({ page }) => {
  await apiFixture(page, { scenario: 'unknown' })
  await start(page)
  await complete(page)
  await expect(page.getByText('Нужно уточнение', { exact: true })).toBeVisible()
  await expect(page.getByText('Самопомощь', { exact: true })).toHaveCount(0)
})

test('delete failure retains the current session until confirmed success', async ({ page }) => {
  const fixture = await apiFixture(page, { deleteFailure: true })
  await start(page)
  await page.getByRole('button', { name: 'Удалить обращение' }).click()
  const modal = page.getByRole('dialog')
  await modal.getByRole('button', { name: 'Удалить', exact: true }).click()
  await expect(modal.getByRole('alert')).toBeVisible()
  await modal.getByRole('button', { name: 'Удалить', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Несколько важных слов' })).toBeVisible()
  expect(fixture.deletions).toHaveLength(2)
  expect(fixture.deletions[0]).toEqual(fixture.deletions[1])
})
