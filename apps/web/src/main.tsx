import { createRoot } from 'react-dom/client'
import { App } from './app/App'
import { createMockHost } from './max/mockHost'
import './styles/global.css'

const demo = import.meta.env.VITE_HOST_MODE === 'demo'
  || (import.meta.env.DEV && import.meta.env.VITE_HOST_MODE === undefined)

const hostAdapter = demo
  ? createMockHost(new URLSearchParams(window.location.search).get('demo') === 'error-once')
  : undefined

createRoot(document.getElementById('root')!).render(<App hostAdapter={hostAdapter} />)
