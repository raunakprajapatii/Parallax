"""Google Calendar event creation after explicit user confirmation."""
from __future__ import annotations

from datetime import datetime, timezone
import os
import re

import httpx
from fastapi import APIRouter, HTTPException, Request

from app.agent.models import CalendarEventRequest
from app.connectors.oauth import access_token

router = APIRouter(prefix="/api/calendar", tags=["calendar"])
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@router.post("/events")
def create_event(payload: CalendarEventRequest, request: Request):
    store = getattr(request.app.state, "oauth_store", None)
    if not store or not store.get("calendar"):
        raise HTTPException(409, "Connect Google Calendar before scheduling this event.")
    for field_name, value in (("start", payload.start), ("end", payload.end)):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(422, f"{field_name} must be a valid RFC3339 date and time.") from exc
        if parsed.tzinfo is None:
            raise HTTPException(422, f"{field_name} must include a timezone.")
    start, end = datetime.fromisoformat(payload.start), datetime.fromisoformat(payload.end)
    if end <= start or start <= datetime.now(timezone.utc):
        raise HTTPException(422, "The event must end after it starts and be scheduled in the future.")
    if any(not _EMAIL.fullmatch(email) for email in payload.attendeeEmails):
        raise HTTPException(422, "Each attendee must have a valid email address.")
    token = access_token(store, "calendar", os.getenv("GOOGLE_CLIENT_ID"),
                         os.getenv("GOOGLE_CLIENT_SECRET"))
    if not token:
        raise HTTPException(409, "Reconnect Google Calendar to authorize event creation.")
    event = {"id": payload.draftId, "summary": payload.summary.strip(), "description": payload.description,
             "start": {"dateTime": payload.start}, "end": {"dateTime": payload.end},
             "attendees": [{"email": email} for email in payload.attendeeEmails]}
    try:
        response = httpx.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            params={"sendUpdates": "all"},
            headers={"Authorization": f"Bearer {token}"}, json=event, timeout=20)
        if response.status_code == 409:
            response = httpx.get(
                f"https://www.googleapis.com/calendar/v3/calendars/primary/events/{payload.draftId}",
                headers={"Authorization": f"Bearer {token}"}, timeout=20)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {401, 403}:
            raise HTTPException(409, "Google Calendar denied access. Reconnect it with event creation permission.") from exc
        raise HTTPException(502, "Google Calendar could not create the event. Please try again.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Google Calendar could not be reached. Please try again.") from exc
    created = response.json()
    return {"id": created.get("id"), "summary": created.get("summary", payload.summary),
            "htmlLink": created.get("htmlLink"), "start": created.get("start", {}).get("dateTime", payload.start),
            "end": created.get("end", {}).get("dateTime", payload.end)}
