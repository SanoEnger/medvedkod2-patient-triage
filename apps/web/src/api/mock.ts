import { ApiError } from './client'
import { QUESTIONS } from './contracts'
import type { AnswerRequest, Survey, SurveyClient, Triage } from './contracts'

export type DemoScenario = 'planned' | 'emergency' | 'unknown'
export function demoResult(scenario: DemoScenario): Triage {
  return {
    urgency: scenario === 'emergency' ? 'EMERGENCY' : scenario === 'unknown' ? 'UNKNOWN' : 'PLANNED',
    specialty: scenario === 'planned' ? 'Дерматолог' : null,
    place: scenario === 'emergency' ? 'Скорая помощь: 103/112' : scenario === 'planned' ? 'Поликлиника' : null,
    rationale: scenario === 'emergency' ? 'Вымышленный пример экстренного ответа сервера.' : scenario === 'unknown' ? 'В демонстрационном примере недостаточно сведений для маршрутизации.' : 'Вымышленный пример итоговой карточки.',
    disclaimer: 'Бот не ставит диагноз и не заменяет врача. При ухудшении вызывайте скорую: 103/112.',
    rule_codes: scenario === 'emergency' ? ['SYNTHETIC_EMERGENCY'] : [],
    needs_clarification: scenario === 'unknown',
  }
}
export function createMockClient(scenario: DemoScenario = 'planned'): SurveyClient {
  const sessions = new Map<string, { survey: Survey; replay: Map<string, { body: string; response: Survey }> }>()
  const clone = <T,>(value: T): T => structuredClone(value)
  function find(id: string) {
    const stored = sessions.get(id)
    if (!stored || Date.parse(stored.survey.expires_at) <= Date.now()) throw new ApiError(404)
    return stored
  }
  function advance(survey: Survey, answered: number) {
    survey.progress = { answered, total: QUESTIONS.length, percent: answered * 100 / QUESTIONS.length }
    survey.current_question = survey.next_question = QUESTIONS[answered] ?? null
    survey.status = survey.state = answered === QUESTIONS.length ? 'REVIEWING' : 'COLLECTING'
  }
  return {
    async create() {
      const id = crypto.randomUUID()
      const survey: Survey = {
        id, status: 'COLLECTING', state: 'COLLECTING', progress: { answered: 0, total: QUESTIONS.length, percent: 0 },
        current_question: QUESTIONS[0], next_question: QUESTIONS[0], expires_at: new Date(Date.now() + 86400000).toISOString(),
        emergency: false, urgency: null, message: null, matched_rule_codes: [], result: null,
      }
      sessions.set(id, { survey, replay: new Map() })
      return clone(survey)
    },
    async get(id) { return clone(find(id).survey) },
    async answer(id, answer: AnswerRequest) {
      const stored = find(id)
      const serialized = JSON.stringify({ question_key: answer.question_key, value: answer.value })
      const previous = stored.replay.get(answer.idempotency_key)
      if (previous) {
        if (previous.body !== serialized) throw new ApiError(409)
        return clone(previous.response)
      }
      const survey = stored.survey
      if (survey.status !== 'COLLECTING' || survey.current_question !== answer.question_key) throw new ApiError(409)
      survey.answers = { ...survey.answers, [answer.question_key]: clone(answer.value) }
      advance(survey, survey.progress.answered + 1)
      // Fixtures select outcomes explicitly; medical input is never interpreted in the browser.
      if (scenario === 'emergency') {
        survey.status = survey.state = 'EMERGENCY_STOP'
        survey.emergency = true
        survey.urgency = 'EMERGENCY'
        survey.message = 'Вызовите скорую помощь (103/112). Не ждите окончания опроса.'
        survey.current_question = survey.next_question = null
        survey.result = demoResult('emergency')
      } else if (survey.progress.answered === QUESTIONS.length) survey.result = demoResult(scenario)
      stored.replay.set(answer.idempotency_key, { body: serialized, response: clone(survey) })
      return clone(survey)
    },
    async back(id, target) {
      const stored = find(id)
      if (stored.survey.emergency || target < 0 || target >= stored.survey.progress.answered) throw new ApiError(409)
      if (stored.survey.answers) {
        for (const key of QUESTIONS.slice(target)) delete stored.survey.answers[key]
      }
      advance(stored.survey, target)
      stored.survey.result = null
      stored.replay.clear()
      return clone(stored.survey)
    },
    async triage(id) {
      const survey = find(id).survey
      survey.result ??= demoResult(survey.progress.answered === QUESTIONS.length ? scenario : 'unknown')
      if (survey.progress.answered === QUESTIONS.length && survey.status === 'REVIEWING') survey.status = survey.state = 'COMPLETED'
      return clone(survey.result)
    },
    async delete(id) { find(id); sessions.delete(id) },
  }
}
