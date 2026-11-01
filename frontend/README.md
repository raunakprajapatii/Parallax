# Atlas Intelligence frontend

React, TypeScript, and Vite frontend for the Live Data Intelligence Agent. The interface posts questions to the documented `POST /api/chat` endpoint and renders the returned answer, citations, conversation ID, trace ID, and memory usage.

## Run locally

```powershell
cd frontend
npm install
npm run dev
```

Vite serves the app at `http://localhost:3000` and proxies `/api` requests to `http://localhost:8000`. Start the backend separately using the root project instructions.

If the chat endpoint cannot be reached due to a network connection failure, the frontend automatically switches to a clearly labeled Atlas demo response. The isolated mock is in `src/mockApi.ts`. To return to backend mode, reload the page after starting the API.

## Checks

```powershell
npm run build
npm run lint
```

The chat response contract does not include source record content or per-tool trace events. The source detail dialog therefore displays only citation fields supplied by the API, and the trace panel identifies the run and available response metadata. Connector status endpoints are not defined in `PROJECT_PLAN.md`.
