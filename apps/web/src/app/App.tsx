import { useEffect, useMemo, useRef, useState } from 'react'
import type { HostContext, MaxHostAdapter } from '../max/MaxHostAdapter'
import type { Survey } from '../api/contracts'
import { ErrorState, LoadingState } from '../components/ScreenState'
import { Button } from '../components/ui'
import { WelcomePage } from '../pages/WelcomePage'
import { QuestionnairePage } from '../features/questionnaire/QuestionnairePage'
import { ChatPage } from '../features/chat/ChatPage'
import { createApiClient } from '../api/client'
import { AppShell } from './AppShell'

type LaunchState = { status: 'loading' } | { status: 'error' } | { status: 'ready'; context: HostContext }
const inProgress = (survey: Survey | null) => !!survey && ['COLLECTING', 'REVIEWING'].includes(survey.status)

export function App({ hostAdapter }: { hostAdapter?: MaxHostAdapter }) {
  const [launch, setLaunch] = useState<LaunchState>({ status: 'loading' })
  const [attempt, setAttempt] = useState(0)
  const [page, setPage] = useState<'welcome' | 'survey' | 'chat'>('welcome')
  const [survey, setSurvey] = useState<Survey | null>(null)
  const [serverSurvey, setServerSurvey] = useState<Survey | null>(null)
  const [initialSurvey, setInitialSurvey] = useState<Survey | null>(null)
  const [surveyKey, setSurveyKey] = useState(0)
  const [surveyOpened, setSurveyOpened] = useState(false)
  const [checking, setChecking] = useState(true)
  const [availabilityError, setAvailabilityError] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [chatTarget, setChatTarget] = useState<{ questionnaireId?: string; key: string } | null>(null)
  const focusAfterNavigation = useRef(false)
  const mode = launch.status === 'ready' ? launch.context.mode : undefined
  const client = useMemo(() => mode ? createApiClient(mode) : undefined, [mode])
  const activeSurvey = inProgress(survey) ? survey
    : serverSurvey && !(survey?.id === serverSurvey.id && !inProgress(survey)) ? serverSurvey : null
  const chatBlocked = checking || availabilityError || !!activeSurvey || survey?.status === 'EMERGENCY_STOP'

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
    if (!client) return
    const controller = new AbortController()
    client.chat.availability(controller.signal).then(
      ({ active_survey }) => { if (!controller.signal.aborted) { setServerSurvey(active_survey); setAvailabilityError(false) } },
      () => { if (!controller.signal.aborted) setAvailabilityError(true) },
    ).finally(() => { if (!controller.signal.aborted) setChecking(false) })
    return () => controller.abort()
  }, [client, survey?.id, survey?.status, refresh])
  useEffect(() => {
    if (focusAfterNavigation.current) {
      document.querySelector<HTMLElement>('main > div:not([hidden]) h1, main > .welcome-layout h1')?.focus()
      window.scrollTo(0, 0)
    }
  }, [page])
  function navigate(next: 'welcome' | 'survey' | 'chat') {
    focusAfterNavigation.current = true
    setPage(next)
    if (next === 'welcome') setRefresh((value) => value + 1)
  }
  function startSurvey() {
    if (!surveyOpened || (activeSurvey && activeSurvey.id !== survey?.id) || !activeSurvey) {
      setInitialSurvey(activeSurvey)
      setSurvey(activeSurvey)
      setSurveyKey((value) => value + 1)
      setSurveyOpened(true)
    }
    navigate('survey')
  }
  function openChat(questionnaireId?: string, forceNew = false) {
    if (questionnaireId || !chatTarget || forceNew) {
      if (forceNew || !chatTarget || chatTarget.questionnaireId !== questionnaireId) {
        setChatTarget({ questionnaireId, key: crypto.randomUUID() })
      }
    }
    navigate('chat')
  }
  const retry = () => { setLaunch({ status: 'loading' }); setAttempt((value) => value + 1) }
  return <AppShell mode={mode}>
    {!hostAdapter || launch.status === 'error'
      ? <ErrorState missingHost={!hostAdapter} hostLaunch={hostAdapter?.kind === 'host'} onRetry={retry} />
      : launch.status === 'loading'
        ? <LoadingState />
        : <>
          {page === 'welcome' && <><WelcomePage onStart={startSurvey} onChat={() => openChat()} surveyInProgress={!!activeSurvey} chatBlocked={chatBlocked} />
            {availabilityError && <div className="survey-error" role="alert"><p>Не удалось проверить текущий опрос. Чат временно недоступен.</p><Button icon="restart" variant="secondary" onClick={() => { setChecking(true); setRefresh((value) => value + 1) }}>Повторить проверку</Button></div>}
          </>}
          {client && surveyOpened && <div hidden={page !== 'survey'}>
            <QuestionnairePage key={surveyKey} client={client} initialSurvey={initialSurvey} active={page === 'survey'} onSessionChange={setSurvey}
              onHome={() => navigate('welcome')} onChat={(id) => openChat(id)} />
          </div>}
          {client && chatTarget && <div hidden={page !== 'chat'}>
            <ChatPage key={chatTarget.key} client={client.chat} questionnaireId={chatTarget.questionnaireId}
              active={page === 'chat'} blocked={chatBlocked} onHome={() => navigate('welcome')}
              onSurvey={() => { if (surveyOpened && !inProgress(activeSurvey)) navigate('survey'); else startSurvey() }}
              onNew={() => openChat(undefined, true)} />
          </div>}
        </>}
  </AppShell>
}
