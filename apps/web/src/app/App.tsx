import { useEffect, useRef, useState } from 'react'
import type { HostContext, MaxHostAdapter } from '../max/MaxHostAdapter'
import { ErrorState, LoadingState } from '../components/ScreenState'
import { WelcomePage } from '../pages/WelcomePage'
import { DemoPage } from '../pages/DemoPage'
import { AppShell } from './AppShell'

type LaunchState = { status: 'loading' } | { status: 'error' } | { status: 'ready'; context: HostContext }

export function App({ hostAdapter }: { hostAdapter?: MaxHostAdapter }) {
  const [launch, setLaunch] = useState<LaunchState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [page, setPage] = useState<'welcome' | 'demo'>('welcome')
  const focusAfterNavigation = useRef(false)

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

  function navigate(next: 'welcome' | 'demo') {
    focusAfterNavigation.current = true
    setPage(next)
  }

  const retry = () => {
    setLaunch({ status: 'loading' })
    setAttempt((value) => value + 1)
  }

  return <AppShell mode={launch.status === 'ready' ? launch.context.mode : undefined}>
    {!hostAdapter || launch.status === 'error'
      ? <ErrorState missingHost={!hostAdapter} hostLaunch={hostAdapter?.kind === 'host'} onRetry={retry} />
      : launch.status === 'loading'
        ? <LoadingState />
        : page === 'welcome'
          ? <WelcomePage onOpenDemo={() => navigate('demo')} />
          : <DemoPage onBack={() => navigate('welcome')} />}
  </AppShell>
}
