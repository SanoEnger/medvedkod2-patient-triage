import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError } from '../../api/client'
import type { ChatClient, Conversation } from '../../api/chat'
import { Button, Card } from '../../components/ui'
import medvedUrl from '../../assets/medved-bear-button.svg?url'

type Message = { text: string; client_message_id: string }
function errorText(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 409) return 'Сейчас чат недоступен. Завершите или удалите текущий опрос, затем вернитесь в чат.'
    if (error.status === 401 || error.status === 403) return 'Доступ истёк. Откройте приложение заново.'
    if (error.status === 404) return 'Чат удалён или срок его хранения истёк. Начните новый чат.'
    if (error.status === 429) return 'Слишком много сообщений. Подождите немного и повторите.'
  }
  return 'МедВед пока не смог ответить. Ваше сообщение сохранено для повторной отправки.'
}

export function ChatPage({ client, questionnaireId, active, blocked, onHome, onSurvey, onNew }: {
  client: ChatClient; questionnaireId?: string; active: boolean; blocked: boolean
  onHome: () => void; onSurvey: () => void; onNew: () => void
}) {
  const [chat, setChat] = useState<Conversation | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const pending = useRef<Message | null>(null)
  const alive = useRef(true)
  const sending = useRef(false)
  const refreshOnReturn = useRef(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const dialog = useRef<HTMLDialogElement>(null)

  function accept(value: Conversation) {
    setChat(value)
    if (!value.pending) {
      if (pending.current && value.messages.some((message) => message.client_message_id === pending.current?.client_message_id)) { pending.current = null; setDraft('') }
    }
    else {
      const last = value.messages.at(-1)
      if (last?.role === 'user' && last.client_message_id) {
        pending.current = { text: last.text, client_message_id: last.client_message_id }
        setDraft(last.text)
      }
    }
  }
  useEffect(() => {
    alive.current = true
    const controller = new AbortController()
    setBusy(true); setError('')
    client.open(questionnaireId, controller.signal).then(
      (value) => { if (alive.current && !controller.signal.aborted) accept(value) },
      () => { if (alive.current && !controller.signal.aborted) setError('Не удалось открыть чат. Повторите попытку или вернитесь к опросу.') },
    ).finally(() => { if (alive.current && !controller.signal.aborted) setBusy(false) })
    return () => { alive.current = false; controller.abort() }
  }, [client, questionnaireId, attempt])
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
    if (confirmDelete) dialog.current?.showModal()
    else dialog.current?.close()
  }, [confirmDelete])
  useEffect(() => {
    if (!chat?.pending || chat.retryable || busy || blocked) return
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      client.get(chat.id, controller.signal).then(
        (value) => { if (alive.current && !controller.signal.aborted) accept(value) },
        () => { if (alive.current && !controller.signal.aborted) setError('Не удалось обновить переписку. Нажмите «Обновить чат».') },
      )
    }, 1500)
    return () => { clearTimeout(timer); controller.abort() }
  }, [chat, busy, blocked, client])

  async function send(event?: FormEvent) {
    event?.preventDefault()
    if (!chat || sending.current || busy || blocked || chat.emergency || (chat.pending && !chat.retryable)) return
    const message = pending.current || { text: draft.trim(), client_message_id: crypto.randomUUID() }
    if (!message.text) return
    pending.current = message
    sending.current = true; setBusy(true); setError('')
    try {
      const value = await client.send(chat.id, message)
      if (alive.current) accept(value)
    } catch (cause) {
      if (alive.current) {
        setError(errorText(cause))
        try {
          const current = await client.get(chat.id)
          if (alive.current) { accept(current); if (!current.pending && !pending.current) setError('') }
        } catch { /* Keep the immutable message for retry. */ }
      }
    } finally {
      sending.current = false
      if (alive.current) setBusy(false)
    }
  }
  async function refresh() {
    if (!chat || busy) return
    setBusy(true); setError('')
    try { accept(await client.get(chat.id)) }
    catch (cause) { setError(errorText(cause)) }
    finally { setBusy(false) }
  }
  async function remove() {
    if (!chat || busy) return
    setBusy(true); setError('')
    try { await client.delete(chat.id); setConfirmDelete(false); onNew() }
    catch (cause) { setError(errorText(cause)) }
    finally { setBusy(false) }
  }

  return <div className="chat-page">
    <div className="form-actions">
      <Button icon="home" variant="secondary" disabled={busy} onClick={onHome}>На главную</Button>
      {questionnaireId && <Button icon="clipboard" variant="secondary" disabled={busy} onClick={onSurvey}>К результату опроса</Button>}
    </div>
    <header className="chat-heading">
      <img src={medvedUrl} width={48} height={48} alt="" />
      <div><h1 ref={heading} tabIndex={-1}>Чат с МедВедом</h1><p>Помогу уточнить вопрос и подготовиться к обращению к врачу.</p></div>
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
    {(busy || (chat?.pending && !chat.retryable)) && <p className="survey-loading" role="status">{chat ? 'МедВед отвечает…' : 'Открываем чат…'}</p>}
    {error && <div className="survey-error" role="alert"><p>{error}</p></div>}
    {!chat && !busy && <Button icon="restart" onClick={() => setAttempt((value) => value + 1)}>Повторить открытие</Button>}
    {chat && !chat.emergency && <form className="chat-composer" onSubmit={(event) => { void send(event) }}>
      <label htmlFor="chat-message">Ваше сообщение</label>
      <textarea id="chat-message" maxLength={2000} rows={3} value={draft} disabled={busy || blocked || (chat.pending && !chat.retryable)}
        readOnly={!!pending.current} onChange={(event) => setDraft(event.target.value)}
        placeholder="Что вы хотите уточнить?"
        onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send() } }} />
      <p className="field-hint">До 2000 символов. Не указывайте имя, телефон, адрес и данные документов.</p>
      <div className="form-actions">
        <Button icon="arrow-right" type="submit" disabled={busy || blocked || !draft.trim() || (chat.pending && !chat.retryable)}>
          {pending.current ? 'Повторить отправку' : 'Отправить'}
        </Button>
        {error && <Button icon="restart" variant="secondary" disabled={busy} onClick={() => { void refresh() }}>Обновить чат</Button>}
      </div>
    </form>}
    {chat && <div className="chat-actions">
      <Button icon="restart" variant="secondary" disabled={busy || blocked} onClick={onNew}>Новый чат</Button>
      {!chat.questionnaire_id && <Button variant="secondary" disabled={busy} onClick={() => setConfirmDelete(true)}>Удалить чат</Button>}
    </div>}
    <dialog className="delete-dialog" ref={dialog} aria-labelledby="delete-chat-title" onCancel={() => setConfirmDelete(false)} onClose={() => setConfirmDelete(false)}>
      <h2 id="delete-chat-title">Удалить этот чат?</h2><p>Переписка будет удалена.</p>
      <div className="form-actions"><Button variant="secondary" autoFocus disabled={busy} onClick={() => setConfirmDelete(false)}>Отмена</Button><Button disabled={busy} onClick={() => { void remove() }}>Удалить</Button></div>
    </dialog>
  </div>
}
