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


def test_routes_sales_development_representative_question_to_drive():
    question = "Who is the sales development representative?"
    assert is_work_query(question)
    assert route_query(question).sources == ("drive",)


def test_routes_customer_account_lookup_to_drive():
    question = "Fetch details about our customer Blue Group"
    assert is_work_query(question)
    assert route_query(question).sources == ("drive",)


def test_routes_anonymous_specific_workspace_facts_to_retrieval_fallback():
    assert is_work_query("Look up the vendor profile for Northstar")


def test_routes_employee_leave_request_to_drive():
    question = "Can you tell me about Vishal Chopra's leave request?"
    assert is_work_query(question)
    assert route_query(question).sources == ("drive",)


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


def test_explicit_sources_are_kept_alongside_a_jira_key():
    from app.agent.routing import retrieval_query

    question = "Compare Google Drive, Jira PAR-8, and Notion for Northstar Labs"
    assert route_query(question).sources == ("jira", "notion", "drive")
    assert retrieval_query(question, "jira", "PAR-8 owner and status") == "PAR-8 owner and status"


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


def test_multi_source_fallback_groups_evidence_by_platform_with_citations():
    from app.agent.synthesis import synthesize

    records = [
        record(id="jira:ATL-42", source="jira", title="API limit blocker", content="Status: Blocked."),
        record(id="gmail:m2", source="gmail", title="API review email", content="Review is scheduled Friday."),
    ]
    answer, citations = synthesize("Compare the Jira blocker with the related email", records)

    assert "**Jira**" in answer and "**Gmail**" in answer
    assert {citation.source for citation in citations} == {"jira", "gmail"}


def test_rank_records_keeps_one_relevant_record_per_source():
    from app.agent.synthesis import rank_records

    records = [
        record(id="drive:1", source="drive", title="Northstar rollout brief", content="Retention approval is pending."),
        record(id="drive:2", source="drive", title="Northstar actions", content="Riley owns the schedule."),
        record(id="jira:PAR-8", source="jira", title="Northstar approval blocker", content="Status: To Do."),
        record(id="notion:n1", source="notion", title="Northstar Labs Analytics Rollout", content=""),
    ]

    ranked = rank_records("Compare Northstar rollout approval across Drive, Jira, and Notion", records, limit=3)

    assert {item.source for item in ranked} == {"drive", "jira", "notion"}


def test_rejects_mismatched_citation_metadata():
    source = record()
    citation = Citation(number=1, recordId=source.id, title="Made up title", source=source.source, url=source.url)
    try:
        validate_citations([citation], [source])
    except ValueError as exc:
        assert "metadata" in str(exc)
    else:
        raise AssertionError("mismatched citation should be rejected")
