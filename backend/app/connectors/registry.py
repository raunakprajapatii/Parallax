"""Common source registry consumed by the agent orchestrator."""

from app.agent.models import SourceName, ToolResult

from .config import ConnectorConfig
from .gmail import GmailConnector
from .jira import JiraConnector
from .notion import NotionConnector
from .live import LiveConnector


class ConnectorRegistry:
    """Dispatch searches to demo connectors using the agreed agent interface."""

    def __init__(self, config: ConnectorConfig | None = None):
        self.config = config or ConnectorConfig()
        self._connectors = {
            "gmail": GmailConnector(),
            "jira": JiraConnector(),
            "notion": NotionConnector(),
        }

    def search(self, source: SourceName, query: str, limit: int = 5, *, demo_mode: bool = True) -> ToolResult:
        if demo_mode:
            return self._connectors[source].search(query, limit)
        if not self.config.enable_live:
            return ToolResult(toolName=f"search_{source}", query=" ".join(query.split()), records=[], latencyMs=0,
                              error="Live connectors are disabled; set CONNECTOR_ENABLE_LIVE=true.")
        return LiveConnector(source, self.config).search(query, limit)
