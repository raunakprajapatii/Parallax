"""Natural-language route and agent regression matrix across all connectors."""

import pytest

from app.agent.models import ChatRequest, SourceRecord, ToolResult
from app.agent.orchestrator import AgentOrchestrator
from app.agent.routing import is_follow_up, is_work_query, route_query


PROMPT_CASES = [
    # Gmail basics and common paraphrases
    ("gmail", "How many unread emails do I have?", ("gmail",)),
    ("gmail", "Do I have any unread messages?", ("gmail",)),
    ("gmail", "Show me my latest emails.", ("gmail",)),
    ("gmail", "Summarize my recent email threads.", ("gmail",)),
    ("gmail", "Who sent me an email today?", ("gmail",)),
    ("gmail", "Find messages from Maya Chen.", ("gmail",)),
    ("gmail", "Any important emails that need attention?", ("gmail",)),
    ("gmail", "Show my inbox.", ("gmail",)),
    ("gmail", "Have I received any messages from the supplier?", ("gmail",)),
    ("gmail", "Search Gmail for the launch approval email.", ("gmail",)),
    # Jira basics, paraphrases, and the screenshot regression
    ("jira", "check jira", ("jira",)),
    ("jira", "check jira for latest updates", ("jira",)),
    ("jira", "What tasks are currently assigned to me?", ("jira",)),
    ("jira", "Show my Jira tickets.", ("jira",)),
    ("jira", "Which issues are overdue?", ("jira",)),
    ("jira", "Any unresolved high-priority work?", ("jira",)),
    ("jira", "What is the status of SCRUM-6?", ("jira",)),
    ("jira", "What's on my plate?", ("jira",)),
    ("jira", "What should I work on next?", ("jira",)),
    ("jira", "Which tickets need priority attention?", ("jira",)),
    # Notion basics and paraphrases
    ("notion", "Find my project documentation.", ("notion",)),
    ("notion", "Can you find the project brief?", ("notion",)),
    ("notion", "Summarize my latest meeting notes.", ("notion",)),
    ("notion", "Find the meeting minutes.", ("notion",)),
    ("notion", "What are the action items in my notes?", ("notion",)),
    ("notion", "Check Notion for the latest updates.", ("notion",)),
    ("notion", "What does the owner list say?", ("notion",)),
    ("notion", "Find the project roadmap.", ("notion",)),
    # Cross-source queries
    ("cross", "Find emails related to my current Jira tasks.", ("jira", "gmail")),
    ("cross", "Compare Jira tasks with Notion action items.", ("jira", "notion")),
    ("cross", "Are there emails mentioning unresolved Jira issues?", ("jira", "gmail")),
    ("cross", "What is blocking the Atlas launch and who owns each blocker?", ("gmail", "jira", "notion")),
    ("cross", "Search all sources for launch risks.", ("gmail", "jira", "notion")),
    ("cross", "Find Gmail messages and Notion notes about project status.", ("gmail", "notion")),
    # Workplace intent without naming a provider
    ("work", "What should I work on next?", ("jira",)),
    ("work", "What needs my attention today?", ("gmail", "jira")),
    ("work", "What changed in the project recently?", ("gmail", "jira", "notion")),
    # These must remain general chat and avoid connector calls
    ("general", "Hi, how are you?", ()),
    ("general", "Explain photosynthesis in simple terms.", ()),
    ("general", "What's the weather like?", ()),
    ("general", "Tell me a joke.", ()),
]


class RecordingConnectors:
    def __init__(self):
        self.calls = []
        self.records = {
            "gmail": SourceRecord(id="gmail:test", source="gmail", title="Recent email",
                                  content="Maya sent an update about the launch.", author="Maya Chen",
                                  createdAt="2026-11-02T08:30:00Z"),
            "jira": SourceRecord(id="jira:SCRUM-6", source="jira", title="Launch issue",
                                 content="Status: In Progress. Assignee: Maya Chen. Priority: High.",
                                 metadata={"status": "In Progress", "assignee": "Maya Chen", "priority": "High"}),
            "notion": SourceRecord(id="notion:test", source="notion", title="Project notes",
                                   content="Maya Chen owns the project notes. Action items for the launch.",
                                   author="Maya Chen"),
        }

    def search(self, source, query, limit=5, *, demo_mode=True):
        self.calls.append((source, query))
        return ToolResult(toolName=f"search_{source}", query=query,
                          records=[self.records[source]], latencyMs=1)


@pytest.mark.parametrize("category,prompt,expected_sources", PROMPT_CASES)
def test_natural_prompt_routes_to_expected_tools_and_returns_grounded_evidence(category, prompt, expected_sources):
    connectors = RecordingConnectors()
    response = AgentOrchestrator(connectors).run(ChatRequest(message=prompt, demoMode=False))

    assert tuple(source for source, _ in connectors.calls) == expected_sources, (category, prompt)
    if expected_sources:
        assert response.citations
        assert {citation.source for citation in response.citations} <= set(expected_sources)
    else:
        assert not response.citations


@pytest.mark.parametrize("prompt", [
    "What about its priority?", "Who is it assigned to?", "And the owner?",
    "How many?", "Why?", "Which one?", "What about today?", "Can you expand on that?",
    "What's the latest?", "Tell me more.", "Any updates?", "What changed since then?",
    "What was the sender?", "What's the subject?", "What happened next?",
])
def test_short_follow_up_and_referential_prompts_keep_conversation_context(prompt):
    assert is_follow_up(prompt), prompt


@pytest.mark.parametrize("prompt", [
    "What is the weather?", "How do I make pasta?", "Tell me about the solar system.",
    "Can you explain recursion?", "Write a birthday greeting.",
])
def test_general_questions_do_not_route_to_private_connectors(prompt):
    assert not is_work_query(prompt)


@pytest.mark.parametrize("first,follow_up,source,answer_fact", [
    ("Show me my latest emails.", "Who sent it?", "gmail", "Maya Chen"),
    ("What is the status of SCRUM-6?", "What is its priority?", "jira", "High"),
    ("Summarize my latest meeting notes.", "Who owns it?", "notion", "Maya Chen"),
])
def test_follow_up_run_reuses_prior_source_and_evidence(first, follow_up, source, answer_fact, tmp_path):
    from app.memory.service import MemoryService

    connectors = RecordingConnectors()
    agent = AgentOrchestrator(connectors, memory=MemoryService(tmp_path / f"{source}.sqlite3"))
    first_response = agent.run(ChatRequest(message=first, demoMode=False))
    second_response = agent.run(ChatRequest(conversationId=first_response.conversationId,
                                            message=follow_up, demoMode=False))

    assert [called for called, _ in connectors.calls] == [source, source]
    assert second_response.citations
    assert answer_fact.casefold() in second_response.answer.casefold()
