"""Deterministic route → retrieve → rank → synthesize → validate pipeline."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import os
from time import perf_counter
from uuid import uuid4

from .citations import validate_citations
from .interfaces import ConnectorRegistry, MemoryService, TraceRecorder
from .models import ChatRequest, ChatResponse, SourceName, ToolResult, TraceEvent
from .routing import retrieval_query, route_query, is_work_query, is_follow_up
from .synthesis import INSUFFICIENT_ANSWER, synthesize, synthesize_with_groq, answer_general_with_groq

_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="agent-tool")


class AgentOrchestrator:
    def __init__(self, connectors: ConnectorRegistry, memory: MemoryService | None = None,
                 trace_recorder: TraceRecorder | None = None, *,
                 tool_timeout_seconds: float | None = None,
                 groq_api_key: str | None = None, groq_model: str = "llama-3.3-70b-versatile"):
        self.connectors = connectors
        self.memory = memory
        self.trace_recorder = trace_recorder
        # Live Notion retrieval performs a search plus a page-block fetch;
        # three seconds was too short for that normal two-request path.
        self.tool_timeout_seconds = (tool_timeout_seconds if tool_timeout_seconds is not None
                                     else float(os.getenv("AGENT_TOOL_TIMEOUT_SECONDS", "12")))
        self.groq_api_key = groq_api_key
        self.groq_model = groq_model

    def _trace(self, trace_id: str, step: str, **fields: object) -> None:
        step_map = {"route_complete": "source_selected", "tool_error": "tool_complete",
                    "citation_validation_complete": "answer_complete", "synthesis_complete": "answer_complete"}
        step = step_map.get(step, step)
        standard = {key: fields.pop(key) for key in ("tool", "durationMs", "recordCount") if key in fields}
        status = "error" if "errorType" in fields or fields.get("error") else "success"
        # Module D stores safe labels and recognized event fields, not arbitrary details.
        standard["labels"] = fields
        standard["status"] = status
        event = TraceEvent(traceId=trace_id, step=step, timestamp=datetime.now(timezone.utc).isoformat(), **standard)
        if self.trace_recorder:
            self.trace_recorder.record(event.model_dump(exclude_none=True))

    def run(self, request: ChatRequest) -> ChatResponse:
        trace_id = f"run_{uuid4().hex}"
        conversation_id = request.conversationId or f"conversation_{uuid4().hex}"
        history: list[dict[str, str]] = []
        if self.memory:
            try:
                history = [{"role": item["role"], "content": item["content"]}
                           for item in self.memory.get_session(conversation_id, limit=8)
                           if item.get("role") in {"user", "assistant"} and item.get("content")]
            except (AttributeError, NotImplementedError, KeyError):
                history = []
        previous_work_query = next((item["content"] for item in reversed(history)
                                    if item["role"] == "user" and is_work_query(item["content"])), None)
        contextual_work_follow_up = bool(
            previous_work_query and not is_work_query(request.message) and is_follow_up(request.message)
        )
        is_work_turn = is_work_query(request.message) or contextual_work_follow_up
        if not is_work_turn:
            conversational_reply = answer_general_with_groq(
                request.message, self.groq_api_key, self.groq_model, history=history
            )
            self._trace(trace_id, "route_complete", selectedSources=[], reason="small_talk")
            memory_used: list[str] = []
            if self.memory:
                try:
                    memory_used = self.memory.get_relevant(conversation_id, request.message)[:6]
                    self.memory.add_message(conversation_id, "user", request.message,
                                            {"demoMode": request.demoMode})
                    self.memory.add_message(conversation_id, "assistant", conversational_reply,
                                            {"citations": [], "traceId": trace_id,
                                             "memoryUsed": memory_used, "demoMode": request.demoMode})
                except (AttributeError, NotImplementedError):
                    pass
            self._trace(trace_id, "synthesis_complete", evidenceCount=0, insufficient=False)
            return ChatResponse(conversationId=conversation_id, answer=conversational_reply, citations=[],
                                traceId=trace_id, memoryUsed=memory_used)
        contextual_query = (f"{previous_work_query} Follow-up: {request.message}"
                            if contextual_work_follow_up and previous_work_query else request.message)
        route = route_query(contextual_query)
        self._trace(trace_id, "route_complete", selectedSources=list(route.sources), reason=route.reason)
        results: list[ToolResult] = []
        records = []
        for source in route.sources[:3]:
            query = retrieval_query(contextual_query, source)
            started = perf_counter()
            try:
                future = _TOOL_EXECUTOR.submit(
                    self.connectors.search, source, query, limit=5, demo_mode=request.demoMode
                )
                result = future.result(timeout=self.tool_timeout_seconds)
                elapsed = int((perf_counter() - started) * 1000)
                # Bound the accepted evidence independently of adapter behavior.
                result = result.model_copy(update={"records": result.records[:5], "latencyMs": max(result.latencyMs, elapsed)})
                results.append(result)
                records.extend(result.records)
                self._trace(trace_id, "tool_complete", tool=result.toolName, durationMs=result.latencyMs,
                            recordCount=len(result.records), error=result.error)
            except FutureTimeout:
                self._trace(trace_id, "tool_error", tool=f"search_{source}",
                            durationMs=int((perf_counter() - started) * 1000), errorType="TimeoutError")
            except Exception as exc:
                self._trace(trace_id, "tool_error", tool=f"search_{source}",
                            durationMs=int((perf_counter() - started) * 1000), errorType=type(exc).__name__)
        # Deduplicate identical record IDs before ranking and citation numbering.
        unique = list({record.id: record for record in reversed(records)}.values())[::-1]
        answer, citations = (synthesize_with_groq(request.message, unique, self.groq_api_key, self.groq_model,
                                                  history=history)
                             if self.groq_api_key else synthesize(request.message, unique))
        citations = validate_citations(citations, unique)
        self._trace(trace_id, "citation_validation_complete", citationCount=len(citations), valid=True)
        memory_used: list[str] = []
        if self.memory:
            try:
                memory_used = self.memory.get_relevant(conversation_id, request.message)[:6]
            except (AttributeError, NotImplementedError):
                memory_used = []
            try:
                self.memory.add_message(conversation_id, "user", request.message,
                                        {"demoMode": request.demoMode})
                self.memory.add_message(conversation_id, "assistant", answer,
                                        {"citations": [citation.model_dump(exclude_none=True) for citation in citations],
                                         "traceId": trace_id, "memoryUsed": memory_used,
                                         "demoMode": request.demoMode})
            except (AttributeError, NotImplementedError):
                pass
        # Long-term memory is deliberately not written by this read-only chat pipeline.
        self._trace(trace_id, "synthesis_complete", evidenceCount=len(unique), insufficient=(answer == INSUFFICIENT_ANSWER))
        return ChatResponse(conversationId=conversation_id, answer=answer, citations=citations,
                            traceId=trace_id, memoryUsed=memory_used)
