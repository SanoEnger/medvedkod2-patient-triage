import { defineConfig } from '@playwright/test'

const port = Number(process.env.PLAYWRIGHT_PORT || 4173)
const baseURL = `http://127.0.0.1:${port}`

export default defineConfig({
  testDir: './tests',
  testIgnore: '**/live/**',
  fullyParallel: true,
  workers: 1,
  use: { baseURL, browserName: 'chromium' },
  webServer: {
    command: `node node_modules/vite/bin/vite.js --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    env: { VITE_HOST_MODE: 'demo', VITE_SURVEY_MODE: 'mock', VITE_API_ORIGIN: '' },
  },
})
