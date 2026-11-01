from app.agent.citations import validate_citations
from app.agent.models import Citation, SourceRecord
from app.agent.routing import route_query


def record(**overrides):
    values = dict(id="jira:ATL-42", source="jira", title="API rate limits", content="Blocked by API rate limits.",
                  url="https://example.test/ATL-42", metadata={})
    values.update(overrides)
    return SourceRecord(**values)


def test_routes_source_specific_question_to_jira():
    assert route_query("What is the status of Jira ticket ATL-42?").sources == ("jira",)


def test_routes_cross_source_launch_question_to_all_sources_in_stable_order():
    assert route_query("What is blocking the Atlas launch and who owns each blocker?").sources == (
        "gmail", "jira", "notion")


def test_routes_general_question_to_all_sources():
    assert route_query("Summarize the work situation").sources == ("gmail", "jira", "notion")


def test_accepts_citation_matching_retrieved_record():
    source = record()
    citation = Citation(number=1, recordId=source.id, title=source.title, source=source.source, url=source.url)
    assert validate_citations([citation], [source]) == [citation]


def test_rejects_citation_to_missing_record():
    citation = Citation(number=1, recordId="notion:fake", title="Fake", source="notion")
    try:
        validate_citations([citation], [record()])
    except ValueError as exc:
        assert "unavailable record" in str(exc)
    else:
        raise AssertionError("fabricated citation should be rejected")


def test_rejects_mismatched_citation_metadata():
    source = record()
    citation = Citation(number=1, recordId=source.id, title="Made up title", source=source.source, url=source.url)
    try:
        validate_citations([citation], [source])
    except ValueError as exc:
        assert "metadata" in str(exc)
    else:
        raise AssertionError("mismatched citation should be rejected")
