import { afterEach, expect, test, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import * as api from '../api/client'
import type { MedvedClient } from '../api/client'
import type { Conversation } from '../api/chat'
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
    create: async () => { current = await base.create(); return current },
    answer: async (...args) => { current = await base.answer(...args); return current },
    back: async (...args) => { current = await base.back(...args); return current },
    triage: async (id) => { const result = await base.triage(id); current = await base.get(id); return result },
    chat: {
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
  await user.click(screen.getByRole('button', { name: 'Сохранить ответы и посмотреть итог' }))
  expect(screen.getByRole('heading', { name: 'Результат опроса' })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Уточнить у МедВеда' }))
  await screen.findByRole('heading', { name: 'Чат с МедВедом' })
  await screen.findByText('Готов обсудить ваш результат.')
  expect(open).toHaveBeenCalledWith(current!.id, expect.any(AbortSignal))
  expect(screen.getByText('Результат вашего опроса')).toBeVisible()
})
