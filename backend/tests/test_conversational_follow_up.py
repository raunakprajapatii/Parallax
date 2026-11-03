from app.agent.models import ChatRequest, SourceRecord, ToolResult
from app.agent.orchestrator import AgentOrchestrator
from app.agent.synthesis import synthesize, synthesize_with_groq
from app.memory.service import MemoryService


class JiraOnlyConnector:
    def __init__(self):
        self.queries = []

    def search(self, source, query, limit=5, *, demo_mode=True):
        self.queries.append((source, query))
        issue = SourceRecord(
            id="jira:SCRUM-1", source="jira", title="Create UI for Auth",
            content="Status: To Do. Assignee: Jesse Pinkman. Priority: Medium.",
            url="https://example.atlassian.net/browse/SCRUM-1",
            metadata={"status": "To Do", "assignee": "Jesse Pinkman", "priority": "Medium"},
        )
        return ToolResult(toolName="search_jira", query=query, records=[issue], latencyMs=1)


def test_follow_up_keeps_jira_issue_context(tmp_path):
    memory = MemoryService(tmp_path / "chat.sqlite3")
    connector = JiraOnlyConnector()
    agent = AgentOrchestrator(connector, memory=memory)
    first = agent.run(ChatRequest(message="What is the status of Jira issue SCRUM-1?", demoMode=False))

    second = agent.run(ChatRequest(
        conversationId=first.conversationId,
        message="What is its priority?",
        demoMode=False,
    ))

    assert len(connector.queries) == 2
    assert connector.queries[1][0] == "jira"
    assert "SCRUM-1" in connector.queries[1][1]
    assert "priority" in connector.queries[1][1].casefold()
    assert "Medium priority" in second.answer


def test_groq_synthesis_includes_recent_chat_and_prefers_natural_answers(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return self

        def json(self):
            return {"choices": [{"message": {"content": "It is assigned to Jesse Pinkman 【1】. Want me to check another issue?"}}]}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr("app.agent.synthesis.httpx.post", fake_post)
    issue = SourceRecord(
        id="jira:SCRUM-1", source="jira", title="Create UI for Auth",
        content="Status: To Do. Assignee: Jesse Pinkman.",
        metadata={"status": "To Do", "assignee": "Jesse Pinkman"},
    )

    answer, citations = synthesize_with_groq(
        "Who is it assigned to?", [issue], "test-key", history=[
            {"role": "user", "content": "What is the status and assignee of Jira issue SCRUM-1?"},
            {"role": "assistant", "content": "SCRUM-1 is To Do."},
        ],
    )

    assert "Want me to check another issue?" in answer
    assert "[1]" in answer
    assert len(citations) == 1 and citations[0].recordId == "jira:SCRUM-1"
    messages = captured["json"]["messages"]
    assert "friendly work intelligence assistant" in messages[0]["content"]
    assert any("SCRUM-1" in message["content"] for message in messages[1:-1])
    assert any("Key fields: status: To Do; assignee: Jesse Pinkman" in message["content"] for message in messages)
    assert captured["json"]["include_reasoning"] is False
    assert captured["json"]["max_completion_tokens"] == 700


def test_extractive_fallback_summarizes_requested_jira_field_naturally():
    issue = SourceRecord(
        id="jira:SCRUM-1", source="jira", title="Create UI for Auth",
        content="Status: To Do. Assignee: Jesse Pinkman. Priority: Not set.",
        metadata={"status": "To Do", "assignee": "Jesse Pinkman", "priority": "Not set"},
    )

    answer, citations = synthesize("What about its priority?", [issue])

    assert answer.startswith("SCRUM-1 (Create UI for Auth) has no priority set. [1]")
    assert answer.endswith("Would you like me to check another Jira issue or summarize this issue's description?")
    assert citations[0].recordId == "jira:SCRUM-1"


def test_exact_jira_issue_fields_bypass_groq_to_prevent_invented_values(monkeypatch):
    def unexpected_model_call(*args, **kwargs):
        raise AssertionError("Exact issue field lookup should use Jira response fields directly")

    monkeypatch.setattr("app.agent.synthesis.httpx.post", unexpected_model_call)
    issue = SourceRecord(
        id="jira:SCRUM-2", source="jira", title="Create social media handles",
        content="Status: In Progress. Assignee: zoodiiac3. Priority: Not set.",
        metadata={"status": "In Progress", "assignee": "zoodiiac3", "priority": "Not set"},
    )

    answer, citations = synthesize_with_groq(
        "Who is SCRUM-2 assigned to?", [issue], "test-key", "openai/gpt-oss-20b"
    )

    assert answer.startswith("SCRUM-2 is assigned to zoodiiac3. [1]")
    assert citations[0].recordId == "jira:SCRUM-2"


def test_exact_jira_description_question_returns_clean_description():
    issue = SourceRecord(
        id="jira:SCRUM-2", source="jira", title="Create social media handles",
        content="Status: In Progress. Assignee: zoodiiac3. Priority: Not set. Create social media handles.",
        metadata={"status": "In Progress", "assignee": "zoodiiac3", "priority": "Not set",
                  "description": "Create YouTube, Instagram, and Facebook handles for the project."},
    )

    answer, citations = synthesize("What is the description of SCRUM-2?", [issue])

    assert "description:" in answer
    assert "Create YouTube, Instagram, and Facebook handles for the project." in answer
    assert "Status: In Progress" not in answer
    assert answer.endswith("Would you like me to check this issue's status or assignee?")
    assert citations[0].recordId == "jira:SCRUM-2"
