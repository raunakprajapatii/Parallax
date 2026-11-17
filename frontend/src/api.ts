export type ChatRequest = {
  conversationId?: string
  message: string
  demoMode: boolean
}

export type Citation = {
  number: number
  recordId: string
  title: string
  source: 'gmail' | 'jira' | 'notion' | 'calendar' | 'drive'
  url?: string
}

export type ChatResponse = {
  conversationId: string
  answer: string
  citations: Citation[]
  traceId: string
  memoryUsed: string[]
  calendarDraft?: CalendarEventDraft
  calendarConnectUrl?: string
}

export type CalendarEventDraft = {
  draftId: string
  summary: string
  start: string
  end: string
  description: string
  attendeeEmails: string[]
}

export type ChatClient = (request: ChatRequest) => Promise<ChatResponse>
export type ConversationSummary = { conversationId: string; title: string; updatedAt: string }
export type StoredMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
  metadata: { citations?: Citation[]; traceId?: string; memoryUsed?: string[]; demoMode?: boolean; calendarDraft?: CalendarEventDraft; calendarConnectUrl?: string }
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

export async function createCalendarEvent(event: CalendarEventDraft): Promise<{ summary: string; htmlLink?: string }> {
  const response = await fetch('/api/calendar/events', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event),
  })
  if (!response.ok) {
    let message = `Could not create the calendar event (${response.status}).`
    try { message = (await response.json()).detail ?? message } catch { /* Keep the status-based message. */ }
    throw new Error(message)
  }
  return response.json()
}

export type DriveFolder = { id: string; name: string }
export type DriveKnowledgeStatus = { connected: boolean; folders: DriveFolder[]; selectedFolderId: string | null }
export type GoogleIntegrationStatus = { gmail: boolean; calendar: boolean }

export function getGoogleIntegrationStatus(): Promise<GoogleIntegrationStatus> {
  return getJson<GoogleIntegrationStatus>('/api/oauth/status')
}

export async function disconnectGoogleIntegration(provider: 'gmail' | 'calendar'): Promise<void> {
  const response = await fetch(`/api/oauth/${provider}`, { method: 'DELETE' })
  if (!response.ok) throw new Error(`Could not disconnect Google ${provider === 'gmail' ? 'Gmail' : 'Calendar'}.`)
}

export async function getDriveKnowledgeStatus(): Promise<DriveKnowledgeStatus> {
  const statusResponse = await getJson<Record<string, boolean>>('/api/oauth/status')
  if (!statusResponse.drive) return { connected: false, folders: [], selectedFolderId: null }
  const data = await getJson<{ folders: DriveFolder[]; selectedFolderId: string | null }>('/api/drive/folders')
  return { connected: true, ...data }
}

export async function selectDriveFolder(folderId: string): Promise<void> {
  const response = await fetch('/api/drive/folder', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ folderId }) })
  if (!response.ok) throw new Error((await response.json()).detail ?? 'Could not select that folder.')
}

export async function clearDriveFolder(): Promise<void> {
  const response = await fetch('/api/drive/folder', { method: 'DELETE' })
  if (!response.ok) throw new Error('Could not clear the selected folder.')
}

export async function disconnectDrive(): Promise<void> {
  const response = await fetch('/api/oauth/drive', { method: 'DELETE' })
  if (!response.ok) throw new Error('Could not disconnect Google Drive.')
}
