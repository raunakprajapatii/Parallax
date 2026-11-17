"""Google Drive retrieval with a small demo corpus and folder-scoped live search."""
from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import csv
import io
import struct
import math
from time import perf_counter
from urllib.parse import quote

import httpx

from app.agent.models import SourceRecord, ToolResult
from .config import ConnectorConfig
from .oauth import OAuthStore, access_token


_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_model = None


def _embed(texts: list[str]):
    """Create normalized, local sentence embeddings; model loads on first use."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_EMBEDDING_MODEL)
    return _model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def _query_profile(query: str) -> tuple[str, str, tuple[str, ...]]:
    """Identify the document family and add useful lexical variants."""
    text = query.casefold()
    if any(term in text for term in ("policy", "carryover", "carry over", "carry forward", "entitlement", "eligibility", "rule")):
        synonyms = ("policy", "handbook", "carryover", "carry", "forward", "unused", "balance", "entitlement")
        return "policy", "policy handbook leave carryover carry forward unused balance entitlement", synonyms
    if any(term in text for term in ("leave request", "leave status", "who requested leave", "time off request")):
        return "leave_record", query, ("leave", "request", "employee", "status")
    if any(term in text for term in ("customer", "account", "client", "renewal", "account owner")):
        return "customer", query, ("customer", "account", "account_name", "account_owner", "lifecycle_stage")
    if any(term in text for term in ("project", "initiative", "blocker", "launch", "work item", "status")):
        return "project", query, ("project", "initiative", "status", "owner", "blocker")
    return "general", query, ()


def _intent_title_boost(intent: str, title: str) -> float:
    name = title.casefold()
    if intent == "policy":
        if any(term in name for term in ("policy", "handbook")):
            return 0.012
        if any(term in name for term in ("request", "ticket", "work_item")):
            return -0.012
    if intent == "leave_record":
        if "leave" in name and "request" in name:
            return 0.01
        if "policy" in name or "handbook" in name:
            return -0.006
    if intent == "customer":
        if any(term in name for term in ("customer", "account")):
            return 0.01
        if "support_ticket" in name or "support ticket" in name:
            return -0.006
    return 0.0


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
        demo_folder = "__parallax_demo_drive__"
        with sqlite3.connect(self.db_path, timeout=30) as db:
            self._ensure_index(db)
            current = {record.id.removeprefix("drive:"): record for record in records}
            indexed = {row[0]: row[1] for row in db.execute(
                "SELECT file_id, content_hash FROM drive_rag_documents WHERE folder_id=?", (demo_folder,))}
            for file_id in indexed.keys() - current.keys():
                self._delete_document(db, file_id)
            for file_id, record in current.items():
                digest = hashlib.sha256(record.content.encode("utf-8")).hexdigest()
                if indexed.get(file_id) == digest:
                    continue
                item = {"id": file_id, "name": record.title, "mimeType": record.metadata.get("mimeType", "text/plain"),
                        "webViewLink": record.url or "", "modifiedTime": record.createdAt or ""}
                self._store_document(db, demo_folder, item, record.content)
        return self._retrieve(query, demo_folder, limit)

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
            items = self._list_folder_files(folder_id, headers)
            self._index_files(folder_id, items, headers)
            result = self._retrieve(query, folder_id, limit)
            return result.model_copy(update={"latencyMs": int((perf_counter() - started) * 1000)})
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            reason = (str(exc) if isinstance(exc, ValueError) and str(exc) else
                      f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError)
                      else type(exc).__name__)
            return ToolResult(toolName="search_drive", query=" ".join(query.split()), records=[],
                              latencyMs=int((perf_counter() - started) * 1000),
                              error=f"Google Drive request failed: {reason}")

    def _list_folder_files(self, folder_id: str, headers: dict[str, str]) -> list[dict]:
        """List files below the selected folder, including nested folders."""
        items: list[dict] = []
        pending, visited = [folder_id], set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            page_token = None
            while True:
                params = {
                    "q": f"'{current}' in parents and trashed=false",
                    "fields": "nextPageToken,files(id,name,mimeType,webViewLink,modifiedTime,md5Checksum,size)",
                    "pageSize": 100, "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
                }
                if page_token:
                    params["pageToken"] = page_token
                response = httpx.get("https://www.googleapis.com/drive/v3/files", params=params,
                                     headers=headers, timeout=25)
                response.raise_for_status()
                data = response.json()
                for item in data.get("files", []):
                    if item.get("mimeType") == "application/vnd.google-apps.folder":
                        pending.append(item["id"])
                    else:
                        items.append(item)
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        return items

    def _index_files(self, folder_id: str, items: list[dict], headers: dict[str, str]) -> None:
        """Incrementally ingest changed Drive files into a local passage index."""
        supported = [item for item in items if self._is_supported(item)]
        with sqlite3.connect(self.db_path, timeout=30) as db:
            self._ensure_index(db)
            present = {item["id"] for item in supported}
            indexed = {row[0]: row[1] for row in db.execute(
                "SELECT file_id, modified_time FROM drive_rag_documents WHERE folder_id=?", (folder_id,))}
            unembedded = {row[0] for row in db.execute(
                "SELECT DISTINCT d.file_id FROM drive_rag_documents d "
                "JOIN drive_rag_passages p ON p.file_id=d.file_id "
                "WHERE d.folder_id=? AND p.embedding IS NULL", (folder_id,))}
            for file_id in indexed.keys() - present:
                self._delete_document(db, file_id)
            changed = [item for item in supported
                       if indexed.get(item["id"]) != item.get("modifiedTime", "") or item["id"] in unembedded]
            with ThreadPoolExecutor(max_workers=8, thread_name_prefix="drive-read") as executor:
                downloads = {item["id"]: executor.submit(self._file_text, item, headers) for item in changed}
                for item in changed:
                    content = downloads[item["id"]].result()
                    self._store_document(db, folder_id, item, content)

    @staticmethod
    def _ensure_index(db: sqlite3.Connection) -> None:
        db.execute("""CREATE TABLE IF NOT EXISTS drive_rag_documents (
            file_id TEXT PRIMARY KEY, folder_id TEXT NOT NULL, title TEXT NOT NULL,
            mime_type TEXT NOT NULL, url TEXT, modified_time TEXT NOT NULL,
            content_hash TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS drive_rag_passages (
            passage_id INTEGER PRIMARY KEY, file_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
            content TEXT NOT NULL, UNIQUE(file_id, ordinal))""")
        db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS drive_rag_fts USING fts5(
            title, content, file_id UNINDEXED, passage_id UNINDEXED,
            tokenize='unicode61 remove_diacritics 2')""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(drive_rag_passages)")}
        if "embedding" not in columns:
            db.execute("ALTER TABLE drive_rag_passages ADD COLUMN embedding BLOB")

    @staticmethod
    def _is_supported(item: dict) -> bool:
        mime = item.get("mimeType", "")
        return mime.startswith("text/") or mime in {
            "application/json", "application/csv", "application/pdf", "application/vnd.google-apps.document",
            "application/vnd.google-apps.spreadsheet", "application/vnd.google-apps.presentation",
        }

    @classmethod
    def _store_document(cls, db: sqlite3.Connection, folder_id: str, item: dict, content: str) -> None:
        file_id = item["id"]
        content = content[:1_500_000]
        passages = cls._chunk_content(content, item.get("mimeType", ""))
        vectors = _embed([f"{item['name']}\n{passage}" for passage in passages]) if passages else []
        digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        cls._delete_document(db, file_id)
        db.execute("""INSERT OR REPLACE INTO drive_rag_documents
            (file_id, folder_id, title, mime_type, url, modified_time, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (file_id, folder_id, item["name"], item.get("mimeType", ""),
             item.get("webViewLink") or f"https://drive.google.com/open?id={quote(file_id)}",
             item.get("modifiedTime", ""), digest))
        for ordinal, (passage, vector) in enumerate(zip(passages, vectors)):
            embedding = struct.pack(f"{len(vector)}f", *vector)
            cursor = db.execute("INSERT INTO drive_rag_passages(file_id, ordinal, content, embedding) VALUES (?, ?, ?, ?)",
                                (file_id, ordinal, passage, embedding))
            db.execute("INSERT INTO drive_rag_fts(rowid, title, content, file_id, passage_id) VALUES (?, ?, ?, ?, ?)",
                       (cursor.lastrowid, item["name"], passage, file_id, cursor.lastrowid))

    @staticmethod
    def _delete_document(db: sqlite3.Connection, file_id: str) -> None:
        rows = list(db.execute("SELECT passage_id FROM drive_rag_passages WHERE file_id=?", (file_id,)))
        db.executemany("DELETE FROM drive_rag_fts WHERE rowid=?", rows)
        db.execute("DELETE FROM drive_rag_passages WHERE file_id=?", (file_id,))
        db.execute("DELETE FROM drive_rag_documents WHERE file_id=?", (file_id,))

    @staticmethod
    def _chunk_content(content: str, mime_type: str, max_chars: int = 1100) -> list[str]:
        """Split prose into overlapping passages and CSV into row-level passages."""
        if not content or not content.strip():
            return []
        lines = content.splitlines()
        looks_tabular = len(lines) > 1 and "," in lines[0] and all("," in line for line in lines[1:min(len(lines), 4)])
        if "csv" in mime_type or looks_tabular:
            try:
                rows = csv.DictReader(io.StringIO(content))
                passages = ["; ".join(f"{key}: {value.strip()}" for key, value in row.items()
                                      if key and value and value.strip()) for row in rows]
                return [passage[:max_chars] for passage in passages if passage]
            except csv.Error:
                pass
        units = [unit.strip() for unit in re.split(r"\n\s*\n|(?<=[.!?])\s+", content) if unit.strip()]
        passages: list[str] = []
        current = ""
        for unit in units:
            if len(unit) > max_chars:
                if current:
                    passages.append(current)
                    current = ""
                start = 0
                while start < len(unit):
                    end = min(start + max_chars, len(unit))
                    if end < len(unit):
                        boundary = unit.rfind(" ", start, end)
                        if boundary > start + max_chars // 2:
                            end = boundary
                    passages.append(unit[start:end].strip())
                    start = max(start + 1, end - 120)
                continue
            if current and len(current) + len(unit) + 1 > max_chars:
                passages.append(current)
                current = current[-120:] + " " + unit
            else:
                current = f"{current} {unit}".strip()
        if current:
            passages.append(current)
        return passages

    def _retrieve(self, query: str, folder_id: str, limit: int) -> ToolResult:
        intent, semantic_query, expansions = _query_profile(query)
        query_vector = _embed([semantic_query])[0]
        query_vector = [float(value) for value in query_vector]
        query_norm = math.sqrt(sum(value * value for value in query_vector)) or 1.0
        query_vector = [value / query_norm for value in query_vector]
        with sqlite3.connect(self.db_path, timeout=30) as db:
            self._ensure_index(db)
            rows = db.execute("""SELECT p.passage_id, d.file_id, d.title, d.mime_type, d.url,
                       d.modified_time, p.content, p.embedding
                FROM drive_rag_passages p JOIN drive_rag_documents d ON d.file_id=p.file_id
                WHERE d.folder_id=? AND p.embedding IS NOT NULL""", (folder_id,)).fetchall()
            terms = list(dict.fromkeys([*re.findall(r"[\w-]+", query.casefold()), *expansions]))
            terms = [term for term in terms if len(term) > 1 and term not in {
                "what", "when", "where", "which", "who", "how", "does", "did", "the", "and",
                "for", "with", "from", "tell", "about", "please"}]
            lexical_rows = []
            if terms:
                match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms[:24])
                lexical_rows = db.execute("""SELECT CAST(f.passage_id AS INTEGER), bm25(drive_rag_fts, 3.0, 1.0)
                    FROM drive_rag_fts f JOIN drive_rag_passages p ON p.passage_id=CAST(f.passage_id AS INTEGER)
                    JOIN drive_rag_documents d ON d.file_id=p.file_id
                    WHERE drive_rag_fts MATCH ? AND d.folder_id=? ORDER BY bm25(drive_rag_fts, 3.0, 1.0)""",
                    (match, folder_id)).fetchall()
        semantic_scores: dict[int, float] = {}
        passage_rows: dict[int, tuple] = {}
        for row in rows:
            passage_id, file_id, title, mime, url, modified, passage, raw_vector = row
            vector = struct.unpack(f"{len(raw_vector) // 4}f", raw_vector)
            semantic_scores[passage_id] = sum(a * b for a, b in zip(query_vector, vector))
            passage_rows[passage_id] = (file_id, title, mime, url, modified, passage)

        # Reciprocal-rank fusion avoids comparing cosine values with FTS5's
        # negative BM25 values directly. Both retrievers get a vote; semantic
        # matches carry slightly more weight, while exact term hits still help.
        semantic_rank = sorted(semantic_scores, key=lambda pid: semantic_scores[pid], reverse=True)[:max(50, limit * 20)]
        lexical_rank = [int(pid) for pid, _ in lexical_rows]
        combined: dict[int, float] = {}
        rrf_k = 60
        for rank, passage_id in enumerate(semantic_rank, 1):
            combined[passage_id] = 0.65 / (rrf_k + rank)
        for rank, passage_id in enumerate(lexical_rank, 1):
            combined[passage_id] = combined.get(passage_id, 0.0) + 0.35 / (rrf_k + rank)
        grouped: dict[str, dict] = {}
        for passage_id, score in combined.items():
            file_id, title, mime, url, modified, passage = passage_rows[passage_id]
            doc = grouped.setdefault(file_id, {"title": title, "mime": mime, "url": url,
                                                "modified": modified, "passages": [], "score": 0.0})
            score += _intent_title_boost(intent, title)
            doc["passages"].append((score, passage))
        for doc in grouped.values():
            best = sorted((score for score, _ in doc["passages"]), reverse=True)[:3]
            doc["score"] = sum(best)
            doc["passages"].sort(key=lambda item: item[0], reverse=True)
        ranked = sorted(grouped.items(), key=lambda pair: (-pair[1]["score"], pair[1]["title"].casefold()))[:max(0, limit)]
        records = [SourceRecord(
            id=f"drive:{file_id}", source="drive", title=doc["title"],
            content="\n\n".join(text for _, text in doc["passages"][:3]),
            url=doc["url"], createdAt=doc["modified"],
            metadata={"mimeType": doc["mime"], "retrieval": "hybrid_vector_bm25"})
            for file_id, doc in ranked]
        return ToolResult(toolName="search_drive", query=" ".join(query.split()), records=records, latencyMs=0)

    def _retrieve_fts_legacy(self, query: str, folder_id: str, limit: int) -> ToolResult:
        terms = list(dict.fromkeys(re.findall(r"[\w-]+", query.casefold())))
        terms = [term for term in terms if len(term) > 1 and term not in {
            "what", "when", "where", "which", "who", "how", "does", "did", "the", "and", "for", "with", "from", "tell", "about", "please"}]
        if not terms:
            return ToolResult(toolName="search_drive", query=" ".join(query.split()), records=[], latencyMs=0)
        match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms[:24])
        with sqlite3.connect(self.db_path, timeout=30) as db:
            self._ensure_index(db)
            rows = db.execute("""SELECT d.file_id, d.title, d.mime_type, d.url, d.modified_time,
                       p.content, bm25(drive_rag_fts, 3.0, 1.0) AS score
                FROM drive_rag_fts f
                JOIN drive_rag_passages p ON p.passage_id=CAST(f.passage_id AS INTEGER)
                JOIN drive_rag_documents d ON d.file_id=f.file_id
                WHERE drive_rag_fts MATCH ? AND d.folder_id=?
                ORDER BY score, d.title COLLATE NOCASE LIMIT ?""",
                (match, folder_id, max(limit * 6, 18))).fetchall()
        grouped: dict[str, dict] = {}
        for file_id, title, mime, url, modified, passage, score in rows:
            doc = grouped.setdefault(file_id, {"title": title, "mime": mime, "url": url,
                                                "modified": modified, "passages": [], "score": score})
            if len(doc["passages"]) < 3 and passage not in doc["passages"]:
                doc["passages"].append(passage)
                doc["score"] += score
        ranked = sorted(grouped.items(), key=lambda pair: (pair[1]["score"], pair[1]["title"].casefold()))[:max(0, limit)]
        records = [SourceRecord(
            id=f"drive:{file_id}", source="drive", title=doc["title"],
            content="\n\n".join(doc["passages"]), url=doc["url"], createdAt=doc["modified"],
            metadata={"mimeType": doc["mime"], "retrieval": "sqlite_fts5_bm25"})
            for file_id, doc in ranked]
        return ToolResult(toolName="search_drive", query=" ".join(query.split()), records=records, latencyMs=0)

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
        if mime == "application/pdf":
            response = httpx.get(f"https://www.googleapis.com/drive/v3/files/{file_id}",
                                 params={"alt": "media"}, headers=headers, timeout=30)
            response.raise_for_status()
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(response.content))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
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
