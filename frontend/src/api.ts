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
