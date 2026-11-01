"""Boundary protocols for Module C connectors and Module D services."""

from typing import Protocol

from .models import SourceName, ToolResult


class ConnectorRegistry(Protocol):
    def search(self, source: SourceName, query: str, limit: int = 5, *, demo_mode: bool = True) -> ToolResult: ...


class MemoryService(Protocol):
    def get_session(self, conversation_id: str, limit: int | None = None) -> list[dict[str, object]]: ...
    def get_relevant(self, conversation_id: str, query: str) -> list[str]: ...
    def remember(self, conversation_id: str, text: str, *, consent_source: str) -> None: ...


class TraceRecorder(Protocol):
    def record(self, event: dict[str, object]) -> None: ...
