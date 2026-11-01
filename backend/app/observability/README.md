# Run trace store

`TraceStore` persists trace events to SQLite (`TRACE_DB_PATH`, default shared
`backend/data/memory.sqlite3`). The core JSON event fields follow the agreed
contract: `traceId`, `step`, `tool`, `durationMs`, `recordCount`, and ISO
`timestamp`. `record_tool_result()` accepts the normalized connector
`ToolResult` (`toolName`, `query`, `records`, `latencyMs`, optional `error`)
and stores each returned `SourceRecord.id` for evaluation and citation audits.

Additional `labels`, `status`, and `error` fields are structured, user-safe
metadata. Record decisions as short labels such as
`{"selected_sources":["jira","gmail"]}`; never persist private chain-of-thought.
Events are append-only during a run and can be listed or deleted by `traceId`.
