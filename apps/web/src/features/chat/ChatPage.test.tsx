import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { ApiError } from '../../api/client'
import type { ChatClient, ChatSummary, Conversation } from '../../api/chat'
import { ChatPage } from './ChatPage'

function fixture() {
  let chat: Conversation = {
    id: crypto.randomUUID(), questionnaire_id: null, result: null, emergency: false, pending: false, retryable: false,
    messages: [{ id: crypto.randomUUID(), role: 'assistant', text: 'Здравствуйте! Что вы хотите уточнить?', created_at: new Date().toISOString(), emergency: false }],
  }
  const send = vi.fn<ChatClient['send']>(async (_id, body) => {
    chat = { ...chat, messages: [...chat.messages,
      { id: crypto.randomUUID(), role: 'user', text: body.text, client_message_id: body.client_message_id, created_at: new Date().toISOString(), emergency: false },
      { id: crypto.randomUUID(), role: 'assistant', text: 'Подготовьте вопросы для врача.', created_at: new Date().toISOString(), emergency: false },
    ] }
    return structuredClone(chat)
  })
  const client: ChatClient = {
    list: vi.fn(async () => ({ items: [], next_cursor: null })),
    availability: vi.fn(async () => ({ active_survey: null })),
    open: vi.fn(async () => structuredClone(chat)),
    get: vi.fn(async () => structuredClone(chat)),
    send, delete: vi.fn(async () => {}),
  }
  return { client, send }
}
function mount(client: ChatClient, blocked = false) {
  const onSurvey = vi.fn()
  render(<ChatPage client={client} active blocked={blocked} onHome={vi.fn()} onSurvey={onSurvey} onNew={vi.fn()} />)
  return { user: userEvent.setup(), onSurvey }
}

test('chat sends a real client request and renders a reply as text', async () => {
  const { client, send } = fixture()
  const { user } = mount(client)
  await screen.findByText('Здравствуйте! Что вы хотите уточнить?')
  await user.type(screen.getByLabelText('Ваше сообщение'), 'Что взять на приём?')
  await user.click(screen.getByRole('button', { name: 'Отправить' }))
  await screen.findByText('Подготовьте вопросы для врача.')
  expect(send).toHaveBeenCalledOnce()
  expect(send.mock.calls[0][1]).toMatchObject({ text: 'Что взять на приём?', client_message_id: expect.any(String) })
  expect(screen.getByLabelText('Ваше сообщение')).toHaveValue('')
})

test('lost request preserves the text and reuses the same message ID on retry', async () => {
  const { client, send } = fixture()
  send.mockRejectedValueOnce(new ApiError(503))
  const { user } = mount(client)
  await screen.findByText('Здравствуйте! Что вы хотите уточнить?')
  await user.type(screen.getByLabelText('Ваше сообщение'), 'Уточню вопрос')
  await user.click(screen.getByRole('button', { name: 'Отправить' }))
  await screen.findByRole('alert')
  expect(screen.getByLabelText('Ваше сообщение')).toHaveValue('Уточню вопрос')
  await user.click(screen.getByRole('button', { name: 'Повторить отправку' }))
  await screen.findByText('Подготовьте вопросы для врача.')
  expect(send.mock.calls[0][1]).toEqual(send.mock.calls[1][1])
})

test('active survey disables chat composition and offers a return to the survey', async () => {
  const { client, send } = fixture()
  const { user, onSurvey } = mount(client, true)
  await screen.findByText('Здравствуйте! Что вы хотите уточнить?')
  expect(screen.getByLabelText('Ваше сообщение')).toBeDisabled()
  await user.click(screen.getByRole('button', { name: 'Продолжить опрос' }))
  expect(onSurvey).toHaveBeenCalledOnce()
  expect(send).not.toHaveBeenCalled()
})

test('emergency response replaces the composer with accessible phone links', async () => {
  const { client, send } = fixture()
  send.mockImplementationOnce(async (_id, body) => ({
    id: (await client.open()).id, questionnaire_id: null, result: null, emergency: true, pending: false, retryable: false,
    messages: [{ id: crypto.randomUUID(), role: 'assistant', text: body.text, created_at: new Date().toISOString(), emergency: true }],
  }))
  const { user } = mount(client)
  await screen.findByText('Здравствуйте! Что вы хотите уточнить?')
  await user.type(screen.getByLabelText('Ваше сообщение'), 'Срочный вопрос')
  await user.click(screen.getByRole('button', { name: 'Отправить' }))
  await waitFor(() => expect(screen.queryByLabelText('Ваше сообщение')).not.toBeInTheDocument())
  expect(screen.getByRole('link', { name: 'Позвонить 103' })).toHaveAttribute('href', 'tel:103')
  expect(screen.getByRole('link', { name: 'Позвонить 112' })).toHaveAttribute('href', 'tel:112')
})

test('saved pending message is rendered as text and retried using its original ID', async () => {
  const { client, send } = fixture()
  const chat = await client.get('saved')
  const html = '<img src="synthetic.png" alt="synthetic-history-image">'
  const now = new Date().toISOString()
  const message = { id: crypto.randomUUID(), role: 'user' as const, text: html, created_at: now,
    emergency: false, client_message_id: crypto.randomUUID() }
  vi.mocked(client.get).mockResolvedValue({ ...chat, messages: [...chat.messages, message], pending: true, retryable: true })
  vi.mocked(client.open).mockClear()
  const saved: ChatSummary = { id: chat.id, kind: 'chat', title: 'Чат от 21 ноября', created_at: now,
    last_activity_at: now, expires_at: now, emergency: false }
  render(<ChatPage client={client} saved={saved} active blocked={false} onHome={vi.fn()} onSurvey={vi.fn()} onNew={vi.fn()} />)
  const user = userEvent.setup()
  expect(await within(await screen.findByRole('log')).findByText(html)).toBeVisible()
  expect(screen.queryByAltText('synthetic-history-image')).toBeNull()
  expect(client.open).not.toHaveBeenCalled()
  expect(client.get).toHaveBeenLastCalledWith(saved.id, expect.any(AbortSignal))
  await user.click(screen.getByRole('button', { name: 'Повторить отправку' }))
  expect(send).toHaveBeenCalledWith(saved.id, { text: html, client_message_id: message.client_message_id })
})
