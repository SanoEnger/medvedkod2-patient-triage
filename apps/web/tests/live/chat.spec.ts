import { expect, test } from '@playwright/test'

// Requires a local HTTPS backend (mock or live Groq), synthetic input only.
test('chat survives reload through HTTPS and can be removed from history', async ({ page, request }) => {
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
    expect(new URL(apiOrigin).protocol).toBe('https:')
    await expect(page.getByRole('heading', { name: 'Чат с МедВедом' })).toBeVisible()
    await expect(page.getByLabel('Ваше сообщение')).toBeEnabled()
    const replyPromise = page.waitForResponse((response) => response.url().includes('/messages') && response.request().method() === 'POST')
    const text = '<img src="synthetic.png" alt="synthetic-chat-image"> Синтетический вопрос для врача.'
    await page.getByLabel('Ваше сообщение').fill(text)
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

    await page.reload()
    const listPromise = page.waitForResponse((value) => value.url() === `${apiOrigin}/api/v1/chats` && value.request().method() === 'GET')
    await page.getByRole('button', { name: 'История чатов' }).click()
    const list = await listPromise
    expect(list.headers()['cache-control']).toBe('no-store')
    const saved = (await list.json()).items.find((item: { id: string }) => item.id === chatId)
    expect(saved).toMatchObject({ id: chatId, kind: 'chat', emergency: false })
    const entry = page.getByRole('listitem').filter({ has: page.getByRole('heading', { name: saved.title, exact: true }) }).first()
    const getPromise = page.waitForResponse((value) => value.url() === `${apiOrigin}/api/v1/chats/${chatId}` && value.request().method() === 'GET')
    await entry.getByRole('button', { name: /^Открыть:/ }).click()
    expect(await (await getPromise).json()).toEqual(conversation)
    await expect(page.getByText(text)).toBeVisible()
    await expect(page.getByAltText('synthetic-chat-image')).toHaveCount(0)
    await expect(page.locator('.chat-message .chat-text')).toHaveText(conversation.messages.map((message: { text: string }) => message.text))
    expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0)

    await page.getByRole('button', { name: 'История чатов' }).click()
    await entry.getByRole('button', { name: /^Удалить:/ }).click()
    const deleted = page.waitForResponse((value) => value.url() === `${apiOrigin}/api/v1/chats/${chatId}` && value.request().method() === 'DELETE')
    await page.getByRole('dialog').getByRole('button', { name: 'Удалить', exact: true }).click()
    expect((await deleted).status()).toBe(204)
    await expect(entry).toHaveCount(0)
    const missing = await request.get(`${apiOrigin}/api/v1/chats/${chatId}`, { headers: { Authorization: `Bearer ${accessToken}` } })
    expect(missing.status()).toBe(404)
    chatId = ''
  } finally {
    if (chatId && accessToken) {
      const response = await request.delete(`${apiOrigin}/api/v1/chats/${chatId}`, { headers: { Authorization: `Bearer ${accessToken}` } })
      expect([204, 404]).toContain(response.status())
    }
  }
})
