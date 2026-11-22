import type { HostContext, MaxHostAdapter } from './MaxHostAdapter'

let session: { accessToken: string; expiresAt: number } | undefined
let launchSequence = 0
export function getAppSession() {
  return session && session.expiresAt > Date.now() ? session : undefined
}

export function clearAppSession(accessToken: string) {
  if (session?.accessToken !== accessToken) return false
  session = undefined
  return true
}

export function createHostAdapter(): MaxHostAdapter | undefined {
  const url = new URL(window.location.href)
  const tokens = url.searchParams.getAll('token')
  if (!tokens.length) return undefined
  url.searchParams.delete('token')
  window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
  let token: string | undefined = tokens.length === 1 ? tokens[0] : undefined
  let pending: Promise<HostContext> | undefined
  return {
    kind: 'host',
    initialize() {
      pending ??= (async (): Promise<HostContext> => {
        const sequence = ++launchSequence
        const credential = token
        token = undefined
        session = undefined
        if (!credential || credential.length > 6000) throw new Error('HOST_LAUNCH_INVALID')
        const endpoint = new URL('/api/v1/auth/launch', import.meta.env.VITE_API_ORIGIN || window.location.origin)
        if (endpoint.protocol !== 'https:' && !['localhost', '127.0.0.1'].includes(endpoint.hostname)) {
          throw new Error('HOST_API_CONFIGURATION')
        }
        let response: Response
        try {
          response = await fetch(endpoint, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: 'host', host_token: credential }),
            credentials: 'omit', cache: 'no-store', redirect: 'error',
            signal: AbortSignal.timeout(10000), referrerPolicy: 'no-referrer',
          })
        } catch { throw new Error('HOST_AUTH_UNAVAILABLE') }
        if (!response.ok) throw new Error('HOST_AUTH_FAILED')
        const data: unknown = await response.json()
        if (!data || typeof data !== 'object' || !('access_token' in data)
          || typeof data.access_token !== 'string' || !data.access_token
          || !('token_type' in data) || data.token_type !== 'bearer'
          || !('expires_in' in data) || typeof data.expires_in !== 'number'
          || !Number.isFinite(data.expires_in) || data.expires_in <= 0) {
          throw new Error('HOST_AUTH_INVALID_RESPONSE')
        }
        if (sequence !== launchSequence) throw new Error('HOST_LAUNCH_REPLACED')
        session = { accessToken: data.access_token, expiresAt: Date.now() + data.expires_in * 1000 }
        return { mode: 'max' }
      })()
      return pending
    },
  }
}
