import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

Object.defineProperty(window, 'scrollTo', { value: () => {}, writable: true })
Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { value(this: HTMLDialogElement) { this.setAttribute('open', '') } })
Object.defineProperty(HTMLDialogElement.prototype, 'close', { value(this: HTMLDialogElement) { this.removeAttribute('open'); this.dispatchEvent(new Event('close')) } })
afterEach(() => { cleanup() })
