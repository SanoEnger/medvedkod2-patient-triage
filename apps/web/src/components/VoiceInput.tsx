import { useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import type { TranscribeAudio } from '../api/client'

type Recording = { controller: AbortController; stream?: MediaStream; recorder?: MediaRecorder; timer?: number }
type VoiceState = 'idle' | 'starting' | 'recording' | 'transcribing'
export type VoiceOptions = {
  value: string; onChange: (value: string) => void; maxLength: number
  transcribe?: TranscribeAudio; disabled?: boolean; separator?: string
}
type VoiceProps = VoiceOptions & { label: string }
const mimeTypes = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']

function release(recording: Recording) {
  window.clearTimeout(recording.timer)
  recording.stream?.getTracks().forEach((track) => track.stop())
  recording.stream = undefined
}

function cancel(recording: Recording) {
  recording.controller.abort()
  if (recording.recorder?.state === 'recording') recording.recorder.stop()
  release(recording)
}

export function VoiceInput({ children, ...props }: VoiceProps & { children: ReactNode }) {
  const supported = typeof MediaRecorder !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
  const mimeType = supported ? mimeTypes.find((type) => MediaRecorder.isTypeSupported(type)) : undefined
  if (!props.transcribe || !mimeType) return <>{children}</>

  return <div className="voice-field">
    {children}
    <VoiceButton key={props.disabled ? 'disabled' : 'enabled'} {...props} transcribe={props.transcribe} mimeType={mimeType} />
  </div>
}

function VoiceButton({ label, value, onChange, maxLength, transcribe, disabled, separator = ' ', mimeType }:
  VoiceProps & { transcribe: TranscribeAudio; mimeType: string }) {
  const current = useRef<Recording | null>(null)
  const latest = useRef({ value, onChange })
  const [state, setState] = useState<VoiceState>('idle')
  const [error, setError] = useState('')
  useLayoutEffect(() => { latest.current = { value, onChange } }, [value, onChange])
  useLayoutEffect(() => () => { if (current.current) cancel(current.current) }, [])

  function stop() {
    const recorder = current.current?.recorder
    if (recorder?.state !== 'recording') return
    recorder.stop()
    setState('transcribing')
  }

  async function start() {
    if (current.current) return
    const recording: Recording = { controller: new AbortController() }
    const { signal } = recording.controller
    current.current = recording
    setError('')
    setState('starting')

    function finish(message = '') {
      if (signal.aborted) return
      cancel(recording)
      current.current = null
      setState('idle')
      setError(message)
    }

    try {
      recording.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (signal.aborted) { release(recording); return }

      const recorder = new MediaRecorder(recording.stream, { mimeType, audioBitsPerSecond: 64000 })
      recording.recorder = recorder
      const chunks: Blob[] = []
      recorder.ondataavailable = ({ data }) => { if (data.size) chunks.push(data) }
      recorder.onerror = () => finish('Не удалось записать звук. Попробуйте ещё раз.')
      recorder.onstop = async () => {
        release(recording)
        if (signal.aborted) return
        setState('transcribing')
        const audio = new Blob(chunks, { type: recorder.mimeType || mimeType })
        if (!audio.size) { finish('Запись пуста. Попробуйте ещё раз.'); return }
        try {
          const text = await transcribe(audio, signal)
          if (signal.aborted) return
          const { value: draft, onChange: change } = latest.current
          const prefix = draft && !/\s$/.test(draft) ? draft + separator : draft
          change((prefix + text).slice(0, maxLength))
          finish()
        } catch (cause) {
          const status = cause instanceof ApiError ? cause.status : 0
          finish(status === 422 ? 'Не удалось распознать речь. Попробуйте ещё раз.'
            : status === 503 ? 'Голосовой ввод сейчас недоступен. Ответ можно ввести вручную.'
            : 'Не удалось обработать запись. Попробуйте ещё раз.')
        }
      }
      recorder.start()
      setState('recording')
      recording.timer = window.setTimeout(stop, 30000)
    } catch {
      finish('Не удалось включить микрофон. Проверьте разрешение на запись.')
    }
  }

  const recording = state === 'recording'
  const action = recording ? 'Остановить запись' : 'Начать голосовой ввод'
  return <>
    <button type="button" className="voice-button" aria-label="Голосовой ввод" aria-description={label} aria-pressed={recording}
      title={action} disabled={disabled || state === 'starting' || state === 'transcribing' || (!recording && value.length >= maxLength)}
      onClick={() => { if (recording) stop(); else void start() }} />
    {state !== 'idle' && <p className="field-hint" role="status">{
      recording ? 'Идёт запись. Нажмите на микрофон, чтобы остановить.' : state === 'starting' ? 'Включаем микрофон…' : 'Распознаём речь…'
    }</p>}
    {error && <p className="field-error" role="alert">{error}</p>}
  </>
}
