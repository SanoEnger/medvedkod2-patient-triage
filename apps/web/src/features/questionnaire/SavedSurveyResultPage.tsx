import { useEffect, useRef, useState } from 'react'
import { ApiError, emergencyHint } from '../../api/client'
import type { SurveyClient, Triage } from '../../api/contracts'
import { Button, Card } from '../../components/ui'
import { EmergencyActions, ResultCard } from './QuestionnairePage'
import { ClinicEntry } from '../clinics/ClinicEntry'

export function SavedSurveyResultPage({ id, client, chatBlocked, active = true, onHistory, onChat, onClinics }: {
  id: string; client: SurveyClient; chatBlocked: boolean; onHistory: () => void; onChat: () => void
  active?: boolean; onClinics?: (result: Triage, age?: number | null) => void
}) {
  const [result, setResult] = useState<{ triage: Triage; age?: number | null } | 'loading' | 'error' | 'missing' | 'emergency'>('loading')
  const [attempt, setAttempt] = useState(0)
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => { if (active) heading.current?.focus() }, [active])
  useEffect(() => {
    const controller = new AbortController()
    client.get(id, controller.signal).then(
      (survey) => {
        if (controller.signal.aborted) return
        setResult(emergencyHint(survey) ? 'emergency' : survey.status === 'COMPLETED' && survey.result
          ? { triage: survey.result, age: survey.answers?.patient_context?.age_years } : 'missing')
      },
      (cause) => {
        if (controller.signal.aborted) return
        setResult(cause instanceof ApiError && cause.emergency ? 'emergency'
          : cause instanceof ApiError && [403, 404].includes(cause.status) ? 'missing' : 'error')
      },
    )
    return () => controller.abort()
  }, [client, id, attempt])

  return <div className="chat-page result-layout">
    <div><Button icon="arrow-left" variant="secondary" onClick={onHistory}>К истории</Button></div>
    <h1 ref={heading} tabIndex={-1}>Результат опроса</h1>
    {result === 'loading' && <p className="survey-loading" role="status">Загружаем результат…</p>}
    {result === 'missing' && <Card role="alert"><p>Результат недоступен. Возможно, обращение удалено или срок хранения истёк.</p></Card>}
    {result === 'emergency' && <Card className="emergency-card">
      <p className="emergency-message" role="alert">Вызовите скорую помощь (103/112).</p>
      <EmergencyActions />
    </Card>}
    {result === 'error' && <div className="survey-error" role="alert">
      <p>Не удалось загрузить результат опроса.</p>
      <Button variant="secondary" onClick={() => { setResult('loading'); setAttempt((value) => value + 1) }}>Повторить загрузку</Button>
    </div>}
    {typeof result === 'object' && <>
      <ResultCard result={result.triage} />
      <div><Button icon="chat" disabled={chatBlocked} onClick={onChat}>Уточнить у МедВеда</Button></div>
      {onClinics && <ClinicEntry result={result.triage} age={result.age} onOpen={onClinics} />}
    </>}
  </div>
}
