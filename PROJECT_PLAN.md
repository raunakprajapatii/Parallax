# Live Data Intelligence Agent — Project Plan

## 1. Project in one sentence

Build a web application where a user asks a work question (for example, “What is blocking the Q4 launch?”), and an AI agent retrieves live or mocked information from Gmail, Jira, and Notion, combines the evidence, and returns a concise answer with source citations, memory, and a visible execution trace.

## 2. Goal and resume value

This is **not** a generic chatbot or a static RAG demo. The differentiator is an agentic workflow:

1. Understand the question.
2. Decide which connected sources matter.
3. Call one or more source tools.
4. Combine the returned evidence.
5. Produce a grounded answer with citations.
6. Store only useful user-approved context for future questions.
7. Show what the agent did, without exposing hidden reasoning.

The completed project demonstrates full-stack engineering, API integration, tool calling, retrieval grounding, observability, and product thinking—strong material for a group-project demo and résumé.

## 3. Scope: build this, not everything

### MVP (must ship)

- Chat-style UI with one clear workflow: ask a work-intelligence question.
- Connectors for **Gmail, Jira, and Notion** through a common interface.
- A deterministic agent workflow: route → retrieve → synthesize → cite.
- Source cards/citations that open the original item or a local mock record.
- Session memory and simple persistent user memory (“remember this project is called Atlas”).
- A run trace showing tools used, timing, source count, and success/failure.
- Demo mode containing realistic local Gmail/Jira/Notion data so the project works without OAuth credentials.
- Evaluation script with 15–20 predefined questions and expected evidence sources.

### Stretch goals (only after MVP works)

- Real OAuth integrations for one or more services.
- Follow-up questions that reuse previous retrieved evidence.
- Scheduled daily digest.
- Vector search for large Notion collections.
- Role-based access or multi-user deployment.

### Explicit non-goals for this version

- Autonomous writing/sending of emails or editing Jira/Notion.
- Complex multi-agent collaboration.
- Fine-tuning a model.
- Production-grade enterprise permissions and audit compliance.
- Supporting every work application.

## 4. Product demo scenario

Seed the demo workspace **“Atlas Launch”** with:

- Gmail: a design handoff delay and an approval request.
- Jira: `ATL-42` blocked by API rate limits and `ATL-51` in review.
- Notion: launch brief, owner list, and launch date.

Demo question:

> “What is blocking the Atlas launch, who owns each blocker, and what should happen next?”

Expected answer: a short prioritized list that joins Jira’s blocked ticket, Gmail’s discussion, and Notion’s launch context. Every factual claim has a citation.

## 5. Recommended architecture

```text
React/Vite frontend
        │  HTTP/SSE
FastAPI backend
        │
Agent Orchestrator ── Tool Registry ── Gmail adapter
        │                              Jira adapter
        │                              Notion adapter
        │
Memory service ─── SQLite
        │
Run/trace store ── SQLite
```

### Stack choices

| Layer | Choice | Why |
|---|---|---|
| Frontend | React + Vite + TypeScript + Tailwind | Fast to build and polished for a demo |
| Backend | Python FastAPI + Pydantic | Excellent for tool/API workflows and typed contracts |
| Agent model | OpenAI small/mini model (configurable) | Good tool calling at low cost; a fake model mode can support UI tests |
| Database | SQLite + SQLModel/SQLAlchemy | Free, portable, no deployment complexity |
| Integrations | Official APIs when configured; local JSON fixtures otherwise | Reliable demo and optional live data |
| Testing | Pytest + Vitest | Lightweight coverage for the critical logic |

Use environment variables for API keys. Never place credentials in the repository. Provide `.env.example` only.

## 6. Four modules and ownership

Each owner should work in their module directory and expose only the agreed API/contract below. This avoids merge conflicts.

| Module | Owner focus | Deliverables | Done when |
|---|---|---|---|
| **A. Frontend & Experience** | UI engineer | Chat view, answer/citation cards, source detail modal, trace panel, integration-status view | A user can submit a query, see streamed/loading states, read citations and inspect a run trace |
| **B. Agent Orchestrator & API** | Backend/AI engineer | FastAPI endpoints, routing/planning, tool calling loop, answer synthesis schema, citation validation | Given normalized tool results, the API returns a grounded answer and never invents a citation |
| **C. Connectors & Demo Data** | Integration/data engineer | Gmail/Jira/Notion adapter interface, mock JSON data, search/filter functions, optional real API adapters | All three sources return normalized records for the demo questions, even with no external credentials |
| **D. Memory, Observability & Evaluation** | Platform/QA engineer | SQLite schema, memory service, trace event recorder, metrics page/API, evaluation dataset and report | Memory can be saved/retrieved safely; each run is traceable; evaluation runs are repeatable |

### Suggested folders

```text
frontend/                 # Module A
backend/
  app/api/                # shared endpoint layer
  app/agent/              # Module B
  app/connectors/         # Module C
  app/memory/             # Module D
  app/observability/      # Module D
  app/data/demo/          # Module C
  tests/                  # shared tests, owned by relevant module
docs/
```

## 7. Integration contracts (agree before coding)

### Normalized source record

Every connector returns this shape. Do not return provider-specific data directly to the agent.

```ts
type SourceRecord = {
  id: string;                         // e.g. "jira:ATL-42"
  source: "gmail" | "jira" | "notion";
  title: string;
  content: string;                    // clean, relevant text
  url?: string;
  author?: string;
  createdAt?: string;                 // ISO date
  metadata: Record<string, string>;   // e.g. status, assignee, labels
};
```

### Tool contract

```ts
type ToolResult = {
  toolName: "search_gmail" | "search_jira" | "search_notion";
  query: string;
  records: SourceRecord[];
  latencyMs: number;
  error?: string;
};
```

### Chat request/response

`POST /api/chat`

```json
{ "conversationId": "optional-id", "message": "What blocks Atlas?", "demoMode": true }
```

```json
{
  "conversationId": "...",
  "answer": "The main blocker is... [1]",
  "citations": [{ "number": 1, "recordId": "jira:ATL-42", "title": "...", "source": "jira", "url": "..." }],
  "traceId": "run_...",
  "memoryUsed": ["Atlas is the Q4 launch project"]
}
```

### Trace event

```json
{ "traceId": "run_...", "step": "tool_complete", "tool": "search_jira", "durationMs": 117, "recordCount": 2, "timestamp": "..." }
```

## 8. Agent design: simple, inspectable, grounded

Keep the agent workflow constrained. A reliable state machine is more impressive than an unpredictable autonomous loop.

```text
User query
  → classify intent and select 1–3 sources
  → retrieve records (max 5/source)
  → rank/deduplicate evidence
  → synthesize answer only from records
  → validate citation IDs exist
  → optionally write an explicit memory
  → return answer + trace
```

Rules:

- Use a maximum of three retrieval rounds and a timeout per tool.
- If evidence is missing, say so clearly; do not guess.
- Cite each factual sentence or bullet.
- Store memory only when the user says “remember…” or explicitly approves a suggested memory.
- Log decisions as short structured labels (for example, `selected_sources: [jira, gmail]`), not private chain-of-thought.

## 9. Memory design

| Memory type | Storage | Example | Retention |
|---|---|---|---|
| Conversation context | SQLite, tied to conversation ID | Last 6 messages | Session / configurable |
| Long-term fact | SQLite, tied to local demo user | “Atlas launch target is 15 Dec” | Until forgotten by user |
| Run trace | SQLite | tool calls, latency, record IDs | For demo/evaluation |

Long-term memory rows need: `id`, `user_id`, `text`, `category`, `created_at`, `last_used_at`, `consent_source`. Include a “Forget memory” action in the UI.

## 10. Evaluation rubric

Create `backend/tests/evaluation_cases.json` with 15–20 questions across these categories:

- Single-source retrieval (find Jira status).
- Cross-source synthesis (identify a blocker + owner + context).
- Temporal question (what changed recently).
- Insufficient evidence (agent must say it cannot determine the answer).
- Citation fidelity (each cited ID maps to retrieved evidence).
- Memory behavior (remember only after permission; retrieve it later).

Score each case:

| Metric | Definition | MVP target |
|---|---|---|
| Source selection | Needed source was queried | ≥ 85% |
| Evidence recall | Expected record was retrieved | ≥ 80% |
| Citation validity | Citation points to returned record | 100% |
| Groundedness | Answer claims supported by evidence | ≥ 90% manual sample |
| Latency | Demo response time | < 8 seconds |

For the final presentation, show a small table with 5 representative evaluation results and one intentionally unanswerable query.

## 11. Build plan for today

| Time block | Team outcome |
|---|---|
| Hour 0–1 | Agree on scope/contracts, create repository skeleton, seed Atlas data, confirm demo questions |
| Hour 1–3 | A builds UI shell; B creates chat API/orchestrator skeleton; C builds mock connectors; D creates database + trace schema |
| Hour 3–5 | Integrate `/api/chat` end to end using demo mode; display citations and trace |
| Hour 5–6 | Add memory workflow, error/empty states, and cross-source synthesis |
| Hour 6–7 | Run evaluation cases, fix citation and data gaps, polish demo flow |
| Final 30 min | README, architecture diagram, individual contribution notes, rehearsal |

### Checkpoints

1. **First demo:** query → one mock source → cited answer.
2. **Core demo:** multi-source question → answer + three citations + trace.
3. **Final demo:** memory, evaluation result, graceful “not enough evidence” response.

If time becomes tight, ship in this order: mock connectors → cited answer → trace → UI polish → memory → real OAuth.

## 12. Cost-control plan

- Develop entirely using local fixtures; live integrations are optional.
- Keep context small: top 5 cleaned records per source, truncate each record to a sensible limit.
- Use a configurable low-cost model for routing/synthesis; cache identical demo queries during a presentation.
- Set a per-request token and tool-call cap.
- Do not embed every document or run a managed vector database for the MVP.
- Publish only a demo dataset—never real workplace emails, tokens, or private documents.

Expected cost for a student demo: near-zero without external model/API use; low single-digit USD if using a small hosted model sparingly.

## 13. Teammate handoff prompts

Copy one prompt to each teammate’s coding LLM after sharing this file.

### Module A — Frontend & Experience

> We are building the project described in `PROJECT_PLAN.md`. You own Module A only. Implement a React + TypeScript + Vite frontend under `frontend/`. Build a professional chat view, loading/error states, numbered citation cards, a source-detail modal, and a collapsible execution trace panel. Consume `POST /api/chat` exactly as documented in the plan; use typed API models and a temporary mock client only if the backend is unavailable. Do not modify backend modules. Make the UI work with the plan’s response contract and add concise setup instructions.

### Module B — Agent Orchestrator & API

> We are building the project described in `PROJECT_PLAN.md`. You own Module B only. Implement FastAPI endpoints and the constrained agent pipeline under `backend/app/agent/` and `backend/app/api/`. Follow the exact `SourceRecord`, `ToolResult`, and `/api/chat` contracts in the plan. Build a deterministic route → retrieve → rank → synthesize → validate-citations workflow. The synthesizer must answer only from evidence and must return an explicit insufficiency message when needed. Record structured, non-chain-of-thought trace events. Depend on connector and memory interfaces, not their internal implementations. Add pytest coverage for citation validation and routing.

### Module C — Connectors & Demo Data

> We are building the project described in `PROJECT_PLAN.md`. You own Module C only. Implement the common Gmail/Jira/Notion connector interface in `backend/app/connectors/` plus realistic local Atlas Launch fixture data in `backend/app/data/demo/`. Each search function must return the exact normalized `SourceRecord` and `ToolResult` contracts in the plan. Make demo mode completely credential-free and include data supporting the specified launch-blocker demo question. Keep optional real API integration configuration isolated and disabled by default. Add tests that prove each connector retrieves expected records.

### Module D — Memory, Observability & Evaluation

> We are building the project described in `PROJECT_PLAN.md`. You own Module D only. Implement SQLite-backed session/long-term memory, structured run trace persistence, and an evaluation suite under `backend/app/memory/`, `backend/app/observability/`, and `backend/tests/`. Honor the rule that long-term memory is written only following explicit user instruction or approval, and support forget/delete. Implement the documented trace event contract. Create 15–20 evaluation cases with expected source/record evidence and a script/report that calculates the plan’s metrics. Do not change the connector or frontend internals; use their published contracts.

## 14. README/demo checklist

- [ ] One-command local startup (or clear frontend/backend commands).
- [ ] `.env.example` without secrets.
- [ ] Demo mode works from a fresh clone.
- [ ] Architecture diagram and module ownership in README.
- [ ] Three rehearsed questions: cross-source, memory, insufficient evidence.
- [ ] Visible citations and trace for every answer.
- [ ] Evaluation result screenshot/table.
- [ ] Contribution summary from all four teammates.

## 15. Suggested project title and résumé bullet

**Project title:** Live Data Intelligence Agent

**Résumé bullet (adapt after completion):** Built a full-stack agentic work-intelligence system that orchestrates Gmail, Jira, and Notion retrieval, synthesizes evidence-backed answers with citations, persists consented user memory, and exposes run-level observability; evaluated retrieval and citation fidelity using a reproducible test suite.
