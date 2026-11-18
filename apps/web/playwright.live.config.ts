import { env } from 'node:process'
import { defineConfig } from '@playwright/test'

const origin = env.MEDVED_LIVE_API_ORIGIN || 'https://127.0.0.1:8444'
const endpoint = new URL(origin)
if (endpoint.protocol !== 'https:' || !['localhost', '127.0.0.1'].includes(endpoint.hostname)) {
  throw new Error('Live tests require a local HTTPS API with synthetic data')
}
export default defineConfig({
  testDir: './tests/live',
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: 'http://127.0.0.1:4174', browserName: 'chromium', channel: 'chromium',
    // Local test CA only. The application itself never disables certificate verification.
    ignoreHTTPSErrors: true,
  },
  webServer: {
    command: 'node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 4174 --strictPort',
    url: 'http://127.0.0.1:4174', reuseExistingServer: false,
    env: { VITE_HOST_MODE: 'demo', VITE_SURVEY_MODE: 'api', VITE_API_ORIGIN: origin },
  },
})
