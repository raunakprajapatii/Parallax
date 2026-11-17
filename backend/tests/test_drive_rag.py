import sqlite3
import struct

from app.connectors.config import ConnectorConfig
from app.connectors.drive import DriveConnector


def test_hybrid_drive_retrieval_combines_semantic_and_keyword_rankings(tmp_path, monkeypatch):
    db_path = tmp_path / "drive.sqlite3"
    connector = DriveConnector(ConnectorConfig(oauth_db_path=str(db_path)))
    vectors = {
        "query": [1.0, 0.0],
        "semantic": [0.99, 0.01],
        "keyword": [0.0, 1.0],
    }
    monkeypatch.setattr("app.connectors.drive._embed", lambda texts: [vectors[t] for t in texts])
    with sqlite3.connect(db_path) as db:
        connector._ensure_index(db)
        documents = [
            ("semantic", "Conceptually related", "A semantic concept."),
            ("keyword", "Exact phrase target", "The query keyword is present."),
        ]
        for file_id, title, content in documents:
            db.execute("""INSERT INTO drive_rag_documents
                (file_id, folder_id, title, mime_type, url, modified_time, content_hash)
                VALUES (?, 'folder', ?, 'text/plain', ?, '', '')""", (file_id, title, f"https://drive/{file_id}"))
            vector_key = "semantic" if file_id == "semantic" else "keyword"
            embedding = struct.pack("2f", *vectors[vector_key])
            cursor = db.execute("INSERT INTO drive_rag_passages(file_id, ordinal, content, embedding) VALUES (?, 0, ?, ?)",
                                (file_id, content, embedding))
            db.execute("INSERT INTO drive_rag_fts(rowid, title, content, file_id, passage_id) VALUES (?, ?, ?, ?, ?)",
                       (cursor.lastrowid, title, content, file_id, cursor.lastrowid))

    result = connector._retrieve("query", "folder", 2)

    assert {record.id for record in result.records} == {"drive:semantic", "drive:keyword"}
    assert result.records[0].metadata["retrieval"] == "hybrid_vector_bm25"


def test_csv_is_chunked_into_labeled_rows():
    passages = DriveConnector._chunk_content(
        "name,department\nAri,Sales\nBlair,Support", "text/csv")
    assert passages == ["name: Ari; department: Sales", "name: Blair; department: Support"]


def test_long_prose_chunks_overlap_for_context():
    text = " ".join(f"word{i}" for i in range(180))
    passages = DriveConnector._chunk_content(text, "text/plain", max_chars=200)
    assert len(passages) > 1
    assert set(passages[0].split()) & set(passages[1].split())


def test_retrieval_is_limited_to_requested_folder(tmp_path, monkeypatch):
    db_path = tmp_path / "drive.sqlite3"
    connector = DriveConnector(ConnectorConfig(oauth_db_path=str(db_path)))
    monkeypatch.setattr("app.connectors.drive._embed", lambda texts: [[1.0, 0.0] for _ in texts])
    with sqlite3.connect(db_path) as db:
        connector._ensure_index(db)
        for folder, file_id in (("one", "visible"), ("two", "hidden")):
            item = {"id": file_id, "name": "Sales directory", "mimeType": "text/plain",
                    "modifiedTime": "1", "webViewLink": f"https://drive/{file_id}"}
            DriveConnector._store_document(db, folder, item, "Sales representative roster")

    result = connector._retrieve("sales representative", "one", 5)

    assert [record.id for record in result.records] == ["drive:visible"]


def test_index_sync_removes_files_missing_from_drive_listing(tmp_path, monkeypatch):
    db_path = tmp_path / "drive.sqlite3"
    connector = DriveConnector(ConnectorConfig(oauth_db_path=str(db_path)))
    monkeypatch.setattr("app.connectors.drive._embed", lambda texts: [[1.0, 0.0] for _ in texts])
    with sqlite3.connect(db_path) as db:
        connector._ensure_index(db)
        DriveConnector._store_document(db, "folder", {
            "id": "removed", "name": "Old file", "mimeType": "text/plain", "modifiedTime": "1",
        }, "Obsolete content")

    connector._index_files("folder", [], {})

    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM drive_rag_documents WHERE folder_id='folder'").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM drive_rag_passages WHERE file_id='removed'").fetchone()[0] == 0


def test_policy_query_prefers_policy_document_over_leave_transaction_rows(tmp_path, monkeypatch):
    db_path = tmp_path / "drive.sqlite3"
    connector = DriveConnector(ConnectorConfig(oauth_db_path=str(db_path)))
    monkeypatch.setattr("app.connectors.drive._embed", lambda texts: [[1.0, 0.0] for _ in texts])
    with sqlite3.connect(db_path) as db:
        connector._ensure_index(db)
        docs = [
            ("policy", "People Operations Leave Policy.txt", "Annual leave policy: carry forward unused balance is limited to five days."),
            ("requests", "Leave Requests.csv", "Employee: Riya; leave request status: pending; annual leave dates."),
        ]
        for file_id, title, content in docs:
            DriveConnector._store_document(db, "folder", {
                "id": file_id, "name": title, "mimeType": "text/plain", "modifiedTime": "1",
            }, content)

    result = connector._retrieve("What does the annual leave policy say about carryover?", "folder", 2)

    assert result.records[0].id == "drive:policy"


def test_query_profile_expands_policy_synonyms_and_separates_leave_requests():
    from app.connectors.drive import _query_profile

    intent, semantic, terms = _query_profile("annual leave carryover policy")
    assert intent == "policy"
    assert "carry forward" in semantic
    assert "handbook" in terms
    assert _query_profile("Find Vishal's leave request")[0] == "leave_record"

