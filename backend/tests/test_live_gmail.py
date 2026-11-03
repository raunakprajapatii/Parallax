"""Offline contract tests for live Gmail search, counts, paging, and MIME decoding."""

import base64

from app.connectors.config import ConnectorConfig
from app.connectors.live import LiveConnector


def _encoded(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return self

    def json(self):
        return self.payload


def _connector(tmp_path):
    return LiveConnector("gmail", ConnectorConfig(
        enable_live=True, gmail_token="test-access-token", oauth_db_path=str(tmp_path / "oauth.sqlite3"),
    ))


def test_gmail_follows_message_pages_and_decodes_nested_plain_text(monkeypatch, tmp_path):
    calls = []

    class _Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get(self, url, params, headers):
            calls.append((url, params.copy()))
            if url.endswith("/messages"):
                if params.get("pageToken") == "next":
                    return _Response({"messages": [{"id": "m2"}]})
                return _Response({"messages": [{"id": "m1"}], "nextPageToken": "next"})
            msg_id = url.rsplit("/", 1)[-1]
            payload = {"mimeType": "multipart/mixed", "parts": [{"mimeType": "multipart/alternative", "parts": [
                {"mimeType": "text/plain", "body": {"data": _encoded(f"body {msg_id}")}},
                {"mimeType": "text/html", "body": {"data": _encoded("<p>html</p>")}},
            ]}]}
            return _Response({"id": msg_id, "threadId": "thread-1", "labelIds": ["INBOX", "UNREAD"],
                              "payload": {"headers": [{"name": "Subject", "value": f"subject {msg_id}"}], **payload}})

    monkeypatch.setattr("app.connectors.live.httpx.Client", _Client)
    result = _connector(tmp_path).search("newer_than:30d", limit=2)

    assert result.error is None
    assert [record.id for record in result.records] == ["gmail:m1", "gmail:m2"]
    assert "body m1" in result.records[0].content
    assert "html" not in result.records[0].content
    assert result.records[0].metadata["unread"] == "true"
    assert calls[0][1]["maxResults"] == 2
    assert calls[1][1]["pageToken"] == "next"


def test_gmail_count_walks_all_result_pages_without_fetching_message_bodies(monkeypatch, tmp_path):
    page_calls = []

    class _Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def get(self, url, params, headers):
            assert url.endswith("/messages")
            page_calls.append(params)
            if params.get("pageToken") == "next":
                return _Response({"messages": [{"id": "m3"}, {"id": "m4"}]})
            return _Response({"messages": [{"id": "m1"}, {"id": "m2"}], "nextPageToken": "next"})

    monkeypatch.setattr("app.connectors.live.httpx.Client", _Client)
    result = _connector(tmp_path).search("is:unread __parallax_count__", limit=5)

    assert result.error is None
    assert result.records[0].metadata == {"count": "4", "countType": "unread"}
    assert page_calls[0]["q"] == "is:unread"
    assert page_calls[0]["maxResults"] == 500
    assert page_calls[1]["pageToken"] == "next"
