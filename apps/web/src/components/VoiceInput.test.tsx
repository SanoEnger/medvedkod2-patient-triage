import { useState } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { VoiceInput } from './VoiceInput'

class Recorder {
  static isTypeSupported = () => true
  mimeType = 'audio/webm;codecs=opus'
  state = 'inactive'
  ondataavailable?: (event: { data: Blob }) => void
  onstop?: () => void
  start() { this.state = 'recording' }
  stop() {
    this.state = 'inactive'
    queueMicrotask(() => {
      this.ondataavailable?.({ data: new Blob(['synthetic audio']) })
      this.onstop?.()
    })
  }
}

afterEach(() => { vi.unstubAllGlobals(); Reflect.deleteProperty(document, 'featurePolicy'); Reflect.deleteProperty(window, 'WebApp') })

test('recording state is pressed only during capture and transcript appends to the current draft', async () => {
  const stop = vi.fn()
  vi.stubGlobal('MediaRecorder', Recorder)
  vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop }] }) } })
  const transcribe = vi.fn(async () => 'голосом')
  function Field({ disabled = false }: { disabled?: boolean }) {
    const [value, setValue] = useState('Начало')
    return <VoiceInput label="Ответ" value={value} onChange={setValue} maxLength={120} transcribe={transcribe} disabled={disabled}>
      <textarea value={value} onChange={(event) => setValue(event.target.value)} />
    </VoiceInput>
  }

  const view = render(<Field />)
  const user = userEvent.setup()
  const microphone = () => screen.getByRole('button', { name: 'Голосовой ввод' })
  expect(microphone()).toHaveAttribute('aria-pressed', 'false')
  await user.click(microphone())
  expect(microphone()).toHaveAttribute('aria-pressed', 'true')
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Новый текст' } })
  await user.click(microphone())
  expect(screen.getByRole('textbox')).toHaveValue('Новый текст голосом')
  expect(microphone()).toHaveAttribute('aria-pressed', 'false')
  expect(transcribe).toHaveBeenCalledTimes(1)
  expect(stop).toHaveBeenCalledTimes(1)

  await user.click(microphone())
  expect(microphone()).toHaveAttribute('aria-pressed', 'true')
  view.rerender(<Field disabled />)
  await waitFor(() => expect(stop).toHaveBeenCalledTimes(2))
  expect(microphone()).toBeDisabled()
  expect(transcribe).toHaveBeenCalledTimes(1)
})

test.each([
  ['NotAllowedError', 'Доступ к микрофону не разрешён'],
  ['NotFoundError', 'Микрофон не найден'],
  ['NotReadableError', 'Не удалось открыть микрофон'],
])('capture failure %s is distinguished without exposing exception text', async (name, message) => {
  vi.stubGlobal('MediaRecorder', Recorder)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(new DOMException('private-message-and-token', name)) } })
  const transcribe = vi.fn()
  render(<VoiceInput label="Ответ" value="" onChange={vi.fn()} maxLength={100} transcribe={transcribe}><textarea /></VoiceInput>)
  await userEvent.click(screen.getByRole('button', { name: 'Голосовой ввод' }))
  expect(screen.getByRole('alert')).toHaveTextContent(message)
  expect(screen.getByText(/Этап:/)).toHaveTextContent('Этап: доступ к микрофону')
  expect(screen.getByText(/Этап:/)).toHaveTextContent('Код: ' + name)
  expect(document.body.textContent).not.toContain('private-message-and-token')
  expect(transcribe).not.toHaveBeenCalled()
})

test('an actual denied page policy is reported separately from user permission', async () => {
  Object.defineProperty(document, 'featurePolicy', { configurable: true, value: { allowsFeature: (feature: string) => feature !== 'microphone' } })
  vi.stubGlobal('MediaRecorder', Recorder)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(new DOMException('', 'NotAllowedError')) } })
  render(<VoiceInput label="Ответ" value="" onChange={vi.fn()} maxLength={100} transcribe={vi.fn()}><textarea /></VoiceInput>)
  await userEvent.click(screen.getByRole('button', { name: 'Голосовой ввод' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Доступ к микрофону запрещён настройками страницы mini-app')
  expect(screen.getByText(/Этап:/)).toHaveTextContent('Политика страницы: запрещает микрофон')
})

test.each(['constructor', 'start'])('a recorder %s failure releases the microphone and does not blame permission', async (stage) => {
  class BrokenRecorder extends Recorder {
    constructor() { super(); if (stage === 'constructor') throw new DOMException('', 'NotSupportedError') }
    start() { throw new DOMException('', 'NotSupportedError') }
  }
  const stop = vi.fn()
  const transcribe = vi.fn()
  vi.stubGlobal('MediaRecorder', BrokenRecorder)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] }) } })
  render(<VoiceInput label="Ответ" value="" onChange={vi.fn()} maxLength={100} transcribe={transcribe}><textarea /></VoiceInput>)
  const microphone = screen.getByRole('button', { name: 'Голосовой ввод' })
  await userEvent.click(microphone)
  expect(screen.getByRole('alert')).toHaveTextContent('Браузер получил микрофон')
  expect(screen.getByText(/Этап:/)).toHaveTextContent(stage === 'constructor' ? 'создание записи' : 'запуск записи')
  expect(microphone).toHaveAttribute('aria-pressed', 'false')
  expect(stop).toHaveBeenCalledOnce()
  expect(transcribe).not.toHaveBeenCalled()
})

test('a successful retry clears capture diagnostics', async () => {
  vi.stubGlobal('MediaRecorder', Recorder)
  const getUserMedia = vi.fn().mockRejectedValueOnce(new DOMException('', 'NotAllowedError'))
    .mockResolvedValue({ getTracks: () => [{ stop: vi.fn() }] })
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
  render(<VoiceInput label="Ответ" value="" onChange={vi.fn()} maxLength={100} transcribe={vi.fn()}><textarea /></VoiceInput>)
  const microphone = screen.getByRole('button', { name: 'Голосовой ввод' })
  await userEvent.click(microphone)
  expect(screen.getByRole('alert')).toBeVisible()
  await userEvent.click(microphone)
  expect(microphone).toHaveAttribute('aria-pressed', 'true')
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.queryByText('Технические сведения о микрофоне')).not.toBeInTheDocument()
})

test.each([false, true])('MAX permission precedes browser capture (already initialized: %s)', async (isInited) => {
  const order: string[] = []
  const permissions = {
    isInited, isMicAppAccessGranted: true,
    init: vi.fn(async () => { order.push('init') }),
    requestAccess: vi.fn(async () => { order.push('max') }),
  }
  Object.defineProperty(window, 'WebApp', { configurable: true, value: { PermissionsManager: permissions } })
  vi.stubGlobal('MediaRecorder', Recorder)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia: vi.fn(async () => {
    order.push('browser'); return { getTracks: () => [{ stop: vi.fn() }] }
  }) } })
  render(<VoiceInput label="Ответ" value="" onChange={vi.fn()} maxLength={100} transcribe={vi.fn()}><textarea /></VoiceInput>)
  expect(order).toEqual([])
  await userEvent.click(screen.getByRole('button', { name: 'Голосовой ввод' }))
  expect(order).toEqual(isInited ? ['max', 'browser'] : ['init', 'max', 'browser'])
  expect(permissions.requestAccess).toHaveBeenCalledWith('mic', expect.any(String))
  expect(screen.getByRole('button', { name: 'Голосовой ввод' })).toHaveAttribute('aria-pressed', 'true')
})

test.each([
  ['mic_app_permission_denied', 'Разрешите микрофон этому mini-app'],
  ['mic_system_permission_denied', 'Разрешите MAX доступ к микрофону'],
  ['mic_not_supported', 'MAX не обнаружил доступный микрофон'],
])('MAX %s stops before browser capture', async (reason, message) => {
  Object.defineProperty(window, 'WebApp', { configurable: true, value: { PermissionsManager: {
    isInited: true, requestAccess: vi.fn().mockRejectedValue({ error: { code: 'client.permissions_request_access.' + reason, message: 'private-sdk-response' } }),
  } } })
  const getUserMedia = vi.fn()
  vi.stubGlobal('MediaRecorder', Recorder)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
  render(<VoiceInput label="Ответ" value="" onChange={vi.fn()} maxLength={100} transcribe={vi.fn()}><textarea /></VoiceInput>)
  await userEvent.click(screen.getByRole('button', { name: 'Голосовой ввод' }))
  expect(screen.getByRole('alert')).toHaveTextContent(message)
  expect(document.body.textContent).not.toContain('private-sdk-response')
  expect(getUserMedia).not.toHaveBeenCalled()
})

test('leaving while MAX initializes never requests permission or opens a microphone later', async () => {
  let initialized!: () => void
  const init = new Promise<void>(resolve => { initialized = resolve })
  const permissions = { isInited: false, init: vi.fn(() => init), requestAccess: vi.fn() }
  Object.defineProperty(window, 'WebApp', { configurable: true, value: { PermissionsManager: permissions } })
  const getUserMedia = vi.fn()
  vi.stubGlobal('MediaRecorder', Recorder)
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } })
  const view = render(<VoiceInput label="Ответ" value="" onChange={vi.fn()} maxLength={100} transcribe={vi.fn()}><textarea /></VoiceInput>)
  await userEvent.click(screen.getByRole('button', { name: 'Голосовой ввод' }))
  view.unmount()
  initialized()
  await waitFor(() => expect(permissions.init).toHaveBeenCalledOnce())
  expect(permissions.requestAccess).not.toHaveBeenCalled()
  expect(getUserMedia).not.toHaveBeenCalled()
})
