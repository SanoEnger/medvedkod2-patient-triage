export const QUESTIONS = ['primary_complaint', 'patient_context', 'symptom_details', 'red_flags', 'medical_history'] as const
export type QuestionKey = typeof QUESTIONS[number]
export type Category = 'pain' | 'fever' | 'breathing' | 'digestive' | 'skin' | 'neurology' | 'injury' | 'other'
export type Status = 'COLLECTING' | 'REVIEWING' | 'COMPLETED' | 'EMERGENCY_STOP' | 'EXPIRED'
export type Urgency = 'EMERGENCY' | 'WITHIN_24H' | 'PLANNED' | 'SELF_CARE' | 'UNKNOWN'
export const RED_FLAGS = ['chest_pain', 'dyspnea_rest', 'loss_of_consciousness', 'seizure', 'bleeding', 'facial_asymmetry', 'arm_weakness', 'speech_difficulty', 'anaphylaxis', 'acute_abdominal_pain', 'head_injury_with_loc'] as const
export type RedFlag = typeof RED_FLAGS[number]
export const HISTORY_FIELDS = ['chronic_conditions', 'medications', 'allergies', 'operations_last_year', 'hospitalizations_last_year', 'family_history', 'habits'] as const
export type HistoryField = typeof HISTORY_FIELDS[number]

export interface Answers {
  primary_complaint: { category: Category; text: string }
  patient_context: { age_years: number | null; temperature_c: number | null; pregnancy: boolean | null; lactation: boolean | null }
  symptom_details: { location: string; duration: string; severity_0_10: number | null; additional_text: string }
  red_flags: Record<RedFlag, boolean | null>
  medical_history: Record<HistoryField, string[]>
}
export type AnswerRequest = { [K in QuestionKey]: { question_key: K; value: Answers[K]; idempotency_key: string } }[QuestionKey]
export interface Triage {
  urgency: Urgency
  specialty: string | null
  place: string | null
  rationale: string
  disclaimer: string
  rule_codes: string[]
  needs_clarification: boolean
}
export interface Survey {
  id: string
  status: Status
  state: Status
  progress: { answered: number; total: number; percent: number }
  current_question: QuestionKey | null
  next_question: QuestionKey | null
  expires_at: string
  emergency: boolean
  urgency: Urgency | null
  message: string | null
  matched_rule_codes: string[]
  result: Triage | null
}
export interface SurveyClient {
  create(signal?: AbortSignal): Promise<Survey>
  get(id: string, signal?: AbortSignal): Promise<Survey>
  answer(id: string, answer: AnswerRequest, signal?: AbortSignal): Promise<Survey>
  back(id: string, target: number, signal?: AbortSignal): Promise<Survey>
  triage(id: string, signal?: AbortSignal): Promise<Triage>
  delete(id: string, signal?: AbortSignal): Promise<void>
}
export function isEmergency(value: Pick<Survey, 'status' | 'emergency' | 'urgency' | 'result'>): boolean {
  return value.emergency || value.status === 'EMERGENCY_STOP' || value.urgency === 'EMERGENCY' || value.result?.urgency === 'EMERGENCY'
}
