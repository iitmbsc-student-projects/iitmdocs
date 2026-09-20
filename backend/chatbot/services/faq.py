"""Async FAQ semantic search for Django's request path.

Flow: request an Ollama embedding -> execute the existing pgvector expression
against the shared FAQ model -> convert rows to the existing JSON shape. The
synchronous bootstrap path in ``pg/faq_api`` remains unchanged.

Every read is scoped to one programme. A request for "es" sees `es` rows plus the
shared `common` rows and nothing belonging to ds, mg or ae. The scope rule lives in
programs.py so this async path and the sync bootstrap path cannot drift apart.
"""
from __future__ import annotations


from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from programs import faq_program_scope

from .. import appconfig
from .logs import measure_duration

OLLAMA_TIMEOUT_SECONDS = 60

_async_session_factory = None


class FaqEmbeddingError(Exception):
    """Ollama embedding failed (-> HTTP 502)."""


class FaqDatabaseError(Exception):
    """Postgres query failed (-> HTTP 500)."""

def _get_async_session_factory():
    """Return the process-wide creator for short-lived async FAQ sessions."""
    global _async_session_factory
    if _async_session_factory is None:
        from pg.faq_api.orm import database_url_from_env

        engine = create_async_engine(database_url_from_env(), pool_pre_ping=True)
        _async_session_factory = async_sessionmaker(
            engine,
            autoflush=False,
            expire_on_commit=False,
        )
    return _async_session_factory


async def request_embedding_async(client, text, ollama_url, model):
    """Get one validated FAQ embedding without blocking the event loop.

    Example: an expected dimension of 2 accepts ``[0.1, 0.2]`` and returns
    those values as floats. This is called before every async FAQ search.
    """
    response = await client.post(
        f"{ollama_url.rstrip('/')}/api/embeddings",
        json={"model": model, "prompt": text},
        headers={"Content-Type": "application/json"},
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    if not response.is_success:
        raise RuntimeError(f"Ollama HTTP {response.status_code}")

    embedding = response.json().get("embedding")
    dimension = appconfig.embedding_dimension()
    if not isinstance(embedding, list) or not embedding:
        raise RuntimeError("Ollama returned invalid embedding payload")
    if len(embedding) != dimension:
        raise RuntimeError(
            f"Ollama embedding dimension mismatch: expected {dimension}, got {len(embedding)}"
        )
    return [float(value) for value in embedding]


async def search_async(client, q, k, program_id):
    """Return the closest FAQ rows for one programme, using async Ollama and Postgres.

    Example: search_async(client, "fees", 5, "es") can return `es` and `common` rows,
    never a `ds` one.
    """
    from pg.faq_api.orm import Faq

    try:
        query_vector = await request_embedding_async(
            client,
            q,
            appconfig.faq_ollama_url(),
            appconfig.ollama_model(),
        )
    except Exception as exc:  # noqa: BLE001
        raise FaqEmbeddingError("Embedding service failed") from exc

    try:
        distance = Faq.embedding.cosine_distance(query_vector)
        similarity = (1 - distance).label("cosine_similarity")
        statement = (
            select(Faq, similarity)
            .where(Faq.embedding.is_not(None))
            .where(Faq.program_id.in_(faq_program_scope(program_id)))
            .order_by(distance)
            .limit(k)
        )
        async with _get_async_session_factory()() as session:
            rows = (await session.execute(statement)).all()
    except Exception as exc:  # noqa: BLE001
        raise FaqDatabaseError("Internal error") from exc

    return [
        {
            "id": int(row.id),
            "program_id": row.program_id,
            "question": row.question,
            "answer": row.answer,
            "cosine_similarity": float(score),
        }
        for row, score in rows
    ]


async def search_result_async(client, q, k, program_id):
    """Return async FAQ matches plus the existing pipeline error category."""
    try:
        with measure_duration("pg_faq_search"):
            items = await search_async(client, q, k, program_id)
        return {"items": items, "error": None}
    except FaqEmbeddingError:
        return {"items": [], "error": "pg_faq_embedding_error"}
    except FaqDatabaseError:
        return {"items": [], "error": "pg_faq_database_error"}
    except Exception:  # noqa: BLE001
        return {"items": [], "error": "pg_faq_search_error"}


async def get_faq_async(faq_id, program_id):
    """Look up one FAQ by id, restricted to what `program_id` is allowed to read.

    Example: get_faq_async(42, "es") returns row 42 only if it belongs to `es` or
    `common`; otherwise it returns None, which the view turns into a 404. Without
    the scope, a user of one bot could read another bot's FAQ by guessing an id.
    """
    from pg.faq_api.orm import Faq

    statement = select(Faq).where(
        Faq.id == faq_id,
        Faq.program_id.in_(faq_program_scope(program_id)),
    )
    try:
        async with _get_async_session_factory()() as session:
            row = (await session.execute(statement)).scalar_one_or_none()
    except Exception as exc:
        raise FaqDatabaseError("Internal error") from exc
    if row is None:
        return None
    return {
        "id": int(row.id),
        "program_id": row.program_id,
        "question": row.question,
        "answer": row.answer,
        "cosine_similarity": 1.0,
    }


async def close_async_faq_engine():
    """Dispose the process-wide async PostgreSQL pool during ASGI shutdown."""
    global _async_session_factory
    if _async_session_factory is None:
        return
    engine = _async_session_factory.kw["bind"]
    _async_session_factory = None
    await engine.dispose()
