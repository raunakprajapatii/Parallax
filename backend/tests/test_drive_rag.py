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

