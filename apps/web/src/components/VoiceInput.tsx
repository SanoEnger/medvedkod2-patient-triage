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
type CaptureStage = 'max' | 'microphone' | 'recorder' | 'start' | 'recording'
type MaxPermissions = {
  isInited: boolean
  isMicAppAccessGranted?: boolean
  init: () => Promise<unknown>
  requestAccess: (permission: 'mic', reason: string) => Promise<unknown>
}
function maxPermissions() {
  return (window as Window & { WebApp?: { PermissionsManager?: MaxPermissions } }).WebApp?.PermissionsManager
}
type CaptureFailure = { stage: CaptureStage; code: string; policy: boolean | null; embedded: boolean; secure: boolean }
const captureStages: Record<CaptureStage, string> = {
  max: 'разрешение mini-app в MAX',
  microphone: 'доступ к микрофону', recorder: 'создание записи', start: 'запуск записи', recording: 'запись звука',
}

function captureFailure(cause: unknown, stage: CaptureStage): CaptureFailure {
  const page = document as Document & {
    permissionsPolicy?: { allowsFeature: (feature: string) => boolean }
    featurePolicy?: { allowsFeature: (feature: string) => boolean }
  }
  const name = typeof cause === 'object' && cause !== null && 'name' in cause && typeof cause.name === 'string' ? cause.name : ''
  let code = ['NotAllowedError', 'SecurityError', 'NotFoundError', 'NotReadableError', 'NotSupportedError', 'InvalidStateError', 'AbortError', 'OverconstrainedError'].includes(name) ? name : 'UnknownError'
  if (stage === 'max') {
    const error = cause as { error?: { code?: unknown } } | null
    const sdkCode = error?.error?.code
    code = name === 'NotAllowedError' || typeof sdkCode === 'string' && /\.(mic_app_permission_denied|app_permission_denied)$/.test(sdkCode) ? 'MAX_APP_DENIED'
      : typeof sdkCode === 'string' && /\.(mic_system_permission_denied|system_permission_denied)$/.test(sdkCode) ? 'MAX_SYSTEM_DENIED'
      : typeof sdkCode === 'string' && sdkCode.endsWith('.mic_not_supported') ? 'MAX_MIC_UNAVAILABLE'
      : 'MAX_PERMISSION_REQUEST_FAILED'
  }
  return { stage, code, policy: (page.permissionsPolicy || page.featurePolicy)?.allowsFeature('microphone') ?? null,
    embedded: window.top !== window, secure: window.isSecureContext === true }
}

function captureMessage(failure: CaptureFailure) {
  if (failure.stage === 'max') {
    if (failure.code === 'MAX_APP_DENIED') return 'Разрешите микрофон этому mini-app в настройках MAX и откройте его заново.'
    if (failure.code === 'MAX_SYSTEM_DENIED') return 'Разрешите MAX доступ к микрофону в настройках устройства или браузера.'
    if (failure.code === 'MAX_MIC_UNAVAILABLE') return 'MAX не обнаружил доступный микрофон.'
    return 'Не удалось получить разрешение микрофона через MAX. Повторно откройте mini-app и попробуйте ещё раз.'
  }
  if (failure.stage !== 'microphone') return 'Браузер получил микрофон, но не смог запустить или продолжить запись звука. Попробуйте другой браузер.'
  if (failure.policy === false) return 'Доступ к микрофону запрещён настройками страницы mini-app. Изменение разрешения в браузере не снимает этот запрет.'
  if (failure.code === 'NotAllowedError' || failure.code === 'SecurityError') return 'Доступ к микрофону не разрешён. Проверьте разрешение для сайта или MAX в браузере и настройках устройства.'
  if (failure.code === 'NotFoundError') return 'Микрофон не найден. Подключите его и попробуйте ещё раз.'
  if (failure.code === 'NotReadableError') return 'Не удалось открыть микрофон. Проверьте, не занят ли он другим приложением и разрешён ли доступ в настройках устройства.'
  return 'Не удалось включить микрофон. Откройте технические сведения, чтобы уточнить причину.'
}

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
  const [failure, setFailure] = useState<CaptureFailure | null>(null)
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
    setFailure(null)
    setState('starting')

    function finish(message = '') {
      if (signal.aborted) return
      cancel(recording)
      current.current = null
      setState('idle')
      setError(message)
    }

    function failCapture(cause: unknown, stage: CaptureStage) {
      if (signal.aborted) return
      const diagnostic = captureFailure(cause, stage)
      setFailure(diagnostic)
      finish(captureMessage(diagnostic))
    }

    let stage: CaptureStage = 'microphone'
    try {
      const permissions = maxPermissions()
      if (permissions) {
        stage = 'max'
        if (!permissions.isInited) await permissions.init()
        if (signal.aborted) return
        await permissions.requestAccess('mic', 'Голосовой ввод ответа в анкете или чате МедВеда')
        if (signal.aborted) return
        if (permissions.isMicAppAccessGranted === false) {
          throw new DOMException('', 'NotAllowedError')
        }
      }
      stage = 'microphone'
      recording.stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (signal.aborted) { release(recording); return }

      stage = 'recorder'
      const recorder = new MediaRecorder(recording.stream, { mimeType, audioBitsPerSecond: 64000 })
      recording.recorder = recorder
      const chunks: Blob[] = []
      recorder.ondataavailable = ({ data }) => { if (data.size) chunks.push(data) }
      recorder.onerror = (event) => failCapture('error' in event ? event.error : event, 'recording')
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
      stage = 'start'
      recorder.start()
      setState('recording')
      recording.timer = window.setTimeout(stop, 30000)
    } catch (cause) {
      failCapture(cause, stage)
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
    {failure && <details className="field-hint">
      <summary>Технические сведения о микрофоне</summary>
      <p>Этап: {captureStages[failure.stage]}. Код: {failure.code}.
        Политика страницы: {failure.policy === null ? 'не определена' : failure.policy ? 'разрешает микрофон' : 'запрещает микрофон'}.
        Вложенное окно: {failure.embedded ? 'да' : 'нет'}. Защищённый контекст: {failure.secure ? 'да' : 'нет'}.</p>
    </details>}
  </>
}
