"""Offline contract tests for live Notion page search and block pagination."""

from app.connectors.config import ConnectorConfig
from app.connectors.live import LiveConnector


class _Response:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): return self
    def json(self): return self.payload


def _page():
    return {"id": "page-1", "object": "page", "url": "https://notion.test/page-1",
            "last_edited_time": "2026-11-01T10:00:00Z",
            "properties": {"Name": {"type": "title", "title": [{"plain_text": "Sprint notes"}]}}}


def test_notion_search_and_block_pagination_build_a_complete_source_record(monkeypatch, tmp_path):
    calls = []

    class _Client:
        def __init__(self, **kwargs): self.kwargs = kwargs
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, url, json):
            calls.append(("post", url, json))
            return _Response({"results": [_page()]})
        def get(self, url, params):
            calls.append(("get", url, params.copy()))
            if params.get("start_cursor"):
                return _Response({"results": [{"type": "bulleted_list_item", "bulleted_list_item": {
                    "rich_text": [{"plain_text": "Follow up with design"}]}}], "has_more": False})
            return _Response({"results": [{"type": "paragraph", "paragraph": {
                "rich_text": [{"plain_text": "Discussed release readiness."}]}}],
                "has_more": True, "next_cursor": "cursor-2"})

    monkeypatch.setattr("app.connectors.live.httpx.Client", _Client)
    connector = LiveConnector("notion", ConnectorConfig(
        enable_live=True, notion_token="test-notion-token",
        oauth_db_path=str(tmp_path / "oauth.sqlite3"),
    ))
    result = connector.search("Summarize my latest meeting notes", limit=3)

    assert result.error is None
    assert len(result.records) == 1
    record = result.records[0]
    assert record.id == "notion:page-1"
    assert record.title == "Sprint notes"
    assert "release readiness" in record.content
    assert "Follow up with design" in record.content
    assert calls[0][2] == {"page_size": 3}
    assert calls[2][2]["start_cursor"] == "cursor-2"


def test_notion_specific_query_is_sent_to_search_endpoint(monkeypatch, tmp_path):
    captured = {}

    class _Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, url, json):
            captured.update(json)
            return _Response({"results": []})

    monkeypatch.setattr("app.connectors.live.httpx.Client", _Client)
    connector = LiveConnector("notion", ConnectorConfig(
        enable_live=True, notion_token="test-notion-token",
        oauth_db_path=str(tmp_path / "oauth.sqlite3"),
    ))

    result = connector.search("Atlas launch brief", limit=2)

    assert result.error is None
    assert captured == {"page_size": 2, "query": "Atlas launch brief"}


def test_notion_retries_with_entity_phrase_and_drops_unrelated_pages(monkeypatch, tmp_path):
    searches = []

    def page(page_id, title):
        return {"id": page_id, "object": "page", "url": f"https://notion.test/{page_id}",
                "last_edited_time": "2026-11-01T10:00:00Z",
                "properties": {"Name": {"type": "title", "title": [{"plain_text": title}]}}}

    class _Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, url, json):
            searches.append(json["query"])
            if len(searches) == 1:
                return _Response({"results": [page("atlas", "Parallax Atlas Launch Brief")]})
            return _Response({"results": [page("northstar", "Northstar Labs Analytics Rollout")]})
        def get(self, url, params):
            return _Response({"results": [], "has_more": False})

    monkeypatch.setattr("app.connectors.live.httpx.Client", _Client)
    connector = LiveConnector("notion", ConnectorConfig(
        enable_live=True, notion_token="test-notion-token",
        oauth_db_path=str(tmp_path / "oauth.sqlite3"),
    ))

    result = connector.search("Northstar Labs Analytics Rollout project brief", limit=3)

    assert result.error is None
    assert searches == ["Northstar Labs Analytics Rollout project brief", "Northstar Labs Analytics Rollout"]
    assert [item.id for item in result.records] == ["notion:northstar"]
