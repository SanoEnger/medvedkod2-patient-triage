import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { AppShell } from '../app/AppShell'
import { WelcomePage } from './WelcomePage'

test('welcome has neutral copy and keeps the start action', async () => {
  const start = vi.fn()
  const { container } = render(<AppShell mode="demo"><WelcomePage onStart={start} /></AppShell>)
  expect(container.textContent).not.toMatch(/демонстр|демоверси|вымышлен|учебный/i)
  await userEvent.click(screen.getByRole('button', { name: 'Начать опрос' }))
  expect(start).toHaveBeenCalledOnce()
})
