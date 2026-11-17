"""Deterministic source routing; the labels are safe to expose in traces."""

import re
from datetime import date, timedelta
from dataclasses import dataclass

from .models import SourceName


@dataclass(frozen=True)
class Route:
    sources: tuple[SourceName, ...]
    reason: str


_TERMS: dict[SourceName, tuple[str, ...]] = {
    "gmail": ("email", "emails", "mail", "inbox", "gmail", "unread", "sender", "sent", "received", "urgent", "important", "professor", "message"),
    "jira": ("jira", "ticket", "issue", "task", "tasks", "overdue", "unresolved", "priority", "blocked", "blocker", "status", "assignee", "assigned", "scrum-", "atl-", "sprint", "on my plate", "what should i work on", "next priority", "to-do"),
    "notion": ("notion", "notes", "meeting", "action item", "action items", "brief", "project documentation", "document", "documentation", "wiki", "roadmap", "launch readiness", "owner list"),
    "calendar": ("calendar", "meeting", "meetings", "event", "events", "appointment", "appointments"),
    "drive": ("google drive", "drive", "company", "company knowledge", "knowledge base", "employee", "employees", "staff", "customer", "customers", "account", "accounts", "client", "clients", "crm", "hr", "leave request", "leave requests", "leave balance", "annual leave", "sick leave", "time off", "personnel", "sales development representative", "sales representative", "sdr", "pan card", "pan number", "pan", "tax id", "gst", "leave policy", "support ticket", "support tickets", "atlas", "company profile", "employee directory"),
}
_CROSS_SOURCE = ("across all sources", "all sources", "all work apps", "each blocker", "related to my current jira", "compare my jira", "mentioning unresolved jira", "cross-platform")
_WORK_CONTEXT = (
    "gmail", "jira", "notion", "email", "emails", "mail", "inbox", "unread", "important", "urgent", "messages", "sender", "received", "my professor", "my emails", "email thread", "my inbox", "our inbox", "my team", "our team",
    "my project", "our project", "my work", "our work", "project", "workspace", "launch", "blocker",
    "blocked", "ticket", "issue", "task", "overdue", "unresolved", "sprint", "assignee", "owner", "roadmap", "handoff",
    "standup", "meeting", "meeting notes", "notes", "brief", "document", "documentation", "wiki", "action items", "release", "approval", "atl-", "scrum-", "project status", "assigned",
    "what needs attention", "what needs my attention", "what should i work on", "what's on my plate", "what is on my plate", "my next priority", "next priority", "latest updates",
    "company", "employee", "employees", "customer", "customers", "account", "accounts", "client", "clients", "crm", "hr", "leave request", "leave requests", "leave balance", "annual leave", "sick leave", "time off", "personnel", "sales development representative", "sales representative", "sdr", "pan card", "pan number", "pan", "tax id", "gst", "leave policy", "knowledge base", "google drive", "calendar", "meetings", "events",
)

_FOLLOW_UP_PREFIXES = (
    "and ", "what about", "how about", "who is", "who's", "who was", "who were", "why is", "why did",
    "what does that", "what do you mean", "what is it", "what's its", "how so",
    "tell me more", "explain more", "more details", "can you explain", "can you expand", "expand on that", "what next", "what's the latest", "what is the latest",
    "any updates", "any news", "anything new", "what else", "what changed", "what happened next", "and then",
)


def _contains_term(text: str, term: str) -> bool:
    if " " in term:
        return term in text
    return bool(re.search(rf"\b{re.escape(term)}\b", text))


def is_work_query(query: str) -> bool:
    """Only route questions needing connected workspace context to source retrieval."""
    if re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", query.upper()):
        return True
    text = re.sub(r"[^\w\s']", "", query.casefold())
    text = re.sub(r"\s+", " ", text).strip()
    if any(_contains_term(text, term) for term in _WORK_CONTEXT):
        return True
    # Specific factual questions about an entity usually need workspace evidence,
    # even when the entity type is phrased in a way we do not yet recognize.
    return bool(re.search(r"\b(fetch|find|look up|tell me about|what do we know about)\b.+\b(customer|account|client|company|vendor|employee|person|project|leave|hr)\b", text)
                or re.search(r"\b(?:leave request|time off|sick leave)\b.*\b(?:for|of|from)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?", query))


def is_follow_up(query: str) -> bool:
    """Recognize short references that need the immediately preceding turn."""
    text = re.sub(r"\s+", " ", query.casefold()).strip()
    if not text:
        return False
    if text in {"yes", "yes please", "sure", "okay", "ok", "please do", "do that", "go ahead"}:
        return True
    return len(text.split()) <= 14 and (
        any(text.startswith(prefix) for prefix in _FOLLOW_UP_PREFIXES)
        or bool(re.search(r"\b(it|its|that|those|they|them|this|there|one|first|second|same|other)\b", text))
        or bool(re.search(r"\b(the|that|this)\s+(?:sender|subject|status|owner|assignee|priority|deadline|task|ticket|email|message|note)\b", text))
        or bool(re.fullmatch(r"(?:why|when|where|who|which|how many|how much|what)\??", text))
    )


def route_query(query: str) -> Route:
    """Choose relevant sources in a stable order, always querying at least one."""
    text = query.casefold()
    if re.search(r"\bPX-(?:SUP|ATLAS)-\d+\b", query.upper()):
        return Route(("drive",), "drive_record_id")
    # Explicitly named sources must not be discarded just because the same
    # question also contains a Jira issue key. Preserve Jira for the key, then
    # search every other named source requested by the user.
    named = [source for source, patterns in {
        "gmail": (r"\bgmail\b", r"\bgoogle mail\b"),
        "jira": (r"\bjira\b",),
        "notion": (r"\bnotion\b",),
        "calendar": (r"\bcalendar\b",),
        "drive": (r"\bgoogle drive\b", r"\bdrive\b", r"\bcompany knowledge\b", r"\bknowledge base\b"),
    }.items() if any(re.search(pattern, text) for pattern in patterns)]
    has_jira_key = bool(re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", query.upper()))
    if named:
        if has_jira_key and "jira" not in named:
            named.append("jira")
        return Route(tuple(named[:3]), "explicit_sources")
    if re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", query.upper()):
        return Route(("jira",), "jira_issue_key")
    selected = [source for source, terms in _TERMS.items() if any(_contains_term(text, term) for term in terms)]
    if re.search(r"\bwhat needs (?:my )?attention\b", text):
        return Route(("gmail", "jira"), "attention_summary")
    if re.search(r"\b(?:email|emails|mail)\b.*\b(?:jira|task|tasks|issue|issues)\b|\b(?:jira|task|tasks|issue|issues)\b.*\b(?:email|emails|mail)\b", text):
        return Route(("jira", "gmail"), "jira_to_email_lookup")
    # If the user names applications, honor that explicit selection. Domain
    # words such as "status" should not silently add a third connector.
    if re.search(r"\b(?:related to|mention(?:ing)?|compare|across|with)\b", text) and len(selected) > 1:
        return Route(tuple(selected[:3]), "multi_source_intent")
    if any(term in text for term in _CROSS_SOURCE) or (
        any(term in text for term in ("what is blocking", "what's blocking", "who owns")) and
        any(term in text for term in ("each blocker", "blockers", "what is blocking", "what's blocking"))
    ):
        selected = ["gmail", "jira", "notion"]
    if not selected:
        selected = ["gmail", "jira", "notion"]
    return Route(tuple(selected[:3]), "keyword_match" if any(s in selected for s in _TERMS) else "general_query")


def retrieval_query(query: str, source: SourceName, planned_query: str | None = None) -> str:
    """Translate common Gmail intents to Gmail's query language; preserve provider queries."""
    normalized = re.sub(r"\s+", " ", query).strip()
    lower = normalized.casefold()
    # A source-specific plan carries the entity or identifier the planner chose
    # for this connector. Do not discard it because the full question happens
    # to contain a broad phrase such as "cross-check Jira".
    if source in {"jira", "notion", "drive", "calendar"} and planned_query:
        return planned_query
    if source == "jira" and re.search(r"\b(check|show|fetch|find)\b.*\b(jira|updates?|activity)\b|\b(jira|updates?|activity)\b.*\b(latest|recent|newest)\b", lower):
        return "latest Jira updates"
    if source == "jira" and any(term in lower for term in ("what should i work on", "on my plate", "what is on my plate", "assigned to me", "my tasks", "current tasks", "tasks do i have", "my tickets", "what should i focus on")):
        return "What tasks are currently assigned to me?"
    if source == "jira" and any(term in lower for term in ("next priority", "what needs attention", "what needs my attention")):
        return "Which high-priority tasks remain unresolved?"
    if source == "jira" and any(term in lower for term in ("my jira task", "current jira task", "emails related to", "email related to")):
        return "What tasks are currently assigned to me?"
    if source != "gmail":
        return normalized
    text = lower
    terms: list[str] = []
    if "unread" in text:
        terms.append("is:unread")
    if "important" in text or "urgent" in text or "attention" in text:
        terms.append("is:important")
    if "today" in text:
        today = date.today()
        terms.extend((f"after:{today:%Y/%m/%d}", f"before:{today + timedelta(days=1):%Y/%m/%d}"))
    elif any(word in text for word in ("recent", "latest", "newest", "summarize", "check gmail", "check my gmail")):
        terms.append("newer_than:30d")
    sender = re.search(r"\bfrom\s+(?:my\s+|the\s+|a\s+)?([\w.+-]+@[\w.-]+|[\w.'-]+(?:\s+[\w.'-]+){0,2})", normalized, re.I)
    if sender:
        terms.append(f"from:{sender.group(1).strip().strip('.,?!')}")
    if "sent me" in text or "who sent" in text or "received" in text:
        terms.append("-in:sent")
    if re.search(r"\bhow many\b|\bcount\b|\bnumber of\b", text):
        terms.append("__parallax_count__")
    # Keep provider-ready rewrites for Gmail, retaining explicit count and filters.
    if planned_query:
        for term in planned_query.split():
            if term not in terms:
                terms.append(term)
    # Keep meaningful free-text terms for Gmail full-text search.
    if not terms:
        ignored = {"show", "find", "email", "emails", "mail", "message", "messages", "latest", "recent", "me", "my", "the", "from", "sent", "who", "what", "are", "is", "have", "today", "summarize", "please"}
        words = [word.strip(".,?!:;") for word in normalized.split() if word.casefold().strip(".,?!:;") not in ignored]
        terms.extend(words[:8])
    return " ".join(terms) or "newer_than:30d"
