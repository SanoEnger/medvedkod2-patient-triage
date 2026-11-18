import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  testIgnore: '**/live/**',
  fullyParallel: true,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:4173', browserName: 'chromium', channel: 'chromium' },
  webServer: {
    command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173',
    reuseExistingServer: false,
    env: { VITE_HOST_MODE: 'demo', VITE_SURVEY_MODE: 'mock', VITE_API_ORIGIN: '' },
  },
})
