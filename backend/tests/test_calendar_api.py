from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.agent.models import CalendarEventRequest
from app.api.calendar import create_event


class CalendarStore:
    def __init__(self):
        self.token = {"access_token": "stale"}

    def get(self, provider):
        return self.token if provider == "calendar" else None

    def delete(self, provider):
        if provider == "calendar":
            self.token = None


def request_with_store(store):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(oauth_store=store)))


def event_payload():
    start = datetime.now(timezone.utc) + timedelta(days=2)
    end = start + timedelta(minutes=30)
    return CalendarEventRequest(
        draftId="a" * 32, summary="Project check-in", description="",
        start=start.isoformat(), end=end.isoformat(), attendeeEmails=[],
    )


def test_revoked_calendar_refresh_token_returns_reconnect_response(monkeypatch):
    store = CalendarStore()
    request = httpx.Request("POST", "https://oauth2.googleapis.com/token")
    response = httpx.Response(400, json={"error": "invalid_grant"}, request=request)

    def invalid_refresh(*args, **kwargs):
        raise httpx.HTTPStatusError("invalid grant", request=request, response=response)

    monkeypatch.setattr("app.api.calendar.access_token", invalid_refresh)

    with pytest.raises(HTTPException) as error:
        create_event(event_payload(), request_with_store(store))

    assert error.value.status_code == 409
    assert "Reconnect Google Calendar" in error.value.detail
    assert store.get("calendar") is None


def test_calendar_event_creation_uses_confirmed_event_payload(monkeypatch):
    store = CalendarStore()
    monkeypatch.setattr("app.api.calendar.access_token", lambda *args, **kwargs: "test-access-token")
    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "a" * 32, "summary": "Project check-in",
                    "htmlLink": "https://calendar.google.test/event"}

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr("app.api.calendar.httpx.post", fake_post)
    payload = event_payload()

    created = create_event(payload, request_with_store(store))

    assert created["summary"] == payload.summary
    assert created["htmlLink"] == "https://calendar.google.test/event"
    assert captured["json"]["summary"] == payload.summary
    assert captured["params"] == {"sendUpdates": "all"}
