export interface HostContext {
  mode: 'demo' | 'max'
}

// UI boundary only. Launch authentication belongs to the backend and host owners.
export interface MaxHostAdapter {
  readonly kind?: 'host'
  initialize(): Promise<HostContext>
}
