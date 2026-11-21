import { useEffect, useMemo, useRef, useState } from 'react'
import type { HostContext, MaxHostAdapter } from '../max/MaxHostAdapter'
import type { Survey } from '../api/contracts'
import type { ChatSummary } from '../api/chat'
import { ErrorState, LoadingState } from '../components/ScreenState'
import { Button } from '../components/ui'
import { WelcomePage } from '../pages/WelcomePage'
import { QuestionnairePage } from '../features/questionnaire/QuestionnairePage'
import { ChatPage } from '../features/chat/ChatPage'
import { ChatHistoryPage } from '../features/chat/ChatHistoryPage'
import { createApiClient } from '../api/client'
import type { MedvedClient } from '../api/client'
import { AppShell } from './AppShell'

type LaunchState = { adapter: MaxHostAdapter; context?: HostContext }
const inProgress = (survey: Survey | null) => !!survey && ['COLLECTING', 'REVIEWING'].includes(survey.status)

export function App({ hostAdapter }: { hostAdapter?: MaxHostAdapter }) {
  const [launch, setLaunch] = useState<LaunchState>()
  const [attempt, setAttempt] = useState(0)
  const current = launch?.adapter === hostAdapter ? launch : undefined
  const mode = current?.context?.mode
  const client = useMemo(() => mode ? createApiClient(mode, () => {
    setLaunch((active) => active === current && hostAdapter ? { adapter: hostAdapter } : active)
  }) : undefined, [mode, current, hostAdapter])

  useEffect(() => {
    let active = true
    if (!hostAdapter) return
    hostAdapter.initialize().then(
      (context) => { if (active) setLaunch({ adapter: hostAdapter, context }) },
      () => { if (active) setLaunch({ adapter: hostAdapter }) },
    )
    return () => { active = false }
  }, [hostAdapter, attempt])

  return <AppShell mode={mode}>
    {client ? <Workspace client={client} />
      : !hostAdapter || current
        ? <ErrorState missingHost={!hostAdapter} hostLaunch={hostAdapter?.kind === 'host'}
          onRetry={() => { setLaunch(undefined); setAttempt((value) => value + 1) }} />
        : <LoadingState />}
  </AppShell>
}

type Page = 'welcome' | 'survey' | 'chat' | 'history'

function Workspace({ client }: { client: MedvedClient }) {
  const [page, setPage] = useState<Page>('welcome')
  const [survey, setSurvey] = useState<Survey | null>(null)
  const [serverSurvey, setServerSurvey] = useState<Survey | null>(null)
  const [initialSurvey, setInitialSurvey] = useState<Survey | null>(null)
  const [surveyKey, setSurveyKey] = useState(0)
  const [surveyOpened, setSurveyOpened] = useState(false)
  const [checking, setChecking] = useState(true)
  const [availabilityError, setAvailabilityError] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const [chatTarget, setChatTarget] = useState<{ questionnaireId?: string; saved?: ChatSummary; key: string } | null>(null)
  const focusAfterNavigation = useRef(false)
  const activeSurvey = inProgress(survey) ? survey
    : serverSurvey && !(survey?.id === serverSurvey.id && !inProgress(survey)) ? serverSurvey : null
  const chatBlocked = checking || availabilityError || !!activeSurvey || survey?.status === 'EMERGENCY_STOP'

  useEffect(() => {
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
  function navigate(next: Page) {
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
    if (forceNew || !chatTarget || chatTarget.saved || (questionnaireId && chatTarget.questionnaireId !== questionnaireId)) {
      setChatTarget({ questionnaireId, key: crypto.randomUUID() })
    }
    navigate('chat')
  }
  function openSaved(saved: ChatSummary) {
    setChatTarget({ saved, key: crypto.randomUUID() })
    navigate('chat')
  }
  function chatDeleted(id: string) {
    setChatTarget(null)
    if (survey?.id === id) {
      setSurvey(null)
      setInitialSurvey(null)
      setSurveyOpened(false)
    }
  }

  return <>
    {page === 'welcome' && <><WelcomePage onStart={startSurvey} onChat={() => openChat()} onHistory={() => navigate('history')}
      surveyInProgress={!!activeSurvey} chatBlocked={chatBlocked} />
      {availabilityError && <div className="survey-error" role="alert"><p>Не удалось проверить текущий опрос. Чат временно недоступен.</p><Button icon="restart" variant="secondary" onClick={() => { setChecking(true); setRefresh((value) => value + 1) }}>Повторить проверку</Button></div>}
    </>}
    {page === 'history' && <ChatHistoryPage client={client.chat} onHome={() => navigate('welcome')} onOpen={openSaved} onDeleted={chatDeleted} />}
    {surveyOpened && <div hidden={page !== 'survey'}>
      <QuestionnairePage key={surveyKey} client={client} initialSurvey={initialSurvey} active={page === 'survey'} onSessionChange={setSurvey}
        onHome={() => navigate('welcome')} onChat={(id) => openChat(id)} />
    </div>}
    {chatTarget && <div hidden={page !== 'chat'}>
      <ChatPage key={chatTarget.key} client={client.chat} questionnaireId={chatTarget.questionnaireId} saved={chatTarget.saved}
        active={page === 'chat'} blocked={chatBlocked} onHome={() => navigate('welcome')}
        onHistory={() => { setChatTarget(null); navigate('history') }}
        onSurvey={() => { if (surveyOpened && !inProgress(activeSurvey)) navigate('survey'); else startSurvey() }}
        onNew={() => openChat(undefined, true)}
        onDeleted={(id) => { chatDeleted(id); navigate('history') }} />
    </div>}
  </>
}
