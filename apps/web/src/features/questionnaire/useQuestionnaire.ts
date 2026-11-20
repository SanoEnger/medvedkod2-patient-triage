import { useEffect, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import { isEmergency } from '../../api/contracts'
import type { AnswerRequest, Survey, SurveyClient } from '../../api/contracts'

type Operation = {
  kind: 'create' | 'answer' | 'back' | 'refresh' | 'triage' | 'delete'
  execute: (signal: AbortSignal, emit: (survey: Survey) => void) => Promise<Survey | undefined>
}

export function useQuestionnaire(client: SurveyClient, initial?: Survey | null) {
  const [survey, setSurvey] = useState<Survey | null>(initial || null)
  const [error, setError] = useState<ApiError | null>(null)
  const [activity, setActivity] = useState<Operation['kind'] | null>(null)
  const [emergency, setEmergency] = useState(!!initial && isEmergency(initial))
  const current = useRef<Survey | null>(initial || null)
  const stopped = useRef(!!initial && isEmergency(initial))
  const epoch = useRef(0)
  const busy = useRef(false)
  const abort = useRef<AbortController | null>(null)
  const failed = useRef<Operation | null>(null)

  useEffect(() => () => { epoch.current++; abort.current?.abort() }, [client])

  function emit(next: Survey) {
    if (stopped.current && !isEmergency(next)) return
    if (isEmergency(next)) {
      stopped.current = true
      setEmergency(true)
    }
    current.current = next
    setSurvey(next)
    if (next.status === 'EXPIRED' && !stopped.current) setError(new ApiError(404))
  }

  async function run(operation: Operation): Promise<boolean> {
    if (busy.current) return false
    busy.current = true
    const generation = epoch.current
    const controller = new AbortController()
    abort.current = controller
    setActivity(operation.kind)
    setError(null)
    try {
      const next = await operation.execute(controller.signal, (value) => {
        if (epoch.current === generation) emit(value)
      })
      if (epoch.current !== generation) return false
      if (next) emit(next)
      failed.current = null
      return true
    } catch (cause) {
      if (epoch.current !== generation) return false
      const failure = cause instanceof ApiError ? cause : new ApiError()
      if (failure.emergency) {
        stopped.current = true
        setEmergency(true)
      }
      failed.current = operation
      setError(failure)
      return false
    } finally {
      if (epoch.current === generation) {
        busy.current = false
        abort.current = null
        setActivity(null)
      }
    }
  }

  function reset() {
    epoch.current++
    abort.current?.abort()
    abort.current = null
    busy.current = stopped.current = false
    current.current = null
    failed.current = null
    setSurvey(null)
    setEmergency(false)
    setError(null)
    setActivity(null)
  }

  function answer(body: Omit<AnswerRequest, 'idempotency_key'>) {
    if (!current.current || stopped.current) return Promise.resolve(false)
    const id = current.current.id
    const snapshot = structuredClone({ ...body, idempotency_key: crypto.randomUUID() }) as AnswerRequest
    return run({ kind: 'answer', execute: (signal) => client.answer(id, snapshot, signal) })
  }
  function back(target: number) {
    if (!current.current || stopped.current) return Promise.resolve(false)
    const id = current.current.id
    return run({ kind: 'back', execute: (signal) => client.back(id, target, signal) })
  }
  function refresh() {
    if (!current.current) return Promise.resolve(false)
    const id = current.current.id
    return run({ kind: 'refresh', execute: (signal) => client.get(id, signal) })
  }
  function triage() {
    if (!current.current || stopped.current) return Promise.resolve(false)
    const id = current.current.id
    return run({
      kind: 'triage',
      async execute(signal, update) {
        const result = await client.triage(id, signal)
        if (current.current?.id === id) update({ ...current.current, result, urgency: result.urgency })
        return client.get(id, signal)
      },
    })
  }
  async function remove() {
    if (!current.current) return false
    const id = current.current.id
    const removed = await run({ kind: 'delete', execute: async (signal) => { await client.delete(id, signal); return undefined } })
    if (removed) reset()
    return removed
  }
  const canRetry = !!error && !!failed.current && ![400, 401, 403, 404, 409, 413, 422].includes(error.status)
  return {
    survey, emergency, error, activity, busy: activity !== null,
    uncertainAnswer: !!error && failed.current?.kind === 'answer' && (error.status === 0 || error.status >= 500),
    canRetry, failedKind: failed.current?.kind, reset, answer, back, refresh, triage, remove,
    start: () => run({ kind: 'create', execute: (signal) => client.create(signal) }),
    retry: () => failed.current ? run(failed.current) : Promise.resolve(false),
  }
}
