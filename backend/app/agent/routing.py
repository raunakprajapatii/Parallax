"""Deterministic source routing; the labels are safe to expose in traces."""

import re
from dataclasses import dataclass

from .models import SourceName


@dataclass(frozen=True)
class Route:
    sources: tuple[SourceName, ...]
    reason: str


_TERMS: dict[SourceName, tuple[str, ...]] = {
    "gmail": ("email", "mail", "gmail", "approval", "thread", "sent", "design handoff"),
    "jira": ("jira", "ticket", "issue", "blocked", "blocker", "status", "assignee", "assigned", "atl-", "sprint"),
    "notion": ("notion", "brief", "launch date", "owner list", "document", "wiki", "roadmap"),
}
_CROSS_SOURCE = ("across", "all sources", "each blocker", "who owns", "what is blocking", "what's blocking", "launch")
_WORK_CONTEXT = (
    "gmail", "jira", "notion", "email thread", "my inbox", "our inbox", "my team", "our team",
    "my project", "our project", "my work", "our work", "workspace", "launch", "blocker",
    "blocked", "ticket", "issue", "sprint", "assignee", "owner", "roadmap", "handoff",
    "standup", "meeting notes", "release", "approval", "atl-", "project status", "assigned",
)

_FOLLOW_UP_PREFIXES = (
    "and ", "what about", "how about", "who is", "who's", "why is", "why did",
    "what does that", "what do you mean", "what is it", "what's its", "how so",
    "tell me more", "explain more", "more details", "can you explain", "what next",
)


def is_work_query(query: str) -> bool:
    """Only route questions needing connected workspace context to source retrieval."""
    if re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", query.upper()):
        return True
    text = re.sub(r"[^\w\s']", "", query.casefold())
    text = re.sub(r"\s+", " ", text).strip()
    return any(term in text for term in _WORK_CONTEXT)


def is_follow_up(query: str) -> bool:
    """Recognize short references that need the immediately preceding turn."""
    text = re.sub(r"\s+", " ", query.casefold()).strip()
    if not text:
        return False
    if text in {"yes", "yes please", "sure", "okay", "ok", "please do", "do that", "go ahead"}:
        return True
    return len(text.split()) <= 14 and (
        any(text.startswith(prefix) for prefix in _FOLLOW_UP_PREFIXES)
        or bool(re.search(r"\b(it|its|that|those|they|them|this|there)\b", text))
    )


def route_query(query: str) -> Route:
    """Choose relevant sources in a stable order, always querying at least one."""
    text = query.casefold()
    if re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", query.upper()):
        return Route(("jira",), "jira_issue_key")
    selected = [source for source, terms in _TERMS.items() if any(term in text for term in terms)]
    if any(term in text for term in _CROSS_SOURCE):
        selected = ["gmail", "jira", "notion"]
    if not selected:
        selected = ["gmail", "jira", "notion"]
    return Route(tuple(selected[:3]), "keyword_match" if any(s in selected for s in _TERMS) else "general_query")


def retrieval_query(query: str, source: SourceName) -> str:
    """Keep the user's intent intact while enabling adapters to specialize if needed."""
    return re.sub(r"\s+", " ", query).strip()
