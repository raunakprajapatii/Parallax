# Live Data Intelligence Agent

An agentic work assistant that searches Gmail, Jira, and Notion, combines retrieved evidence into cited answers, and records a visible run trace. See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the product scope, module ownership, API contracts, demo story, and evaluation plan.

## Team modules

| Module | Ownership | Main area |
|---|---|---|
| A — Frontend & Experience | UI and chat workflow | `frontend/` |
| B — Agent & API | Routing, orchestration, synthesis | `backend/app/agent/`, `backend/app/api/` |
| C — Connectors & Demo Data | Gmail/Jira/Notion adapters and fixtures | `backend/app/connectors/`, `backend/app/data/demo/` |
| D — Memory, Observability & Evaluation | Persistence, traces, evaluation | `backend/app/memory/`, `backend/app/observability/`, `backend/tests/` |

Keep module implementations in their owned folders. Coordinate changes to shared contracts in `PROJECT_PLAN.md` with the team before changing field names or endpoint behavior.

## Local setup

1. Copy `.env.example` to `.env` and fill only the credentials you intend to use. Demo mode works without external service credentials. Keep `.env` private; it is ignored by Git.
2. Create and activate a Python virtual environment from the repository root.
3. Install backend dependencies and start the API:

   ```powershell
   python -m pip install -r backend/requirements.txt
   uvicorn app.api.app:app --reload --app-dir backend
   ```

4. Open `http://localhost:8000/docs` to inspect the API. Frontend setup instructions will be added when Module A establishes its package scripts.

## Working together

- Agree on the contracts in `PROJECT_PLAN.md` before parallel implementation.
- Work on separate branches and keep commits focused on your module.
- Do not commit `.env`, access tokens, real work data, local databases, or generated build/cache files.
- Keep demo fixtures synthetic and usable without OAuth/API credentials.
- Integrate early: frontend against the chat response contract, agent against connector and memory interfaces.

## Configuration

`.env.example` lists the shared configuration names. Optional service credentials should remain blank for demo mode. If a real key is accidentally committed, revoke it immediately; deleting it in a later commit does not remove it from Git history.
