"""Citation validation against the records actually returned in this run."""

from .models import Citation, SourceRecord


def validate_citations(citations: list[Citation], records: list[SourceRecord]) -> list[Citation]:
    """Reject fabricated, mismatched, duplicate, or unused citation references."""
    by_id = {record.id: record for record in records}
    seen_numbers: set[int] = set()
    seen_records: set[str] = set()
    valid: list[Citation] = []
    for citation in citations:
        record = by_id.get(citation.recordId)
        if record is None:
            raise ValueError(f"Citation references unavailable record: {citation.recordId}")
        if citation.number < 1 or citation.number in seen_numbers:
            raise ValueError(f"Invalid or duplicate citation number: {citation.number}")
        if citation.recordId in seen_records:
            raise ValueError(f"Duplicate citation record: {citation.recordId}")
        if (citation.title, citation.source, citation.url) != (record.title, record.source, record.url):
            raise ValueError(f"Citation metadata does not match record: {citation.recordId}")
        seen_numbers.add(citation.number)
        seen_records.add(citation.recordId)
        valid.append(citation)
    return valid
