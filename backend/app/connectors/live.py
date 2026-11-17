"""Read-only HTTP clients for Gmail, Jira Cloud, and Notion."""
from __future__ import annotations

import base64
import re
from time import perf_counter
from typing import Any
from urllib.parse import quote

import httpx

from app.agent.models import SourceName, SourceRecord, ToolResult
from .config import ConnectorConfig
from .oauth import OAuthStore, access_token


_NOTION_QUERY_NOISE = {
    "a", "an", "and", "brief", "check", "compare", "details", "document", "for",
    "google", "in", "jira", "latest", "notion", "of", "on", "owner", "owners",
    "page", "pages", "project", "projects", "search", "status", "the", "to", "with",
}


def _notion_terms(query: str) -> set[str]:
    """Return discriminating query terms for filtering Notion search results."""
    return {word.casefold() for word in re.findall(r"[\w'-]+", query)
            if len(word) > 2 and word.casefold() not in _NOTION_QUERY_NOISE}


def _notion_relevance(query: str, title: str, content: str, *, broad: bool) -> tuple[bool, int]:
    """Reject pages returned by Notion that do not match a specific request."""
    if broad:
        return True, 0
    wanted = _notion_terms(query)
    if not wanted:
        return True, 0
    title_terms = _notion_terms(title)
    content_terms = _notion_terms(content)
    title_hits = wanted & title_terms
    content_hits = wanted & content_terms
    score = len(title_hits) * 3 + len(content_hits)
    # A title hit is normally enough for Notion's title-oriented search. A body
    # match needs two terms so a generic word like "approval" cannot pull in an
    # unrelated project page.
    return bool(title_hits or len(content_hits) >= 2), score


def _compact_notion_query(query: str) -> str:
    """Keep the entity name when the initial natural-language search is too broad."""
    words = [word for word in re.findall(r"[\w'-]+", query)
             if word.casefold() not in _NOTION_QUERY_NOISE]
    return " ".join(words[:6])


def _plain(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_plain(item) for item in value)
    if isinstance(value, dict):
        if isinstance(value.get("plain_text"), str):
            return value["plain_text"]
        node_type = value.get("type")
        if node_type == "text":
            return str(value.get("text", ""))
        if node_type == "hardBreak":
            return "\n"
        if node_type == "mention":
            return str((value.get("attrs") or {}).get("text", "@someone"))
        children = _plain(value.get("content", []))
        if node_type == "listItem":
            return f"• {children.strip()}\n"
        if node_type in {"paragraph", "heading", "codeBlock"}:
            return f"{children.strip()}\n" if children.strip() else ""
        if node_type in {"bulletList", "orderedList", "doc"}:
            return children
        if isinstance(value.get("text"), str):
            return value["text"]
        return children
    return ""


class LiveConnector:
    def __init__(self, source: SourceName, config: ConnectorConfig):
        self.source, self.config = source, config

    def search(self, query: str, limit: int = 5) -> ToolResult:
        started = perf_counter()
        try:
            if self.source == "gmail":
                records = self._gmail(query, limit)
            elif self.source == "jira":
                records = self._jira(query, limit)
            else:
                records = self._notion(query, limit)
            return ToolResult(toolName=f"search_{self.source}", query=query, records=records,
                              latencyMs=int((perf_counter() - started) * 1000))
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            reason = "authentication rejected" if status == 401 else "permission denied" if status == 403 else f"HTTP {status}"
            return ToolResult(toolName=f"search_{self.source}", query=query, records=[],
                              latencyMs=int((perf_counter() - started) * 1000),
                              error=f"{self.source} request failed: {reason}")
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return ToolResult(toolName=f"search_{self.source}", query=query, records=[],
                              latencyMs=int((perf_counter() - started) * 1000),
                              error=f"{self.source} request failed: {type(exc).__name__}")

    def _gmail(self, query: str, limit: int) -> list[SourceRecord]:
        count_requested = "__parallax_count__" in query
        query = query.replace("__parallax_count__", "").strip()
        token = access_token(OAuthStore(self.config.oauth_db_path), "gmail",
                             self.config.google_client_id, self.config.google_client_secret)
        if not token:
            token = self.config.gmail_token
            if self.config.gmail_refresh_token and self.config.google_client_id and self.config.google_client_secret:
                refreshed = httpx.post("https://oauth2.googleapis.com/token", timeout=15, data={
                    "client_id": self.config.google_client_id,
                    "client_secret": self.config.google_client_secret,
                    "refresh_token": self.config.gmail_refresh_token,
                    "grant_type": "refresh_token",
                })
                refreshed.raise_for_status()
                token = refreshed.json().get("access_token")
        if not token:
            raise ValueError("Connect Gmail at /api/oauth/gmail/connect or configure Google OAuth credentials")
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(timeout=20) as client:
            endpoint = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
            items: list[dict[str, str]] = []
            page_token = None
            first_page: dict[str, Any] = {}
            item_cap = 5000 if count_requested else min(max(limit, 1), 500)
            while len(items) < item_cap:
                page_size = 500 if count_requested else min(100, max(limit - len(items), 1))
                params: dict[str, Any] = {"q": query, "maxResults": page_size}
                if page_token:
                    params["pageToken"] = page_token
                data = client.get(endpoint, params=params, headers=headers).raise_for_status().json()
                if not first_page:
                    first_page = data
                items.extend(data.get("messages", []))
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
            if count_requested:
                total = len(items)
                label = ("unread" if "is:unread" in query else
                         "important" if "is:important" in query else "matching")
                noun = "emails" if label == "matching" else f"{label} emails"
                return [SourceRecord(id=f"gmail:count:{label}", source="gmail", title=f"Email count",
                    content=f"There are {total} {noun} matching the Gmail query.",
                    metadata={"count": str(total), "countType": label})]
            records = []
            for item in items[:limit]:
                message = client.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}",
                                     params={"format": "full"}, headers=headers).raise_for_status().json()
                headers_by_name = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
                def walk_parts(part: dict[str, Any]) -> list[str]:
                    found: list[str] = []
                    body = part.get("body", {}).get("data")
                    if body and part.get("mimeType") == "text/plain":
                        found.append(base64.urlsafe_b64decode(body + "==").decode("utf-8", "replace"))
                    for child in part.get("parts", []):
                        found.extend(walk_parts(child))
                    return found
                texts = walk_parts(message.get("payload", {}))
                labels = message.get("labelIds", [])
                records.append(SourceRecord(id=f"gmail:{message['id']}", source="gmail",
                    title=headers_by_name.get("subject", "(no subject)"),
                    content=" ".join(texts) or message.get("snippet", ""),
                    url=f"https://mail.google.com/mail/u/0/#all/{message['id']}",
                    author=headers_by_name.get("from"), createdAt=headers_by_name.get("date"),
                    metadata={"threadId": message.get("threadId", ""), "labels": ",".join(labels),
                              "unread": str("UNREAD" in labels).lower(),
                              "important": str("IMPORTANT" in labels).lower()}))
            return records

    def _jira(self, query: str, limit: int) -> list[SourceRecord]:
        cfg = self.config
        oauth_store = OAuthStore(cfg.oauth_db_path)
        oauth_access = access_token(oauth_store, "jira", cfg.jira_oauth_client_id, cfg.jira_oauth_client_secret)
        cloud_base = None
        if oauth_access:
            with httpx.Client(timeout=15, headers={"Authorization": f"Bearer {oauth_access}",
                                                   "Accept": "application/json"}) as client:
                sites = client.get("https://api.atlassian.com/oauth/token/accessible-resources").raise_for_status().json()
            if not sites:
                raise ValueError("No Jira site is available to this Atlassian account")
            site = sites[0]
            cloud_base = f"https://api.atlassian.com/ex/jira/{site['id']}"
            web_base = site.get("url", "")
        elif cfg.jira_base_url and cfg.jira_email and cfg.jira_token:
            cloud_base = cfg.jira_base_url.rstrip("/")
            web_base = cloud_base
        else:
            raise ValueError("Connect Jira at /api/oauth/jira/connect or configure Jira API token credentials")
        issue_keys = list(dict.fromkeys(re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", query.upper())))
        if issue_keys:
            keys = ", ".join(f'"{key}"' for key in issue_keys)
            jql = f"key in ({keys}) ORDER BY updated DESC"
        else:
            lower_query = query.casefold()
            if re.search(r"\b(latest|recent|newest)\b.*\b(update|activity|issue|ticket)|\bcheck jira\b", lower_query):
                jql = "updated >= -30d ORDER BY updated DESC"
            elif re.search(r"\b(overdue|past due|late)\b", lower_query):
                jql = "due < now() AND resolution IS EMPTY ORDER BY due ASC"
            elif "unresolved" in lower_query and any(term in lower_query for term in ("high", "highest", "critical")):
                jql = 'resolution IS EMPTY AND priority in ("Highest", "High", "Critical") ORDER BY priority DESC, updated DESC'
            elif any(term in lower_query for term in ("assigned to me", "my tasks", "tasks assigned")):
                jql = "assignee = currentUser() AND resolution IS EMPTY ORDER BY updated DESC"
            else:
            # JQL text search should search useful query terms, not the full
            # natural-language question as one exact phrase.
                stop_words = {"what", "is", "the", "and", "of", "for", "in", "on", "to", "jira", "issue", "status", "assignee", "which", "are", "currently", "me", "my", "tasks", "task", "assigned"}
                terms = [term for term in re.findall(r"[A-Za-z0-9_-]+", query) if term.casefold() not in stop_words]
                if not terms:
                    terms = re.findall(r"[A-Za-z0-9_-]+", query)
                jql_terms = " AND ".join(f'text ~ "{term.replace(chr(34), "")[:80]}"' for term in terms[:6])
                jql = f"{jql_terms} ORDER BY updated DESC"
        headers = {"Authorization": f"Bearer {oauth_access}"} if oauth_access else None
        auth = None if oauth_access else (cfg.jira_email, cfg.jira_token)
        with httpx.Client(timeout=15, auth=auth, headers=headers) as client:
            endpoint = f"{cloud_base}/rest/api/3/search/jql"
            data = client.post(endpoint,
                               json={"jql": jql, "maxResults": limit,
                                     "fields": ["summary", "description", "status", "assignee", "priority", "updated", "duedate", "resolution"]}).raise_for_status().json()
        records = []
        for issue in data.get("issues", []):
            fields = issue.get("fields", {})
            assignee = fields.get("assignee") or {}
            status = (fields.get("status") or {}).get("name", "")
            assignee_name = assignee.get("displayName") or "Unassigned"
            priority_data = fields.get("priority")
            priority = (priority_data or {}).get("name") or "Not set"
            due_date = fields.get("duedate") or ""
            resolution = (fields.get("resolution") or {}).get("name", "")
            description = _plain(fields.get("description")).strip()
            facts = [f"Status: {status}" if status else "",
                     f"Assignee: {assignee_name}" if assignee_name else "Unassigned",
                     f"Priority: {priority}"]
            content = ". ".join(fact for fact in [*facts, description] if fact)
            records.append(SourceRecord(id=f"jira:{issue['key']}", source="jira", title=fields.get("summary", ""),
                content=content,
                url=f"{web_base.rstrip('/')}/browse/{quote(issue['key'])}",
                author=assignee_name if assignee_name != "Unassigned" else None, createdAt=fields.get("updated"),
                metadata={key: value for key, value in {
                    "status": status, "assignee": assignee_name, "priority": priority,
                    "dueDate": due_date, "resolution": resolution, "description": description,
                }.items() if value}))
        return records

    def _notion(self, query: str, limit: int) -> list[SourceRecord]:
        token = access_token(OAuthStore(self.config.oauth_db_path), "notion",
                             self.config.notion_oauth_client_id, self.config.notion_oauth_client_secret)
        token = token or self.config.notion_token
        if not token:
            raise ValueError("Connect Notion at /api/oauth/notion/connect or configure NOTION_API_KEY")
        headers = {"Authorization": f"Bearer {token}", "Notion-Version": self.config.notion_version}
        with httpx.Client(timeout=15, headers=headers) as client:
            broad_query = bool(re.search(r"\b(latest|recent|newest|check)\b.*\b(updates?|activity|pages?|notion|notes?|meeting|documents?)|\bcheck notion\b", query.casefold()))
            def retrieve(search_query: str | None) -> list[SourceRecord]:
                payload: dict[str, Any] = {"page_size": min(max(limit, 1), 100)}
                if search_query:
                    payload["query"] = search_query
                search_data = client.post("https://api.notion.com/v1/search", json=payload).raise_for_status().json()
                records: list[SourceRecord] = []
                for page in search_data.get("results", []):
                    title = ""
                    for prop in page.get("properties", {}).values():
                        if prop.get("type") == "title":
                            title = _plain(prop.get("title")); break
                    page_id = page["id"]
                    blocks: list[dict[str, Any]] = []
                    cursor = None
                    while len(blocks) < 500:
                        params: dict[str, Any] = {"page_size": 100}
                        if cursor:
                            params["start_cursor"] = cursor
                        block_page = client.get(f"https://api.notion.com/v1/blocks/{page_id}/children",
                                                params=params).raise_for_status().json()
                        blocks.extend(block_page.get("results", []))
                        cursor = block_page.get("next_cursor")
                        if not block_page.get("has_more") or not cursor:
                            break
                    content = " ".join(_plain(block.get(block.get("type", ""), {}).get("rich_text", [])) for block in blocks)
                    records.append(SourceRecord(id=f"notion:{page_id}", source="notion", title=title or "Notion page",
                        content=content, url=page.get("url"), createdAt=page.get("last_edited_time"),
                        metadata={"object": page.get("object", "page")}))
                return records

            records = retrieve(None if broad_query else query.strip())
            relevant = [(record, _notion_relevance(query, record.title, record.content, broad=broad_query))
                        for record in records]
            relevant = [(record, score) for record, (matched, score) in relevant if matched]
            # Search again with the entity-only phrase when Notion returns pages
            # for the generic words but none for the requested project.
            compact = _compact_notion_query(query)
            if records and not relevant and compact and compact.casefold() != query.casefold():
                records = retrieve(compact)
                relevant = [(record, _notion_relevance(query, record.title, record.content, broad=broad_query))
                            for record in records]
                relevant = [(record, score) for record, (matched, score) in relevant if matched]
            relevant.sort(key=lambda item: (-item[1], item[0].title.casefold(), item[0].id))
            return [record for record, _ in relevant[:limit]]
