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


@router.get("/conversations")
def list_conversations(request: Request) -> list[dict[str, object]]:
    memory = getattr(request.app.state, "memory_service", None)
    return memory.list_conversations() if memory else []


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, request: Request) -> dict[str, object]:
    memory = getattr(request.app.state, "memory_service", None)
    if memory is None:
        raise HTTPException(status_code=503, detail="Conversation storage is not configured")
    messages = memory.get_conversation(conversation_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"conversationId": conversation_id, "messages": messages}
