"""Deterministic route → retrieve → rank → synthesize → validate pipeline."""

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from time import perf_counter
from uuid import uuid4

from .citations import validate_citations
from .interfaces import ConnectorRegistry, MemoryService, TraceRecorder
from .models import ChatRequest, ChatResponse, SourceName, ToolResult, TraceEvent
from .routing import retrieval_query, route_query
from .synthesis import INSUFFICIENT_ANSWER, synthesize

_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="agent-tool")


class AgentOrchestrator:
    def __init__(self, connectors: ConnectorRegistry, memory: MemoryService | None = None,
                 trace_recorder: TraceRecorder | None = None, *, tool_timeout_seconds: float = 3.0):
        self.connectors = connectors
        self.memory = memory
        self.trace_recorder = trace_recorder
        self.tool_timeout_seconds = tool_timeout_seconds

    def _trace(self, trace_id: str, step: str, **fields: object) -> None:
        standard = {key: fields.pop(key) for key in ("tool", "durationMs", "recordCount") if key in fields}
        event = TraceEvent(traceId=trace_id, step=step, timestamp=datetime.now(timezone.utc).isoformat(),
                           details=fields, **standard)
        if self.trace_recorder:
            self.trace_recorder.record(event.model_dump(exclude_none=True))

    def run(self, request: ChatRequest) -> ChatResponse:
        trace_id = f"run_{uuid4().hex}"
        conversation_id = request.conversationId or f"conversation_{uuid4().hex}"
        route = route_query(request.message)
        self._trace(trace_id, "route_complete", selectedSources=list(route.sources), reason=route.reason)
        results: list[ToolResult] = []
        records = []
        for source in route.sources[:3]:
            query = retrieval_query(request.message, source)
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
        answer, citations = synthesize(request.message, unique)
        citations = validate_citations(citations, unique)
        self._trace(trace_id, "citation_validation_complete", citationCount=len(citations), valid=True)
        memory_used: list[str] = []
        if self.memory:
            try:
                memory_used = self.memory.get_relevant(conversation_id, request.message)[:6]
            except (AttributeError, NotImplementedError):
                memory_used = []
        # Long-term memory is deliberately not written by this read-only chat pipeline.
        self._trace(trace_id, "synthesis_complete", evidenceCount=len(unique), insufficient=(answer == INSUFFICIENT_ANSWER))
        return ChatResponse(conversationId=conversation_id, answer=answer, citations=citations,
                            traceId=trace_id, memoryUsed=memory_used)
