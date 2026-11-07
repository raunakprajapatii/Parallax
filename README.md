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

To search or schedule with Google Calendar, configure the Google OAuth client and register both the Gmail and Calendar callback URLs in Google Cloud. Calendar uses the `calendar.events` permission. Event creation still prepares a draft and requires you to select **Create event**.

### Google Drive knowledge source

To demo Drive retrieval, upload the prepared [`Parallax.inc Knowledge Demo` folder](demo_drive_knowledge/Parallax.inc%20Knowledge%20Demo) into the Google account you will connect. It contains 15 plain-text and CSV documents with 241 employee records, 360 work items, 180 customer accounts, 500 support tickets, and supporting policy, finance, leave, vendor, and operating data. The records are generated for demonstration; email addresses use the reserved `example.test` domain, and the internal tax reference is not a valid PAN or statutory identifier. See the [upload guide](demo_drive_knowledge/README.md).

For live Drive search, configure `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, register `http://localhost:8000/api/oauth/drive/callback` as an authorized redirect URI, and set `GOOGLE_DRIVE_OAUTH_REDIRECT_URI` if using a different host. Set `CONNECTOR_ENABLE_LIVE=true` and restart the backend. In Parallax, open **Knowledge sources**, choose **Connected sources**, connect Google Drive, and select `Parallax.inc Knowledge Demo`. Retrieval searches full text/CSV content, ranks matching passages, and cites the original Drive file. It does not recurse into subfolders or ingest PDF/binary formats yet. Disconnect Drive or clear the selected folder from the app to stop using this source.

Use synthetic documents for demos. A selected folder is read at query time; Parallax does not make a separate vector database or retain document contents in its local database.

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

The graph carries turn state between nodes. A compact structured LLM plan selects up to three allow-listed sources and gives each a query of at most 12 words; deterministic routing is the fallback. Connector requests retry once for transient 429/5xx or timeout errors. Answers are grounded in retrieved evidence and sized to the question. The SQLite memory service remains the durable transcript store.
