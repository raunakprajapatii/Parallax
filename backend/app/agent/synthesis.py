"""Evidence-only deterministic extractive synthesis."""

import re

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


def synthesize(query: str, records: list[SourceRecord], max_records: int = 5) -> tuple[str, list[Citation]]:
    """Return brief factual excerpts with one grounded citation per sentence."""
    ranked = rank_records(query, records, max_records)
    usable: list[tuple[SourceRecord, str]] = []
    for record in ranked:
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
    return answer, citations
