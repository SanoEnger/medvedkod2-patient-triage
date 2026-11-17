import { useState } from 'react'
import type { ReactNode } from 'react'
import { Button } from '../components/ui'

export function AppShell({ children, mode }: { children: ReactNode; mode?: 'demo' | 'max' }) {
  const [enhancedReadability, setEnhancedReadability] = useState(false)

  return <div className="app-shell" data-readability={enhancedReadability ? 'enhanced' : undefined}>
    <a className="skip-link" href="#main">Перейти к содержимому</a>
    <header className="site-header">
      <a className="brand" href="/" aria-label="МедВед — на главную"><img className="brand-mark" src="/brand/medved-mark.png" width={52} height={52} alt="" aria-hidden="true" decoding="async" /><span>МедВед<span className="brand-caption">навигатор пациента</span></span></a>
      {mode && <span className="mode-badge">{mode === 'demo' ? 'Демоверсия' : 'MAX'}</span>}
    </header>
    <div className="readability-controls">
      <Button variant="secondary" className="readability-toggle" aria-pressed={enhancedReadability} onClick={() => setEnhancedReadability((value) => !value)}><span aria-hidden="true">Аа</span> Читаемость</Button>
    </div>
    <main id="main" tabIndex={-1}>{children}</main>
    <footer className="site-footer"><span>МедВед.Код2 · 2026</span><span>Бот не ставит диагноз и не заменяет врача</span></footer>
  </div>
}
