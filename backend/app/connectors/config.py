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
    gmail_refresh_token: str | None = None
    google_client_id: str | None = None
    google_client_secret: str | None = None
    jira_base_url: str | None = None
    jira_email: str | None = None
    jira_token: str | None = None
    notion_token: str | None = None
    notion_version: str = "2022-06-28"
    jira_oauth_client_id: str | None = None
    jira_oauth_client_secret: str | None = None
    notion_oauth_client_id: str | None = None
    notion_oauth_client_secret: str | None = None
    oauth_db_path: str = "backend/data/live_data_intelligence.sqlite3"
    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    llm_provider: str = "groq"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"

    @classmethod
    def from_environment(cls) -> "ConnectorConfig":
        return cls(
            demo_mode=os.getenv("CONNECTOR_DEMO_MODE", "true").casefold() != "false",
            enable_live=os.getenv("CONNECTOR_ENABLE_LIVE", "false").casefold() == "true",
            gmail_token=os.getenv("GMAIL_ACCESS_TOKEN"),
            gmail_refresh_token=os.getenv("GMAIL_REFRESH_TOKEN"),
            google_client_id=os.getenv("GOOGLE_CLIENT_ID"),
            google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
            jira_base_url=os.getenv("JIRA_BASE_URL"),
            jira_email=os.getenv("JIRA_EMAIL"),
            jira_token=os.getenv("JIRA_API_TOKEN"),
            notion_token=os.getenv("NOTION_API_KEY") or os.getenv("NOTION_TOKEN"),
            notion_version=os.getenv("NOTION_VERSION", "2022-06-28"),
            jira_oauth_client_id=os.getenv("JIRA_OAUTH_CLIENT_ID"),
            jira_oauth_client_secret=os.getenv("JIRA_OAUTH_CLIENT_SECRET"),
            notion_oauth_client_id=os.getenv("NOTION_OAUTH_CLIENT_ID"),
            notion_oauth_client_secret=os.getenv("NOTION_OAUTH_CLIENT_SECRET"),
            oauth_db_path=os.getenv("OAUTH_DB_PATH", "backend/data/live_data_intelligence.sqlite3"),
            groq_api_key=os.getenv("GROQ_API_KEY"),
            groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            llm_provider=os.getenv("LLM_PROVIDER", "groq").casefold(),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        )

    def live_credentials_configured(self) -> bool:
        return bool(self.enable_live and self.gmail_token and self.jira_base_url and self.jira_email and self.jira_token and self.notion_token)
