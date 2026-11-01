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
