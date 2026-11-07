"""Google Drive retrieval with a small demo corpus and folder-scoped live search."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import csv
import io
from time import perf_counter
from urllib.parse import quote

import httpx

from app.agent.models import SourceRecord, ToolResult
from .config import ConnectorConfig
from .oauth import OAuthStore, access_token


class DriveConnector:
    def __init__(self, config: ConnectorConfig):
        self.config = config
        self.db_path = config.oauth_db_path
        self.oauth_store = OAuthStore(self.db_path)

    def selected_folder(self) -> str | None:
        with sqlite3.connect(self.db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS drive_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = db.execute("SELECT value FROM drive_settings WHERE key='folder_id'").fetchone()
        return row[0] if row else None

    def set_folder(self, folder_id: str | None) -> None:
        with sqlite3.connect(self.db_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS drive_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            if folder_id:
                db.execute("INSERT OR REPLACE INTO drive_settings VALUES ('folder_id', ?)", (folder_id,))
            else:
                db.execute("DELETE FROM drive_settings WHERE key='folder_id'")

    def demo_search(self, query: str, limit: int = 5) -> ToolResult:
        path = Path(__file__).resolve().parents[1] / "data" / "demo" / "drive.json"
        records = [SourceRecord.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8"))]
        return self._rank(query, records, limit)

    def folders(self) -> list[dict[str, str]]:
        token = self._token()
        response = httpx.get("https://www.googleapis.com/drive/v3/files", params={
            "q": "mimeType='application/vnd.google-apps.folder' and trashed=false",
            "fields": "files(id,name,mimeType,webViewLink)", "pageSize": 100,
            "orderBy": "name", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
        }, headers={"Authorization": f"Bearer {token}"}, timeout=25)
        response.raise_for_status()
        return [{"id": item["id"], "name": item["name"]} for item in response.json().get("files", [])]

    def search(self, query: str, limit: int = 5) -> ToolResult:
        started = perf_counter()
        folder_id = self.selected_folder()
        if not folder_id:
            return ToolResult(toolName="search_drive", query=query, records=[], latencyMs=0,
                              error="Choose a Google Drive folder in Knowledge sources before asking about company knowledge.")
        try:
            token = self._token()
            headers = {"Authorization": f"Bearer {token}"}
            response = httpx.get("https://www.googleapis.com/drive/v3/files", params={
                "q": f"'{folder_id}' in parents and trashed=false",
                "fields": "files(id,name,mimeType,webViewLink,modifiedTime,description)",
                "pageSize": 100, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
            }, headers=headers, timeout=25)
            response.raise_for_status()
            items = response.json().get("files", [])
            with ThreadPoolExecutor(max_workers=8, thread_name_prefix="drive-read") as executor:
                downloads = [executor.submit(self._file_text, item, headers) for item in items]
                contents = [future.result() for future in downloads]
            records: list[SourceRecord] = []
            for item, content in zip(items, contents):
                if content.strip():
                    records.append(SourceRecord(
                        id=f"drive:{item['id']}", source="drive", title=item["name"], content=content[:1_500_000],
                        url=item.get("webViewLink") or f"https://drive.google.com/open?id={quote(item['id'])}",
                        createdAt=item.get("modifiedTime"), metadata={"mimeType": item.get("mimeType", "")},
                    ))
            result = self._rank(query, records, limit)
            return result.model_copy(update={"latencyMs": int((perf_counter() - started) * 1000)})
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            reason = (str(exc) if isinstance(exc, ValueError) and str(exc) else
                      f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError)
                      else type(exc).__name__)
            return ToolResult(toolName="search_drive", query=" ".join(query.split()), records=[],
                              latencyMs=int((perf_counter() - started) * 1000),
                              error=f"Google Drive request failed: {reason}")

    def _token(self) -> str:
        token = access_token(self.oauth_store, "drive", self.config.google_client_id, self.config.google_client_secret)
        if not token:
            raise ValueError("Google Drive is not connected")
        return token

    @staticmethod
    def _file_text(item: dict, headers: dict[str, str]) -> str:
        file_id = quote(item["id"])
        mime = item.get("mimeType", "")
        if mime == "application/vnd.google-apps.folder":
            return ""
        if mime.startswith("application/vnd.google-apps."):
            url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export"
            response = httpx.get(url, params={"mimeType": "text/plain"}, headers=headers, timeout=30)
        elif mime.startswith("text/") or mime == "application/json":
            response = httpx.get(f"https://www.googleapis.com/drive/v3/files/{file_id}", params={"alt": "media"}, headers=headers, timeout=30)
        else:
            return ""
        response.raise_for_status()
        return response.text

    @staticmethod
    def _rank(query: str, records: list[SourceRecord], limit: int) -> ToolResult:
        ignored = {"what", "when", "where", "which", "who", "whom", "whose", "how", "many", "much", "does", "did", "do", "is", "are", "was", "were", "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "at", "by", "with", "about", "tell", "me", "please", "our", "my", "their", "this", "that", "from", "can", "you", "show", "find", "give"}
        words = [w for w in re.findall(r"[\w-]+", query.casefold()) if len(w) > 1 and w not in ignored]
        ranked = []
        for record in records:
            # CSV rows and prose lines become independent passages; score them against
            # the question and retain the parent file ID so citations open the source.
            if record.title.casefold().endswith(".csv"):
                rows = csv.DictReader(io.StringIO(record.content))
                chunks = ["; ".join(f"{key}: {value.strip()}" for key, value in row.items()
                                    if key and value and value.strip()) for row in rows]
                chunks = [chunk for chunk in chunks if chunk]
            else:
                chunks = [part.strip() for part in re.split(r"\n+|(?<=[.!?])\s+", record.content) if part.strip()]
            if not chunks:
                chunks = [record.content]
            passage_scores = sorted(
                ((sum(chunk.casefold().count(word) for word in words), chunk) for chunk in chunks),
                key=lambda item: (-item[0], item[1].casefold()),
            )
            matching = [(score, chunk) for score, chunk in passage_scores if score > 0][:5]
            score = sum(item[0] for item in matching[:3])
            score += sum(3 for word in words if word in record.title.casefold())
            if score:
                excerpt = "\n".join(chunk for _, chunk in matching) or record.content[:2200]
                ranked.append((score, record.model_copy(update={"content": excerpt[:5000]})))
        ranked.sort(key=lambda pair: (-pair[0], pair[1].title.casefold()))
        return ToolResult(toolName="search_drive", query=" ".join(query.split()),
                          records=[record for _, record in ranked[:max(0, limit)]], latencyMs=0)
