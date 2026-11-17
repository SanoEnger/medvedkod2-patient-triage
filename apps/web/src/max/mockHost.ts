import type { MaxHostAdapter } from './MaxHostAdapter'

export function createMockHost(failOnce = false): MaxHostAdapter {
  let shouldFail = failOnce

  return {
    async initialize() {
      await new Promise((resolve) => setTimeout(resolve, 500))
      if (shouldFail) {
        shouldFail = false
        throw new Error('DEMO_HOST_UNAVAILABLE')
      }
      return { mode: 'demo' }
    },
  }
}
