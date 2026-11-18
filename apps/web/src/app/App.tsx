import { useEffect, useMemo, useRef, useState } from 'react'
import type { HostContext, MaxHostAdapter } from '../max/MaxHostAdapter'
import { ErrorState, LoadingState } from '../components/ScreenState'
import { WelcomePage } from '../pages/WelcomePage'
import { QuestionnairePage } from '../features/questionnaire/QuestionnairePage'
import { createApiClient } from '../api/client'
import { createMockClient } from '../api/mock'
import { AppShell } from './AppShell'

type LaunchState = { status: 'loading' } | { status: 'error' } | { status: 'ready'; context: HostContext }

export function App({ hostAdapter }: { hostAdapter?: MaxHostAdapter }) {
  const [launch, setLaunch] = useState<LaunchState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [page, setPage] = useState<'welcome' | 'survey'>('welcome')
  const focusAfterNavigation = useRef(false)
  const mode = launch.status === 'ready' ? launch.context.mode : undefined
  const mock = mode === 'demo' && (import.meta.env.VITE_SURVEY_MODE === 'mock'
    || (!import.meta.env.VITE_SURVEY_MODE && !import.meta.env.VITE_API_ORIGIN))
  const client = useMemo(() => {
    if (!mode) return undefined
    if (!mock) return createApiClient(mode)
    const scenario = new URLSearchParams(window.location.search).get('scenario')
    return createMockClient(scenario === 'emergency' || scenario === 'unknown' ? scenario : 'planned')
  }, [mode, mock])

  useEffect(() => {
    let active = true
    if (!hostAdapter) return
    hostAdapter.initialize().then(
      (context) => { if (active) setLaunch({ status: 'ready', context }) },
      () => { if (active) setLaunch({ status: 'error' }) },
    )
    return () => { active = false }
  }, [hostAdapter, attempt])

  useEffect(() => {
    if (focusAfterNavigation.current) {
      document.querySelector<HTMLElement>('h1')?.focus()
      window.scrollTo(0, 0)
    }
  }, [page])
  function navigate(next: 'welcome' | 'survey') {
    focusAfterNavigation.current = true
    setPage(next)
  }
  const retry = () => {
    setLaunch({ status: 'loading' })
    setAttempt((value) => value + 1)
  }
  return <AppShell mode={mode}>
    {!hostAdapter || launch.status === 'error'
      ? <ErrorState missingHost={!hostAdapter} hostLaunch={hostAdapter?.kind === 'host'} onRetry={retry} />
      : launch.status === 'loading'
        ? <LoadingState />
        : page === 'welcome'
          ? <WelcomePage onStart={() => navigate('survey')} />
          : client && <QuestionnairePage client={client} mock={mock} onHome={() => navigate('welcome')} />}
  </AppShell>
}
