"""Configuration for optional live integrations.

Demo mode is deliberately the default and never requires credentials. Live
integration is opt-in so a fresh checkout is safe to run locally.
"""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ConnectorConfig:
    demo_mode: bool = True
    enable_live: bool = False
    gmail_token: str | None = None
    jira_base_url: str | None = None
    jira_token: str | None = None
    notion_token: str | None = None

    @classmethod
    def from_environment(cls) -> "ConnectorConfig":
        return cls(
            demo_mode=os.getenv("CONNECTOR_DEMO_MODE", "true").casefold() != "false",
            enable_live=os.getenv("CONNECTOR_ENABLE_LIVE", "false").casefold() == "true",
            gmail_token=os.getenv("GMAIL_ACCESS_TOKEN"),
            jira_base_url=os.getenv("JIRA_BASE_URL"),
            jira_token=os.getenv("JIRA_API_TOKEN"),
            notion_token=os.getenv("NOTION_TOKEN"),
        )

    def live_credentials_configured(self) -> bool:
        return bool(self.enable_live and self.gmail_token and self.jira_base_url and self.jira_token and self.notion_token)
