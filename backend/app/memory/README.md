# Memory service

`MemoryService` uses SQLite (`MEMORY_DB_PATH`, default `backend/data/memory.sqlite3`).
Session messages are tied to `conversation_id` and retain the latest six messages
by default. `clear_session(conversation_id)` removes session context.

Long-term writes must call `remember(..., consent_source=...)` with exactly
`user_instruction` or `user_approval`. Omitting it raises `ConsentRequired`;
do not translate a suggestion or inferred preference into consent. `forget()`
deletes one memory by ID or exact text, or all memories for a user. Memory rows
include the fields listed in the project plan, including consent source and
last-use timestamp.

Example:

```python
memory.remember(user_id, "Atlas is the Q4 launch project", consent_source="user_instruction")
memory.list_memories(user_id)
memory.forget(user_id, memory_id=memory_id)
```
