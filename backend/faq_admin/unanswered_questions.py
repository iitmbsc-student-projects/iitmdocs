"""Turn one chatbot log record into a safe unanswered-question candidate.

Flow: the Test BigQuery reader gives this module one structured conversation
log -> ``build_candidate_from_log`` excludes safety and technical events -> it
returns only the fields the FAQ-admin table needs. For example, a completed DS
fact-check rejection becomes a DS candidate; a prompt injection returns
``None``.
"""
import json

from programs import REAL_PROGRAM_IDS


class UnansweredQuestionError(ValueError):
    """Raised when an admin action cannot safely change a review row."""


def _text_or_none(value):
    """Return trimmed text, or ``None`` for missing/blank log values."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _fact_check_rejection_reason(fact_checks):
    """Join the fact checker's concrete objections for the admin.

    Example: ``[{"incorrect": ["Unsupported."]}]`` becomes
    ``"Unsupported."``. Malformed historical log entries are ignored.
    """
    if not isinstance(fact_checks, list):
        return None

    reasons = []
    for check in fact_checks:
        if not isinstance(check, dict):
            continue
        incorrect = check.get("incorrect")
        if not isinstance(incorrect, list):
            continue
        for item in incorrect:
            text = _text_or_none(item)
            if text:
                reasons.append(text)
    return "; ".join(reasons) or None


def build_candidate_from_log(log):
    """Return one eligible Test-log candidate, or ``None`` when it is excluded.

    A candidate must be a completed normal bot turn that failed fact checking.
    Prompt injection, Raahat, direct-FAQ, no-search-result, failed/disconnected,
    malformed, and technical-error logs are excluded.
    """
    if not isinstance(log, dict):
        return None

    program_id = log.get("program_id")
    question = _text_or_none(log.get("question"))
    if program_id not in REAL_PROGRAM_IDS or question is None:
        return None
    if log.get("stream_status") != "completed":
        return None
    if log.get("query_source") in ("rejected", "faq_direct_id"):
        return None
    if log.get("contains_raahat") is True:
        return None
    if _text_or_none(log.get("error")):
        return None

    rejection_reason = _text_or_none(log.get("rejection_reason"))
    fact_check_passed = log.get("fact_check_passed")
    is_fact_check_failure = fact_check_passed is False
    if not is_fact_check_failure:
        return None

    return {
        "program_id": program_id,
        "original_question": question,
        "rewritten_question": _text_or_none(log.get("rewritten_query")),
        "rejection_reason": rejection_reason,
        "original_answer": _text_or_none(log.get("original_answer")),
        "asked_at": log.get("asked_at"),
        "fact_check_passed": fact_check_passed if isinstance(fact_check_passed, bool) else None,
        "fact_check_rejection_reason": _fact_check_rejection_reason(log.get("fact_checks")),
    }


def build_candidates_from_logs(logs):
    """Return one candidate per exact programme/question pair from log records.

    Example: two identical AE logs become one candidate. The first iteration
    intentionally does not record occurrence counts or update a previous row.
    """
    if not isinstance(logs, list):
        return []

    candidates = []
    seen = set()
    for log in logs:
        candidate = build_candidate_from_log(log)
        if candidate is None:
            continue
        key = (candidate["program_id"], candidate["original_question"])
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    return candidates


def _row_as_dict(row):
    """Convert one ORM review row into plain template/API data."""
    return {
        "id": int(row.id),
        "program_id": row.program_id,
        "original_question": row.original_question,
        "rewritten_question": row.rewritten_question,
        "rejection_reason": row.rejection_reason,
        "original_answer": row.original_answer,
        "asked_at": row.asked_at,
        "fact_check_passed": row.fact_check_passed,
        "fact_check_rejection_reason": row.fact_check_rejection_reason,
        "accepted_or_rejected_by_admin": row.accepted_or_rejected_by_admin,
        "ai_suggestion": row.ai_suggestion,
        "ai_reason": getattr(row, "ai_reason", None),
        "matching_faq_ids": json.loads(getattr(row, "matching_faq_ids", None) or "[]"),
        "suggested_clean_question": getattr(row, "suggested_clean_question", None),
    }


def _get_row_for_admin_action(session, question_id):
    """Return the selected row or explain why the requested action is invalid."""
    from pg.faq_api.orm import UnansweredQuestion

    if not isinstance(question_id, int) or question_id < 1:
        raise UnansweredQuestionError("Choose a valid unanswered question")
    row = session.get(UnansweredQuestion, question_id)
    if row is None:
        raise UnansweredQuestionError("The unanswered question no longer exists")
    return row


def _list_unanswered_questions(admin_decision=None):
    """Return review rows, optionally limited to one admin decision.

    Example: ``_list_unanswered_questions("accepted")`` powers the review
    page, while no decision returns both accepted and rejected audit rows.
    """
    from sqlalchemy import select

    from pg.faq_api.orm import (
        UnansweredQuestion,
        create_pg_engine,
        create_session_factory,
        session_scope,
    )

    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            statement = select(UnansweredQuestion).order_by(UnansweredQuestion.id)
            if admin_decision is not None:
                statement = statement.where(
                    UnansweredQuestion.accepted_or_rejected_by_admin == admin_decision
                )
            rows = session.execute(statement).scalars().all()
            return [_row_as_dict(row) for row in rows]
    finally:
        engine.dispose()


def list_accepted_unanswered_questions():
    """Return pending rows for the action-focused admin review page.

    Example: an accepted DS row is returned, while a rejected row remains
    stored but is intentionally not shown again on that page.
    """
    return _list_unanswered_questions("accepted")


def list_all_unanswered_questions():
    """Return every row for the read-only unanswered-question audit page.

    Example: a rejected AE row remains visible here so an admin can verify
    that the Reject action saved its decision.
    """
    return _list_unanswered_questions()


def reject_unanswered_question(question_id):
    """Mark one accepted review row as rejected and return its new state.

    Example: ``reject_unanswered_question(7)`` changes row 7 to ``rejected``.
    The first version has no restore action, so later imports leave it hidden.
    """
    return _finish_unanswered_question(question_id, "rejected")


def complete_unanswered_question(question_id):
    """Mark one accepted review row as completed after the admin handles it.

    Example: ``complete_unanswered_question(7)`` changes row 7 to
    ``completed``. It records review completion only; it does not add an FAQ.
    """
    return _finish_unanswered_question(question_id, "completed")


def _finish_unanswered_question(question_id, decision):
    """Store a final admin decision only for a pending accepted row.

    Example: ``_finish_unanswered_question(7, "rejected")`` keeps an already
    rejected or completed row unchanged by refusing the repeated action.
    """
    from pg.faq_api.orm import create_pg_engine, create_session_factory, session_scope

    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            row = _get_row_for_admin_action(session, question_id)
            if row.accepted_or_rejected_by_admin != "accepted":
                raise UnansweredQuestionError("This question is no longer pending review")
            row.accepted_or_rejected_by_admin = decision
            session.flush()
            return _row_as_dict(row)
    finally:
        engine.dispose()


def save_new_candidates(candidates):
    """Insert unseen candidates and preserve every existing admin decision.

    Example: when DS already has ``"Fees?"``, importing it again returns zero
    new rows. A separate AE ``"Fees?"`` candidate is allowed.
    """
    from sqlalchemy import select

    from pg.faq_api.orm import (
        UnansweredQuestion,
        create_pg_engine,
        create_session_factory,
        session_scope,
    )

    if not isinstance(candidates, list):
        return 0

    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            inserted = 0
            for candidate in candidates:
                existing_id = session.scalar(
                    select(UnansweredQuestion.id).where(
                        UnansweredQuestion.program_id == candidate["program_id"],
                        UnansweredQuestion.original_question == candidate["original_question"],
                    )
                )
                if existing_id is not None:
                    continue
                session.add(UnansweredQuestion(**candidate))
                inserted += 1
            return inserted
    finally:
        engine.dispose()


def refresh_unanswered_questions():
    """Read Test logs, filter candidates, save new rows, and report the counts.

    Example: two logs containing one prompt injection and one retrieval miss
    report two logs, one candidate, and one inserted row. This runs only after
    the admin explicitly clicks Refresh.
    """
    from .log_import import read_last_seven_days_test_logs

    logs = read_last_seven_days_test_logs()
    candidates = build_candidates_from_logs(logs)
    inserted = save_new_candidates(candidates)
    return {
        "log_count": len(logs),
        "candidate_count": len(candidates),
        "inserted_count": inserted,
    }
