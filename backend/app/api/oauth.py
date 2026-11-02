"""OAuth connect, callback, status, and disconnect endpoints (local single-user mode)."""
from __future__ import annotations

import os
import time
from html import escape

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.connectors.oauth import OAuthStore, authorization_url, exchange_code

router = APIRouter(prefix="/api/oauth", tags=["integrations"])
PROVIDERS = {"jira", "notion", "gmail"}


def _settings(provider: str) -> tuple[str, str, str, list[str]]:
    if provider == "gmail":
        return (os.getenv("GOOGLE_CLIENT_ID", ""), os.getenv("GOOGLE_CLIENT_SECRET", ""),
                os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:8000/api/oauth/gmail/callback"),
                ["https://www.googleapis.com/auth/gmail.readonly"])
    if provider == "jira":
        return (os.getenv("JIRA_OAUTH_CLIENT_ID", ""), os.getenv("JIRA_OAUTH_CLIENT_SECRET", ""),
                os.getenv("JIRA_OAUTH_REDIRECT_URI", "http://localhost:8000/api/oauth/jira/callback"),
                os.getenv("JIRA_OAUTH_SCOPES", "read:jira-work read:jira-user offline_access").split())
    return (os.getenv("NOTION_OAUTH_CLIENT_ID", ""), os.getenv("NOTION_OAUTH_CLIENT_SECRET", ""),
            os.getenv("NOTION_OAUTH_REDIRECT_URI", "http://localhost:8000/api/oauth/notion/callback"), [])


def _store(request: Request) -> OAuthStore:
    return request.app.state.oauth_store


@router.get("/{provider}/connect")
def connect(provider: str, request: Request):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Provider must be jira, notion, or gmail")
    client_id, secret, redirect_uri, scopes = _settings(provider)
    if not client_id or not secret:
        names = {"gmail": "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET",
                 "jira": "JIRA_OAUTH_CLIENT_ID and JIRA_OAUTH_CLIENT_SECRET",
                 "notion": "NOTION_OAUTH_CLIENT_ID and NOTION_OAUTH_CLIENT_SECRET"}
        raise HTTPException(503, f"Configure {names[provider]}")
    state = _store(request).new_state(provider)
    return RedirectResponse(authorization_url(provider, state, client_id, redirect_uri, scopes))


@router.get("/{provider}/callback", response_class=HTMLResponse)
def callback(provider: str, request: Request, code: str | None = None,
             state: str | None = None, error: str | None = None):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Provider must be jira, notion, or gmail")
    if error:
        return HTMLResponse(f"<h2>{provider.title()} connection was not authorized.</h2><p>{escape(error)}</p>", status_code=400)
    if not code or not state or not _store(request).consume_state(state, provider):
        raise HTTPException(400, "Missing/invalid OAuth state or authorization code")
    client_id, secret, redirect_uri, _ = _settings(provider)
    try:
        token = exchange_code(provider, code, client_id, secret, redirect_uri)
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, f"{provider.title()} token exchange failed") from exc
    token["obtained_at"] = int(time.time())
    _store(request).save(provider, token)
    return HTMLResponse(f"<h2>{provider.title()} connected.</h2><p>You can close this tab and return to Parallax.</p>")


@router.get("/status")
def status(request: Request):
    return _store(request).status()


@router.delete("/{provider}")
def disconnect(provider: str, request: Request):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Provider must be jira, notion, or gmail")
    _store(request).delete(provider)
    return {"provider": provider, "connected": False}
