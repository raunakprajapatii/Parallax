"""Regression coverage for Jira Cloud live search handling."""

from app.connectors.config import ConnectorConfig
from app.connectors.live import LiveConnector, _plain


class _Response:
    def raise_for_status(self):
        return self

    def json(self):
        return {
            "issues": [{
                "key": "SCRUM-1",
                "fields": {
                    "summary": "Create UI for Auth",
                    "description": {"type": "doc", "content": [
                        {"type": "paragraph", "content": [
                            {"type": "text", "text": "Create a clean "},
                            {"type": "text", "text": "authentication UI."},
                        ]},
                    ]},
                    "status": {"name": "To Do"},
                    "assignee": {"displayName": "Jesse Pinkman"},
                    "priority": None,
                    "updated": "2026-11-01T00:00:00.000+0000",
                },
            }]
        }


class _Client:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, json):
        assert url == "https://example.atlassian.net/rest/api/3/search/jql"
        assert json["jql"] == 'key in ("SCRUM-1") ORDER BY updated DESC'
        return _Response()


def test_live_jira_issue_key_search_handles_null_priority_and_includes_owner(monkeypatch):
    monkeypatch.setattr("app.connectors.live.httpx.Client", _Client)
    connector = LiveConnector("jira", ConnectorConfig(
        enable_live=True,
        jira_base_url="https://example.atlassian.net",
        jira_email="demo@example.com",
        jira_token="test-token",
    ))

    result = connector.search("What is the status and assignee of Jira issue SCRUM-1")

    assert result.error is None
    assert len(result.records) == 1
    issue = result.records[0]
    assert issue.metadata == {"status": "To Do", "assignee": "Jesse Pinkman", "priority": "Not set",
                              "description": "Create a clean authentication UI."}
    assert "Status: To Do" in issue.content
    assert "Assignee: Jesse Pinkman" in issue.content
    assert "Priority: Not set" in issue.content
    assert issue.metadata["description"] == "Create a clean authentication UI."
    assert "doc paragraph text" not in issue.content


def test_jira_description_parser_handles_paragraphs_and_lists():
    adf = {"type": "doc", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "Issue summary."}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "First requirement"},
            ]}]},
        ]},
    ]}

    assert _plain(adf) == "Issue summary.\n• First requirement\n"
