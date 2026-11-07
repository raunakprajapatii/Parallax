"""Persist run events using the project's documented trace event contract."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

TRACE_STEPS = {"run_started", "source_selected", "tool_started", "tool_complete", "answer_complete", "memory_written", "run_failed"}
TOOLS = {"search_gmail", "search_jira", "search_notion", "search_calendar", "search_drive"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class TraceEvent:
    traceId: str
    step: str
    tool: str | None = None
    durationMs: int | None = None
    recordCount: int | None = None
    timestamp: str = field(default_factory=_now)
    # Useful evidence and safe structured labels; never store private reasoning.
    recordIds: tuple[str, ...] = ()
    labels: dict[str, Any] = field(default_factory=dict)
    status: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.traceId:
            raise ValueError("traceId is required")
        if self.step not in TRACE_STEPS:
            raise ValueError(f"unsupported trace step: {self.step}")
        if self.tool is not None and self.tool not in TOOLS:
            raise ValueError(f"unsupported tool: {self.tool}")
        if self.durationMs is not None and self.durationMs < 0:
            raise ValueError("durationMs cannot be negative")
        if self.recordCount is not None and self.recordCount < 0:
            raise ValueError("recordCount cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["recordIds"] = list(self.recordIds)
        return value


class TraceStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or os.getenv("TRACE_DB_PATH", "backend/data/memory.sqlite3"))
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS trace_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL,
                step TEXT NOT NULL, tool TEXT, duration_ms INTEGER, record_count INTEGER,
                timestamp TEXT NOT NULL, record_ids_json TEXT NOT NULL,
                labels_json TEXT NOT NULL, status TEXT, error TEXT
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS ix_trace_events_trace ON trace_events(trace_id, id)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def record(self, event: TraceEvent | dict[str, Any]) -> dict[str, Any]:
        if isinstance(event, dict):
            event = TraceEvent(**event)
        values = (event.traceId, event.step, event.tool, event.durationMs, event.recordCount,
                  event.timestamp, json.dumps(list(event.recordIds)), json.dumps(event.labels), event.status, event.error)
        with self._connect() as db:
            db.execute("INSERT INTO trace_events(trace_id,step,tool,duration_ms,record_count,timestamp,record_ids_json,labels_json,status,error) VALUES (?,?,?,?,?,?,?,?,?,?)", values)
        return event.to_dict()

    def record_tool_result(self, trace_id: str, tool_result: dict[str, Any], timestamp: str | None = None) -> dict[str, Any]:
        """Record one normalized ToolResult and its returned source record IDs."""
        records = tool_result.get("records") or []
        event = TraceEvent(traceId=trace_id, step="tool_complete", tool=tool_result["toolName"],
                           durationMs=int(tool_result.get("latencyMs", 0)), recordCount=len(records),
                           timestamp=timestamp or _now(), recordIds=tuple(r["id"] for r in records),
                           status="error" if tool_result.get("error") else "success", error=tool_result.get("error"))
        return self.record(event)

    def get_trace(self, trace_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM trace_events WHERE trace_id=? ORDER BY id", (trace_id,)).fetchall()
        return [{"traceId": r["trace_id"], "step": r["step"], "tool": r["tool"],
                 "durationMs": r["duration_ms"], "recordCount": r["record_count"], "timestamp": r["timestamp"],
                 "recordIds": json.loads(r["record_ids_json"]), "labels": json.loads(r["labels_json"]),
                 "status": r["status"], "error": r["error"]} for r in rows]

    def delete_trace(self, trace_id: str) -> int:
        with self._connect() as db:
            return db.execute("DELETE FROM trace_events WHERE trace_id=?", (trace_id,)).rowcount

    def new_trace_id(self) -> str:
        return f"run_{uuid.uuid4().hex}"

    def list_trace_ids(self, limit: int = 50) -> list[str]:
        with self._connect() as db:
            rows = db.execute("SELECT trace_id, MAX(id) AS latest FROM trace_events GROUP BY trace_id ORDER BY latest DESC LIMIT ?", (max(1, limit),)).fetchall()
        return [r["trace_id"] for r in rows]
