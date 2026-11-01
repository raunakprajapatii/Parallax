"""Evidence-only deterministic extractive synthesis."""

import re
import httpx

from .models import Citation, SourceRecord

INSUFFICIENT_ANSWER = "I don’t have enough evidence in the connected sources to answer that."
_WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)


def _terms(text: str) -> set[str]:
    return {word.casefold() for word in _WORD_RE.findall(text) if len(word) > 2}


def rank_records(query: str, records: list[SourceRecord], limit: int = 5) -> list[SourceRecord]:
    """Rank by query-term overlap, breaking ties by connector order and stable ID."""
    wanted = _terms(query)
    indexed = list(enumerate(records))
    indexed.sort(key=lambda pair: (-len(wanted & _terms(pair[1].title + " " + pair[1].content)), pair[0], pair[1].id))
    return [record for _, record in indexed[:limit]]


def _asks_description(query: str) -> bool:
    text = query.casefold()
    return any(term in text for term in ("description", "describe", "details")) or bool(
        re.search(r"\b(?:issue|ticket|task)\s+about\b", text)
    )


def _append_follow_up(answer: str, records: list[SourceRecord], query: str = "") -> str:
    if not answer or answer == INSUFFICIENT_ANSWER or "?" in answer:
        return answer
    sources = {record.source for record in records}
    if len(sources) > 1:
        question = "Would you like me to check a related item in another connected source?"
    elif "jira" in sources:
        if _asks_description(query):
            question = "Would you like me to check this issue's status or assignee?"
        else:
            question = "Would you like me to check another Jira issue or summarize this issue's description?"
    elif "gmail" in sources:
        question = "Would you like me to look for a related email?"
    elif "notion" in sources:
        question = "Would you like me to find a related Notion page?"
    else:
        question = "What would you like me to look up next?"
    return f"{answer.rstrip()}\n\n{question}"


def _jira_issue_answer(query: str, record: SourceRecord) -> str:
    requested = query.casefold()
    issue_key = record.id.partition(":")[2]
    if _asks_description(query):
        description = re.sub(r"\n{3,}", "\n\n", record.metadata.get("description", "")).strip()
        title = f" ({record.title})" if record.title else ""
        if not description:
            return f"{issue_key}{title} has no description in Jira."
        if len(description) > 1200:
            description = description[:1197].rsplit(" ", 1)[0].rstrip() + "…"
        return f"{issue_key}{title} description:\n\n{description}"

    status = record.metadata.get("status", "")
    assignee = record.metadata.get("assignee", "")
    priority = record.metadata.get("priority", "")
    want_status = "status" in requested
    want_assignee = any(term in requested for term in ("assignee", "assigned", "owner"))
    want_priority = "priority" in requested
    if not any((want_status, want_assignee, want_priority)):
        want_status = want_assignee = want_priority = True

    sentence = issue_key
    if want_status and status:
        sentence += f" is currently {status}"
    if want_assignee and assignee:
        if want_status and status:
            sentence += f" and assigned to {assignee}"
        else:
            sentence += f" is assigned to {assignee}"
    if want_priority and priority:
        if priority.casefold() == "not set":
            sentence += "; its priority is not set"
        else:
            sentence += f"; its priority is {priority}"
    return sentence + "."


def synthesize(query: str, records: list[SourceRecord], max_records: int = 5) -> tuple[str, list[Citation]]:
    """Return brief factual excerpts with one grounded citation per sentence."""
    ranked = rank_records(query, records, max_records)
    usable: list[tuple[SourceRecord, str]] = []
    issue_keys = set(re.findall(r"\b[A-Z][A-Z0-9]+-\d+\b", query.upper()))
    for record in ranked:
        record_key = record.id.partition(":")[2].upper()
        if record.source == "jira" and issue_keys and record_key in issue_keys:
            usable.append((record, _jira_issue_answer(query, record)))
            continue
        if record.source == "jira" and record.metadata:
            ask = query.casefold()
            selected_facts = []
            if "status" in ask and record.metadata.get("status"):
                selected_facts.append(f"is currently {record.metadata['status']}")
            if any(term in ask for term in ("assignee", "assigned", "owner")) and record.metadata.get("assignee"):
                selected_facts.append(f"is assigned to {record.metadata['assignee']}")
            if "priority" in ask and record.metadata.get("priority"):
                priority = record.metadata["priority"]
                selected_facts.append("has no priority set" if priority.casefold() == "not set"
                                      else f"has {priority} priority")
            if selected_facts:
                key = record.id.partition(":")[2]
                title = f" ({record.title})" if record.title else ""
                usable.append((record, f"{key}{title} " + "; it ".join(selected_facts) + "."))
                continue
        content = re.sub(r"\s+", " ", record.content).strip()
        if content:
            # Keep a complete excerpt; never add claims, owners, dates, or conclusions.
            excerpt = content[:600].rstrip()
            if len(content) > 600:
                excerpt = excerpt.rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
            usable.append((record, excerpt))
    if not usable:
        return INSUFFICIENT_ANSWER, []
    citations = [Citation(number=i, recordId=record.id, title=record.title, source=record.source, url=record.url)
                 for i, (record, _) in enumerate(usable, start=1)]
    answer = "\n".join(f"{excerpt} [{i}]" for i, (_, excerpt) in enumerate(usable, start=1))
    answer = _append_follow_up(answer, [record for record, _ in usable], query)
    return answer, citations


def synthesize_with_groq(query: str, records: list[SourceRecord], api_key: str,
                         model: str = "llama-3.3-70b-versatile",
                         history: list[dict[str, str]] | None = None) -> tuple[str, list[Citation]]:
    """Ask Groq to write a concise answer, mapping citations only to supplied records."""
    ranked = rank_records(query, records, 10)
    if not ranked:
        return INSUFFICIENT_ANSWER, []
    if re.search(r"\b[A-Z][A-Z0-9]+-\d+\b", query.upper()) and any(record.source == "jira" for record in ranked):
        # Exact Jira-key lookups are answered directly from Jira fields. This
        # prevents the language model from inventing issue owners or statuses.
        return synthesize(query, ranked)
    evidence_parts = []
    for i, record in enumerate(ranked, 1):
        metadata = "; ".join(f"{key}: {value}" for key, value in record.metadata.items() if value)
        details = f"\nKey fields: {metadata}" if metadata else ""
        evidence_parts.append(f"[{i}] id={record.id} source={record.source} title={record.title}{details}\n{record.content[:1800]}")
    evidence = "\n\n".join(evidence_parts)
    messages = [{"role": "system", "content": (
        "You are Parallax, a friendly work assistant. Answer the user's latest question directly and naturally in plain language. "
        "Use prior conversation only to understand references and follow-ups; use the current retrieved evidence for factual claims. "
        "Do not copy raw notes or irrelevant source text. Be concise, explain the answer in your own words, and cite each factual claim "
        "with the matching evidence number, such as [1]. If the evidence does not answer the question, say so plainly. "
        "When it would help the conversation, end with one brief, specific follow-up question about another read-only lookup or detail "
        "available in the connected sources. Never offer to edit, send, or create anything. Avoid generic filler. "
        "Never invent facts or citations."
    )}]
    for turn in (history or [])[-8:]:
        if turn.get("role") in {"user", "assistant"} and turn.get("content"):
            messages.append({"role": turn["role"], "content": turn["content"][:1200]})
    messages.append({"role": "user", "content": f"Latest question: {query}\n\nRetrieved evidence:\n{evidence}"})
    try:
        response = httpx.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"}, timeout=25,
            json={"model": model, "temperature": 0.2, "reasoning_effort": "low",
                  "include_reasoning": False, "max_completion_tokens": 700,
                  "messages": messages})
        response.raise_for_status()
        answer = response.json()["choices"][0]["message"]["content"].strip()
        marker = re.compile(r"\[(\d+)\]|【(\d+)】")
        used = sorted({int(match.group(1) or match.group(2)) for match in marker.finditer(answer)
                       if 1 <= int(match.group(1) or match.group(2)) <= len(ranked)})
        if not answer or not used:
            return synthesize(query, records)
        # Strip invalid citation markers and build only citations tied to evidence.
        answer = marker.sub(lambda match: f"[{match.group(1) or match.group(2)}]"
                            if int(match.group(1) or match.group(2)) in used else "", answer)
        citations = [Citation(number=i, recordId=ranked[n-1].id, title=ranked[n-1].title,
                              source=ranked[n-1].source, url=ranked[n-1].url)
                     for i, n in enumerate(used, 1)]
        for new, old in enumerate(used, 1):
            answer = answer.replace(f"[{old}]", f"[{new}]")
        answer = re.sub(r"(?<!\s)(\[\d+\])", r" \1", answer)
        answer = _append_follow_up(answer, ranked, query)
        return answer, citations
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return synthesize(query, records)


def answer_general_with_groq(message: str, api_key: str | None,
                             model: str = "llama-3.3-70b-versatile",
                             history: list[dict[str, str]] | None = None) -> str:
    """Answer general conversation with Groq, without retrieving work content."""
    if not api_key:
        return "Groq is not configured. Add GROQ_API_KEY to enable conversational replies."
    try:
        response = httpx.post("https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"}, timeout=20,
            json={"model": model, "temperature": 0.6, "reasoning_effort": "low",
                  "include_reasoning": False, "max_completion_tokens": 300,
                  "messages": [
                      {"role": "system", "content": "You are Parallax, a friendly and helpful conversational assistant. Reply naturally, remember the recent conversation provided here, and handle follow-up questions in context. Answer general questions concisely. Do not claim feelings or personal experiences. You do not have access to private work data unless current retrieved evidence is supplied."},
                      *[{"role": turn["role"], "content": turn["content"][:1200]}
                        for turn in (history or [])[-8:]
                        if turn.get("role") in {"user", "assistant"} and turn.get("content")],
                      {"role": "user", "content": message},
                  ]})
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return "I couldn’t reach Groq just now. Please try again in a moment."
