import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ArrowDown, ArrowLeft, ArrowUp, CalendarDays, ChevronRight, Clock3, HardDrive, Layers3, Link2, LoaderCircle, Mail, Plus, RefreshCw, Sparkles, TriangleAlert, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { clearDriveFolder, createCalendarEvent, disconnectDrive, disconnectGoogleIntegration, getConversation, getConversations, getDriveKnowledgeStatus, getGoogleIntegrationStatus, postChat, selectDriveFolder, type ChatClient, type ChatRequest, type ChatResponse, type Citation, type ConversationSummary, type DriveKnowledgeStatus, type GoogleIntegrationStatus } from './api'
import { mockChat } from './mockApi'
import './App.css'
import './classic.css'

type Turn = { question: string; response?: ChatResponse }
const sourceLabels: Record<Citation['source'], string> = { drive: 'Drive', gmail: 'Gmail', jira: 'Jira', notion: 'Notion', calendar: 'Calendar' }
const suggestions = [
  'What is blocking the Atlas launch, who owns each blocker, and what should happen next?',
  'What is the current status of ATL-42 and ATL-51?',
  'Summarize the latest design handoff updates for Atlas.',
  'What should we prioritize before the launch review?',
  "What is Parallax.inc's internal tax reference, and is it a PAN?",
]

function citationSourceClass(source: Citation['source']) { return `source-logo source-${source}` }
function SourceMark({ source }: { source: Citation['source'] }) {
  return <span className={citationSourceClass(source)} aria-label={source}>{source === 'gmail' ? 'G' : source === 'jira' ? 'J' : source === 'drive' ? 'D' : source === 'calendar' ? 'C' : 'N'}</span>
}

function App() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [searchPhase, setSearchPhase] = useState<'searching' | 'synthesizing'>('searching')
  const [showLatestCue, setShowLatestCue] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conversationId, setConversationId] = useState<string>()
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null)
  const [isDemo, setIsDemo] = useState(false)
  const [connectorDemoMode, setConnectorDemoMode] = useState(import.meta.env.VITE_CONNECTOR_DEMO_MODE !== 'false')
  const [useMock, setUseMock] = useState(false)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [calendarCreating, setCalendarCreating] = useState<number | null>(null)
  const [knowledgeOpen, setKnowledgeOpen] = useState(false)
  const [driveKnowledge, setDriveKnowledge] = useState<DriveKnowledgeStatus>({ connected: false, folders: [], selectedFolderId: null })
  const [googleStatus, setGoogleStatus] = useState<GoogleIntegrationStatus>({ gmail: false, calendar: false })
  const [knowledgeError, setKnowledgeError] = useState<string | null>(null)
  const conversationRef = useRef<HTMLDivElement>(null)
  const conversationAtBottomRef = useRef(true)
  const client: ChatClient = useMemo(() => useMock ? mockChat : postChat, [useMock])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelectedCitation(null) }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    void refreshConversations()
  }, [])

  async function refreshDriveKnowledge() {
    try { setDriveKnowledge(await getDriveKnowledgeStatus()); setKnowledgeError(null) }
    catch (cause) { setKnowledgeError(cause instanceof Error ? cause.message : 'Could not load Drive folders.') }
  }

  async function refreshGoogleStatus() {
    try { setGoogleStatus(await getGoogleIntegrationStatus()) }
    catch (cause) { setKnowledgeError(cause instanceof Error ? cause.message : 'Could not load Google connection status.') }
  }

  async function disconnectGoogle(provider: 'gmail' | 'calendar') {
    try {
      await disconnectGoogleIntegration(provider)
      await refreshGoogleStatus()
      setKnowledgeError(null)
    } catch (cause) {
      setKnowledgeError(cause instanceof Error ? cause.message : `Could not disconnect Google ${provider}.`)
    }
  }

  async function refreshConversations() {
    if (useMock) return
    try { setConversations(await getConversations()) } catch { /* Chat still works if history is temporarily unavailable. */ }
  }

  useEffect(() => {
    if (!loading) { setSearchPhase('searching'); return }
    const timer = window.setTimeout(() => setSearchPhase('synthesizing'), 900)
    return () => window.clearTimeout(timer)
  }, [loading, turns.length])

  useEffect(() => {
    const conversation = conversationRef.current
    if (!conversation) return
    if (conversationAtBottomRef.current) {
      conversation.scrollTo({ top: conversation.scrollHeight, behavior: 'smooth' })
      setShowLatestCue(false)
    } else if (turns.length > 0) {
      setShowLatestCue(true)
    }
  }, [turns, loading])

  function handleConversationScroll() {
    const conversation = conversationRef.current
    if (!conversation) return
    const atBottom = conversation.scrollHeight - conversation.scrollTop - conversation.clientHeight < 48
    conversationAtBottomRef.current = atBottom
    if (atBottom) setShowLatestCue(false)
  }

  function jumpToLatest() {
    conversationAtBottomRef.current = true
    conversationRef.current?.scrollTo({ top: conversationRef.current.scrollHeight, behavior: 'smooth' })
    setShowLatestCue(false)
  }

  async function submitQuestion(question = draft) {
    const message = question.trim()
    if (!message || loading) return
    setDraft(''); setError(null); setLoading(true)
    setTurns((previous) => [...previous, { question: message }])
    const request: ChatRequest = { conversationId, message, demoMode: connectorDemoMode }
    try {
      let response: ChatResponse
      try {
        response = await client(request)
        setIsDemo(connectorDemoMode || useMock)
      } catch (cause) {
        if (useMock || !(cause instanceof TypeError)) throw cause
        response = await mockChat({ ...request, demoMode: true })
        setUseMock(true); setIsDemo(true)
      }
      setConversationId(response.conversationId)
      setTurns((previous) => previous.map((turn, index) => index === previous.length - 1 ? { ...turn, response } : turn))
      void refreshConversations()
    } catch (cause) {
      setTurns((previous) => previous.slice(0, -1))
      setDraft(message)
      setError(cause instanceof Error ? cause.message : 'Something went wrong. Please try again.')
    } finally { setLoading(false) }
  }

  function resetConversation() { conversationAtBottomRef.current = true; setShowLatestCue(false); setTurns([]); setDraft(''); setError(null); setConversationId(undefined); setSelectedCitation(null) }

  async function openConversation(id: string) {
    if (loading || useMock) return
    setError(null)
    try {
      const saved = await getConversation(id)
      const restored: Turn[] = []
      let pendingQuestion: string | undefined
      for (const message of saved.messages) {
        if (message.role === 'user') pendingQuestion = message.content
        if (message.role === 'assistant' && pendingQuestion !== undefined) {
          const metadata = message.metadata ?? {}
          restored.push({ question: pendingQuestion, response: {
            conversationId: id,
            answer: message.content,
            citations: metadata.citations ?? [],
            traceId: metadata.traceId ?? '',
            memoryUsed: metadata.memoryUsed ?? [],
            calendarDraft: metadata.calendarDraft,
            calendarConnectUrl: metadata.calendarConnectUrl,
          } })
          setIsDemo(Boolean(metadata.demoMode))
          pendingQuestion = undefined
        }
      }
      setConversationId(id)
      conversationAtBottomRef.current = true
      setShowLatestCue(false)
      setTurns(restored)
      setDraft('')
      setSelectedCitation(null)
      setHistoryOpen(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not open this saved conversation.')
    }
  }
  function onSubmit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); void submitQuestion() }

  async function confirmCalendarEvent(turnIndex: number, response: ChatResponse) {
    if (!response.calendarDraft || calendarCreating !== null) return
    setCalendarCreating(turnIndex); setError(null)
    try {
      const created = await createCalendarEvent(response.calendarDraft)
      setTurns((previous) => previous.map((turn, index) => index !== turnIndex || !turn.response ? turn : {
        ...turn,
        response: { ...turn.response, answer: `${turn.response.answer}\n\n**Scheduled:** ${created.htmlLink ? `[${created.summary}](${created.htmlLink})` : created.summary}`, calendarDraft: undefined, calendarConnectUrl: undefined },
      }))
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : 'Could not create the calendar event.'
      if (/(?:re)?connect Google Calendar/i.test(message)) {
        setTurns((previous) => previous.map((turn, index) => index !== turnIndex || !turn.response ? turn : {
          ...turn,
          response: { ...turn.response, calendarConnectUrl: '/api/oauth/calendar/connect' },
        }))
      }
      setError(message)
    } finally { setCalendarCreating(null) }
  }

  const renderAnswer = (response: ChatResponse) => {
    const markdown = response.answer.replace(/\[(\d+)\]/g, '[$1](#citation-$1)')
    return <ReactMarkdown components={{
      a: ({ href, children }) => {
        const match = href?.match(/^#citation-(\d+)$/)
        if (match) {
          const citation = response.citations.find((item) => item.number === Number(match[1]))
          return citation
            ? <button type="button" className="citation-inline" onClick={() => setSelectedCitation(citation)} aria-label={`Open citation ${citation.number}`}>[{citation.number}]</button>
            : <span>{children}</span>
        }
        if (href?.startsWith('https://') || href?.startsWith('http://')) {
          return <a href={href} target="_blank" rel="noreferrer">{children}</a>
        }
        return <span>{children}</span>
      },
    }}>{markdown}</ReactMarkdown>
  }

  return <div className="app-shell">
    <aside className="sidebar" aria-label="Parallax">
      <div className="brand"><img className="brand-wordmark" src="/parallax-logo.png" alt="Parallax Work Intelligence" /></div>
      <button className="new-chat" onClick={resetConversation}><Plus size={16}/> New conversation</button>
      <div className="saved-chats">
        <div className="saved-chats-label">Recent chats</div>
        {conversations.length ? conversations.map((conversation) => <button className={`saved-chat ${conversationId === conversation.conversationId ? 'selected' : ''}`} key={conversation.conversationId} onClick={() => void openConversation(conversation.conversationId)} title={conversation.title}>{conversation.title}</button>) : <div className="no-saved-chats">Your conversations will appear here.</div>}
      </div>
    </aside>

    <section className="workspace">
      <header className="topbar"><div className="mobile-brand"><img className="mobile-brand-mark" src="/parallax-mark.svg" alt="" />PARALLAX</div><div className="breadcrumb"><span>Work intelligence</span><ChevronRight size={13}/><strong>Ask Parallax</strong></div><div className="top-right"><button className="knowledge-toggle" onClick={() => { setKnowledgeOpen(true); setKnowledgeError(null); void refreshDriveKnowledge(); void refreshGoogleStatus() }}><HardDrive size={14}/> Knowledge sources</button><button className="mobile-history-toggle" onClick={() => setHistoryOpen((open) => !open)} aria-expanded={historyOpen}><Clock3 size={14}/> History</button><div className="demo-pill"><span className="demo-dot"/>{isDemo ? 'Demo workspace' : 'Ready to ask'}</div></div>
        {historyOpen && <div className="mobile-history-menu"><div className="saved-chats-label">Recent chats</div>{conversations.length ? conversations.map((conversation) => <button className="saved-chat" key={conversation.conversationId} onClick={() => void openConversation(conversation.conversationId)} title={conversation.title}>{conversation.title}</button>) : <div className="no-saved-chats">Your conversations will appear here.</div>}</div>}
      </header>
      <main className="main-content">
        {turns.length === 0 && <div className="intro"><div className="eyebrow"><Sparkles size={14}/> YOUR WORK, IN CONTEXT</div><h1>Everything, in context.</h1><p>Ask a question across your connected work apps.</p></div>}

        {turns.length === 0 && <div className="prompt-grid" aria-label="Suggested questions">{suggestions.slice(0, 3).map((suggestion) => <button className="prompt-card" key={suggestion} onClick={() => void submitQuestion(suggestion)}><span className="prompt-icon"><Layers3 size={15}/></span><span><small className="example-label">TRY ASKING</small>{suggestion}</span><ArrowUp size={13} style={{marginLeft:'auto',flex:'none',color:'#a2a7b7'}}/></button>)}</div>}

        <div className="conversation-wrap">
        <div className="conversation" aria-live="polite" ref={conversationRef} onScroll={handleConversationScroll}>
          {turns.map((turn, index) => <div className="turn" key={`${index}-${turn.question}`}>
            <div className="user-message">{turn.question}</div>
            {turn.response ? <>
              <article className="answer-card"><div className="answer-head"><span className="assistant-icon"><img className="assistant-logo" src="/parallax-mark.svg" alt="" /></span><span><strong>Parallax</strong><small>{turn.response.citations.length ? `Sources in this answer · ${[...new Set(turn.response.citations.map((citation) => sourceLabels[citation.source]))].join(' · ')}` : isDemo ? 'Workspace answer · Just now' : 'Answer grounded in your workspace'}</small></span></div>
                <div className="answer-body">{renderAnswer(turn.response)}</div>
                {(turn.response.calendarDraft || turn.response.calendarConnectUrl) && <div className="calendar-action-row">
                  {turn.response.calendarConnectUrl
                    ? <a className="calendar-action" href={turn.response.calendarConnectUrl} target="_blank" rel="noreferrer">Connect Google Calendar</a>
                    : turn.response.calendarDraft && <button className="calendar-action" type="button" disabled={calendarCreating === index} onClick={() => void confirmCalendarEvent(index, turn.response!)}>{calendarCreating === index ? 'Creating event…' : 'Create event'}</button>}
                  <small>{turn.response.calendarConnectUrl ? turn.response.calendarDraft ? 'Review the details, connect your account, then return and reopen this chat to confirm.' : 'Calendar is needed to create the event. Connect now, then tell me the date and time.' : 'This adds the event to Google Calendar and emails the listed invitees.'}</small>
                </div>}
                {turn.response.citations.length > 0 && <div className="citation-list" aria-label="Sources cited in this answer">{turn.response.citations.map((citation) => <button className="citation-chip" key={citation.number} onClick={() => setSelectedCitation(citation)} title={`${sourceLabels[citation.source]} · ${citation.title}`}><SourceMark source={citation.source}/><span className="citation-ref">[{citation.number}]</span><span className="citation-title">{citation.title}</span><span className="citation-open">Details</span></button>)}</div>}
              </article>
            </> : index === turns.length - 1 && loading ? <div className="answer-card"><div className="answer-head"><span className="assistant-icon"><img className="assistant-logo" src="/parallax-mark.svg" alt="" /></span><span><strong>Parallax</strong><small>{searchPhase === 'searching' ? 'Searching connected sources' : 'Putting your answer together'} <span className="loading-dots"><i/><i/><i/></span></small></span><LoaderCircle size={15} className="spin" style={{marginLeft:'auto',color:'#7775d8'}}/></div><div className="answer-body search-status" role="status">{searchPhase === 'searching' ? 'Checking your connected workspace for relevant information…' : 'Reviewing the matching information and preparing a cited answer…'}</div></div> : null}
          </div>)}
          {error && <div className="error-banner" role="alert"><TriangleAlert size={16} style={{flex:'none'}}/><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError(null)} style={{marginLeft:'auto',border:0,background:'transparent',color:'inherit',cursor:'pointer'}}><X size={14}/></button></div>}
        </div>
        {showLatestCue && turns.length > 0 && <button type="button" className="new-messages-cue" onClick={jumpToLatest}><ArrowDown size={14}/> New messages</button>}
        </div>

        <div className="composer-wrap"><form className="composer" onSubmit={onSubmit}><textarea aria-label="Ask a question" maxLength={4000} placeholder="Ask anything about your work…" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submitQuestion() } }} disabled={loading}/><div className="composer-actions"><span className="composer-hint">{draft.length > 0 && <span className="character-count">{draft.length}/4000 · </span>}Enter to send · Shift + Enter for a new line</span><button className="send-button" type="submit" disabled={!draft.trim() || loading} aria-label="Send question">{loading ? <LoaderCircle size={16} className="spin"/> : <ArrowUp size={17}/>}</button></div></form></div>
      </main>
    </section>

    {selectedCitation && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedCitation(null) }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="source-title"><div className="modal-head"><div><SourceMark source={selectedCitation.source}/><h2 className="modal-title" id="source-title">{selectedCitation.title}</h2></div><button className="modal-close" aria-label="Close source details" onClick={() => setSelectedCitation(null)}><X size={16}/></button></div><div className="modal-body"><div className="detail-row"><span className="detail-label">Source</span><span className="detail-value" style={{textTransform:'capitalize'}}>{selectedCitation.source}</span></div><div className="detail-row"><span className="detail-label">Record ID</span><span className="detail-value">{selectedCitation.recordId}</span></div><div className="detail-row"><span className="detail-label">Citation</span><span className="detail-value">[{selectedCitation.number}] · Referenced in the answer</span></div>{selectedCitation.url ? <div className="detail-row"><span className="detail-label">Original source</span><a className="detail-value" href={selectedCitation.url} target="_blank" rel="noreferrer"><Link2 size={13} style={{verticalAlign:'middle',marginRight:5}}/>{selectedCitation.url}<ArrowLeft size={12} style={{transform:'rotate(135deg)',marginLeft:4,verticalAlign:'middle'}}/></a></div> : <div className="detail-row"><span className="detail-label">Original source</span><span className="detail-value">No source URL was provided by the API.</span></div>}</div></section></div>}
    {knowledgeOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setKnowledgeOpen(false) }}>
      <section className="modal knowledge-modal" role="dialog" aria-modal="true" aria-labelledby="knowledge-title">
        <div className="modal-head"><div><HardDrive size={18}/><h2 className="modal-title" id="knowledge-title">Knowledge sources</h2></div><button className="modal-close" aria-label="Close knowledge sources" onClick={() => setKnowledgeOpen(false)}><X size={16}/></button></div>
        <div className="modal-body">
          <label className="folder-label" htmlFor="knowledge-mode">Knowledge mode</label>
          <select id="knowledge-mode" className="folder-select" value={connectorDemoMode ? 'demo' : 'live'} onChange={(event) => setConnectorDemoMode(event.target.value === 'demo')}><option value="demo">Local synthetic data</option><option value="live">Connected sources</option></select>
          <small className="knowledge-note">Local demo mode uses bundled sample records. Connected sources searches your connected work apps and selected Drive folder.</small>

          <div className="integration-section">
            <div className="integration-heading"><strong>Google connections</strong><button type="button" className="integration-refresh" onClick={() => { void refreshGoogleStatus(); void refreshDriveKnowledge() }} aria-label="Refresh Google connection status" title="Refresh status"><RefreshCw size={13}/></button></div>
            <div className="integration-row"><span className="integration-icon"><Mail size={15}/></span><span className="integration-copy"><strong>Gmail</strong><small>Read and search your email</small></span>{googleStatus.gmail ? <><span className="integration-connected">Connected</span><button type="button" className="disconnect-drive" onClick={() => void disconnectGoogle('gmail')}>Disconnect</button></> : <a className="calendar-action integration-connect" href="/api/oauth/gmail/connect" target="_blank" rel="noreferrer" onClick={() => window.setTimeout(() => void refreshGoogleStatus(), 2500)}>Connect</a>}</div>
            <div className="integration-row"><span className="integration-icon"><CalendarDays size={15}/></span><span className="integration-copy"><strong>Google Calendar</strong><small>Find availability and create events</small></span>{googleStatus.calendar ? <><span className="integration-connected">Connected</span><button type="button" className="disconnect-drive" onClick={() => void disconnectGoogle('calendar')}>Disconnect</button></> : <a className="calendar-action integration-connect" href="/api/oauth/calendar/connect" target="_blank" rel="noreferrer" onClick={() => window.setTimeout(() => void refreshGoogleStatus(), 2500)}>Connect</a>}</div>
            <small className="knowledge-note">Sign in in the new tab, then use refresh if the connection status has not updated.</small>
          </div>

          <div className="integration-section drive-section">
            <div className="integration-heading"><strong>Google Drive</strong>{driveKnowledge.connected && <span className="integration-connected">Connected</span>}</div>
            <p className="knowledge-description">Connect Drive and choose a folder. Parallax reads supported files there and cites the original source.</p>
            {!driveKnowledge.connected ? <><a className="calendar-action" href="/api/oauth/drive/connect" target="_blank" rel="noreferrer" onClick={() => window.setTimeout(() => void refreshDriveKnowledge(), 2500)}>Connect Google Drive</a><small className="knowledge-note">Read-only Drive access.</small></> : <>
              <label className="folder-label" htmlFor="drive-folder">Search this Drive folder</label>
              <select id="drive-folder" className="folder-select" value={driveKnowledge.selectedFolderId ?? ''} onChange={async (event) => { const id = event.target.value; try { if (id) await selectDriveFolder(id); else await clearDriveFolder(); await refreshDriveKnowledge() } catch (cause) { setKnowledgeError(cause instanceof Error ? cause.message : 'Could not save folder.') } }}><option value="">Choose a folder…</option>{driveKnowledge.folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select>
              <small className="knowledge-note">Only files directly inside the selected folder are searched.</small>
              <button type="button" className="disconnect-drive" onClick={async () => { try { await disconnectDrive(); setDriveKnowledge({ connected: false, folders: [], selectedFolderId: null }); setKnowledgeError(null) } catch (cause) { setKnowledgeError(cause instanceof Error ? cause.message : 'Could not disconnect Drive.') } }}>Disconnect Google Drive</button>
            </>}
          </div>
          {knowledgeError && <div className="error-banner" role="alert">{knowledgeError}</div>}
        </div>
      </section>
    </div>}
  </div>
}

export default App
