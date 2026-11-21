import { useEffect, useRef } from 'react'
import { Button } from '../../components/ui'

export function DeleteChatDialog({ open, questionnaire, busy, onCancel, onDelete }: {
  open: boolean; questionnaire: boolean; busy: boolean; onCancel: () => void; onDelete: () => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    if (open) dialog.current?.showModal()
    else dialog.current?.close()
  }, [open])

  return <dialog className="delete-dialog" ref={dialog} aria-label="Удалить этот чат?"
    onClose={onCancel} onCancel={(event) => { event.preventDefault(); if (!busy) onCancel() }}>
    <h2>Удалить этот чат?</h2>
    <p>{questionnaire ? 'Будут удалены переписка, ответы и результат опроса.' : 'Переписка будет удалена.'}</p>
    <div className="form-actions">
      <Button variant="secondary" autoFocus disabled={busy} onClick={onCancel}>Отмена</Button>
      <Button disabled={busy} onClick={onDelete}>Удалить</Button>
    </div>
  </dialog>
}
