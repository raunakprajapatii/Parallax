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
    "jira": ("jira", "ticket", "issue", "blocked", "blocker", "status", "assignee", "atl-", "sprint"),
    "notion": ("notion", "brief", "launch date", "owner list", "document", "wiki", "roadmap"),
}
_CROSS_SOURCE = ("across", "all sources", "each blocker", "who owns", "what is blocking", "what's blocking", "launch")


def route_query(query: str) -> Route:
    """Choose relevant sources in a stable order, always querying at least one."""
    text = query.casefold()
    selected = [source for source, terms in _TERMS.items() if any(term in text for term in terms)]
    if any(term in text for term in _CROSS_SOURCE):
        selected = ["gmail", "jira", "notion"]
    if not selected:
        selected = ["gmail", "jira", "notion"]
    return Route(tuple(selected[:3]), "keyword_match" if any(s in selected for s in _TERMS) else "general_query")


def retrieval_query(query: str, source: SourceName) -> str:
    """Keep the user's intent intact while enabling adapters to specialize if needed."""
    return re.sub(r"\s+", " ", query).strip()
