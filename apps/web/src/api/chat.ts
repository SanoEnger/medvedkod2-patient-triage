import type { Survey, Triage } from './contracts'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  created_at: string
  emergency: boolean
  client_message_id?: string | null
}
export interface Conversation {
  id: string
  questionnaire_id: string | null
  messages: ChatMessage[]
  result: Triage | null
  emergency: boolean
  pending: boolean
  retryable: boolean
}
export interface ChatClient {
  availability(signal?: AbortSignal): Promise<{ active_survey: Survey | null }>
  open(questionnaireId?: string, signal?: AbortSignal): Promise<Conversation>
  get(id: string, signal?: AbortSignal): Promise<Conversation>
  send(id: string, message: { text: string; client_message_id: string }, signal?: AbortSignal): Promise<Conversation>
  delete(id: string, signal?: AbortSignal): Promise<void>
}
