"""LangGraph workflow for Parallax chat turns.

The graph owns per-run state and control flow. Conversation history and trace
events remain in the existing SQLite services so there is one durable source of
truth for the application's transcript contract.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import re
from time import perf_counter
from time import sleep
from typing import Any, Literal, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from .citations import validate_citations
from .models import ChatRequest, ChatResponse, Citation, SourceName, SourceRecord, ToolResult
from .routing import is_follow_up, is_work_query, retrieval_query, route_query
from .synthesis import (INSUFFICIENT_ANSWER, SYNTHESIS_UNAVAILABLE,
                        answer_general_with_groq, synthesize_with_groq)
from .scheduling import extract_meeting_details, is_scheduling_request

_TOOL_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="agent-tool")


class AgentRunState(TypedDict, total=False):
    request: ChatRequest
    trace_id: str
    conversation_id: str
    history: list[dict[str, str]]
    previous_work_query: str | None
    contextual_work_follow_up: bool
    is_work_turn: bool
    contextual_query: str
    selected_sources: list[SourceName]
    tool_results: list[ToolResult]
    records: list[SourceRecord]
    answer: str
    citations: list[Citation]
    memory_used: list[str]
    response: ChatResponse
    is_scheduling_turn: bool
    calendar_draft: dict[str, object] | None
    calendar_connect_url: str | None


def _is_transient_tool_error(error: str | None) -> bool:
    if not error:
        return False
    value = error.casefold()
    return any(marker in value for marker in (
        "http 429", "http 500", "http 502", "http 503", "http 504",
        "timeout", "readerror", "connecterror", "temporarily unavailable",
    ))


def build_agent_workflow(agent: Any):
    """Build the explicit route → retrieve → synthesize → persist graph."""

    def load_context(state: AgentRunState) -> dict[str, object]:
        request = state["request"]
        history: list[dict[str, str]] = []
        if agent.memory:
            try:
                history = [{"role": item["role"], "content": item["content"]}
                           for item in agent.memory.get_session(state["conversation_id"], limit=8)
                           if item.get("role") in {"user", "assistant"} and item.get("content")]
            except (AttributeError, NotImplementedError, KeyError):
                history = []
        previous_work_query = next((item["content"] for item in reversed(history)
                                    if item["role"] == "user" and is_work_query(item["content"])), None)
        contextual_follow_up = bool(previous_work_query and is_follow_up(request.message))
        is_work_turn = is_work_query(request.message) or contextual_follow_up
        contextual_query = (f"{previous_work_query} Follow-up: {request.message}"
                            if contextual_follow_up and previous_work_query else request.message)
        previous_schedule = any(is_scheduling_request(item["content"]) for item in history
                                if item["role"] == "user")
        last_assistant = next((item["content"] for item in reversed(history)
                               if item["role"] == "assistant"), "")
        awaiting_schedule_details = any(phrase in last_assistant.casefold() for phrase in
                                        ("what date and start time", "what email address should i invite",
                                         "valid date, start time"))
        scheduling_follow_up = previous_schedule and (is_follow_up(request.message) or awaiting_schedule_details)
        is_scheduling_turn = is_scheduling_request(request.message) or scheduling_follow_up
        return {"history": history, "previous_work_query": previous_work_query,
                "contextual_work_follow_up": contextual_follow_up,
                "is_work_turn": is_work_turn, "contextual_query": contextual_query,
                "is_scheduling_turn": is_scheduling_turn}

    def choose_path(state: AgentRunState) -> Literal["work", "general"]:
        if state.get("is_scheduling_turn"):
            return "schedule"
        return "work" if state.get("is_work_turn") else "general"

    def prepare_schedule(state: AgentRunState) -> dict[str, object]:
        calendar_connected = agent.has_calendar_connection()
        provider = agent.llm_provider
        api_key, model = ((agent.gemini_api_key, agent.gemini_model) if provider == "gemini"
                          else (agent.groq_api_key, agent.groq_model))
        if not api_key:
            answer = (f"I’ll need the date, start time, and meeting length. {provider.title()} is not configured to read those details yet.")
            return {"answer": answer, "citations": [], "calendar_draft": None,
                    "calendar_connect_url": None if calendar_connected else "/api/oauth/calendar/connect"}
        try:
            result = extract_meeting_details(state["request"].message, state.get("history", []),
                                             api_key, model, provider)
        except Exception:
            answer = "What date, start time, and meeting length should I use? You can connect Google Calendar now, and I’ll prepare the event after you provide the details."
            return {"answer": answer, "citations": [], "calendar_draft": None,
                    "calendar_connect_url": None if calendar_connected else "/api/oauth/calendar/connect"}
        if not result.get("complete"):
            return {"answer": str(result.get("question") or "What date and time should I schedule?"),
                    "citations": [], "calendar_draft": None,
                    "calendar_connect_url": None if calendar_connected else "/api/oauth/calendar/connect"}
        draft = {**result["draft"], "draftId": uuid4().hex}
        lines = [f"**Meeting:** {draft['summary']}",
                 f"**When:** {draft['start']} to {draft['end']} (Asia/Kolkata)"]
        if draft.get("attendeeEmails"):
            lines.append("**Inviting:** " + ", ".join(draft["attendeeEmails"]))
        if not calendar_connected:
            lines.append("Connect Google Calendar to continue. I’ll wait for your confirmation before creating it.")
            return {"answer": "\n\n".join(lines), "citations": [], "calendar_draft": draft,
                    "calendar_connect_url": "/api/oauth/calendar/connect"}
        lines.append("Review the details, then choose **Create event** to add it to your calendar and send invitations.")
        return {"answer": "\n\n".join(lines), "citations": [], "calendar_draft": draft,
                "calendar_connect_url": None}

    def answer_general(state: AgentRunState) -> dict[str, object]:
        request = state["request"]
        provider = agent.llm_provider
        api_key, model = ((agent.gemini_api_key, agent.gemini_model) if provider == "gemini"
                          else (agent.groq_api_key, agent.groq_model))
        answer = answer_general_with_groq(request.message, api_key, model,
                                          history=state.get("history", []), provider=provider)
        agent._trace(state["trace_id"], "route_complete", selectedSources=[], reason="small_talk")
        memory_used: list[str] = []
        if agent.memory:
            try:
                memory_used = agent.memory.get_relevant(state["conversation_id"], request.message)[:6]
            except (AttributeError, NotImplementedError):
                pass
        return {"answer": answer, "citations": [], "memory_used": memory_used,
                "selected_sources": [], "records": [], "tool_results": []}

    def select_sources(state: AgentRunState) -> dict[str, object]:
        route = route_query(state["contextual_query"])
        agent._trace(state["trace_id"], "route_complete", selectedSources=list(route.sources), reason=route.reason)
        return {"selected_sources": list(route.sources[:3]), "tool_results": [], "records": []}

    def retrieve_sources(state: AgentRunState) -> dict[str, object]:
        request = state["request"]
        contextual_query = state["contextual_query"]
        results: list[ToolResult] = []
        records: list[SourceRecord] = []
        related_jira_terms: list[str] = []
        for source in state.get("selected_sources", []):
            query = retrieval_query(contextual_query, source)
            if source == "gmail" and related_jira_terms:
                issue_keys = [term for term in related_jira_terms if re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", term)]
                if issue_keys:
                    query = f"newer_than:30d {{{' '.join(issue_keys[:12])}}}"
            started = perf_counter()
            result: ToolResult | None = None
            retry_count = 0
            try:
                for attempt in range(2):
                    future = _TOOL_EXECUTOR.submit(
                        agent.connectors.search, source, query, limit=5, demo_mode=request.demoMode
                    )
                    try:
                        result = future.result(timeout=agent.tool_timeout_seconds)
                    except FutureTimeout:
                        if attempt == 0:
                            retry_count += 1
                            sleep(0.15)
                            continue
                        raise
                    if attempt == 0 and _is_transient_tool_error(result.error):
                        retry_count += 1
                        sleep(0.15)
                        continue
                    break
                assert result is not None
                elapsed = int((perf_counter() - started) * 1000)
                result = result.model_copy(update={"records": result.records[:5],
                                                   "latencyMs": max(result.latencyMs, elapsed)})
                results.append(result)
                records.extend(result.records)
                if source == "jira" and result.records:
                    related_jira_terms = [record.id.partition(":")[2] for record in result.records]
                    related_jira_terms.extend(record.title for record in result.records if record.title)
                agent._trace(state["trace_id"], "tool_complete", tool=result.toolName,
                             durationMs=result.latencyMs, recordCount=len(result.records),
                             retries=retry_count, error=result.error)
            except FutureTimeout:
                elapsed = int((perf_counter() - started) * 1000)
                results.append(ToolResult(toolName=f"search_{source}", query=query,
                                          records=[], latencyMs=elapsed, error="Tool timeout"))
                agent._trace(state["trace_id"], "tool_error", tool=f"search_{source}",
                             durationMs=elapsed, retries=retry_count, errorType="TimeoutError")
            except Exception as exc:
                elapsed = int((perf_counter() - started) * 1000)
                results.append(ToolResult(toolName=f"search_{source}", query=query,
                                          records=[], latencyMs=elapsed, error="Provider error"))
                agent._trace(state["trace_id"], "tool_error", tool=f"search_{source}",
                             durationMs=elapsed, errorType=type(exc).__name__)
        unique = list({record.id: record for record in reversed(records)}.values())[::-1]
        return {"tool_results": results, "records": unique}

    def synthesize_answer(state: AgentRunState) -> dict[str, object]:
        request = state["request"]
        records = state.get("records", [])
        if not records:
            results = state.get("tool_results", [])
            failures = [result.error or "" for result in results if result.error]
            if failures and len(failures) == len(results):
                if any("403" in error or "permission" in error.casefold() for error in failures):
                    answer = "I couldn’t access the connected source because the account may be missing permission for this data. Reconnect it or grant the required read access, then try again."
                elif any("401" in error or "unauthorized" in error.casefold() for error in failures):
                    answer = "The connected source rejected its credentials. Reconnect the account and try again."
                else:
                    answer = "I couldn’t retrieve data from the connected source just now. Please try again."
            elif failures:
                answer = "I checked the available connected sources, but one or more could not be reached, so this result may be incomplete."
            else:
                answer = "I checked the connected sources and found no matching items for that request. Try a name, project, issue key, or a narrower date range."
            citations: list[Citation] = []
        else:
            provider = agent.llm_provider
            api_key, model = ((agent.gemini_api_key, agent.gemini_model) if provider == "gemini"
                              else (agent.groq_api_key, agent.groq_model))
            if api_key:
                answer, citations = synthesize_with_groq(
                    request.message, records, api_key, model,
                    history=state.get("history", []), provider=provider)
            else:
                # Never expose raw connector records as if they were a finished answer.
                answer, citations = SYNTHESIS_UNAVAILABLE, []
        citations = validate_citations(citations, records)
        agent._trace(state["trace_id"], "citation_validation_complete", citationCount=len(citations), valid=True)
        memory_used: list[str] = []
        if agent.memory:
            try:
                memory_used = agent.memory.get_relevant(state["conversation_id"], request.message)[:6]
            except (AttributeError, NotImplementedError):
                pass
        return {"answer": answer, "citations": citations, "memory_used": memory_used}

    def persist_response(state: AgentRunState) -> dict[str, object]:
        request = state["request"]
        answer = state.get("answer", "")
        citations = state.get("citations", [])
        memory_used = state.get("memory_used", [])
        if agent.memory:
            try:
                agent.memory.add_message(state["conversation_id"], "user", request.message,
                                         {"demoMode": request.demoMode})
                agent.memory.add_message(
                    state["conversation_id"], "assistant", answer,
                    {"citations": [citation.model_dump(exclude_none=True) for citation in citations],
                     "traceId": state["trace_id"], "memoryUsed": memory_used,
                     "demoMode": request.demoMode,
                     "calendarDraft": state.get("calendar_draft"),
                     "calendarConnectUrl": state.get("calendar_connect_url")},
                )
            except (AttributeError, NotImplementedError):
                pass
        agent._trace(state["trace_id"], "synthesis_complete", evidenceCount=len(state.get("records", [])),
                     insufficient=(answer == INSUFFICIENT_ANSWER))
        response = ChatResponse(conversationId=state["conversation_id"], answer=answer,
                                citations=citations, traceId=state["trace_id"], memoryUsed=memory_used,
                                calendarDraft=state.get("calendar_draft"),
                                calendarConnectUrl=state.get("calendar_connect_url"))
        return {"response": response}

    graph = StateGraph(AgentRunState)
    graph.add_node("load_context", load_context)
    graph.add_node("answer_general", answer_general)
    graph.add_node("prepare_schedule", prepare_schedule)
    graph.add_node("select_sources", select_sources)
    graph.add_node("retrieve_sources", retrieve_sources)
    graph.add_node("synthesize_answer", synthesize_answer)
    graph.add_node("persist_response", persist_response)
    graph.add_edge(START, "load_context")
    graph.add_conditional_edges("load_context", choose_path,
                                {"work": "select_sources", "general": "answer_general",
                                 "schedule": "prepare_schedule"})
    graph.add_edge("answer_general", "persist_response")
    graph.add_edge("prepare_schedule", "persist_response")
    graph.add_edge("select_sources", "retrieve_sources")
    graph.add_edge("retrieve_sources", "synthesize_answer")
    graph.add_edge("synthesize_answer", "persist_response")
    graph.add_edge("persist_response", END)
    return graph.compile(name="Parallax work assistant")


def invoke_agent_workflow(agent: Any, request: ChatRequest) -> ChatResponse:
    trace_id = f"run_{uuid4().hex}"
    conversation_id = request.conversationId or f"conversation_{uuid4().hex}"
    result = agent.workflow.invoke({"request": request, "trace_id": trace_id,
                                    "conversation_id": conversation_id})
    return result["response"]
