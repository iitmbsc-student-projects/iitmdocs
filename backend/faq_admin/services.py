"""FAQ-admin data rules shared by the review and save views.

Flow: browser form data -> ``build_new_faq_rows`` -> validated Postgres row
shapes -> a later database function creates embeddings and writes them.

An FAQ category describes how many stored FAQ rows one admin-facing FAQ needs:
common/timeline FAQs use one shared ``common`` row, a programme-specific FAQ
uses one row, and a different-answer FAQ uses four programme rows.
"""
from programs import REAL_PROGRAM_IDS, validate_program_id
from pg.faq_api.orm import FAQ_QUESTION_CATEGORIES
from sqlalchemy import select


class FaqAdminValidationError(ValueError):
    """Raised when an admin form cannot safely become FAQ database rows."""


def _required_text(data, key):
    """Return one trimmed required string from form data.

    Example: ``_required_text({"question": " Fees? "}, "question")`` returns
    ``"Fees?"``. It rejects blank and non-string values before database work.
    """
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise FaqAdminValidationError(f"{key} is required")
    return value.strip()


def build_new_faq_rows(data):
    """Build validated FAQ rows for one new admin form submission.

    Example: a ``common`` submission returns one row whose ``program_id`` is
    ``common``; a ``diff_answers`` submission returns one row per real programme.
    This function only shapes data. It does not open Postgres or call Ollama.
    """
    category = _required_text(data, "question_category")
    if category not in FAQ_QUESTION_CATEGORIES:
        raise FaqAdminValidationError("Unknown FAQ type")

    question = _required_text(data, "question")
    if category == "diff_answers":
        answers = data.get("answers")
        if not isinstance(answers, dict):
            raise FaqAdminValidationError("All four answers are required")
        return [
            {
                "program_id": program_id,
                "question": question,
                "answer": _required_text(answers, program_id),
                "question_category": category,
            }
            for program_id in REAL_PROGRAM_IDS
        ]

    if category in ("common", "timeline_based"):
        program_id = "common"
    else:
        try:
            program_id = validate_program_id(data.get("program_id"))
        except ValueError as exc:
            raise FaqAdminValidationError("Choose a valid programme") from exc

    return [{
        "program_id": program_id,
        "question": question,
        "answer": _required_text(data, "answer"),
        "question_category": category,
    }]


def find_similar_faqs(question):
    """Return up to five close FAQ questions from every stored programme.

    Example: an AE draft can return a close shared or DS FAQ, because this is
    an admin review rather than a chatbot answer request.
    """
    import httpx
    from chatbot import appconfig
    from pg.faq_api.orm import Faq, create_pg_engine, create_session_factory, session_scope

    question = _required_text({"question": question}, "question")
    response = httpx.post(
        f"{appconfig.faq_ollama_url().rstrip('/')}/api/embeddings",
        json={"model": appconfig.ollama_model(), "prompt": question},
        timeout=60,
    )
    response.raise_for_status()
    embedding = response.json().get("embedding")
    if not isinstance(embedding, list) or len(embedding) != appconfig.embedding_dimension():
        raise RuntimeError("Embedding service returned an invalid vector")

    distance = Faq.embedding.cosine_distance(embedding)
    similarity = (1 - distance).label("similarity")
    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            rows = session.execute(
                select(Faq, similarity)
                .where(Faq.embedding.is_not(None))
                .order_by(distance)
                .limit(5)
            ).all()
    finally:
        engine.dispose()
    return [
        {"id": int(row.id), "question": row.question, "program_id": row.program_id,
         "question_category": row.question_category, "similarity": float(score)}
        for row, score in rows if float(score) >= 0.65
    ]
