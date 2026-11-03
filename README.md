# Parallax — Work Intelligence

Parallax is an agentic work assistant that searches Gmail, Jira, and Notion, combines retrieved evidence into cited answers, and records a visible run trace. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the product scope, module ownership, API contracts, demo story, and evaluation plan.

## Team modules

| Module | Ownership | Main area |
|---|---|---|
| A — Frontend & Experience | UI and chat workflow | `frontend/` |
| B — Agent & API | Routing, orchestration, synthesis | `backend/app/agent/`, `backend/app/api/` |
| C — Connectors & Demo Data | Gmail/Jira/Notion adapters and fixtures | `backend/app/connectors/`, `backend/app/data/demo/` |
| D — Memory, Observability & Evaluation | Persistence, traces, evaluation | `backend/app/memory/`, `backend/app/observability/`, `backend/tests/` |

Keep module implementations in their owned folders. Coordinate changes to shared contracts in `PROJECT_PLAN.md` with the team before changing field names or endpoint behavior.

## Local setup

1. Copy `.env.example` to `.env`. Demo mode works without connector credentials. To use Gemini, set `LLM_PROVIDER=gemini` and `GEMINI_API_KEY`; to use Groq, set `LLM_PROVIDER=groq` and `GROQ_API_KEY`. Provider keys are optional; without one, the backend returns extractive answers. For live integrations set `CONNECTOR_ENABLE_LIVE=true`, `CONNECTOR_DEMO_MODE=false`, and add the relevant credentials. Keep `.env` private; it is ignored by Git.
2. Create and activate a Python virtual environment from the repository root.
3. Install backend dependencies and start the API:

   ```powershell
   python -m pip install -r backend/requirements.txt
   uvicorn app.api.app:app --reload --app-dir backend
   ```

4. In another terminal, run `cd frontend`, `npm install`, then `npm run dev`. Open `http://localhost:3000` for Parallax or `http://localhost:8000/docs` for the API.

To schedule meetings, configure the Google OAuth client and register both the Gmail and Calendar callback URLs in Google Cloud. Calendar uses the separate `calendar.events` permission; connect it from the Calendar prompt in chat. Parallax prepares a draft first and creates the event only after you select **Create event**.

## Working together

- Agree on the contracts in `PROJECT_PLAN.md` before parallel implementation.
- Work on separate branches and keep commits focused on your module.
- Do not commit `.env`, access tokens, real work data, local databases, or generated build/cache files.
- Keep demo fixtures synthetic and usable without OAuth/API credentials.
- Integrate early: frontend against the chat response contract, agent against connector and memory interfaces.

## Configuration

`.env.example` lists the shared configuration names. Optional service credentials should remain blank for demo mode. If a real key is accidentally committed, revoke it immediately; deleting it in a later commit does not remove it from Git history.

## Agent workflow

The chat orchestrator is implemented as a LangGraph state graph in `backend/app/agent/workflow.py`:

```text
load context → route to work retrieval or general chat
             → select sources → retrieve → synthesize and validate citations
             → persist the response
```

The graph carries turn state between nodes. The existing SQLite memory service remains the durable transcript store, so the graph does not keep a second copy of conversation history. Read-only connector requests retry once for transient 429/5xx or timeout errors; permission and authentication failures are reported without retry. The application-specific router still chooses sources, while LangGraph owns the workflow and branching.
