import { useEffect, useRef } from 'react'
import type { ChatSummary } from '../../api/chat'
import { Button } from '../../components/ui'

export function DeleteChatDialog({ open, kind, busy, onCancel, onDelete }: {
  open: boolean; kind: ChatSummary['kind']; busy: boolean; onCancel: () => void; onDelete: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (open) dialog.current?.showModal()
    else dialog.current?.close()
  }, [open])

  const title = kind === 'questionnaire_result' ? 'Удалить этот опрос?' : 'Удалить этот чат?'
  return <dialog className="delete-dialog" ref={dialog} aria-label={title}
    onClose={onCancel} onCancel={(event) => { event.preventDefault(); if (!busy) onCancel() }}>
    <h2>{title}</h2>
    <p>{kind === 'questionnaire_result' ? 'Будут удалены ответы и результат опроса.'
      : kind === 'questionnaire' ? 'Будут удалены переписка, ответы и результат опроса.' : 'Переписка будет удалена.'}</p>
    <div className="form-actions">
      <Button variant="secondary" autoFocus disabled={busy} onClick={onCancel}>Отмена</Button>
      <Button disabled={busy} onClick={onDelete}>Удалить</Button>
    </div>
  </dialog>
}
