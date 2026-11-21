import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../api/client'
import type { ChatClient, ChatSummary, Conversation } from '../../api/chat'
import { Button, Card } from '../../components/ui'
import medvedUrl from '../../assets/medved-bear-button.svg?url'
import { DeleteChatDialog } from './DeleteChatDialog'

type Message = { text: string; client_message_id: string }
function errorText(error: unknown, fallback = 'Не удалось обновить переписку. Нажмите «Обновить чат».') {
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403) return 'Доступ истёк. Снова откройте приложение в MAX.'
    if (error.status === 404) return 'Чат удалён или срок его хранения истёк. Начните новый чат.'
    if (error.code === 'questionnaire_in_progress' || error.code === 'questionnaire_not_completed') {
      return 'Завершите текущий опрос, чтобы продолжить переписку.'
    }
    if (error.code === 'chat_reply_pending' || error.code === 'chat_turn_pending') {
      return 'Предыдущее сообщение ещё обрабатывается. Обновите чат и проверьте ответ.'
    }
    if (error.code === 'chat_emergency_stop') return 'Этот чат остановлен и доступен для чтения.'
    if (error.code === 'chat_message_limit') return 'Этот чат достиг лимита сообщений. Начните новый чат.'
    if (error.code === 'questionnaire_changed') return 'Ответы опроса изменились. Откройте актуальный результат опроса.'
    if (error.code === 'idempotency_conflict') return 'Сообщение изменилось при повторе. Проверьте текст и отправьте снова.'
    if (error.status === 429) return 'Слишком много запросов. Подождите немного и повторите отправку.'
  }
  return fallback
}

export function ChatPage({ client, questionnaireId, saved, active, blocked, onHome, onHistory, onSurvey, onNew, onDeleted }: {
  client: ChatClient; questionnaireId?: string; saved?: ChatSummary; active: boolean; blocked: boolean
  onHome: () => void; onSurvey: () => void; onNew: () => void
  onHistory?: () => void; onDeleted?: (id: string) => void
}) {
  const [chat, setChat] = useState<Conversation | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const pending = useRef<Message | null>(null)
  const alive = useRef(true)
  const sending = useRef(false)
  const refreshOnReturn = useRef(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const savedId = saved?.id
  const lastMessage = chat?.pending ? chat.messages.at(-1) : undefined
  const previousMessage = lastMessage?.client_message_id && pending.current &&
    lastMessage.client_message_id !== pending.current.client_message_id ? lastMessage : undefined
  const waitingForReply = chat?.pending && !chat.retryable

  function accept(value: Conversation) {
    setChat(value)
    const last = value.messages.at(-1)
    if (pending.current && value.messages.some((message) => message.client_message_id === pending.current?.client_message_id
      && message.text === pending.current?.text && (!value.pending || message !== last))) {
      pending.current = null
      setDraft('')
    }
    if (value.pending && !pending.current && last?.role === 'user' && last.client_message_id) {
      pending.current = { text: last.text, client_message_id: last.client_message_id }
      setDraft(last.text)
    }
  }
  useEffect(() => {
    alive.current = true
    const controller = new AbortController()
    setBusy(true); setError('')
    const load = savedId ? client.get(savedId, controller.signal) : client.open(questionnaireId, controller.signal)
    load.then(
      (value) => { if (alive.current && !controller.signal.aborted) accept(value) },
      (cause) => { if (alive.current && !controller.signal.aborted) setError(
        errorText(cause, 'Не удалось открыть чат. Повторите открытие.'),
      ) },
    ).finally(() => { if (alive.current && !controller.signal.aborted) setBusy(false) })
    return () => { alive.current = false; controller.abort() }
  }, [client, questionnaireId, savedId, attempt])
  useEffect(() => { if (active) heading.current?.focus() }, [active])
  useEffect(() => {
    if (!active) { refreshOnReturn.current = true; return }
    if (!chat?.id || !refreshOnReturn.current) return
    refreshOnReturn.current = false
    const controller = new AbortController()
    client.get(chat.id, controller.signal).then(
      (value) => { if (!controller.signal.aborted) accept(value) },
      (cause) => { if (!controller.signal.aborted) { if (cause instanceof ApiError && cause.status === 404) setChat(null); setError(errorText(cause)) } },
    )
    return () => controller.abort()
  }, [active, chat?.id, client])
  useEffect(() => { if (active) bottom.current?.scrollIntoView({ block: 'nearest' }) }, [chat?.messages.length, active])
  useEffect(() => {
    if (!active || !chat?.pending || chat.retryable || busy || deleting) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      client.get(chat.id, controller.signal).then(
        (value) => { if (alive.current && !controller.signal.aborted) accept(value) },
        (cause) => {
          if (!alive.current || controller.signal.aborted) return
          if (cause instanceof ApiError && cause.status === 404) { setChat(null); setError(errorText(cause)) }
          else setError('Не удалось обновить переписку. Нажмите «Обновить чат».')
        },
      )
    }, 1500)
    return () => { clearTimeout(timer); controller.abort() }
  }, [chat, active, busy, deleting, client])

  async function send(event?: FormEvent) {
    event?.preventDefault()
    if (!chat || sending.current || busy || deleting || blocked || chat.emergency || waitingForReply) return
    const message = previousMessage
      ? { text: previousMessage.text, client_message_id: previousMessage.client_message_id! }
      : pending.current || { text: draft.trim(), client_message_id: crypto.randomUUID() }
    if (!message.text) return
    if (!previousMessage) pending.current = message
    sending.current = true; setBusy(true); setError('')
    try {
      const value = await client.send(chat.id, message)
      if (alive.current) accept(value)
    } catch (cause) {
      if (alive.current) {
        if (cause instanceof ApiError && (cause.status === 400 || cause.status === 422 || cause.code === 'idempotency_conflict')) {
          if (!previousMessage) pending.current = null
          setError(errorText(cause, 'Сообщение не принято. Проверьте текст и отправьте снова.'))
          return
        }
        setError(errorText(cause, 'Не удалось проверить, сохранилось ли сообщение. Обновите чат или повторите отправку.'))
        try {
          const current = await client.get(chat.id)
          if (alive.current) {
            accept(current)
            const savedMessage = current.messages.some((row) => row.client_message_id === message.client_message_id && row.text === message.text)
            const surveyBlockedReply = cause instanceof ApiError &&
              (cause.code === 'questionnaire_in_progress' || cause.code === 'questionnaire_changed')
            setError(savedMessage && !surveyBlockedReply ? '' :
              errorText(cause, 'Сообщение не найдено в переписке. Нажмите «Повторить отправку».'))
          }
        } catch (failure) {
          if (alive.current && failure instanceof ApiError && failure.status === 404) {
            setChat(null); setError(errorText(failure))
          }
        }
      }
    } finally {
      sending.current = false
      if (alive.current) setBusy(false)
    }
  }
  async function refresh() {
    if (!chat || busy) return
    setBusy(true); setError('')
    try {
      const value = await client.get(chat.id)
      accept(value)
      if (!value.pending && pending.current) setError('Сообщение не найдено в переписке. Нажмите «Повторить отправку».')
    }
    catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) setChat(null)
      setError(errorText(cause))
    }
    finally { setBusy(false) }
  }
  async function remove() {
    if (!chat || deleting) return
    setDeleting(true); setError('')
    try {
      await client.delete(chat.id)
      if (alive.current) {
        setConfirmDelete(false)
        if (onDeleted) onDeleted(chat.id)
        else onNew()
      }
    } catch {
      if (alive.current) { setConfirmDelete(false); setError('Не удалось удалить чат. Повторите попытку.') }
    } finally {
      if (alive.current) setDeleting(false)
    }
  }

  return <div className="chat-page">
    <div className="form-actions">
      <Button icon="home" variant="secondary" onClick={onHome}>На главную</Button>
      {onHistory && <Button icon="chat" variant="secondary" onClick={onHistory}>История чатов</Button>}
      {questionnaireId && <Button icon="clipboard" variant="secondary" disabled={busy} onClick={onSurvey}>К результату опроса</Button>}
    </div>
    <header className="chat-heading">
      <img src={medvedUrl} width={48} height={48} alt="" />
      <div><h1 ref={heading} tabIndex={-1}>Чат с МедВедом</h1>
        {saved ? <p>{saved.kind === 'questionnaire' ? 'Чат по опросу' : 'Отдельный чат'} · <time dateTime={saved.created_at}>{new Date(saved.created_at).toLocaleDateString('ru-RU')}</time></p>
          : <p>Помогу уточнить вопрос и подготовиться к обращению к врачу.</p>}
      </div>
    </header>
    {blocked && <Card className="chat-blocked"><p>Пока идёт опрос, переписка приостановлена.</p><Button icon="clipboard" onClick={onSurvey}>Продолжить опрос</Button></Card>}
    {chat?.result && <details className="chat-context">
      <summary>Результат вашего опроса</summary>
      <p><strong>Специалист: </strong>{chat.result.specialty || 'Терапевт'}</p>
      <p>{chat.result.rationale}</p>
      <p className="field-hint">МедВед учитывает ваши ответы и результат этого опроса.</p>
    </details>}
    {chat && <div className="chat-log" tabIndex={0} role="log" aria-label="Переписка с МедВедом" aria-live="polite" aria-relevant="additions">
      <ol className="chat-messages">{chat.messages.map((message) => <li className={'chat-message chat-message--' + message.role} key={message.id}>
        <p className="chat-author">{message.role === 'user' ? 'Вы' : 'МедВед'}</p>
        <p className="chat-text">{message.text}</p>
      </li>)}</ol><div ref={bottom} />
    </div>}
    {chat?.emergency && <Card className="emergency-card" role="alert">
      <h2>Не откладывайте обращение за помощью</h2>
      <p>Позвоните 103/112. Не ждите продолжения переписки.</p>
      <div className="emergency-actions"><a className="button button--primary" href="tel:103">Позвонить 103</a><a className="button button--secondary" href="tel:112">Позвонить 112</a></div>
    </Card>}
    {busy && <p className="survey-loading" role="status">
      {!chat ? 'Открываем чат…' : sending.current ? 'Отправляем сообщение…' : 'Обновляем переписку…'}
    </p>}
    {!busy && !error && chat?.pending && <p className="survey-loading" role="status">
      {previousMessage ? chat.retryable ? 'Повторите отправку предыдущего сообщения, чтобы продолжить.'
        : 'Предыдущее сообщение сохранено. МедВед готовит ответ…'
        : chat.retryable ? 'Сообщение сохранено, но ответ не получен. Нажмите «Повторить отправку».'
          : 'Сообщение сохранено. МедВед готовит ответ…'}
    </p>}
    {error && <div className="survey-error" role="alert"><p>{error}</p></div>}
    {!chat && !busy && <Button icon="restart" onClick={() => setAttempt((value) => value + 1)}>Повторить открытие</Button>}
    {chat && !chat.emergency && <form className="chat-composer" onSubmit={(event) => { void send(event) }}>
      <label htmlFor="chat-message">Ваше сообщение</label>
      <textarea id="chat-message" maxLength={2000} rows={3} value={draft} disabled={busy || blocked || waitingForReply}
        readOnly={!!pending.current} onChange={(event) => setDraft(event.target.value)}
        placeholder="Что вы хотите уточнить?"
        onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} />
      <p className="field-hint">До 2000 символов. Не указывайте имя, телефон, адрес и данные документов.</p>
      <div className="form-actions">
        <Button icon="arrow-right" type="submit" disabled={busy || blocked || !draft.trim() || waitingForReply}>
          {previousMessage ? 'Повторить предыдущее сообщение' : pending.current ? 'Повторить отправку' : 'Отправить'}
        </Button>
        {(error || chat.pending) && <Button icon="restart" variant="secondary" disabled={busy} onClick={() => { void refresh() }}>Обновить чат</Button>}
      </div>
    </form>}
    {chat && <div className="chat-actions">
      <Button icon="restart" variant="secondary" disabled={busy || blocked} onClick={onNew}>Новый чат</Button>
      <Button variant="secondary" onClick={() => setConfirmDelete(true)}>Удалить чат</Button>
    </div>}
    <DeleteChatDialog open={confirmDelete} kind={chat?.questionnaire_id ? 'questionnaire' : 'chat'} busy={deleting}
      onCancel={() => setConfirmDelete(false)} onDelete={() => { void remove() }} />
  </div>
}
