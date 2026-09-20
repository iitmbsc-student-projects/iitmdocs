from __future__ import annotations

"""
Database action layer for the PG FAQ feature.

This file answers: "What database operations can the rest of the app perform?"

The bootstrap flow in `embed.py` calls these named functions instead of writing
database queries inline, which keeps bootstrap orchestration and database behavior
separated. (The Django request path has its own async equivalents in
`backend/chatbot/services/faq.py`.)

Every read is scoped to one programme: a request for "es" sees `es` rows plus the
shared `common` rows, and nothing from `ds`, `mg` or `ae`. The scope rule itself
lives in programs.py so the sync and async paths cannot drift apart.

The functions here use SQLAlchemy ORM/expression APIs against the `Faq` model:
- direct lookup by id
- semantic search by pgvector cosine distance
- replace all seeded FAQ rows
- find/update missing embeddings
- count rows for bootstrap logs

Return values are small dataclasses rather than raw ORM objects so callers do
not depend on SQLAlchemy session-bound model instances.
"""

from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from programs import faq_program_scope
from pg.faq_api.orm import Faq


@dataclass(frozen=True)
class FaqSearchRow:
    """FAQ row returned by lookup/search operations."""

    id: int
    program_id: str
    question: str
    answer: str
    cosine_similarity: float


@dataclass(frozen=True)
class FaqEmbeddingInput:
    """FAQ row that needs an embedding backfill."""

    id: int
    program_id: str
    question: str


def _to_search_row(faq: Faq, cosine_similarity: float) -> FaqSearchRow:
    return FaqSearchRow(
        id=int(faq.id),
        program_id=faq.program_id,
        question=faq.question,
        answer=faq.answer,
        cosine_similarity=float(cosine_similarity),
    )


def get_faq_by_id(session: Session, faq_id: int, program_id: str) -> Optional[FaqSearchRow]:
    """Fetch one FAQ by id, restricted to what `program_id` is allowed to read.

    Returns None for an id that belongs to another programme, so a user of one bot
    cannot read another bot's FAQ by guessing an id.

    Example: get_faq_by_id(session, 12, "es") returns row 12 only if that row's
    program_id is "es" or "common".
    """

    stmt = select(Faq).where(
        Faq.id == faq_id,
        Faq.program_id.in_(faq_program_scope(program_id)),
    )
    faq = session.scalar(stmt)
    if faq is None:
        return None
    return _to_search_row(faq, 1.0)


def search_faqs_by_embedding(
    session: Session,
    query_embedding: Sequence[float],
    limit: int,
    program_id: str,
) -> list[FaqSearchRow]:
    """Find the FAQs closest to a question, within one programme's scope.

    Computes pgvector cosine distance between the query embedding and every FAQ
    embedding the programme can see, and returns the top-k ordered by similarity
    (highest first).

    Args:
        session: SQLAlchemy session for database access
        query_embedding: Embedding vector of the user's question (1024 floats)
        limit: Maximum number of results to return (e.g., 5)
        program_id: The selected programme; search covers it plus "common"

    Returns:
        list[FaqSearchRow]: Top-k FAQs with similarity scores (1.0 = identical)
    """

    # Distance runs 0..2 (0 = identical). Convert to a similarity for easier display.
    distance = Faq.embedding.cosine_distance(list(query_embedding))
    cosine_similarity = (1 - distance).label("cosine_similarity")

    stmt = (
        select(Faq, cosine_similarity)
        .where(Faq.embedding.is_not(None))
        .where(Faq.program_id.in_(faq_program_scope(program_id)))
        .order_by(distance)
        .limit(limit)
    )

    results: list[FaqSearchRow] = []
    for faq, similarity in session.execute(stmt):
        results.append(_to_search_row(faq, similarity))
    return results


def replace_seed_faqs(session: Session, rows: Sequence[dict]) -> int:
    """Replace the seeded FAQ rows, but only for the programmes present in `rows`.

    Deleting the whole table would mean a partial re-seed silently empties the other
    three bots, so the delete is scoped to the program ids actually being reloaded.

    Example: rows containing only "es" and "common" leave ds, mg and ae untouched.
    """

    program_ids = sorted({row["program_id"] for row in rows})
    if program_ids:
        session.execute(delete(Faq).where(Faq.program_id.in_(program_ids)))

    session.add_all(
        Faq(
            program_id=row["program_id"],
            question=row["question"],
            answer=row["answer"],
        )
        for row in rows
    )
    return len(rows)


def get_faqs_missing_embeddings(session: Session, limit: int) -> list[FaqEmbeddingInput]:
    """Return a deterministic batch of FAQ rows that still need embeddings."""

    stmt = (
        select(Faq.id, Faq.program_id, Faq.question)
        .where(Faq.embedding.is_(None))
        .order_by(Faq.id)
        .limit(limit)
    )
    return [
        FaqEmbeddingInput(id=int(row.id), program_id=row.program_id, question=row.question)
        for row in session.execute(stmt)
    ]


def update_faq_embedding(session: Session, faq_id: int, embedding: Sequence[float]) -> None:
    """Assign a computed embedding vector to a specific FAQ row.
    
    Used by the bootstrap flow to backfill embeddings generated by Ollama.
    Silently returns if FAQ id does not exist (no error raised).
    
    Args:
        session: SQLAlchemy session for database access
        faq_id: The FAQ row to update
        embedding: The embedding vector from Ollama (1024 floats)
    """

    faq = session.get(Faq, faq_id)
    if faq is None:
        return
    faq.embedding = list(embedding)


def count_faqs(session: Session) -> int:
    """Count total FAQ rows in the database.
    
    Used by bootstrap logs to track initial FAQ load. Returns 0 if table is empty.
    
    Args:
        session: SQLAlchemy session for database access
    
    Returns:
        int: Total number of FAQ rows
    """

    return int(session.scalar(select(func.count()).select_from(Faq)) or 0)


def count_faqs_missing_embeddings(session: Session) -> int:
    """Count FAQ rows that lack embeddings (need backfill).
    
    Used by the bootstrap flow to determine how many FAQs still need Ollama embeddings.
    Returns 0 if all FAQs have embeddings.
    
    Args:
        session: SQLAlchemy session for database access
    
    Returns:
        int: Number of FAQ rows with `embedding IS NULL`
    """

    stmt = select(func.count()).select_from(Faq).where(Faq.embedding.is_(None))
    return int(session.scalar(stmt) or 0)
