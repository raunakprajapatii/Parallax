"""FastAPI chat endpoint and injectable Module B dependencies."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.agent.models import ChatRequest, ChatResponse
from app.agent.orchestrator import AgentOrchestrator

router = APIRouter(prefix="/api", tags=["chat"])


def get_orchestrator(request: Request) -> AgentOrchestrator:
    orchestrator = getattr(request.app.state, "agent_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(status_code=503, detail="Agent connectors are not configured")
    return orchestrator


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, orchestrator: AgentOrchestrator = Depends(get_orchestrator)) -> ChatResponse:
    return orchestrator.run(payload)
