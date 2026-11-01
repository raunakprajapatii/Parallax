export type ChatRequest = {
  conversationId?: string
  message: string
  demoMode: boolean
}

export type Citation = {
  number: number
  recordId: string
  title: string
  source: 'gmail' | 'jira' | 'notion'
  url?: string
}

export type ChatResponse = {
  conversationId: string
  answer: string
  citations: Citation[]
  traceId: string
  memoryUsed: string[]
}

export type ChatClient = (request: ChatRequest) => Promise<ChatResponse>
export type ConversationSummary = { conversationId: string; title: string; updatedAt: string }
export type StoredMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  metadata: { citations?: Citation[]; traceId?: string; memoryUsed?: string[]; demoMode?: boolean }
  createdAt: string
}

export async function postChat(request: ChatRequest): Promise<ChatResponse> {
  const response = await fetch('/api/chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request),
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `The assistant request failed (${response.status}).`)
  }
  return (await response.json()) as ChatResponse
}

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`Request failed (${response.status}).`)
  return (await response.json()) as T
}

export function getConversations(): Promise<ConversationSummary[]> {
  return getJson<ConversationSummary[]>('/api/conversations')
}

export function getConversation(conversationId: string): Promise<{ conversationId: string; messages: StoredMessage[] }> {
  return getJson<{ conversationId: string; messages: StoredMessage[] }>(`/api/conversations/${encodeURIComponent(conversationId)}`)
}
