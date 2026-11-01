"""Jira connector with a deterministic local Atlas Launch implementation."""

from app.agent.models import SourceRecord, ToolResult

from .base import Connector
from .demo import DEMO_DATA_DIR


class JiraConnector(Connector):
    source = "jira"
    tool_name = "search_jira"

    def __init__(self):
        super().__init__(DEMO_DATA_DIR / "jira.json")

    def _matches(self, record: SourceRecord, query: str) -> bool:
        text = query.casefold()
        return "jira" in text or "ticket" in text or "issue" in text or "atl-" in text or "block" in text or "status" in text


def search_jira(query: str, limit: int = 5) -> ToolResult:
    return JiraConnector().search(query, limit)
