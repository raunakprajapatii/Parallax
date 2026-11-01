from fastapi.testclient import TestClient

from app.agent.orchestrator import AgentOrchestrator
from app.api.app import create_app
from app.memory.service import MemoryService


class UnusedConnectors:
    def search(self, *args, **kwargs):
        raise AssertionError("general chat should not search work connectors")


def test_chat_transcript_can_be_listed_and_reopened_from_sqlite(tmp_path):
    memory = MemoryService(tmp_path / "chat.sqlite3")
    orchestrator = AgentOrchestrator(UnusedConnectors(), memory=memory)
    app = create_app(orchestrator=orchestrator)
    app.state.memory_service = memory
    client = TestClient(app)

    response = client.post("/api/chat", json={"message": "Hello", "demoMode": True})
    assert response.status_code == 200
    conversation_id = response.json()["conversationId"]

    listed = client.get("/api/conversations")
    assert listed.status_code == 200
    assert listed.json()[0]["conversationId"] == conversation_id
    assert listed.json()[0]["title"] == "Hello"

    opened = client.get(f"/api/conversations/{conversation_id}")
    assert opened.status_code == 200
    messages = opened.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[1]["metadata"]["traceId"] == response.json()["traceId"]


def test_missing_conversation_returns_404(tmp_path):
    memory = MemoryService(tmp_path / "chat.sqlite3")
    app = create_app(orchestrator=AgentOrchestrator(UnusedConnectors(), memory=memory))
    app.state.memory_service = memory
    response = TestClient(app).get("/api/conversations/missing")
    assert response.status_code == 404
