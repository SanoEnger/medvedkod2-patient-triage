import { useEffect, useRef, useState } from 'react'
import { Button, Card } from '../../components/ui'
import { Icon } from '../../components/Icon'
import { QUESTIONS } from '../../api/contracts'
import type { Survey, SurveyClient, Triage } from '../../api/contracts'
import type { TranscribeAudio } from '../../api/client'
import { titles, draftsFromAnswers } from './fields'
import { QuestionForm } from './QuestionForm'
import { useQuestionnaire } from './useQuestionnaire'

const urgencyLabels: Record<Triage['urgency'], string> = {
  EMERGENCY: 'Экстренно', WITHIN_24H: 'В течение 24 часов', PLANNED: 'Планово', SELF_CARE: 'Самопомощь', UNKNOWN: 'Нужно уточнение',
}
export function ResultCard({ result }: { result: Triage }) {
  return <Card className="result-card">
    <p className="urgency-label">{urgencyLabels[result.urgency]}</p>
    <h2>Куда обратиться</h2>
    <dl className="result-details">
      <div><dt>Специалист</dt><dd>{result.specialty || 'Не определён'}</dd></div>
      <div><dt>Место обращения</dt><dd>{result.place || 'Нужно уточнить'}</dd></div>
      <div><dt>Обоснование</dt><dd>{result.rationale}</dd></div>
    </dl>
    {result.analysis && <section aria-label="Разбор анкеты">
      <h2>{result.analysis_source === 'mock' ? 'Демонстрационный разбор' : 'Разбор анкеты МедВедом'}</h2>
      <p style={{ whiteSpace: 'pre-wrap' }}>{result.analysis}</p>
    </section>}
    {result.analysis_source === 'unavailable' && <p role="status">Разбор анкеты моделью сейчас недоступен. Выше показан результат правил безопасности.</p>}
    {result.needs_clarification && result.urgency !== 'UNKNOWN' && <p className="notice">Ответы требуют уточнения.</p>}
    <p className="result-disclaimer">{result.disclaimer.replace('Демонстрационный прототип', 'МедВед')}</p>
  </Card>
}
function errorText(status: number, invalid: boolean, hasSession: boolean): string {
  if (!hasSession && status === 404) return 'Не удалось подключиться к опросу. Проверьте подключение и повторите попытку.'
  if (status === 401 || status === 403) return 'Доступ к опросу истёк или запрещён. Вернитесь в MAX и откройте приложение заново.'
  if (status === 404) return 'Срок хранения обращения истёк или оно удалено. Можно начать новый опрос.'
  if (status === 409) return 'Состояние обращения изменилось. Обновите его перед продолжением.'
  if (status === 400 || status === 422) return 'Сервер не принял ответ. Проверьте поля и отправьте исправленный вариант.'
  if (status === 413) return 'В ответе слишком много текста. Сократите записи и отправьте заново.'
  if (invalid) return 'Не удалось прочитать ответ сервера. Результат пока не подтверждён.'
  return 'Не удалось подтвердить действие. Проверьте подключение и повторите попытку.'
}

export function QuestionnairePage({ client, onHome, onChat, initialSurvey, active = true, onSessionChange, transcribe }: {
  client: SurveyClient; onHome: () => void; onChat?: (id: string) => void; initialSurvey?: Survey | null
  active?: boolean; onSessionChange?: (survey: Survey | null) => void
  transcribe?: TranscribeAudio
}) {
  const flow = useQuestionnaire(client, initialSurvey)
  const [drafts, setDrafts] = useState(() => draftsFromAnswers(initialSurvey?.answers))
  const [accepted, setAccepted] = useState(!!initialSurvey)
  const [editing, setEditing] = useState(false)
  const [finished, setFinished] = useState(false)
  const [chatHintFor, setChatHintFor] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const dialog = useRef<HTMLDialogElement>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const question = flow.survey?.current_question
  const surveyCompleted = flow.survey?.status === 'COMPLETED'
  const unavailable = flow.survey && flow.error && [401, 403, 404].includes(flow.error.status)
  const screen = flow.emergency ? 'emergency' : unavailable ? 'unavailable' : question || (flow.survey ? 'result' : 'consent')
  useEffect(() => {
    if (active) { heading.current?.focus(); window.scrollTo(0, 0) }
  }, [screen, active])
  useEffect(() => { onSessionChange?.(flow.survey) }, [flow.survey, onSessionChange])
  useEffect(() => {
    if (confirmDelete) dialog.current?.showModal()
    else dialog.current?.close()
  }, [confirmDelete])
  function reset() {
    flow.reset()
    setDrafts(draftsFromAnswers())
    setAccepted(false)
    setEditing(false)
    setFinished(false)
  }
  const error = flow.error && <div className="survey-error" role="alert">
    <p>{errorText(flow.error.status, flow.error.invalidResponse, !!flow.survey)}</p>
    <div className="form-actions">
      {flow.canRetry && flow.failedKind !== 'delete' && <Button icon="restart" variant="secondary" disabled={flow.busy} onClick={() => { void flow.retry() }}>Повторить действие</Button>}
      {flow.survey && ![401, 403, 404].includes(flow.error.status) && <Button icon="restart" variant="secondary" disabled={flow.busy} onClick={() => { void flow.refresh() }}>Обновить состояние</Button>}
    </div>
  </div>
  const backPending = flow.activity === 'back' || (flow.error && flow.failedKind === 'back')
  return <div className="questionnaire-page">
    {!flow.emergency && <Button icon="home" variant="secondary" className="home-action" disabled={flow.busy} onClick={onHome}>На главную</Button>}
    {flow.emergency ? <Card className="emergency-card">
      <p className="urgency-label">Экстренно · 103/112</p>
      <h1 ref={heading} tabIndex={-1}>Вызовите скорую помощь</h1>
      <p className="emergency-message" role="alert">Вызовите скорую помощь (103/112). Не ждите окончания опроса.</p>
      {flow.survey?.result?.rationale && <p>{flow.survey.result.rationale}</p>}
      <div className="emergency-actions">
        <a className="button button--primary" href="tel:103"><Icon name="phone" /><span>Позвонить 103</span></a>
        <a className="button button--secondary" href="tel:112"><Icon name="phone" /><span>Позвонить 112</span></a>
      </div>
      {error}
      <Button icon="restart" variant="secondary" disabled={flow.busy} onClick={reset}>Начать новый опрос</Button>
    </Card> : <>
      {!flow.survey && !unavailable && <Card>
        <p className="eyebrow">Перед началом</p>
        <h1 ref={heading} tabIndex={-1}>Несколько важных слов</h1>
        <p className="question-note">Бот не ставит диагноз и не заменяет врача. Он не назначает лекарства и лечение.</p>
        <div className="notice"><p>Не указывайте имя, телефон, адрес и данные документов.</p></div>
        <form onSubmit={(event) => { event.preventDefault(); if (accepted && !flow.busy) void flow.start() }}>
          <label className="consent-field"><input type="checkbox" required checked={accepted} disabled={flow.busy} onChange={(event) => setAccepted(event.target.checked)} /><span>Я понимаю, что бот не ставит диагноз и не заменяет врача</span></label>
          <Button icon="clipboard" type="submit" className="wide" disabled={!accepted || flow.busy}>Начать опрос</Button>
        </form>
        {error}
      </Card>}
      {unavailable && <Card>
        <h1 ref={heading} tabIndex={-1}>Обращение недоступно</h1>
        {error}
        {flow.error?.status === 404 && <Button icon="restart" onClick={reset}>Начать новый опрос</Button>}
      </Card>}
      {flow.survey && !unavailable && <>
        <div className="survey-progress">
          <p>Отвечено {flow.survey.progress.answered} из {flow.survey.progress.total}</p>
          <progress aria-label="Прогресс опроса" max={100} value={flow.survey.progress.percent} />
        </div>
        {backPending ? <Card><h1 ref={heading} tabIndex={-1}>Возвращаемся к ответам</h1>{error}</Card> :
          question ? <Card>
            <p className="eyebrow">Шаг {flow.survey.progress.answered + 1} из {flow.survey.progress.total}</p>
            <h1 ref={heading} tabIndex={-1}>{titles[question]}</h1>
            <QuestionForm key={question} question={question} drafts={drafts} onChange={setDrafts} active={active} transcribe={transcribe}
              onAnswer={(body) => { void flow.answer(body) }} disabled={flow.busy || flow.uncertainAnswer || flow.error?.status === 409} />
            {flow.survey.progress.answered > 0 && <Button icon="arrow-left" className="back-action" variant="secondary" disabled={flow.busy || flow.uncertainAnswer || flow.error?.status === 409}
              onClick={() => { void flow.back(flow.survey!.progress.answered - 1) }}>Назад</Button>}
            {error}
          </Card> : <div className="result-layout">
            <h1 ref={heading} tabIndex={-1}>Результат опроса</h1>
            {flow.survey.result ? <ResultCard result={flow.survey.result} /> : <Card><p>Итог ещё не получен.</p></Card>}
            {(finished || surveyCompleted) && <p className="form-feedback" role="status">Ответы сохранены. Можно вернуться на главную или начать новый опрос.</p>}
            <div className="form-actions">
              {!finished && flow.survey.status !== 'COMPLETED' && <Button icon="check" disabled={flow.busy} onClick={async () => { if (await flow.triage()) setFinished(true) }}>{flow.survey.result ? 'Завершить опрос' : 'Получить результат'}</Button>}
              {onChat && flow.survey.result && <Button icon="chat" variant={surveyCompleted ? 'primary' : 'secondary'}
                disabled={flow.busy} aria-disabled={surveyCompleted ? undefined : true} onClick={() => {
                  const id = flow.survey!.id
                  if (surveyCompleted) onChat(id)
                  else setChatHintFor(id)
                }}>Уточнить у МедВеда</Button>}
              <Button icon="edit" variant="secondary" disabled={flow.busy} onClick={() => setEditing((value) => !value)}>Уточнить ответы</Button>
              <Button icon="restart" variant="secondary" disabled={flow.busy} onClick={async () => {
                if (flow.survey!.status !== 'REVIEWING' || await flow.triage()) reset()
              }}>Начать новый опрос</Button>
            </div>
            {!surveyCompleted && chatHintFor === flow.survey.id &&
              <p className="field-hint" role="status">Чтобы уточнить результат у МедВеда, завершите опрос.</p>}
            {editing && <Card><h2>К какому шагу вернуться?</h2><p className="question-note">После возврата следующие ответы нужно подтвердить заново. Прежний результат будет сброшен.</p>
              <div className="edit-steps">{QUESTIONS.slice(0, flow.survey.progress.answered).map((key, index) =>
                <Button key={key} icon="edit" variant="secondary" disabled={flow.busy} onClick={async () => {
                  if (await flow.back(index)) { setEditing(false); setFinished(false); setChatHintFor(null) }
                }}>{index + 1}. {titles[key]}</Button>)}</div>
            </Card>}
            {error}
          </div>}
      </>}
    </>}
    {flow.busy && <p className="survey-loading" role="status">{question === 'medical_history' ? 'Формируем итог и разбор МедВеда…' : 'Сохраняем и проверяем сведения…'}</p>}
    {flow.survey && <Button className="delete-action" variant="secondary" disabled={flow.busy} onClick={() => setConfirmDelete(true)}>Удалить обращение</Button>}
    <dialog className="delete-dialog" ref={dialog} aria-labelledby="delete-title" onCancel={() => setConfirmDelete(false)} onClose={() => setConfirmDelete(false)}>
      <h2 id="delete-title">Удалить это обращение?</h2>
      <p className="question-note">Ответы, переписка и результат будут удалены. Действие нельзя отменить.</p>
      {confirmDelete && error}
      <div className="form-actions">
        <Button variant="secondary" autoFocus disabled={flow.busy} onClick={() => setConfirmDelete(false)}>Отмена</Button>
        <Button disabled={flow.busy} onClick={async () => {
          if (await flow.remove()) { setConfirmDelete(false); setDrafts(draftsFromAnswers()); setAccepted(false); setFinished(false); setEditing(false) }
        }}>{flow.activity === 'delete' ? 'Удаляем…' : 'Удалить'}</Button>
      </div>
    </dialog>
  </div>
}
