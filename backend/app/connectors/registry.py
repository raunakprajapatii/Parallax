"""Common source registry consumed by the agent orchestrator."""

from app.agent.models import SourceName, ToolResult

from .config import ConnectorConfig
from .gmail import GmailConnector
from .jira import JiraConnector
from .notion import NotionConnector


class ConnectorRegistry:
    """Dispatch searches to demo connectors using the agreed agent interface."""

    def __init__(self, config: ConnectorConfig | None = None):
        self.config = config or ConnectorConfig()
        # Live adapters are intentionally not constructed here. This keeps a
        # demo run credential-free and leaves provider SDKs outside the MVP.
        self._connectors = {
            "gmail": GmailConnector(),
            "jira": JiraConnector(),
            "notion": NotionConnector(),
        }

    def search(self, source: SourceName, query: str, limit: int = 5, *, demo_mode: bool = True) -> ToolResult:
        if not demo_mode or not self.config.demo_mode:
            return ToolResult(toolName=f"search_{source}", query=" ".join(query.split()), records=[], latencyMs=0,
                              error="Live connectors are disabled; enable them explicitly in ConnectorConfig.")
        return self._connectors[source].search(query, limit)
