import { getAppSession } from '../max/host'
import { QUESTIONS } from './contracts'
import type { Survey, SurveyClient, Triage } from './contracts'

export class ApiError extends Error {
  constructor(public readonly status = 0, public readonly emergency = false, public readonly invalidResponse = false) {
    super('SURVEY_API_ERROR')
  }
}
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every((entry) => typeof entry === 'string')
const nullableText = (value: unknown) => value === null || typeof value === 'string'
const urgency = ['EMERGENCY', 'WITHIN_24H', 'PLANNED', 'SELF_CARE', 'UNKNOWN']
const statuses = ['COLLECTING', 'REVIEWING', 'COMPLETED', 'EMERGENCY_STOP', 'EXPIRED']
export function emergencyHint(value: unknown): boolean {
  return object(value) && (value.emergency === true || value.status === 'EMERGENCY_STOP' || value.state === 'EMERGENCY_STOP'
    || value.urgency === 'EMERGENCY' || (object(value.result) && value.result.urgency === 'EMERGENCY'))
}
export function parseTriage(value: unknown): Triage {
  if (!object(value) || !urgency.includes(String(value.urgency)) || !nullableText(value.specialty)
    || !nullableText(value.place) || typeof value.rationale !== 'string' || typeof value.disclaimer !== 'string'
    || !value.disclaimer || !strings(value.rule_codes) || typeof value.needs_clarification !== 'boolean') {
    throw new ApiError(0, emergencyHint(value), true)
  }
  return value as unknown as Triage
}
export function parseSurvey(value: unknown): Survey {
  const question = (entry: unknown) => entry === null || QUESTIONS.includes(entry as typeof QUESTIONS[number])
  if (!object(value) || typeof value.id !== 'string' || !/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value.id)
    || !statuses.includes(String(value.status)) || value.state !== value.status
    || !object(value.progress) || !Number.isInteger(value.progress.answered) || !Number.isInteger(value.progress.total)
    || value.progress.total !== QUESTIONS.length || Number(value.progress.answered) < 0 || Number(value.progress.answered) > QUESTIONS.length
    || !Number.isInteger(value.progress.percent) || Number(value.progress.percent) < 0 || Number(value.progress.percent) > 100
    || value.progress.percent !== Math.floor(Number(value.progress.answered) * 100 / QUESTIONS.length)
    || !question(value.current_question) || !question(value.next_question)
    || value.current_question !== value.next_question
    || (value.status !== 'COLLECTING' && value.current_question !== null)
    || typeof value.expires_at !== 'string' || !Number.isFinite(Date.parse(value.expires_at))
    || typeof value.emergency !== 'boolean' || !nullableText(value.message) || !strings(value.matched_rule_codes)
    || !(value.urgency === null || urgency.includes(String(value.urgency)))) {
    throw new ApiError(0, emergencyHint(value), true)
  }
  if (value.status === 'COLLECTING' && value.current_question !== QUESTIONS[Number(value.progress.answered)]) {
    throw new ApiError(0, emergencyHint(value), true)
  }
  if (value.result !== null) parseTriage(value.result)
  return value as unknown as Survey
}
export function apiEndpoint(path: string): URL {
  let origin: URL
  try { origin = new URL(import.meta.env.VITE_API_ORIGIN || window.location.origin) }
  catch { throw new ApiError(0, false, true) }
  if (origin.username || origin.password || origin.search || origin.hash
    || (origin.protocol !== 'https:' && !(origin.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(origin.hostname)))) {
    throw new ApiError(0, false, true)
  }
  return new URL(path, origin.origin)
}

export function createApiClient(mode: 'demo' | 'max'): SurveyClient {
  let demoSession: { accessToken: string; expiresAt: number } | undefined
  let authorization: Promise<string> | undefined
  async function request(path: string, method: string, body?: unknown, signal?: AbortSignal, token?: string): Promise<unknown> {
    let response: Response
    try {
      response = await fetch(apiEndpoint(path), {
        method, headers: { ...(body === undefined ? {} : { 'Content-Type': 'application/json' }), ...(token ? { Authorization: 'Bearer ' + token } : {}) },
        body: body === undefined ? undefined : JSON.stringify(body),
        credentials: 'omit', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer',
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000),
      })
    } catch (error) { if (error instanceof ApiError) throw error; throw new ApiError() }
    if (method === 'DELETE' && response.status === 204) return undefined
    let value: unknown
    try { value = await response.json() } catch { throw new ApiError(response.status, false, true) }
    if (!response.ok) {
      if (response.status === 401 && mode === 'demo') demoSession = undefined
      throw new ApiError(response.status, emergencyHint(value))
    }
    return value
  }
  async function token(): Promise<string> {
    if (mode === 'max') {
      const session = getAppSession()
      if (!session) throw new ApiError(401)
      return session.accessToken
    }
    if (demoSession && demoSession.expiresAt > Date.now()) return demoSession.accessToken
    authorization ??= request('/api/v1/auth/launch', 'POST', { mode: 'demo' }).then((value) => {
      if (!object(value) || typeof value.access_token !== 'string' || !value.access_token || value.token_type !== 'bearer'
        || typeof value.expires_in !== 'number' || !Number.isFinite(value.expires_in) || value.expires_in <= 0) throw new ApiError(0, false, true)
      demoSession = { accessToken: value.access_token, expiresAt: Date.now() + value.expires_in * 1000 }
      return value.access_token
    }).finally(() => { authorization = undefined })
    return authorization
  }
  async function call(path: string, method: string, body?: unknown, signal?: AbortSignal) {
    return request(path, method, body, signal, await token())
  }
  const path = (id: string) => '/api/v1/sessions/' + encodeURIComponent(id)
  return {
    create: async (signal) => parseSurvey(await call('/api/v1/sessions', 'POST', { accepted_disclaimer: true }, signal)),
    get: async (id, signal) => parseSurvey(await call(path(id), 'GET', undefined, signal)),
    answer: async (id, body, signal) => parseSurvey(await call(path(id) + '/answers', 'POST', body, signal)),
    back: async (id, target, signal) => parseSurvey(await call(path(id) + '/back', 'POST', { target_step: target }, signal)),
    triage: async (id, signal) => parseTriage(await call(path(id) + '/triage', 'POST', {}, signal)),
    delete: async (id, signal) => { await call(path(id), 'DELETE', undefined, signal) },
  }
}
