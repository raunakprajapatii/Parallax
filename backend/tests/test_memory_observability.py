import pytest

from backend.app.memory import ConsentRequired, MemoryService
from backend.app.observability import TraceEvent, TraceStore


def test_long_term_memory_requires_explicit_consent_and_can_be_forgotten(tmp_path):
    memory = MemoryService(tmp_path / "memory.sqlite3")
    with pytest.raises(ConsentRequired):
        memory.remember("demo-user", "Atlas is the Q4 launch")
    saved = memory.remember("demo-user", "Atlas is the Q4 launch", consent_source="user_instruction")
    assert memory.list_memories("demo-user", touch=False)[0]["id"] == saved["id"]
    assert memory.forget("demo-user", memory_id=saved["id"]) == 1
    assert memory.list_memories("demo-user", touch=False) == []


def test_session_context_is_bounded_and_clearable(tmp_path):
    memory = MemoryService(tmp_path / "memory.sqlite3", session_limit=2)
    memory.add_message("conversation-1", "user", "first")
    memory.add_message("conversation-1", "assistant", "second")
    memory.add_message("conversation-1", "user", "third")
    assert [m["content"] for m in memory.get_session("conversation-1")] == ["second", "third"]
    assert memory.clear_session("conversation-1") == 3


def test_saved_conversation_keeps_full_transcript_and_response_metadata(tmp_path):
    memory = MemoryService(tmp_path / "memory.sqlite3", session_limit=2)
    memory.add_message("conversation-2", "user", "first question")
    memory.add_message("conversation-2", "assistant", "first answer", {"citations": []})
    memory.add_message("conversation-2", "user", "second question")
    memory.add_message("conversation-2", "assistant", "second answer", {"traceId": "run_2"})
    assert len(memory.get_session("conversation-2")) == 2
    transcript = memory.get_conversation("conversation-2")
    assert [message["content"] for message in transcript] == [
        "first question", "first answer", "second question", "second answer",
    ]
    assert transcript[-1]["metadata"]["traceId"] == "run_2"
    assert memory.list_conversations()[0]["title"] == "first question"


def test_trace_persists_documented_tool_complete_contract_and_record_ids(tmp_path):
    traces = TraceStore(tmp_path / "trace.sqlite3")
    traces.record_tool_result("run_demo", {
        "toolName": "search_jira", "query": "Atlas blocker", "latencyMs": 117,
        "records": [{"id": "jira:ATL-42"}],
    }, timestamp="2026-11-01T00:00:00Z")
    event = traces.get_trace("run_demo")[0]
    assert {key: event[key] for key in ("traceId", "step", "tool", "durationMs", "recordCount", "timestamp")} == {
        "traceId": "run_demo", "step": "tool_complete", "tool": "search_jira",
        "durationMs": 117, "recordCount": 1, "timestamp": "2026-11-01T00:00:00Z",
    }
    assert event["recordIds"] == ["jira:ATL-42"]
    assert traces.delete_trace("run_demo") == 1


def test_trace_rejects_negative_duration():
    with pytest.raises(ValueError):
        TraceEvent(traceId="run_demo", step="tool_complete", tool="search_jira", durationMs=-1)
