import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { Activity, ArrowDown, ArrowLeft, ArrowUp, ChevronRight, Clock3, FileText, Layers3, Link2, LoaderCircle, Plus, Sparkles, TriangleAlert, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import { createCalendarEvent, getConversation, getConversations, postChat, type ChatClient, type ChatRequest, type ChatResponse, type Citation, type ConversationSummary } from './api'
import { mockChat } from './mockApi'
import './App.css'
import './classic.css'

type Turn = { question: string; response?: ChatResponse }
const suggestions = [
  'What is blocking the Atlas launch, who owns each blocker, and what should happen next?',
  'What is the current status of ATL-42 and ATL-51?',
  'Summarize the latest design handoff updates for Atlas.',
  'What should we prioritize before the launch review?',
]

function citationSourceClass(source: Citation['source']) { return `source-logo source-${source}` }
function SourceMark({ source }: { source: Citation['source'] }) {
  return <span className={citationSourceClass(source)} aria-label={source}>{source === 'gmail' ? 'G' : source === 'jira' ? 'J' : 'N'}</span>
}

function App() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conversationId, setConversationId] = useState<string>()
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null)
  const [isDemo, setIsDemo] = useState(false)
  const [useMock, setUseMock] = useState(false)
  const [conversations, setConversations] = useState<ConversationSummary[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [calendarCreating, setCalendarCreating] = useState<number | null>(null)
  const conversationRef = useRef<HTMLDivElement>(null)
  const connectorDemoMode = import.meta.env.VITE_CONNECTOR_DEMO_MODE !== 'false'

  const client: ChatClient = useMemo(() => useMock ? mockChat : postChat, [useMock])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelectedCitation(null) }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    void refreshConversations()
  }, [])

  async function refreshConversations() {
    if (useMock) return
    try { setConversations(await getConversations()) } catch { /* Chat still works if history is temporarily unavailable. */ }
  }

  useEffect(() => {
    const conversation = conversationRef.current
    if (conversation) conversation.scrollTo({ top: conversation.scrollHeight, behavior: 'smooth' })
  }, [turns, loading])

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
      setError(cause instanceof Error ? cause.message : 'Something went wrong. Please try again.')
    } finally { setLoading(false) }
  }

  function resetConversation() { setTurns([]); setDraft(''); setError(null); setConversationId(undefined); setSelectedCitation(null) }

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
      setError(cause instanceof Error ? cause.message : 'Could not create the calendar event.')
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
      <header className="topbar"><div className="mobile-brand"><img className="mobile-brand-mark" src="/parallax-mark.svg" alt="" />PARALLAX</div><div className="breadcrumb"><span>Work intelligence</span><ChevronRight size={13}/><strong>Ask Parallax</strong></div><div className="top-right"><button className="mobile-history-toggle" onClick={() => setHistoryOpen((open) => !open)} aria-expanded={historyOpen}><Clock3 size={14}/> History</button><div className="demo-pill"><span className="demo-dot"/>{isDemo ? 'Demo workspace' : 'Ready to ask'}</div></div>
        {historyOpen && <div className="mobile-history-menu"><div className="saved-chats-label">Recent chats</div>{conversations.length ? conversations.map((conversation) => <button className="saved-chat" key={conversation.conversationId} onClick={() => void openConversation(conversation.conversationId)} title={conversation.title}>{conversation.title}</button>) : <div className="no-saved-chats">Your conversations will appear here.</div>}</div>}
      </header>
      <main className="main-content">
        {turns.length === 0 ? <div className="intro"><div className="eyebrow"><Sparkles size={14}/> YOUR WORK, IN CONTEXT</div><h1>Everything, in context.</h1><p>Ask a question across your connected work apps.</p></div> : <div className="intro" style={{marginBottom:22}}><div className="eyebrow"><Sparkles size={13}/> PARALLAX</div><h1 style={{fontSize:27}}>Your workspace, understood.</h1></div>}

        {turns.length === 0 && <div className="prompt-grid" aria-label="Suggested questions">{suggestions.map((suggestion, index) => <button className="prompt-card" key={suggestion} onClick={() => void submitQuestion(suggestion)}><span className="prompt-icon">{index === 0 ? <Layers3 size={15}/> : index === 1 ? <Activity size={15}/> : index === 2 ? <FileText size={15}/> : <ArrowDown size={15}/>}</span><span>{suggestion}</span><ArrowUp size={13} style={{marginLeft:'auto',flex:'none',color:'#a2a7b7'}}/></button>)}</div>}

        <div className="conversation" aria-live="polite" ref={conversationRef}>
          {turns.map((turn, index) => <div className="turn" key={`${index}-${turn.question}`}>
            <div className="user-message">{turn.question}</div>
            {turn.response ? <>
              <article className="answer-card"><div className="answer-head"><span className="assistant-icon"><img className="assistant-logo" src="/parallax-mark.svg" alt="" /></span><span><strong>Parallax</strong><small>{isDemo ? 'Demo response · Just now' : 'Answer grounded in your workspace'}</small></span></div>
                <div className="answer-body">{renderAnswer(turn.response)}</div>
                {(turn.response.calendarDraft || turn.response.calendarConnectUrl) && <div className="calendar-action-row">
                  {turn.response.calendarConnectUrl
                    ? <a className="calendar-action" href={turn.response.calendarConnectUrl} target="_blank" rel="noreferrer">Connect Google Calendar</a>
                    : turn.response.calendarDraft && <button className="calendar-action" type="button" disabled={calendarCreating === index} onClick={() => void confirmCalendarEvent(index, turn.response!)}>{calendarCreating === index ? 'Creating event…' : 'Create event'}</button>}
                  <small>{turn.response.calendarConnectUrl ? turn.response.calendarDraft ? 'Review the details, connect your account, then return and reopen this chat to confirm.' : 'Calendar is needed to create the event. Connect now, then tell me the date and time.' : 'This adds the event to Google Calendar and emails the listed invitees.'}</small>
                </div>}
                {turn.response.citations.length > 0 && <div className="citation-list">{turn.response.citations.map((citation) => <button className="citation-chip" key={citation.number} onClick={() => setSelectedCitation(citation)}><SourceMark source={citation.source}/><span>[{citation.number}] {citation.title}</span><ArrowUp size={11} style={{transform:'rotate(45deg)',color:'#a0a7b6'}}/></button>)}</div>}
              </article>
            </> : index === turns.length - 1 && loading ? <div className="answer-card"><div className="answer-head"><span className="assistant-icon"><img className="assistant-logo" src="/parallax-mark.svg" alt="" /></span><span><strong>Parallax</strong><small>Searching your workspace <span className="loading-dots"><i/><i/><i/></span></small></span><LoaderCircle size={15} className="spin" style={{marginLeft:'auto',color:'#7775d8'}}/></div><div className="answer-body" style={{color:'#929bad'}}>Connecting relevant knowledge and preparing a cited answer…</div></div> : null}
          </div>)}
          {turns.length === 0 && <div className="empty-state"><span className="assistant-icon" style={{display:'inline-grid',marginBottom:10}}><img className="assistant-logo" src="/parallax-mark.svg" alt="" /></span><div>Ready when you are. Ask a question to explore your workspace.</div></div>}
          {error && <div className="error-banner" role="alert"><TriangleAlert size={16} style={{flex:'none'}}/><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError(null)} style={{marginLeft:'auto',border:0,background:'transparent',color:'inherit',cursor:'pointer'}}><X size={14}/></button></div>}
        </div>

        <div className="composer-wrap"><form className="composer" onSubmit={onSubmit}><textarea aria-label="Ask a question" placeholder="Ask anything about your work…" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submitQuestion() } }} disabled={loading}/><div className="composer-actions"><span className="composer-hint">Enter to send · Shift + Enter for a new line</span><button className="send-button" type="submit" disabled={!draft.trim() || loading} aria-label="Send question">{loading ? <LoaderCircle size={16}/> : <ArrowUp size={17}/>}</button></div></form></div>
      </main>
    </section>

    {selectedCitation && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedCitation(null) }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="source-title"><div className="modal-head"><div><SourceMark source={selectedCitation.source}/><h2 className="modal-title" id="source-title">{selectedCitation.title}</h2></div><button className="modal-close" aria-label="Close source details" onClick={() => setSelectedCitation(null)}><X size={16}/></button></div><div className="modal-body"><div className="detail-row"><span className="detail-label">Source</span><span className="detail-value" style={{textTransform:'capitalize'}}>{selectedCitation.source}</span></div><div className="detail-row"><span className="detail-label">Record ID</span><span className="detail-value">{selectedCitation.recordId}</span></div><div className="detail-row"><span className="detail-label">Citation</span><span className="detail-value">[{selectedCitation.number}] · Referenced in the answer</span></div>{selectedCitation.url ? <div className="detail-row"><span className="detail-label">Original source</span><a className="detail-value" href={selectedCitation.url} target="_blank" rel="noreferrer"><Link2 size={13} style={{verticalAlign:'middle',marginRight:5}}/>{selectedCitation.url}<ArrowLeft size={12} style={{transform:'rotate(135deg)',marginLeft:4,verticalAlign:'middle'}}/></a></div> : <div className="detail-row"><span className="detail-label">Original source</span><span className="detail-value">No source URL was provided by the API.</span></div>}</div></section></div>}
  </div>
}

export default App
