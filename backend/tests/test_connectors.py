"""Contract and Atlas Launch retrieval tests for Module C."""

from app.agent.models import SourceRecord, ToolResult
from app.connectors import ConnectorRegistry
from app.connectors.gmail import search_gmail
from app.connectors.jira import search_jira
from app.connectors.notion import search_notion


def assert_contract(result: ToolResult, tool_name: str, source: str) -> None:
    assert isinstance(result, ToolResult)
    assert result.toolName == tool_name
    assert result.latencyMs >= 0
    assert result.error is None
    assert result.records
    assert all(isinstance(record, SourceRecord) for record in result.records)
    assert all(record.source == source and record.id.startswith(f"{source}:") for record in result.records)
    assert all(isinstance(value, str) for record in result.records for value in record.metadata.values())


def test_gmail_retrieves_design_handoff_and_approval_evidence():
    result = search_gmail("What email blockers affect the Atlas launch?")
    assert_contract(result, "search_gmail", "gmail")
    assert {record.id for record in result.records} == {"gmail:atlas-design-handoff", "gmail:atlas-approval-request"}


def test_jira_retrieves_blocked_ticket_and_review_ticket():
    result = search_jira("What is blocking Atlas and what is the Jira status?")
    assert_contract(result, "search_jira", "jira")
    assert {record.id for record in result.records} == {"jira:ATL-42", "jira:ATL-51"}
    assert result.records[0].metadata["status"] == "Blocked"


def test_notion_retrieves_launch_context_and_owners():
    result = search_notion("What does the Atlas launch brief say about owners and launch date?")
    assert_contract(result, "search_notion", "notion")
    assert {record.id for record in result.records} == {"notion:atlas-launch-brief", "notion:atlas-owner-list"}
    assert any("2026-12-15" in record.content for record in result.records)


def test_registry_is_credential_free_in_demo_mode():
    registry = ConnectorRegistry()
    result = registry.search("jira", "What blocks the Atlas launch?", demo_mode=True)
    assert_contract(result, "search_jira", "jira")


def test_live_mode_is_disabled_by_default_without_calling_external_services():
    result = ConnectorRegistry().search("gmail", "Atlas", demo_mode=False)
    assert result.records == []
    assert "disabled" in (result.error or "")
