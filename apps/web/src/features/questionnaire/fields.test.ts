import { expect, test } from 'vitest'
import { answerFromDraft, emptyDrafts } from './fields'

test('unknown context and red flags remain null, not negative answers', () => {
  expect(answerFromDraft('patient_context', emptyDrafts()).value).toEqual({
    age_years: null, temperature_c: null, sex: null, height_cm: null, weight_kg: null, pregnancy: null, lactation: null,
  })
  const flags = answerFromDraft('red_flags', emptyDrafts()).value
  expect(Object.values(flags).every((value) => value === null)).toBe(true)
})

test('anamnesis includes separate operations, hospitalization and lactation', () => {
  const drafts = emptyDrafts()
  drafts.patient_context.sex = 'female'
  drafts.patient_context.lactation = 'yes'
  drafts.medical_history.hospitalizations_last_year = 'Synthetic admission A;\nSynthetic admission B'
  expect(answerFromDraft('patient_context', drafts).value).toMatchObject({ lactation: true })
  expect(answerFromDraft('medical_history', drafts).value).toMatchObject({
    hospitalizations_last_year: ['Synthetic admission A', 'Synthetic admission B'], operations_last_year: [],
  })
})

test('frontend validates numeric ranges and bounded history entries', () => {
  const drafts = emptyDrafts()
  drafts.patient_context.age_years = '121'
  expect(() => answerFromDraft('patient_context', drafts)).toThrow()
  drafts.medical_history.medications = Array(11).fill('synthetic').join(';')
  expect(() => answerFromDraft('medical_history', drafts)).toThrow()
  drafts.medical_history.medications = 'a'.repeat(121)
  expect(() => answerFromDraft('medical_history', drafts)).toThrow()
  expect(() => answerFromDraft('primary_complaint', emptyDrafts())).toThrow()
})

test('new patient fields serialize with units and hidden maternity answers stay unknown', () => {
  const drafts = emptyDrafts()
  Object.assign(drafts.patient_context, { sex: 'female', height_cm: '172,5', weight_kg: '64,2', pregnancy: 'yes', lactation: 'no' })
  expect(answerFromDraft('patient_context', drafts).value).toMatchObject({
    sex: 'female', height_cm: 172.5, weight_kg: 64.2, pregnancy: true, lactation: false,
  })
  drafts.patient_context.sex = 'male'
  expect(answerFromDraft('patient_context', drafts).value).toMatchObject({ pregnancy: null, lactation: null })
  drafts.patient_context.sex = ''
  expect(answerFromDraft('patient_context', drafts).value).toMatchObject({ sex: null, pregnancy: null, lactation: null })
})

test.each([['height_cm', '0'], ['height_cm', '301'], ['weight_kg', '0'], ['weight_kg', '1001']] as const)(
  'invalid %s is not sent (%s)', (field, value) => {
    const drafts = emptyDrafts()
    drafts.patient_context[field] = value
    expect(() => answerFromDraft('patient_context', drafts)).toThrow()
  },
)
