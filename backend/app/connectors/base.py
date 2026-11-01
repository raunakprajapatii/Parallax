"""Shared connector implementation for normalized local records."""

from abc import ABC, abstractmethod
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from app.agent.models import SourceName, SourceRecord, ToolResult


class Connector(ABC):
    source: SourceName
    tool_name: str

    def __init__(self, fixture_path: Path):
        self.fixture_path = fixture_path

    def _load_records(self) -> list[SourceRecord]:
        with self.fixture_path.open(encoding="utf-8") as fixture:
            payload: list[dict[str, Any]] = json.load(fixture)
        return [SourceRecord.model_validate(item) for item in payload]

    @abstractmethod
    def _matches(self, record: SourceRecord, query: str) -> bool:
        """Return whether a record contains meaningful query terms."""

    def search(self, query: str, limit: int = 5) -> ToolResult:
        started = perf_counter()
        normalized_query = " ".join(query.split())
        records = self._load_records()
        terms = {term for term in normalized_query.casefold().split() if len(term) > 2}
        matched = [record for record in records if self._matches(record, normalized_query) or any(term in self._search_text(record) for term in terms)]
        # Stable fixture order is intentional: it makes the demo and evaluation repeatable.
        return ToolResult(
            toolName=self.tool_name, query=normalized_query, records=matched[: max(0, limit)],
            latencyMs=max(0, int((perf_counter() - started) * 1000)),
        )

    @staticmethod
    def _search_text(record: SourceRecord) -> str:
        return " ".join((record.title, record.content, record.author or "", *record.metadata.values())).casefold()
