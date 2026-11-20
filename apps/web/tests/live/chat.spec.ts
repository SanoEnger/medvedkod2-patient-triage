import { expect, test } from '@playwright/test'

// Requires a local HTTPS backend (mock or live Groq), synthetic input only.
test('chat response from real API is rendered and removable', async ({ page, request }) => {
  let accessToken = ''
  let chatId = ''
  let apiOrigin = ''
  page.on('response', async (response) => {
    if (response.url().endsWith('/api/v1/auth/launch') && response.ok()) {
      accessToken = (await response.json()).access_token
    }
  })
  try {
    await page.goto('/')
    const openPromise = page.waitForResponse((response) => response.url().endsWith('/api/v1/chats') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Начать чат с МедВедом' }).click()
    const opened = await openPromise
    expect(opened.status()).toBe(201)
    chatId = (await opened.json()).id
    apiOrigin = new URL(opened.url()).origin
    await expect(page.getByRole('heading', { name: 'Чат с МедВедом' })).toBeVisible()
    await expect(page.getByLabel('Ваше сообщение')).toBeEnabled()
    const replyPromise = page.waitForResponse((response) => response.url().includes('/messages') && response.request().method() === 'POST')
    await page.getByLabel('Ваше сообщение').fill('Это синтетический пример. Как подготовить список вопросов к врачу?')
    await page.getByRole('button', { name: 'Отправить', exact: true }).click()
    const response = await replyPromise
    expect(response.status()).toBe(200)
    const conversation = await response.json()
    chatId = conversation.id
    expect(conversation.pending).toBe(false)
    const last = conversation.messages.at(-1)
    expect(last.role).toBe('assistant')
    expect(last.text.length).toBeGreaterThan(0)
    await expect(page.locator('.chat-message--assistant .chat-text').last()).toHaveText(last.text)
    await expect(page.getByLabel('Ваше сообщение')).toHaveValue('')
    expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)
  } finally {
    if (chatId && accessToken) {
      const response = await request.delete(`${apiOrigin}/api/v1/chats/${chatId}`, { headers: { Authorization: `Bearer ${accessToken}` } })
      expect(response.status()).toBe(204)
    }
  }
})
