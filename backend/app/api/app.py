"""FastAPI application and shared service wiring."""

from pathlib import Path
from dataclasses import replace

from dotenv import load_dotenv

from fastapi import FastAPI

from .chat import router
from .calendar import router as calendar_router
from .oauth import router as oauth_router
from .drive import router as drive_router
from app.agent.orchestrator import AgentOrchestrator
from app.connectors.config import ConnectorConfig
from app.connectors.registry import ConnectorRegistry
from app.memory.service import MemoryService
from app.observability.trace_store import TraceStore
from app.connectors.oauth import OAuthStore

BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT.parent / ".env")


def create_app(*, orchestrator=None) -> FastAPI:
    app = FastAPI(title="Parallax Work Intelligence API")
    app.include_router(router)
    app.include_router(calendar_router)
    app.include_router(oauth_router)
    app.include_router(drive_router)
    config = ConnectorConfig.from_environment()
    db_path = BACKEND_ROOT.parent / "backend" / "data" / "live_data_intelligence.sqlite3"
    config = replace(config, oauth_db_path=str(db_path))
    memory = MemoryService(db_path)
    traces = TraceStore(db_path)
    app.state.memory_service = memory
    app.state.trace_store = traces
    app.state.oauth_store = OAuthStore(db_path)
    app.state.agent_orchestrator = orchestrator or AgentOrchestrator(
        ConnectorRegistry(config), memory=memory, trace_recorder=traces,
        groq_api_key=config.groq_api_key, groq_model=config.groq_model,
        llm_provider=config.llm_provider, gemini_api_key=config.gemini_api_key,
        gemini_model=config.gemini_model,
        calendar_connected=bool(app.state.oauth_store.get("calendar")),
        calendar_store=app.state.oauth_store
    )
    return app


app = create_app()
