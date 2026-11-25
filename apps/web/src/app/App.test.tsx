import { afterEach, expect, test, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as api from '../api/client'
import type { MedvedClient } from '../api/client'
import type { ChatSummary, Conversation } from '../api/chat'
import type { Survey } from '../api/contracts'
import { createMockClient } from '../api/mock'
import { App } from './App'

afterEach(() => { vi.restoreAllMocks() })

test('survey remains mounted on home, blocks chat, then hands its result to MedVed', async () => {
  const base = createMockClient('unknown')
  let current: Survey | null = null
  const conversation = (id?: string): Conversation => ({
    id: id || crypto.randomUUID(), questionnaire_id: id || null,
    result: current?.result || null, emergency: false, pending: false, retryable: false,
    messages: [{ id: crypto.randomUUID(), role: 'assistant', text: 'Готов обсудить ваш результат.', created_at: new Date().toISOString(), emergency: false }],
  })
  const open = vi.fn(async (id?: string) => conversation(id))
  const client: MedvedClient = {
    ...base,
    clinics: { geocode: vi.fn(), reverseGeocode: vi.fn(), search: vi.fn() },
    create: async () => { current = await base.create(); return current },
    answer: async (...args) => { current = await base.answer(...args); return current },
    back: async (...args) => { current = await base.back(...args); return current },
    triage: async (id) => { const result = await base.triage(id); current = await base.get(id); return result },
    chat: {
      list: vi.fn(),
      availability: async () => ({ active_survey: current && ['COLLECTING', 'REVIEWING'].includes(current.status) ? current : null }),
      open, get: async (id) => conversation(id), send: vi.fn(), delete: vi.fn(),
    },
  }
  vi.spyOn(api, 'createApiClient').mockReturnValue(client)
  render(<App hostAdapter={{ initialize: async () => ({ mode: 'demo' }) }} />)
  const user = userEvent.setup()
  const startChat = await screen.findByRole('button', { name: 'Начать чат с МедВедом' })
  await waitFor(() => expect(startChat).toBeEnabled())
  await user.click(screen.getByRole('button', { name: 'Начать опрос' }))
  await user.click(screen.getByRole('checkbox', { name: /Я понимаю/ }))
  await user.click(screen.getByRole('button', { name: 'Начать опрос' }))
  await user.click(screen.getByRole('radio', { name: 'Кожа' }))
  await user.click(screen.getByRole('button', { name: 'На главную' }))
  expect(screen.getByRole('button', { name: 'Начать чат с МедВедом' })).toBeDisabled()
  await user.click(screen.getByRole('button', { name: 'Продолжить опрос' }))
  expect(screen.getByRole('radio', { name: 'Кожа' })).toBeChecked()
  await user.click(screen.getByRole('button', { name: 'Продолжить' }))
  await user.type(screen.getByLabelText('Возраст в полных годах'), '30')
  await user.click(screen.getByRole('button', { name: 'Продолжить' }))
  await user.type(screen.getByLabelText('Как давно появились симптомы?'), '1 день')
  await user.click(screen.getByRole('button', { name: 'Продолжить' }))
  await user.click(screen.getByRole('button', { name: 'Ничего из перечисленного' }))
  await user.click(screen.getByRole('button', { name: 'Продолжить' }))
  await user.click(screen.getByRole('button', { name: 'Завершить опрос и посмотреть итог' }))
  expect(screen.getByRole('heading', { name: 'Результат опроса' })).toBeVisible()
  const chatButton = screen.getByRole('button', { name: 'Уточнить у МедВеда' })
  const chatHint = 'Чтобы уточнить результат у МедВеда, завершите опрос.'
  expect(chatButton).toBeVisible()
  expect(chatButton).not.toHaveAttribute('aria-disabled')
  expect(screen.queryByText(chatHint)).not.toBeInTheDocument()
  expect(open).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: 'Завершить опрос' })).not.toBeInTheDocument()
  expect(screen.queryByText(chatHint)).not.toBeInTheDocument()
  await user.click(chatButton)
  await screen.findByRole('heading', { name: 'Чат с МедВедом' })
  await screen.findByText('Готов обсудить ваш результат.')
  expect(open).toHaveBeenCalledWith(current!.id, expect.any(AbortSignal))
  expect(screen.getByText('Результат вашего опроса')).toBeVisible()
})

test('history opens with an active survey, and changing MAX identity clears the old chat', async () => {
  const base = createMockClient('unknown')
  const activeSurvey = await base.create()
  const id = crypto.randomUUID()
  const date = new Date().toISOString()
  const saved: ChatSummary = { id, kind: 'chat', title: 'Боль в груди', created_at: date,
    last_activity_at: date, expires_at: date, emergency: true }
  const open = vi.fn()
  const list = vi.fn<MedvedClient['chat']['list']>()
    .mockRejectedValueOnce(new api.ApiError(503))
    .mockResolvedValueOnce({ items: [], next_cursor: null })
    .mockResolvedValueOnce({ items: [], next_cursor: 'next-page' })
    .mockResolvedValueOnce({ items: [saved], next_cursor: null })
    .mockResolvedValue({ items: [], next_cursor: null })
  const get = vi.fn(async (): Promise<Conversation> => ({
    id, questionnaire_id: null, result: null, emergency: true, pending: false, retryable: false,
    messages: [{ id: crypto.randomUUID(), role: 'assistant', text: 'Синтетическая переписка владельца', created_at: date, emergency: true }],
  }))
  vi.spyOn(api, 'createApiClient').mockReturnValue({
    ...base, clinics: { geocode: vi.fn(), reverseGeocode: vi.fn(), search: vi.fn() }, chat: { list, open, get, send: vi.fn(), delete: vi.fn(), availability: async () => ({ active_survey: activeSurvey }) },
  })
  const first = { kind: 'host' as const, initialize: async () => ({ mode: 'max' as const }) }
  const second = { ...first }
  const { rerender } = render(<App hostAdapter={first} />)
  const user = userEvent.setup()
  await screen.findByRole('button', { name: 'Продолжить опрос' })
  expect(screen.getByRole('button', { name: 'Начать чат с МедВедом' })).toBeDisabled()
  await user.click(screen.getByRole('button', { name: 'История чатов' }))
  await user.click(await screen.findByRole('button', { name: 'Повторить загрузку' }))
  await user.click(screen.getByRole('button', { name: 'Чаты' }))
  expect(screen.getByRole('button', { name: 'Чаты' })).toHaveAttribute('aria-pressed', 'true')
  await user.click(await screen.findByRole('button', { name: 'Показать ещё' }))
  expect(list).toHaveBeenLastCalledWith({ kind: 'chat', cursor: 'next-page' }, expect.any(AbortSignal))
  expect(await screen.findByRole('heading', { name: 'Боль в груди' })).toBeVisible()
  expect(screen.getByText(/^Чат с МедВедом ·/)).toBeVisible()
  await user.click(screen.getByRole('button', { name: /^Открыть: Боль в груди, Чат с МедВедом/ }))
  expect(await screen.findByText('Синтетическая переписка владельца')).toBeVisible()
  expect(screen.queryByLabelText('Ваше сообщение')).toBeNull()
  expect(screen.getByRole('link', { name: 'Позвонить 112' })).toHaveAttribute('href', 'tel:112')
  expect(open).not.toHaveBeenCalled()
  expect(get).toHaveBeenCalledWith(id, expect.any(AbortSignal))
  rerender(<App hostAdapter={second} />)
  await user.click(await screen.findByRole('button', { name: 'История чатов' }))
  expect(await screen.findByText('Сохранённых чатов и результатов пока нет.')).toBeVisible()
  expect(screen.queryByText('Синтетическая переписка владельца')).toBeNull()
})

test('history opens a completed result without creating its chat', async () => {
  const base = createMockClient('unknown')
  const survey = await base.create()
  const result = { ...await base.triage(survey.id), rationale: 'Сохранённое обоснование результата' }
  const date = new Date().toISOString()
  const saved: ChatSummary = { id: survey.id, kind: 'questionnaire_result', title: 'Боль в колене',
    created_at: date, last_activity_at: date, expires_at: survey.expires_at, emergency: false }
  const get = vi.fn(async (): Promise<Survey> => ({ ...survey, status: 'COMPLETED', state: 'COMPLETED', result }))
  const open = vi.fn()
  const getChat = vi.fn()
  vi.spyOn(api, 'createApiClient').mockReturnValue({
    ...base, get, clinics: { geocode: vi.fn(), reverseGeocode: vi.fn(), search: vi.fn() },
    chat: { list: async () => ({ items: [saved], next_cursor: null }), open, get: getChat, send: vi.fn(),
      delete: vi.fn(), availability: async () => ({ active_survey: null }) },
  })
  render(<App hostAdapter={{ initialize: async () => ({ mode: 'demo' }) }} />)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'История чатов' }))
  expect(await screen.findByRole('heading', { name: 'Боль в колене' })).toBeVisible()
  expect(screen.getByText(/^Результат опроса ·/)).toBeVisible()
  await user.click(screen.getByRole('button', { name: /^Открыть: Боль в колене, Результат опроса/ }))
  expect(await screen.findByText(result.rationale)).toBeVisible()
  expect(get).toHaveBeenCalledWith(survey.id, expect.any(AbortSignal))
  expect(open).not.toHaveBeenCalled()
  expect(getChat).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'К истории' }))
  expect(await screen.findByRole('heading', { name: 'История чатов' })).toBeVisible()
})
