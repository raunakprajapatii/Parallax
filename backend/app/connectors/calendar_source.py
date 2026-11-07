"""Read-only Google Calendar event search used by the work-query planner."""
from __future__ import annotations

from datetime import datetime, time, timedelta
import json
from pathlib import Path
import re
from time import perf_counter
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from app.agent.models import SourceRecord, ToolResult
from .config import ConnectorConfig
from .oauth import OAuthStore, access_token


class CalendarConnector:
    def __init__(self, config: ConnectorConfig):
        self.config = config
        self.store = OAuthStore(config.oauth_db_path)

    def search(self, query: str, limit: int = 5, *, demo_mode: bool = True) -> ToolResult:
        started = perf_counter()
        if demo_mode:
            path = Path(__file__).resolve().parents[1] / "data" / "demo" / "calendar.json"
            records = [SourceRecord.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8"))]
            words = [word.casefold() for word in re.findall(r"[\w-]+", query) if len(word) > 2]
            records = [record for record in records if any(
                word in f"{record.title} {record.content}".casefold() for word in words
            ) or any(term in query.casefold() for term in ("meeting", "event", "calendar", "tomorrow", "week"))]
            return ToolResult(toolName="search_calendar", query=" ".join(query.split()),
                              records=records[:limit], latencyMs=0)
        try:
            token = access_token(self.store, "calendar", self.config.google_client_id,
                                 self.config.google_client_secret)
            if not token:
                raise ValueError("Google Calendar is not connected")
            now = datetime.now(ZoneInfo("Asia/Kolkata"))
            start, end = self._range(query, now)
            params = {"singleEvents": "true", "orderBy": "startTime", "maxResults": min(max(limit, 1), 10),
                      "timeMin": start.isoformat(), "timeMax": end.isoformat()}
            keywords = self._keywords(query)
            if keywords:
                params["q"] = keywords
            response = httpx.get("https://www.googleapis.com/calendar/v3/calendars/primary/events",
                                 params=params, headers={"Authorization": f"Bearer {token}"}, timeout=15)
            response.raise_for_status()
            records = []
            for event in response.json().get("items", []):
                begins = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date", "")
                ends = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date", "")
                attendees = [item.get("email", "") for item in event.get("attendees", []) if item.get("email")]
                detail = [f"Starts: {begins}", f"Ends: {ends}"]
                if event.get("location"):
                    detail.append(f"Location: {event['location']}")
                if attendees:
                    detail.append("Attendees: " + ", ".join(attendees[:12]))
                if event.get("description"):
                    detail.append(event["description"][:1800])
                records.append(SourceRecord(
                    id=f"calendar:{quote(event.get('id', 'unknown'))}", source="calendar",
                    title=event.get("summary") or "Untitled calendar event", content="\n".join(detail),
                    url=event.get("htmlLink"), createdAt=begins,
                    metadata={"start": begins, "end": ends, "status": event.get("status", "confirmed")},
                ))
            return ToolResult(toolName="search_calendar", query=" ".join(query.split()), records=records,
                              latencyMs=int((perf_counter() - started) * 1000))
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            if isinstance(exc, ValueError) and str(exc):
                detail = str(exc)
            else:
                detail = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
            return ToolResult(toolName="search_calendar", query=" ".join(query.split()), records=[],
                              latencyMs=int((perf_counter() - started) * 1000),
                              error=f"Google Calendar request failed: {detail}")

    @staticmethod
    def _range(query: str, now: datetime) -> tuple[datetime, datetime]:
        local = now.tzinfo
        lower = query.casefold()
        date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", query)
        if "today" in lower or "tomorrow" in lower or date_match:
            day = (datetime.fromisoformat(date_match.group(1)).date() if date_match else
                   now.date() + timedelta(days=1 if "tomorrow" in lower else 0))
            return datetime.combine(day, time.min, local), datetime.combine(day + timedelta(days=1), time.min, local)
        weekday = re.search(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower)
        if weekday:
            target = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday").index(weekday.group(1))
            delta = (target - now.weekday()) % 7
            if delta == 0 or "next" in lower:
                delta += 7
            day = now.date() + timedelta(days=delta)
            return datetime.combine(day, time.min, local), datetime.combine(day + timedelta(days=1), time.min, local)
        return now, now + timedelta(days=7 if "week" in lower or "7 days" in lower else 30)

    @staticmethod
    def _keywords(query: str) -> str:
        ignored = {"calendar", "meeting", "meetings", "event", "events", "appointment", "appointments",
                   "what", "when", "where", "who", "how", "many", "is", "are", "the", "a", "an",
                   "on", "in", "for", "my", "me", "today", "tomorrow", "week", "upcoming", "next",
                   "this", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                   "show", "find", "list", "schedule", "scheduled", "do", "i", "have"}
        return " ".join(word for word in re.findall(r"[\w-]+", query) if word.casefold() not in ignored)[:160]
