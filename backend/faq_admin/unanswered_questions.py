"""Turn one chatbot log record into a safe unanswered-question candidate.

Flow: the Test BigQuery reader gives this module one structured conversation
log -> ``build_candidate_from_log`` excludes safety and technical events -> it
returns only the fields the FAQ-admin table needs. For example, a completed DS
fact-check rejection becomes a DS candidate; a prompt injection returns
``None``.
"""
import random

from programs import REAL_PROGRAM_IDS


AI_SUGGESTIONS = (
    "should_be_added",
    "should_not_be_added",
    "answer_already_present",
)


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

    A candidate must be a completed normal bot turn that either found no search
    results or failed fact checking. Prompt injection, Raahat, direct-FAQ,
    failed/disconnected, malformed, and technical-error logs are excluded.
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
    is_no_search_result = rejection_reason == "no_search_results"
    is_fact_check_failure = fact_check_passed is False
    if not is_no_search_result and not is_fact_check_failure:
        return None

    return {
        "program_id": program_id,
        "original_question": question,
        "rewritten_question": _text_or_none(log.get("rewritten_query")),
        "rejection_reason": rejection_reason,
        "original_answer": _text_or_none(log.get("original_answer")),
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
        "fact_check_passed": row.fact_check_passed,
        "fact_check_rejection_reason": row.fact_check_rejection_reason,
        "accepted_or_rejected_by_admin": row.accepted_or_rejected_by_admin,
        "ai_suggestion": row.ai_suggestion,
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


def list_accepted_unanswered_questions():
    """Return the pending admin-review rows in primary-key order.

    Example: an accepted DS row is returned for the review page, while a
    rejected row remains stored but is intentionally not shown again.
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
            rows = session.execute(
                select(UnansweredQuestion)
                .where(UnansweredQuestion.accepted_or_rejected_by_admin == "accepted")
                .order_by(UnansweredQuestion.id)
            ).scalars().all()
            return [_row_as_dict(row) for row in rows]
    finally:
        engine.dispose()


def reject_unanswered_question(question_id):
    """Mark one accepted review row as rejected and return its new state.

    Example: ``reject_unanswered_question(7)`` changes row 7 to ``rejected``.
    The first version has no restore action, so later imports leave it hidden.
    """
    from pg.faq_api.orm import create_pg_engine, create_session_factory, session_scope

    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            row = _get_row_for_admin_action(session, question_id)
            row.accepted_or_rejected_by_admin = "rejected"
            session.flush()
            return _row_as_dict(row)
    finally:
        engine.dispose()


def save_temporary_ai_suggestion(question_id):
    """Save one random temporary AI label, without rerunning a saved result.

    Example: calling this for a new row may save ``should_be_added``. This is
    intentionally a test stub and does not inspect FAQ content or invent IDs.
    """
    from pg.faq_api.orm import create_pg_engine, create_session_factory, session_scope

    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            row = _get_row_for_admin_action(session, question_id)
            if row.accepted_or_rejected_by_admin != "accepted":
                raise UnansweredQuestionError("Rejected questions cannot receive AI help")
            if row.ai_suggestion is None:
                row.ai_suggestion = random.choice(AI_SUGGESTIONS)
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
