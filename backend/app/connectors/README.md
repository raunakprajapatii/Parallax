# Module C: Connectors and demo data

`ConnectorRegistry` is the agent-facing interface:

```python
registry.search("jira", query, limit=5, demo_mode=True)
```

Every result is an `app.agent.models.ToolResult` containing only normalized
`SourceRecord` values. The default registry reads the local Atlas Launch JSON
fixtures and does not access credentials or the network. Live integration is
reserved for a future adapter and is disabled unless explicitly enabled in
`ConnectorConfig`.

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
