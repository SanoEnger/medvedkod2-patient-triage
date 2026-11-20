import { useId, useState } from 'react'
import type { FormEvent } from 'react'
import { Button, SelectField, TextAreaField, TextField } from '../../components/ui'
import { Icon } from '../../components/Icon'
import type { IconName } from '../../components/Icon'
import { HISTORY_FIELDS, RED_FLAGS } from '../../api/contracts'
import type { AnswerRequest, Category, QuestionKey, Sex } from '../../api/contracts'
import { answerFromDraft, categories, flagLabels, historyLabels } from './fields'
import type { Choice, Drafts } from './fields'

const categoryIcons: Record<Category, IconName> = {
  pain: 'pain', fever: 'temperature', breathing: 'breathing', digestive: 'stomach',
  skin: 'skin', neurology: 'clipboard', injury: 'injury', other: 'more',
}

function Choices({ label, value, onChange }: { label: string; value: Choice; onChange: (value: Choice) => void }) {
  const name = useId()
  return <fieldset className="choice-field">
    <legend>{label}</legend>
    <div className="choice-row">{([['yes', 'Да'], ['no', 'Нет'], ['unknown', 'Не знаю']] as const).map(([key, text]) =>
      <label className="choice-option" key={key}>
        <input type="radio" name={name} value={key} checked={value === key} onChange={() => onChange(key)} />
        <span>{text}</span><Icon name="check" className="choice-check" />
      </label>)}</div>
  </fieldset>
}

function HistoryField({ label, value, none, onNoneChange, onChange }: {
  label: string; value: string; none: boolean
  onNoneChange: (none: boolean) => void; onChange: (value: string) => void
}) {
  const id = useId()
  return <fieldset className="field history-field">
    <legend id={id + '-label'}>{label}</legend>
    <label className="history-none">
      <input type="checkbox" aria-label={'Нет: ' + label} checked={none} onChange={(event) => onNoneChange(event.target.checked)} />
      <span>Нет</span>
    </label>
    {!none && <>
      <textarea id={id} aria-labelledby={id + '-label'} aria-describedby={id + '-hint'} rows={3} maxLength={1300} value={value} onChange={(event) => onChange(event.target.value)} />
      <p id={id + '-hint'} className="field-hint">До 10 записей: с новой строки или через точку с запятой. Каждая запись — до 120 символов.</p>
    </>}
  </fieldset>
}

export function QuestionForm({ question, drafts, onChange, onAnswer, disabled }: {
  question: QuestionKey; drafts: Drafts; onChange: (drafts: Drafts) => void
  onAnswer: (body: Omit<AnswerRequest, 'idempotency_key'>) => void; disabled: boolean
}) {
  const [error, setError] = useState('')
  function update<K extends QuestionKey>(key: K, value: Drafts[K]) {
    setError('')
    onChange({ ...drafts, [key]: value })
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    if (disabled) return
    try { const body = answerFromDraft(question, drafts); setError(''); onAnswer(body) }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Проверьте заполненные поля.') }
  }
  const primary = drafts.primary_complaint
  const patient = drafts.patient_context
  const details = drafts.symptom_details
  return <form className="question-form" onSubmit={submit}>
    <fieldset className="form-fields" disabled={disabled}>
      <legend className="visually-hidden">Ответ на текущий вопрос</legend>
      {question === 'primary_complaint' && <>
        <fieldset className="category-field">
          <legend>Основная жалоба</legend>
          <div className="category-grid">{categories.map(([key, label]) =>
            <label className="choice-option" key={key}>
              <input required type="radio" name="category" value={key} checked={primary.category === key} onChange={() => update('primary_complaint', { ...primary, category: key })} />
              <Icon name={categoryIcons[key]} /><span>{label}</span><Icon name="check" className="choice-check" />
            </label>)}</div>
        </fieldset>
        <TextAreaField label="Что беспокоит — своими словами" hint="Можно оставить пустым. До 1200 символов, без имени, телефона и адреса." maxLength={1200} rows={4} value={primary.text} onChange={(event) => update('primary_complaint', { ...primary, text: event.target.value })} />
      </>}
      {question === 'patient_context' && <>
        <TextField label="Температура тела, °C" type="number" inputMode="decimal" min={30} max={45} step={0.1} value={patient.temperature_c} onChange={(event) => update('patient_context', { ...patient, temperature_c: event.target.value })} hint="Если не измеряли, оставьте поле пустым." />
        <div className="field-grid">
          <TextField label="Возраст в полных годах" type="number" inputMode="numeric" min={0} max={120} step={1} value={patient.age_years} onChange={(event) => update('patient_context', { ...patient, age_years: event.target.value })} hint="Если возраст неизвестен, оставьте поле пустым." />
          <SelectField label="Пол" value={patient.sex} onChange={(event) => {
            const sex = event.target.value as Sex | ''
            update('patient_context', { ...patient, sex,
              ...(sex !== 'female' ? { pregnancy: 'unknown', lactation: 'unknown' } as const : {}) })
          }}>
            <option value="">Не указан</option>
            <option value="male">Мужской</option>
            <option value="female">Женский</option>
          </SelectField>
          <TextField label="Рост, см" type="number" inputMode="decimal" min={1} max={300} step={0.1} value={patient.height_cm} onChange={(event) => update('patient_context', { ...patient, height_cm: event.target.value })} hint="Если рост неизвестен, оставьте поле пустым." />
          <TextField label="Вес, кг" type="number" inputMode="decimal" min={0.1} max={1000} step={0.1} value={patient.weight_kg} onChange={(event) => update('patient_context', { ...patient, weight_kg: event.target.value })} hint="Если вес неизвестен, оставьте поле пустым." />
        </div>
        {patient.sex === 'female' && <div className="optional-fields" role="group" aria-label="Беременность и лактация">
          <Choices label="Есть ли беременность?" value={patient.pregnancy} onChange={(value) => update('patient_context', { ...patient, pregnancy: value })} />
          <Choices label="Есть ли грудное вскармливание?" value={patient.lactation} onChange={(value) => update('patient_context', { ...patient, lactation: value })} />
        </div>}
      </>}
      {question === 'symptom_details' && <>
        <TextField label="Где ощущаются симптомы?" maxLength={120} value={details.location} onChange={(event) => update('symptom_details', { ...details, location: event.target.value })} hint="Необязательно. До 120 символов." />
        <TextField label="Как давно появились симптомы?" maxLength={120} value={details.duration} onChange={(event) => update('symptom_details', { ...details, duration: event.target.value })} hint="Например, несколько часов. До 120 символов." />
        <TextField label="Выраженность симптомов от 0 до 10" type="number" inputMode="numeric" min={0} max={10} step={1} value={details.severity_0_10} onChange={(event) => update('symptom_details', { ...details, severity_0_10: event.target.value })} hint="0 — не ощущаются, 10 — максимально выражены. Если не знаете, оставьте пустым." />
        <TextAreaField label="Дополнительные сведения о симптомах" hint="Необязательно. До 1200 символов, без личных данных." maxLength={1200} rows={4} value={details.additional_text} onChange={(event) => update('symptom_details', { ...details, additional_text: event.target.value })} />
      </>}
      {question === 'red_flags' && <>
        <p className="question-note">При ответе «Да» сведения сразу отправятся на проверку серверу. Если есть непосредственная опасность, звоните 103/112.</p>
        <Button icon="check" variant="secondary" onClick={() => update('red_flags', Object.fromEntries(RED_FLAGS.map((key) => [key, 'no'])) as Drafts['red_flags'])}>Ничего из перечисленного</Button>
        <div className="flags-list">{RED_FLAGS.map((key) =>
          <Choices key={key} label={flagLabels[key]} value={drafts.red_flags[key]} onChange={(value) => {
            const next = { ...drafts, red_flags: { ...drafts.red_flags, [key]: value } }
            update('red_flags', next.red_flags)
            if (value === 'yes') onAnswer(answerFromDraft('red_flags', next))
          }} />)}</div>
      </>}
      {question === 'medical_history' && <>
        <p className="question-note">Заполните то, что известно. Поля можно оставить пустыми.</p>
        {HISTORY_FIELDS.map((key) => <HistoryField key={key} label={historyLabels[key]}
          value={drafts.medical_history[key]} none={drafts.history_none[key]}
          onNoneChange={(none) => {
            setError('')
            onChange({ ...drafts, history_none: { ...drafts.history_none, [key]: none } })
          }}
          onChange={(value) => update('medical_history', { ...drafts.medical_history, [key]: value })} />)}
      </>}
      {error && <p className="field-error" role="alert">{error}</p>}
      <Button icon={question === 'medical_history' ? 'check' : 'arrow-right'} className="wide" type="submit">{question === 'medical_history' ? 'Сохранить ответы и посмотреть итог' : 'Продолжить'}</Button>
    </fieldset>
  </form>
}
