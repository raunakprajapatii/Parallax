"""Common source registry consumed by the agent orchestrator."""

from app.agent.models import SourceName, ToolResult

from .config import ConnectorConfig
from .gmail import GmailConnector
from .jira import JiraConnector
from .notion import NotionConnector
from .live import LiveConnector
from .drive import DriveConnector
from .calendar_source import CalendarConnector


class ConnectorRegistry:
    """Dispatch searches to demo connectors using the agreed agent interface."""

    def __init__(self, config: ConnectorConfig | None = None):
        self.config = config or ConnectorConfig()
        self._connectors = {
            "gmail": GmailConnector(),
            "jira": JiraConnector(),
            "notion": NotionConnector(),
        }
        self._drive = DriveConnector(self.config)
        self._calendar = CalendarConnector(self.config)

    def search(self, source: SourceName, query: str, limit: int = 5, *, demo_mode: bool = True) -> ToolResult:
        if source == "calendar":
            if not demo_mode and not self.config.enable_live:
                return ToolResult(toolName="search_calendar", query=" ".join(query.split()), records=[], latencyMs=0,
                                  error="Live connectors are disabled; set CONNECTOR_ENABLE_LIVE=true.")
            return self._calendar.search(query, limit, demo_mode=demo_mode)
        if source == "drive":
            if demo_mode:
                return self._drive.demo_search(query, limit)
            if not self.config.enable_live:
                return ToolResult(toolName="search_drive", query=" ".join(query.split()), records=[], latencyMs=0,
                                  error="Live connectors are disabled; set CONNECTOR_ENABLE_LIVE=true.")
            return self._drive.search(query, limit)
        if demo_mode:
            return self._connectors[source].search(query, limit)
        if not self.config.enable_live:
            return ToolResult(toolName=f"search_{source}", query=" ".join(query.split()), records=[], latencyMs=0,
                              error="Live connectors are disabled; set CONNECTOR_ENABLE_LIVE=true.")
        return LiveConnector(source, self.config).search(query, limit)

    @property
    def drive(self) -> DriveConnector:
        return self._drive
