from app.agent.citations import validate_citations
from app.agent.models import Citation, SourceRecord
from app.agent.routing import route_query, is_work_query, is_follow_up


def record(**overrides):
    values = dict(id="jira:ATL-42", source="jira", title="API rate limits", content="Blocked by API rate limits.",
                  url="https://example.test/ATL-42", metadata={})
    values.update(overrides)
    return SourceRecord(**values)


def test_routes_source_specific_question_to_jira():
    assert route_query("What is the status of Jira ticket ATL-42?").sources == ("jira",)
    assert route_query("Who is SCRUM-2 assigned to?").sources == ("jira",)
    assert is_work_query("Who is SCRUM-2 assigned to?")


def test_routes_cross_source_launch_question_to_all_sources_in_stable_order():
    assert route_query("What is blocking the Atlas launch and who owns each blocker?").sources == (
        "gmail", "jira", "notion")


def test_routes_general_question_to_all_sources():
    assert route_query("Summarize the work situation").sources == ("gmail", "jira", "notion")


def test_general_talk_does_not_trigger_work_source_retrieval():
    assert not is_work_query("Hi, how are you?")
    assert not is_work_query("Explain how photosynthesis works")
    assert is_work_query("Hi, what is blocking the Atlas launch?")
    assert is_work_query("What is the status of Jira ticket ATL-42?")
    assert is_work_query("How many unread emails do I have?")
    assert is_work_query("Which issues are overdue?")
    assert is_work_query("Summarize my latest meeting notes.")


def test_live_retrieval_queries_are_specialized_for_connected_sources():
    from app.agent.routing import retrieval_query

    assert retrieval_query("How many unread emails do I have?", "gmail") == "is:unread __parallax_count__"
    assert retrieval_query("Find emails from my professor.", "gmail") == "from:professor"
    assert "-in:sent" in retrieval_query("Who sent me an email today?", "gmail")
    assert retrieval_query("Which issues are overdue?", "jira") == "Which issues are overdue?"
    assert retrieval_query("check jira", "jira") == "latest Jira updates"
    assert retrieval_query("check jira for latest updates", "jira") == "latest Jira updates"
    assert route_query("check jira").sources == ("jira",)


def test_short_referential_questions_are_detected_as_follow_ups():
    assert is_follow_up("What is its priority?")
    assert is_follow_up("Who is that assigned to?")
    assert is_follow_up("yes please")
    assert not is_follow_up("How do I bake sourdough bread?")


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


def test_gmail_sender_answers_use_sender_and_subject_fields():
    from app.agent.synthesis import synthesize

    message = record(id="gmail:m1", source="gmail", title="Launch checklist approval",
                     content="Please review the security checklist.", author="Maya Chen",
                     createdAt="2026-11-02T08:30:00Z")
    answer, citations = synthesize("Who sent me an email today?", [message])

    assert "Maya Chen" in answer
    assert "Launch checklist approval" in answer
    assert citations[0].recordId == "gmail:m1"


def test_rejects_mismatched_citation_metadata():
    source = record()
    citation = Citation(number=1, recordId=source.id, title="Made up title", source=source.source, url=source.url)
    try:
        validate_citations([citation], [source])
    except ValueError as exc:
        assert "metadata" in str(exc)
    else:
        raise AssertionError("mismatched citation should be rejected")
