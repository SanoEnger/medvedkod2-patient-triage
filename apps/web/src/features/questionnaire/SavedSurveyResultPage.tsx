import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import type { SurveyClient, Triage } from '../../api/contracts'
import { Button, Card } from '../../components/ui'
import { ResultCard } from './QuestionnairePage'

export function SavedSurveyResultPage({ id, client, chatBlocked, onHistory, onChat }: {
  id: string; client: SurveyClient; chatBlocked: boolean; onHistory: () => void; onChat: () => void
}) {
  const [result, setResult] = useState<Triage | 'loading' | 'error' | 'missing'>('loading')
  const [attempt, setAttempt] = useState(0)
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => { heading.current?.focus() }, [])
  useEffect(() => {
    const controller = new AbortController()
    client.get(id, controller.signal).then(
      (survey) => {
        if (controller.signal.aborted) return
        setResult(survey.status === 'COMPLETED' && survey.result ? survey.result : 'missing')
      },
      (cause) => {
        if (controller.signal.aborted) return
        setResult(cause instanceof ApiError && [403, 404].includes(cause.status) ? 'missing' : 'error')
      },
    )
    return () => controller.abort()
  }, [client, id, attempt])

  return <div className="chat-page result-layout">
    <div><Button icon="arrow-left" variant="secondary" onClick={onHistory}>К истории</Button></div>
    <h1 ref={heading} tabIndex={-1}>Результат опроса</h1>
    {result === 'loading' && <p className="survey-loading" role="status">Загружаем результат…</p>}
    {result === 'missing' && <Card role="alert"><p>Результат недоступен. Возможно, обращение удалено или срок хранения истёк.</p></Card>}
    {result === 'error' && <div className="survey-error" role="alert">
      <p>Не удалось загрузить результат опроса.</p>
      <Button variant="secondary" onClick={() => { setResult('loading'); setAttempt((value) => value + 1) }}>Повторить загрузку</Button>
    </div>}
    {typeof result === 'object' && <>
      <ResultCard result={result} />
      <div><Button icon="chat" disabled={chatBlocked} onClick={onChat}>Уточнить у МедВеда</Button></div>
    </>}
  </div>
}
