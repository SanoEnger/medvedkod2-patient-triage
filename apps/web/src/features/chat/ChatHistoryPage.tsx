import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import type { MedvedClient } from '../../api/client'
import type { ChatHistoryQuery, ChatKind, ChatSummary } from '../../api/chat'
import { Button, Card } from '../../components/ui'
import { DeleteChatDialog } from './DeleteChatDialog'

const dateTime = new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
const historyKinds: Record<ChatSummary['kind'], string> = {
  chat: 'Чат с МедВедом',
  questionnaire: 'Уточнение по опросу',
  questionnaire_result: 'Результат опроса',
}
const filters: { kind?: ChatKind; label: string }[] = [
  { label: 'Все' },
  { kind: 'questionnaire_result', label: 'Результаты опросов' },
  { kind: 'questionnaire', label: 'Уточнения' },
  { kind: 'chat', label: 'Чаты' },
]

export function ChatHistoryPage({ client, filter, onFilterChange, onHome, onOpen, onDeleted }: {
  client: MedvedClient; onHome: () => void; onOpen: (chat: ChatSummary) => void; onDeleted: (id: string) => void
  filter?: ChatKind; onFilterChange: (kind?: ChatKind) => void
}) {
  const [items, setItems] = useState<ChatSummary[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [request, setRequest] = useState<ChatHistoryQuery | null>({ kind: filter })
  const [retry, setRetry] = useState<ChatHistoryQuery | null>(null)
  const [error, setError] = useState('')
  const [selection, setSelection] = useState<ChatSummary | null>(null)
  const [deleting, setDeleting] = useState(false)
  const deletion = useRef<AbortController | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    if (!request) return
    const controller = new AbortController()
    client.chat.list(request, controller.signal).then(({ items: page, next_cursor }) => {
      if (controller.signal.aborted) return
      setItems((previous) => request.cursor ? [...previous, ...page] : page)
      setNext(next_cursor)
    }, (cause) => {
      if (controller.signal.aborted) return
      setRetry(request)
      setError(cause instanceof ApiError && cause.status === 401
        ? 'Вход истёк. Снова откройте приложение в MAX.'
        : 'Не удалось загрузить историю чатов. Повторите загрузку.')
    }).finally(() => { if (!controller.signal.aborted) setRequest(null) })
    return () => controller.abort()
  }, [client, request])

  useEffect(() => {
    heading.current?.focus()
    return () => deletion.current?.abort()
  }, [])

  function load(page: ChatHistoryQuery) {
    setError('')
    setRetry(null)
    setRequest(page)
  }

  async function remove() {
    if (!selection || deletion.current) return
    const controller = new AbortController()
    deletion.current = controller
    setDeleting(true)
    setError('')
    try {
      if (selection.kind === 'questionnaire_result') await client.delete(selection.id, controller.signal)
      else await client.chat.delete(selection.id, controller.signal)
      if (controller.signal.aborted) return
      setItems((previous) => previous.filter(({ id }) => id !== selection.id))
      onDeleted(selection.id)
      heading.current?.focus()
    } catch {
      if (!controller.signal.aborted) setError('Не удалось удалить обращение. Обновите историю или повторите удаление.')
    } finally {
      if (!controller.signal.aborted) {
        deletion.current = null
        setDeleting(false)
        setSelection(null)
      }
    }
  }

  return <div className="chat-page">
    <Button icon="home" variant="secondary" onClick={onHome}>На главную</Button>
    <header className="chat-heading"><h1 ref={heading} tabIndex={-1}>История чатов</h1></header>
    <div className="form-actions chat-history-filters" role="group" aria-label="Тип записи">
      {filters.map(({ kind, label }) => <Button key={label} variant={kind === filter ? 'primary' : 'secondary'}
        aria-pressed={kind === filter} onClick={() => {
          if (kind === filter) return
          onFilterChange(kind)
          setItems([])
          setNext(null)
          load({ kind })
        }}>{label}</Button>)}
    </div>
    {items.length > 0 && <ul className="chat-history">{items.map((chat) => {
      const type = historyKinds[chat.kind]
      const createdAt = dateTime.format(new Date(chat.created_at))
      const name = `${chat.title}, ${type}, ${createdAt}`
      const resultOnly = chat.kind === 'questionnaire_result'
      return <li key={chat.id}>
        <Card>
          <h2>{chat.title}</h2>
          <p>{type} · <time dateTime={chat.created_at}>{createdAt}</time></p>
          <p>Последняя активность <time dateTime={chat.last_activity_at}>{dateTime.format(new Date(chat.last_activity_at))}</time></p>
          <p>Хранится до <time dateTime={chat.expires_at}>{dateTime.format(new Date(chat.expires_at))}</time></p>
          {chat.emergency && <p>Экстренная остановка. Только чтение.</p>}
          <div className="form-actions">
            <Button onClick={() => onOpen(chat)} aria-label={`Открыть: ${name}`}>{resultOnly ? 'Открыть результат' : 'Открыть чат'}</Button>
            <Button variant="secondary" onClick={() => setSelection(chat)} aria-label={`Удалить: ${name}`}>{resultOnly ? 'Удалить опрос' : 'Удалить чат'}</Button>
          </div>
        </Card>
      </li>
    })}</ul>}
    {request && <p className="survey-loading" role="status">Загружаем историю…</p>}
    {error && <div className="survey-error" role="alert"><p>{error}</p></div>}
    {!request && !error && !items.length && !next &&
      <Card><p>{filter ? 'Записей этого типа пока нет.' : 'Сохранённых чатов и результатов пока нет.'}</p></Card>}
    {retry && <Button icon="restart" variant="secondary" onClick={() => load(retry)}>Повторить загрузку</Button>}
    {!request && !retry && next && <Button variant="secondary" onClick={() => load({ kind: filter, cursor: next })}>Показать ещё</Button>}
    {!request && error && !retry && <Button icon="restart" variant="secondary" onClick={() => load({ kind: filter })}>Обновить историю</Button>}
    <DeleteChatDialog open={!!selection} kind={selection?.kind ?? 'chat'} busy={deleting}
      onCancel={() => setSelection(null)} onDelete={() => { void remove() }} />
  </div>
}
