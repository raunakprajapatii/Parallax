"""Behavioral tests for Parallax's LangGraph orchestration layer."""

from app.agent.models import ChatRequest, SourceRecord, ToolResult
from app.agent.orchestrator import AgentOrchestrator
from time import sleep


class _RetryingJira:
    def __init__(self):
        self.calls = 0

    def search(self, source, query, limit=5, *, demo_mode=True):
        self.calls += 1
        if self.calls == 1:
            return ToolResult(toolName="search_jira", query=query, records=[], latencyMs=1,
                              error="jira request failed: HTTP 503")
        record = SourceRecord(id="jira:SCRUM-6", source="jira", title="Login flow",
                              content="Status: In Progress. Priority: High.",
                              metadata={"status": "In Progress", "priority": "High"})
        return ToolResult(toolName="search_jira", query=query, records=[record], latencyMs=1)


class _TraceSink:
    def __init__(self):
        self.events = []

    def record(self, event):
        self.events.append(event)


def test_agent_is_compiled_as_a_graph_with_explicit_work_and_general_paths():
    agent = AgentOrchestrator(_RetryingJira())
    graph = agent.workflow.get_graph()

    assert {"load_context", "answer_general", "select_sources", "retrieve_sources",
            "synthesize_answer", "persist_response"} <= set(graph.nodes)
    assert any(edge.source == "load_context" and edge.conditional for edge in graph.edges)
    assert any(edge.source == "retrieve_sources" and edge.target == "synthesize_answer" for edge in graph.edges)


def test_graph_retries_transient_connector_failure_and_returns_cited_result():
    connector = _RetryingJira()
    trace = _TraceSink()
    agent = AgentOrchestrator(connector, trace_recorder=trace)

    response = agent.run(ChatRequest(message="What is the status of SCRUM-6?", demoMode=False))

    assert connector.calls == 2
    assert response.citations[0].recordId == "jira:SCRUM-6"
    tool_event = next(event for event in trace.events if event["step"] == "tool_complete")
    assert tool_event["labels"]["retries"] == 1


def test_graph_does_not_retry_permission_errors():
    class Forbidden:
        calls = 0
        def search(self, source, query, limit=5, *, demo_mode=True):
            self.calls += 1
            return ToolResult(toolName="search_jira", query=query, records=[], latencyMs=1,
                              error="jira request failed: permission denied")

    connector = Forbidden()
    response = AgentOrchestrator(connector).run(
        ChatRequest(message="What is the status of SCRUM-6?", demoMode=False)
    )

    assert connector.calls == 1
    assert "missing permission" in response.answer
    assert not response.citations


def test_graph_retries_a_timed_out_read_only_tool_once():
    class SlowFirstCall:
        calls = 0
        def search(self, source, query, limit=5, *, demo_mode=True):
            self.calls += 1
            if self.calls == 1:
                sleep(0.08)
                return ToolResult(toolName="search_jira", query=query, records=[], latencyMs=80,
                                  error="late response")
            record = SourceRecord(id="jira:SCRUM-6", source="jira", title="Login flow",
                                  content="Status: In Progress.")
            return ToolResult(toolName="search_jira", query=query, records=[record], latencyMs=1)

    connector = SlowFirstCall()
    response = AgentOrchestrator(connector, tool_timeout_seconds=0.01).run(
        ChatRequest(message="What is the status of SCRUM-6?", demoMode=False)
    )

    assert connector.calls == 2
    assert response.citations[0].recordId == "jira:SCRUM-6"
