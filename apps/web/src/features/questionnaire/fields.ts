import { HISTORY_FIELDS, RED_FLAGS } from '../../api/contracts'
import type { AnswerRequest, Category, HistoryField, QuestionKey, RedFlag } from '../../api/contracts'

export const titles: Record<QuestionKey, string> = {
  primary_complaint: 'Что вас беспокоит?',
  patient_context: 'Важные сведения о самочувствии',
  symptom_details: 'Расскажите о симптомах',
  red_flags: 'Есть ли опасные признаки?',
  medical_history: 'Сведения о здоровье',
}
export const categories: [Category, string][] = [
  ['pain', 'Боль'], ['fever', 'Температура'], ['breathing', 'Дыхание'], ['digestive', 'Пищеварение'],
  ['skin', 'Кожа'], ['neurology', 'Неврология'], ['injury', 'Травма'], ['other', 'Другое'],
]
export const flagLabels: Record<RedFlag, string> = {
  chest_pain: 'Боль в груди', dyspnea_rest: 'Одышка в покое', loss_of_consciousness: 'Потеря сознания',
  seizure: 'Судороги', bleeding: 'Кровотечение', facial_asymmetry: 'Асимметрия лица',
  arm_weakness: 'Слабость в руке', speech_difficulty: 'Нарушение речи', anaphylaxis: 'Признаки анафилаксии',
  acute_abdominal_pain: 'Острая боль в животе', head_injury_with_loc: 'Травма головы с потерей сознания',
}
export const historyLabels: Record<HistoryField, string> = {
  chronic_conditions: 'Хронические заболевания', medications: 'Принимаемые лекарства', allergies: 'Аллергии',
  operations_last_year: 'Операции за последний год', hospitalizations_last_year: 'Госпитализации за последний год',
  family_history: 'Наследственность', habits: 'Вредные привычки (необязательно)',
}
export type Choice = 'unknown' | 'yes' | 'no'
export interface Drafts {
  primary_complaint: { category: Category | ''; text: string }
  patient_context: { age_years: string; temperature_c: string; pregnancy: Choice; lactation: Choice }
  symptom_details: { location: string; duration: string; severity_0_10: string; additional_text: string }
  red_flags: Record<RedFlag, Choice>
  medical_history: Record<HistoryField, string>
}
export function emptyDrafts(): Drafts {
  return {
    primary_complaint: { category: '', text: '' },
    patient_context: { age_years: '', temperature_c: '', pregnancy: 'unknown', lactation: 'unknown' },
    symptom_details: { location: '', duration: '', severity_0_10: '', additional_text: '' },
    red_flags: Object.fromEntries(RED_FLAGS.map((key) => [key, 'unknown'])) as Drafts['red_flags'],
    medical_history: Object.fromEntries(HISTORY_FIELDS.map((key) => [key, ''])) as Drafts['medical_history'],
  }
}
function number(value: string, min: number, max: number, label: string, integer = false): number | null {
  if (!value.trim()) return null
  const parsed = Number(value.replace(',', '.'))
  if (!Number.isFinite(parsed) || parsed < min || parsed > max || (integer && !Number.isInteger(parsed))) {
    throw new Error(label + ': укажите число от ' + min + ' до ' + max + '.')
  }
  return parsed
}
function text(value: string, max: number): string {
  if (value.trim().length > max) throw new Error('Сократите текст: максимум ' + max + ' символов в одном поле.')
  return value.trim()
}
const boolean = (value: Choice): boolean | null => value === 'unknown' ? null : value === 'yes'
export function answerFromDraft(question: QuestionKey, drafts: Drafts): Omit<AnswerRequest, 'idempotency_key'> {
  switch (question) {
    case 'primary_complaint': {
      const value = drafts.primary_complaint
      if (!value.category) throw new Error('Выберите основную жалобу.')
      return { question_key: question, value: { category: value.category, text: text(value.text, 1200) } }
    }
    case 'patient_context': {
      const value = drafts.patient_context
      return { question_key: question, value: {
        age_years: number(value.age_years, 0, 120, 'Возраст', true),
        temperature_c: number(value.temperature_c, 30, 45, 'Температура'),
        pregnancy: boolean(value.pregnancy), lactation: boolean(value.lactation),
      } }
    }
    case 'symptom_details': {
      const value = drafts.symptom_details
      return { question_key: question, value: {
        location: text(value.location, 120), duration: text(value.duration, 120),
        severity_0_10: number(value.severity_0_10, 0, 10, 'Выраженность симптомов', true),
        additional_text: text(value.additional_text, 1200),
      } }
    }
    case 'red_flags':
      return { question_key: question, value: Object.fromEntries(RED_FLAGS.map((key) => [key, boolean(drafts.red_flags[key])])) as Record<RedFlag, boolean | null> }
    case 'medical_history': {
      const value = Object.fromEntries(HISTORY_FIELDS.map((key) => {
        const entries = drafts.medical_history[key].split(/[\n;]+/).map((entry) => entry.trim()).filter(Boolean)
        if (entries.length > 10 || entries.some((entry) => entry.length > 120)) {
          throw new Error(historyLabels[key] + ': не более 10 записей, каждая до 120 символов.')
        }
        return [key, entries]
      })) as Record<HistoryField, string[]>
      return { question_key: question, value }
    }
  }
}
