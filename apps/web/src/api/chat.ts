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
export interface ChatSummary {
  id: string
  kind: 'chat' | 'questionnaire' | 'questionnaire_result'
  title: string
  created_at: string
  last_activity_at: string
  expires_at: string
  emergency: boolean
}

export interface ChatHistory {
  items: ChatSummary[]
  next_cursor: string | null
}

export interface ChatClient {
  list(cursor?: string, signal?: AbortSignal): Promise<ChatHistory>
  availability(signal?: AbortSignal): Promise<{ active_survey: Survey | null }>
  open(questionnaireId?: string, signal?: AbortSignal): Promise<Conversation>
  get(id: string, signal?: AbortSignal): Promise<Conversation>
  send(id: string, message: { text: string; client_message_id: string }, signal?: AbortSignal): Promise<Conversation>
  delete(id: string, signal?: AbortSignal): Promise<void>
}
