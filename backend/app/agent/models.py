"""Shared agent wire models. Fields mirror PROJECT_PLAN.md exactly."""

from typing import Literal

from pydantic import BaseModel, Field


SourceName = Literal["gmail", "jira", "notion"]
ToolName = Literal["search_gmail", "search_jira", "search_notion"]


class SourceRecord(BaseModel):
    id: str
    source: SourceName
    title: str
    content: str
    url: str | None = None
    author: str | None = None
    createdAt: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)


class ToolResult(BaseModel):
    toolName: ToolName
    query: str
    records: list[SourceRecord]
    latencyMs: int = Field(ge=0)
    error: str | None = None


class ChatRequest(BaseModel):
    conversationId: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    demoMode: bool = True


class Citation(BaseModel):
    number: int
    recordId: str
    title: str
    source: SourceName
    url: str | None = None


class ChatResponse(BaseModel):
    conversationId: str
    answer: str
    citations: list[Citation]
    traceId: str
    memoryUsed: list[str]
    calendarDraft: dict[str, object] | None = None
    calendarConnectUrl: str | None = None


class CalendarEventRequest(BaseModel):
    draftId: str = Field(pattern=r"^[0-9a-f]{32}$")
    summary: str = Field(min_length=1, max_length=200)
    start: str = Field(min_length=1, max_length=80)
    end: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=4000)
    attendeeEmails: list[str] = Field(default_factory=list, max_length=50)


class TraceEvent(BaseModel):
    traceId: str
    step: str
    tool: str | None = None
    durationMs: int | None = None
    recordCount: int | None = None
    timestamp: str
    labels: dict[str, object] = Field(default_factory=dict)
    status: str | None = None
    error: str | None = None
    recordIds: list[str] = Field(default_factory=list)
