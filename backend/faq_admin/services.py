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


def normalize_question(value):
    """Normalize a question for exact duplicate comparison."""
    return " ".join(str(value).lower().split())


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


def build_answers_for_safety_check(data):
    """Return exactly the answers a pending add or update would write.

    Example: adding a different-answer FAQ returns four programme-labelled
    answers; updating only AE returns just the new AE answer. This lets the
    safety check use the same server-side validation as the eventual save.
    """
    action = _required_text(data, "action")
    if action == "add":
        return [
            {"program_id": row["program_id"], "answer": row["answer"]}
            for row in build_new_faq_rows(data)
        ]
    if action != "update":
        raise FaqAdminValidationError("Choose whether to add or update the FAQ")

    from pg.faq_api.orm import Faq, create_pg_engine, create_session_factory, session_scope

    selected_faq_id = data.get("selected_faq_id")
    if not isinstance(selected_faq_id, int) or selected_faq_id < 1:
        raise FaqAdminValidationError("Choose an FAQ to update")

    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            selected_faq = session.get(Faq, selected_faq_id)
            if selected_faq is None:
                raise FaqAdminValidationError("The selected FAQ no longer exists")
            category = selected_faq.question_category
            if category not in FAQ_QUESTION_CATEGORIES:
                raise FaqAdminValidationError("The selected FAQ has no recognised category")
            update = build_faq_update_data(data, category, selected_faq.program_id)
            if category == "diff_answers":
                rows = session.execute(
                    select(Faq).where(
                        Faq.question_category == "diff_answers",
                        Faq.question == selected_faq.question,
                    )
                ).scalars().all()
                if {row.program_id for row in rows} != set(REAL_PROGRAM_IDS) or len(rows) != len(REAL_PROGRAM_IDS):
                    raise FaqAdminValidationError("The selected different-answer FAQ is incomplete")
            return [
                {"program_id": program_id, "answer": answer}
                for program_id, answer in update["answers"].items()
            ]
    finally:
        engine.dispose()


def build_faq_update_data(data, selected_category, selected_program_id):
    """Validate the values that will replace one selected FAQ.

    Example: updating an AE answer in a different-answer FAQ returns only the
    new AE answer. The selected database row decides its category; browser form
    values never decide which stored rows are allowed to change.
    """
    question = _required_text(data, "question")
    if selected_category != "diff_answers":
        return {"question": question, "answers": {selected_program_id: _required_text(data, "answer")}}

    answer_program_id = data.get("answer_program_id")
    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise FaqAdminValidationError("An answer is required")

    if answer_program_id == "all":
        try:
            return {
                "question": question,
                "answers": {
                    program_id: _required_text(answers, program_id)
                    for program_id in REAL_PROGRAM_IDS
                },
            }
        except FaqAdminValidationError as exc:
            raise FaqAdminValidationError("All four answers are required") from exc

    try:
        answer_program_id = validate_program_id(answer_program_id)
    except ValueError as exc:
        raise FaqAdminValidationError("Choose one programme or all programmes") from exc
    return {
        "question": question,
        "answers": {answer_program_id: _required_text(answers, answer_program_id)},
    }


def _question_embedding(question):
    """Generate one validated embedding for a changed FAQ question."""
    import httpx
    from chatbot import appconfig

    response = httpx.post(
        f"{appconfig.faq_ollama_url().rstrip('/')}/api/embeddings",
        json={"model": appconfig.ollama_model(), "prompt": question},
        timeout=60,
    )
    response.raise_for_status()
    embedding = response.json().get("embedding")
    if not isinstance(embedding, list) or len(embedding) != appconfig.embedding_dimension():
        raise RuntimeError("Embedding service returned an invalid vector")
    return embedding


def group_similar_faqs(matches, selected_program):
    """Combine four different-answer rows into one selectable FAQ result.

    Example: the DS, AE, ES, and MG rows for ``What is the Qualifier Exam?``
    become one card. The selected programme's row is used when available, so
    the existing update screen starts with the most relevant programme answer.
    """
    grouped_matches = []
    different_answer_groups = {}
    for match in matches:
        if match["question_category"] != "diff_answers":
            match["has_program_specific_answers"] = False
            grouped_matches.append(match)
            continue

        group = different_answer_groups.setdefault(match["question"], [])
        group.append(match)
        if len(group) != 1:
            continue

        grouped_matches.append(group)

    results = []
    for match in grouped_matches:
        if isinstance(match, dict):
            results.append(match)
            continue

        representative = next(
            (item for item in match if item["program_id"] == selected_program),
            match[0],
        ).copy()
        representative["has_program_specific_answers"] = True
        representative["is_exact"] = any(item["is_exact"] for item in match)
        results.append(representative)
    return results


def find_similar_faqs(question, selected_program):
    """Return up to five close FAQ questions from every stored programme.

    Example: an AE draft can return a close shared or DS FAQ, because this is
    an admin review rather than a chatbot answer request.
    """
    import httpx
    from chatbot import appconfig
    from pg.faq_api.orm import Faq, create_pg_engine, create_session_factory, session_scope

    question = _required_text({"question": question}, "question")
    selected_program = validate_program_id(selected_program)
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
                .limit(20)
            ).all()
    finally:
        engine.dispose()
    normalized_question = normalize_question(question)
    matches = [
        {"id": int(row.id), "question": row.question, "program_id": row.program_id,
         "question_category": row.question_category or "uncategorised",
         "similarity": float(score), "is_exact": (
             normalize_question(row.question) == normalized_question
             and row.program_id in (selected_program, "common")
         )}
        for row, score in rows if float(score) >= 0.65
    ]
    return group_similar_faqs(matches, selected_program)[:5]


def add_new_faq(data):
    """Create validated FAQ rows with one Ollama embedding for their question."""
    from pg.faq_api.orm import Faq, create_pg_engine, create_session_factory, session_scope

    rows = build_new_faq_rows(data)
    embedding = _question_embedding(rows[0]["question"])
    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            saved = []
            for row in rows:
                existing = session.scalar(select(Faq.id).where(Faq.program_id == row["program_id"], Faq.question == row["question"]))
                if existing is not None:
                    raise FaqAdminValidationError("An exact FAQ already exists in this programme")
                faq = Faq(**row, embedding=embedding)
                session.add(faq)
                session.flush()
                saved.append(int(faq.id))
            return saved
    finally:
        engine.dispose()


def get_faq_answer(faq_id):
    """Return the stored question, answer, and labels for one FAQ result.

    Example: ``get_faq_answer(8)`` returns the stored question and answer for
    result card 8. This read-only lookup lets an admin inspect or edit that
    exact FAQ instead of using the wording entered for similarity search.
    """
    from pg.faq_api.orm import Faq, create_pg_engine, create_session_factory, session_scope

    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            faq = session.get(Faq, faq_id)
            if faq is None:
                raise FaqAdminValidationError("The selected FAQ no longer exists")
            return {
                "id": int(faq.id),
                "question": faq.question,
                "answer": faq.answer,
                "program_id": faq.program_id,
                "question_category": faq.question_category or "uncategorised",
            }
    finally:
        engine.dispose()


def _faq_management_row(faq):
    """Return every stored FAQ column in a template-safe plain dictionary.

    Example: an FAQ with id ``8`` becomes a dictionary containing ``id``, its
    programme, question, answer, category, and embedding. The all-FAQs page
    uses this shape so it does not need to know about SQLAlchemy objects.
    """
    embedding = list(faq.embedding) if faq.embedding is not None else None
    return {
        "id": int(faq.id),
        "program_id": faq.program_id,
        "question": faq.question,
        "answer": faq.answer,
        "question_category": faq.question_category,
        "embedding": embedding,
    }


def list_all_faqs():
    """Return every FAQ table row in primary-key order for the admin list.

    Example: the row with primary key ``8`` appears before row ``9``. This is
    intentionally an admin-only full-table view, not a chatbot retrieval path.
    """
    from pg.faq_api.orm import Faq, create_pg_engine, create_session_factory, session_scope

    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            faqs = session.execute(select(Faq).order_by(Faq.id)).scalars().all()
            return [_faq_management_row(faq) for faq in faqs]
    finally:
        engine.dispose()


def get_faq_for_management(faq_id):
    """Return every stored column for one row being edited in the admin list.

    Example: ``get_faq_for_management(8)`` returns row 8 including its primary
    key and embedding, while the edit form only makes question and answer editable.
    """
    from pg.faq_api.orm import Faq, create_pg_engine, create_session_factory, session_scope

    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            faq = session.get(Faq, faq_id)
            if faq is None:
                raise FaqAdminValidationError("The selected FAQ no longer exists")
            return _faq_management_row(faq)
    finally:
        engine.dispose()


def _management_rows_for_selected_faq(session, selected_faq):
    """Return one row, or all four rows when a different-answer group is edited.

    Example: selecting an AE row in a different-answer group returns the DS,
    AE, ES, and MG rows. Keeping them together prevents a changed question from
    splitting one shared question into four inconsistent questions.
    """
    if selected_faq.question_category != "diff_answers":
        return [selected_faq]
    from pg.faq_api.orm import Faq

    return session.execute(
        select(Faq).where(
            Faq.question_category == "diff_answers",
            Faq.question == selected_faq.question,
        )
    ).scalars().all()


def update_faq_from_management(faq_id, question, answer):
    """Update a listed FAQ row and return the primary keys changed.

    Example: editing row 8 changes that row's answer. For a different-answer
    group, its selected programme answer changes while a changed question and
    embedding are applied to the complete group.
    """
    from pg.faq_api.orm import Faq, create_pg_engine, create_session_factory, session_scope

    question = _required_text({"question": question}, "question")
    answer = _required_text({"answer": answer}, "answer")
    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            selected_faq = session.get(Faq, faq_id)
            if selected_faq is None:
                raise FaqAdminValidationError("The selected FAQ no longer exists")

            rows = _management_rows_for_selected_faq(session, selected_faq)
            question_changed = question != selected_faq.question
            embedding = _question_embedding(question) if question_changed else None
            changed_rows = []
            for row in rows:
                if question_changed:
                    row.question = question
                    row.embedding = embedding
                    changed_rows.append(row)
                if row.id == selected_faq.id:
                    row.answer = answer
                    if row not in changed_rows:
                        changed_rows.append(row)
            session.flush()
            return {
                "updated_ids": [int(row.id) for row in changed_rows],
                "question_category": selected_faq.question_category,
            }
    finally:
        engine.dispose()


def delete_faq_from_management(faq_id):
    """Delete one listed FAQ, or its complete different-answer group.

    Example: deleting row 8 normally removes only row 8. If row 8 belongs to
    ``diff_answers``, every stored programme answer for that question is removed
    together so the database cannot retain a partial group.
    """
    from pg.faq_api.orm import Faq, create_pg_engine, create_session_factory, session_scope

    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            selected_faq = session.get(Faq, faq_id)
            if selected_faq is None:
                raise FaqAdminValidationError("The selected FAQ no longer exists")
            rows = _management_rows_for_selected_faq(session, selected_faq)
            deleted_ids = [int(row.id) for row in rows]
            for row in rows:
                session.delete(row)
            session.flush()
            return {
                "deleted_ids": deleted_ids,
                "question_category": selected_faq.question_category,
            }
    finally:
        engine.dispose()


def update_existing_faq(data):
    """Update the FAQ identified by ``selected_faq_id`` and return changed rows.

    Example: selecting one row from a different-answer group and choosing AE
    updates only the group's AE answer. A changed group question and embedding
    are applied to all four rows in one transaction.
    """
    from pg.faq_api.orm import Faq, create_pg_engine, create_session_factory, session_scope

    selected_faq_id = data.get("selected_faq_id")
    if not isinstance(selected_faq_id, int) or selected_faq_id < 1:
        raise FaqAdminValidationError("Choose an FAQ to update")

    engine = create_pg_engine()
    try:
        with session_scope(create_session_factory(engine)) as session:
            selected_faq = session.get(Faq, selected_faq_id)
            if selected_faq is None:
                raise FaqAdminValidationError("The selected FAQ no longer exists")
            category = selected_faq.question_category
            if category not in FAQ_QUESTION_CATEGORIES:
                raise FaqAdminValidationError("The selected FAQ has no recognised category")

            update = build_faq_update_data(data, category, selected_faq.program_id)
            rows = [selected_faq]
            if category == "diff_answers":
                rows = session.execute(
                    select(Faq).where(
                        Faq.question_category == "diff_answers",
                        Faq.question == selected_faq.question,
                    )
                ).scalars().all()
                if {row.program_id for row in rows} != set(REAL_PROGRAM_IDS) or len(rows) != len(REAL_PROGRAM_IDS):
                    raise FaqAdminValidationError("The selected different-answer FAQ is incomplete")

            question_changed = update["question"] != selected_faq.question
            embedding = _question_embedding(update["question"]) if question_changed else None
            updated_rows = []
            for row in rows:
                if question_changed:
                    row.question = update["question"]
                    row.embedding = embedding
                    updated_rows.append(row)
                if row.program_id in update["answers"]:
                    row.answer = update["answers"][row.program_id]
                    if row not in updated_rows:
                        updated_rows.append(row)

            session.flush()
            return {
                "updated_ids": [int(row.id) for row in updated_rows],
                "question_category": category,
                "program_ids": sorted(row.program_id for row in updated_rows),
            }
    finally:
        engine.dispose()
