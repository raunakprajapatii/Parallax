import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Activity, ArrowDown, ArrowLeft, ArrowUp, Check, ChevronDown, ChevronRight, CircleHelp, Command, FileText, Layers3, Link2, LoaderCircle, MessageSquareText, Plus, Sparkles, TriangleAlert, X } from 'lucide-react'
import { postChat, type ChatClient, type ChatRequest, type ChatResponse, type Citation } from './api'
import { mockChat } from './mockApi'
import './App.css'
import './classic.css'
import './dark.css'

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
  const [traceOpen, setTraceOpen] = useState(false)
  const [isDemo, setIsDemo] = useState(false)
  const [useMock, setUseMock] = useState(false)

  const client: ChatClient = useMemo(() => useMock ? mockChat : postChat, [useMock])
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') setSelectedCitation(null) }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  async function submitQuestion(question = draft) {
    const message = question.trim()
    if (!message || loading) return
    setDraft(''); setError(null); setLoading(true); setTraceOpen(false)
    setTurns((previous) => [...previous, { question: message }])
    const request: ChatRequest = { conversationId, message, demoMode: useMock }
    try {
      let response: ChatResponse
      try {
        response = await client(request)
        setIsDemo(useMock)
      } catch (cause) {
        if (useMock || !(cause instanceof TypeError)) throw cause
        response = await mockChat({ ...request, demoMode: true })
        setUseMock(true); setIsDemo(true)
      }
      setConversationId(response.conversationId)
      setTurns((previous) => previous.map((turn, index) => index === previous.length - 1 ? { ...turn, response } : turn))
    } catch (cause) {
      setTurns((previous) => previous.slice(0, -1))
      setError(cause instanceof Error ? cause.message : 'Something went wrong. Please try again.')
    } finally { setLoading(false) }
  }

  function resetConversation() { setTurns([]); setDraft(''); setError(null); setConversationId(undefined); setTraceOpen(false) }
  function onSubmit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); void submitQuestion() }

  const renderAnswer = (response: ChatResponse) => {
    const pieces = response.answer.split(/(\[\d+\])/g)
    return pieces.map((piece, index) => {
      const match = piece.match(/^\[(\d+)\]$/)
      if (!match) return <span key={`text-${index}`}>{piece}</span>
      const citation = response.citations.find((item) => item.number === Number(match[1]))
      return citation ? <button className="citation-inline" key={`cite-${index}`} onClick={() => setSelectedCitation(citation)} aria-label={`Open citation ${citation.number}`}>[{citation.number}]</button> : <span key={`missing-${index}`}>{piece}</span>
    })
  }

  return <div className="app-shell">
    <aside className="sidebar" aria-label="Main navigation">
      <div className="brand"><span className="brand-mark"><Sparkles size={18}/></span><span><span className="brand-name">atlas intelligence</span><span className="brand-caption">WORKSPACE ASSISTANT</span></span></div>
      <button className="new-chat" onClick={resetConversation}><Plus size={16}/> New conversation <Command size={13} style={{marginLeft:'auto',opacity:.5}}/></button>
      <div><div className="side-label">Workspace</div><div className="nav-item active"><MessageSquareText size={16}/> Ask Atlas</div><div className="nav-item"><Layers3 size={16}/> Knowledge sources</div><div className="nav-item"><Activity size={16}/> Activity</div></div>
      <div><div className="side-label">Recent conversations</div><div className={`recent-title ${turns.length ? 'selected' : ''}`}>{turns.at(-1)?.question ?? 'Atlas launch planning'}</div><div className="recent-title">Q4 launch readiness</div><div className="recent-title">Product team sync</div></div>
      <div className="side-bottom"><div className="nav-item"><CircleHelp size={16}/> Help & feedback</div><div className="nav-item"><span className="avatar">A</span><span style={{lineHeight:1.4}}>Alex Morgan<small style={{display:'block',color:'#a0a7b6',fontSize:10}}>Workspace admin</small></span><ChevronDown size={14} style={{marginLeft:'auto'}}/></div></div>
    </aside>

    <section className="workspace">
      <header className="topbar"><div className="mobile-brand"><span className="brand-mark"><Sparkles size={15}/></span>atlas intelligence</div><div className="breadcrumb"><span>Workspace</span><ChevronRight size={13}/><strong>Ask Atlas</strong></div><div className="top-right"><div className="demo-pill"><span className="demo-dot"/>{isDemo ? 'Demo workspace' : 'Ready to ask'}</div><div className="avatar" aria-label="Alex Morgan">A</div></div></header>
      <main className="main-content">
        {turns.length === 0 ? <div className="intro"><div className="eyebrow"><Sparkles size={14}/> YOUR WORK, IN CONTEXT</div><h1>Good morning, Alex <span aria-hidden="true">✦</span></h1><p>Ask across your connected work apps. Get clear answers grounded in your team's knowledge.</p></div> : <div className="intro" style={{marginBottom:22}}><div className="eyebrow"><Sparkles size={13}/> ATLAS WORKSPACE</div><h1 style={{fontSize:27}}>Your workspace, understood.</h1></div>}

        {turns.length === 0 && <div className="prompt-grid" aria-label="Suggested questions">{suggestions.map((suggestion, index) => <button className="prompt-card" key={suggestion} onClick={() => void submitQuestion(suggestion)}><span className="prompt-icon">{index === 0 ? <Layers3 size={15}/> : index === 1 ? <Activity size={15}/> : index === 2 ? <FileText size={15}/> : <ArrowDown size={15}/>}</span><span>{suggestion}</span><ArrowUp size={13} style={{marginLeft:'auto',flex:'none',color:'#a2a7b7'}}/></button>)}</div>}

        <div className="conversation" aria-live="polite">
          {turns.map((turn, index) => <div className="turn" key={`${index}-${turn.question}`}>
            <div className="user-message">{turn.question}</div>
            {turn.response ? <>
              <article className="answer-card"><div className="answer-head"><span className="assistant-icon"><Sparkles size={15}/></span><span><strong>Atlas AI</strong><small>{isDemo ? 'Demo response · Just now' : 'Answer grounded in your workspace'}</small></span></div>
                <div className="answer-body">{renderAnswer(turn.response)}</div>
                {turn.response.citations.length > 0 && <div className="citation-list">{turn.response.citations.map((citation) => <button className="citation-chip" key={citation.number} onClick={() => setSelectedCitation(citation)}><SourceMark source={citation.source}/><span>[{citation.number}] {citation.title}</span><ArrowUp size={11} style={{transform:'rotate(45deg)',color:'#a0a7b6'}}/></button>)}</div>}
                {turn.response.memoryUsed.length > 0 && <div className="answer-foot"><span><Check size={12}/> Memory used</span><span>{turn.response.memoryUsed.join(' · ')}</span></div>}
              </article>
              <section className="trace"><button className="trace-toggle" aria-expanded={traceOpen} onClick={() => setTraceOpen((open) => !open)}><span className="trace-title"><Activity size={15}/> Execution trace <span style={{fontWeight:400,color:'#9aa2b3'}}>· {turn.response.traceId}</span></span>{traceOpen ? <ChevronDown size={16}/> : <ChevronRight size={16}/>}</button>
                {traceOpen && <div className="trace-content"><div className="trace-row"><Check size={13} color="#57b98e"/> Request completed</div><div className="trace-row"><span>Run ID</span><code>{turn.response.traceId}</code></div><div className="trace-row"><span>Sources cited</span><strong>{turn.response.citations.length}</strong></div><div className="trace-row"><span>Conversation</span><code>{turn.response.conversationId}</code></div><p className="trace-footnote">Per-tool trace events are not included in the documented chat response.</p></div>}
              </section>
            </> : index === turns.length - 1 && loading ? <div className="answer-card"><div className="answer-head"><span className="assistant-icon"><Sparkles size={15}/></span><span><strong>Atlas AI</strong><small>Searching your workspace <span className="loading-dots"><i/><i/><i/></span></small></span><LoaderCircle size={15} className="spin" style={{marginLeft:'auto',color:'#7775d8'}}/></div><div className="answer-body" style={{color:'#929bad'}}>Connecting relevant knowledge and preparing a cited answer…</div></div> : null}
          </div>)}
          {turns.length === 0 && <div className="empty-state"><span className="assistant-icon" style={{display:'inline-grid',marginBottom:10}}><Sparkles size={15}/></span><div>Ready when you are. Ask a question to explore your workspace.</div></div>}
          {error && <div className="error-banner" role="alert"><TriangleAlert size={16} style={{flex:'none'}}/><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError(null)} style={{marginLeft:'auto',border:0,background:'transparent',color:'inherit',cursor:'pointer'}}><X size={14}/></button></div>}
        </div>

        <div className="composer-wrap"><form className="composer" onSubmit={onSubmit}><textarea aria-label="Ask a question" placeholder="Ask anything about your work…" value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submitQuestion() } }} disabled={loading}/><div className="composer-actions"><span className="composer-hint">Enter to send · Shift + Enter for a new line</span><button className="send-button" type="submit" disabled={!draft.trim() || loading} aria-label="Send question">{loading ? <LoaderCircle size={16}/> : <ArrowUp size={17}/>}</button></div></form><div className="disclaimer">AI can make mistakes. Verify important details in the original sources.</div></div>
      </main>
    </section>

    {selectedCitation && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedCitation(null) }}><section className="modal" role="dialog" aria-modal="true" aria-labelledby="source-title"><div className="modal-head"><div><SourceMark source={selectedCitation.source}/><h2 className="modal-title" id="source-title">{selectedCitation.title}</h2></div><button className="modal-close" aria-label="Close source details" onClick={() => setSelectedCitation(null)}><X size={16}/></button></div><div className="modal-body"><div className="detail-row"><span className="detail-label">Source</span><span className="detail-value" style={{textTransform:'capitalize'}}>{selectedCitation.source}</span></div><div className="detail-row"><span className="detail-label">Record ID</span><span className="detail-value">{selectedCitation.recordId}</span></div><div className="detail-row"><span className="detail-label">Citation</span><span className="detail-value">[{selectedCitation.number}] · Referenced in the answer</span></div>{selectedCitation.url ? <div className="detail-row"><span className="detail-label">Original source</span><a className="detail-value" href={selectedCitation.url} target="_blank" rel="noreferrer"><Link2 size={13} style={{verticalAlign:'middle',marginRight:5}}/>{selectedCitation.url}<ArrowLeft size={12} style={{transform:'rotate(135deg)',marginLeft:4,verticalAlign:'middle'}}/></a></div> : <div className="detail-row"><span className="detail-label">Original source</span><span className="detail-value">No source URL was provided by the API.</span></div>}</div></section></div>}
  </div>
}

export default App
