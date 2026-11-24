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

afterEach(() => { vi.unstubAllGlobals(); Reflect.deleteProperty(document, 'featurePolicy') })

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

test('a blocked iframe policy is explained without requesting or uploading audio', async () => {
  const getUserMedia = vi.fn()
  const transcribe = vi.fn()
  vi.stubGlobal('MediaRecorder', Recorder)
  vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia } })
  const policy = vi.fn(() => false)
  Object.defineProperty(document, 'featurePolicy', { configurable: true, value: { allowsFeature: policy } })
  render(<VoiceInput label="Ответ" value="" onChange={vi.fn()} maxLength={100} transcribe={transcribe}><textarea /></VoiceInput>)
  await userEvent.click(screen.getByRole('button', { name: 'Голосовой ввод' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Окно mini-app запрещает доступ к микрофону')
  expect(policy).toHaveBeenCalledWith('microphone')
  expect(getUserMedia).not.toHaveBeenCalled()
  expect(transcribe).not.toHaveBeenCalled()
})

test.each([
  ['NotAllowedError', 'Доступ к микрофону не разрешён'],
  ['NotFoundError', 'Микрофон не найден'],
  ['NotReadableError', 'Микрофон недоступен'],
])('microphone error %s has a specific message', async (name, message) => {
  vi.stubGlobal('MediaRecorder', Recorder)
  vi.stubGlobal('navigator', { ...navigator, mediaDevices: { getUserMedia: vi.fn().mockRejectedValue(new DOMException('', name)) } })
  render(<VoiceInput label="Ответ" value="" onChange={vi.fn()} maxLength={100} transcribe={vi.fn()}><textarea /></VoiceInput>)
  await userEvent.click(screen.getByRole('button', { name: 'Голосовой ввод' }))
  expect(screen.getByRole('alert')).toHaveTextContent(message)
})
