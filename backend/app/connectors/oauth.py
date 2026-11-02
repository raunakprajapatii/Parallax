"""Local single-user OAuth flows and SQLite token storage for Jira and Notion."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlencode

import httpx


class OAuthError(Exception):
    pass


class OAuthStore:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS oauth_states (
                    state TEXT PRIMARY KEY, provider TEXT NOT NULL, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    provider TEXT PRIMARY KEY, token_json TEXT NOT NULL, updated_at INTEGER NOT NULL
                );
            """)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=10)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def new_state(self, provider: str) -> str:
        state = secrets.token_urlsafe(32)
        with self._connect() as db:
            db.execute("DELETE FROM oauth_states WHERE created_at < ?", (int(time.time()) - 600,))
            db.execute("INSERT INTO oauth_states VALUES (?, ?, ?)", (state, provider, int(time.time())))
        return state

    def consume_state(self, state: str, provider: str) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT provider, created_at FROM oauth_states WHERE state=?", (state,)).fetchone()
            if not row:
                return False
            if int(time.time()) - row[1] > 600:
                db.execute("DELETE FROM oauth_states WHERE state=?", (state,))
                return False
            if row[0] != provider:
                return False
            db.execute("DELETE FROM oauth_states WHERE state=?", (state,))
            return True

    def save(self, provider: str, token: dict) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO oauth_tokens VALUES (?, ?, ?)",
                       (provider, json.dumps(token), int(time.time())))

    def get(self, provider: str) -> dict | None:
        with self._connect() as db:
            row = db.execute("SELECT token_json FROM oauth_tokens WHERE provider=?", (provider,)).fetchone()
        return json.loads(row[0]) if row else None

    def delete(self, provider: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM oauth_tokens WHERE provider=?", (provider,))

    def status(self) -> dict[str, bool]:
        with self._connect() as db:
            rows = db.execute("SELECT provider FROM oauth_tokens").fetchall()
        connected = {row[0] for row in rows}
        return {provider: provider in connected for provider in ("jira", "notion", "gmail")}


def authorization_url(provider: str, state: str, client_id: str, redirect_uri: str,
                      scopes: list[str]) -> str:
    if provider == "gmail":
        params = {"client_id": client_id, "redirect_uri": redirect_uri,
                  "response_type": "code", "scope": " ".join(scopes),
                  "state": state, "access_type": "offline", "prompt": "consent"}
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    if provider == "jira":
        params = {"audience": "api.atlassian.com", "client_id": client_id,
                  "scope": " ".join(scopes), "redirect_uri": redirect_uri,
                  "state": state, "response_type": "code", "prompt": "consent"}
        return "https://auth.atlassian.com/authorize?" + urlencode(params)
    params = {"client_id": client_id, "response_type": "code", "owner": "user",
              "redirect_uri": redirect_uri, "state": state}
    if scopes:
        params["scope"] = " ".join(scopes)
    return "https://api.notion.com/v1/oauth/authorize?" + urlencode(params)


def exchange_code(provider: str, code: str, client_id: str, client_secret: str,
                  redirect_uri: str) -> dict:
    if provider == "gmail":
        response = httpx.post("https://oauth2.googleapis.com/token", data={
            "grant_type": "authorization_code", "client_id": client_id,
            "client_secret": client_secret, "code": code, "redirect_uri": redirect_uri,
        }, timeout=20)
    elif provider == "jira":
        response = httpx.post("https://auth.atlassian.com/oauth/token", json={
            "grant_type": "authorization_code", "client_id": client_id,
            "client_secret": client_secret, "code": code, "redirect_uri": redirect_uri,
        }, timeout=20)
    else:
        response = httpx.post("https://api.notion.com/v1/oauth/token", auth=(client_id, client_secret),
                              json={"grant_type": "authorization_code", "code": code,
                                    "redirect_uri": redirect_uri}, timeout=20)
    response.raise_for_status()
    return response.json()


def refresh_token(provider: str, token: dict, client_id: str, client_secret: str) -> dict:
    refresh = token.get("refresh_token")
    if not refresh:
        return token
    url = ({"gmail": "https://oauth2.googleapis.com/token",
            "jira": "https://auth.atlassian.com/oauth/token",
            "notion": "https://api.notion.com/v1/oauth/token"}[provider])
    payload = {"grant_type": "refresh_token", "refresh_token": refresh}
    if provider == "gmail":
        payload.update(client_id=client_id, client_secret=client_secret)
        response = httpx.post(url, data=payload, timeout=20)
    elif provider == "jira":
        payload.update(client_id=client_id, client_secret=client_secret)
        response = httpx.post(url, json=payload, timeout=20)
    else:
        response = httpx.post(url, auth=(client_id, client_secret), json=payload, timeout=20)
    response.raise_for_status()
    updated = response.json()
    if "refresh_token" not in updated:
        updated["refresh_token"] = refresh
    return updated


def access_token(store: OAuthStore, provider: str, client_id: str | None,
                 client_secret: str | None) -> str | None:
    token = store.get(provider)
    if not token:
        return None
    expires_at = int(token.get("obtained_at", 0)) + int(token.get("expires_in", 0))
    if expires_at and time.time() >= expires_at - 60 and client_id and client_secret and token.get("refresh_token"):
        token = refresh_token(provider, token, client_id, client_secret)
        token["obtained_at"] = int(time.time())
        store.save(provider, token)
    return token.get("access_token")
