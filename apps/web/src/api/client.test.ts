import { afterEach, expect, test, vi } from 'vitest'
import { ApiError, createApiClient, parseSurvey, parseTriage } from './client'
import { createMockClient, demoResult } from './mock'
import * as host from '../max/host'

afterEach(() => { expect(localStorage.length + sessionStorage.length).toBe(0) })

test('API demo exchanges a token once and uses bearer for session requests', async () => {
  vi.stubEnv('VITE_API_ORIGIN', 'https://api.example')
  const survey = await createMockClient().create()
  const fetch = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({
    access_token: 'synthetic-app-token', token_type: 'bearer', expires_in: 3600,
  }))).mockImplementation(async () => new Response(JSON.stringify(survey)))
  vi.stubGlobal('fetch', fetch)
  const client = createApiClient('demo')
  await client.create()
  await client.get(survey.id)
  expect(fetch).toHaveBeenCalledTimes(3)
  expect(String(fetch.mock.calls[0][0])).toBe('https://api.example/api/v1/auth/launch')
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ mode: 'demo' })
  expect(fetch.mock.calls[1][1]).toMatchObject({
    credentials: 'omit', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer',
    headers: { Authorization: 'Bearer synthetic-app-token' },
  })
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ accepted_disclaimer: true })
})

test('MAX uses the existing app token and never starts demo authentication', async () => {
  vi.stubEnv('VITE_API_ORIGIN', 'https://api.example')
  vi.spyOn(host, 'getAppSession').mockReturnValue({ accessToken: 'synthetic-host-session', expiresAt: Date.now() + 3600000 })
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(await createMockClient().create())))
  vi.stubGlobal('fetch', fetch)
  await createApiClient('max').create()
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(String(fetch.mock.calls[0][0])).toBe('https://api.example/api/v1/sessions')
  expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer synthetic-host-session')
})

test('missing MAX authorization fails without a demo or network fallback', async () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  vi.spyOn(host, 'getAppSession').mockReturnValue(undefined)
  await expect(createApiClient('max').create()).rejects.toMatchObject({ status: 401 })
  expect(fetch).not.toHaveBeenCalled()
})

test('DELETE 204 does not require or read a JSON response', async () => {
  vi.spyOn(host, 'getAppSession').mockReturnValue({ accessToken: 'synthetic-token', expiresAt: Date.now() + 3600000 })
  const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
  vi.stubGlobal('fetch', fetch)
  await expect(createApiClient('max').delete(crypto.randomUUID())).resolves.toBeUndefined()
})

test('non-local plaintext API origin is rejected before network access', async () => {
  vi.stubEnv('VITE_API_ORIGIN', 'http://untrusted.example')
  vi.spyOn(host, 'getAppSession').mockReturnValue({ accessToken: 'synthetic-token', expiresAt: Date.now() + 3600000 })
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  await expect(createApiClient('max').create()).rejects.toBeInstanceOf(ApiError)
  expect(fetch).not.toHaveBeenCalled()
})

test('errors never expose a raw server body', async () => {
  vi.spyOn(host, 'getAppSession').mockReturnValue({ accessToken: 'synthetic-token', expiresAt: Date.now() + 3600000 })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
    detail: 'synthetic confidential marker',
  }), { status: 503 })))
  try { await createApiClient('max').create(); expect.fail('Expected failure') }
  catch (error) {
    expect(error).toMatchObject({ status: 503 })
    expect(String(error)).not.toContain('confidential')
  }
})

test('malformed emergency hint still produces a non-dismissible emergency signal', () => {
  expect(() => parseSurvey({ emergency: true })).toThrow(ApiError)
  try { parseSurvey({ status: 'EMERGENCY_STOP' }) }
  catch (error) { expect(error).toMatchObject({ emergency: true, invalidResponse: true }) }
  try { parseTriage({ urgency: 'EMERGENCY' }) }
  catch (error) { expect(error).toMatchObject({ emergency: true }) }
})

test('unknown urgency and inconsistent current question fail closed', async () => {
  expect(() => parseTriage({ ...demoResult('planned'), urgency: 'MADE_UP' })).toThrow(ApiError)
  const survey = await createMockClient().create()
  expect(() => parseSurvey({ ...survey, current_question: 'medical_history' })).toThrow(ApiError)
  expect(() => parseSurvey({ ...survey, progress: { ...survey.progress, total: 999 } })).toThrow(ApiError)
})
