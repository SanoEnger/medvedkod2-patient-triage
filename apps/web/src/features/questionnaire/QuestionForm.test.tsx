import { useState } from 'react'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { HISTORY_FIELDS } from '../../api/contracts'
import { QuestionForm } from './QuestionForm'
import { emptyDrafts, historyLabels } from './fields'

test('every history field has an independent No option and restores its draft', async () => {
  const answer = vi.fn()
  function Form() {
    const [drafts, setDrafts] = useState(() => {
      const initial = emptyDrafts()
      initial.medical_history.chronic_conditions = 'Запись о заболевании'
      initial.medical_history.medications = 'Запись о препарате'
      return initial
    })
    return <QuestionForm question="medical_history" drafts={drafts} onChange={setDrafts} onAnswer={answer} disabled={false} />
  }
  render(<Form />)
  const user = userEvent.setup()
  expect(screen.getAllByRole('checkbox')).toHaveLength(HISTORY_FIELDS.length)
  for (const key of HISTORY_FIELDS) {
    const label = historyLabels[key]
    const none = screen.getByRole('checkbox', { name: 'Нет: ' + label })
    expect(none).not.toBeChecked()
    await user.click(none)
    expect(screen.getByRole('group', { name: label })).toBeVisible()
    expect(screen.queryByRole('textbox', { name: label })).not.toBeInTheDocument()
    if (key === 'chronic_conditions') expect(screen.getByLabelText('Принимаемые лекарства')).toHaveValue('Запись о препарате')
  }
  await user.click(screen.getByRole('button', { name: 'Сохранить ответы и посмотреть итог' }))
  expect(answer).toHaveBeenLastCalledWith({
    question_key: 'medical_history',
    value: Object.fromEntries(HISTORY_FIELDS.map((key) => [key, ['Нет']])),
  })
  await user.click(screen.getByRole('checkbox', { name: 'Нет: Принимаемые лекарства' }))
  expect(screen.getByLabelText('Принимаемые лекарства')).toHaveValue('Запись о препарате')
  expect(screen.getByRole('checkbox', { name: 'Нет: Хронические заболевания' })).toBeChecked()
  await user.click(screen.getByRole('button', { name: 'Сохранить ответы и посмотреть итог' }))
  expect(answer).toHaveBeenLastCalledWith(expect.objectContaining({
    value: expect.objectContaining({ medications: ['Запись о препарате'], chronic_conditions: ['Нет'] }),
  }))
})

test('history No options are disabled while an answer is pending', () => {
  render(<QuestionForm question="medical_history" drafts={emptyDrafts()} onChange={vi.fn()} onAnswer={vi.fn()} disabled />)
  for (const option of screen.getAllByRole('checkbox')) expect(option).toBeDisabled()
})

test('patient context asks temperature first and shows maternity questions only for women', async () => {
  const answer = vi.fn()
  function Form() {
    const [drafts, setDrafts] = useState(emptyDrafts)
    return <QuestionForm question="patient_context" drafts={drafts} onChange={setDrafts} onAnswer={answer} disabled={false} />
  }
  render(<Form />)
  const user = userEvent.setup()
  expect(screen.getAllByRole('spinbutton')[0]).toBe(screen.getByLabelText('Температура тела, °C'))
  expect(screen.queryByRole('group', { name: 'Беременность и лактация' })).not.toBeInTheDocument()
  await user.type(screen.getByLabelText('Температура тела, °C'), '36.6')
  await user.type(screen.getByLabelText('Возраст в полных годах'), '32')
  await user.type(screen.getByLabelText('Рост, см'), '168.5')
  await user.type(screen.getByLabelText('Вес, кг'), '60.5')
  await user.selectOptions(screen.getByLabelText('Пол'), 'female')
  await user.click(within(screen.getByRole('group', { name: 'Есть ли беременность?' })).getByRole('radio', { name: 'Да' }))
  await user.click(within(screen.getByRole('group', { name: 'Есть ли грудное вскармливание?' })).getByRole('radio', { name: 'Нет' }))
  await user.click(screen.getByRole('button', { name: 'Продолжить' }))
  expect(answer).toHaveBeenLastCalledWith({
    question_key: 'patient_context',
    value: { age_years: 32, temperature_c: 36.6, sex: 'female', height_cm: 168.5, weight_kg: 60.5, pregnancy: true, lactation: false },
  })
  await user.selectOptions(screen.getByLabelText('Пол'), 'male')
  expect(screen.queryByRole('group', { name: 'Беременность и лактация' })).not.toBeInTheDocument()
  expect(screen.getByLabelText('Рост, см')).toHaveValue(168.5)
  await user.click(screen.getByRole('button', { name: 'Продолжить' }))
  expect(answer).toHaveBeenLastCalledWith(expect.objectContaining({
    value: expect.objectContaining({ sex: 'male', pregnancy: null, lactation: null }),
  }))
  await user.selectOptions(screen.getByLabelText('Пол'), 'female')
  expect(within(screen.getByRole('group', { name: 'Есть ли беременность?' })).getByRole('radio', { name: 'Не знаю' })).toBeChecked()
  expect(within(screen.getByRole('group', { name: 'Есть ли грудное вскармливание?' })).getByRole('radio', { name: 'Не знаю' })).toBeChecked()
})
