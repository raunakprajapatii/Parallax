"""Deterministic route → retrieve → rank → synthesize → validate pipeline."""

from datetime import datetime, timezone
import os

from .citations import validate_citations
from .interfaces import ConnectorRegistry, MemoryService, TraceRecorder
from .models import ChatRequest, ChatResponse, TraceEvent
from .workflow import build_agent_workflow, invoke_agent_workflow


class AgentOrchestrator:
    def __init__(self, connectors: ConnectorRegistry, memory: MemoryService | None = None,
                 trace_recorder: TraceRecorder | None = None, *,
                 tool_timeout_seconds: float | None = None,
                 groq_api_key: str | None = None, groq_model: str = "llama-3.3-70b-versatile",
                 llm_provider: str = "groq", gemini_api_key: str | None = None,
                 gemini_model: str = "gemini-2.5-flash", calendar_connected: bool = False,
                 calendar_store=None):
        self.connectors = connectors
        self.memory = memory
        self.trace_recorder = trace_recorder
        # Live Notion retrieval performs a search plus a page-block fetch;
        # three seconds was too short for that normal two-request path.
        self.tool_timeout_seconds = (tool_timeout_seconds if tool_timeout_seconds is not None
                                     else float(os.getenv("AGENT_TOOL_TIMEOUT_SECONDS", "12")))
        self.groq_api_key = groq_api_key
        self.groq_model = groq_model
        self.llm_provider = llm_provider.casefold()
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.calendar_connected = calendar_connected
        self.calendar_store = calendar_store
        self.workflow = build_agent_workflow(self)

    def has_calendar_connection(self) -> bool:
        return bool(self.calendar_store.get("calendar")) if self.calendar_store else self.calendar_connected

    def _trace(self, trace_id: str, step: str, **fields: object) -> None:
        step_map = {"route_complete": "source_selected", "tool_error": "tool_complete",
                    "citation_validation_complete": "answer_complete", "synthesis_complete": "answer_complete"}
        step = step_map.get(step, step)
        standard = {key: fields.pop(key) for key in ("tool", "durationMs", "recordCount") if key in fields}
        raw_error = fields.pop("error", None)
        error_type = fields.pop("errorType", None)
        status = "error" if error_type or raw_error else "success"
        if raw_error:
            error_text = str(raw_error).casefold()
            fields["errorCategory"] = ("permission_denied" if "permission" in error_text or "403" in error_text
                                       else "authentication" if "401" in error_text or "auth" in error_text
                                       else "provider_error")
        if error_type:
            fields["errorCategory"] = str(error_type)
        # Module D stores safe labels and recognized event fields, not arbitrary details.
        standard["labels"] = fields
        standard["status"] = status
        event = TraceEvent(traceId=trace_id, step=step, timestamp=datetime.now(timezone.utc).isoformat(), **standard)
        if self.trace_recorder:
            self.trace_recorder.record(event.model_dump(exclude_none=True))

    def run(self, request: ChatRequest) -> ChatResponse:
        return invoke_agent_workflow(self, request)
