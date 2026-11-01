"""Gmail connector with a deterministic local Atlas Launch implementation."""

from app.agent.models import SourceRecord, ToolResult

from .base import Connector
from .demo import DEMO_DATA_DIR


class GmailConnector(Connector):
    source = "gmail"
    tool_name = "search_gmail"

    def __init__(self):
        super().__init__(DEMO_DATA_DIR / "gmail.json")

    def _matches(self, record: SourceRecord, query: str) -> bool:
        text = query.casefold()
        return any(term in text for term in ("email", "mail", "approval", "handoff", "design", "atlas")) and "atlas" in self._search_text(record)


def search_gmail(query: str, limit: int = 5) -> ToolResult:
    return GmailConnector().search(query, limit)
