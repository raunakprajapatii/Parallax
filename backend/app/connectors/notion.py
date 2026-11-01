"""Notion connector with a deterministic local Atlas Launch implementation."""

from app.agent.models import SourceRecord, ToolResult

from .base import Connector
from .demo import DEMO_DATA_DIR


class NotionConnector(Connector):
    source = "notion"
    tool_name = "search_notion"

    def __init__(self):
        super().__init__(DEMO_DATA_DIR / "notion.json")

    def _matches(self, record: SourceRecord, query: str) -> bool:
        text = query.casefold()
        return any(term in text for term in ("notion", "brief", "owner", "launch", "roadmap", "document", "atlas")) and "atlas" in self._search_text(record)


def search_notion(query: str, limit: int = 5) -> ToolResult:
    return NotionConnector().search(query, limit)
