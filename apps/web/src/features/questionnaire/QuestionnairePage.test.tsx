import { act, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, test, vi } from 'vitest'
import { AppShell } from '../../app/AppShell'
import { ApiError } from '../../api/client'
import { createMockClient, demoResult } from '../../api/mock'
import type { Survey, SurveyClient } from '../../api/contracts'
import { QuestionnairePage, ResultCard } from './QuestionnairePage'
import { useQuestionnaire } from './useQuestionnaire'

function mount(client: SurveyClient = createMockClient()) {
  const home = vi.fn()
  render(<AppShell mode="demo"><QuestionnairePage client={client} onHome={home} /></AppShell>)
  return { user: userEvent.setup(), home }
}
async function consent(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('checkbox', { name: /Я понимаю/ }))
  await user.click(screen.getByRole('button', { name: 'Начать опрос' }))
  await screen.findByRole('heading', { name: 'Что вас беспокоит?' })
}
async function primary(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('radio', { name: 'Кожа' }))
  await user.click(screen.getByRole('button', { name: 'Продолжить' }))
}
async function complete(user: ReturnType<typeof userEvent.setup>) {
  await consent(user)
  await primary(user)
  await user.type(screen.getByLabelText('Возраст в полных годах'), '30')
  await user.click(screen.getByRole('button', { name: 'Продолжить' }))
  await user.type(screen.getByLabelText('Как давно появились симптомы?'), '1 день')
  await user.type(screen.getByLabelText('Выраженность симптомов от 0 до 10'), '2')
  await user.click(screen.getByRole('button', { name: 'Продолжить' }))
  await user.click(screen.getByRole('button', { name: 'Ничего из перечисленного' }))
  await user.click(screen.getByRole('button', { name: 'Продолжить' }))
  await user.type(screen.getByLabelText('Госпитализации за последний год'), 'Синтетический пример')
  await user.click(screen.getByRole('button', { name: 'Завершить опрос и посмотреть итог' }))
  await screen.findByRole('heading', { name: 'Результат опроса' })
}

describe('questionnaire UI', () => {
  test('renders model analysis as text without inventing a specialist', () => {
    render(<ResultCard result={{ ...demoResult('unknown'), specialty: null, analysis_source: 'groq', analysis: '<img src=x> Сведения анкеты.' }} />)
    expect(screen.getByRole('heading', { name: 'Разбор анкеты МедВедом' })).toBeVisible()
    expect(screen.getByText('<img src=x> Сведения анкеты.')).toBeVisible()
    expect(screen.getByText('Не определён')).toBeVisible()
    expect(document.querySelector('img')).toBeNull()
  })
  test('shows model failure separately from the safety result', () => {
    render(<ResultCard result={{ ...demoResult('unknown'), analysis_source: 'unavailable' }} />)
    expect(screen.getByRole('status')).toHaveTextContent('Разбор анкеты моделью сейчас недоступен')
    expect(screen.getByText(demoResult('unknown').rationale)).toBeVisible()
  })
  test('does not create a session before consent', async () => {
    const client = createMockClient()
    const create = vi.spyOn(client, 'create')
    const { user } = mount(client)
    expect(screen.getByRole('button', { name: 'Начать опрос' })).toBeDisabled()
    expect(create).not.toHaveBeenCalled()
    await consent(user)
    expect(create).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '0')
  })

  test('complete flow, result, finish and new consent', async () => {
    const client = createMockClient()
    const send = vi.spyOn(client, 'answer')
    const { user } = mount(client)
    await complete(user)
    expect(screen.getByText('Дерматолог')).toBeVisible()
    expect(send).toHaveBeenCalledTimes(5)
    expect(send.mock.calls[4][1].value).toMatchObject({ hospitalizations_last_year: ['Синтетический пример'] })
    expect(screen.queryByRole('button', { name: 'Завершить опрос' })).not.toBeInTheDocument()
    await screen.findByText(/Ответы сохранены/)
    await user.click(screen.getByRole('button', { name: 'Начать новый опрос' }))
    expect(screen.getByRole('checkbox', { name: /Я понимаю/ })).not.toBeChecked()
    expect(screen.queryByText('Дерматолог')).not.toBeInTheDocument()
    expect(localStorage.length + sessionStorage.length).toBe(0)
  })

  test('back and editing keep drafts but discard the prior result', async () => {
    const { user } = mount()
    await complete(user)
    await user.click(screen.getByRole('button', { name: 'Уточнить ответы' }))
    await user.click(screen.getByRole('button', { name: '1. Что вас беспокоит?' }))
    await screen.findByRole('heading', { name: 'Что вас беспокоит?' })
    expect(screen.getByRole('radio', { name: 'Кожа' })).toBeChecked()
    expect(screen.queryByText('Дерматолог')).not.toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: 'Другое' }))
    await user.click(screen.getByRole('button', { name: 'Продолжить' }))
    expect(screen.getByLabelText('Возраст в полных годах')).toHaveValue(30)
    await user.click(screen.getByRole('button', { name: 'Назад' }))
    expect(screen.getByRole('radio', { name: 'Другое' })).toBeChecked()
  })

  test('uncertain answer retry uses the same UUID and immutable body', async () => {
    const client = createMockClient()
    const accept = client.answer
    let first = true
    const send = vi.spyOn(client, 'answer').mockImplementation(async (...args) => {
      const value = await accept(...args)
      if (first) { first = false; throw new ApiError(503) }
      return value
    })
    const { user } = mount(client)
    await consent(user)
    await primary(user)
    await screen.findByRole('alert')
    expect(screen.getByRole('radio', { name: 'Кожа' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Повторить действие' }))
    await screen.findByRole('heading', { name: 'Важные сведения о самочувствии' })
    expect(send.mock.calls[0][1]).toEqual(send.mock.calls[1][1])
    expect(screen.getByRole('progressbar')).toHaveAttribute('value', '20')
  })

  test('emergency takes priority and stops ordinary navigation', async () => {
    const { user } = mount(createMockClient('emergency'))
    await consent(user)
    await primary(user)
    await screen.findByRole('heading', { name: 'Вызовите скорую помощь' })
    expect(screen.getByRole('link', { name: 'Позвонить 103' })).toHaveAttribute('href', 'tel:103')
    expect(screen.getByRole('link', { name: 'Позвонить 112' })).toHaveAttribute('href', 'tel:112')
    expect(screen.queryByRole('button', { name: 'Назад' })).not.toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Версия для слабовидящих' }))
    expect(screen.getByRole('heading', { name: 'Вызовите скорую помощь' })).toBeVisible()
  })

  test('unknown result requests clarification and never suggests self-care', async () => {
    const { user } = mount(createMockClient('unknown'))
    await complete(user)
    expect(screen.getByText('Нужно уточнение', { exact: true })).toBeVisible()
    const card = screen.getByRole('heading', { name: 'Куда обратиться' }).closest('section')!
    expect(within(card).getByText('Не определён', { exact: true })).toBeVisible()
    expect(card.textContent?.match(/103\/112/g)).toHaveLength(1)
    expect(within(card).queryByText(/Уточните ответы/)).not.toBeInTheDocument()
    expect(screen.queryByText('Самопомощь', { exact: true })).not.toBeInTheDocument()
  })

  test('delete needs confirmation; failure preserves the session until success', async () => {
    const client = createMockClient()
    const remove = vi.spyOn(client, 'delete').mockRejectedValueOnce(new ApiError(503))
    const { user } = mount(client)
    await consent(user)
    await primary(user)
    await user.click(screen.getByRole('button', { name: 'Удалить обращение' }))
    expect(remove).not.toHaveBeenCalled()
    let modal = within(screen.getByRole('dialog'))
    await user.click(modal.getByRole('button', { name: 'Отмена' }))
    expect(remove).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Удалить обращение' }))
    modal = within(screen.getByRole('dialog'))
    await user.click(modal.getByRole('button', { name: 'Удалить' }))
    expect(await modal.findByRole('alert')).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Важные сведения о самочувствии' })).toBeInTheDocument()
    await user.click(modal.getByRole('button', { name: 'Удалить' }))
    await screen.findByRole('heading', { name: 'Несколько важных слов' })
    expect(screen.getByRole('checkbox', { name: /Я понимаю/ })).not.toBeChecked()
    expect(remove).toHaveBeenCalledTimes(2)
  })

  test('a positive red flag is sent immediately to the server', async () => {
    const client = createMockClient()
    const original = client.answer
    const send = vi.spyOn(client, 'answer').mockImplementation(async (...args) => {
      const response = await original(...args)
      return args[1].question_key === 'red_flags'
        ? { ...response, emergency: true, status: 'EMERGENCY_STOP', state: 'EMERGENCY_STOP', current_question: null, next_question: null, result: demoResult('emergency') }
        : response
    })
    const { user } = mount(client)
    await consent(user); await primary(user)
    await user.click(screen.getByRole('button', { name: 'Продолжить' }))
    await user.click(screen.getByRole('button', { name: 'Продолжить' }))
    await user.click(within(screen.getByRole('group', { name: 'Боль в груди' })).getByRole('radio', { name: 'Да' }))
    await screen.findByRole('heading', { name: 'Вызовите скорую помощь' })
    expect(send.mock.calls[3][1].value).toMatchObject({ chest_pain: true, bleeding: null })
  })

  test.each(['primary_complaint', 'symptom_details', 'medical_history'] as const)(
    'a model emergency from %s immediately opens the stop screen without final analysis', async (target) => {
      const client = createMockClient()
      const original = client.answer
      const triage = vi.spyOn(client, 'triage')
      vi.spyOn(client, 'answer').mockImplementation(async (...args) => {
        const response = await original(...args)
        return args[1].question_key === target
          ? { ...response, emergency: true, status: 'EMERGENCY_STOP', state: 'EMERGENCY_STOP', current_question: null, next_question: null, result: demoResult('emergency') }
          : response
      })
      const { user } = mount(client)
      await consent(user)
      await user.type(screen.getByLabelText('Что беспокоит — своими словами'), 'Сжимает за грудиной')
      await primary(user)
      if (target !== 'primary_complaint') {
        await user.click(screen.getByRole('button', { name: 'Продолжить' }))
        await user.type(screen.getByLabelText('Как давно появились симптомы?'), 'Сейчас')
        await user.click(screen.getByRole('button', { name: 'Продолжить' }))
      }
      if (target === 'medical_history') {
        await user.click(screen.getByRole('button', { name: 'Ничего из перечисленного' }))
        await user.click(screen.getByRole('button', { name: 'Продолжить' }))
        await user.type(screen.getByLabelText('Госпитализации за последний год'), 'Сжимает за грудиной сейчас')
        await user.click(screen.getByRole('button', { name: 'Завершить опрос и посмотреть итог' }))
      }
      await screen.findByRole('heading', { name: 'Вызовите скорую помощь' })
      expect(screen.getByRole('link', { name: 'Позвонить 103' })).toBeVisible()
      expect(screen.queryByRole('button', { name: 'Продолжить' })).not.toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: 'Результат опроса' })).not.toBeInTheDocument()
      expect(triage).not.toHaveBeenCalled()
    },
  )

  test('readability preserves entered values and sends no request', async () => {
    const client = createMockClient()
    const send = vi.spyOn(client, 'answer')
    const { user } = mount(client)
    await consent(user)
    await user.type(screen.getByLabelText('Что беспокоит — своими словами'), 'Synthetic retained draft')
    await user.click(screen.getByRole('radio', { name: 'Кожа' }))
    await user.click(screen.getByRole('button', { name: 'Версия для слабовидящих' }))
    expect(screen.getByLabelText('Что беспокоит — своими словами')).toHaveValue('Synthetic retained draft')
    expect(screen.getByRole('radio', { name: 'Кожа' })).toBeChecked()
    expect(send).not.toHaveBeenCalled()
  })

  test('server text is displayed as text, not HTML', async () => {
    const client = createMockClient()
    const get = client.triage
    vi.spyOn(client, 'triage').mockImplementation(async (...args) => {
      const value = await get(...args)
      return { ...value, rationale: '<img src=x onerror=alert(1)>' }
    })
    const { user } = mount(client)
    await complete(user)
    expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeVisible()
    expect(document.querySelector('.result-card img')).toBeNull()
  })

  test('native validation blocks invalid numeric input', async () => {
    const { user } = mount()
    await consent(user); await primary(user)
    fireEvent.change(screen.getByLabelText('Возраст в полных годах'), { target: { value: '121' } })
    await user.click(screen.getByRole('button', { name: 'Продолжить' }))
    expect(screen.getByLabelText('Возраст в полных годах')).toBeInvalid()
  })
})

test('last answer waits for the complete model result and retries without resubmitting a new answer', async () => {
  const client = createMockClient()
  const send = vi.spyOn(client, 'answer')
  const finalize = client.triage
  vi.spyOn(client, 'triage').mockRejectedValueOnce(new ApiError(503)).mockImplementation(finalize)
  const { result } = renderHook(() => useQuestionnaire(client))
  await act(async () => { await result.current.start() })
  const steps = [
    { question_key: 'primary_complaint', value: { category: 'skin', text: '' } },
    { question_key: 'patient_context', value: { age_years: 30 } },
    { question_key: 'symptom_details', value: { duration: '1 день', severity_0_10: 2 } },
    { question_key: 'red_flags', value: {} },
  ] as Parameters<typeof result.current.answer>[0][]
  for (const step of steps) await act(async () => { await result.current.answer(step) })
  await act(async () => { await result.current.answer({ question_key: 'medical_history', value: {} as never }) })
  // A failed finalization must not expose the preliminary result as a finished card.
  expect(result.current.survey?.current_question).toBe('medical_history')
  expect(result.current.survey?.result).toBeNull()
  await act(async () => { await result.current.retry() })
  expect(result.current.survey?.status).toBe('COMPLETED')
  expect(result.current.survey?.result?.specialty).toBe('Дерматолог')
  expect(send.mock.calls[4][1]).toEqual(send.mock.calls[5][1])
})

test('a normal late response cannot hide an emergency in the same session', async () => {
  const client = createMockClient('emergency')
  const { result } = renderHook(() => useQuestionnaire(client))
  await act(async () => { await result.current.start() })
  const initial = structuredClone(result.current.survey!)
  await act(async () => { await result.current.answer({ question_key: 'primary_complaint', value: { category: 'skin', text: '' } }) })
  vi.spyOn(client, 'get').mockResolvedValue(initial)
  await act(async () => { await result.current.refresh() })
  expect(result.current.emergency).toBe(true)
  expect(result.current.survey?.status).toBe('EMERGENCY_STOP')
  await act(async () => { await result.current.back(0) })
  expect(result.current.emergency).toBe(true)
})

test('late completion of an abandoned request cannot overwrite a new session', async () => {
  const client = createMockClient()
  let resolve!: (survey: Survey) => void
  vi.spyOn(client, 'answer').mockImplementation(() => new Promise((done) => { resolve = done }))
  const { result } = renderHook(() => useQuestionnaire(client))
  await act(async () => { await result.current.start() })
  const old = result.current.survey!
  let pending!: Promise<boolean>
  act(() => { pending = result.current.answer({ question_key: 'primary_complaint', value: { category: 'skin', text: '' } }) })
  act(() => { result.current.reset() })
  await act(async () => { await result.current.start() })
  const newer = result.current.survey!.id
  await act(async () => { resolve({ ...old, emergency: true, status: 'EMERGENCY_STOP', state: 'EMERGENCY_STOP' }); await pending })
  expect(result.current.survey?.id).toBe(newer)
  expect(result.current.emergency).toBe(false)
  await waitFor(() => expect(result.current.busy).toBe(false))
})

test('a missing API at creation is not presented as an expired existing session', async () => {
  const client = createMockClient()
  vi.spyOn(client, 'create').mockRejectedValue(new ApiError(404))
  const { user } = mount(client)
  await user.click(screen.getByRole('checkbox', { name: /Я понимаю/ }))
  await user.click(screen.getByRole('button', { name: 'Начать опрос' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Не удалось подключиться к опросу')
  expect(screen.queryByRole('heading', { name: 'Обращение недоступно' })).not.toBeInTheDocument()
})
