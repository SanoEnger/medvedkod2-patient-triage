import { defineConfig } from 'vitest/config'

export default defineConfig({
  esbuild: { jsx: 'automatic' },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.{ts,tsx}'],
    setupFiles: ['src/test/setup.ts'],
    pool: 'threads',
    maxWorkers: 2,
    restoreMocks: true,
    unstubEnvs: true,
    unstubGlobals: true,
  },
})
