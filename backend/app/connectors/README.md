# Module C: Connectors and demo data

`ConnectorRegistry` is the agent-facing interface:

```python
registry.search("jira", query, limit=5, demo_mode=True)
```

Every result is an `app.agent.models.ToolResult` containing only normalized
`SourceRecord` values. In demo mode, the registry reads local JSON fixtures.
For live requests, Gmail, Jira, Notion, Calendar, and Drive connectors use
their configured credentials; set `CONNECTOR_ENABLE_LIVE=true` and
`demoMode:false` to use them.

## Jira and Notion OAuth (local single-user setup)

Create OAuth apps in Atlassian Developer Console and Notion Integrations. Set
their client IDs/secrets in the root `.env`. Register these exact callbacks:

- Jira: `http://localhost:8000/api/oauth/jira/callback`
- Notion: `http://localhost:8000/api/oauth/notion/callback`

Start the backend, then open `/api/oauth/jira/connect` or
`/api/oauth/notion/connect` and approve access. `/api/oauth/status` reports
connection state; `DELETE /api/oauth/jira` and `/api/oauth/notion` disconnect.
Jira uses the first site authorized by the Atlassian account. Both connectors
prefer OAuth tokens over static tokens and refresh them when supported. Live
search still requires `CONNECTOR_ENABLE_LIVE=true` and `demoMode:false`.

The local SQLite token table is for local single-user development only. Before
multi-user/production use, add user sessions and encrypt tokens at rest in a
managed secrets store. Deployed callbacks must use HTTPS.

## Gmail OAuth

Create a Google OAuth client of type **Web application**, add
`http://localhost:8000/api/oauth/gmail/callback` as an authorized redirect URI,
and configure the OAuth consent screen with your account as a test user if the
app is in Testing. Put that client's ID and secret in `GOOGLE_CLIENT_ID` and
`GOOGLE_CLIENT_SECRET`, then restart the backend and open
`/api/oauth/gmail/connect`. The app requests only
`https://www.googleapis.com/auth/gmail.readonly`. Check `/api/oauth/status`
and disconnect with `DELETE /api/oauth/gmail`.

Google may limit refresh-token lifetime while an external consent screen is in
Testing; if Gmail later disconnects, reconnect after adjusting the Google OAuth
publishing/test-user setup. Never put client secrets or tokens in the frontend.

## Google Drive retrieval

Connect Google Drive through `/api/oauth/drive/connect`, then choose a folder in
Knowledge sources. Chat retrieval reads supported text files, CSV/JSON, PDFs,
and Google Docs, Sheets, and Slides in that folder and its subfolders. The first
search ingests file text into a local SQLite passage index; later searches only
re-download files whose Drive `modifiedTime` changed. Prose is split into
overlapping passages and CSV is split by row. Passages are embedded locally
with `all-MiniLM-L6-v2`; cosine similarity and SQLite FTS5 BM25 rankings are
combined with reciprocal-rank fusion. The best passages are grouped under
their source file so citations link back to Drive. Removed files are dropped from the selected
folder's index on its next search. OAuth refresh tokens and the passage index
currently share the configured local SQLite database; keep it private and back
it up or rebuild it after deleting it.
